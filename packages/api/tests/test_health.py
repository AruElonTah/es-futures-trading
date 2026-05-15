"""TestClient integration test for the FastAPI shell + GET /health.

Plan 01-06 Task 1 — proves the workspace import graph (api -> trading_core)
works end-to-end and that the `/health` endpoint is the ONLY route registered
on the Phase 1 shell. Phase 3 owns the real surface (/bars, /backtests,
WS /stream, etc.) — this test guards against accidentally registering more
endpoints than allowed in Phase 1.
"""

from __future__ import annotations

import pytest


def test_health_endpoint_returns_200_and_canonical_body() -> None:
    """`GET /health` returns 200 with the exact contract body."""
    # Imported inside the test (not at module top) so import-time errors
    # surface as a test failure rather than a collection error.
    from fastapi.testclient import TestClient

    from api.app import app

    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "es-api",
        "version": "0.1.0",
    }


def test_app_is_a_fastapi_instance() -> None:
    """`api.app.app` must be a FastAPI instance (proves the import graph)."""
    from api.app import app

    assert type(app).__name__ == "FastAPI"


def test_only_health_endpoint_registered() -> None:
    """T-01-06-01 mitigation: Phase 1 ships ONLY /health.

    Phase 3 owns /bars, /backtests, WS /stream. Adding a second app.get/post
    here in Phase 1 is a regression — guard with this test.
    """
    from api.app import app

    # Routes can include the auto-registered /openapi.json + /docs + /redoc
    # default endpoints that FastAPI always installs. Filter to user routes
    # only by checking against the canonical set FastAPI auto-registers.
    DEFAULT_FASTAPI_PATHS = {
        "/openapi.json",
        "/docs",
        "/docs/oauth2-redirect",
        "/redoc",
    }
    user_paths = sorted(
        {
            route.path  # type: ignore[attr-defined]
            for route in app.routes
            if hasattr(route, "path")
            and getattr(route, "path", None) not in DEFAULT_FASTAPI_PATHS
        }
    )
    assert user_paths == ["/health"], (
        f"Phase 1 shell must expose ONLY /health; found: {user_paths}"
    )


def test_app_imports_trading_core_settings() -> None:
    """FND-01 success-criterion #1: the workspace dep wires correctly.

    The api package depends on trading-core via `[tool.uv.sources] workspace=true`;
    importing Settings inside api/app.py is the proof.
    """
    import api.app as app_module

    # Module-level _settings is a Settings instance (or the Settings class is
    # importable from app_module's namespace at minimum).
    assert hasattr(app_module, "_settings") or hasattr(app_module, "Settings")
