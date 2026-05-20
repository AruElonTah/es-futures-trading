---
phase: 07-bloomberg-density-ui-polish
verified: 2026-05-20T00:00:00Z
status: human_needed
score: 18/18 must-haves verified
overrides_applied: 0
human_verification:
  - test: "Open http://localhost:3000/dashboard at desktop width (1440px+). Verify all 4 pane title bars are visible: CHART (left), BLOTTER (right-top), HISTORY (right-mid), CONTROLS (right-bottom)."
    expected: "4 panes visible, each with a 28px title bar showing its label."
    why_human: "Visual layout with react-resizable-panels cannot be confirmed programmatically."
  - test: "Drag the vertical 4px resize handle between the chart pane and the right column. Then drag the horizontal handles between right-column panes."
    expected: "Layout shifts responsively; panes resize correctly."
    why_human: "Drag-resize behavior requires browser interaction."
  - test: "Reload the page after resizing. Verify the layout is restored to the resized dimensions."
    expected: "localStorage persists layout sizes (keys: es-terminal-layout-h, es-terminal-layout-v) across reloads."
    why_human: "localStorage persistence requires browser-side validation."
  - test: "Navigate to http://localhost:3000/dashboard/blotter."
    expected: "Browser permanently redirects (301) to http://localhost:3000/dashboard."
    why_human: "Next.js redirect behavior requires a live server to confirm."
  - test: "Kill uvicorn and restart it. Watch the ConnectionStatus indicator in the header."
    expected: "Indicator goes yellow/red, then returns to connected (green) after WS reconnects with exponential backoff."
    why_human: "WS reconnect and status indicator behavior requires live observation."
  - test: "In the CONTROLS pane, if orb.yaml exists: change an ORB param (e.g., opening_range_minutes) and click Save & Hot-reload."
    expected: "Transient '\\''Params saved — engine reloading'\\'' confirmation text appears in green (#4ade80) for ~2s."
    why_human: "Transient UI state feedback requires live interaction."
  - test: "In the CONTROLS pane, click Run Backtest."
    expected: "Button label changes to 'Running…' and becomes disabled (cursor: not-allowed) while polling. Returns to 'Run Backtest' on completion."
    why_human: "Polling state and button disable behavior requires live end-to-end flow."
  - test: "Run the Playwright E2E test: pnpm --filter web test:e2e (requires uvicorn on :8000 and Next.js on :3000)."
    expected: "ws-reconnect.spec.ts passes — navigates to /dashboard, simulates WS drop, asserts pane labels and /positions response."
    why_human: "Playwright test requires live servers. Cannot run in static analysis."
---

# Phase 07: Bloomberg Density UI Polish — Verification Report

