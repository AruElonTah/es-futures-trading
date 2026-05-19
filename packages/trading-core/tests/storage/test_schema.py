"""Tests that schema.sql DDL creates the Phase 6 tv_overlays and tv_alerts tables.

Task IDs: 06-01-01
"""

from __future__ import annotations

from trading_core.storage.duckdb_store import DuckDBStore


def _make_store() -> DuckDBStore:
    store = DuckDBStore(":memory:")
    store.ensure_schema()
    return store


def test_tv_overlays_table_exists() -> None:
    """After ensure_schema(), SELECT from tv_overlays succeeds and returns the expected columns."""
    store = _make_store()
    cursor = store._conn.execute("SELECT * FROM tv_overlays LIMIT 0")
    cols = [desc[0] for desc in cursor.description]
    assert "overlay_id" in cols
    assert "strategy_id" in cols
    assert "signal_id" in cols
    assert "shape_kind" in cols
    assert "shape_id" in cols
    assert "trading_date" in cols
    assert "created_at" in cols
    assert "deleted_at" in cols
    store.close()


def test_tv_alerts_table_exists() -> None:
    """After ensure_schema(), SELECT from tv_alerts succeeds and returns the expected columns."""
    store = _make_store()
    cursor = store._conn.execute("SELECT * FROM tv_alerts LIMIT 0")
    cols = [desc[0] for desc in cursor.description]
    assert "alert_id" in cols
    assert "strategy_id" in cols
    assert "tv_alert_id" in cols
    assert "condition" in cols
    assert "created_at" in cols
    assert "deleted_at" in cols
    store.close()
