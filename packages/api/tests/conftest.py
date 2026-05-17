# Plan 01-04+ will import shared fixtures from trading_core.tests via pytest_plugins.
#
# Note: under pytest --import-mode=importlib + no tests/__init__.py (Plan 01-01
# decision #1), `pytest_plugins = ["trading_core.tests.conftest"]` does NOT
# work — trading_core.tests is not an importable Python package. The api tests
# do not currently need any shared fixtures (test_health.py uses TestClient
# directly), so this conftest stays empty for Phase 1. Phase 3 can use the
# `importmode=importlib` sys.path trick (prepending packages/trading-core/tests
# to sys.path) if/when shared fixtures are actually needed.
#
# Plan 03-04: make_test_app factory defined here so test_ws_stream.py can
# import it from conftest without relying on test_routes being importable
# as a module under --import-mode=importlib.
#
# IMPORTANT: WebSocket + WebSocketDisconnect must be imported at module level
# (not inside make_test_app) because FastAPI resolves ws_stream's type hints
# via the handler function's __globals__ (= conftest module globals). When
# `from __future__ import annotations` is active, all annotations become
# forward-reference strings; typing.get_type_hints() resolves them against
# the function's __globals__. If WebSocket is only imported inside the
# make_test_app closure it won't appear in conftest.__dict__, and FastAPI
# will treat `websocket` as an unknown (Query) parameter.

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

# Must be module-level so FastAPI's type-hint resolver finds them in __globals__
from fastapi import FastAPI, WebSocket, WebSocketDisconnect


def make_test_app(duckdb_path: Path) -> FastAPI:
    """Mirror app.py lifespan but accept a custom DuckDB path.

    Shared by test_routes.py and test_ws_stream.py. Exposes /bars,
    /backtests, and /stream so all route tests can use the same factory.
    """
    from fastapi.middleware.cors import CORSMiddleware
    from trading_core.events import EventBus
    from trading_core.storage.duckdb_store import DuckDBStore
    from api.routes import bars as bars_routes, backtests as backtests_routes
    from api.ws import ConnectionManager

    @asynccontextmanager
    async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
        store = DuckDBStore(duckdb_path)
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

    test_app = FastAPI(title="Test API", version="0.0.1", lifespan=_lifespan)
    # Mirror app.py CORS config so TestCORS tests exercise real middleware (T-03-05-02)
    test_app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000"],
        allow_methods=["GET"],
        allow_headers=["*"],
        allow_credentials=False,
    )
    test_app.include_router(bars_routes.router)
    test_app.include_router(backtests_routes.router)

    # NOTE: ws_stream must be defined here (as a closure inside make_test_app)
    # so it captures the correct `test_app` reference. FastAPI resolves the
    # `websocket: WebSocket` type hint via this function's __globals__, which
    # is conftest's module-level namespace. Because WebSocket is imported at
    # module level above, the type hint resolution succeeds.
    @test_app.websocket("/stream")
    async def ws_stream(websocket: WebSocket) -> None:
        from api.ws import ConnectionManager as CM
        manager: CM = websocket.app.state.manager
        q = await manager.connect(websocket)
        try:
            while True:
                msg = await q.get()
                await websocket.send_text(msg)
        except WebSocketDisconnect:
            pass
        finally:
            manager.disconnect(q)

    return test_app
