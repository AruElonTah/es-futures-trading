---
phase: 07-bloomberg-density-ui-polish
reviewed: 2026-05-20T00:00:00Z
depth: standard
files_reviewed: 32
files_reviewed_list:
  - packages/trading-core/tests/test_phase7_plan01_foundations.py
  - packages/api/tests/test_ws_seq.py
  - packages/api/tests/test_strategies.py
  - apps/web/e2e/playwright.config.ts
  - apps/web/e2e/ws-reconnect.spec.ts
  - apps/web/__tests__/TradeHistoryPane.test.ts
  - packages/trading-core/src/trading_core/events/models.py
  - packages/trading-core/src/trading_core/strategy/registry.py
  - packages/trading-core/src/trading_core/storage/schema.sql
  - packages/trading-core/src/trading_core/storage/duckdb_store.py
  - packages/api/src/api/routes/backtests.py
  - packages/api/src/api/ws.py
  - packages/api/tests/test_health.py
  - packages/api/tests/test_routes.py
  - apps/web/package.json
  - apps/web/components/ConfirmationDialog.tsx
  - apps/web/components/HelpOverlay.tsx
  - apps/web/components/PaneContainer.tsx
  - packages/api/src/api/routes/strategies.py
  - apps/web/next.config.ts
  - apps/web/store/ws.ts
  - apps/web/hooks/useStream.ts
  - apps/web/lib/api.ts
  - apps/web/hooks/useBacktests.ts
  - apps/web/app/dashboard/page.tsx
  - packages/api/src/api/app.py
  - apps/web/components/BlotterPane.tsx
  - apps/web/components/TradeHistoryPane.tsx
  - apps/web/components/Chart.tsx
  - apps/web/components/StrategyControlsPane.tsx
  - apps/web/e2e/tsconfig.json
  - apps/web/vitest.config.ts
findings:
  critical: 4
  warning: 7
  info: 4
  total: 15
status: issues_found
---

# Phase 7: Code Review Report

**Reviewed:** 2026-05-20T00:00:00Z
**Depth:** standard
**Files Reviewed:** 32
**Status:** issues_found

## Summary

Phase 7 delivers a 4-pane Bloomberg-style terminal layout, strategy controls (toggle/params/run), WS monotonic sequence numbers, and a strategy hot-reload pathway. The architecture is largely coherent and the security posture on the critical paths (path-traversal guards, parameterized SQL, YAML-write-from-validated-model) is solid. However, four blocker-level defects were found spanning correctness, data integrity, and a broken test assumption that causes tests to pass in the wrong scenario. Seven warnings cover logic gaps that degrade reliability or produce silently wrong behavior in production use.

---

## Critical Issues

### CR-01: `write_pending_backtest` stores empty `equity_curve_path` that triggers 403 at the equity endpoint

**File:** `packages/trading-core/src/trading_core/storage/duckdb_store.py:817-829`

**Issue:** `write_pending_backtest` sets `equity_curve_path = ''`. When the UI transitions the run to `complete` and immediately calls `GET /backtests/{run_id}/equity`, the route at `backtests.py:203-218` resolves the empty string path. `Path('')` resolves to the current working directory (`Path.cwd()`). `Path.cwd().resolve()` then fails `relative_to(_EQUITY_ROOT)` because the CWD is not under `data/parquet/equity/`, triggering the 403 guard with detail `"forbidden equity path"`. The user sees a confusing permission error instead of a "not yet available" indicator. Additionally, this path is never a valid target — the equity file does not exist at CWD — so the correct response before the task finishes is 404, not 403.

**Fix:** Use a sentinel value the equity endpoint can recognize:
```python
# In write_pending_backtest:
[run_id, "orb-v1", "SPY", "1m", now_utc, now_utc, "pending", "__pending__", now_utc, "pending"]
```
Then in `get_backtest_equity` before the path-traversal check:
```python
if equity_curve_path in ("__pending__", ""):
    raise HTTPException(status_code=404, detail="equity curve not yet available")
```

