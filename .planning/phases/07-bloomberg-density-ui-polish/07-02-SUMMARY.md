---
phase: "07"
plan: "02"
subsystem: layout-ws-strategies
tags: [terminal-layout, websocket, strategy-api, pane-components, exponential-backoff]
dependency_graph:
  requires:
    - "07-01 (TOPIC_STRATEGY_RELOAD, StrategyRegistry.reload, WS seq counter)"
  provides:
    - "next.config.ts: permanent redirect /dashboard/blotter -> /dashboard"
    - "PaneContainer component (28px title bar + rightSlot)"
    - "ConfirmationDialog standalone component"
    - "HelpOverlay standalone component"
    - "WsStore: focusedBarTs + lastSeq atoms"
    - "useStream: exponential backoff + seq gap detection"
    - "StrategyInfo type in api.ts"
    - "useStrategies() hook"
    - "useStrategyRun() polling hook"
    - "GET /strategies endpoint"
    - "PUT /strategies/{id}/params endpoint (with path traversal guard)"
    - "POST /strategies/{id}/toggle endpoint"
    - "POST /backtests/run endpoint (202 + run_id)"
    - "DuckDBStore.get_strategy_enabled()"
    - "DuckDBStore.write_strategy_enabled()"
    - "DuckDBStore.write_pending_backtest()"
    - "dashboard/page.tsx: 4-pane TerminalLayout shell with react-resizable-panels"
  affects:
    - "Plan 07-03: BlotterPane imports ConfirmationDialog + HelpOverlay from components/"
    - "Plan 07-03: TradeHistoryPane uses useStrategies, useStrategyRun hooks"
    - "Plan 07-04: StrategyControlsPane calls GET/PUT/POST /strategies endpoints"
    - "Plan 07-04: Chart.tsx watches focusedBarTs for scroll-to-trade (D-12)"
tech_stack:
  added: []
  patterns:
    - "Exponential backoff reconnect with MAX_BACKOFF_MS=30000 in useStream"
    - "Seq gap detection with TanStack Query invalidateQueries on WS gap"
    - "Path traversal guard: regex ^[a-z0-9_-]+$ + Path.resolve()+relative_to()"
    - "Pydantic ORBConfigUpdate validates params before YAML write (T-07-02-02)"
    - "asyncio.create_task for non-blocking POST /backtests/run (202 pattern)"
    - "TOPIC_STRATEGY_RELOAD subscriber task in lifespan with graceful cancel"
    - "react-resizable-panels PanelGroup with localStorage persistence (D-06)"
key_files:
  created:
    - apps/web/components/ConfirmationDialog.tsx
    - apps/web/components/HelpOverlay.tsx
    - apps/web/components/PaneContainer.tsx
    - packages/api/src/api/routes/strategies.py
  modified:
    - apps/web/next.config.ts
    - apps/web/store/ws.ts
    - apps/web/hooks/useStream.ts
    - apps/web/lib/api.ts
    - apps/web/hooks/useBacktests.ts
    - apps/web/app/dashboard/page.tsx
    - packages/api/src/api/app.py
    - packages/api/tests/test_strategies.py
    - packages/api/tests/test_health.py
    - packages/trading-core/src/trading_core/storage/duckdb_store.py
decisions:
  - "ORBConfigUpdate is a partial update model (all fields optional); only non-None fields merged into YAML"
  - "write_strategy_enabled uses session_id=strategy_id in engine_state table to track per-strategy enabled state"
  - "test_put_strategy_invalid_id uses uppercase strategy_id to trigger regex rejection (URL path traversal decoding prevented easier path-sep test)"
  - "useEquityCurve() called without destructuring in dashboard shell — wired to TradeHistoryPane in Plan 07-03"
  - "Dashboard placeholder panes use literal 'Coming in Plan 07-03' text to make stub state obvious"
metrics:
  duration: "~22 minutes"
  completed: "2026-05-20"
  tasks: 3
  files: 14
---

# Phase 07 Plan 02: Core Layout Restructure, WS Hardening, and Strategies Backend Summary

next.config.ts redirect + ConfirmationDialog/HelpOverlay/PaneContainer extraction + WsStore/useStream hardening + StrategyInfo types + strategies API routes (GET/PUT/POST) with path traversal guards + 4-pane TerminalLayout shell with localStorage persistence.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | next.config.ts redirect + ConfirmationDialog + HelpOverlay + PaneContainer | 50be405 | next.config.ts, ConfirmationDialog.tsx, HelpOverlay.tsx, PaneContainer.tsx |
| 2 | WsStore + useStream backoff + useBacktests hooks + TerminalLayout shell | 154cea1 | ws.ts, useStream.ts, api.ts, useBacktests.ts, dashboard/page.tsx |
| 3 (RED) | Failing tests for strategies routes | f4b4852 | test_strategies.py |
| 3 (GREEN) | strategies.py + app.py wiring + DuckDBStore methods | 9988d41 | strategies.py, app.py, test_strategies.py, test_health.py, duckdb_store.py |

