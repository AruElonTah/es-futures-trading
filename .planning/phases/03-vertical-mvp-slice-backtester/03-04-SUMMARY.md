---
phase: 03-vertical-mvp-slice-backtester
plan: "04"
subsystem: api
tags:
  - fastapi
  - websocket
  - rest
  - event-bus
  - wave-4
  - ui-01
dependency_graph:
  requires:
    - 03-01-PLAN.md  # DuckDBStore.write_backtest, schema.sql (backtests table)
    - 03-02-PLAN.md  # EventBus, topic constants, ConnectionManager contract
    - 03-03-PLAN.md  # BacktestEngine already publishes to EventBus
  provides:
    - GET /bars (D-07 cold-load, Pydantic Query validation, T-03-04-01/02/03)
    - GET /backtests (D-01 listing, created_at DESC)
    - WS /stream (D-04 7-topic mirror, D-05 envelope, D-06 per-client asyncio.Queue)
    - ConnectionManager (fan-out, no broadcaster dep)
    - FastAPI app lifespan (DuckDBStore + EventBus + ConnectionManager singleton management)
  affects:
    - 03-05-PLAN.md  # dashboard consumes /bars + /backtests + /stream
tech_stack:
  added:
    - FastAPI asynccontextmanager lifespan (DuckDBStore + EventBus + ConnectionManager lifecycle)
    - asyncio.Queue per-client WebSocket fan-out (D-06)
    - Pydantic Literal validators on Query params (symbol/tf) + Query(ge=1, le=10_000) (T-03-04-01/03)
    - parameterized DuckDB queries in route handlers (T-03-04-02)
  patterns:
    - WS fan-out via asyncio.gather over 7 _subscribe_topic coroutines
    - D-05 envelope: {"type": event.topic, "payload": event.model_dump(mode="json")}
    - conftest.make_test_app factory with module-level WebSocket import (FastAPI type-hint resolution fix)
    - asyncio.get_event_loop().run_until_complete() for publishing in sync TestClient WS tests
key_files:
  created:
    - packages/api/src/api/deps.py
    - packages/api/src/api/routes/__init__.py
    - packages/api/src/api/routes/bars.py
    - packages/api/src/api/routes/backtests.py
    - packages/api/src/api/ws.py
    - packages/api/tests/test_routes.py
    - packages/api/tests/test_ws_stream.py
  modified:
    - packages/api/src/api/app.py
    - packages/api/tests/test_health.py
    - packages/api/tests/conftest.py
decisions:
  - "Phase 1 test_only_health_endpoint_registered renamed to test_phase3_endpoints_registered; assertion updated to accept /backtests, /bars, /health, /stream"
  - "WebSocket/WebSocketDisconnect imported at conftest module level (not inside make_test_app closure) to fix FastAPI __globals__-based type-hint resolution under --import-mode=importlib"
  - "Multi-client WS test uses two websocket_connect() calls on the same TestClient instance; two nested TestClient(app) contexts would deadlock on shared lifespan"
  - "TOPIC_BARS (BarReceived) and TOPIC_DEGRADED_STATE (DegradedStateEvent) exercised in test_ws_stream_topic_mirror; 5 other topics have no concrete Event subclass in Phase 3"
  - "Event.topic field duplication in D-05 payload is acceptable for v1 (topic appears as envelope type AND as payload.topic); Phase 7 may flatten"
metrics:
  duration: "~35 minutes (including TDD RED+GREEN cycles, conftest type-hint debug)"
  completed_date: "2026-05-17"
  task_count: 2
  file_count: 10
---

# Phase 03 Plan 04: FastAPI REST + WS /stream Surface Summary

**One-liner:** FastAPI GET /bars + GET /backtests REST endpoints with Pydantic Query validation (T-03-04-01/02/03) and WS /stream with 7-topic asyncio.Queue fan-out (D-04/D-05/D-06), completing the UI-01 operator-facing surface.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 RED | REST endpoint failing tests | eda026b | packages/api/tests/test_routes.py |
| 1 GREEN | REST endpoints + Phase 3 app.py | 4e1c8b6 | deps.py, routes/__init__.py, routes/bars.py, routes/backtests.py, ws.py, app.py, test_health.py |
| 2 GREEN | WS /stream tests + conftest factory | f9006c8 | test_ws_stream.py, conftest.py, test_routes.py (factory refactor) |

