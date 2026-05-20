"""Phase 7 Plan 01 — RED tests for backend wiring foundations.

Tests:
1. TOPIC_STRATEGY_RELOAD importable from trading_core.events.models
2. StrategyRegistry.reload() returns ORBStrategy for valid YAML
3. StrategyRegistry.reload() raises FileNotFoundError for missing strategy
4. GET /backtests/{run_id} returns 200 with status field for existing run
5. GET /backtests/{run_id} returns 404 for unknown run_id
6. GET /backtests list returns rows with status field present
"""

from __future__ import annotations

import sys
import pathlib
from datetime import datetime, timezone
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# 1. TOPIC_STRATEGY_RELOAD
# ---------------------------------------------------------------------------


def test_topic_strategy_reload_importable():
    """TOPIC_STRATEGY_RELOAD must be importable and equal 'strategy_reload'."""
    from trading_core.events.models import TOPIC_STRATEGY_RELOAD
    assert TOPIC_STRATEGY_RELOAD == "strategy_reload"


# ---------------------------------------------------------------------------
# 2 & 3. StrategyRegistry.reload()
# ---------------------------------------------------------------------------


def test_registry_reload_returns_orb_strategy(tmp_path: Path):
    """reload('orb', dir) returns an ORBStrategy for a valid orb.yaml."""
    from trading_core.strategy.registry import StrategyRegistry
    from trading_core.strategy.orb import ORBStrategy

    # Locate the real orb.yaml in config/strategies/
    # Walk up from this file to find repo root
    here = Path(__file__).resolve()
    repo_root: Path | None = None
    for candidate in [here, *here.parents]:
        if (candidate / "pyproject.toml").exists():
            repo_root = candidate
    assert repo_root is not None, "Could not find repo root"
    strategies_dir = repo_root / "config" / "strategies"
    assert strategies_dir.exists(), f"strategies_dir not found: {strategies_dir}"

    result = StrategyRegistry.reload("orb", strategies_dir)
    assert isinstance(result, ORBStrategy)


def test_registry_reload_raises_file_not_found(tmp_path: Path):
    """reload('nonexistent', dir) raises FileNotFoundError."""
    from trading_core.strategy.registry import StrategyRegistry

    # Use an empty tmp_path as the strategies_dir
    with pytest.raises(FileNotFoundError):
        StrategyRegistry.reload("nonexistent", tmp_path)


# ---------------------------------------------------------------------------
# 4, 5, 6. GET /backtests/{run_id} endpoint
# ---------------------------------------------------------------------------

def _make_test_app(duckdb_path: Path):
    """Delegate to conftest.make_test_app (api/tests pattern)."""
    tests_dir = str(Path(__file__).parent.parent.parent / "api" / "tests")
    if tests_dir not in sys.path:
        sys.path.insert(0, tests_dir)
    import importlib
    _conftest = importlib.import_module("conftest")
    return _conftest.make_test_app(duckdb_path)


def _seed_backtest_row(db_path: Path, run_id: str = "test-run-001") -> None:
    """Insert a minimal backtest row so GET /backtests/{run_id} can find it."""
    from trading_core.storage.duckdb_store import DuckDBStore
    store = DuckDBStore(db_path)
    store.ensure_schema()
    store._conn.execute(
        "INSERT INTO backtests (run_id, strategy_id, symbol, timeframe, from_ts, to_ts, "
        "param_hash, equity_curve_path, total_return, cagr, sharpe, sortino, calmar, "
        "max_dd, max_dd_duration_bars, win_rate, expectancy, profit_factor, "
        "trade_count, avg_hold_bars) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            run_id, "orb-v1", "SPY", "1m",
            datetime(2024, 1, 2, 14, 30, tzinfo=timezone.utc),
            datetime(2024, 1, 2, 21, 0, tzinfo=timezone.utc),
            "abc123", "data/parquet/equity/test.parquet",
            0.05, None, None, None, None, None, None, None, None, None, 5, None,
        ],
    )
    store.close()


def test_get_backtest_by_run_id_returns_200(tmp_path: Path):
    """GET /backtests/{run_id} returns 200 with status field for existing run."""
    from fastapi.testclient import TestClient

    db_path = tmp_path / "t.duckdb"
    _seed_backtest_row(db_path, "test-run-001")

    app = _make_test_app(db_path)
    with TestClient(app) as client:
        response = client.get("/backtests/test-run-001")

    assert response.status_code == 200
    data = response.json()
    assert data["run_id"] == "test-run-001"
    assert "status" in data


def test_get_backtest_by_run_id_returns_404(tmp_path: Path):
    """GET /backtests/{run_id} returns 404 for unknown run_id."""
    from fastapi.testclient import TestClient

    db_path = tmp_path / "t.duckdb"
    # No rows seeded — ensure schema only
    from trading_core.storage.duckdb_store import DuckDBStore
    store = DuckDBStore(db_path)
    store.ensure_schema()
    store.close()

    app = _make_test_app(db_path)
    with TestClient(app) as client:
        response = client.get("/backtests/nonexistent-run-id")

    assert response.status_code == 404


def test_get_backtests_list_includes_status_field(tmp_path: Path):
    """GET /backtests (list) returns rows with 'status' field present."""
    from fastapi.testclient import TestClient

    db_path = tmp_path / "t.duckdb"
    _seed_backtest_row(db_path, "test-run-002")

    app = _make_test_app(db_path)
    with TestClient(app) as client:
        response = client.get("/backtests")

    assert response.status_code == 200
    rows = response.json()
    assert len(rows) >= 1
    assert "status" in rows[0]
