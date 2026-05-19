---
phase: 05-risk-manager-full-audit-controls
plan: "04"
subsystem: api-risk-controls
tags: [fastapi, risk, kill-switch, flatten, eod-scheduler, cors, blotter, instruments]
dependency_graph:
  requires:
    - FullRiskManager._positions dict + set_killed() + load_hwm_from_db() + load_kill_state_from_db() (05-02)
    - DuckDBStore.write_engine_state() / get_engine_state() / write_audit_event() (05-01)
    - EventBus.publish(TOPIC_ENGINE_STATE, ...) + publish_engine_state() helper (05-03)
    - TOPIC_ENGINE_STATE from events/models.py (05-01)
    - instruments.get(symbol).point_value from instruments.REGISTRY (Phase 1)
    - new_run_id() from storage/runs.py (Phase 1)
    - RiskConfig / DrawdownModel from risk/models.py (05-01)
  provides:
    - GET /positions — UI-05 blotter data source (point_value enriched, FND-06)
    - POST /kill — SP-05 kill switch with asyncio.Event gate (D-10, D-12)
    - POST /flatten — SP-05 flatten command, no-op when empty (D-12)
    - POST /pause — toggle engine pause/resume state
    - EodScheduler — wall-clock asyncio task firing at session_close - 60s (RM-07)
    - FullRiskManager singleton on app.state.risk_manager (HWM + kill-state bootstrapped)
    - CORS POST allowed (previously GET-only)
    - TOPIC_ENGINE_STATE in ws.py fan-out
  affects:
    - Phase 5 Plan 05 (blotter frontend) consumes GET /positions + WS engine_state events
    - Phase 6 (live executor) will wire EodScheduler on_flatten to real position close
tech_stack:
  added:
    - pyyaml (runtime dep, used to load config/risk.yaml in lifespan)
  patterns:
    - EodScheduler: wall-clock asyncio.sleep + ZoneInfo DST-correct fire time calculation
    - _get_rm() helper: getattr guard for optional risk_manager on app.state
    - Plain dict publish on TOPIC_ENGINE_STATE; ws.py fan-out now handles both Event objects and dicts
    - FullRiskManager singleton created in lifespan from YAML-loaded RiskConfig
    - Risk endpoint session_id derived from rm._session_id for audit trail grouping
key_files:
  created:
    - packages/trading-core/src/trading_core/execution/eod_scheduler.py
    - packages/api/src/api/routes/risk.py
  modified:
    - packages/api/src/api/app.py
    - packages/api/src/api/ws.py
    - packages/api/tests/test_health.py
key_decisions:
  - "EodScheduler does not check market calendars — paper-mode flatten on non-trading day is harmless no-op; calendar enforcement is Phase 6+"
  - "TOPIC_ENGINE_STATE fan-out in ws.py handles both pydantic Event objects (model_dump) and plain dicts (already-enveloped); isinstance(event, dict) branch added"
  - "FullRiskManager singleton uses symbol='MES' matching the ROADMAP-locked default instrument; Phase 6 makes this configurable"
  - "POST /flatten writes flatten_requested state then immediately writes running again — flatten is a momentary request, not a persistent state"
  - "POST /pause reads current state from DuckDB to determine toggle direction — source of truth for toggle is persisted state, not in-memory"
  - "test_health.py route guard updated from Phase 4 to Phase 5 expected route set (Rule 1 auto-fix)"

requirements-completed: [RM-05, RM-07, SP-02, SP-05, UI-05]

duration: ~22min
completed: 2026-05-18
---

# Phase 05 Plan 04: Risk API Routes + EOD Scheduler Summary

**FastAPI kill/flatten/pause controls + blotter positions endpoint wired to FullRiskManager, with CORS POST enabled, HWM+kill-state bootstrap from DuckDB on startup, and wall-clock EOD scheduler asyncio task.**

## Performance

- **Duration:** ~22 min
- **Started:** 2026-05-18T19:10Z
- **Completed:** 2026-05-18T19:32Z
- **Tasks:** 2
- **Files modified:** 5 (2 created, 3 modified)

## Accomplishments

- GET /positions returns open positions enriched with server-side `point_value` from instruments registry (FND-06 — no magic numbers client-side)
- POST /kill activates kill switch even with no positions (D-12), writes audit record + sets asyncio.Event (D-10)
- POST /flatten is no-op when no positions (D-12); still writes audit record for non-repudiation (T-05-04-02)
- POST /pause toggles running/paused; keeps asyncio.Event in sync via set_killed()
- EodScheduler fires at 15:59:00 ET (16:00 - 60s) daily; DST-correct via ZoneInfo; no market-calendar dependency (Phase 6+)
- FullRiskManager singleton bootstrapped from `config/risk.yaml` on lifespan startup; HWM from yesterday's DuckDB row (D-08); kill-state from DuckDB engine_state (D-10)
- CORS allow_methods expanded to include POST (T-05-04-04 accepted)
- TOPIC_ENGINE_STATE added to WebSocket fan-out; dict-payload handling added for non-Event publish calls

## Task Commits

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Create EodScheduler + risk.py routes | cdfcafd | execution/eod_scheduler.py, routes/risk.py |
| 2 | Wire risk router + CORS + HWM bootstrap + EOD scheduler into app.py | 89cd000 | app.py, ws.py, test_health.py |

## Files Created/Modified

