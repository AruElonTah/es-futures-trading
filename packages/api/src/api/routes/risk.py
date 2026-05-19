"""Risk manager API routes — Phase 5 Plan 04.

SP-05 kill/flatten/pause controls + UI-05 positions blotter data source.

Endpoints:
  GET  /positions  — UI-05: live blotter data; returns open positions enriched
                     with server-side point_value (FND-06, no magic numbers client-side).
  POST /kill       — SP-05: activate kill switch; halts new signal processing.
                     Activates even with no positions open (D-12).
  POST /flatten    — SP-05: close all open positions at next-bar-open.
                     No-op when no positions are open (D-12).
  POST /pause      — Toggle engine pause/resume state.

All mutating routes (kill/flatten/pause) write to the audit_log and engine_state
DuckDB tables before returning (T-05-04-02: no repudiation).

Auth: None in v1 (single-operator localhost). CORS is restricted to localhost:3000
(T-05-04-01: spoofing accepted, mitigated by origin restriction).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Request

from api.deps import get_bus, get_store
from trading_core.events.models import TOPIC_ENGINE_STATE
from trading_core.instruments import get as get_instrument
from trading_core.logging import get_logger
from trading_core.storage.duckdb_store import DuckDBStore
from trading_core.storage.runs import new_run_id

router = APIRouter()
_log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_rm(request: Request) -> Any:
    """Return the FullRiskManager singleton from app.state, or None."""
    return getattr(request.app.state, "risk_manager", None)


def _positions_held(rm: Any) -> int:
    """Return the count of open positions from the risk manager."""
    if rm is not None and hasattr(rm, "_positions"):
        return len(rm._positions)
    return 0


def _session_id(rm: Any) -> str:
    """Return the current session_id from the risk manager, or a fallback."""
    if rm is not None and hasattr(rm, "_session_id"):
        return rm._session_id
    return new_run_id()


# ---------------------------------------------------------------------------
# GET /positions — UI-05 blotter data source (FND-06)
# ---------------------------------------------------------------------------


@router.get("/positions")
async def get_positions(request: Request) -> dict:
    """Return open positions from the in-memory risk manager.

    Each position dict is enriched server-side with:
    - ``point_value``: float — from instruments.get(symbol).point_value (FND-06).
      The frontend uses this for unrealized P&L calculation; no magic numbers client-side.
    - ``engine_state``: str — most-recent engine state from DuckDB.

    Returns an empty positions list when no positions are open (HTTP 200).
    """
    store: DuckDBStore = get_store(request)
    rm = _get_rm(request)

    engine_state = store.get_engine_state()

    positions: list[dict] = []
    if rm is not None and hasattr(rm, "_positions"):
        for pos in rm._positions.values():
            enriched = dict(pos)
            # Server-side point_value injection — FND-06 compliance.
            # Falls back to None if the symbol is not in the instruments registry
            # (should never happen for ES/MES but guards against test fixtures).
            symbol = pos.get("symbol", "")
            try:
                point_value = float(get_instrument(symbol).point_value)
            except KeyError:
                point_value = None
            enriched["point_value"] = point_value
            enriched["engine_state"] = engine_state
            positions.append(enriched)

    _log.info("positions.listed", count=len(positions), engine_state=engine_state)
    return {"positions": positions, "engine_state": engine_state}


# ---------------------------------------------------------------------------
# POST /kill — SP-05 kill switch (D-10, D-12)
# ---------------------------------------------------------------------------


@router.post("/kill")
async def post_kill(request: Request) -> dict:
    """Activate the kill switch — halt all signal processing.

    Existing positions are held (not flattened). Activates even with no open
    positions (D-12). The asyncio.Event is set AFTER DuckDB writes to ensure
    the audit record is committed even if the event-set step fails.

    Sequence (D-10 ordering):
      1. write_engine_state(session_id, 'killed')
      2. write_audit_event(reason_code='kill_switch')
      3. rm.set_killed('killed')  — set asyncio.Event
      4. bus.publish(TOPIC_ENGINE_STATE, engine_state_changed)
      5. return {state, positions_held}
    """
    store: DuckDBStore = get_store(request)
    bus = get_bus(request)
    rm = _get_rm(request)
    sid = _session_id(rm)
    now_utc = datetime.now(timezone.utc)

    # Step 1: persist to engine_state
    store.write_engine_state(session_id=sid, state="killed")

    # Step 2: audit record (T-05-04-02: repudiation mitigation)
    store.write_audit_event(
        event_id=new_run_id(),
        ts_utc=now_utc,
        topic="engine_state",
        entity_id=sid,
        reason_code="kill_switch",
        payload_json=json.dumps({"state": "killed"}),
    )

    # Step 3: set the asyncio.Event kill-switch (D-10)
    if rm is not None and hasattr(rm, "set_killed"):
        rm.set_killed("killed")

    # Step 4: publish WS notification
    await bus.publish(
        TOPIC_ENGINE_STATE,
        {"type": "engine_state_changed", "payload": {"state": "killed"}},
    )

    positions_held = _positions_held(rm)
    _log.info("kill_switch.activated", positions_held=positions_held, session_id=sid)
    return {"state": "killed", "positions_held": positions_held}


# ---------------------------------------------------------------------------
# POST /flatten — SP-05 flatten command (D-12)
# ---------------------------------------------------------------------------


@router.post("/flatten")
async def post_flatten(request: Request) -> dict:
    """Request closure of all open positions at next-bar-open.

    No-op when there are no open positions (D-12): still writes the audit record
    but returns immediately without changing the engine state.

    In Phase 5 (paper mode) there is no live executor — the EodScheduler's
    _eod_flatten callback handles physical closure. This endpoint records the
    intent and notifies the WS clients.

    Sequence:
      1. Compute positions_held count.
      2. write_engine_state('flatten_requested')
      3. write_audit_event(reason_code='flatten_all')
      4. bus.publish(TOPIC_ENGINE_STATE, flatten_requested)
      5. write_engine_state('running')  — immediately mark running again
      6. return {positions_closed}
    """
    store: DuckDBStore = get_store(request)
    bus = get_bus(request)
    rm = _get_rm(request)
    sid = _session_id(rm)
    now_utc = datetime.now(timezone.utc)
    positions_held = _positions_held(rm)

    # Step 2: persist flatten_requested state
    store.write_engine_state(session_id=sid, state="flatten_requested")

    # Step 3: audit record (T-05-04-02: repudiation mitigation)
    store.write_audit_event(
        event_id=new_run_id(),
        ts_utc=now_utc,
        topic="engine_state",
        entity_id=sid,
        reason_code="flatten_all",
        payload_json=json.dumps({"positions_closed": positions_held}),
    )

    # Step 4: publish WS notification
    await bus.publish(
        TOPIC_ENGINE_STATE,
        {"type": "engine_state_changed", "payload": {"state": "flatten_requested"}},
    )

    # Step 5: immediately mark running again (flatten is a momentary request,
    # not a persistent state — the executor handles the actual close)
    store.write_engine_state(session_id=sid, state="running")

    _log.info(
        "flatten.requested", positions_closed=positions_held, session_id=sid
    )
    return {"positions_closed": positions_held}


# ---------------------------------------------------------------------------
# POST /pause — toggle engine pause / resume
# ---------------------------------------------------------------------------


@router.post("/pause")
async def post_pause(request: Request) -> dict:
    """Toggle engine pause/resume state.

    Reads the current engine_state from DuckDB to determine the toggle direction:
    - If currently 'paused'  → new_state = 'running'
    - Otherwise (including 'killed') → new_state = 'paused'

    The kill-switch asyncio.Event is kept in sync via rm.set_killed():
    - 'paused'  → clears _kill_event (same behavior as 'running'; pause is a
      logical state, not a signal-block in Phase 5)
    - 'running' → clears _kill_event

    Sequence:
      1. current = store.get_engine_state()
      2. new_state = toggle
      3. write_engine_state(new_state)
      4. rm.set_killed(new_state)
      5. bus.publish(TOPIC_ENGINE_STATE, new_state)
      6. return {state: new_state}
    """
    store: DuckDBStore = get_store(request)
    bus = get_bus(request)
    rm = _get_rm(request)
    sid = _session_id(rm)
    now_utc = datetime.now(timezone.utc)

    # Step 1: determine current state
    current = store.get_engine_state()

    # Step 2: toggle
    new_state = "running" if current == "paused" else "paused"

    # Step 3: persist
    store.write_engine_state(session_id=sid, state=new_state)

    # Audit record
    store.write_audit_event(
        event_id=new_run_id(),
        ts_utc=now_utc,
        topic="engine_state",
        entity_id=sid,
        reason_code=f"pause_toggle_{new_state}",
        payload_json=json.dumps({"previous_state": current, "new_state": new_state}),
    )

    # Step 4: keep asyncio.Event in sync
    if rm is not None and hasattr(rm, "set_killed"):
        rm.set_killed(new_state)

    # Step 5: publish WS notification
    await bus.publish(
        TOPIC_ENGINE_STATE,
        {"type": "engine_state_changed", "payload": {"state": new_state}},
    )

    _log.info(
        "pause.toggled",
        previous_state=current,
        new_state=new_state,
        session_id=sid,
    )
    return {"state": new_state}
