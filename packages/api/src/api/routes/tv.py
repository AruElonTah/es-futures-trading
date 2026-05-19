"""TV REST routes — Phase 6 Plan 02 Task 3 (TV-03, TV-05, TV-07).

Endpoints:
  POST /tv/focus          — Drive TV Desktop chart to symbol+date+timeframe (202 Accepted)
  POST /tv/alerts         — Create a TradingView alert (201 Created)
  DELETE /tv/alerts/{id}  — Delete a TradingView alert (200 OK)
  GET  /tv/status         — TVBridge connection status (200 OK)

Security mitigations:
  T-06-02-05 (Tampering via /tv/focus symbol): Pydantic @field_validator enforces
    _SYMBOL_ALLOWLIST; invalid symbol → 422.
  T-06-02-06 (Tampering via /tv/focus date): Pydantic @field_validator parses via
    date.fromisoformat; invalid → 422.
  T-06-02-07 (Repudiation): every mutating route writes write_audit_event before
    returning success.

Auth: None in v1 (single-operator localhost). CORS restricted to localhost:3000
(T-05-04-01 inherited from Phase 5 CORS configuration).
"""

from __future__ import annotations

import asyncio
import json
from datetime import date as _date
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, field_validator

from api.deps import get_store
from trading_core.logging import get_logger
from trading_core.storage.duckdb_store import DuckDBStore
from trading_core.storage.runs import new_run_id

router = APIRouter()
_log = get_logger(__name__)

# Symbol allowlist — mirrors bridge.py _SYMBOL_ALLOWLIST as the REST-layer contract.
# T-06-02-05: validated via @field_validator before any bridge call is made.
_SYMBOL_ALLOWLIST: frozenset[str] = frozenset({"ES", "MES", "SPY"})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_bridge(request: Request) -> Any:
    """Return the TVBridge singleton from app.state, or None if not wired."""
    return getattr(request.app.state, "tv_bridge", None)


# ---------------------------------------------------------------------------
# Request body models
# ---------------------------------------------------------------------------


class TVFocusRequest(BaseModel):
    """POST /tv/focus request body."""

    symbol: str
    date: str           # YYYY-MM-DD (ET)
    timeframe: str = "1"  # TV timeframe string; default 1m

    @field_validator("symbol")
    @classmethod
    def symbol_must_be_allowed(cls, value: str) -> str:
        """Enforce symbol allowlist (T-06-02-05)."""
        if value not in _SYMBOL_ALLOWLIST:
            raise ValueError(
                f"symbol {value!r} not in allowlist {sorted(_SYMBOL_ALLOWLIST)}"
            )
        return value

    @field_validator("date")
    @classmethod
    def date_must_be_iso(cls, value: str) -> str:
        """Validate ISO date format (T-06-02-06)."""
        try:
            _date.fromisoformat(value)
        except ValueError:
            raise ValueError(f"date {value!r} must be a valid ISO date YYYY-MM-DD")
        return value


class TVAlertRequest(BaseModel):
    """POST /tv/alerts request body."""

    strategy_id: str    # max 64 chars enforced by MCP payload cap in bridge
    condition: str      # max 256 chars
    message: str        # max 256 chars


# ---------------------------------------------------------------------------
# POST /tv/focus — TV-03, TV-05
# ---------------------------------------------------------------------------


@router.post("/tv/focus", status_code=202)
async def tv_focus(req: TVFocusRequest, request: Request) -> dict:
    """Drive TV Desktop to symbol+date+timeframe (fire-and-forget, 202 Accepted).

    Returns immediately without awaiting chart readiness — chart_set_symbol
    can take up to 11s cold. The actual chart update happens asynchronously
    via asyncio.create_task. HTTP 202 is returned in < 200ms regardless.

    Returns 422 if symbol not in allowlist or date is not a valid ISO date.
    Returns 503 if TVBridge is not available (app.state.tv_bridge is None).
    """
    bridge = _get_bridge(request)
    if bridge is None:
        raise HTTPException(503, "TVBridge not available")
    asyncio.create_task(
        bridge.focus(req.symbol, req.date, req.timeframe),
        name=f"tv_focus_{req.symbol}_{req.date}",
    )
    _log.info("tv_focus.accepted", symbol=req.symbol, date=req.date)
    return {"status": "accepted", "symbol": req.symbol, "date": req.date}


