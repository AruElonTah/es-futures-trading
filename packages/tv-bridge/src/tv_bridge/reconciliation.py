"""Daily reconciliation: TV SPY bars vs Twelve Data SPY bars (MD-10).

Phase 6 Plan 03 scope: runs once per day at 16:10 ET, compares same-instrument
cross-vendor SPY bars (TradingViewDataSource vs TwelveDataSource), and writes
per-divergent-bar audit_log rows with topic='reconciliation_alert'.

BLOCKER 2 fix (from Plan 03):
    An earlier draft cross-compared ES futures volume vs SPY ETF volume using a
    fixed basis ratio (ES_SPY_BASIS_RATIO). That comparison is INVALID because
    volume is not basis-comparable — ES futures and SPY ETF trade on different
    exchanges with different aggregation rules, producing false-positive flood
    alerts every session. The correct comparison is SPY-vs-SPY: both data sources
    are asked to fetch SPY 1m bars, and the divergence is computed directly
    between the two vendor feeds for the same instrument.

WARNING 3 fix (from Plan 03):
    ReconciliationScheduler passes a TradingViewDataSource (from
    packages/trading-core) NOT the shared TVBridge session. TradingViewDataSource
    opens a per-call subprocess so reconciliation does NOT contend with the
    live-drawing TVBridge session.

Security note (T-06-03-04):
    Both DataFrames carry SPY 1m bars from different vendors — same instrument.
    Direct comparison is valid. pandas merge on ts_utc enforces type alignment;
    downstream comparisons use float() coercion; non-numeric data raises TypeError
    before any audit_log write.

Security note (T-06-03-03):
    audit_log is local-only DuckDB + CSV; payload_json is created via json.dumps
    (no string interpolation) and contains only numeric price/volume data.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Coroutine
from datetime import date, datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from trading_core.execution.eod_scheduler import EodScheduler
from trading_core.logging import get_logger
from trading_core.storage.duckdb_store import DuckDBStore
from trading_core.storage.runs import new_run_id

_log = get_logger(__name__)

# MD-10 divergence thresholds.
# NOTE: No ES_SPY_BASIS_RATIO constant — cross-instrument comparison was rejected
# (BLOCKER 2 fix). Both sources fetch SPY so direct comparison is valid.
PRICE_DIVERGENCE_THRESHOLD = 0.0005  # 0.05%
VOLUME_DIVERGENCE_THRESHOLD = 0.05   # 5%

# RTH window in ET: 9:30–16:00 = UTC 14:30–21:00 (EDT, offset -4h)
# ZoneInfo handles DST automatically.
_NY_TZ = ZoneInfo("America/New_York")

# Reconciliation symbol — both sources fetch SPY (same instrument, cross-vendor).
_RECON_SYMBOL = "SPY"
_RECON_TIMEFRAME = "1m"


def _rth_window(trading_date: date) -> tuple[datetime, datetime]:
    """Return (rth_start, rth_end) as tz-aware UTC datetimes for the given date.

    Uses ZoneInfo for DST-correct conversion.
    """
    from datetime import time

    open_et = datetime.combine(trading_date, time(9, 30), tzinfo=_NY_TZ)
    close_et = datetime.combine(trading_date, time(16, 0), tzinfo=_NY_TZ)
    return open_et.astimezone(timezone.utc), close_et.astimezone(timezone.utc)


async def run_reconciliation(
    *,
    tv_source: Any | None,
    twelve_source: Any | None,
    store: DuckDBStore,
    trading_date: date,
) -> int:
    """Compare TV SPY bars vs Twelve Data SPY bars and write divergence audit rows.

    Both sources are asked to fetch SPY 1m bars for the RTH window of
    ``trading_date``. Bars are aligned on ts_utc, and each aligned pair is
    checked for price divergence (> 0.05%) and volume divergence (> 5%).

    For each divergent bar, writes an audit_log row with topic='reconciliation_alert'.
    If either source is unavailable or returns no bars, writes a single
    'reconciliation_skipped' row.

    WARNING 3 fix: tv_source should be a DataSource (TradingViewDataSource), NOT
    the live-drawing TVBridge singleton. This function accepts Any so tests can
    pass mock objects without importing trading_core types.

    BLOCKER 2 fix: No basis-ratio scaling. Both sources fetch SPY — the same
    instrument — so direct numeric comparison of prices and volumes is valid.
    (ES futures volume and SPY ETF volume are NOT comparable and would produce
    false-positive flood alerts daily.)

    Args:
        tv_source: DataSource for TV bars (TradingViewDataSource). None to skip.
        twelve_source: DataSource for Twelve Data bars (TwelveDataSource). None to skip.
        store: DuckDBStore instance for writing audit events.
        trading_date: Calendar date to reconcile (RTH window 9:30–16:00 ET).

    Returns:
        Number of divergent bars found (0 if skipped).
    """
    # Gate 1: missing source → write skipped row and return 0.
    if tv_source is None or twelve_source is None:
        store.write_audit_event(
            event_id=new_run_id(),
            ts_utc=datetime.now(timezone.utc),
            topic="reconciliation_skipped",
            entity_id=trading_date.isoformat(),
            reason_code="missing_source",
            payload_json=json.dumps({
                "tv_source_present": tv_source is not None,
                "twelve_source_present": twelve_source is not None,
            }),
        )
        _log.info(
            "reconciliation.skipped",
            reason="missing_source",
            trading_date=trading_date.isoformat(),
        )
        return 0

    rth_start, rth_end = _rth_window(trading_date)

    # Fetch both sides.
    try:
        tv_df = await tv_source.fetch_bars(
            _RECON_SYMBOL, _RECON_TIMEFRAME, rth_start, rth_end
        )
    except Exception as e:
        _log.warning("reconciliation.tv_fetch_failed", error=repr(e))
        tv_df = pd.DataFrame()

    try:
        twelve_df = await twelve_source.fetch_bars(
            _RECON_SYMBOL, _RECON_TIMEFRAME, rth_start, rth_end
        )
    except Exception as e:
        _log.warning("reconciliation.twelve_fetch_failed", error=repr(e))
        twelve_df = pd.DataFrame()

    # Gate 2: either side returned no bars.
    if tv_df.empty or twelve_df.empty:
        store.write_audit_event(
            event_id=new_run_id(),
            ts_utc=datetime.now(timezone.utc),
            topic="reconciliation_skipped",
            entity_id=trading_date.isoformat(),
            reason_code="no_bars",
            payload_json=json.dumps({
                "tv_bar_count": len(tv_df),
                "twelve_bar_count": len(twelve_df),
            }),
        )
        _log.info(
            "reconciliation.skipped",
            reason="no_bars",
            tv_bars=len(tv_df),
            twelve_bars=len(twelve_df),
        )
        return 0

    # Align on ts_utc.
    merged = tv_df.merge(twelve_df, on="ts_utc", suffixes=("_tv", "_twelve"))

    # Gate 3: no overlapping timestamps.
    if merged.empty:
        store.write_audit_event(
            event_id=new_run_id(),
            ts_utc=datetime.now(timezone.utc),
            topic="reconciliation_skipped",
            entity_id=trading_date.isoformat(),
            reason_code="no_overlap",
            payload_json=json.dumps({
                "tv_bar_count": len(tv_df),
                "twelve_bar_count": len(twelve_df),
            }),
        )
        _log.info("reconciliation.skipped", reason="no_overlap")
        return 0

    divergence_count = 0
    for row in merged.itertuples(index=False):
        ts: datetime = row.ts_utc  # type: ignore[attr-defined]
        # CR-03(a): compare all OHLC fields, not just close.
        open_tv = float(row.open_tv)  # type: ignore[attr-defined]
        open_twelve = float(row.open_twelve)  # type: ignore[attr-defined]
        high_tv = float(row.high_tv)  # type: ignore[attr-defined]
        high_twelve = float(row.high_twelve)  # type: ignore[attr-defined]
        low_tv = float(row.low_tv)  # type: ignore[attr-defined]
        low_twelve = float(row.low_twelve)  # type: ignore[attr-defined]
        close_tv = float(row.close_tv)  # type: ignore[attr-defined]
        close_twelve = float(row.close_twelve)  # type: ignore[attr-defined]
        vol_tv = float(row.volume_tv)  # type: ignore[attr-defined]
        vol_twelve = float(row.volume_twelve)  # type: ignore[attr-defined]

        # Direct comparison — both sides are SPY, no basis adjustment (BLOCKER 2 fix).
        # CR-03(a): check worst-case divergence across all four price fields.
        def _price_pct(a: float, b: float) -> float:
            return abs(a - b) / b if b != 0 else 0.0

        price_pct = max(
            _price_pct(open_tv, open_twelve),
            _price_pct(high_tv, high_twelve),
            _price_pct(low_tv, low_twelve),
            _price_pct(close_tv, close_twelve),
        )

        # CR-03(b): skip volume comparison when both sources report zero volume
        # to avoid false-positive alerts (e.g. pre-market or halted bars).
        if max(vol_tv, vol_twelve) > 0:
            vol_pct = abs(vol_tv - vol_twelve) / max(vol_tv, vol_twelve)
        else:
            vol_pct = 0.0

        if price_pct > PRICE_DIVERGENCE_THRESHOLD:
            reason_code = "price_divergence"
        elif vol_pct > VOLUME_DIVERGENCE_THRESHOLD:
            reason_code = "volume_divergence"
        else:
            continue

        ts_str = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
        store.write_audit_event(
            event_id=new_run_id(),
            ts_utc=ts if isinstance(ts, datetime) else datetime.now(timezone.utc),
            topic="reconciliation_alert",
            entity_id=trading_date.isoformat(),
            reason_code=reason_code,
            payload_json=json.dumps({
                "ts": ts_str,
                "price_pct": float(price_pct),
                "vol_pct": float(vol_pct),
                "source_pair": "tv_spy_vs_twelve_spy",
            }),
        )
        divergence_count += 1
        _log.warning(
            "reconciliation.divergence",
            ts=ts_str,
            reason_code=reason_code,
            price_pct=round(price_pct * 100, 4),
            vol_pct=round(vol_pct * 100, 2),
        )

    _log.info(
        "reconciliation.complete",
        trading_date=trading_date.isoformat(),
        aligned_bars=len(merged),
        divergences=divergence_count,
    )
    return divergence_count


class ReconciliationScheduler:
    """Fires run_reconciliation() at 16:10 ET daily (10 min post-RTH close).

    Wraps EodScheduler — same infinite-loop pattern used for EOD flatten.
    Shutdown: cancel the asyncio.Task returned by asyncio.create_task(scheduler.run()).
    """

    def __init__(
        self,
        *,
        on_reconcile: Callable[[], Coroutine[Any, Any, None]],
        close_time_et: str = "16:10",
    ) -> None:
        """Construct ReconciliationScheduler.

        Args:
            on_reconcile: Async callable with no arguments; called at 16:10 ET.
            close_time_et: Override the fire time (default 16:10 ET).
        """
        self._scheduler = EodScheduler(
            on_flatten=on_reconcile,
            close_time_et=close_time_et,
            lead_seconds=0,
            tz="America/New_York",
        )

    async def run(self) -> None:
        """Main loop — delegates to EodScheduler.run().

        Runs indefinitely; cancelled via asyncio.Task.cancel().
        EodScheduler wraps callbacks in try/except so a single failed
        reconciliation does not stop the loop (T-06-03-05 DoS mitigation).
        """
        await self._scheduler.run()
