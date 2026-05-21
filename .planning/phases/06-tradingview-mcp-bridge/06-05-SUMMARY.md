---
plan: 06-05
phase: 06-tradingview-mcp-bridge
status: complete
gap_closure: true
completed: 2026-05-20
commits:
  - 79e533a fix(06): shapes.py — correct draw_shape payload to MCP schema (point + overrides)
  - 6e51805 fix(06): bridge.py — pass signal ts_epoch to shapes.py draw helpers
  - 505e531 fix(06): bridge.py focus() — use chart_set_visible_range instead of chart_scroll_to_date
  - f1ee4e2 fix(06): bridge.create_alert() — add required price param to alert_create MCP call
  - 05a99c6 fix(06): TVAlertRequest — add price field; route passes price to bridge.create_alert()
  - 7089900 test(06): update focus and alert tests for MCP schema fixes
tasks_completed: 6/6
test_result: 104 passed in 33.57s
key-files:
  created: []
  modified:
    - packages/tv-bridge/src/tv_bridge/shapes.py
    - packages/tv-bridge/src/tv_bridge/bridge.py
    - packages/api/src/api/routes/tv.py
    - packages/tv-bridge/tests/test_bridge.py
    - packages/api/tests/test_tv_routes.py
---

## Self-Check: PASSED

## What Was Built

Fixed three production-breaking bugs found during Phase 6 UAT (all tests were mocked at the MCP layer and did not catch format mismatches).

### Gap 1 Fixed — shapes.py MCP format mismatch

All four draw_shape arg-builder functions produced flat dicts (`{shape, price, color, ...}`) that don't match the MCP `draw_shape` tool schema. Every draw_shape call was silently failing inside `_safe_draw_signal`'s except block — no shapes appeared on the TV Desktop chart.

**Fix:** Rewrote all four builders to use `{shape, point:{time,price}, overrides:json_string}` (horizontal_line) and `{shape, point, point2, overrides}` (rectangle), matching the verified MCP tool schema. Added `signal_ts_epoch: int` parameter to the three horizontal_line builders. Added `import json` to shapes.py.

### Gap 2 Fixed — focus() chart navigation

`chart_scroll_to_date` was immediately overridden by TV's auto-scroll, leaving the chart on the current session regardless of the requested date.

**Fix:** Replaced `chart_scroll_to_date` with `chart_set_visible_range`, computing explicit unix timestamp bounds for the target date's RTH session window (09:30–16:00 ET with 30-min buffers on each side). Added `timedelta` to datetime imports.

### Gap 3 Fixed — create_alert() missing price

`bridge.create_alert()` was passing `{condition, message}` to the `alert_create` MCP tool, which requires `{condition, price, message}`. Every POST /tv/alerts call returned 502.

**Fix:** Added `price: float` to `bridge.create_alert()` signature and MCP payload. Added `price: float` to `TVAlertRequest` Pydantic model. Updated route handler to pass `req.price`.

## Deviations

None. All 6 tasks executed as planned.

## Test Results

104 passed in 33.57s (up from 94 pre-gap — the +10 are from existing tests in the broader suite that were already present). All Phase 6 tests green.
