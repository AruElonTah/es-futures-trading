---
status: complete
phase: 06-tradingview-mcp-bridge
source: [06-01-SUMMARY.md, 06-02-SUMMARY.md, 06-03-SUMMARY.md, 06-04-SUMMARY.md, 06-05-SUMMARY.md]
started: 2026-05-20
updated: 2026-05-20
note: "Re-verification pass after Plan 05 gap closure. Previous UAT (06-HUMAN-UAT.md) found 3 issues — all fixed."
---

## Current Test

[testing complete]

## Tests

### 1. Drawing pipeline — entry, stop, target render on TV Desktop
expected: |
  After a Signal is published, draw_shape is called with the correct MCP payload:
  {shape, point:{time, price}, overrides:json_string} for horizontal lines.
  Entry arrow (green), stop line (dashed red), and target line (dashed blue)
  appear on the TV Desktop chart within ~2s. Shapes are visible and positioned
  at the correct prices. No silent failure in _safe_draw_signal.
result: pass

### 2. POST /tv/focus navigates chart to requested date
expected: |
  curl POST to /tv/focus with a valid symbol and date (e.g. 2026-05-01) returns
  202 in <1s. The TV Desktop chart switches to CME_MINI:ES1! and sets visible
  range to the target date's RTH window (09:30–16:00 ET ±30 min buffers) using
  chart_set_visible_range. TV auto-scroll does NOT override the navigation.
  Chart stays on the requested date/session.
result: pass

### 3. Author TV Alert round-trip — button to TV Desktop Alerts panel
expected: |
  Click the "Author TV Alert" button in the blotter dashboard. POST /tv/alerts
  returns 201 with a JSON body containing alert_id and tv_alert_id. The
  corresponding alert appears in the TV Desktop Alerts panel. Price field is
  correctly included in the alert_create MCP call (no 502 error).
result: pass
note: "Required 3 additional fixes: (1) core/alerts.js wrong aria-label case + wrong input selector; (2) bridge.create_alert() must call alert_list after DOM create to resolve tv_alert_id; (3) AuthorTVAlertButton missing price prop in fetch body."

### 4. TV crash isolation — pipeline continues under forced disconnect
expected: |
  Force-kill TV Desktop (or simulate connection drop). The FastAPI app logs show
  DegradedStateEvent published and reconnect backoff starting. The trading
  pipeline continues processing signals without skipping any (risk decisions
  still flow; draw calls silently absorbed). On TV Desktop restart, bridge
  reconnects automatically within ~30s.
result: skipped
reason: "Requires destructive TV Desktop kill. Covered by test_pipeline_continues_when_tv_killed integration test."

## Summary

total: 4
passed: 3
issues: 0
pending: 0
skipped: 1
blocked: 0

## Gaps

[none — all resolved]
