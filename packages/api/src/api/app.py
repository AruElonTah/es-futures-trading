"""FastAPI application for the ES Futures Trading System.

Phase 1 shipped only GET /health. Phase 3 (Plan 03-04) adds the full UI-01
REST + WebSocket surface:
  - GET /bars   — D-07 cold-load; most-recent N bars from DuckDB
  - GET /backtests — D-01 backtest run listing
  - WS /stream  — D-04/D-05/D-06 EventBus mirror with {type,payload} envelope

Phase 5 (Plan 05-04) adds:
  - GET /positions — UI-05 blotter data source (enriched with point_value, FND-06)
  - POST /kill     — SP-05 kill switch (D-10)
  - POST /flatten  — SP-05 flatten command (D-12)
  - POST /pause    — toggle engine pause/resume
  - CORS POST allowed (previously GET only)
  - FullRiskManager singleton bootstrapped from config/risk.yaml on startup
  - HWM loaded from yesterday's DuckDB risk_state row (D-08 / RM-05)
  - kill-switch asyncio.Event bootstrapped from DuckDB engine_state (D-10)
  - Wall-clock EOD scheduler asyncio task (RM-07)

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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

# Module-level Settings instantiation — proves the api -> trading-core
# workspace dependency wires correctly (FND-01 success criterion #1).
from trading_core.config import Settings
from trading_core.events import EventBus
from trading_core.logging import get_logger
from trading_core.storage.duckdb_store import DuckDBStore
from trading_core.storage.runs import new_run_id

from api.routes import backtests as backtests_routes
from api.routes import bars as bars_routes
from api.routes import optimizations as optimizations_routes
from api.routes import risk as risk_routes
from api.routes import strategies as strategies_routes
from api.routes import tv as tv_routes
from api.ws import ConnectionManager

__all__ = ["app"]

_settings: Settings = Settings()
_log = get_logger(__name__)


def _find_repo_root(start: Path) -> Path:
    """Walk upward from *start* to the outermost directory containing pyproject.toml.

    Continues past inner package pyproject.toml files to find the true repo root.
    Reused from backtests.py (WR-001 pattern).
    """
    found: Path | None = None
    for candidate in [start, *start.parents]:
        if (candidate / "pyproject.toml").exists():
            found = candidate
    if found is None:
        raise RuntimeError(f"Could not locate repo root from {start}")
    return found


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage DuckDBStore, EventBus, ConnectionManager, FullRiskManager, and EodScheduler.

    On startup:
      - Open and schema-ensure the DuckDB database
      - Create the in-process EventBus
      - Create the ConnectionManager and start the background fan-out task
      - Load FullRiskManager from config/risk.yaml; bootstrap HWM + kill-state from DuckDB
      - Start the wall-clock EOD scheduler asyncio task (RM-07)

    On shutdown:
      - Cancel the EOD scheduler task
      - Cancel the fan-out task
      - Close the DuckDB connection
    """
    app.state.store = DuckDBStore(_settings.duckdb_path)
    app.state.store.ensure_schema()
    app.state.bus = EventBus()
    app.state.manager = ConnectionManager(app.state.bus)
    app.state.fan_out_task = asyncio.create_task(
        app.state.manager.start_background_fan_out()
    )

    # -----------------------------------------------------------------------
    # Phase 5: create FullRiskManager singleton and bootstrap state from DuckDB
    # -----------------------------------------------------------------------
    import yaml

    from trading_core.risk.full_risk_manager import FullRiskManager
    from trading_core.risk.models import RiskConfig

    # Locate config/risk.yaml relative to the repo root (WR-001 pattern).
    _repo_root = _find_repo_root(Path(__file__).resolve())
    risk_yaml_path = _repo_root / "config" / "risk.yaml"
    risk_cfg_dict: dict = {}
    if risk_yaml_path.exists():
        with open(risk_yaml_path) as f:
            risk_cfg_dict = yaml.safe_load(f) or {}
    risk_config = RiskConfig(**risk_cfg_dict)

    rm = FullRiskManager(config=risk_config, store=app.state.store, symbol="MES")

    # Bootstrap HWM from yesterday's last risk_state row (RM-05 / D-08).
    _et_tz = ZoneInfo("America/New_York")
    _yesterday = (datetime.now(_et_tz) - timedelta(days=1)).strftime("%Y-%m-%d")
    rm.load_hwm_from_db(date_str=_yesterday, store=app.state.store)
    _log.info("risk_manager.hwm_bootstrapped", yesterday=_yesterday)

    # Bootstrap kill-switch asyncio.Event from DuckDB (D-10).
    rm.load_kill_state_from_db(store=app.state.store)
    _log.info(
        "risk_manager.kill_state_bootstrapped",
        engine_state=app.state.store.get_engine_state(),
    )

    app.state.risk_manager = rm

    # -----------------------------------------------------------------------
    # Phase 5: wall-clock EOD scheduler (RM-07 / D-11)
    # -----------------------------------------------------------------------
    from trading_core.execution.eod_scheduler import EodScheduler

    async def _eod_flatten() -> None:
        """EOD flatten callback — no-op in Phase 5 (no live positions to flatten).

        Phase 6 will call the live executor's flatten method here. For now, the
        callback writes an audit record so the wall-clock fire is always traceable.
        """
        _log.info("eod_scheduler.fired", reason="wall_clock_eod")
        _store: DuckDBStore = app.state.store
        _rm = getattr(app.state, "risk_manager", None)
        _sid = getattr(_rm, "_session_id", "unknown")
        _store.write_audit_event(
            event_id=new_run_id(),
            ts_utc=datetime.now(timezone.utc),
            topic="engine_state",
            entity_id=_sid,
            reason_code="eod_flatten",
            payload_json='{"trigger": "wall_clock"}',
        )

    _scheduler = EodScheduler(on_flatten=_eod_flatten)
    app.state.eod_task = asyncio.create_task(_scheduler.run())
    _log.info("eod_scheduler.started")

    # -----------------------------------------------------------------------
    # Phase 6 Plan 02: TVBridge — long-lived supervised MCP stdio client
    # -----------------------------------------------------------------------
    from tv_bridge import TVBridge  # noqa: PLC0415

    _tv_bridge_ref = TVBridge(
        store=app.state.store, bus=app.state.bus, settings=_settings
    )
    await _tv_bridge_ref.start()
    app.state.tv_bridge = _tv_bridge_ref
    _log.info("tv_bridge.started")

    # -----------------------------------------------------------------------
    # Phase 6 Plan 03: ReconciliationScheduler — daily 16:10 ET SPY cross-vendor
    # -----------------------------------------------------------------------
    from datetime import date as _date  # noqa: PLC0415

    from trading_core.data.tradingview import TradingViewDataSource  # noqa: PLC0415
    from trading_core.data.twelvedata import TwelveDataSource  # noqa: PLC0415
    from tv_bridge import ReconciliationScheduler, run_reconciliation  # noqa: PLC0415

    # WARNING 3 fix: reconciliation uses TradingViewDataSource (per-call subprocess),
    # NOT the shared TVBridge session, to avoid contention with live drawing.
    _tv_recon_source = TradingViewDataSource(_settings, bus=app.state.bus)
    _twelve_source = TwelveDataSource(_settings)

    async def _do_reconcile() -> None:
        await run_reconciliation(
            tv_source=_tv_recon_source,
            twelve_source=_twelve_source,
            store=app.state.store,
            trading_date=_date.today(),
        )

    _recon_scheduler = ReconciliationScheduler(on_reconcile=_do_reconcile)
    app.state.recon_task = asyncio.create_task(
        _recon_scheduler.run(), name="reconciliation_scheduler"
    )
    _log.info("reconciliation_scheduler.started")

    # -----------------------------------------------------------------------
    # Phase 6 Plan 04: NightlyCleanupScheduler — 03:00 ET daily overlay cleanup
    # -----------------------------------------------------------------------
    from tv_bridge import NightlyCleanupScheduler, nightly_cleanup  # noqa: PLC0415

    async def _do_cleanup() -> None:
        await nightly_cleanup(bridge=app.state.tv_bridge, store=app.state.store)

    _cleanup_scheduler = NightlyCleanupScheduler(on_cleanup=_do_cleanup)
    app.state.cleanup_task = asyncio.create_task(
        _cleanup_scheduler.run(), name="nightly_cleanup_scheduler"
    )
    _log.info("nightly_cleanup_scheduler.started")

    # -----------------------------------------------------------------------
    # Phase 7 Plan 02: TOPIC_STRATEGY_RELOAD subscriber — hot-reload strategy (D-14)
    # -----------------------------------------------------------------------
    from trading_core.events.models import TOPIC_STRATEGY_RELOAD  # noqa: PLC0415
    from trading_core.strategy.registry import StrategyRegistry  # noqa: PLC0415

    async def _strategy_reload_handler() -> None:
        """Subscribe to TOPIC_STRATEGY_RELOAD and swap in-memory Strategy instance."""
        async with app.state.bus.subscribe(TOPIC_STRATEGY_RELOAD) as sub:
            async for event in sub:
                if isinstance(event, dict):
                    payload = event.get("payload", event)
                else:
                    payload = event
                strategy_id = payload.get("strategy_id", "")
                _log.info("strategy.hot_reload_received", strategy_id=strategy_id)
                _repo_root2 = _find_repo_root(Path(__file__).resolve())
                yaml_path = _repo_root2 / "config" / "strategies" / f"{strategy_id}.yaml"
                if yaml_path.exists():
                    new_strategy = StrategyRegistry.load(yaml_path)
                    # Store on app.state for engine to pick up
                    if not hasattr(app.state, "strategies"):
                        app.state.strategies = {}
                    app.state.strategies[strategy_id] = new_strategy
                    _log.info("strategy.hot_reloaded", strategy_id=strategy_id)

    app.state.strategy_reload_task = asyncio.create_task(
        _strategy_reload_handler(), name="strategy_reload_handler"
    )
    _log.info("strategy_reload_handler.started")

    yield

    # -----------------------------------------------------------------------
    # Shutdown — cancel background tasks in reverse startup order
    # -----------------------------------------------------------------------
    # Cancel strategy reload handler (Phase 7 Plan 02)
    app.state.strategy_reload_task.cancel()
    try:
        await app.state.strategy_reload_task
    except asyncio.CancelledError:
        pass

    # Cancel nightly cleanup scheduler (Phase 6 Plan 04)
    app.state.cleanup_task.cancel()
    try:
        await app.state.cleanup_task
    except asyncio.CancelledError:
        pass

    # Cancel reconciliation scheduler (Phase 6 Plan 03)
    app.state.recon_task.cancel()
    try:
        await app.state.recon_task
    except asyncio.CancelledError:
        pass

    # Stop TVBridge (Phase 6 Plan 02)
    await _tv_bridge_ref.stop()
    _log.info("tv_bridge.stopped")

    app.state.eod_task.cancel()
    try:
        await app.state.eod_task
    except asyncio.CancelledError:
        pass

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
        "Phase 5 surface: GET /positions (UI-05), POST /kill, POST /flatten, POST /pause (SP-05). "
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


# CORS middleware — T-03-05-02: explicit allow list, NOT wildcard origin.
# allow_credentials=False prevents cookie exfiltration from non-localhost tabs.
# Phase 5 adds POST to allow_methods (SP-05 kill/flatten/pause endpoints).
# T-05-04-04: expanding to POST on localhost is accepted per Phase 5 threat model.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    allow_credentials=False,
)

app.include_router(bars_routes.router)
app.include_router(backtests_routes.router)
app.include_router(optimizations_routes.router)
app.include_router(risk_routes.router)
app.include_router(strategies_routes.router)
app.include_router(tv_routes.router)


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
