"""Tests for Phase 6 DuckDBStore TV-related methods.

Task IDs: 06-01-02
Tests: write_tv_overlay, count_active_overlays (with deleted), write_tv_alert, get_tv_alert_tv_id,
       mark_tv_alert_deleted, mark_tv_overlay_deleted, list_overlays_older_than
"""

from __future__ import annotations

from datetime import date

from trading_core.storage.duckdb_store import DuckDBStore
from trading_core.storage.runs import new_run_id


def _make_store() -> DuckDBStore:
    store = DuckDBStore(":memory:")
    store.ensure_schema()
    return store


def test_write_tv_overlay_inserts_row() -> None:
    """write_tv_overlay inserts one row; the row is queryable by overlay_id."""
    store = _make_store()
    overlay_id = new_run_id()
    store.write_tv_overlay(
        overlay_id=overlay_id,
        strategy_id="orb",
        signal_id="sig1",
        shape_kind="entry_arrow",
        shape_id="shape_abc",
        trading_date=date(2026, 5, 19),
    )
    count = store._conn.execute(
        "SELECT COUNT(*) FROM tv_overlays WHERE overlay_id = ?", [overlay_id]
    ).fetchone()[0]
    assert count == 1
    store.close()


def test_count_active_overlays_excludes_deleted() -> None:
    """count_active_overlays returns only rows with deleted_at IS NULL."""
    store = _make_store()
    # Write 3 overlays
    ids = [new_run_id() for _ in range(3)]
    for i, oid in enumerate(ids):
        store.write_tv_overlay(
            overlay_id=oid,
            strategy_id="orb",
            signal_id=f"sig{i}",
            shape_kind="stop_line",
            shape_id=f"shape_{i}",
            trading_date=date(2026, 5, 19),
        )
    # Delete one
    store.mark_tv_overlay_deleted(overlay_id=ids[0])
    active = store.count_active_overlays()
    assert active == 2
    store.close()


def test_write_tv_alert_and_get_tv_id() -> None:
    """write_tv_alert persists a row; get_tv_alert_tv_id returns the tv_alert_id."""
    store = _make_store()
    alert_id = new_run_id()
    tv_alert_id = "tv_alert_xyz"
    store.write_tv_alert(
        alert_id=alert_id,
        strategy_id="orb",
        tv_alert_id=tv_alert_id,
        condition="ES above 5500",
    )
    result = store.get_tv_alert_tv_id(alert_id)
    assert result == tv_alert_id
    store.close()


def test_mark_tv_alert_deleted_preserves_tv_id() -> None:
    """mark_tv_alert_deleted sets deleted_at; get_tv_alert_tv_id still returns the value."""
    store = _make_store()
    alert_id = new_run_id()
    tv_alert_id = "tv_alert_abc123"
    store.write_tv_alert(
        alert_id=alert_id,
        strategy_id="orb",
        tv_alert_id=tv_alert_id,
        condition="ES crosses 5400",
    )
    store.mark_tv_alert_deleted(alert_id=alert_id)
    # tv_alert_id still retrievable (we keep history)
    result = store.get_tv_alert_tv_id(alert_id)
    assert result == tv_alert_id
    # deleted_at is set
    row = store._conn.execute(
        "SELECT deleted_at FROM tv_alerts WHERE alert_id = ?", [alert_id]
    ).fetchone()
    assert row is not None
    assert row[0] is not None  # deleted_at was set
    store.close()


def test_get_tv_alert_tv_id_returns_none_for_unknown() -> None:
    """get_tv_alert_tv_id returns None for an alert_id that does not exist."""
    store = _make_store()
    result = store.get_tv_alert_tv_id("nonexistent-id")
    assert result is None
    store.close()


def test_list_overlays_older_than() -> None:
    """list_overlays_older_than returns only active overlays with trading_date < cutoff."""
    store = _make_store()
    # Old overlay (should be included)
    old_id = new_run_id()
    store.write_tv_overlay(
        overlay_id=old_id,
        strategy_id="orb",
        signal_id="sig_old",
        shape_kind="orb_box",
        shape_id="shape_old",
        trading_date=date(2026, 5, 12),  # 7 days ago
    )
    # Recent overlay (should NOT be included)
    recent_id = new_run_id()
    store.write_tv_overlay(
        overlay_id=recent_id,
        strategy_id="orb",
        signal_id="sig_recent",
        shape_kind="entry_arrow",
        shape_id="shape_recent",
        trading_date=date(2026, 5, 18),  # yesterday
    )
    cutoff = date(2026, 5, 15)
    results = store.list_overlays_older_than(cutoff)
    overlay_ids = [r[0] for r in results]
    assert old_id in overlay_ids
    assert recent_id not in overlay_ids
    store.close()