- `packages/trading-core/src/trading_core/execution/eod_scheduler.py` — EodScheduler class; wall-clock asyncio fire loop with ZoneInfo DST-correct next-fire calculation
- `packages/api/src/api/routes/risk.py` — FastAPI router with GET /positions, POST /kill, POST /flatten, POST /pause; audit writes on every mutating route
- `packages/api/src/api/app.py` — CORS POST added; risk router included; FullRiskManager singleton + HWM/kill-state bootstrap in lifespan; EodScheduler task started and cancelled on shutdown
- `packages/api/src/api/ws.py` — TOPIC_ENGINE_STATE added to ALL_TOPICS fan-out; dict-payload branch added to handle non-Event publishes
- `packages/api/tests/test_health.py` — route guard updated from Phase 4 to Phase 5 expected routes (Rule 1 auto-fix)

## Decisions Made

- **EodScheduler no calendar check:** Paper-mode flatten on a non-trading day (holiday, weekend) is a no-op because `rm._positions` is empty. Calendar enforcement adds Phase 6+ complexity; not needed for paper mode.
- **Dict-aware WS fan-out:** `EventBus.publish()` accepts any payload type. POST /kill publishes a plain dict `{type, payload}` envelope already formatted for the client. The ws.py `_subscribe_topic` needed an `isinstance(event, dict)` branch to json.dumps it directly instead of calling `.topic` / `.model_dump()`.
- **POST /flatten writes running immediately after flatten_requested:** The "flatten_requested" state is transient (the executor hasn't actually closed positions yet in Phase 5). Writing "running" immediately avoids leaving the DB in a permanent "flatten_requested" state that would confuse the next startup's kill-state bootstrap.
- **app.state.risk_manager (not app.state.rm):** Used the more descriptive name to avoid collision with potential future `rm` abbreviations in the lifespan scope.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] test_health.py route guard rejected new Phase 5 endpoints**
- **Found during:** Task 2 (after adding risk_routes.router to app.py)
- **Issue:** `test_phase3_endpoints_registered` asserted exactly the Phase 4 route set and failed with `AssertionError` when the 4 new Phase 5 routes (/positions, /kill, /flatten, /pause) appeared.
- **Fix:** Updated the expected set in `test_phase3_endpoints_registered` to include all Phase 5 routes; updated docstring to reflect Phase 5. The test's intent (guard against unexpected endpoints) is preserved.
- **Files modified:** `packages/api/tests/test_health.py`
- **Verification:** `43 passed` after fix
- **Committed in:** 89cd000 (Task 2 commit)

**2. [Rule 2 - Missing Critical] TOPIC_ENGINE_STATE not in WebSocket fan-out**
- **Found during:** Task 2 (CHANGE 5 in plan)
- **Issue:** ws.py ALL_TOPICS only covered 7 topics and did not include TOPIC_ENGINE_STATE. Blotter panel would never receive kill/pause WS notifications. Additionally, the fan-out called `event.topic` and `event.model_dump()` which fail on plain dict payloads published by the risk routes.
- **Fix:** Added TOPIC_ENGINE_STATE to ALL_TOPICS; added `isinstance(event, dict)` branch in `_subscribe_topic` to handle both Event objects and pre-enveloped dicts.
- **Files modified:** `packages/api/src/api/ws.py`
- **Verification:** All 43 API tests pass; ws.py import verified
- **Committed in:** 89cd000 (Task 2 commit)

---

**Total deviations:** 2 auto-fixed (1 Rule 1 test bug, 1 Rule 2 missing WS topic)
**Impact on plan:** Both auto-fixes necessary for correctness. No scope creep.

## Issues Encountered

None — plan executed without blocking issues. The two deviations above were identified during implementation and fixed inline.

## Known Stubs

None — all endpoints return real data from `rm._positions` and DuckDB. The `_eod_flatten` callback in app.py is intentionally a no-op in Phase 5 (paper mode, no live positions), but is documented as such and writes an audit record on every fire.

## Threat Flags

None — no new threat surface beyond what the plan's threat register already covers:
- T-05-04-01: No auth on POST /kill/flatten/pause — accepted (single-operator localhost, CORS restricted)
- T-05-04-02: Audit repudiation — mitigated; all three routes write audit_log before returning
- T-05-04-04: CORS POST expansion — accepted per Phase 5 threat model
- T-05-04-06: Kill-switch Event not restored on restart — mitigated; load_kill_state_from_db() called in lifespan

## Self-Check: PASSED

- `packages/api/src/api/routes/risk.py`: FOUND (4 routes: GET /positions, POST /kill, POST /flatten, POST /pause)
- `packages/trading-core/src/trading_core/execution/eod_scheduler.py`: FOUND (EodScheduler with run() + _next_fire_time())
- `packages/api/src/api/app.py`: FOUND (CORS POST, risk_routes.router, FullRiskManager bootstrap, EodScheduler task)
- `packages/api/src/api/ws.py`: FOUND (TOPIC_ENGINE_STATE in ALL_TOPICS, dict-branch in fan-out)
- Commit cdfcafd (Task 1): FOUND in git log
- Commit 89cd000 (Task 2): FOUND in git log
- 43 API tests pass: Confirmed
- 443 trading-core tests pass: Confirmed (background job exit code 0)
- Import verification: `risk router: 4 routes`, `EodScheduler: <class>` — Confirmed
- GET /positions 200 with empty list: Confirmed
- POST /kill returns {state: 'killed', positions_held: 0}: Confirmed
- POST /flatten returns {positions_closed: 0}: Confirmed
- POST /pause returns {state: 'paused'}: Confirmed
