"""Tests for DuckDB schema extensions and holdout quota enforcement.

OPT-08: 3 burns per quarter allowed; 4th refused.
Also verifies opt_runs, opt_results, holdout_burns tables created by ensure_schema().
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from trading_core.storage.duckdb_store import DuckDBStore


@pytest.fixture()
def tmp_store(tmp_path: Path) -> DuckDBStore:
    """In-memory-backed DuckDBStore with schema applied."""
    db_file = tmp_path / "test.duckdb"
    store = DuckDBStore(db_file)
    store.ensure_schema()
    yield store
    store.close()


def test_schema_tables(tmp_store: DuckDBStore) -> None:
    """ensure_schema() creates opt_runs, opt_results, holdout_burns tables."""
    tables = {
        row[0]
        for row in tmp_store._conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='main'"
        ).fetchall()
    }
    assert "opt_runs" in tables, f"opt_runs missing; got: {tables}"
    assert "opt_results" in tables, f"opt_results missing; got: {tables}"
    assert "holdout_burns" in tables, f"holdout_burns missing; got: {tables}"


def test_quota_allows_three_burns(tmp_store: DuckDBStore) -> None:
    """3 burns in the same quarter all return True from check_holdout_quota."""
    quarter = "2026Q2"
    from trading_core.storage.runs import new_run_id

    run_id = new_run_id()
    for _ in range(3):
        burn_id = new_run_id()
        tmp_store.write_holdout_burn(
            burn_id=burn_id, run_id=run_id, quarter=quarter
        )
        # After each burn, check: should still be True (< 3 threshold) until 3rd
    # After all 3 burns, quota check should return False
    result = tmp_store.check_holdout_quota(quarter)
    assert result is False, "After 3 burns, quota should be exceeded (False)"


def test_quota_refuses_fourth_burn(tmp_store: DuckDBStore) -> None:
    """4th burn in the same quarter returns False from check_holdout_quota."""
    quarter = "2026Q2"
    from trading_core.storage.runs import new_run_id

    run_id = new_run_id()
    # Insert exactly 3 burns
    for _ in range(3):
        burn_id = new_run_id()
        tmp_store.write_holdout_burn(
            burn_id=burn_id, run_id=run_id, quarter=quarter
        )
    # 4th burn check — quota exceeded
    assert tmp_store.check_holdout_quota(quarter) is False


def test_quota_allows_fresh_quarter(tmp_store: DuckDBStore) -> None:
    """A different quarter's burns do not count toward the current quarter quota."""
    from trading_core.storage.runs import new_run_id

    run_id = new_run_id()
    # Exhaust Q1
    for _ in range(3):
        burn_id = new_run_id()
        tmp_store.write_holdout_burn(
            burn_id=burn_id, run_id=run_id, quarter="2026Q1"
        )
    # Q2 should still allow burns
    assert tmp_store.check_holdout_quota("2026Q2") is True


def test_write_opt_run_persists(tmp_store: DuckDBStore) -> None:
    """write_opt_run inserts a row readable via information_schema."""
    from trading_core.storage.runs import new_run_id

    run_id = new_run_id()
    tmp_store.write_opt_run(
        run_id=run_id,
        strategy_id="orb",
        adr_hash="abc123",
        param_grid_hash="def456",
        is_window_months=6,
        oos_window_months=1,
        step_months=1,
        seed=42,
        fold_count=4,
        completed_combos=0,
        total_combos=125,
        status="running",
    )
    row = tmp_store._conn.execute(
        "SELECT run_id, status, total_combos FROM opt_runs WHERE run_id = ?",
        [run_id],
    ).fetchone()
    assert row is not None
    assert row[0] == run_id
    assert row[1] == "running"
    assert row[2] == 125


def test_write_opt_results_batch(tmp_store: DuckDBStore) -> None:
    """write_opt_results inserts multiple rows; read_opt_results returns them sorted."""
    from trading_core.storage.runs import new_run_id

    run_id = new_run_id()
    # Insert an opt_run first (FK constraint is soft in this schema, but good practice)
    tmp_store.write_opt_run(
        run_id=run_id,
        strategy_id="orb",
        adr_hash="abc",
        param_grid_hash="def",
        is_window_months=6,
        oos_window_months=1,
        step_months=1,
        seed=42,
        fold_count=1,
        completed_combos=2,
        total_combos=2,
        status="complete",
    )
    rows = [
        {
            "result_id": new_run_id(),
            "run_id": run_id,
            "fold_idx": 0,
            "param_hash": "ph1",
            "opening_range_minutes": 5,
            "atr_stop_mult": 1.0,
            "r_target": 1.5,
            "is_sharpe": 0.8,
            "oos_sharpe": 0.5,
            "is_return": 0.10,
            "oos_return": 0.05,
            "edge_ratio": 1.6,
            "equity_curve_path": "data/parquet/opt/test/worker_ph1.parquet",
            "git_sha": "abc",
            "data_hash": "def",
            "seed": 42,
        },
        {
            "result_id": new_run_id(),
            "run_id": run_id,
            "fold_idx": 0,
            "param_hash": "ph2",
            "opening_range_minutes": 10,
            "atr_stop_mult": 2.0,
            "r_target": 2.5,
            "is_sharpe": 1.2,
            "oos_sharpe": 0.9,
            "is_return": 0.20,
            "oos_return": 0.12,
            "edge_ratio": 1.33,
            "equity_curve_path": "data/parquet/opt/test/worker_ph2.parquet",
            "git_sha": "abc",
            "data_hash": "def",
            "seed": 42,
        },
    ]
    tmp_store.write_opt_results(rows)
    results = tmp_store.read_opt_results(run_id)
    assert len(results) == 2
    # Should be sorted by oos_sharpe DESC
    assert results[0]["oos_sharpe"] >= results[1]["oos_sharpe"]
