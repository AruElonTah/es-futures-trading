# Phase 6: TradingView MCP Bridge — Pattern Map

**Mapped:** 2026-05-19
**Files analyzed:** 6 new/modified files
**Analogs found:** 6 / 6

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `packages/tv-bridge/src/tv_bridge/bridge.py` | service (supervisor) | event-driven | `packages/trading-core/src/trading_core/data/tradingview.py` | role-match (same MCP SDK, same stdio_client pattern; bridge upgrades to long-lived session) |
| `packages/tv-bridge/src/tv_bridge/replay.py` | service (DataSource impl) | request-response | `packages/trading-core/src/trading_core/data/tradingview.py` | exact (same DataSource protocol, same per-call stdio_client pattern) |
| `packages/tv-bridge/src/tv_bridge/reconciliation.py` | service (scheduler) | batch | `packages/trading-core/src/trading_core/execution/eod_scheduler.py` | role-match (same asyncio scheduled-task pattern, same EodScheduler wrapping) |
| `packages/tv-bridge/src/tv_bridge/shapes.py` | utility | transform | `packages/trading-core/src/trading_core/indicators/atr.py` | partial (pure-function utility module — no direct analog for MCP payload builders) |
| `packages/api/src/api/routes/tv.py` | controller | request-response | `packages/api/src/api/routes/risk.py` | exact (same async routes, same `request.app.state` accessor, same audit_log + bus pattern) |
| `packages/trading-core/src/trading_core/storage/schema.sql` | config (DDL) | CRUD | self (existing schema.sql patterns) | exact (same `CREATE TABLE IF NOT EXISTS`, same `TIMESTAMPTZ`, same uuid7 PK, same `deleted_at` nullable pattern) |

---

## Pattern Assignments

### `packages/tv-bridge/src/tv_bridge/bridge.py` (service, event-driven)

**Analog:** `packages/trading-core/src/trading_core/data/tradingview.py`

**Imports pattern** (lines 34-56 of analog):
```python
from __future__ import annotations

import asyncio
import io
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

import structlog
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from trading_core.config import Settings
from trading_core.events import (
    TOPIC_DEGRADED_STATE,
    TOPIC_SIGNALS,
    TOPIC_FILLS,
    DegradedStateEvent,
    EventBus,
)
from trading_core.storage.duckdb_store import DuckDBStore

_log = structlog.get_logger(__name__)
```

**`_server_params` pattern** (lines 125-136 of analog — copy verbatim):
```python
def _server_params(self) -> StdioServerParameters:
    server_js = self._mcp_server_path / "src" / "server.js"
    return StdioServerParameters(
        command="node",
        args=[str(server_js)],
        env=None,
    )
```

**`_parse_tool_payload` pattern** (lines 155-169 of analog — copy verbatim):
```python
@staticmethod
def _parse_tool_payload(result: object) -> dict[str, object]:
    content = getattr(result, "content", None)
    if not content:
        return {}
    try:
        text = content[0].text
    except (AttributeError, IndexError):
        return {}
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return {"_raw": text}
    return payload if isinstance(payload, dict) else {"_value": payload}
```

**`_publish_degraded` pattern** (lines 138-153 of analog — copy verbatim):
```python
async def _publish_degraded(self, reason: str) -> None:
    try:
        await self._bus.publish(
            TOPIC_DEGRADED_STATE,
            DegradedStateEvent(
                topic=TOPIC_DEGRADED_STATE,
                emitted_at=datetime.now(tz=timezone.utc),
                source=self.name,
                reason=reason,
            ),
        )
    except Exception as e:
        _log.warning("degraded_publish_failed", error=repr(e))
```

**Supervisor loop pattern** (from RESEARCH.md Pattern 1 — no existing analog; use as-is):
```python
_BACKOFF_SECONDS = [1, 2, 4, 8, 16, 30]  # capped at 30s

async def _supervisor_loop(self) -> None:
    attempt = 0
    while True:
        try:
            async with stdio_client(self._server_params(), errlog=self._stderr_capture) as (r, w):
                async with ClientSession(r, w) as session:
                    await asyncio.wait_for(session.initialize(), timeout=15.0)
                    # health gate — same as fetch_bars in tradingview.py lines 251-259
                    health_result = await session.call_tool("tv_health_check", {})
                    health = self._parse_tool_payload(health_result)
                    if not health.get("api_available"):
                        raise RuntimeError(f"health_check failed: {health}")
                    async with self._session_lock:
                        self._session = session
                    attempt = 0
                    _log.info("tv_bridge.connected")
                    await asyncio.Future()   # holds context manager alive until exception
        except asyncio.CancelledError:
            return
        except Exception as e:
            async with self._session_lock:
                self._session = None
            await self._publish_degraded(f"tv_bridge disconnect: {e}")
            backoff = self._BACKOFF_SECONDS[min(attempt, len(self._BACKOFF_SECONDS) - 1)]
            _log.warning("tv_bridge.reconnecting", attempt=attempt, backoff=backoff)
            await asyncio.sleep(backoff)
            attempt += 1
```

