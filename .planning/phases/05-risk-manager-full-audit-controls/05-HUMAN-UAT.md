---
status: partial
phase: 05-risk-manager-full-audit-controls
source: [05-VERIFICATION.md]
started: 2026-05-18T00:00:00.000Z
updated: 2026-05-20T00:00:00.000Z
---

## Current Test

[testing complete]

## Tests

### 1. Flatten dialog requires typing "FLATTEN" to confirm
expected: Navigate to /dashboard/blotter, press F or click Flatten All. ConfirmationDialog appears with title "FLATTEN ALL POSITIONS". Confirm button is disabled until user types exactly "FLATTEN" in the input. After typing, button enables and clicking calls POST /api/flatten.
result: blocked
blocked_by: server
reason: "website is not operating, it wont load"

### 2. Engine state badge color changes on kill/pause
expected: Badge shows RUNNING (#4ade80 green) on load. After POST /api/kill (press K → type KILL → confirm), badge switches to KILLED (#ef4444 red) in real-time via WS engine_state_changed event. After POST /api/pause, badge shows PAUSED (#eab308 yellow).
result: blocked
blocked_by: server
reason: "website is not operating, it wont load"

### 3. ? key opens HelpOverlay from any focus context
expected: Press ? while focus is inside a table cell or other input. HelpOverlay appears listing F/K/P/? hotkeys. Press Escape to dismiss.
result: blocked
blocked_by: server
reason: "website is not operating, it wont load"

## Summary

total: 3
passed: 0
issues: 0
pending: 0
skipped: 0
blocked: 3

## Gaps