## Implementation Notes

### GET /bars (D-07 Cold-Load)

Route: `GET /bars?symbol=SPY&tf=1m&limit=390` returning `list[dict]`.

**Pydantic Query validation (T-03-04-01):**
- `symbol: Literal["ES", "MES", "SPY"]` — rejects any other symbol with HTTP 422
- `tf: Literal["1m", "5m", "15m"]` — rejects non-whitelisted timeframes with HTTP 422
- `limit: int, Query(ge=1, le=10_000)` — rejects out-of-range limits with HTTP 422

**SQL injection defense (T-03-04-02):** Parameterized `?` placeholders prevent injection even if Pydantic is bypassed. SQL injection via symbol is blocked first by the Literal whitelist (422), then by parameterized query.

**Query pattern:** `ORDER BY ts_utc DESC LIMIT ?` to get most-recent N bars, then reversed in Python to return ASC for chronological chart display (D-07).

### GET /backtests (D-01)

Route: `GET /backtests` returning all `backtests` table rows `ORDER BY created_at DESC`. No query params in Phase 3. TIMESTAMPTZ values coerced to ISO 8601 strings; nullable metrics serialized as JSON `null`.

### WS /stream (D-04, D-05, D-06, SP-01)

**ConnectionManager:**
- `connect(ws)`: `await ws.accept()`, allocate `asyncio.Queue`, add to `_clients` set, return queue
- `disconnect(q)`: `_clients.discard(q)` — no error if absent
- `start_background_fan_out()`: `asyncio.gather` over 7 `_subscribe_topic(topic)` coroutines; each subscribes to the EventBus and puts `json.dumps({"type": event.topic, "payload": event.model_dump(mode="json")})` onto every client queue

**D-05 envelope:** `{"type": "<topic>", "payload": <serialized event>}`. `event.topic` field appears twice — once as the envelope `type`, once inside `payload.topic`. This duplication is acceptable for v1 and documented; Phase 7 may flatten.

**D-06:** No `broadcaster` dependency. Pure `asyncio.Queue` per client.

**Lifespan:** `asyncio.create_task(manager.start_background_fan_out())` on startup; `task.cancel()` + `try/except CancelledError` on shutdown.

### Phase 1 → Phase 3 Deviation on test_only_health_endpoint_registered

**Original (Phase 1):** `test_only_health_endpoint_registered` asserted `user_paths == ["/health"]`.

**Updated (Phase 3):** Renamed to `test_phase3_endpoints_registered`; assertion updated to `user_paths == ["/backtests", "/bars", "/health", "/stream"]`. The intent (guard against unexpected endpoints) is preserved; the expected set is expanded for Phase 3. Comment added: `# Plan 03-04 expanded the Phase 1 surface — see 03-04-PLAN.md Task 1.`

### 7-Topic Coverage in test_ws_stream_all_7_topics_mirror

Only **2 of 7 topics** have concrete Event subclasses in Phase 3:

| Topic | Concrete Class | Tested |
|-------|---------------|--------|
| `TOPIC_BARS` | `BarReceived` | YES |
| `TOPIC_DEGRADED_STATE` | `DegradedStateEvent` | YES |
| `TOPIC_SIGNALS` | None (stub) | Not exercised (no concrete class) |
| `TOPIC_RISK_DECISIONS` | None (stub) | Not exercised (no concrete class) |
| `TOPIC_FILLS` | None (stub) | Not exercised (no concrete class) |
| `TOPIC_POSITIONS` | None (stub) | Not exercised (no concrete class) |
| `TOPIC_EQUITY` | None (stub) | Not exercised (no concrete class) |

The `ConnectionManager` is topic-agnostic — it serializes any `Event` subclass. All 7 subscriptions are registered in `start_background_fan_out`. The 5 unexercised topics will gain concrete classes in Phase 2 (signals) and Phase 5 (risk/fills/positions/equity), and tests can be extended then.