**EventBus subscription pattern** (from `packages/trading-core/src/trading_core/events/bus.py` lines 110-128):
```python
# In start() — create_task wrapping, not awaiting, the subscription loop:
asyncio.create_task(self._subscribe_signals())

# Subscription loop body:
async def _subscribe_signals(self) -> None:
    async with self._bus.subscribe(TOPIC_SIGNALS) as sub:
        async for event in sub:
            asyncio.create_task(
                self._safe_draw_signal(event),
                name=f"tv_draw_signal_{event.signal_id}",
            )
```

**safe_call_tool / error suppression pattern** (modeled on the health-gate in tradingview.py lines 251-259 but wrapped for TVBridge non-blocking contract):
```python
async def call_tool(self, tool: str, args: dict) -> dict | None:
    async with self._session_lock:
        session = self._session
    if session is None:
        _log.warning("tv_bridge.no_session", tool=tool)
        return None
    try:
        result = await asyncio.wait_for(
            session.call_tool(tool, args),
            timeout=12.0,
        )
        return self._parse_tool_payload(result)
    except asyncio.TimeoutError:
        _log.warning("tv_bridge.tool_timeout", tool=tool)
        return None
    except Exception as e:
        _log.exception("tv_bridge.tool_error", tool=tool)
        return None
```

**lifespan wiring pattern** (from `packages/api/src/api/app.py` lines 101-168):
```python
# In lifespan(), after existing store/bus/rm setup:
from tv_bridge.bridge import TVBridge
bridge = TVBridge(store=app.state.store, bus=app.state.bus, settings=_settings)
await bridge.start()           # spawns supervisor task + subscribe tasks
app.state.tv_bridge = bridge

yield

# Shutdown — before fan_out_task.cancel():
await bridge.stop()
```

---

### `packages/tv-bridge/src/tv_bridge/replay.py` (service, DataSource protocol)

**Analog:** `packages/trading-core/src/trading_core/data/tradingview.py`

**Imports pattern** (same as tradingview.py lines 34-56; swap class name):
```python
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, AsyncIterator

import pandas as pd
import structlog
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from trading_core.config import Settings
from trading_core.data.models import Bar
from trading_core.data.protocols import DataSourceUnavailable
from trading_core.events import TOPIC_DEGRADED_STATE, DegradedStateEvent, EventBus

_log = structlog.get_logger(__name__)
```

**DataSource protocol surface** (from `packages/trading-core/src/trading_core/data/protocols.py` lines 37-73):
```python
class TVReplayDataSource:
    """DataSource backed by TV replay session (TV-04)."""
    name = "tradingview_replay"

    async def fetch_bars(
        self,
        symbol: str,
        timeframe: str,      # "1m" | "5m" | "15m"
        start: datetime,     # tz-aware UTC
        end: datetime,       # tz-aware UTC, exclusive
    ) -> pd.DataFrame: ...

    async def subscribe_bars(
        self,
        symbol: str,
        timeframe: str,
    ) -> AsyncIterator[Bar]: ...
```

**Per-call session pattern** (tradingview.py lines 229-295 — the `async with stdio_client(...)` block inside `fetch_bars`):
- Open `stdio_client(self._server_params())` fresh per `fetch_bars` call (same as Phase 1 TradingViewDataSource, NOT the shared session of TVBridge)
- `await asyncio.wait_for(session.initialize(), timeout=_INIT_TIMEOUT_SECONDS)` with same 15s budget
- Health gate: `call_tool("tv_health_check", {})` + `health.get("api_available")` check
- On any failure: `await self._publish_degraded(reason)` then `raise DataSourceUnavailable(...)`

**DataFrame output contract** (tradingview.py lines 298-319 — copy column names verbatim):
```python
# Empty DataFrame columns must match exactly:
columns=["symbol", "timeframe", "ts_utc", "open", "high", "low", "close", "volume", "provider"]

# Populated DataFrame construction pattern:
df = pd.DataFrame({
    "symbol": [symbol] * len(bars),
    "timeframe": [timeframe] * len(bars),
    "ts_utc": ts,  # list of datetime objects from _bar_time_to_utc()
    "open": [float(b["open"]) for b in bars],
    "high": [float(b["high"]) for b in bars],
    "low": [float(b["low"]) for b in bars],
    "close": [float(b["close"]) for b in bars],
    "volume": [int(b.get("volume") or 0) for b in bars],
    "provider": [self.name] * len(bars),
})
return df.sort_values("ts_utc").reset_index(drop=True)
```

