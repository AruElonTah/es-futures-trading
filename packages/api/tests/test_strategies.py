"""Tests for strategies API routes (Plan 07-02 Task 3).

Tests:
    - test_get_strategies_returns_list: GET /strategies returns list with expected fields
    - test_put_strategy_params_200: PUT /strategies/orb/params with valid body returns 200
    - test_put_strategy_params_422: PUT with invalid params (negative) returns 422
    - test_put_strategy_invalid_id: PUT with path-traversal ID returns 400
    - test_post_strategy_toggle: POST /strategies/orb/toggle returns 200 with enabled boolean

Requirements: UI-07 (Strategy Controls panel), D-17 (new API routes), T-07-02-01 (path traversal guard).
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from trading_core.events import EventBus
from trading_core.storage.duckdb_store import DuckDBStore


# ---------------------------------------------------------------------------
# Test app factory
# ---------------------------------------------------------------------------

def _make_strategies_test_app(db_path: Path) -> FastAPI:
    """Minimal FastAPI test app with strategies + risk routes wired."""
    from fastapi.middleware.cors import CORSMiddleware

    from api.routes import strategies as strategies_routes
    from api.ws import ConnectionManager

    @asynccontextmanager
    async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
        store = DuckDBStore(db_path)
        store.ensure_schema()
        app.state.store = store
        bus = EventBus()
        app.state.bus = bus
        manager = ConnectionManager(bus)
        app.state.manager = manager
        app.state.fan_out_task = asyncio.create_task(
            manager.start_background_fan_out()
        )
        yield
        app.state.fan_out_task.cancel()
        try:
            await app.state.fan_out_task
        except asyncio.CancelledError:
            pass
        store.close()

    test_app = FastAPI(lifespan=_lifespan)
    test_app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000"],
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        allow_credentials=False,
    )
    test_app.include_router(strategies_routes.router)
    return test_app


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_get_strategies_returns_list(tmp_path: Path) -> None:
    """GET /strategies returns a list of registered strategies with current params.

    Expected shape:
        [{"strategy_id": "orb-v1", "name": "...", "params": {...}, "enabled": bool}, ...]
    """
    app = _make_strategies_test_app(tmp_path / "test.duckdb")
    with TestClient(app) as client:
        response = client.get("/strategies")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    row = data[0]
    assert "strategy_id" in row
    assert "name" in row
    assert "params" in row
    assert "enabled" in row
    assert isinstance(row["params"], dict)
    assert isinstance(row["enabled"], bool)


def test_put_strategy_params_200(tmp_path: Path) -> None:
    """PUT /strategies/orb/params with valid params returns 200 and updates params."""
    app = _make_strategies_test_app(tmp_path / "test.duckdb")
    with TestClient(app) as client:
        response = client.put(
            "/strategies/orb/params",
            json={"opening_range_minutes": 30, "atr_stop_mult": 2.0, "r_target": 3.0},
        )
    assert response.status_code == 200
    data = response.json()
    assert "strategy_id" in data
    assert "params" in data
    assert data["params"].get("opening_range_minutes") == 30


def test_put_strategy_params_422(tmp_path: Path) -> None:
    """PUT /strategies/orb/params with invalid params returns 422 with detail.

    D-16: server-side Pydantic validation only. Invalid params return 422.
    """
    app = _make_strategies_test_app(tmp_path / "test.duckdb")
    with TestClient(app) as client:
        response = client.put(
            "/strategies/orb/params",
            json={"opening_range_minutes": -1},
        )
    assert response.status_code == 422


def test_put_strategy_invalid_id(tmp_path: Path) -> None:
    """PUT /strategies with invalid strategy_id returns 400 (path traversal blocked).

    T-07-02-01: strategy_id regex ^[a-z0-9_-]+$ must reject IDs with uppercase,
    special chars, or other non-conforming patterns that could lead to path issues.
    """
    app = _make_strategies_test_app(tmp_path / "test.duckdb")
    with TestClient(app) as client:
        # Uppercase is blocked by regex: ^[a-z0-9_-]+$ only allows lowercase
        response = client.put(
            "/strategies/Invalid_ID/params",
            json={"opening_range_minutes": 15},
        )
    assert response.status_code == 400


def test_post_strategy_toggle(tmp_path: Path) -> None:
    """POST /strategies/orb/toggle returns 200 with enabled boolean.

    Toggle should flip enabled state and return the new state.
    """
    app = _make_strategies_test_app(tmp_path / "test.duckdb")
    with TestClient(app) as client:
        response = client.post("/strategies/orb/toggle")
    assert response.status_code == 200
    data = response.json()
    assert "strategy_id" in data
    assert "enabled" in data
    assert isinstance(data["enabled"], bool)
