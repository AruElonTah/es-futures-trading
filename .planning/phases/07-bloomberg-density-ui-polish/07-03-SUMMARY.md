---
phase: "07"
plan: "03"
subsystem: "web-ui"
tags: ["blotter", "trade-history", "lightweight-charts", "zustand", "tdd"]

dependency_graph:
  requires: ["07-02"]
  provides: ["BlotterPane", "TradeHistoryPane", "Chart.focusedBarTs"]
  affects: ["apps/web/app/dashboard/page.tsx", "apps/web/components/Chart.tsx"]

tech_stack:
  added: []
  patterns:
    - "Two-effect chart lifecycle split (Pitfall 2 guard)"
    - "Pure-function extraction for Vitest without React rendering"
    - "Zustand cross-pane atom (focusedBarTs) for D-12 click-to-scroll"
    - "HistogramSeries per-bar color (Pitfall 7 guard)"
    - "TanStack Query cache deduplication via shared queryKey"

key_files:
  created:
    - apps/web/components/BlotterPane.tsx
    - apps/web/components/TradeHistoryPane.tsx
  modified:
    - apps/web/components/Chart.tsx
    - apps/web/app/dashboard/page.tsx
    - apps/web/__tests__/TradeHistoryPane.test.ts
  deleted:
    - apps/web/app/dashboard/blotter/page.tsx (entire directory)

decisions:
  - "Hold bars derived from exit_ts_utc - entry_ts_utc in minutes (TradeRow has no hold_bars field)"
  - "DD histogram values use -Math.abs(p.drawdown) so negative drawdown from API doesn't double-negate"
  - "Slippage $ hardcoded at POINT_VALUE=50 client-side per D-13 (client doesn't call instruments.py)"
  - "22 pure-function Vitest tests — no React rendering ceremony, matching useStream.test.ts pattern"
  - "Dashboard page TanStack deduplicates trades fetch: same queryKey ['trades', latestRunId]"

metrics:
  duration: "~25 minutes (resumed from prior session)"
  completed: "2026-05-20"
  tasks_completed: 2
  tasks_total: 2
  files_created: 2
  files_modified: 3
  files_deleted: 1
---

# Phase 07 Plan 03: BlotterPane Migration + TradeHistoryPane Summary

BlotterPane migrated from retired /dashboard/blotter route; TradeHistoryPane added with 9-column trade table + LineSeries equity curve + HistogramSeries drawdown chart, wired to Chart.tsx click-to-scroll via focusedBarTs Zustand atom.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | BlotterPane migration + blotter dir deletion | 85e75dd | BlotterPane.tsx (new), dashboard/blotter/ (deleted), dashboard/page.tsx |
| RED | TradeHistoryPane tests (22 real tests) | 3b38cae | __tests__/TradeHistoryPane.test.ts |
| 2 GREEN | TradeHistoryPane + Chart focusedBarTs | 9571b03 | TradeHistoryPane.tsx (new), Chart.tsx, dashboard/page.tsx |

## What Was Built

### Task 1: BlotterPane Migration

`BlotterPane.tsx` is a pane-body component (not a page) extracted from the retired `/dashboard/blotter/page.tsx`:

- Does NOT call `useStream()` — parent dashboard handles WS subscription once
- Reads `positions` and `engineState` from `useWsStore` (cross-pane Zustand state)
- Uses extracted `ConfirmationDialog` and `HelpOverlay` from Plan 07-02
- 1s polling fallback via TanStack Query `refetchInterval: 1000` for WS-down scenarios
- F (Flatten) / K (Kill) / P (Pause) control row at bottom with confirmation dialogs
- WR-02: flatten error banner surfaced inline above positions table
- Empty state: "No open positions" / "Start a backtest to generate fills"
- Error state: "Failed to load positions. Is the API running? Check uvicorn output."

`apps/web/app/dashboard/blotter/` directory deleted. `next.config.ts` permanent redirect `/dashboard/blotter → /dashboard` was already present from Plan 07-02.

`dashboard/page.tsx` updated:
- Imports `BlotterPane`, inline `EngineStateBadge` (D-05)
- BLOTTER pane `rightSlot`: `<EngineStateBadge state={engineState} />` + `<AuthorTVAlertButton />`

### Task 2 (TDD): TradeHistoryPane + Chart.tsx Effect 3