**`_bar_time_to_utc` helper** (tradingview.py lines 172-187 — copy verbatim; replay bars use same Unix-epoch format):
```python
@staticmethod
def _bar_time_to_utc(value: object) -> datetime:
    if isinstance(value, (int, float)):
        seconds = float(value) / 1000.0 if value > 10_000_000_000 else float(value)
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    raise ValueError(f"Cannot parse bar time field: {value!r}")
```

**Symbol and timeframe maps** (tradingview.py lines 59-78 — copy verbatim):
```python
_SYMBOL_MAP: dict[str, str] = {"ES": "CME_MINI:ES1!", "MES": "CME_MINI:MES1!"}
_TF_TO_TV: dict[str, str] = {"1m": "1", "5m": "5", "15m": "15"}
```

---

### `packages/tv-bridge/src/tv_bridge/reconciliation.py` (service, batch)

**Analog:** `packages/trading-core/src/trading_core/execution/eod_scheduler.py`

**Imports pattern** (eod_scheduler.py lines 1-24):
```python
from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Coroutine
from datetime import date, datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from trading_core.logging import get_logger
from trading_core.storage.duckdb_store import DuckDBStore
from trading_core.storage.runs import new_run_id
```

**EodScheduler wrapping pattern** (eod_scheduler.py lines 27-80 — ReconciliationScheduler wraps EodScheduler identically to how `_eod_flatten` is wired in app.py lines 148-168):
```python
class ReconciliationScheduler:
    """Fires run_reconciliation() at 16:10 ET daily (10 min post-RTH close)."""

    def __init__(self, on_reconcile: Callable[[], Coroutine[Any, Any, None]]):
        self._scheduler = EodScheduler(
            on_flatten=on_reconcile,
            close_time_et="16:10",   # 10 min after RTH close
            lead_seconds=0,
        )

    async def run(self) -> None:
        await self._scheduler.run()
```

**Lifespan task wiring** (app.py lines 165-169 — copy pattern):
```python
# In lifespan(), after bridge.start():
from tv_bridge.reconciliation import ReconciliationScheduler, run_reconciliation

async def _reconcile() -> None:
    await run_reconciliation(
        tv_bridge=app.state.tv_bridge,
        twelve_source=_twelve_source,
        store=app.state.store,
    )

_recon_scheduler = ReconciliationScheduler(on_reconcile=_reconcile)
app.state.recon_task = asyncio.create_task(_recon_scheduler.run())
```

**Shutdown pattern** (app.py lines 176-183):
```python
# In shutdown block before fan_out_task.cancel():
app.state.recon_task.cancel()
try:
    await app.state.recon_task
except asyncio.CancelledError:
    pass
```

**`write_audit_event` call for reconciliation alert** (duckdb_store.py lines 627-669 — keyword-only signature):
```python
store.write_audit_event(
    event_id=new_run_id(),
    ts_utc=datetime.now(timezone.utc),
    topic="reconciliation_alert",
    entity_id=trading_date.isoformat(),
    reason_code="price_divergence",   # or "volume_divergence"
    payload_json=json.dumps({"ts": ts.isoformat(), "price_pct": price_pct}),
)
```

---

### `packages/tv-bridge/src/tv_bridge/shapes.py` (utility, transform)

**No close analog** — this is a pure-function module producing dict payloads for the `draw_shape` MCP tool. Nearest pattern is the hand-rolled indicator modules (`indicators/atr.py`, `indicators/vwap.py`) in their use of module-level constants + pure functions with no class.

**Module structure to copy from** `packages/trading-core/src/trading_core/indicators/atr.py`:
```python
# Module-level docstring
# Module-level constants (type-annotated)
# Pure functions — no class, no state

def entry_arrow_args(signal, fill_bar_time: int) -> dict:
    """Return draw_shape kwargs for an entry horizontal_line."""
    ...

def stop_line_args(signal) -> dict: ...
def target_line_args(signal) -> dict: ...
def orb_box_args(orb_high: float, orb_low: float, session_open_ts: int, orb_end_ts: int) -> dict: ...
```

**Import pattern for shapes.py** (minimal — no framework imports):
```python
from __future__ import annotations
from typing import Any
```

---

### `packages/api/src/api/routes/tv.py` (controller, request-response)