---

### CR-02: `TOPIC_STRATEGY_RELOAD` is absent from `ALL_TOPICS` — hot-reload events never reach the browser

**File:** `packages/api/src/api/ws.py:39-48`

**Issue:** `ALL_TOPICS` lists 8 topics for the WS fan-out. `TOPIC_STRATEGY_RELOAD` (introduced in Phase 7 for D-14) is not included. When `PUT /strategies/{id}/params` publishes to this topic, the event is consumed only by the in-process `_strategy_reload_handler` in `app.py` — the browser never receives it. The comment in `ws.py` line 57 still says "all 7 EventBus topics" though there are already 8 in the tuple, confirming the new topic was simply forgotten. Any future frontend handler for strategy-reload confirmation will never fire.

**Fix:**
```python
from trading_core.events.models import (
    ...
    TOPIC_STRATEGY_RELOAD,
)

ALL_TOPICS: tuple[str, ...] = (
    TOPIC_BARS,
    TOPIC_SIGNALS,
    TOPIC_RISK_DECISIONS,
    TOPIC_FILLS,
    TOPIC_POSITIONS,
    TOPIC_EQUITY,
    TOPIC_DEGRADED_STATE,
    TOPIC_ENGINE_STATE,
    TOPIC_STRATEGY_RELOAD,   # Phase 7 D-14
)
```

---

### CR-03: WS seq tests use `asyncio.get_event_loop().run_until_complete()` across thread boundary — publishes to the wrong event loop

**File:** `packages/api/tests/test_ws_seq.py:68, 91, 117, 144`

**Issue:** All four sequence-counter tests call `asyncio.get_event_loop().run_until_complete(app.state.bus.publish(...))` from inside a synchronous `with client.websocket_connect("/stream") as ws:` block. `TestClient` runs the ASGI app in a background thread using `anyio`. The `app.state.bus` object's internal subscriber queues are bound to the event loop in that background thread. `asyncio.get_event_loop()` in the main thread returns a *different* loop — the one in the main thread. `run_until_complete` on the wrong loop means the `bus.publish()` coroutine runs on a loop that has no subscribers attached, so no message is ever enqueued. On Python 3.12 this also emits `DeprecationWarning: There is no current event loop` and will raise `RuntimeError` on Python 3.14+. The tests may appear to pass due to timing artifacts (e.g., the WS connection itself sends an implicit message on connect) rather than because the publish actually worked.

**Fix:** Publish via an HTTP trigger if one exists, or restructure as `anyio`-native async tests using `AsyncClient` with `ASGITransport`.

---

### CR-04: `loadSizes` accesses `localStorage` at render time — crashes during Next.js SSR/build

**File:** `apps/web/app/dashboard/page.tsx:50-56, 247, 248, 271, 280, 315, 330`

**Issue:** `loadSizes(LAYOUT_KEY_H, DEFAULT_H_SIZES)` is called directly as `defaultSize` prop values during the React render of six `<Panel>` components. Although the file is marked `'use client'`, Next.js 16 pre-renders Client Components on the server during `next build` (for static generation) and for SSR. `localStorage` is browser-only and throws `ReferenceError: localStorage is not defined` in the Node.js rendering environment. This breaks `next build` entirely and causes a 500 on first server-side render in any deployment scenario. The `onLayout` callback at line 241 which writes to `localStorage` is safe (callbacks only fire in the browser), but the read at render time is not.

**Fix:**
```typescript
function loadSizes(key: string, fallback: number[]): number[] {
  if (typeof window === 'undefined') return fallback  // SSR guard
  try {
    const raw = localStorage.getItem(key)
    if (raw) return JSON.parse(raw) as number[]
  } catch { /* silent fallback */ }
  return fallback
}
```

---

## Warnings

### WR-01: `BacktestRow` TypeScript interface missing `status` field — silent `undefined` at runtime

**File:** `apps/web/lib/api.ts:26-48`

