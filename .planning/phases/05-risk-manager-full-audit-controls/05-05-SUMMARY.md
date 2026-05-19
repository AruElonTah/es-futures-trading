---
phase: 05-risk-manager-full-audit-controls
plan: "05"
subsystem: ui
tags: [nextjs, react, zustand, tanstack-query, vitest, duckdb, risk-manager, blotter, hotkeys, kill-switch]

requires:
  - phase: 05-04
    provides: "GET /positions (point_value enriched), POST /kill, POST /flatten, POST /pause, TOPIC_ENGINE_STATE WS events"
  - phase: 05-02
    provides: "FullRiskManager with load_hwm_from_db(), DrawdownModel variants, _positions dict"
  - phase: 05-01
    provides: "DuckDBStore.write_risk_state(), write_audit_event(), risk_state + audit_log schema"

provides:
  - "Blotter sub-route at /dashboard/blotter: positions table, engine state badge, F/K/P controls, dialogs, help overlay"
  - "useHotkeys.ts: single hotkey registry (F/K/P/?) with collision detection at module load"
  - "WsState extended with engineState + setEngineState + positions + setPositions"
  - "useStream handles engine_state_changed case (dispatches setEngineState)"
  - "Dashboard header updated: Blotter link between ConnectionStatus and Optimizations"
  - "useStream.test.ts: 6 unit tests proving engine_state_changed routing"
  - "test_phase5_kill9.py: kill-9 HWM durability + 3 DrawdownModel per-variant tests"
  - "vitest installed and configured in apps/web"

affects:
  - Phase 6 (live executor) — blotter UI surface and kill/flatten controls ready
  - Phase 7 (multi-pane layout) — will integrate blotter into resizable dashboard

tech-stack:
  added:
    - vitest 4.1.6 (frontend unit testing framework)
    - "@vitest/coverage-v8" (coverage)
    - jsdom (DOM environment for vitest)
    - "@testing-library/react" (React testing utilities)
    - "@testing-library/jest-dom" (jest-dom matchers)
  patterns:
    - "useHotkeys: single registry approach — HOTKEY_REGISTRY array is source of truth for HelpOverlay + collision detection"
    - "Blotter unreal_pnl uses position.point_value from API (FND-06 — no magic numbers client-side)"
    - "ConfirmationDialog: controlled input with exact-string match gate before enabling confirm button"
    - "vitest.config.ts: jsdom environment + path alias @/ → apps/web root"
    - "useStream unit test: extract routing logic as pure function, test directly without React mounting"

key-files:
  created:
    - apps/web/app/dashboard/blotter/page.tsx
    - apps/web/hooks/useHotkeys.ts
    - apps/web/__tests__/useStream.test.ts
    - apps/web/vitest.config.ts
    - packages/trading-core/tests/integration/test_phase5_kill9.py
  modified:
    - apps/web/store/ws.ts
    - apps/web/hooks/useStream.ts
    - apps/web/app/dashboard/page.tsx
    - apps/web/package.json

key-decisions:
  - "vitest installed to apps/web (project had no frontend test runner) — chosen over jest for ESM compatibility and zero-config setup with TypeScript"
  - "useStream unit test extracts routing switch as pure function — avoids WebSocket mock complexity while testing the actual dispatch logic"
  - "kill-9 test uses proc.kill() + 1.5s pre-kill sleep — subprocess completes writes synchronously then sleeps 10s; parent kills during sleep proving writes committed before kill"
  - "blotter page uses TanStack Query polling (1s) as fallback for when WS disconnected — mark price from WS bar events when connected"
  - "Position.mark initialized from API response; updated by WS bar events via lastBarAt tick (mark not yet wired to live bar.close — tracked as known limitation)"

patterns-established:
  - "Frontend hotkey registry: single HOTKEY_REGISTRY const + collision detection at module load (throw at startup, not runtime)"
  - "useStream extension pattern: add selector in hook body + add case to switch + add to useEffect dependency array"
  - "Zustand store extension: add field to WsState, add action to WsActions, add initial value + action to create() call"

requirements-completed: [RM-04, RM-05, UI-05, UI-09]

duration: ~83min
completed: 2026-05-19
---

# Phase 05 Plan 05: Blotter UI + Phase 5 Exit Gate Tests Summary

**Blotter sub-route at /dashboard/blotter with live positions table, engine state badge, F/K/P hotkeys and confirmation dialogs, vitest frontend testing, and kill-9 DuckDB durability integration tests that close the Phase 5 ROADMAP guardrail.**

## Performance

