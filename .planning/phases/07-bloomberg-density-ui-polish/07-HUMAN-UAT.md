---
status: complete
phase: 07-bloomberg-density-ui-polish
source: [07-VERIFICATION.md]
started: 2026-05-20T00:00:00Z
updated: 2026-05-21T00:00:00Z
---

## Current Test

Complete — all 8 UAT tests resolved (2026-05-21).

## Tests

### 1. Four panes visible at /dashboard
expected: At 1440px+ width, four labeled panes visible — CHART (left, candlestick chart), BLOTTER (right top, positions table or empty state), HISTORY (right middle, trade table or empty state), CONTROLS (right bottom, strategy list)
result: passed — all 4 pane labels (CHART, BLOTTER, HISTORY, CONTROLS) visible with dark title bars; empty pane content is expected in no-data state

### 2. Drag-resize handles work
expected: Vertical 4px handle between chart and right column is draggable; three horizontal handles in right column are draggable; panes resize correctly
result: passed — vertical and horizontal handles all draggable; panes resize correctly

### 3. localStorage layout persistence across reloads
expected: After dragging panes to custom sizes, reload the page; sizes are restored to the same positions
result: passed — layout persists across hard reload (Ctrl+Shift+R); switched from manual localStorage + SSR guard to react-resizable-panels autoSaveId which eliminates hydration mismatch warning (fix applied 2026-05-21)

### 4. /dashboard/blotter redirect
expected: Navigating to http://localhost:3000/dashboard/blotter redirects to http://localhost:3000/dashboard in the browser (HTTP 308)
result: passed — browser navigated to /dashboard/blotter and address bar showed /dashboard

### 5. WS reconnect visible in ConnectionStatus indicator
expected: Kill uvicorn and restart it; ConnectionStatus indicator goes yellow/red then returns to connected state
result: passed — full green→red→green cycle confirmed with automatic reconnect (no page refresh needed); two bugs fixed: (a) stale ws.onclose clobbered connected=true in React StrictMode double-invocation — fix: guard with `if (stopped) return`; (b) same for ws.onerror

### 6. Strategy controls — "Params saved — engine reloading" transient text
expected: In CONTROLS pane, change an ORB param value and click "Save & Hot-reload"; green text "Params saved — engine reloading" appears briefly then disappears
result: passed — green confirmation text appeared and auto-disappeared after ~2 seconds

### 7. Run Backtest button disables/re-enables
expected: Click "Run Backtest"; button shows "Running…" and is disabled; after polling completes, button returns to "Run Backtest" and enabled
result: passed — button disabled (label "Running…") during polling, re-enabled after stub completes

### 8. Playwright E2E test runs (optional — requires live servers)
expected: pnpm --filter web test:e2e passes or shows a meaningful failure (not a compilation error)
result: passed — 1 passed (13.4s); fixed testDir bug in playwright.config.ts (was './e2e' relative to e2e/ dir, should be '.')

## Summary

total: 8
passed: 8
issues: 0
pending: 0
skipped: 0
blocked: 0

## Gaps

None — all 8 tests passed. Bugs fixed inline:
- useStream.ts: stale ws.onclose/onerror clobbering connected state in React StrictMode dev mode
- page.tsx: replaced manual localStorage + SSR guard with react-resizable-panels autoSaveId (eliminates hydration mismatch warning)
- playwright.config.ts: testDir './e2e' → '.' (config file is already inside e2e/)

Phase 7 fully signed off — all 8 human UAT tests passed (2026-05-21).
