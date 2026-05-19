---
phase: "06"
plan: "02"
subsystem: tv-bridge
tags: [tv-bridge, mcp, asyncio, supervisor-loop, draw-shapes, rest-routes, fastapi]
dependency_graph:
  requires: [06-01]
  provides: [tv_bridge.bridge supervisor loop, shapes.py payload builders, safe-draw engine, TV REST routes]
  affects: [packages/tv-bridge, packages/api]
tech_stack:
  added: [asyncio supervisor loop, asyncio.timeout, asyncio.Semaphore, MCP stdio_client]
  patterns: [exponential backoff reconnect, fire-and-forget draw via create_task, 200-shape cap enforcement, Pydantic v2 field_validator, soft-delete tv_alerts]
key_files:
  created:
    - packages/tv-bridge/src/tv_bridge/shapes.py
    - packages/api/src/api/routes/tv.py
  modified:
    - packages/tv-bridge/src/tv_bridge/bridge.py
    - packages/tv-bridge/tests/conftest.py
    - packages/tv-bridge/tests/test_bridge.py
    - packages/tv-bridge/tests/test_overlay_registry.py
    - packages/api/src/api/app.py
    - packages/api/tests/test_health.py
    - packages/api/tests/test_tv_routes.py
decisions:
  - "asyncio.Future() idiom holds stdio_client context manager alive in supervisor loop — avoids context-exit tearing session on reconnect"
  - "asyncio.timeout(5.0) rather than asyncio.wait_for for draw cancellation — cleaner stack, same semantics"
  - "Real EventBus in conftest bridge fixture (not MockBus) — subscriber tasks call bus.subscribe() which requires the real lock protocol"
  - "fire-and-forget draw via asyncio.create_task ensures bus.publish returns in <100ms regardless of MCP latency"
  - "200-shape cap checked inside _draw_semaphore to prevent concurrent overcounts at the boundary"
  - "TV routes use 202 Accepted for POST /tv/focus (fire-and-forget) and 201 Created for POST /tv/alerts (synchronous persist)"
metrics:
  duration: "~2 hours (re-execution)"
  completed: "2026-05-19"
  tasks: 3
  files_created: 2
  files_modified: 7
---

# Phase 06 Plan 02: TVBridge Drawing Engine + TV REST Routes Summary

TVBridge full supervisor loop with capped exponential backoff, fire-and-forget signal drawing (4 shape kinds), 200-shape cap enforcement, and 4 TV REST routes (/tv/focus, /tv/alerts, DELETE /tv/alerts/{id}, /tv/status).

## Tasks Completed

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| 1 | shapes.py + supervisor loop | 49b6642 | shapes.py, bridge.py (_supervisor_loop) |
| 2 | Bus subscribers + safe-draw + overlay registry | 489fc46 | bridge.py (_subscribe_signals/_fills, _safe_draw_signal), test_overlay_registry.py |
| 3 | TV REST routes + app wiring + test conversion | 622d4fc | api/routes/tv.py, app.py, test_tv_routes.py, test_health.py |

## What Was Built

### Task 1: shapes.py + Supervisor Loop (49b6642)

**`packages/tv-bridge/src/tv_bridge/shapes.py`** — 4 pure-function MCP payload builders:
- `entry_arrow_args(side, entry_price, signal_id)` — horizontal_line in green (long) or red (short), text capped to 64 chars
- `stop_line_args(stop_price, signal_id)` — dashed red horizontal_line
- `target_line_args(target_price, signal_id)` — dashed blue horizontal_line
- `orb_box_args(orb_high, orb_low, session_open_ts, orb_end_ts)` — gold rectangle with 20% opacity fill

All numeric args coerced via `float()` / `int()` at boundary — no Decimal leaking to JSON.

**`bridge.py` — `_supervisor_loop()`**:
- Opens MCP session via `stdio_client` + `ClientSession` with `asyncio.Future()` hold pattern
- Health-gate: calls `health_check` MCP tool; if `api_available=False` raises `RuntimeError`
- On RuntimeError: publishes `DegradedStateEvent` to bus, sleeps `_BACKOFF_SECONDS[attempt % 6]` (= [1,2,4,8,16,30])
- On clean exit: resets attempt counter
- `_BACKOFF_SECONDS = [1, 2, 4, 8, 16, 30]` class attribute

### Task 2: Bus Subscribers + Safe Draw + Overlay Registry (489fc46)

**`bridge.py` — subscriber tasks**:
- `_subscribe_signals()` — async for Signal events on TOPIC_SIGNALS; dispatches `asyncio.create_task(_safe_draw_signal(signal))` (fire-and-forget)
- `_subscribe_fills()` — async for Fill events on TOPIC_FILLS; dispatches fill-draw tasks (stub for Plan 04)
- `start()` now creates 3 tasks: supervisor + sig_sub + fill_sub

**`_safe_draw_signal(signal)`**:
- Acquires `_draw_semaphore` (3-concurrent limit)
- Calls `count_active_overlays()` → if >= 200: writes audit_log row (topic='tv_draw_refused'), returns
- Wraps 4 draw calls inside `asyncio.timeout(5.0)`: entry_arrow, stop_line, target_line, orb_box_if_new
- On TimeoutError: writes audit_log row (topic='tv_draw_timeout', reason_code='draw_timeout')
- Each successful draw_shape call → `_record_overlay(...)` → `store.write_tv_overlay(...)`

**`_record_overlay(signal_id, shape_kind, entity_id)`** calls `store.write_tv_overlay` with all required fields.

**`conftest.py`** — `bridge` fixture updated to use real `EventBus()` instead of `_MockBus` (subscriber tasks require real `bus.subscribe()` lock protocol).