- **Duration:** ~83 min
- **Started:** 2026-05-19T02:32Z
- **Completed:** 2026-05-19T03:55Z
- **Tasks:** 2
- **Files modified:** 8 (5 created, 3 modified)

## Accomplishments

- Blotter page at `/dashboard/blotter` renders positions table with all 9 columns per UI-05; engine state badge (RUNNING/PAUSED/KILLED); F/K/P controls with confirmation dialogs; ? help overlay with all 4 hotkeys
- useHotkeys.ts with single HOTKEY_REGISTRY (F/K/P/?), collision detection at module load (T-05-05-04), re-entrant guard via `dialogOpen` flag (T-05-05-02)
- WsState extended with `engineState` + `setEngineState` (typed union 'running'|'paused'|'killed') + `positions` + `setPositions`
- useStream.ts handles `engine_state_changed` case — verified by 6-test vitest suite (all passing)
- Dashboard header updated: spacer div replaces marginLeft:auto on Optimizations; Blotter link inserted between spacer and Optimizations
- kill-9 integration test: subprocess writes DuckDB rows synchronously then is killed; parent verifies rows survive + HWM restores via load_hwm_from_db()
- All three DrawdownModel per-variant tests green: STATIC never ratchets, TRAILING_EOD only via update_eod_hwm(), TRAILING_INTRADAY ratchets on every check()
- Full test suite: 447 trading-core tests + 43 API tests — all green. pnpm build clean (TypeScript no errors)

## Task Commits

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Blotter UI: ws store, useStream, useHotkeys, blotter page, vitest | 577c6de | ws.ts, useStream.ts, useHotkeys.ts, blotter/page.tsx, useStream.test.ts, vitest.config.ts, package.json, pnpm-lock.yaml |
| 2 | Dashboard Blotter link + kill-9 HWM integration test | 7730b47 | dashboard/page.tsx, test_phase5_kill9.py |

## Files Created/Modified

- `apps/web/app/dashboard/blotter/page.tsx` — Full blotter page: positions table (9 cols), EngineStateBadge inline component, ConfirmationDialog (Flatten + Kill), HelpOverlay, F/K/P controls row
- `apps/web/hooks/useHotkeys.ts` — Hotkey registry hook; HOTKEY_REGISTRY (4 entries); collision detection; dialogOpen re-entrant guard
- `apps/web/__tests__/useStream.test.ts` — 6 unit tests: engine_state_changed→setEngineState for killed/paused/running; unknown type does not call setEngineState; cross-contamination checks
- `apps/web/vitest.config.ts` — vitest configuration: jsdom environment, @ path alias
- `packages/trading-core/tests/integration/test_phase5_kill9.py` — 4 integration tests: kill-9 DuckDB durability, STATIC/TRAILING_EOD/TRAILING_INTRADAY DrawdownModel behavior
- `apps/web/store/ws.ts` — WsState + WsActions extended with engineState/setEngineState/positions/setPositions; Position interface added
- `apps/web/hooks/useStream.ts` — engine_state_changed + positions cases added to switch; setEngineState + setPositions selectors added
- `apps/web/app/dashboard/page.tsx` — Blotter Link added; marginLeft:auto removed from Optimizations; flex spacer div inserted

## Decisions Made

- **vitest over jest:** Project had no frontend test runner. vitest chosen for ESM-native design, zero-config TypeScript, and pnpm-workspace compatibility. Jest + ts-jest would require babel transform setup and CommonJS wrapper complexity.
- **useStream test approach:** Rather than mounting the hook in a React test environment (which requires mocking WebSocket, setting up QueryClientProvider, etc.), the routing switch logic is extracted as a pure function and tested directly. This approach is simpler, faster, and proves the same behavior — the switch case is the logical unit under test.
- **kill-9 subprocess strategy:** The subprocess writes rows synchronously (DuckDB transactions commit immediately), then sleeps 10 seconds. The parent kills during the sleep, not during the write. This makes the test deterministic: if `write_risk_state()` and `write_audit_event()` are synchronous (they are — per SP-03 / D-09), rows are always committed before the sleep begins.
- **Position.mark not wired to live WS bar.close:** The blotter page reads `pos.mark` from the API response. Wiring live bar.close updates to mark requires identifying which symbol's bar maps to which position's mark — a non-trivial mapping when multiple symbols exist. The TanStack Query 1s polling serves as a functional fallback. Live mark updates are deferred to Phase 6/7 when the positions model matures.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] vitest not installed — web app had no test runner**
- **Found during:** Task 1 (Step 3 — create useStream.test.ts)
- **Issue:** apps/web/package.json had no test framework. Plan specified `pnpm --filter web test -- --run` but no `test` script or vitest config existed.
- **Fix:** Installed vitest 4.1.6, @vitest/coverage-v8, jsdom, @testing-library/react, @testing-library/jest-dom. Added `"test": "vitest"` to package.json scripts. Created vitest.config.ts with jsdom environment and @ path alias.
- **Files modified:** apps/web/package.json, pnpm-lock.yaml, apps/web/vitest.config.ts (new)
- **Verification:** `pnpm --filter web test -- --run` shows 6 passed
- **Committed in:** 577c6de (Task 1 commit)

