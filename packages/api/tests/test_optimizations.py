"""GET /optimizations routes — Phase 4 Plan 03 Task 1 tests (TDD RED).

Tests:
  - test_get_optimizations_empty: empty DB returns 200 + []
  - test_get_opt_results_unknown_run: unknown run_id returns 200 + []
  - test_heatmap_invalid_axis: non-whitelisted axis returns 422
  - test_heatmap_valid_shape: seeded 3x3 grid produces {x, y, z} 2D response
  - test_get_optimizations_returns_list: seeded opt_run row appears in list
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helper: build a test app that includes the optimizations router
# ---------------------------------------------------------------------------

def _make_test_app_with_opts(duckdb_path: Path):
    """Build a test FastAPI app with optimizations router registered.

    Mirrors conftest.make_test_app but also includes optimizations_routes.
    Inline factory because --import-mode=importlib prevents pytest conftest
    from being imported as a module (Plan 01-01 decision #1).
    """
    import asyncio
    from collections.abc import AsyncIterator
    from contextlib import asynccontextmanager

    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from trading_core.storage.duckdb_store import DuckDBStore
    from api.routes import optimizations as optimizations_routes

    @asynccontextmanager
    async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
        store = DuckDBStore(duckdb_path)
        store.ensure_schema()
        app.state.store = store
        yield
        store.close()

    test_app = FastAPI(title="Test Opt API", version="0.0.1", lifespan=_lifespan)
    test_app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000"],
        allow_methods=["GET"],
        allow_headers=["*"],
        allow_credentials=False,
    )
    test_app.include_router(optimizations_routes.router)
    return test_app


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------

def _seed_opt_run(store, run_id: str = "run-001") -> None:
    """Insert a minimal opt_runs row for testing."""
    store._conn.execute(
        """
        INSERT INTO opt_runs (
            run_id, strategy_id, adr_hash, param_grid_hash,
            is_window_months, oos_window_months, step_months, seed,
            fold_count, completed_combos, total_combos, status
        ) VALUES (?, 'orb', 'hash-adr', 'hash-grid',
                  6, 1, 1, 42, 3, 9, 9, 'complete')
        """,
        [run_id],
    )


def _seed_opt_results_3x3(store, run_id: str = "run-001") -> None:
    """Insert a 3x3 grid of opt_results rows (opening_range_minutes x atr_stop_mult)."""
    from uuid import uuid4

    orm_values = [5, 10, 15]
    atr_values = [1.0, 1.5, 2.0]
    fold_idx = 0
    rows = []
    for orm in orm_values:
        for atr in atr_values:
            rows.append({
                "result_id": str(uuid4()),
                "run_id": run_id,
                "fold_idx": fold_idx,
                "param_hash": f"hash-{orm}-{atr}",
                "opening_range_minutes": orm,
                "atr_stop_mult": atr,
                "r_target": 2.0,
                "is_sharpe": 1.0,
                "oos_sharpe": 0.5 + orm * 0.01 + atr * 0.01,
                "is_return": 0.05,
                "oos_return": 0.02,
                "edge_ratio": 2.0,
                "equity_curve_path": None,
                "git_sha": "abc1234",
                "data_hash": "data-hash",
                "seed": 42,
            })
    store.write_opt_results(rows)


# ---------------------------------------------------------------------------
# Tests: GET /optimizations
# ---------------------------------------------------------------------------

class TestGetOptimizationsList:
    def test_get_optimizations_empty(self, tmp_path: Path) -> None:
        """Empty DB returns HTTP 200 with empty list."""
        app = _make_test_app_with_opts(tmp_path / "t.duckdb")
        with TestClient(app) as client:
            response = client.get("/optimizations")
        assert response.status_code == 200
        assert response.json() == []

    def test_get_optimizations_returns_list(self, tmp_path: Path) -> None:
        """Seeded opt_runs row appears in the list with expected run_id."""
        from trading_core.storage.duckdb_store import DuckDBStore

        db_path = tmp_path / "t.duckdb"
        store = DuckDBStore(db_path)
        store.ensure_schema()
        _seed_opt_run(store, run_id="test-run-99")
        store.close()

        app = _make_test_app_with_opts(db_path)
        with TestClient(app) as client:
            response = client.get("/optimizations")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["run_id"] == "test-run-99"
        assert data[0]["strategy_id"] == "orb"
        assert data[0]["status"] == "complete"


# ---------------------------------------------------------------------------
# Tests: GET /optimizations/{run_id}/results
# ---------------------------------------------------------------------------

class TestGetOptResults:
    def test_get_opt_results_unknown_run(self, tmp_path: Path) -> None:
        """Unknown run_id returns 200 + empty list (not 404)."""
        app = _make_test_app_with_opts(tmp_path / "t.duckdb")
        with TestClient(app) as client:
            response = client.get("/optimizations/nonexistent-id/results")
        assert response.status_code == 200
        assert response.json() == []

    def test_get_opt_results_returns_sorted_rows(self, tmp_path: Path) -> None:
        """Seeded rows are returned sorted by oos_sharpe DESC."""
        from trading_core.storage.duckdb_store import DuckDBStore

        db_path = tmp_path / "t.duckdb"
        store = DuckDBStore(db_path)
        store.ensure_schema()
        _seed_opt_run(store)
        _seed_opt_results_3x3(store)
        store.close()

        app = _make_test_app_with_opts(db_path)
        with TestClient(app) as client:
            response = client.get("/optimizations/run-001/results")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 9
        sharpes = [row["oos_sharpe"] for row in data]
        assert sharpes == sorted(sharpes, reverse=True)


# ---------------------------------------------------------------------------
# Tests: GET /optimizations/{run_id}/heatmap
# ---------------------------------------------------------------------------

class TestGetHeatmap:
    def test_heatmap_invalid_axis_x(self, tmp_path: Path) -> None:
        """Non-whitelisted axis_x returns 422 Unprocessable Entity."""
        app = _make_test_app_with_opts(tmp_path / "t.duckdb")
        with TestClient(app) as client:
            response = client.get(
                "/optimizations/test-id/heatmap"
                "?axis_x=evil&axis_y=atr_stop_mult"
            )
        assert response.status_code == 422
        body = response.json()
        # Detail should mention "Invalid axis" or "Allowed"
        detail_str = str(body)
        assert "evil" in detail_str or "Invalid" in detail_str or "Allowed" in detail_str

    def test_heatmap_invalid_axis_y(self, tmp_path: Path) -> None:
        """Non-whitelisted axis_y returns 422 Unprocessable Entity."""
        app = _make_test_app_with_opts(tmp_path / "t.duckdb")
        with TestClient(app) as client:
            response = client.get(
                "/optimizations/test-id/heatmap"
                "?axis_x=opening_range_minutes&axis_y=__import__"
            )
        assert response.status_code == 422

    def test_heatmap_empty_run_returns_empty_shape(self, tmp_path: Path) -> None:
        """Run with no results returns {x: [], y: [], z: []}."""
        app = _make_test_app_with_opts(tmp_path / "t.duckdb")
        with TestClient(app) as client:
            response = client.get(
                "/optimizations/test-id/heatmap"
                "?axis_x=opening_range_minutes&axis_y=atr_stop_mult"
            )
        assert response.status_code == 200
        data = response.json()
        assert data == {"x": [], "y": [], "z": []}

    def test_heatmap_valid_shape(self, tmp_path: Path) -> None:
        """3x3 grid produces correct 2D shape: len(z)==len(y), len(z[0])==len(x)."""
        from trading_core.storage.duckdb_store import DuckDBStore

        db_path = tmp_path / "t.duckdb"
        store = DuckDBStore(db_path)
        store.ensure_schema()
        _seed_opt_run(store)
        _seed_opt_results_3x3(store)
        store.close()

        app = _make_test_app_with_opts(db_path)
        with TestClient(app) as client:
            response = client.get(
                "/optimizations/run-001/heatmap"
                "?axis_x=opening_range_minutes&axis_y=atr_stop_mult"
            )

        assert response.status_code == 200
        data = response.json()
        assert "x" in data and "y" in data and "z" in data
        assert len(data["z"]) == len(data["y"])
        assert len(data["z"]) > 0
        assert len(data["z"][0]) == len(data["x"])


# ---------------------------------------------------------------------------
# Tests: GET /optimizations/{run_id}
# ---------------------------------------------------------------------------

class TestGetOptimizationById:
    def test_get_opt_run_not_found(self, tmp_path: Path) -> None:
        """Unknown run_id returns 404."""
        app = _make_test_app_with_opts(tmp_path / "t.duckdb")
        with TestClient(app) as client:
            response = client.get("/optimizations/nonexistent-id")
        assert response.status_code == 404

    def test_get_opt_run_found(self, tmp_path: Path) -> None:
        """Seeded opt_run is returned with expected fields."""
        from trading_core.storage.duckdb_store import DuckDBStore

        db_path = tmp_path / "t.duckdb"
        store = DuckDBStore(db_path)
        store.ensure_schema()
        _seed_opt_run(store, run_id="specific-run")
        store.close()

        app = _make_test_app_with_opts(db_path)
        with TestClient(app) as client:
            response = client.get("/optimizations/specific-run")

        assert response.status_code == 200
        data = response.json()
        assert data["run_id"] == "specific-run"
        assert "completed_combos" in data
        assert "total_combos" in data