# ---------------------------------------------------------------------------
# POST /tv/alerts — TV-07
# ---------------------------------------------------------------------------


@router.post("/tv/alerts", status_code=201)
async def create_alert(req: TVAlertRequest, request: Request) -> dict:
    """Create a TradingView alert and persist to tv_alerts table.

    Calls bridge.create_alert (awaits — alert_create returns within seconds),
    then writes tv_alerts row + audit_log row (T-06-02-07 repudiation mitigation).

    Returns 201 with {alert_id, tv_alert_id} on success.
    Returns 502 if alert_create MCP call fails.
    Returns 503 if TVBridge is not available.
    """
    bridge = _get_bridge(request)
    if bridge is None:
        raise HTTPException(503, "TVBridge not available")

    tv_alert_id = await bridge.create_alert(req.condition, req.message)
    if tv_alert_id is None:
        raise HTTPException(502, "alert_create failed — TVBridge returned no alert_id")

    store: DuckDBStore = get_store(request)
    alert_id = new_run_id()
    store.write_tv_alert(
        alert_id=alert_id,
        strategy_id=str(req.strategy_id)[:64],
        tv_alert_id=tv_alert_id,
        condition=str(req.condition)[:256],
    )

    # Audit record (T-06-02-07: repudiation mitigation)
    store.write_audit_event(
        event_id=new_run_id(),
        ts_utc=datetime.now(timezone.utc),
        topic="tv_alert",
        entity_id=alert_id,
        reason_code="alert_created",
        payload_json=json.dumps(
            {"strategy_id": str(req.strategy_id)[:64], "tv_alert_id": tv_alert_id}
        ),
    )

    _log.info("tv_alert.created", alert_id=alert_id, tv_alert_id=tv_alert_id)
    return {"alert_id": alert_id, "tv_alert_id": tv_alert_id}


# ---------------------------------------------------------------------------
# DELETE /tv/alerts/{alert_id} — TV-07
# ---------------------------------------------------------------------------


@router.delete("/tv/alerts/{alert_id}", status_code=200)
async def delete_alert(alert_id: str, request: Request) -> dict:
    """Delete a TradingView alert and soft-delete the tv_alerts row.

    Looks up tv_alert_id from DuckDB, calls bridge.delete_alert, marks row
    deleted, writes audit_log (T-06-02-07).

    Returns 200 {deleted: alert_id} on success.
    Returns 404 if alert_id not found.
    Returns 503 if TVBridge is not available.
    """
    store: DuckDBStore = get_store(request)
    bridge = _get_bridge(request)
    if bridge is None:
        raise HTTPException(503, "TVBridge not available")

    tv_alert_id = store.get_tv_alert_tv_id(alert_id)
    if tv_alert_id is None:
        raise HTTPException(404, f"alert_id {alert_id!r} not found")

    await bridge.delete_alert(tv_alert_id)
    store.mark_tv_alert_deleted(alert_id=alert_id)

    # Audit record (T-06-02-07)
    store.write_audit_event(
        event_id=new_run_id(),
        ts_utc=datetime.now(timezone.utc),
        topic="tv_alert",
        entity_id=alert_id,
        reason_code="alert_deleted",
        payload_json=json.dumps({"tv_alert_id": tv_alert_id}),
    )

    _log.info("tv_alert.deleted", alert_id=alert_id, tv_alert_id=tv_alert_id)
    return {"deleted": alert_id}


# ---------------------------------------------------------------------------
# GET /tv/status
# ---------------------------------------------------------------------------


@router.get("/tv/status")
async def tv_status(request: Request) -> dict:
    """Return TVBridge connection status for the frontend connection-status indicator.

    Returns:
        {connected: bool, last_error: null}

    Note: last_error is always null in Plan 02 (T-06-02-04: _stderr_capture
    contents not exposed here). Plan 04 may add a sanitized last_error field.
    """
    bridge = _get_bridge(request)
    connected = bool(bridge and getattr(bridge, "is_connected", False))
    return {"connected": connected, "last_error": None}