**Phase Goal:** Deliver a Bloomberg-density 4-pane terminal UI at /dashboard with drag-resize panes, WS hardening, strategy controls, and trade history.
**Verified:** 2026-05-20
**Status:** human_needed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | TOPIC_STRATEGY_RELOAD constant exists in events/models.py and is importable | VERIFIED | `TOPIC_STRATEGY_RELOAD: Final[str] = "strategy_reload"` confirmed in file |
| 2 | StrategyRegistry.reload() static method exists and returns an ORBStrategy from YAML | VERIFIED | `def reload(strategy_id: str, strategies_dir: str \| Path) -> "ORBStrategy":` confirmed in registry.py |
| 3 | WS messages include a monotonic seq field (server-side ConnectionManager counter) | VERIFIED | `self._seq: int = 0`, `self._seq += 1`, `seq = self._seq` all confirmed in ws.py |
| 4 | backtests table has a status VARCHAR column; GET /backtests/{run_id} returns single row | VERIFIED | schema.sql has `status VARCHAR NOT NULL DEFAULT 'complete'`; `@router.get("/backtests/{run_id}")` confirmed in backtests.py |
| 5 | /dashboard/blotter permanently redirects to /dashboard | VERIFIED | `async redirects()` with `source: '/dashboard/blotter'` confirmed in next.config.ts |
| 6 | PaneContainer renders a 28px title bar with label and optional rightSlot | VERIFIED | `height: '28px'` confirmed in PaneContainer.tsx; rightSlot prop present |
| 7 | WsStore has focusedBarTs and lastSeq atoms with setters | VERIFIED | `focusedBarTs: string \| null`, `lastSeq: number \| null`, both setters confirmed in ws.ts |
| 8 | useStream reconnects with exponential backoff; detects seq gaps and calls invalidateQueries | VERIFIED | `MAX_BACKOFF_MS = 30_000`, `Math.min(Math.pow(2, attempt) * 1000, MAX_BACKOFF_MS)`, `invalidateQueries(['positions'])` and `['backtests']` confirmed in useStream.ts |
| 9 | GET /strategies, PUT /strategies/{id}/params, POST /strategies/{id}/toggle routes registered | VERIFIED | All three `@router` decorators confirmed in strategies.py |
| 10 | ConfirmationDialog and HelpOverlay exist as standalone components in apps/web/components/ | VERIFIED | Both files exist; 'use client' present; wired into BlotterPane |
| 11 | BlotterPane renders positions table + F/K/P controls using ConfirmationDialog and HelpOverlay from components/ | VERIFIED | Imports confirmed; ConfirmationDialog and HelpOverlay rendered inside BlotterPane |
| 12 | apps/web/app/dashboard/blotter/page.tsx is deleted; its directory no longer exists | VERIFIED | `test -d` returns DELETED |
| 13 | TradeHistoryPane renders closed-trade table with 9 columns plus equity+DD chart | VERIFIED | LineSeries + HistogramSeries, 9-column table confirmed in TradeHistoryPane.tsx |
| 14 | Clicking a trade row calls setFocusedBarTs(trade.entry_ts_utc) | VERIFIED | `onClick={() => setFocusedBarTs(trade.entry_ts_utc)}` confirmed in TradeHistoryPane.tsx |
| 15 | Chart.tsx has chartRef stored in a ref and a third useEffect watching focusedBarTs | VERIFIED | `chartRef = useRef<IChartApi \| null>(null)`, Effect 3 watching focusedBarTs confirmed in Chart.tsx |
| 16 | StrategyControlsPane lists all registered strategies, has toggle, param form, Run Backtest, heatmap accordion | VERIFIED | `useStrategies()`, toggle with optimistic update, `ParamForm`, `aria-disabled={isRunning}`, HeatmapAccordion all confirmed in StrategyControlsPane.tsx |
| 17 | PUT /strategies/{id}/params 422 detail shown inline; Save & Hot-reload shows transient confirmation | VERIFIED | `FieldError` component, 422 handler mapping Pydantic v2 array format, `setSaveSuccess(true)` confirmed |
| 18 | ws-reconnect.spec.ts Playwright test exists and is a real test (not fixme stub) | VERIFIED | `test('WS reconnects...')` with `page.routeWebSocket` confirmed; no `test.fixme` found |

