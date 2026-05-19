"""Tests for TV REST routes (Phase 6 Plan 02 Task 3).

Task IDs: 06-02-06, 06-02-07

Real tests:
    - test_tv_focus:            POST /tv/focus returns 202; symbol allowlist enforced; 503 when no bridge
    - test_create_delete_alert: POST /tv/alerts persists tv_alert_id; DELETE /tv/alerts/{id} removes it
    - test_tv_status_when_disconnected: GET /tv/status returns connected=false when bridge disconnected

Plus test_focus_call_sequence is in test_bridge.py (BLOCKER 1 fix).
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from trading_core.events import EventBus
from trading_core.storage.duckdb_store import DuckDBStore


# ---------------------------------------------------------------------------
# Test app factory — mirrors make_test_app pattern from conftest.py
# ---------------------------------------------------------------------------

def _make_tv_test_app(
    db_path: Path,
    bridge_mock: Any = None,
) -> FastAPI:
    """Create a minimal FastAPI test app with TV routes and an injected bridge mock."""
    from fastapi.middleware.cors import CORSMiddleware

    from api.routes import tv as tv_routes
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
        # Inject bridge mock (or None to test 503 path)
        app.state.tv_bridge = bridge_mock
        yield
        app.state.fan_out_task.cancel()
        try:
            await app.state.fan_out_task
        except asyncio.CancelledError:
            pass
        store.close()

    test_app = FastAPI(title="Test TV Routes", version="0.0.1", lifespan=_lifespan)
    test_app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000"],
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        allow_credentials=False,
    )
    test_app.include_router(tv_routes.router)
    return test_app


def _make_bridge_mock(
    is_connected: bool = True,
    focus_side_effect: Any = None,
    create_alert_return: str | None = "tv_alert_test_42",
) -> MagicMock:
    """Build a MagicMock TVBridge with AsyncMock methods."""
    bridge = MagicMock()
    bridge.is_connected = is_connected
    bridge.focus = AsyncMock(side_effect=focus_side_effect)
    bridge.create_alert = AsyncMock(return_value=create_alert_return)
    bridge.delete_alert = AsyncMock(return_value=None)
    return bridge


# ---------------------------------------------------------------------------
# test_tv_focus
# ---------------------------------------------------------------------------

def test_tv_focus(tmp_path: Path) -> None:
    """POST /tv/focus returns 202 Accepted; symbol allowlist enforced; 503 when no bridge."""
    bridge_mock = _make_bridge_mock()
    app = _make_tv_test_app(tmp_path / "t.duckdb", bridge_mock=bridge_mock)

    with TestClient(app) as client:
        # Happy path: valid symbol + date
        resp = client.post("/tv/focus", json={"symbol": "ES", "date": "2024-06-12"})
        assert resp.status_code == 202, f"Expected 202, got {resp.status_code}: {resp.text}"
        body = resp.json()
        assert body["status"] == "accepted"
        assert body["symbol"] == "ES"
        assert body["date"] == "2024-06-12"

        # Invalid symbol returns 422
        resp_invalid = client.post("/tv/focus", json={"symbol": "XYZ", "date": "2024-06-12"})
        assert resp_invalid.status_code == 422, (
            f"Expected 422 for invalid symbol, got {resp_invalid.status_code}"
        )

        # Invalid date returns 422
        resp_bad_date = client.post("/tv/focus", json={"symbol": "ES", "date": "not-a-date"})
        assert resp_bad_date.status_code == 422, (
            f"Expected 422 for invalid date, got {resp_bad_date.status_code}"
        )

    # 503 when bridge is None
    app_no_bridge = _make_tv_test_app(tmp_path / "t2.duckdb", bridge_mock=None)
    with TestClient(app_no_bridge) as client:
        resp_no_bridge = client.post("/tv/focus", json={"symbol": "ES", "date": "2024-06-12"})
        assert resp_no_bridge.status_code == 503, (
            f"Expected 503 when bridge is None, got {resp_no_bridge.status_code}"
        )


# ---------------------------------------------------------------------------
# test_create_delete_alert
# ---------------------------------------------------------------------------

def test_create_delete_alert(tmp_path: Path) -> None:
    """POST /tv/alerts persists tv_alert_id to tv_alerts; DELETE removes it."""
    bridge_mock = _make_bridge_mock(create_alert_return="tv_alert_test_42")
    app = _make_tv_test_app(tmp_path / "t.duckdb", bridge_mock=bridge_mock)

    with TestClient(app) as client:
        # POST /tv/alerts
        resp = client.post(
            "/tv/alerts",
            json={"strategy_id": "orb", "condition": "ES>5500", "message": "ORB long"},
        )
        assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"
        body = resp.json()
        assert "alert_id" in body
        assert body["tv_alert_id"] == "tv_alert_test_42"

        alert_id = body["alert_id"]

        # Verify tv_alerts row exists
        store = app.state.store
        row = store.get_tv_alert_tv_id(alert_id)
        assert row == "tv_alert_test_42", (
            f"Expected tv_alert_id='tv_alert_test_42', got {row!r}"
        )

        # DELETE /tv/alerts/{alert_id}
        resp_del = client.delete(f"/tv/alerts/{alert_id}")
        assert resp_del.status_code == 200, (
            f"Expected 200 on delete, got {resp_del.status_code}: {resp_del.text}"
        )
        del_body = resp_del.json()
        assert del_body["deleted"] == alert_id

        # bridge.delete_alert was called exactly once with tv_alert_id
        bridge_mock.delete_alert.assert_awaited_once_with("tv_alert_test_42")

        # tv_alerts row is now soft-deleted (deleted_at not null)
        deleted_row = store._conn.execute(
            "SELECT deleted_at FROM tv_alerts WHERE alert_id = ?", [alert_id]
        ).fetchone()
        assert deleted_row is not None
        assert deleted_row[0] is not None, "deleted_at should be set after DELETE"


# ---------------------------------------------------------------------------
# test_tv_status_when_disconnected
# ---------------------------------------------------------------------------

def test_tv_status_when_disconnected(tmp_path: Path) -> None:
    """GET /tv/status returns connected=false when bridge.is_connected == False."""
    bridge_mock = _make_bridge_mock(is_connected=False)
    app = _make_tv_test_app(tmp_path / "t.duckdb", bridge_mock=bridge_mock)

    with TestClient(app) as client:
        resp = client.get("/tv/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["connected"] is False
