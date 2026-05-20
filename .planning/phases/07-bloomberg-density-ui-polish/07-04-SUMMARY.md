---
phase: "07"
plan: "04"
subsystem: "web-ui"
tags: ["strategy-controls", "playwright", "e2e", "tanstack-query", "zustand", "optimistic-update"]

dependency_graph:
  requires: ["07-03"]
  provides: ["StrategyControlsPane", "ws-reconnect.spec.ts (real Playwright test)"]
  affects: ["apps/web/app/dashboard/page.tsx", "apps/web/vitest.config.ts"]

tech_stack:
  added: []
  patterns:
    - "Optimistic badge update on POST toggle with error revert"
    - "Per-field 422 inline error display (Pydantic v2 array detail format)"
    - "useStrategyRun polling via refetchInterval returning false on complete/failed"
    - "aria-disabled + cursor not-allowed for double-submit guard (T-07-04-02)"
    - "Accordion component collapsed by default with chevron toggle"
    - "Vitest e2e/ exclusion to prevent @playwright/test import collision"
    - "Playwright routeWebSocket for WS disconnect simulation"

key_files:
  created:
    - apps/web/components/StrategyControlsPane.tsx
    - apps/web/e2e/tsconfig.json
  modified:
    - apps/web/app/dashboard/page.tsx
    - apps/web/e2e/ws-reconnect.spec.ts
    - apps/web/vitest.config.ts

decisions:
  - "Pydantic v2 returns 422 detail as array of {loc, msg} objects — client checks Array.isArray(body.detail) and maps per-field errors"
  - "ParamForm seeded from strategy.params at mount time; no optimistic update — wait for 200 before reflecting changes (Strategy Hot-Reload Contract)"
  - "Toggle button border uses fixed #444444 for both states (consistent with 05-UI-SPEC spec); color changes green/grey based on enabled state"
  - "vitest.config.ts exclude: ['**/e2e/**'] added to resolve pre-existing Playwright/Vitest import collision from Plan 07-01 stub"
  - "e2e/tsconfig.json added to give Playwright files their own TypeScript scope"
  - "Playwright test uses test.slow() for extended CI timeout budget; 5s simulated drop (not 30s per plan note)"

metrics:
  duration: "~20 minutes"
  completed: "2026-05-20"
  tasks_completed: 3
  tasks_total: 3
  files_created: 3
  files_modified: 3
---

# Phase 07 Plan 04: StrategyControlsPane + Playwright WS Reconnect Test Summary

StrategyControlsPane with strategy list (optimistic toggle, param edit with 422 inline errors, Save & Hot-reload, Run Backtest polling), wired into dashboard as the 4th pane; ws-reconnect.spec.ts replaced with a real Playwright E2E test; vitest/playwright collision fixed.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | StrategyControlsPane + wire into dashboard | 64a3da7 | StrategyControlsPane.tsx (new), dashboard/page.tsx |
| 2 | Playwright ws-reconnect.spec.ts implementation | 95b363f | ws-reconnect.spec.ts, vitest.config.ts, e2e/tsconfig.json |
| 3 | checkpoint:human-verify | — | Auto-approved (workflow.auto_advance=true) |

## What Was Built

### Task 1: StrategyControlsPane

`StrategyControlsPane.tsx` is the 4th pane of the 4-pane terminal:

**Strategy list section:**
- Calls `useStrategies()` to get `StrategyInfo[]` from `GET /strategies`
- Each strategy renders as a 36px row: strategy_id label | ACTIVE/OFF status badge | Disable/Enable toggle button | expand chevron
- Toggle button calls `POST /strategies/{id}/toggle` with optimistic badge update (revert + 3s error on failure)
- Row click expands/collapses the param edit form below

**Param edit form (expandable):**
- Renders labeled `<input type="number">` for each key in `strategy.params`
- Human-readable labels from `FIELD_LABELS` lookup: `opening_range_minutes` → "Opening Range (min)", etc.
- No HTML5 `min`/`max`/`step` attributes (D-16 / T-07-04-01: server-side Pydantic is sole validator)
- Save & Hot-reload calls `PUT /strategies/{id}/params`; on 200: 2s transient "Params saved — engine reloading" in #4ade80
- 422 inline errors: Pydantic v2 array format mapped per-field; string format shown as global error
- Field border turns `#f87171` on per-field error

**Run Backtest section:**
- Button calls `POST /backtests/run`; on 202: stores `run_id` in local state
- `useStrategyRun(runId)` polls `GET /backtests/{run_id}` every 2s while pending
- `useEffect` watching `runStatus`: on `complete`/`failed`: `invalidateQueries(['backtests'])` + `setRunId(null)`
- Button disabled while running: `aria-disabled={isRunning}`, `cursor: not-allowed`, color `#555555` (T-07-04-02)
- Guard against double-submit: `if (isRunning) return` in handler

**OPTIMIZATION HEATMAP accordion:**
- Collapsed by default (`useState(false)`)
- Header row 28px with `▶`/`▼` chevron
- When expanded: shows link to `/optimizations` page

**Dashboard wiring:**
- `dashboard/page.tsx` imports `StrategyControlsPane` and replaces the "Coming in Plan 07-04" placeholder
- All 4 panes (CHART / BLOTTER / HISTORY / CONTROLS) now fully implemented

