"""FastAPI application for the ES Futures Trading System.

Phase 1 shipped only GET /health. Phase 3 (Plan 03-04) adds the full UI-01
REST + WebSocket surface:
  - GET /bars   — D-07 cold-load; most-recent N bars from DuckDB
  - GET /backtests — D-01 backtest run listing
  - WS /stream  — D-04/D-05/D-06 EventBus mirror with {type,payload} envelope

Phase 1 contract (preserved):
- ``GET /health`` returns the canonical body unchanged
- Module-level ``_settings: Settings = Settings()`` proves the api -> trading-core
  workspace dependency wires correctly (FND-01 success criterion #1)

Adding any endpoint here in Phase 1 was a regression.
Phase 3 adds /bars, /backtests, WS /stream as the UI-01 surface.

Local sanity (NOT required by the test suite — TestClient covers the
in-process path)::

    uv run uvicorn api.app:app --host 127.0.0.1 --port 8000 --workers 1
    curl http://127.0.0.1:8000/health
    # -> {"status": "ok", "service": "es-api", "version": "0.1.0"}
    curl "http://127.0.0.1:8000/bars?symbol=SPY&tf=1m&limit=10"
    curl http://127.0.0.1:8000/backtests
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

# Module-level Settings instantiation — proves the api -> trading-core
# workspace dependency wires correctly (FND-01 success criterion #1).
from trading_core.config import Settings
from trading_core.events import EventBus
from trading_core.storage.duckdb_store import DuckDBStore

from api.routes import backtests as backtests_routes
from api.routes import bars as bars_routes
from api.ws import ConnectionManager

__all__ = ["app"]

_settings: Settings = Settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage DuckDBStore, EventBus, and ConnectionManager lifetime.

    On startup:
      - Open and schema-ensure the DuckDB database
      - Create the in-process EventBus
      - Create the ConnectionManager and start the background fan-out task

    On shutdown:
      - Cancel the fan-out task (raises CancelledError, caught cleanly)
      - Close the DuckDB connection
    """
    app.state.store = DuckDBStore(_settings.duckdb_path)
    app.state.store.ensure_schema()
    app.state.bus = EventBus()
    app.state.manager = ConnectionManager(app.state.bus)
    app.state.fan_out_task = asyncio.create_task(
        app.state.manager.start_background_fan_out()
    )
    yield
    app.state.fan_out_task.cancel()
    try:
        await app.state.fan_out_task
    except asyncio.CancelledError:
        pass
    app.state.store.close()


app: FastAPI = FastAPI(
    title="ES Futures Trading System API",
    version="0.1.0",
    description=(
        "Phase 3 surface: GET /bars (D-07 cold-load), GET /backtests (D-01), "
        "WS /stream (D-04/D-05/D-06 EventBus mirror). "
        "Phase 1 GET /health preserved."
    ),
    lifespan=lifespan,
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


app.include_router(bars_routes.router)
app.include_router(backtests_routes.router)


@app.websocket("/stream")
async def ws_stream(websocket: WebSocket) -> None:
    """WebSocket endpoint — D-04/D-05/D-06 EventBus fan-out.

    On connect: allocate a per-client asyncio.Queue via ConnectionManager.
    Main loop: drain the queue and forward JSON messages to the client.
    On disconnect (WebSocketDisconnect): remove the queue and exit cleanly.
    """
    manager: ConnectionManager = websocket.app.state.manager
    q = await manager.connect(websocket)
    try:
        while True:
            msg = await q.get()
            await websocket.send_text(msg)
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(q)
