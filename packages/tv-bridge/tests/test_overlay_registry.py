"""Tests for overlay registry writes and cap enforcement (Phase 6 Plan 02 Task 2).

Task IDs: 06-02-04, 06-02-05, 06-04-01

Real tests (Plan 02):
    - test_write_overlay:   direct _record_overlay call produces tv_overlays row
    - test_cap_enforcement: 200-shape cap refuses draw and writes audit_log row

Xfail stubs (Plan 04):
    - test_nightly_cleanup
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from trading_core.storage.duckdb_store import DuckDBStore
from trading_core.storage.runs import new_run_id
from tv_bridge import TVBridge


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
# Xfail stub (Plan 04)
# ---------------------------------------------------------------------------

@pytest.mark.xfail(reason="implemented in Plan 04", strict=True)
def test_nightly_cleanup(in_memory_store: DuckDBStore) -> None:
    """Nightly cleanup removes tv_overlays rows older than 5 trading days."""
    pytest.fail("Plan 04 implements")