**Score:** 18/18 truths verified

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `packages/trading-core/src/trading_core/events/models.py` | TOPIC_STRATEGY_RELOAD constant | VERIFIED | Contains `TOPIC_STRATEGY_RELOAD: Final[str] = "strategy_reload"` |
| `packages/trading-core/src/trading_core/strategy/registry.py` | StrategyRegistry.reload() method | VERIFIED | `def reload` confirmed |
| `packages/api/src/api/ws.py` | seq counter on ConnectionManager | VERIFIED | `self._seq` init + increment + injection confirmed |
| `packages/api/src/api/routes/backtests.py` | GET /backtests/{run_id} single-row endpoint | VERIFIED | `@router.get("/backtests/{run_id}")` confirmed |
| `apps/web/e2e/playwright.config.ts` | Playwright E2E config | VERIFIED | File exists |
| `packages/api/tests/test_strategies.py` | pytest stubs/tests for strategy routes | VERIFIED | File exists; real tests (not stubs) as of Plan 07-02 |
| `apps/web/__tests__/TradeHistoryPane.test.ts` | Vitest tests for TradeHistoryPane | VERIFIED | File exists; stubs replaced with 22 real tests in Plan 07-03 |
| `apps/web/next.config.ts` | permanent redirect /dashboard/blotter -> /dashboard | VERIFIED | `async redirects()` confirmed |
| `apps/web/components/PaneContainer.tsx` | 28px title bar pane wrapper | VERIFIED | `height: '28px'` confirmed |
| `apps/web/components/ConfirmationDialog.tsx` | extracted confirmation dialog | VERIFIED | File exists, 'use client' |
| `apps/web/components/HelpOverlay.tsx` | extracted help overlay | VERIFIED | File exists, 'use client' |
| `apps/web/store/ws.ts` | focusedBarTs and lastSeq in WsStore | VERIFIED | Both atoms + setters confirmed |
| `apps/web/hooks/useStream.ts` | exponential backoff + seq gap detection | VERIFIED | MAX_BACKOFF_MS + invalidateQueries confirmed |
| `packages/api/src/api/routes/strategies.py` | GET/PUT/POST strategy routes | VERIFIED | All three routes confirmed |
| `packages/api/src/api/app.py` | strategies router wired + PUT in CORS + TOPIC_STRATEGY_RELOAD subscriber | VERIFIED | All three confirmed |
| `apps/web/components/BlotterPane.tsx` | Blotter pane with positions + F/K/P dialogs | VERIFIED | Full implementation confirmed |
| `apps/web/components/TradeHistoryPane.tsx` | Trade table + equity+DD chart | VERIFIED | LineSeries + HistogramSeries + 9-column table confirmed |
| `apps/web/components/Chart.tsx` | chartRef + focusedBarTs scroll effect | VERIFIED | chartRef + Effect 3 confirmed |
| `apps/web/components/StrategyControlsPane.tsx` | Strategy controls pane | VERIFIED | Full implementation confirmed |
| `apps/web/e2e/ws-reconnect.spec.ts` | Playwright E2E WS reconnect test | VERIFIED | Real test confirmed (no fixme) |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `useStream.ts` | `ws.ts setLastSeq` | useWsStore selector | WIRED | `useWsStore((s) => s.setLastSeq)` confirmed in useStream.ts |
| `strategies.py` | `TOPIC_STRATEGY_RELOAD in events/models.py` | import | WIRED | `from trading_core.events.models import TOPIC_STRATEGY_RELOAD` confirmed in strategies.py |
| `TradeHistoryPane.tsx` | `ws.ts setFocusedBarTs` | useWsStore selector | WIRED | `useWsStore((s) => s.setFocusedBarTs)` and `onClick` confirmed |
| `Chart.tsx` | `ws.ts focusedBarTs` | useWsStore selector + useEffect dep | WIRED | `useWsStore((s) => s.focusedBarTs)` + Effect 3 confirmed |
| `dashboard/page.tsx` | `BlotterPane.tsx` | import + Panel child | WIRED | `import BlotterPane` + `<BlotterPane />` in Panel confirmed |
| `StrategyControlsPane.tsx` | `GET /strategies (via useStrategies)` | useStrategies() from useBacktests.ts | WIRED | `useStrategies()` import + call confirmed |
| `StrategyControlsPane.tsx` | `POST /backtests/run` | fetch POST | WIRED | `fetch(\`${API_BASE}/backtests/run\`, { method: 'POST' })` confirmed |
| `ws-reconnect.spec.ts` | `WS /stream seq field` | Playwright routeWebSocket | WIRED | `page.routeWebSocket('**/stream', ...)` confirmed |

---

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| `TradeHistoryPane.tsx` | trades / equityCurve | `useEquityTrades(runId)` / `useEquityCurve(runId)` → TanStack Query → `/backtests/{id}/trades` + `/equity` API | Yes — backtests DuckDB queries confirmed in Phase 3 | FLOWING |
| `BlotterPane.tsx` | positions | `useWsStore` + TanStack Query refetchInterval → `/positions` | Yes — FastAPI positions endpoint wired | FLOWING |
| `StrategyControlsPane.tsx` | strategies | `useStrategies()` → GET `/strategies` → reads YAML + `get_strategy_enabled()` from DuckDB | Yes — endpoint implementation confirmed | FLOWING |

---

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `packages/api/src/api/routes/strategies.py` | (internal) | `_run_backtest_task` sleeps 2s then marks complete — stub implementation | Info | BacktestEngine not wired yet; real engine wiring deferred to Phase 8 (plan-documented and per-milestone roadmap) |

No `TBD`, `FIXME`, or `XXX` markers found in phase-modified files. The `_run_backtest_task` stub is documented in the plan as intentional deferred work.

---

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| TOPIC_STRATEGY_RELOAD importable | `grep "TOPIC_STRATEGY_RELOAD" events/models.py` | Match found | PASS |
| Seq counter present in ws.py | `grep "_seq" ws.py` | `self._seq: int = 0` + increment found | PASS |
| GET /backtests/{run_id} endpoint registered | `grep "@router.get.*backtests.*run_id" backtests.py` | Match found | PASS |
| Strategies router 3 routes | `grep "@router" strategies.py` | 4 routes: GET, PUT, POST toggle, POST run | PASS |
| blotter/ directory deleted | `test -d apps/web/app/dashboard/blotter` | Returns DELETED | PASS |
| react-resizable-panels installed | `ls node_modules/react-resizable-panels` | dist/LICENSE/package.json present | PASS |

---

### Human Verification Required

