---
phase: 07-bloomberg-density-ui-polish
fixed_at: 2026-05-20T00:00:00Z
review_path: .planning/phases/07-bloomberg-density-ui-polish/07-REVIEW.md
iteration: 1
findings_in_scope: 11
fixed: 11
skipped: 0
status: all_fixed
---

# Phase 7: Code Review Fix Report

**Fixed at:** 2026-05-20T00:00:00Z
**Source review:** `.planning/phases/07-bloomberg-density-ui-polish/07-REVIEW.md`
**Iteration:** 1

**Summary:**
- Findings in scope: 11 (4 Critical + 7 Warning)
- Fixed: 11
- Skipped: 0

---

## Fixed Issues

### CR-01: `write_pending_backtest` stores empty `equity_curve_path` → 403 instead of 404

**Files modified:** `packages/trading-core/src/trading_core/storage/duckdb_store.py`, `packages/api/src/api/routes/backtests.py`
**Commit:** `9558d98`
**Applied fix:** Changed the INSERT value for `equity_curve_path` from `''` to `'__pending__'` in `write_pending_backtest`. Added an early sentinel check in `get_backtest_equity` that returns HTTP 404 with `"equity curve not yet available"` when `equity_curve_path` is `'__pending__'` or `''`, before the path-traversal guard that was erroneously returning 403.

---

### CR-02: `TOPIC_STRATEGY_RELOAD` missing from `ALL_TOPICS` in ws.py

**Files modified:** `packages/api/src/api/ws.py`
**Commit:** `b271aeb`
**Applied fix:** Added `TOPIC_STRATEGY_RELOAD` to the imports from `trading_core.events.models` and appended it to the `ALL_TOPICS` tuple. Updated the topic count in the module docstring and `start_background_fan_out` docstring from 7/8 to 9 to keep comments accurate.

---

### CR-03: WS seq tests use wrong event loop — `asyncio.get_event_loop().run_until_complete()` in main thread

**Files modified:** `packages/api/tests/test_ws_seq.py`
**Commit:** `054b839`
**Applied fix:** Replaced all four `asyncio.get_event_loop().run_until_complete(app.state.bus.publish(...))` calls with `anyio.from_thread.run(app.state.bus.publish, topic, event)`. Starlette's `TestClient` establishes an `anyio` blocking portal in its background thread; `anyio.from_thread.run()` correctly dispatches coroutines to that portal's event loop rather than the main thread's loop. Also removed the unused `asyncio` import and added the `anyio.from_thread` import.

---

### CR-04: `loadSizes` accesses `localStorage` at render time — crashes SSR/build

**Files modified:** `apps/web/app/dashboard/page.tsx`
**Commit:** `34e7398`
**Applied fix:** Added `if (typeof window === 'undefined') return fallback` as the first line of `loadSizes`. This guard returns the fallback array immediately during Next.js server-side pre-rendering (where `window` is not defined), preventing `ReferenceError: localStorage is not defined` during `next build` and SSR.

---

### WR-01: `BacktestRow` TypeScript interface missing `status` field

**Files modified:** `apps/web/lib/api.ts`, `apps/web/hooks/useBacktests.ts`
**Commit:** `e8c57cf`
**Applied fix:** Added `status: 'pending' | 'running' | 'complete' | 'failed'` to the `BacktestRow` interface in `api.ts`. Simplified `useStrategyRun` in `useBacktests.ts` to return `useQuery<BacktestRow>` directly, removing the inline `BacktestRow & { status?: '...' }` intersection workaround that is no longer needed.

---

### WR-02: `write_strategy_enabled` uses `engine_state` table with `session_id = strategy_id` — collides with real session IDs

**Files modified:** `packages/trading-core/src/trading_core/storage/duckdb_store.py`, `packages/trading-core/src/trading_core/storage/schema.sql`
**Commit:** `8d90f34`
**Applied fix:** Added a `kind VARCHAR NOT NULL DEFAULT 'global'` column to the `engine_state` table in `schema.sql`. Updated `WRITE_ENGINE_STATE_SQL` to explicitly insert `kind='global'`, `GET_ENGINE_STATE_SQL` to filter `WHERE kind = 'global'`, `get_strategy_enabled` to filter `WHERE session_id = ? AND kind = 'strategy'`, and `write_strategy_enabled` to insert `kind='strategy'`. The `DEFAULT 'global'` ensures any pre-existing rows without the column value default correctly on upgrade.

---

### WR-03: `put_strategy_params` uses non-atomic YAML write — file corruption on concurrent requests

**Files modified:** `packages/api/src/api/routes/strategies.py`
**Commit:** `3267cc5`
**Applied fix:** Added `import os` to the imports. Replaced the direct `with yaml_path.open("w", ...) as f: yaml.dump(...)` write with a two-step atomic write: write to `yaml_path.with_suffix('.yaml.tmp')`, then call `os.replace(tmp_path, yaml_path)`. `os.replace` is atomic on POSIX and effectively atomic on Windows (rename of same-filesystem files), so concurrent `GET /strategies` requests never see an empty or partially-written YAML file.

---

### WR-04: `_run_backtest_task` has no `finally` block — failed task leaves `status='pending'` forever

**Files modified:** `packages/api/src/api/routes/strategies.py`
**Commit:** `21d8ab5`
**Applied fix:** Wrapped the task body in `try/except Exception`. On success, `status='complete'` is written as before. On any exception, the error is logged via `_log.error` and the code attempts to write `status='failed'` (with its own inner try/except to avoid masking the original error). This prevents infinite polling by the frontend when a background task crashes.

---

### WR-05: `useStream` casts `positions` payload as `any` — crashes BlotterPane if payload is not a bare array

**Files modified:** `apps/web/hooks/useStream.ts`
**Commit:** `07d7770`
**Applied fix:** Added `type Position` to the import from `@/store/ws`. Replaced the `setPositions(msg.payload as any)` cast with safe extraction: if `msg.payload` is already an array use it directly; otherwise extract `.positions` from the object (matching the backend's `{topic, emitted_at, positions: [...]}` shape). Only calls `setPositions` when the extracted value is confirmed to be an array, preventing `TypeError: positions.map is not a function` in BlotterPane.

---

### WR-06: `ConfirmationDialog` Enter key handler can double-invoke `onConfirm`

**Files modified:** `apps/web/components/ConfirmationDialog.tsx`
**Commit:** `01e75a2`
**Applied fix:** Added `e.preventDefault()` inside the Enter branch of the `keydown` handler. This suppresses the browser's native button-activation behavior when the confirm button has focus, preventing a second `onConfirm()` call from the button's `onClick` handler in the same event tick.

---

### WR-07: `Chart.tsx` `scrollToPosition` uses absolute bar-index instead of offset from right edge

**Files modified:** `apps/web/components/Chart.tsx`
**Commit:** `7734322`
**Applied fix:** Replaced `idx - Math.floor(sorted.length * 0.3)` with the correct right-edge-relative calculation: `(sorted.length - 1 - idx) - Math.floor(sorted.length * 0.3)`. `scrollToPosition` in lightweight-charts v5 takes a logical offset from the current rightmost bar (positive = scroll left/past), not an absolute bar index. The new calculation correctly navigates to early-session bars (small `idx`) that previously only scrolled a few bars left of the current view.

---

## Skipped Issues

None — all 11 in-scope findings were successfully fixed.

---

_Fixed: 2026-05-20T00:00:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
