---
status: partial
phase: 06-tradingview-mcp-bridge
source: [06-VERIFICATION.md]
started: 2026-05-19
updated: 2026-05-19
---

## Current Test

[awaiting human testing]

## Tests

### 1. POST /tv/focus drives TV Desktop chart visually
expected: curl POST to /tv/focus returns 202 within <1s and TV Desktop chart switches to CME_MINI:ES1! scrolling to the requested date within ~15s
result: [pending]

### 2. Drawing pipeline renders correct shapes on live chart
expected: Entry arrow, stop line, target line appear on TV Desktop within 2s of Signal publish; ORB box drawn at correct opening-range coordinates (09:30–09:45 high/low)
result: [pending]
note: VERIFICATION.md flagged that bridge.py uses stub ORB coordinates (signal.entry * 1.001/0.999) — verify whether actual orb_high/orb_low from Signal are used or if a gap-closure plan is needed

### 3. Author TV Alert button round-trips to TV Desktop Alerts panel
expected: Click button in blotter, toast shows tv_alert_id, corresponding alert visible in TV Desktop alerts panel
result: [pending]

### 4. TV crash isolation visible in live system
expected: Force-kill TV Desktop → degradation banner appears in Next.js UI → FastAPI logs show reconnect backoff → auto-reconnect on TV restart within ~30s
result: [pending]

## Summary

total: 4
passed: 0
issues: 0
pending: 4
skipped: 0
blocked: 0

## Gaps