**CRITICAL: Plan 07-04 declared `gate="blocking"` on the human-verify checkpoint. The SUMMARY reports this was auto-approved via `workflow.auto_advance=true`. A blocking gate was bypassed without human confirmation. The following tests MUST be performed before the phase is marked complete.**

#### 1. 4-Pane Terminal Layout Visibility

**Test:** Start uvicorn on port 8000 and Next.js dev server on port 3000. Open http://localhost:3000/dashboard at 1440px+ width.
**Expected:** All 4 panes visible with 28px title bars: CHART (left), BLOTTER (right-top), HISTORY (right-mid), CONTROLS (right-bottom).
**Why human:** Visual layout with react-resizable-panels cannot be confirmed programmatically.

#### 2. Drag-Resize Pane Handles

**Test:** Drag the vertical 4px handle between chart and right column. Drag horizontal handles between right-column panes.
**Expected:** Layout shifts responsively; panes resize without overflow or collapse.
**Why human:** Drag-resize interaction requires browser.

#### 3. localStorage Layout Persistence

**Test:** Resize panes, reload the page.
**Expected:** Layout dimensions restored (localStorage keys: `es-terminal-layout-h`, `es-terminal-layout-v`).
**Why human:** localStorage persistence requires browser-side validation.

#### 4. /dashboard/blotter Redirect

**Test:** Navigate to http://localhost:3000/dashboard/blotter.
**Expected:** Browser receives 301 permanent redirect to http://localhost:3000/dashboard.
**Why human:** Next.js redirect behavior requires a live dev server.

#### 5. WS Reconnect in Browser

**Test:** Kill uvicorn and restart it while watching the ConnectionStatus indicator.
**Expected:** Indicator turns yellow/red, then returns to connected state within ~5s (first backoff attempt ~1s + jitter).
**Why human:** Live WS reconnect and status indicator behavior.

#### 6. Strategy Hot-Reload Confirmation

**Test:** Change an ORB param in CONTROLS pane, click Save & Hot-reload.
**Expected:** Transient "Params saved — engine reloading" text appears in green for ~2s.
**Why human:** Transient UI state feedback.

#### 7. Run Backtest Polling State

**Test:** Click Run Backtest in CONTROLS pane.
**Expected:** Button becomes disabled with "Running…" label; returns to "Run Backtest" after polling completes.
**Why human:** Polling state cycle requires live API.

#### 8. Playwright E2E Test

**Test:** With both servers running: `pnpm --filter web test:e2e`
**Expected:** `ws-reconnect.spec.ts` passes — WS drop simulated, reconnect observed, pane labels asserted, /positions responds 200 or 404.
**Why human:** Playwright test requires live servers.

---

### Requirements Coverage

| Requirement | Description | Status | Evidence |
|-------------|-------------|--------|----------|
| UI-02 | WebSocket reconnect with exponential backoff + jitter; seq gap detection → REST resync | SATISFIED | `MAX_BACKOFF_MS=30_000`, jitter, `invalidateQueries` all confirmed in useStream.ts |
| UI-03 | Next.js 16.2 + React 19 + dark monospace theme; multi-pane drag/resize; desktop widths only | PARTIAL — human needed | 4-pane shell with react-resizable-panels confirmed in code; visual/resize behavior needs human verification |
| UI-06 | Trade history + equity curve panel: closed-trades table + equity curve + DD bars | SATISFIED (code) | TradeHistoryPane with 9-column table, LineSeries, HistogramSeries, click-to-scroll all confirmed |
| UI-07 | Strategy controls + parameter panel: toggle, live-edit params, backtest button, optimization heatmap | SATISFIED (code) | StrategyControlsPane with all four sub-sections confirmed; heatmap accordion confirmed |
| SP-06 | Sequence numbers on every WebSocket message; client detects gaps and requests snapshot resync | SATISFIED | `_seq` counter on ConnectionManager + `invalidateQueries` resync on gap confirmed |

---

### Gaps Summary

No code-level blockers found. All 18 observable truths are verified in the codebase.

**One process concern:** Plan 07-04 declared `<task type="checkpoint:human-verify" gate="blocking">` and the SUMMARY reports auto-approval via `workflow.auto_advance=true`. A blocking gate was bypassed. The 8 human verification items above capture what that checkpoint was intended to confirm. They must be completed before this phase is signed off.

The `_run_backtest_task` stub (2s sleep, no real BacktestEngine) is plan-documented as intentional deferred work for Phase 8. It is not a gap for Phase 7.

---

_Verified: 2026-05-20_
_Verifier: Claude (gsd-verifier)_
