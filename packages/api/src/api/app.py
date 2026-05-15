"""FastAPI application shell for the ES Futures Trading System (Phase 1).

This module ships the **minimum** FastAPI surface that proves the
`packages/api` workspace member is importable, depends correctly on
`packages/trading-core`, and is ready for Phase 3 to add the real route
surface (`/bars`, `/backtests`, `WS /stream`, etc. — UI-01).

Phase 1 contract:
- exactly one operator route: ``GET /health``
- module-level FastAPI app instance importable as ``api.app.app``
- imports ``trading_core.config.Settings`` to prove the workspace
  dependency wires correctly (FND-01 success criterion #1)

Adding ANY other endpoint here in Phase 1 is a regression — the
``test_only_health_endpoint_registered`` test in
``packages/api/tests/test_health.py`` will fail and so will the plan-level
``grep -c '@app\\.'`` done-criterion. Real endpoints land in Phase 3.

Local sanity (NOT required by the test suite — TestClient covers the
in-process path)::

    uv run uvicorn api.app:app --host 127.0.0.1 --port 8000 --workers 1
    curl http://127.0.0.1:8000/health
    # -> {"status": "ok", "service": "es-api", "version": "0.1.0"}
"""

from __future__ import annotations

from fastapi import FastAPI

# Module-level Settings instantiation — proves the api -> trading-core
# workspace dependency wires correctly (FND-01 success criterion #1).
# Phase 3 will replace this top-level grab with a DI dependency on the
# FastAPI app, but for Phase 1 the import alone is the proof we need.
from trading_core.config import Settings

__all__ = ["app"]

_settings: Settings = Settings()

app: FastAPI = FastAPI(
    title="ES Futures Trading System API",
    version="0.1.0",
    description=(
        "Phase 1 shell. Only /health is exposed; Phase 3 adds /bars, "
        "/backtests, WS /stream, and the rest of the UI-01 surface."
    ),
)


@app.get("/health")
def health() -> dict[str, str]:
    """Operator liveness check.

    Returns the canonical Phase 1 body. Phase 3+ may extend with adapter
    health (DataSource connectivity, DuckDB ping, audit-log write check)
    but the v1.0 shape is frozen here so the verifier and any external
    monitor can rely on it.
    """
    return {
        "status": "ok",
        "service": "es-api",
        "version": app.version,
    }