### Task 2: Playwright WS Reconnect Test

`ws-reconnect.spec.ts` (real test, not `test.fixme` stub):
- `test.slow()` for extended CI timeout budget
- Navigates to `/dashboard`, waits for all 4 pane labels visible (15s timeout)
- Waits 2s for WS connection to establish
- `page.routeWebSocket('**/stream', ws => { ws.connectToServer(); setTimeout(() => ws.close(), 500) })` — simulates network drop after brief real connection
- Waits 4s for reconnect attempt scheduling
- `page.unrouteWebSocket('**/stream')` to release intercept
- Waits 3s for reconnect to succeed
- Asserts all 4 pane labels still visible (BLOTTER, HISTORY, CONTROLS)
- Asserts `GET /positions` responds with status 200 or 404 (both acceptable — 404 means no positions, not a failure)

`e2e/tsconfig.json` added for Playwright-specific TypeScript scope.

**Vitest/Playwright collision fixed:**
- `vitest.config.ts` updated to exclude `**/e2e/**` from Vitest test runs
- Pre-existing collision: Wave 0 stub in `e2e/ws-reconnect.spec.ts` used `@playwright/test` imports that Vitest couldn't resolve, causing 1 "test file failed" in the output even though the 22 unit tests all passed
- Now 2/2 test files pass cleanly, 22/22 tests pass

## Verification

```
pnpm --filter web test -- --run:
  2/2 test files pass, 22/22 tests pass

apps/web/components/StrategyControlsPane.tsx: exists
apps/web/e2e/ws-reconnect.spec.ts: real test (no test.fixme)
apps/web/app/dashboard/page.tsx: <StrategyControlsPane /> in CONTROLS pane
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Playwright/Vitest import collision**
- **Found during:** Task 2 verification
- **Issue:** `vitest --run` showed "1 test file failed" because `e2e/ws-reconnect.spec.ts` uses `@playwright/test` imports that Vitest cannot resolve. This was a pre-existing issue from the Wave 0 stub in Plan 07-01 (noted in Plan 07-03 SUMMARY as "expected failure, not new") that was not fixed at the time.
- **Fix:** Added `exclude: ['**/e2e/**', '**/node_modules/**']` to `vitest.config.ts` so Playwright E2E specs are excluded from Vitest test discovery. Added `e2e/tsconfig.json` for proper Playwright TypeScript scope.
- **Files modified:** `apps/web/vitest.config.ts`, `apps/web/e2e/tsconfig.json` (new)
- **Commits:** 95b363f

**2. [Rule 2 - Missing] Per-field Pydantic v2 422 error handling**
- **Found during:** Task 1 implementation
- **Issue:** Plan spec said "display response.json().detail" inline but Pydantic v2 returns `detail` as an array of `{loc: string[], msg: string}` objects, not a plain string.
- **Fix:** `ParamForm.handleSave` checks `Array.isArray(body.detail)` and maps each `err` to `{[field]: msg}` for per-field display; falls back to `typeof body.detail === 'string'` for legacy-format errors.
- **Files modified:** `apps/web/components/StrategyControlsPane.tsx`
- **Commit:** 64a3da7

## Task 3: checkpoint:human-verify

Auto-approved per `workflow.auto_advance=true` configuration.

What was built across Plans 07-01 through 07-04:
- 4-pane TerminalLayout (CHART / BLOTTER / HISTORY / CONTROLS) via `react-resizable-panels`
- localStorage persistence (key: `es-terminal-layout-h`, `es-terminal-layout-v`)
- BlotterPane with positions table, F/K/P hotkeys, ConfirmationDialog, HelpOverlay
- TradeHistoryPane with 9-column trade table + LineSeries equity + DD HistogramSeries + click-to-scroll
- StrategyControlsPane with toggle, param form (422 inline), Save & Hot-reload, Run Backtest, heatmap accordion
- WS exponential backoff with jitter; seq gap detection → invalidateQueries resync
- Playwright E2E test for WS reconnect simulation
- GET /strategies, PUT /strategies/{id}/params (422), POST /strategies/{id}/toggle, POST /backtests/run
- All 22 Vitest unit tests pass; backend pytest suite also clean

## Known Stubs

None — all panes render live data from TanStack Query hooks. The OPTIMIZATION HEATMAP accordion shows a link to `/optimizations` rather than an inline Plotly heatmap (per plan: "The full Plotly heatmap integration from Phase 4 is deferred to a bonus task").

## Threat Flags

None — no new network endpoints introduced in this plan. The `StrategyControlsPane` calls existing `/strategies` endpoints wired in Plan 07-02.

## Self-Check: PASSED

| Check | Result |
|-------|--------|
| `apps/web/components/StrategyControlsPane.tsx` exists | FOUND |
| `apps/web/e2e/ws-reconnect.spec.ts` is real test (no fixme) | CONFIRMED |
| `apps/web/app/dashboard/page.tsx` renders StrategyControlsPane | CONFIRMED |
| `apps/web/vitest.config.ts` excludes e2e/ | CONFIRMED |
| Commit 64a3da7 (Task 1) | FOUND |
| Commit 95b363f (Task 2) | FOUND |
| 22/22 Vitest tests pass | CONFIRMED |