**RED commit (3b38cae):** 22 pure-function Vitest tests written first against extracted helpers:
- `computeSlippageDollars`, `formatHoldTime`, `buildEquityData`, `buildDDData`
- Tests: row count mapping, click→setFocusedBarTs, empty state headings, slippage math, hold time formatting, HistogramSeries addSeries mock call, DD negation, per-bar color (Pitfall 7), equity relative values
- Fixed: `expect(Math.abs(ddData[0].value)).toBe(0)` instead of `toBe(0)` — IEEE 754 `-0` vs `+0`

**GREEN commit (9571b03):** Full implementation:

`TradeHistoryPane.tsx`:
- Two-section layout: trade table (flex: 1, overflow: auto) + 160px equity+DD chart (flexShrink: 0)
- 9-column table: SIDE, ENTRY, EXIT, GROSS P&L, SLIPPAGE $, MAE, MFE, HOLD, REASON
- LineSeries equity (relative: `equity - startEquity`, color `#4ade80`)
- HistogramSeries drawdown: values `-Math.abs(p.drawdown)`, per-bar `color: 'rgba(239,68,68,0.5)'` (D-11, Pitfall 7)
- Row click: `onClick={() => setFocusedBarTs(trade.entry_ts_utc)}`; focused row gets blue border `#4a90d9`
- Loading spinner with `role="status" aria-live="polite"` (D-15)
- Chart container: `aria-label="Equity curve and drawdown chart"`
- `chartRef.current = null` before `chart.remove()` in cleanup (T-07-03-03 / Pitfall 2)

`Chart.tsx` updated:
- Added `chartRef = useRef<IChartApi | null>(null)` stored in Effect 1 (after `seriesRef`)
- Cleanup: `chartRef.current = null` before `chart.remove()` (T-07-03-03)
- Effect 3: watches `focusedBarTs` Zustand atom; sorts bars ASC, finds matching index, calls `scrollToPosition(idx - 30%, false)`; resets `setFocusedBarTs(null)` after scroll (D-12)

`dashboard/page.tsx`:
- HISTORY pane renders `<TradeHistoryPane runId={latestRunId} />`
- `latestRunId` from `backtests?.[0]?.run_id ?? null` (TanStack Query deduplication applies)

## Verification

- `pnpm --filter web exec tsc --noEmit`: clean (no output)
- `pnpm --filter web test -- --run`: 22/22 pass
- `e2e/ws-reconnect.spec.ts`: pre-existing Playwright/Vitest collision (Plan 07-01 stub) — expected failure, not new

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] IEEE 754 -0 vs +0 in DD test assertion**
- **Found during:** RED phase test run
- **Issue:** `expect(ddData[0].value).toBe(0)` failed — `-Math.abs(0)` produces `-0` in IEEE 754; `Object.is(-0, 0)` is `false`
- **Fix:** Changed assertion to `expect(Math.abs(ddData[0].value)).toBe(0)` + `expect(ddData[0].value).toBeLessThanOrEqual(0)`
- **Files modified:** `apps/web/__tests__/TradeHistoryPane.test.ts`
- **Commit:** 3b38cae

## TDD Gate Compliance

| Gate | Commit | Status |
|------|--------|--------|
| RED (test) | 3b38cae | PASS — 22 failing stubs replaced with real tests |
| GREEN (feat) | 9571b03 | PASS — 22/22 tests passing after implementation |

## Known Stubs

None — all panes render live data from TanStack Query hooks. CONTROLS pane in `dashboard/page.tsx` shows "Coming in Plan 07-04" placeholder text but that is intentional per plan scope (Plan 07-04 will implement `StrategyControlsPane`).

## Threat Flags

None — no new network endpoints, auth paths, or schema changes introduced. BlotterPane reuses existing `/positions`, `/flatten`, `/kill`, `/pause` endpoints from Phase 5.

## Self-Check: PASSED

| Check | Result |
|-------|--------|
| BlotterPane.tsx exists | FOUND |
| TradeHistoryPane.tsx exists | FOUND |
| Chart.tsx exists | FOUND |
| TradeHistoryPane.test.ts exists | FOUND |
| apps/web/app/dashboard/blotter/ deleted | CONFIRMED |
| Commit 85e75dd (Task 1) | FOUND |
| Commit 3b38cae (RED tests) | FOUND |
| Commit 9571b03 (Task 2 GREEN) | FOUND |