**Analog:** `packages/api/src/api/routes/risk.py`

**Imports pattern** (risk.py lines 1-37):
```python
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from api.deps import get_store
from trading_core.logging import get_logger
from trading_core.storage.duckdb_store import DuckDBStore
from trading_core.storage.runs import new_run_id

router = APIRouter()
_log = get_logger(__name__)
```

**`request.app.state` accessor pattern** (risk.py lines 44-48 — copy exact pattern):
```python
def _get_bridge(request: Request) -> Any:
    """Return the TVBridge singleton from app.state, or None."""
    return getattr(request.app.state, "tv_bridge", None)
```

**HTTP 503 guard pattern** (risk.py — no bridge check there, but HTTPException is already imported; pattern from RESEARCH.md):
```python
bridge = _get_bridge(request)
if bridge is None:
    raise HTTPException(503, "TVBridge not available")
```

**POST route with Pydantic body + async + fire-and-forget pattern** (risk.py lines 110-156 — POST /kill is the closest action route):
```python
class TVFocusRequest(BaseModel):
    symbol: str          # validated against allowlist in body
    date: str            # ISO date "YYYY-MM-DD"
    timeframe: str = "1" # TV timeframe string

@router.post("/tv/focus", status_code=202)
async def tv_focus(req: TVFocusRequest, request: Request) -> dict:
    bridge = _get_bridge(request)
    if bridge is None:
        raise HTTPException(503, "TVBridge not available")
    asyncio.create_task(bridge.focus(req.symbol, req.date, req.timeframe))
    return {"status": "accepted", "symbol": req.symbol, "date": req.date}
```

**Audit + store write pattern** (risk.py lines 125-144 — POST /kill sequence):
```python
# Pattern for routes that need to persist:
store: DuckDBStore = get_store(request)  # via api.deps.get_store(request)
store.write_audit_event(
    event_id=new_run_id(),
    ts_utc=now_utc,
    topic="tv_alert",
    entity_id=alert_id,
    reason_code="alert_created",
    payload_json=json.dumps({...}),
)
```

**DELETE route pattern** (no existing DELETE in codebase — use risk.py pattern with path param):
```python
@router.delete("/tv/alerts/{alert_id}", status_code=200)
async def delete_alert(alert_id: str, request: Request) -> dict:
    store: DuckDBStore = get_store(request)
    bridge = _get_bridge(request)
    if bridge is None:
        raise HTTPException(503, "TVBridge not available")
    # ... lookup, call bridge, mark deleted
    return {"deleted": alert_id}
```

**Router registration** (app.py lines 231-234 — add after existing routers):
```python
from api.routes import tv as tv_routes
app.include_router(tv_routes.router)
```

---

### `packages/trading-core/src/trading_core/storage/schema.sql` (DDL modification)

**Analog:** Self — existing schema.sql conventions

**Table DDL pattern** (schema.sql lines 150-186 — `audit_log` and `engine_state` are closest in shape: append-only uuid7 PK, TIMESTAMPTZ, nullable `deleted_at`-style column):
```sql
-- Phase 6: TV overlay registry (TV-02)
-- One row per shape drawn on the TV chart.
CREATE TABLE IF NOT EXISTS tv_overlays (
    overlay_id    VARCHAR     PRIMARY KEY,          -- uuid7 (time-sortable)
    strategy_id   VARCHAR     NOT NULL,
    signal_id     VARCHAR     NOT NULL,             -- soft FK to audit_log.entity_id
    shape_kind    VARCHAR     NOT NULL,             -- 'entry_arrow'|'stop_line'|'target_line'|'orb_box'
    shape_id      VARCHAR     NOT NULL,             -- entity_id from draw_shape MCP response
    trading_date  DATE        NOT NULL,             -- ET trading date the shape belongs to
    created_at    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at    TIMESTAMPTZ                       -- NULL = active; set by nightly cleanup
);

-- Phase 6: TV alert registry (TV-07)
CREATE TABLE IF NOT EXISTS tv_alerts (
    alert_id      VARCHAR     PRIMARY KEY,          -- uuid7
    strategy_id   VARCHAR     NOT NULL,
    tv_alert_id   VARCHAR     NOT NULL,             -- alert ID from alert_create MCP tool
    condition     VARCHAR     NOT NULL,             -- free-form alert condition description
    created_at    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at    TIMESTAMPTZ                       -- NULL = active; set on strategy toggle-off
);
```

**DuckDBStore method pattern for new writers** (duckdb_store.py lines 626-669 — `write_audit_event` is the canonical append-only writer pattern):

