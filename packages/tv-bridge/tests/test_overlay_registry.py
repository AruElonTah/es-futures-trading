"""Tests for overlay registry writes and cap enforcement (Phase 6 Plan 02 Task 2).

Task IDs: 06-02-04, 06-02-05, 06-04-01

Real tests (Plan 02):
    - test_write_overlay:   direct _record_overlay call produces tv_overlays row
    - test_cap_enforcement: 200-shape cap refuses draw and writes audit_log row

Real tests (Plan 04 — replaces xfail stubs):
    - test_nightly_cleanup: cleanup marks expired rows as deleted_at, calls draw_remove_one
    - test_nightly_cleanup_tolerates_mcp_failure: cleanup still marks rows even on MCP failure
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from trading_core.storage.duckdb_store import DuckDBStore
from trading_core.storage.runs import new_run_id
from tv_bridge import TVBridge
from tv_bridge.cleanup import nightly_cleanup


# ---------------------------------------------------------------------------
# test_write_overlay — direct _record_overlay call writes one tv_overlays row
# ---------------------------------------------------------------------------

def test_write_overlay(in_memory_store: DuckDBStore, mock_settings, mock_bus) -> None:
    """_record_overlay persists exactly one tv_overlays row with correct values."""
    bridge = TVBridge(store=in_memory_store, bus=mock_bus, settings=mock_settings)

    overlay_id = new_run_id()
    strategy_id = "orb_v1"
    signal_id = "sig-test-1"
    shape_kind = "entry_arrow"
    shape_id = "tv_entity_42"
    trading_date = date(2024, 6, 12)

    bridge._record_overlay(
        overlay_id=overlay_id,
        strategy_id=strategy_id,
        signal_id=signal_id,
        shape_kind=shape_kind,
        shape_id=shape_id,
        trading_date=trading_date,
    )

    # Verify exactly one row was written with correct values
    row = in_memory_store._conn.execute(
        "SELECT overlay_id, strategy_id, signal_id, shape_kind, shape_id, trading_date "
        "FROM tv_overlays WHERE overlay_id = ?",
        [overlay_id],
    ).fetchone()

    assert row is not None, "tv_overlays row was not written"
    assert row[0] == overlay_id
    assert row[1] == strategy_id
    assert row[2] == signal_id
    assert row[3] == shape_kind
    assert row[4] == shape_id
    assert str(row[5]) == str(trading_date)  # DuckDB returns date as str or date

    # Verify count_active_overlays picks it up
    count = in_memory_store.count_active_overlays()
    assert count == 1


# ---------------------------------------------------------------------------
# test_cap_enforcement — 200 active overlays blocks further draws
# ---------------------------------------------------------------------------

async def test_cap_enforcement(
    in_memory_store: DuckDBStore,
    mock_settings,
    mock_bus,
    mock_mcp_session,
) -> None:
    """201st draw_shape call is refused; audit_log written; MCP call not made."""
    from trading_core.events import EventBus as RealEventBus

    real_bus = RealEventBus()
    bridge = TVBridge(store=in_memory_store, bus=real_bus, settings=mock_settings)

    # Inject mock session so call_tool would succeed (if not blocked by cap)
    bridge._session = mock_mcp_session

    # Pre-populate 200 active tv_overlays rows
    trading_date = date(2024, 6, 12)
    for i in range(200):
        in_memory_store.write_tv_overlay(
            overlay_id=new_run_id(),
            strategy_id="orb_v1",
            signal_id=f"sig-{i}",
            shape_kind="entry_arrow",
            shape_id=f"tv_entity_{i}",
            trading_date=trading_date,
        )

    # Confirm cap is at 200
    assert in_memory_store.count_active_overlays() == 200

    # Build a fake signal that would trigger drawing
    from trading_core.strategy.models import Signal

    signal = Signal(
        strategy_id="orb_v1",
        strategy_version="1.0",
        ts_utc=datetime(2024, 6, 12, 14, 30, 0, tzinfo=timezone.utc),
        side="long",
        entry=Decimal("5500.00"),
        stop=Decimal("5490.00"),
        target=Decimal("5520.00"),
        size_hint=Decimal("1"),
        signal_id="sig-cap-test",
    )

    # Call _safe_draw_signal directly (not via bus — tests the cap logic directly)
    await bridge._safe_draw_signal(signal)

    # draw_shape should NOT have been called (cap enforced)
    assert mock_mcp_session.call_tool.call_count == 0, (
        f"Expected 0 draw_shape calls (cap enforced), got {mock_mcp_session.call_tool.call_count}"
    )

    # Verify audit_log row was written with topic='tv_draw_refused'
    audit_row = in_memory_store._conn.execute(
        "SELECT topic, reason_code FROM audit_log WHERE topic = 'tv_draw_refused'",
    ).fetchone()
    assert audit_row is not None, "Expected audit_log row with topic='tv_draw_refused'"
    assert audit_row[1] == "shape_cap"

    # count_active_overlays still == 200 (no new shapes drawn)
    assert in_memory_store.count_active_overlays() == 200


# ---------------------------------------------------------------------------
# test_nightly_cleanup — Plan 04 implementation
# ---------------------------------------------------------------------------

async def test_nightly_cleanup(in_memory_store: DuckDBStore) -> None:
    """Nightly cleanup marks expired rows as deleted_at and calls draw_remove_one.

    Pre-populates tv_overlays with 5 rows spanning:
      - today (should NOT be cleaned)
      - today - 3 trading days (should NOT be cleaned; within retention window)
      - today - 7 trading days (should be cleaned)
      - today - 10 trading days (should be cleaned)
      - today - 30 trading days (should be cleaned)

    Asserts:
      - Rows with trading_date < (today - 5 trading days) have non-null deleted_at
      - Recent rows (today, today-3) are untouched
      - count_active_overlays returns the correct remaining count
      - mock_bridge.call_tool was invoked once per cleaned row with
        tool="draw_remove_one" and args={"entity_id": <shape_id>}
    """
    import pandas_market_calendars as mcal
    from datetime import timedelta

    from trading_core.storage.runs import new_run_id as _new_id

    today = date.today()

    # Compute actual trading days ago using the same calendar as cleanup.py
    cal = mcal.get_calendar("CME_Equity")
    schedule = cal.schedule(
        start_date=today - timedelta(days=100),
        end_date=today,
    )
    trading_days = [d.date() for d in schedule.index]

    def _td_ago(n: int) -> date:
        """Return the calendar date n trading days before today."""
        if len(trading_days) > n:
            return trading_days[-(n + 1)]
        return today - timedelta(days=n * 2)

    # Build test rows: (overlay_id, shape_id, trading_date)
    rows_data = [
        (f"ov-today",  "shape-today",  today),
        (f"ov-3d",     "shape-3d",     _td_ago(3)),
        (f"ov-7d",     "shape-7d",     _td_ago(7)),
        (f"ov-10d",    "shape-10d",    _td_ago(10)),
        (f"ov-30d",    "shape-30d",    _td_ago(30)),
    ]

    for overlay_id, shape_id, trading_date in rows_data:
        in_memory_store.write_tv_overlay(
            overlay_id=overlay_id,
            strategy_id="orb_v1",
            signal_id=f"sig-{overlay_id}",
            shape_kind="entry_arrow",
            shape_id=shape_id,
            trading_date=trading_date,
        )

    # Verify all 5 rows are active
    assert in_memory_store.count_active_overlays() == 5

    # Mock bridge: call_tool returns a valid response (non-None = success)
    mock_bridge = AsyncMock()
    mock_bridge.call_tool = AsyncMock(return_value={"success": True})

    # Run cleanup with default retention (5 trading days)
    removed = await nightly_cleanup(
        bridge=mock_bridge,
        store=in_memory_store,
        today=today,
        retention_trading_days=5,
    )

    # The 3 old rows (7d, 10d, 30d) should be cleaned
    assert removed == 3, f"Expected 3 rows removed, got {removed}"

    # Recent rows (today, today-3) should be untouched
    assert in_memory_store.count_active_overlays() == 2, (
        f"Expected 2 active overlays remaining, got {in_memory_store.count_active_overlays()}"
    )

    # Verify deleted_at is set on expired rows
    for overlay_id, shape_id, _ in rows_data[2:]:  # 7d, 10d, 30d
        row = in_memory_store._conn.execute(
            "SELECT deleted_at FROM tv_overlays WHERE overlay_id = ?",
            [overlay_id],
        ).fetchone()
        assert row is not None, f"Row {overlay_id} not found"
        assert row[0] is not None, f"Row {overlay_id} should have deleted_at set"

    # Verify recent rows are NOT deleted
    for overlay_id, _, _ in rows_data[:2]:  # today, today-3
        row = in_memory_store._conn.execute(
            "SELECT deleted_at FROM tv_overlays WHERE overlay_id = ?",
            [overlay_id],
        ).fetchone()
        assert row is not None, f"Row {overlay_id} not found"
        assert row[0] is None, f"Row {overlay_id} should NOT have deleted_at set"

    # Verify draw_remove_one was called once per expired row
    assert mock_bridge.call_tool.call_count == 3, (
        f"Expected 3 draw_remove_one calls, got {mock_bridge.call_tool.call_count}"
    )
    # All calls should be draw_remove_one
    for call in mock_bridge.call_tool.call_args_list:
        assert call.args[0] == "draw_remove_one", (
            f"Expected call_tool('draw_remove_one', ...) but got {call.args[0]!r}"
        )
        assert "entity_id" in call.args[1], (
            f"Expected entity_id in draw_remove_one args, got {call.args[1]!r}"
        )

    # Verify cleanup_completed audit row
    completed_row = in_memory_store._conn.execute(
        "SELECT topic, reason_code FROM audit_log WHERE topic = 'cleanup_completed'",
    ).fetchone()
    assert completed_row is not None, "Expected cleanup_completed audit row"
    assert completed_row[1] == "nightly_cleanup"


async def test_nightly_cleanup_tolerates_mcp_failure(
    in_memory_store: DuckDBStore,
) -> None:
    """Cleanup marks rows as deleted_at even when MCP draw_remove_one fails.

    mock_bridge.call_tool returns None (simulating MCP failure).
    Cleanup should still:
      - Mark all expired rows as deleted_at
      - Write a cleanup_partial audit row per failed draw_remove_one
    """
    today = date.today()

    # Write one old overlay row (30 days ago — definitely outside retention)
    in_memory_store.write_tv_overlay(
        overlay_id="ov-old-1",
        strategy_id="orb_v1",
        signal_id="sig-old-1",
        shape_kind="entry_arrow",
        shape_id="shape-old-1",
        trading_date=today - timedelta(days=30),
    )
    in_memory_store.write_tv_overlay(
        overlay_id="ov-old-2",
        strategy_id="orb_v1",
        signal_id="sig-old-2",
        shape_kind="stop_line",
        shape_id="shape-old-2",
        trading_date=today - timedelta(days=30),
    )

    assert in_memory_store.count_active_overlays() == 2

    # Mock bridge: call_tool returns None (MCP failure)
    mock_bridge = AsyncMock()
    mock_bridge.call_tool = AsyncMock(return_value=None)

    removed = await nightly_cleanup(
        bridge=mock_bridge,
        store=in_memory_store,
        today=today,
        retention_trading_days=5,
    )

    # All rows should still be marked as deleted despite MCP failure
    assert removed == 2, f"Expected 2 rows removed, got {removed}"
    assert in_memory_store.count_active_overlays() == 0

    # Verify cleanup_partial audit rows were written (one per failed draw_remove_one)
    partial_rows = in_memory_store._conn.execute(
        "SELECT COUNT(*) FROM audit_log WHERE topic = 'cleanup_partial'",
    ).fetchone()
    assert partial_rows is not None
    assert partial_rows[0] == 2, (
        f"Expected 2 cleanup_partial audit rows, got {partial_rows[0]}"
    )

    # Verify cleanup_completed audit row
    completed_row = in_memory_store._conn.execute(
        "SELECT topic, reason_code FROM audit_log WHERE topic = 'cleanup_completed'",
    ).fetchone()
    assert completed_row is not None, "Expected cleanup_completed audit row"