## Verification Results

```
packages/api/tests/ — 56 passed, 0 failed (all API tests)
test_strategies.py — 5 real tests GREEN
test_health.py — route list updated with 4 new paths, PASS
Frontend tsc — no new errors (pre-existing useStream.test.ts mock type errors only)
Frontend tests — 2 failed (TradeHistoryPane Wave 0 stubs, expected)
strategies router smoke: ['/strategies', '/strategies/{strategy_id}/params', '/strategies/{strategy_id}/toggle', '/backtests/run']
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Path traversal test URL routing**
- **Found during:** Task 3 (RED→GREEN transition)
- **Issue:** The test for path traversal using `invalid../../etc%2Fpasswd` returned 404 instead of 400 because FastAPI URL routing rejected the path before our handler ran — `%2F` is decoded to `/` by the router, creating a different path segment entirely.
- **Fix:** Changed test to use uppercase `Invalid_ID` which routes correctly to the handler and is rejected by `^[a-z0-9_-]+$` regex with 400.
- **Files modified:** `packages/api/tests/test_strategies.py`
- **Commit:** 9988d41

**2. [Rule 2 - Missing critical functionality] DuckDBStore missing get_strategy_enabled + write_pending_backtest**
- **Found during:** Task 3 implementation
- **Issue:** strategies.py calls `store.get_strategy_enabled(strategy_id)` and `store.write_pending_backtest(run_id)` but these methods didn't exist in DuckDBStore.
- **Fix:** Added `get_strategy_enabled()`, `write_strategy_enabled()`, and `write_pending_backtest()` to DuckDBStore (Phase 7 section).
- **Files modified:** `packages/trading-core/src/trading_core/storage/duckdb_store.py`
- **Commit:** 9988d41

**3. [Rule 1 - Bug] useEquityCurve destructuring syntax**
- **Found during:** Task 2 (dashboard page.tsx)
- **Issue:** TypeScript doesn't support `const { data: x: y }` destructuring with two colons.
- **Fix:** Changed to `useEquityCurve(latestRunId)` (called for side-effects only — the data is passed to TradeHistoryPane in Plan 07-03 once that pane exists).
- **Files modified:** `apps/web/app/dashboard/page.tsx`
- **Commit:** 154cea1

## Known Stubs

| File | Stub | Reason |
|------|------|--------|
| `apps/web/app/dashboard/page.tsx` | Three right-column panes show "Coming in Plan 07-03" placeholder | BlotterPane/TradeHistoryPane/StrategyControlsPane not yet built |
| `packages/api/src/api/routes/strategies.py` | `_run_backtest_task` sleeps 2s then marks complete | Real BacktestEngine wiring is Phase 8 work |

## Threat Flags

All threat model items from plan addressed:

| Threat ID | Disposition | Implementation |
|-----------|-------------|----------------|
| T-07-02-01 | mitigated | `_STRATEGY_ID_RE = re.compile(r'^[a-z0-9_-]+$')` + `Path.resolve()+relative_to()` |
| T-07-02-02 | mitigated | `ORBConfigUpdate.model_dump(exclude_none=True)` — never raw request body to YAML |
| T-07-02-03 | accepted | PUT added to CORS allow_methods; origins remain localhost:3000/127.0.0.1:3000 only |
| T-07-02-04 | mitigated | `loadSizes()` wraps JSON.parse in try/catch; silent fallback to DEFAULT_H/V_SIZES |

## Self-Check

- [x] `apps/web/next.config.ts` — async redirects() with /dashboard/blotter -> /dashboard present
- [x] `apps/web/components/ConfirmationDialog.tsx` — exists, 'use client', named export
- [x] `apps/web/components/HelpOverlay.tsx` — exists, 'use client', z-index 9998
- [x] `apps/web/components/PaneContainer.tsx` — exists, 28px title bar, rightSlot
- [x] `apps/web/store/ws.ts` — focusedBarTs, lastSeq, setFocusedBarTs, setLastSeq present
- [x] `apps/web/hooks/useStream.ts` — MAX_BACKOFF_MS = 30_000, reconnect loop, gap detection
- [x] `apps/web/lib/api.ts` — StrategyInfo interface present
- [x] `apps/web/hooks/useBacktests.ts` — useStrategies(), useStrategyRun() exported
- [x] `apps/web/app/dashboard/page.tsx` — PanelGroup 60/40 layout, localStorage, Blotter link removed
- [x] `packages/api/src/api/routes/strategies.py` — GET/PUT/POST endpoints registered
- [x] `packages/api/src/api/app.py` — strategies router included, PUT in CORS, reload subscriber task
- [x] Commits: 50be405, 154cea1, f4b4852, 9988d41 — all exist

## Self-Check: PASSED