SQL constant at module level:
```python
WRITE_TV_OVERLAY_SQL = """
INSERT INTO tv_overlays (overlay_id, strategy_id, signal_id, shape_kind, shape_id, trading_date)
VALUES (?, ?, ?, ?, ?, ?);
"""

WRITE_TV_ALERT_SQL = """
INSERT INTO tv_alerts (alert_id, strategy_id, tv_alert_id, condition)
VALUES (?, ?, ?, ?);
"""

MARK_TV_ALERT_DELETED_SQL = """
UPDATE tv_alerts SET deleted_at = now() WHERE alert_id = ?;
"""

COUNT_ACTIVE_OVERLAYS_SQL = """
SELECT COUNT(*) FROM tv_overlays WHERE deleted_at IS NULL;
"""
```

Method signature pattern (keyword-only, `self._conn.execute(...)`):
```python
def write_tv_overlay(
    self,
    *,
    overlay_id: str,
    strategy_id: str,
    signal_id: str,
    shape_kind: str,
    shape_id: str,
    trading_date: date,
) -> None:
    self._conn.execute(
        WRITE_TV_OVERLAY_SQL,
        [overlay_id, strategy_id, signal_id, shape_kind, shape_id, trading_date],
    )
```

---

## Shared Patterns

### structlog Logger
**Source:** `packages/trading-core/src/trading_core/data/tradingview.py` line 56
**Apply to:** `bridge.py`, `replay.py`, `reconciliation.py`, `shapes.py` (if it logs)
```python
import structlog
_log = structlog.get_logger(__name__)
```

### `get_logger` (API side)
**Source:** `packages/api/src/api/routes/bars.py` line 23 and `risk.py` line 37
**Apply to:** `packages/api/src/api/routes/tv.py`
```python
from trading_core.logging import get_logger
_log = get_logger(__name__)
```

### `new_run_id()` for uuid7 PKs
**Source:** `packages/trading-core/src/trading_core/storage/runs.py` (imported throughout)
**Apply to:** `bridge.py` (overlay_id, event_id), `tv.py` (alert_id, event_id), `reconciliation.py` (event_id)
```python
from trading_core.storage.runs import new_run_id
# Usage:
overlay_id = new_run_id()
```

### `_LockedConn` serialization is automatic
**Source:** `packages/trading-core/src/trading_core/storage/duckdb_store.py` lines 36-63
**Apply to:** All new `DuckDBStore` methods — the `_conn` proxy already serializes all `execute` calls; no additional locking needed in TVBridge callers.

### EventBus `publish` call pattern
**Source:** `packages/api/src/api/routes/risk.py` lines 147-152
**Apply to:** `bridge.py` (publish DegradedStateEvent on disconnect)
```python
await bus.publish(
    TOPIC_DEGRADED_STATE,
    DegradedStateEvent(
        topic=TOPIC_DEGRADED_STATE,
        emitted_at=datetime.now(tz=timezone.utc),
        source="tv_bridge",
        reason=reason,
    ),
)
```

### `from __future__ import annotations`
**Source:** Every `.py` file in this codebase
**Apply to:** All Phase 6 Python files — always the first non-comment line.

### `get_store(request)` dependency in routes
**Source:** `packages/api/src/api/deps.py` lines 23-25
**Apply to:** `packages/api/src/api/routes/tv.py`
```python
from api.deps import get_store
store: DuckDBStore = get_store(request)
```

---

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `packages/tv-bridge/src/tv_bridge/shapes.py` | utility | transform | No existing draw-payload builder in codebase; pure-function structure modeled on indicator modules |

Note: `shapes.py` has no direct analog but its module structure (no class, module-level constants, pure typed functions) should follow the hand-rolled indicator pattern in `packages/trading-core/src/trading_core/indicators/`.

---

## Metadata

**Analog search scope:** `packages/trading-core/`, `packages/api/`, `packages/tv-bridge/`
**Files scanned:** 18 source files read
**Key observations:**
- The `stdio_client` + `ClientSession` + `_parse_tool_payload` block from `tradingview.py` is the single most reusable excerpt — `bridge.py` and `replay.py` both copy it
- `risk.py` routes are the canonical template for any new `async def` FastAPI route that reads `app.state` and calls `write_audit_event`
- `schema.sql` follows a strict consistent style: `IF NOT EXISTS`, `TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP`, uuid7 `VARCHAR PRIMARY KEY`, soft FKs as comments
- The `EodScheduler` + lifespan task pattern in `app.py` is the exact template for `ReconciliationScheduler`
- `DuckDBStore` module-level SQL constants + keyword-only method signatures are mandatory for new store methods