**Issue:** The `GET /backtests` endpoint now returns a `status` field on every row (Phase 7, via `COALESCE(status, 'complete') AS status`). The `BacktestRow` interface does not include `status`. `useBacktests()` returning `BacktestRow[]` means TypeScript will not catch `backtests[0].status` accesses — they compile cleanly but evaluate to `undefined` at runtime. The workaround in `useStrategyRun` (line 91) uses `BacktestRow & { status?: '...' }` as an inline patch, but this does not fix the type gap for consumers of `useBacktests`.

**Fix:** Add `status` to `BacktestRow`:
```typescript
export interface BacktestRow {
  ...
  created_at: string
  status: 'pending' | 'running' | 'complete' | 'failed'
}
```
Then simplify `useStrategyRun` to return `BacktestRow` without the inline intersection.

---

### WR-02: `get_strategy_enabled` and `write_strategy_enabled` use `engine_state.session_id` to store per-strategy state — collides with real session IDs

**File:** `packages/trading-core/src/trading_core/storage/duckdb_store.py:757-798`

**Issue:** `write_strategy_enabled` inserts into `engine_state` using `session_id = strategy_id` (e.g., `"orb-v1"`). `get_strategy_enabled` queries `WHERE session_id = strategy_id`. The real `write_engine_state` (line 727) uses `session_id = <UUID7>` for global engine transitions. Both write to the same `engine_state` table with no discriminator column. The result: `get_strategy_enabled("orb-v1")` queries only rows inserted by `write_strategy_enabled`, so the global kill-switch (`POST /kill` → `write_engine_state(session_id=UUID, state="killed")`) has no effect on `get_strategy_enabled` output. Strategy controls pane shows strategy as ACTIVE while the engine is globally killed. The states are logically disconnected in a way that will mislead the operator.

**Fix:** Add a `kind` column (`'global'` | `'strategy'`) to `engine_state`, or create a dedicated `strategy_state` table that cannot be confused with global engine state.

---

### WR-03: `put_strategy_params` uses non-atomic YAML write — file corruption possible on concurrent requests

**File:** `packages/api/src/api/routes/strategies.py:201-212`

**Issue:** The route reads the YAML file, modifies it in memory, then opens the same path with `"w"` and calls `yaml.dump`. Between the truncation (`open("w")`) and the completion of `yaml.dump`, the file is empty or partially written. A concurrent `GET /strategies` request that reads the file during this window receives either empty content or a YAML parse error. The `yaml.safe_load(f) or {}` fallback in `get_strategies` line 138 will silently return `{}` for an empty file, causing the strategy to disappear from the list. Additionally, `yaml.dump` does not preserve comments or key ordering from the original file.

**Fix:** Write to a temporary file then atomically replace:
```python
import os, tempfile
tmp_path = yaml_path.with_suffix('.yaml.tmp')
with tmp_path.open("w", encoding="utf-8") as f:
    yaml.dump(current, f, default_flow_style=False)
os.replace(tmp_path, yaml_path)
```

---

### WR-04: `_run_backtest_task` has no `finally` block — failed task leaves `status='pending'` forever, causing infinite polling

**File:** `packages/api/src/api/routes/strategies.py:98-114`

