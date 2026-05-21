---
status: complete
phase: 06-tradingview-mcp-bridge
source: [06-VERIFICATION.md]
started: 2026-05-19
updated: 2026-05-20
---

## Current Test

[testing complete]

## Tests

### 1. POST /tv/focus drives TV Desktop chart visually
expected: curl POST to /tv/focus returns 202 within <1s and TV Desktop chart switches to CME_MINI:ES1! scrolling to the requested date within ~15s
result: issue
reported: "API returns 202 in 0.21s (PASS). Symbol switches to CME_MINI:ES1! (PASS). Date scroll FAILS — chart_scroll_to_date reports success but TV auto-scroll immediately overrides it, chart stays on current session. Also uncovered: bridge supervisor was never connecting at all due to io.StringIO errlog (no fileno() on Windows) — fixed by removing errlog arg from stdio_client in bridge.py."
severity: major

### 2. Drawing pipeline renders correct shapes on live chart
expected: Entry arrow, stop line, target line appear on TV Desktop within 2s of Signal publish; ORB box drawn at correct opening-range coordinates (09:30–09:45 high/low)
result: issue
reported: "MCP draw_shape works correctly when called directly — entry (green solid), stop (red dashed), target (blue dashed) render on TV Desktop with correct colors and labels. However bridge shapes.py produces wrong format (flat {shape, price, color}) vs MCP tool schema ({shape, point:{time,price}, overrides:json_string}). Production signal draw path fails silently. ORB box confirmed as stub coordinates (known, flagged in VERIFICATION.md)."
severity: major

### 3. Author TV Alert button round-trips to TV Desktop Alerts panel
expected: Click button in blotter, toast shows tv_alert_id, corresponding alert visible in TV Desktop alerts panel
result: issue
reported: "POST /tv/alerts returns 502. Root cause: bridge.create_alert() calls alert_create tool without required price (number) field — tool requires {condition, price, message}. Bridge signature only passes {condition, message}. Direct MCP alert_create also returned success:false (DOM fallback failed, Alerts panel likely needs to be open). Both the bridge call format and the direct tool call fail."
severity: major

### 4. TV crash isolation visible in live system
expected: Force-kill TV Desktop → degradation banner appears in Next.js UI → FastAPI logs show reconnect backoff → auto-reconnect on TV restart within ~30s
result: skipped
reason: "Skipped — requires destructive TV Desktop kill which would disrupt active UAT session. Context constraints also prevent full test cycle."

## Summary

total: 4
passed: 0
issues: 3
pending: 0
skipped: 1
blocked: 0

## Gaps

- truth: "POST /tv/focus scrolls TV Desktop chart to the requested date within ~15s"
  status: failed
  reason: "chart_scroll_to_date reports success but TV auto-scroll overrides it immediately. Also fixed: bridge supervisor was failing to connect due to io.StringIO errlog not having fileno() on Windows — removed errlog arg from stdio_client."
  severity: major
  test: 1
  artifacts: [packages/tv-bridge/src/tv_bridge/bridge.py]
  missing: ["Disable TV auto-scroll before chart_scroll_to_date (e.g. ui_click the Follow Last Bar button off) or use chart_set_visible_range instead"]

- truth: "Entry arrow, stop line, target line appear on TV Desktop within 2s of Signal publish"
  status: failed
  reason: "bridge shapes.py arg-builder functions produce flat {shape, price, color, line_style, line_width} dict but MCP draw_shape expects {shape, point:{time,price}, overrides:json_string}. Production draw path fails silently in _safe_draw_signal except block."
  severity: major
  test: 2
  artifacts: [packages/tv-bridge/src/tv_bridge/shapes.py]
  missing: ["Fix shapes.py builders to produce {shape, point:{time,price}, overrides:json_string} matching MCP tool schema; also fix ORB box to use real orb_high/orb_low from signal context"]

- truth: "Author TV Alert button round-trips to TV Desktop Alerts panel with valid tv_alert_id"
  status: failed
  reason: "bridge.create_alert() missing required price param in alert_create call. MCP tool requires {condition:enum, price:number, message}; bridge passes {condition:string, message} only. Direct MCP call also failed (success:false, DOM fallback) — Alerts panel may need to be open."
  severity: major
  test: 3
  artifacts: [packages/tv-bridge/src/tv_bridge/bridge.py]
  missing: ["Add price param to create_alert signature and alert_create call; open Alerts panel before creating alert or use non-DOM approach"]
