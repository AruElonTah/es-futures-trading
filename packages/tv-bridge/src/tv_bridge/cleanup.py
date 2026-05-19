"""Nightly overlay cleanup — TV-03.

Phase 6 Plan 04 scope: runs once per day at 03:00 ET, marks tv_overlays rows
with trading_date < (today - 5 trading days) as deleted_at = now(), and
attempts to remove each shape from the live TV chart via draw_remove_one
(best-effort; TV failure tolerated).

Security notes:
    T-06-04-01 (DoS via slow draw_remove_one): each call uses bridge.call_tool
    which already has a 12s timeout (from Plan 02). Cleanup runs off-hours at
    03:00 ET so there is no contention with the live signal pipeline.
    T-06-04-02 (Information disclosure via cleanup audit rows): payload_json
    only contains overlay_id, shape_id, and counts — no price or strategy data.
    T-06-04-06 (Repudiation: cleanup partial failures invisible): every failed
    draw_remove_one writes a topic='cleanup_partial' audit row; the summary
    cleanup_completed row records the total removed count.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Coroutine
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pandas_market_calendars as mcal

from trading_core.execution.eod_scheduler import EodScheduler
from trading_core.logging import get_logger
from trading_core.storage.duckdb_store import DuckDBStore
from trading_core.storage.runs import new_run_id

_log = get_logger(__name__)

DEFAULT_RETENTION_TRADING_DAYS = 5
CLEANUP_FIRE_TIME_ET = "03:00"   # Off-hours — TV Desktop typically not in active use


def _trading_days_ago(today: date, n: int) -> date:
    """Return the calendar date that is ``n`` trading days before ``today``.

    Uses the CME_Equity calendar so weekends and US market holidays are
    correctly skipped. Returns a conservative fallback (today - n*2) if the
    calendar schedule is too short (edge case for very early dates).

    Args:
        today: Reference date (inclusive upper bound).
        n: Number of trading days to look back.

    Returns:
        The calendar date that is exactly n trading days before today.
    """
    cal = mcal.get_calendar("CME_Equity")
    # Look back enough calendar days to guarantee n trading days
    schedule = cal.schedule(start_date=today - timedelta(days=n * 2 + 10), end_date=today)
    trading_days = [d.date() for d in schedule.index]
    if len(trading_days) <= n:
        return today - timedelta(days=n * 2)   # Conservative fallback
    return trading_days[-(n + 1)]              # n-th trading day before today


async def nightly_cleanup(
    *,
    bridge: Any | None,
    store: DuckDBStore,
    today: date | None = None,
    retention_trading_days: int = DEFAULT_RETENTION_TRADING_DAYS,
) -> int:
    """Remove tv_overlays rows older than ``retention_trading_days`` trading days.

    For each expired row:
      1. Attempt to remove the shape from the live TV chart via
         ``bridge.call_tool("draw_remove_one", ...)`` (best-effort; failure tolerated).
      2. If the MCP call fails (returns None), write a ``cleanup_partial`` audit row.
      3. Always mark the DuckDB row as deleted_at = now() regardless of MCP outcome.

    Writes a final ``cleanup_completed`` audit row with the total removed count.

    Args:
        bridge: TVBridge instance (may be None if bridge is unavailable at cleanup time).
        store: DuckDBStore for reading overlay rows and writing audit events.
        today: Override for the current date (used in tests). Defaults to date.today().
        retention_trading_days: Number of trading days to retain overlays. Default 5.

    Returns:
        Number of overlay rows marked as deleted.
    """
    today = today or date.today()
    cutoff = _trading_days_ago(today, retention_trading_days)
    _log.info(
        "cleanup.starting",
        today=today.isoformat(),
        cutoff=cutoff.isoformat(),
        retention_trading_days=retention_trading_days,
    )

    rows = store.list_overlays_older_than(cutoff)
    removed = 0

    for overlay_id, shape_id in rows:
        # Best-effort remove from TV chart; tolerate failure (T-06-04-01)
        if bridge is not None:
            result = await bridge.call_tool("draw_remove_one", {"entity_id": shape_id})
            if result is None:
                # MCP call failed — write audit row for forensic replay (T-06-04-06)
                store.write_audit_event(
                    event_id=new_run_id(),
                    ts_utc=datetime.now(timezone.utc),
                    topic="cleanup_partial",
                    entity_id=overlay_id,
                    reason_code="draw_remove_failed",
                    payload_json=json.dumps({"shape_id": shape_id}),
                )

        # Always mark deleted_at — forensic history preserved (deleted_at != NULL)
        store.mark_tv_overlay_deleted(overlay_id=overlay_id)
        removed += 1

    # Single summary audit row
    store.write_audit_event(
        event_id=new_run_id(),
        ts_utc=datetime.now(timezone.utc),
        topic="cleanup_completed",
        entity_id=today.isoformat(),
        reason_code="nightly_cleanup",
        payload_json=json.dumps({"removed": removed, "cutoff": cutoff.isoformat()}),
    )
    _log.info("cleanup.completed", removed=removed, cutoff=cutoff.isoformat())
    return removed


class NightlyCleanupScheduler:
    """Fires nightly_cleanup() at 03:00 ET daily.

    Wraps EodScheduler — same infinite-loop pattern used for reconciliation
    and EOD flatten.

    Shutdown: cancel the asyncio.Task returned by
    asyncio.create_task(scheduler.run()).
    """

    def __init__(
        self,
        *,
        on_cleanup: Callable[[], Coroutine[Any, Any, None]],
        fire_time_et: str = CLEANUP_FIRE_TIME_ET,
    ) -> None:
        """Construct NightlyCleanupScheduler.

        Args:
            on_cleanup: Async callable with no arguments; called at fire_time_et each day.
            fire_time_et: Override the fire time (default "03:00" ET).
        """
        self._scheduler = EodScheduler(
            on_flatten=on_cleanup,
            close_time_et=fire_time_et,
            lead_seconds=0,
            tz="America/New_York",
        )

    async def run(self) -> None:
        """Main loop — delegates to EodScheduler.run().

        Runs indefinitely; cancelled via asyncio.Task.cancel().
        EodScheduler wraps the callback in try/except so a single failed
        cleanup does not stop the loop.
        """
        await self._scheduler.run()