**Issue:** The stub background task catches nothing. If `store._conn.execute(...)` raises (e.g., constraint violation, DuckDB lock), the exception is silently swallowed by `asyncio.create_task` (logged at WARNING by asyncio's exception handler but not re-raised). The `backtests` row stays at `status='pending'`. The frontend's `useStrategyRun` polls every 2 seconds indefinitely when status is `'pending'` (`refetchInterval` returns `2000` on line 103 of `useBacktests.ts`). Every subsequent page load reattaches the polling hook to the orphaned `run_id` stored in `StrategyControlsPane` state — eventually creating a background timer leak.

**Fix:**
```python
async def _run_backtest_task(run_id: str, app_state: object) -> None:
    store: DuckDBStore = getattr(app_state, "store", None)
    try:
        await asyncio.sleep(2)
        if store is not None:
            store._conn.execute(
                "UPDATE backtests SET status = 'complete' WHERE run_id = ?", [run_id]
            )
    except Exception as exc:
        _log.error("backtest.stub_error", run_id=run_id, error=str(exc))
        if store is not None:
            try:
                store._conn.execute(
                    "UPDATE backtests SET status = 'failed' WHERE run_id = ?", [run_id]
                )
            except Exception:
                pass
```

---

### WR-05: `useStream` casts `positions` payload as `any` — crashes `BlotterPane` if payload shape differs from `Position[]`

**File:** `apps/web/hooks/useStream.ts:111-113`

**Issue:** The `positions` case casts `msg.payload as any` and passes it directly to `setPositions`. The backend Phase 5 `TOPIC_POSITIONS` event model serializes as `{topic, emitted_at, positions: [...]}` via `model_dump(mode="json")` — not a bare array. If the WS fan-out wraps it in `{"type": "positions", "seq": N, "payload": {topic: ..., positions: [...]}}`, then `msg.payload` is an object with a `positions` key, not an array. `setPositions` stores this object as `Position[]`. `BlotterPane` then calls `positions.map(...)` on an object, throwing `TypeError: positions.map is not a function` and crashing the blotter.

**Fix:** Extract the array safely:
```typescript
case 'positions': {
  const raw = msg.payload
  const arr = Array.isArray(raw) ? raw : (raw as Record<string, unknown>).positions
  if (Array.isArray(arr)) setPositions(arr as Position[])
  break
}
```

---

### WR-06: `ConfirmationDialog` Enter key handler can double-invoke `onConfirm` when confirm button has focus

**File:** `apps/web/components/ConfirmationDialog.tsx:63-65`

**Issue:** The `keydown` listener fires `onConfirm()` on Enter when `value === confirmString`. When the confirm button has keyboard focus and the user presses Enter, the browser also fires the button's `onClick` handler (native button behavior for keyboard activation). Both handlers call `onConfirm()` in the same tick. For `handleKillConfirm` and `handleFlattenConfirm` in `BlotterPane.tsx`, this means two POST requests are dispatched to `/kill` or `/flatten`. The kill endpoint writes two `engine_state` rows with `state='killed'`, doubling the audit log entries. The flatten endpoint dispatches flatten twice.

**Fix:** Call `e.preventDefault()` on the keydown event and close the dialog before calling `onConfirm`:
```typescript
if (e.key === 'Enter' && value === confirmString) {
  e.preventDefault()
  onConfirm()
}
```
The `onClose()` call should remain in each individual confirm handler after the fetch completes rather than in the keydown handler to keep the dialog visible while the request is in flight.

---

### WR-07: `Chart.tsx` Effect 3 `scrollToPosition` offset is calculated in bar-index space, not lightweight-charts logical space

**File:** `apps/web/components/Chart.tsx:242-244`

**Issue:** `chartRef.current.timeScale().scrollToPosition(idx - Math.floor(sorted.length * 0.3), false)` passes a value that can range from approximately -117 to 390 (for 390 1-minute bars). `scrollToPosition` in lightweight-charts v5 takes a **logical bar offset from the current right edge**, where 0 = current rightmost bar, negative = scroll right (future), positive = scroll left (past). Passing `idx` (an absolute index from the left) does not produce a scroll to the target bar — it scrolls an arbitrary distance that is correct only by coincidence when `idx` happens to match a small positive offset. For trades early in the session (e.g., `idx=15`), the chart scrolls only 15 bars left of the current view, not to bar 15.

**Fix:** Compute the offset from the right edge:
```typescript
const rightmostIdx = sorted.length - 1
const barsFromRight = rightmostIdx - idx
// Center target bar with 30% margin from right
const position = barsFromRight - Math.floor(sorted.length * 0.3)
chartRef.current.timeScale().scrollToPosition(position, false)
```

---

## Info

### IN-01: `StrategyRegistry.reload` has no path-safety guard on `strategy_id` at the library level

**File:** `packages/trading-core/src/trading_core/strategy/registry.py:87-120`

**Issue:** The primary lookup at line 107 constructs `d / f"{strategy_id}.yaml"` without validating `strategy_id`. The regex guard exists in the route layer (`strategies.py` line 184) but not inside the library method. If `reload` is ever called from a non-route context (e.g., a CLI script or test helper) with an unsanitized ID containing `../`, the path construction would escape `strategies_dir`. No current caller passes user input directly, so this is a defense-in-depth gap rather than an active vulnerability.

**Fix:** Add an input guard at the top of `reload`:
```python
import re
if not re.match(r'^[a-z0-9_-]+$', str(strategy_id)):
    raise ValueError(f"Invalid strategy_id: {strategy_id!r}")
```

---

### IN-02: `useStrategyRun` polling has no timeout guard — permanently polls if backend never writes a terminal status

**File:** `apps/web/hooks/useBacktests.ts:102-106`

**Issue:** `refetchInterval` returns `2000` when `status === 'pending'` and `false` otherwise. If the background task crashes before writing any status update and `store` is `None` at line 105 (silently skipped), the row stays at `'pending'` and the hook polls at 2-second intervals until the component unmounts. `StrategyControlsPane` holds the `runId` in component state — if the user navigates away and back, the `runId` is lost from state but the network polling from a prior mount is already cleaned up by React. The main risk is during the current session: a permanently-pending run accumulates 1 network request per 2 seconds as long as `StrategyControlsPane` is mounted.

**Fix:** Add a maximum poll duration:
```typescript
refetchInterval: (query) => {
  const data = query.state.data
  if (!data || data.status === 'pending') {
    // Stop after 60s regardless
    const age = Date.now() - (query.state.dataUpdatedAt ?? 0)
    return age < 60_000 ? 2000 : false
  }
  return false
},
```

---

### IN-03: `TradeHistoryPane` hold-time computation is in wall-clock minutes, but column is labeled `HOLD` implying bars — ambiguous for non-1m timeframes

**File:** `apps/web/components/TradeHistoryPane.tsx:364-368`

**Issue:** `holdBars` is computed as `(exit_ms - entry_ms) / 60000`, which yields wall-clock minutes. `formatHoldTime` then treats this as a count of 60-second units and formats as `HH:MM`. For 1m bars this is correct. For 5m or 15m bars (supported in the schema), a 3-bar trade spanning 15 minutes of 5m bars would display as `00:15` (minutes), which appears correct but is semantically "15 minutes" not "3 bars". The variable is named `holdBars` but the value is actually `holdMinutes`. This is a naming/semantic bug that will cause confusion if multi-timeframe support is added.

**Fix:** Rename `holdBars` to `holdMinutes` throughout, or compute it only from wall-clock time without the misleading "bars" framing.

---

### IN-04: `test_phase3_endpoints_registered` comment says "Phase 5 surface" but lists Phase 6 and Phase 7 routes

**File:** `packages/api/tests/test_health.py:77-118`

**Issue:** The test comment and docstring describe the "Phase 5 surface" but the expected route list includes `/tv/focus`, `/tv/alerts`, `/tv/alerts/{alert_id}`, `/tv/status` (Phase 6) and `/strategies`, `/strategies/{strategy_id}/params`, `/strategies/{strategy_id}/toggle`, `/backtests/run` (Phase 7). The test function name is `test_phase3_endpoints_registered`. All three — function name, docstring, and expected list — are out of sync with the actual phase. This is a documentation-only issue but creates confusion when the test fails and the developer reads the error message expecting a Phase 3 surface.

**Fix:** Rename to `test_api_endpoints_registered`, update the docstring to say "Phase 7 surface (all routes registered through Phase 7)", and keep the exhaustive list as-is.

---

_Reviewed: 2026-05-20T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
