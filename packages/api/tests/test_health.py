"""TestClient integration test for the FastAPI shell + GET /health.

Plan 01-06 Task 1 — proves the workspace import graph (api -> trading_core)
works end-to-end and that the `/health` endpoint is the ONLY route registered
on the Phase 1 shell. Phase 3 owns the real surface (/bars, /backtests,
WS /stream, etc.) — this test guards against accidentally registering more
endpoints than allowed in Phase 1.

# Plan 03-04 expanded the Phase 1 surface — see 03-04-PLAN.md Task 1.
# test_only_health_endpoint_registered has been renamed to
# test_phase3_endpoints_registered and updated to accept the Phase 3 routes.
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


def test_phase3_endpoints_registered() -> None:
    """Phase 1 → Phase 3 → Phase 4 → Phase 5 surface guard: EXACTLY the expected routes.

    Phase 1 shipped only /health. Plan 03-04 adds /bars, /backtests, and
    WS /stream. Plan 04-03 adds /optimizations routes. Plan 05-04 adds
    /positions, /kill, /flatten, /pause (SP-05 risk controls + UI-05 blotter).
    This test is renamed from test_only_health_endpoint_registered
    (Plan 01-06) — the intent (guard against unexpected endpoints) is
    preserved; the assertion is updated for the Phase 5 surface.

    # Plan 03-04 expanded the Phase 1 surface — see 03-04-PLAN.md Task 1.
    # Plan 04-03 adds /optimizations surface — see 04-03-PLAN.md Task 1.
    # Plan 05-04 adds risk controls + blotter — see 05-04-PLAN.md Task 2.
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
    # Phase 5 surface (Plan 03-04 + Plan 03-05 + Plan 04-03 + Plan 05-04):
    #   /backtests, /backtests/{run_id}/equity, /backtests/{run_id}/trades,
    #   /bars, /health, /stream (WS),
    #   /optimizations, /optimizations/{run_id}, /optimizations/{run_id}/results,
    #   /optimizations/{run_id}/heatmap,
    #   /optimizations/{run_id}/results/{result_id}/equity,
    #   /positions, /kill, /flatten, /pause (Phase 5 risk controls + blotter)
    # Phase 6 Plan 02 surface (TV-03, TV-05, TV-07):
    #   /tv/focus, /tv/alerts, /tv/alerts/{alert_id}, /tv/status
    expected = sorted([
        "/backtests",
        "/backtests/{run_id}/equity",
        "/backtests/{run_id}/trades",
        "/bars",
        "/health",
        "/stream",
        "/optimizations",
        "/optimizations/{run_id}",
        "/optimizations/{run_id}/results",
        "/optimizations/{run_id}/heatmap",
        "/optimizations/{run_id}/results/{result_id}/equity",
        "/positions",
        "/kill",
        "/flatten",
        "/pause",
        # Phase 6 Plan 02: TV routes
        "/tv/focus",
        "/tv/alerts",
        "/tv/alerts/{alert_id}",
        "/tv/status",
    ])
    assert user_paths == expected, (
        f"Phase 5 app must expose exactly {expected}; "
        f"found: {user_paths}"
    )


def test_app_imports_trading_core_settings() -> None:
    """FND-01 success-criterion #1: the workspace dep wires correctly.

    The api package depends on trading-core via `[tool.uv.sources] workspace=true`;
    importing Settings inside api/app.py is the proof.

    Implementation note: the api/__init__.py re-exports ``app`` as
    ``from api.app import app`` which makes ``api.app`` resolve to the FastAPI
    instance at the package namespace level. To inspect the underlying module,
    grab it from ``sys.modules`` after the import has been triggered.
    """
    import sys

    import api  # noqa: F401  triggers the re-export

    submodule = sys.modules["api.app"]
    # Module-level _settings IS a Settings instance built at module load
    assert hasattr(submodule, "_settings"), (
        "api.app must instantiate trading_core.config.Settings at module top "
        "to prove the workspace dep wires correctly (FND-01)"
    )
    # And the Settings symbol is in the module namespace (proves the import)
    assert hasattr(submodule, "Settings"), (
        "api.app must import Settings from trading_core.config (FND-01)"
    )
