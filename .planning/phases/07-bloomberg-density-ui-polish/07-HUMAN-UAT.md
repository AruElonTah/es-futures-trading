---
status: partial
phase: 07-bloomberg-density-ui-polish
source: [07-VERIFICATION.md]
started: 2026-05-20T00:00:00Z
updated: 2026-05-20T00:00:00Z
---

## Current Test

[awaiting human testing]

## Tests

### 1. Four panes visible at /dashboard
expected: At 1440px+ width, four labeled panes visible — CHART (left, candlestick chart), BLOTTER (right top, positions table or empty state), HISTORY (right middle, trade table or empty state), CONTROLS (right bottom, strategy list)
result: [pending]

### 2. Drag-resize handles work
expected: Vertical 4px handle between chart and right column is draggable; three horizontal handles in right column are draggable; panes resize correctly
result: [pending]

### 3. localStorage layout persistence across reloads
expected: After dragging panes to custom sizes, reload the page; sizes are restored to the same positions
result: [pending]

### 4. /dashboard/blotter redirect
expected: Navigating to http://localhost:3000/dashboard/blotter redirects to http://localhost:3000/dashboard in the browser (HTTP 308)
result: [pending]

### 5. WS reconnect visible in ConnectionStatus indicator
expected: Kill uvicorn and restart it; ConnectionStatus indicator goes yellow/red then returns to connected state
result: [pending]

### 6. Strategy controls — "Params saved — engine reloading" transient text
expected: In CONTROLS pane, change an ORB param value and click "Save & Hot-reload"; green text "Params saved — engine reloading" appears briefly then disappears
result: [pending]

### 7. Run Backtest button disables/re-enables
expected: Click "Run Backtest"; button shows "Running…" and is disabled; after polling completes, button returns to "Run Backtest" and enabled
result: [pending]

### 8. Playwright E2E test runs (optional — requires live servers)
expected: pnpm --filter web test:e2e passes or shows a meaningful failure (not a compilation error)
result: [pending]

## Summary

total: 8
passed: 0
issues: 0
pending: 8
skipped: 0
blocked: 0

## Gaps
