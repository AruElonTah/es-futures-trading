---
phase: "07"
plan: "01"
subsystem: backend-foundations
tags: [event-bus, strategy-registry, websocket, backtests, test-stubs]
dependency_graph:
  requires: []
  provides:
    - TOPIC_STRATEGY_RELOAD constant (events/models.py)
    - StrategyRegistry.reload() method (strategy/registry.py)
    - GET /backtests/{run_id} endpoint (routes/backtests.py)
    - backtests.status VARCHAR column (schema.sql + ensure_schema migration)
    - ConnectionManager._seq monotonic counter (ws.py)
    - Wave 0 test stubs (4 files)
  affects:
    - Plan 07-02: strategies router imports TOPIC_STRATEGY_RELOAD; uses StrategyRegistry.reload()
    - Plan 07-03: TradeHistoryPane.test.ts stubs turned GREEN
    - Plan 07-04: ws-reconnect.spec.ts stub turned GREEN; polls GET /backtests/{run_id}
tech_stack:
  added:
    - react-resizable-panels@2.1.9 (apps/web)
    - "@playwright/test@1.60.0" (apps/web devDependencies)
  patterns:
    - TDD RED/GREEN per task (2 tasks with failing tests committed before implementation)
    - ALTER TABLE ... ADD COLUMN IF NOT EXISTS for idempotent schema migrations
    - xfail pytest stubs for downstream plan enforcement (Nyquist rule)
    - Monotonic seq counter on ConnectionManager (per-instance, never resets)
key_files:
  created:
    - packages/trading-core/tests/test_phase7_plan01_foundations.py
    - packages/api/tests/test_ws_seq.py
    - packages/api/tests/test_strategies.py
    - apps/web/e2e/playwright.config.ts
    - apps/web/e2e/ws-reconnect.spec.ts
    - apps/web/__tests__/TradeHistoryPane.test.ts
  modified:
    - packages/trading-core/src/trading_core/events/models.py
    - packages/trading-core/src/trading_core/strategy/registry.py
    - packages/trading-core/src/trading_core/storage/schema.sql
    - packages/trading-core/src/trading_core/storage/duckdb_store.py
    - packages/api/src/api/routes/backtests.py
    - packages/api/src/api/ws.py
    - packages/api/tests/test_health.py
    - packages/api/tests/test_routes.py
    - apps/web/package.json
    - pnpm-lock.yaml
decisions:
  - "backtests status column added as VARCHAR DEFAULT 'complete' with ALTER TABLE IF NOT EXISTS migration for existing DBs"
  - "seq counter is per-ConnectionManager-instance (not per-client-connection); never resets on reconnect"
  - "xfail(strict=False) used for pytest stubs so they appear in report without blocking CI"
  - "GET /backtests/{run_id} uses COALESCE(status, 'complete') to handle rows pre-dating the column"
metrics:
  duration: "~25 minutes"
  completed: "2026-05-20"
  tasks: 3
  files: 16
---

# Phase 07 Plan 01: Backend Wiring Foundations and Wave 0 Test Stubs Summary

Backend wiring foundations with TDD: TOPIC_STRATEGY_RELOAD, StrategyRegistry.reload(), WS monotonic seq counter, GET /backtests/{run_id}, backtests status column, and 4 Wave 0 test stubs for downstream plans.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | EventBus topic + StrategyRegistry.reload() + backtests status + GET /backtests/{run_id} | f460e8e | events/models.py, registry.py, schema.sql, duckdb_store.py, routes/backtests.py |
| 2 | WS seq counter in ConnectionManager | aa7bc2a | ws.py, test_ws_stream.py |
| 3 | Wave 0 test stubs — Playwright config + 4 stub files | 9fc4a7f | playwright.config.ts, ws-reconnect.spec.ts, TradeHistoryPane.test.ts, test_strategies.py, package.json |

TDD RED commits: e373773 (Task 1), a0ad5f0 (Task 2)

## Verification Results

```
packages/api/tests/ + key trading-core tests: 78 passed, 4 skipped
TOPIC_STRATEGY_RELOAD: "strategy_reload" ✓
react-resizable-panels: importable ✓
test_strategies.py: 4 xfail stubs discoverable ✓
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] test_health.py route list assertion needed updating**
- **Found during:** Task 1
- **Issue:** `test_phase3_endpoints_registered` had an exact expected list of routes that didn't include the new `GET /backtests/{run_id}` endpoint.
- **Fix:** Added `/backtests/{run_id}` to the expected routes list.
- **Files modified:** `packages/api/tests/test_health.py`
- **Commit:** f460e8e

**2. [Rule 1 - Bug] test_routes.py response shape assertion needed updating**
- **Found during:** Task 1
- **Issue:** `test_get_backtests_response_shape` checked exact key set for backtest rows without `status`.
- **Fix:** Added `"status"` to the expected_keys set.
- **Files modified:** `packages/api/tests/test_routes.py`
- **Commit:** f460e8e

**3. [Rule 1 - Bug] test_ws_stream.py envelope assertion needed updating**
- **Found during:** Task 2
- **Issue:** `test_ws_stream_envelope_shape` asserted `set(msg.keys()) == {"type", "payload"}` exactly, but after adding `seq` the envelope now has 3 keys.
- **Fix:** Changed the assertion to check for the presence of `type`, `payload`, and `seq` individually (membership checks) rather than exact set equality.
- **Files modified:** `packages/api/tests/test_ws_stream.py`
- **Commit:** aa7bc2a

## Known Stubs

| File | Stub | Reason |
|------|------|--------|
| `apps/web/e2e/ws-reconnect.spec.ts` | `test.fixme(true, 'TODO: implement in Plan 07-04')` | Wave 4 work — full Playwright WS reconnect test |
| `apps/web/__tests__/TradeHistoryPane.test.ts` | `expect(true).toBe(false)` (2 tests) | Wave 3 work — TradeHistoryPane component not yet built |
| `packages/api/tests/test_strategies.py` | `pytest.skip(...)` with xfail (4 tests) | Wave 2 work — strategies routes not yet built |

## Threat Flags

No new security-relevant surface introduced beyond what's in the plan's threat model. GET /backtests/{run_id} reads DuckDB only with parameterized queries; status column is server-set only.

## Self-Check

- [x] `packages/trading-core/src/trading_core/events/models.py` — TOPIC_STRATEGY_RELOAD present
- [x] `packages/trading-core/src/trading_core/strategy/registry.py` — reload() method present
- [x] `packages/api/src/api/ws.py` — _seq counter present
- [x] `packages/api/src/api/routes/backtests.py` — get_backtest endpoint present
- [x] `apps/web/e2e/playwright.config.ts` — file exists
- [x] `packages/api/tests/test_strategies.py` — file exists
- [x] `apps/web/__tests__/TradeHistoryPane.test.ts` — file exists
- [x] All task commits exist: e373773, f460e8e, a0ad5f0, aa7bc2a, 9fc4a7f

## Self-Check: PASSED