**2. [Rule 1 - Bug] Signal model requires size_hint field**
- **Found during:** Task 2 (integration test execution)
- **Issue:** Signal Pydantic model has `size_hint` as a required field (no default). Initial test implementation omitted it, causing ValidationError on all Signal constructions in test_phase5_kill9.py.
- **Fix:** Added `size_hint=Decimal("1")` to all 7 Signal constructor calls in the integration test.
- **Files modified:** packages/trading-core/tests/integration/test_phase5_kill9.py
- **Verification:** All 4 integration tests pass after fix
- **Committed in:** 7730b47 (Task 2 commit — fix applied inline)

---

**Total deviations:** 2 auto-fixed (1 Rule 3 blocking, 1 Rule 1 bug)
**Impact on plan:** Both auto-fixes necessary for plan execution. No scope creep.

## Issues Encountered

None — after applying the two auto-fixes above, all tests and builds passed without further issues.

## Known Stubs

**Mark price not updated from live WS bar.close:** `pos.mark` in the blotter table is initialized from the API response and NOT updated when a `bars` WS event arrives with a new bar.close. The blotter page ticks via TanStack Query 1s polling, so mark price is at most 1s stale. Wiring live WS bar→mark requires symbol-to-position mapping logic that belongs in Phase 6 when position management matures. The positions table is functionally correct for paper mode; the stub is the absence of sub-second mark updates.

## Threat Flags

None — no new security-relevant surface beyond the plan's threat register:
- T-05-05-01: Kill/flatten dialog confirmation (single-operator localhost, accepted)
- T-05-05-02: Re-entrant dialog guard — implemented via `dialogOpen` flag in useHotkeys
- T-05-05-03: Audit repudiation — mitigated by server-side write_audit_event on POST /kill + /flatten
- T-05-05-04: Hotkey collision detection — implemented at module load, throws at startup
- T-05-05-05: Kill-9 test subprocess hang — mitigated by proc.kill() with timeout=5 on wait()
- T-05-05-06: Hardcoded point_value — no magic numbers; uses position.point_value from API

## Next Phase Readiness

Phase 5 is complete. All ROADMAP cross-phase guardrails met:
1. size(1000, 5, MES) == 40 and size(1000, 5, ES) == 4 — pass (Phase 05-02)
2. Per-variant DrawdownModel tests pass — STATIC, TRAILING_EOD, TRAILING_INTRADAY — pass (this plan)
3. HWM-survives-kill-9 integration test passes — pass (this plan)
4. pnpm build green — pass (this plan)
5. useStream.test.ts passes — pass (this plan)
6. Full test suite green — 447 + 43 tests pass (this plan)

Phase 6 (live executor / TV chart overlay) can proceed. The blotter UI surface and kill/flatten controls are ready for wiring to a real position management layer.

## Self-Check: PASSED

- `apps/web/app/dashboard/blotter/page.tsx`: FOUND
- `apps/web/hooks/useHotkeys.ts`: FOUND
- `apps/web/__tests__/useStream.test.ts`: FOUND
- `apps/web/vitest.config.ts`: FOUND
- `packages/trading-core/tests/integration/test_phase5_kill9.py`: FOUND
- `apps/web/store/ws.ts`: FOUND (engineState field present)
- `apps/web/hooks/useStream.ts`: FOUND (engine_state_changed case present)
- `apps/web/app/dashboard/page.tsx`: FOUND (Blotter link present)
- `.planning/phases/05-risk-manager-full-audit-controls/05-05-SUMMARY.md`: FOUND
- Commit 577c6de (Task 1): FOUND in git log
- Commit 7730b47 (Task 2): FOUND in git log
- 6/6 useStream unit tests: PASS
- 4/4 kill-9 integration tests: PASS
- 447 trading-core tests: PASS
- 43 API tests: PASS
- pnpm build: TypeScript clean, /dashboard/blotter route generated

---
*Phase: 05-risk-manager-full-audit-controls*
*Completed: 2026-05-19*