### conftest.py Type-Hint Resolution Fix

**Issue (Rule 1 auto-fix):** When `conftest.py` is loaded by pytest under `--import-mode=importlib`, the `ws_stream` handler inside `make_test_app` had `websocket: WebSocket` with `WebSocket` imported *inside* the closure. FastAPI uses `typing.get_type_hints(endpoint)` which resolves forward-reference strings against `endpoint.__globals__` (= conftest module globals). Since `WebSocket` was only in the closure's local scope, not conftest's module globals, resolution failed and FastAPI treated `websocket` as a required Query parameter (HTTP 422).

**Fix:** `WebSocket` and `WebSocketDisconnect` imported at conftest module level. The handler closure's `__globals__` now contains `WebSocket`, resolving the type hint correctly.

## Test Results

```
374 passed, 1 skipped in 373.05s
```

- 11 new tests in `test_routes.py` (GET /bars + GET /backtests)
- 7 new tests in `test_ws_stream.py` (WS /stream D-04/D-05/D-06)
- 4 existing tests in `test_health.py` (1 renamed, assertion updated)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] FastAPI type-hint resolution failure for WebSocket in conftest factory**
- **Found during:** Task 2 GREEN (first WS test run)
- **Issue:** `WebSocket` imported inside `make_test_app` closure not visible in conftest `__globals__`; FastAPI treated `websocket: WebSocket` as a required Query parameter → HTTP 1008 close on connect
- **Fix:** Moved `WebSocket` and `WebSocketDisconnect` imports to conftest module level. Added explanation comment in conftest.
- **Files modified:** `packages/api/tests/conftest.py`
- **Commit:** f9006c8

**2. [Rule 1 - Bug] Multi-client WS test deadlock with nested TestClient(app) contexts**
- **Found during:** Task 2 test suite (test hanging)
- **Issue:** Two `TestClient(app)` instances sharing the same `app` with lifespan caused a deadlock when the second `TestClient.__enter__` tried to re-enter the lifespan while it was active.
- **Fix:** Changed multi-client test to open two `client.websocket_connect("/stream")` calls on the SAME `TestClient` instance. Single lifespan, two concurrent WS connections.
- **Files modified:** `packages/api/tests/test_ws_stream.py`
- **Commit:** f9006c8

### Plan Deviation (Documented)

**3. [Documented] `_make_test_app` moved from inline in test_routes.py to conftest.make_test_app**
- **Original plan:** Inline `_make_test_app(duckdb_path)` helper in `test_routes.py`; test_ws_stream.py imports it from test_routes.
- **Issue:** Under `--import-mode=importlib`, `test_routes` is not importable as a Python module from `test_ws_stream.py`.
- **Change:** Canonical factory lives in `conftest.py` as `make_test_app()`. Both test files use an `importlib.import_module("conftest")` delegate wrapper.

## Known Stubs

None. All plan artifacts are fully implemented and returning real data from DuckDB.

## Threat Flags

All threats from the STRIDE register mitigated:
- T-03-04-01 (symbol/tf injection): Pydantic Literal validators → HTTP 422
- T-03-04-02 (SQL injection): parameterized `?` placeholders in bars.py + backtests.py
- T-03-04-03 (DoS limit): `Query(ge=1, le=10_000)` on limit parameter
- T-03-04-05 (field leakage): `model_dump(mode="json")` on declared-field Pydantic models
- T-03-04-04 and T-03-04-06 accepted per plan

## Self-Check: PASSED

Files verified:
- `packages/api/src/api/deps.py`: FOUND
- `packages/api/src/api/routes/__init__.py`: FOUND
- `packages/api/src/api/routes/bars.py`: FOUND
- `packages/api/src/api/routes/backtests.py`: FOUND
- `packages/api/src/api/ws.py`: FOUND
- `packages/api/tests/test_routes.py`: FOUND
- `packages/api/tests/test_ws_stream.py`: FOUND

Commits verified:
- `eda026b` (RED tests): FOUND
- `4e1c8b6` (GREEN routes + app): FOUND
- `f9006c8` (WS tests + conftest): FOUND

Test suite: 374 passed, 1 skipped.