**`test_overlay_registry.py`** — `test_write_overlay` and `test_cap_enforcement` converted from xfail to real tests.

### Task 3: TV REST Routes + App Wiring (622d4fc)

**`packages/api/src/api/routes/tv.py`** — 4 routes with security mitigations:
- `POST /tv/focus` (202): Pydantic `@field_validator` on symbol (allowlist: ES/MES/SPY → 422) and date (ISO parse → 422). Fire-and-forget via `asyncio.create_task(bridge.focus(...))`. Returns in <200ms regardless of chart load time. 503 if bridge absent.
- `POST /tv/alerts` (201): Awaits `bridge.create_alert(condition, message)`. Writes `tv_alerts` row + audit_log row (T-06-02-07 repudiation). Returns `{alert_id, tv_alert_id}`.
- `DELETE /tv/alerts/{alert_id}` (200): Looks up `tv_alert_id` from DuckDB (404 if not found). Calls `bridge.delete_alert`. Marks row deleted (`deleted_at`). Writes audit_log.
- `GET /tv/status` (200): Returns `{connected: bool, last_error: null}`. Safe against missing bridge.

**`api/app.py`**:
- Added `from api.routes import tv as tv_routes`
- Added `app.include_router(tv_routes.router)` after risk_routes
- Expanded CORS `allow_methods` to include `DELETE` (was `["GET", "POST", "OPTIONS"]`)

**Tests converted from xfail**:
- `test_tv_routes.py::test_tv_focus` — 202 happy path, 422 invalid symbol, 422 invalid date, 503 no bridge
- `test_tv_routes.py::test_create_delete_alert` — POST→201, DuckDB row verified, DELETE→200, deleted_at set
- `test_tv_routes.py::test_tv_status_when_disconnected` — `{connected: false}`
- `test_bridge.py::test_focus_call_sequence` — 3 calls in order: chart_set_symbol → chart_set_timeframe → chart_scroll_to_date
- `test_health.py::test_phase3_endpoints_registered` — expanded expected set to include 4 TV routes

## Verification

Final test run: **61 passed, 1 skipped, 1 xfailed in 18.49s**

The 1 xfailed is an intentional pre-existing stub (not from this plan). The 1 skipped is a platform-conditional test.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] conftest bridge fixture used MockBus lacking subscribe()**
- **Found during:** Task 2 implementation
- **Issue:** `start()` creates `_subscribe_signals()` / `_subscribe_fills()` tasks that call `self._bus.subscribe(topic)`. The conftest `_MockBus` only implemented `publish()` — subscriber tasks raised `AttributeError` on construction.
- **Fix:** Updated `conftest.py` `bridge` fixture to use `EventBus()` (real bus) instead of `_MockBus`.
- **Files modified:** `packages/tv-bridge/tests/conftest.py`
- **Commit:** 489fc46

**2. [Rule 1 - Bug] asyncio.sleep recursion in test_reconnect**
- **Found during:** Task 1 testing
- **Issue:** Patch `asyncio.sleep` with a tracked wrapper that internally called `asyncio.sleep(0.01)` — infinite recursion because the patch replaced the module-level reference the wrapper itself used.
- **Fix:** Captured `original_sleep = asyncio.sleep` before the patch context, then used `await original_sleep(0.001)` inside `_tracked_sleep`.
- **Files modified:** `packages/tv-bridge/tests/test_bridge.py`
- **Commit:** 49b6642

**3. [Rule 1 - Bug] Signal field names entry/stop/target vs entry_price/stop_price/target_price**
- **Found during:** Task 2 implementation
- **Issue:** Plan referenced `signal.entry_price`, `signal.stop_price`, `signal.target_price` but the actual `Signal` model uses `entry`, `stop`, `target` (Decimal fields).
- **Fix:** Used `float(signal.entry)`, `float(signal.stop)`, `float(signal.target)` in all bridge draw helpers.
- **Files modified:** `packages/tv-bridge/src/tv_bridge/bridge.py`
- **Commit:** 489fc46

**4. [Rule 2 - Missing] CORS DELETE method not in allow_methods**
- **Found during:** Task 3 — DELETE /tv/alerts/{alert_id} route required DELETE HTTP method
- **Issue:** `app.py` CORS config was `["GET", "POST", "OPTIONS"]` — DELETE requests would be blocked by preflight.
- **Fix:** Expanded to `["GET", "POST", "DELETE", "OPTIONS"]`.
- **Files modified:** `packages/api/src/api/app.py`
- **Commit:** 622d4fc

**5. [Rule 3 - Blocking] test_health.py endpoint assertion did not include TV routes**
- **Found during:** Task 3 — adding `tv_routes.router` to `app.py` caused `test_phase3_endpoints_registered` to fail
- **Fix:** Added `/tv/focus`, `/tv/alerts`, `/tv/alerts/{alert_id}`, `/tv/status` to the expected sorted list.
- **Files modified:** `packages/api/tests/test_health.py`
- **Commit:** 622d4fc

## Known Stubs

None — all 4 draw helpers produce real MCP payloads. The `_subscribe_fills()` draw task is a deliberate Phase 04 deferral (fills draw is out of scope for Plan 02) and does not affect any user-visible behavior.

## Threat Flags

No new security-relevant surface beyond what the plan's threat model covered. Mitigations T-06-02-05 (symbol allowlist), T-06-02-06 (ISO date validation), and T-06-02-07 (audit repudiation) are all implemented.

## Self-Check: PASSED

- `packages/tv-bridge/src/tv_bridge/shapes.py` — FOUND
- `packages/api/src/api/routes/tv.py` — FOUND
- Commit 49b6642 — FOUND
- Commit 489fc46 — FOUND
- Commit 622d4fc — FOUND
- Test suite: 61 passed, 1 skipped, 1 xfailed
