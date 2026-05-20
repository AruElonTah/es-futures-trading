---
phase: 07-bloomberg-density-ui-polish
reviewed: 2026-05-20T00:00:00Z
depth: standard
files_reviewed: 27
files_reviewed_list:
  - apps/web/__tests__/TradeHistoryPane.test.ts
  - apps/web/__tests__/useStream.test.ts
  - apps/web/app/dashboard/page.tsx
  - apps/web/components/BlotterPane.tsx
  - apps/web/components/Chart.tsx
  - apps/web/components/ConfirmationDialog.tsx
  - apps/web/components/HelpOverlay.tsx
  - apps/web/components/PaneContainer.tsx
  - apps/web/components/StrategyControlsPane.tsx
  - apps/web/components/TradeHistoryPane.tsx
  - apps/web/e2e/playwright.config.ts
  - apps/web/e2e/ws-reconnect.spec.ts
  - apps/web/hooks/useBacktests.ts
  - apps/web/hooks/useStream.ts
  - apps/web/lib/api.ts
  - apps/web/next.config.ts
  - apps/web/store/ws.ts
  - apps/web/vitest.config.ts
  - packages/api/src/api/app.py
  - packages/api/src/api/routes/backtests.py
  - packages/api/src/api/routes/strategies.py
  - packages/api/src/api/ws.py
  - packages/api/tests/test_strategies.py
  - packages/api/tests/test_ws_seq.py
  - packages/trading-core/src/trading_core/events/models.py
  - packages/trading-core/src/trading_core/storage/duckdb_store.py
  - packages/trading-core/src/trading_core/strategy/registry.py
findings:
  critical: 4
  warning: 7
  info: 4
  total: 15
status: issues_found
---

# Phase 07: Code Review Report

**Reviewed:** 2026-05-20T00:00:00Z
**Depth:** standard
**Files Reviewed:** 27
**Status:** issues_found

## Summary

This phase adds a 4-pane Bloomberg-style terminal layout to the dashboard, including a BlotterPane
migration, a new TradeHistoryPane with equity+DD chart, a StrategyControlsPane with hot-reload,
WS reconnect improvements with sequence-number gap detection, and E2E Playwright scaffolding.

The implementation is broadly well-structured. Security posture is good: CORS is restricted,
path-traversal guards are layered, SQL injection risk is managed with parameterized queries, and
Pydantic validates API inputs before YAML writes. However, four critical bugs were found:
one localStorage access that crashes on server render (SSR), one chart lifecycle stale-closure
bug that fires scrolling on the wrong chart instance, an unguarded `loadSizes()` return value that
allows persisted corrupt data to pass through without length validation, and a missing `focusedBarTs`
from the store selector in `TradeHistoryPane` that will cause the focused-row highlight to never
update. Seven warnings address real quality gaps including silent error swallowing, a race condition
in the WS reconnect path, and a `get_strategy_enabled` implementation that piggybacks on the
engine-state table rather than a dedicated column.

---

## Critical Issues

### CR-01: `loadSizes()` called at module parse time — crashes on server render (SSR)

**File:** `apps/web/app/dashboard/page.tsx:51-56`

**Issue:** `loadSizes()` calls `localStorage.getItem()` at the top level of the module, which
executes during Next.js server-side rendering before any `'use client'` boundary is hydrated.
The more subtle form of the bug is that `loadSizes()` is called directly as a `defaultSize` prop
value (lines 247, 271, 279, 316, 334):

```tsx
defaultSize={loadSizes(LAYOUT_KEY_H, DEFAULT_H_SIZES)[0]}
```

These calls happen on every render, but React renders components in SSR context before the
browser runtime is available. On Next.js App Router, `'use client'` does not protect module-level
code from running in the Node.js server process during SSR — it only marks the component as
client-only. `localStorage` is `undefined` in the Node.js environment. The `try/catch` in
`loadSizes()` at line 54 does catch a `ReferenceError` on `undefined.getItem`, so the crash
is silently swallowed and the default is returned. This means the layout persistence feature
silently stops working whenever the function is called in SSR context. Additionally, the
`onLayout` handler at line 241 calls `localStorage.setItem(...)` unconditionally, which crashes
the server if this component is ever rendered server-side without the try/catch guard.

**Fix:** Gate all `localStorage` access behind `typeof window !== 'undefined'`:

```tsx
function loadSizes(key: string, fallback: number[]): number[] {
  if (typeof window === 'undefined') return fallback
  try {
    const raw = localStorage.getItem(key)
    if (raw) {
      const parsed = JSON.parse(raw) as number[]
      // Validate length matches expected layout before trusting persisted data
      if (Array.isArray(parsed) && parsed.length === fallback.length) return parsed
    }
  } catch { /* silent fallback */ }
  return fallback
}
```

And in `onLayout`:
```tsx
onLayout={(sizes: number[]) => {
  if (typeof window !== 'undefined') {
    localStorage.setItem(LAYOUT_KEY_H, JSON.stringify(sizes))
  }
}}
```

---

### CR-02: Stale-closure bug — `setFocusedBarTs` in `Chart` Effect 3 captures stale `bars` ref

**File:** `apps/web/components/Chart.tsx:226-250`

**Issue:** Effect 3 (the focusedBarTs scroll handler) lists `[focusedBarTs, bars, setFocusedBarTs]`
as its dependencies. When `focusedBarTs` fires, the effect re-runs with the current `bars` array.
However, the scroll logic computes a position as `idx - Math.floor(sorted.length * 0.3)`. The
`scrollToPosition` API takes a logical position from the *current* chart's time scale, where
position 0 is the rightmost visible bar. If `bars` has changed since the chart was last created
(e.g., a refetch added bars), `sorted.length` is the full new array length but the chart's
displayed data may be the previous data (Effect 1 only re-runs when `bars` changes, recreating
the chart). More critically, after `chart.remove()` in Effect 1's cleanup, `chartRef.current`
is set to `null` at line 172 **before** `chart.remove()` is called (the comment at line 172
says "Clear before remove"). But the cleanup order is:

```
chartRef.current = null  // line 172
seriesRef.current = null // line 173
chart.remove()           // line 174
```

This means if Effect 3 fires concurrently between `chartRef.current = null` and the next chart
being assigned in the new Effect 1 run, the early-return guard at line 227 fires correctly.
However, there is a real race between Effect 1's async teardown and Effect 3 firing from a state
change: React batches state updates but effects can interleave. If `focusedBarTs` is set and
`bars` changes in the same render cycle, Effect 3 can fire with a stale `chartRef` pointing to
the destroyed chart, causing a call on a removed chart object.

**Fix:** Add a `mounted` flag inside Effect 3, pattern-matched to Effect 1's approach:

```tsx
useEffect(() => {
  if (!focusedBarTs || !seriesRef.current || !chartRef.current) return
  const chart = chartRef.current
  if (!chart) return  // defensive double-check after destructuring

  // ... scroll logic ...

  setFocusedBarTs(null)
}, [focusedBarTs, bars, setFocusedBarTs])
```

Also move `chartRef.current = null` to **after** `chart.remove()` to prevent the window where
`chartRef.current` is null but the old chart object is still alive:

```python
# In Effect 1 cleanup:
return () => {
  resizeObserver.disconnect()
  seriesRef.current = null
  chart.remove()               // remove first
  chartRef.current = null      // then null the ref
}
```

---

### CR-03: `loadSizes()` does not validate persisted array length — corrupt data crashes layout

**File:** `apps/web/app/dashboard/page.tsx:50-56`

**Issue:** `loadSizes()` returns whatever `JSON.parse` produces without checking the length
of the parsed array against `fallback`. The `react-resizable-panels` library requires that the
sum of all panel sizes equals 100, and a persisted array with wrong length (e.g., 2 values for a
3-panel layout after a code change that added a panel) will either crash the library or produce
a broken invisible layout. This is a correctness bug: any deployment that changes the number of
panels will silently corrupt the layout for returning users who have persisted sizes.

**Fix:** Validate the length before returning (already shown in CR-01 fix):

```tsx
if (Array.isArray(parsed) && parsed.length === fallback.length) return parsed
```

---

### CR-04: `focusedBarTs` selector never causes row re-highlight in `TradeHistoryPane`

**File:** `apps/web/components/TradeHistoryPane.tsx:107`

**Issue:** `TradeHistoryPane` reads `focusedBarTs` from the Zustand store at line 107:
```tsx
const focusedBarTs = useWsStore((s) => s.focusedBarTs)
```
This is used at line 363 to compute `isFocused = focusedBarTs === trade.entry_ts_utc`, which
drives the `backgroundColor` and `border` styling of focused rows. However, `Chart.tsx` Effect 3
at line 249 calls `setFocusedBarTs(null)` **after** scrolling, immediately resetting the value.
This means `focusedBarTs` in `TradeHistoryPane` will be non-null for exactly one render cycle
(the one that triggered the effect), then immediately cleared before the user can see any
highlight. The effect is that the focused-row blue highlight border (line 386) never visually
persists — the highlight fires and is cleared in the same event loop turn via Zustand's
synchronous `set()`.

This is a behavioral bug: the feature (D-12 click-to-scroll with highlight) is broken by design
because the same atom is used for two purposes — "trigger scroll" and "show highlight" — and the
scroll consumer immediately resets the trigger, destroying the highlight.

**Fix:** Split into two atoms: one for the scroll trigger (reset after scroll) and one for the
persistent highlight selection (only reset when the user clicks a different row):

In `store/ws.ts`:
```ts
selectedTradeTs: string | null   // persistent highlight, reset on new click
focusedBarTs: string | null      // scroll trigger, reset after Chart scrolls
```

In `TradeHistoryPane`, use `selectedTradeTs` for highlight, set both on row click:
```tsx
onClick={() => {
  setSelectedTradeTs(trade.entry_ts_utc)
  setFocusedBarTs(trade.entry_ts_utc)
}}
```

In `Chart.tsx` Effect 3, only reset `focusedBarTs` (not `selectedTradeTs`).

---

## Warnings

### WR-01: `handleKillConfirm` silently swallows kill failures — no user feedback

**File:** `apps/web/components/BlotterPane.tsx:150-162`

**Issue:** `handleFlattenConfirm` correctly surfaces errors to the user via `setFlattenError`
(WR-02 fix noted in comments), but `handleKillConfirm` has an empty `catch` block at line 159:
```tsx
} catch {
  // Fire-and-forget; backend writes audit log
}
```
And even on a non-OK response (line 154-157), there is no error displayed — the function just
silently exits. The kill switch is the most critical operator action. If it fails (e.g., API
is down), the operator has no feedback and may believe positions are protected when they are not.

**Fix:** Parallel the flatten error pattern:
```tsx
const [killError, setKillError] = useState<string | null>(null)

async function handleKillConfirm() {
  setKillOpen(false)
  try {
    const res = await fetch(`${API_BASE}/kill`, { method: 'POST' })
    if (res.ok) {
      const data = await res.json() as { state: 'running' | 'paused' | 'killed' }
      setEngineState(data.state)
    } else {
      setKillError(`Kill failed: ${res.status}`)
    }
  } catch (e) {
    setKillError(`Kill network error: ${String(e).slice(0, 120)}`)
  }
}
```

---

### WR-02: WS reconnect resets `attempt` counter on `onopen` before `attempt++` in `onclose`

**File:** `apps/web/hooks/useStream.ts:47-58`

**Issue:** The reconnect backoff logic has a subtle ordering issue:

```ts
ws.onopen = () => {
  setConnected(true)
  attempt = 0  // reset here
}

ws.onclose = () => {
  setConnected(false)
  if (!stopped) {
    const delay = Math.min(Math.pow(2, attempt) * 1000, MAX_BACKOFF_MS) + Math.random() * 1000
    attempt++
    timerId = setTimeout(connect, delay)
  }
}
```

If the connection opens and immediately closes (e.g., server accepts then drops the WS), `onopen`
fires first setting `attempt = 0`, then `onclose` fires computing `delay = 2^0 * 1000 = 1000ms`.
This is correct. However, if the connection never opens (server refuses), only `onclose` fires
with the current `attempt` value. The problem is that `attempt` is incremented **after** the
delay is computed. For a sequence of rapid open+close cycles, `attempt` resets to 0 each time
`onopen` fires, meaning the backoff never actually backs off when the connection repeatedly
connects and immediately disconnects (e.g., server closes unhealthy connections). This could
cause rapid reconnect storms against a struggling server.

**Fix:** Only reset `attempt` after the connection has been stable for at least one message:
```ts
ws.onopen = () => {
  setConnected(true)
  // Don't reset here — reset only after a stable connection
}
ws.onmessage = (event) => {
  attempt = 0  // reset backoff only after first successful message
  // ... rest of handler
}
```

---

### WR-03: `_run_backtest_task` task is fire-and-forget with no reference kept — potential silent failure

**File:** `packages/api/src/api/routes/strategies.py:298-303`

**Issue:** `asyncio.create_task()` is called without retaining a reference to the returned
`Task` object:

```python
asyncio.create_task(
    _run_backtest_task(run_id, request.app.state),
    name=f"backtest_{run_id}",
)
```

In Python, if an `asyncio.Task` object is garbage collected while running, the task is silently
cancelled. The Python docs explicitly state: "It is recommended to save a reference to the task
returned by `create_task()`." If the Task finishes with an unhandled exception (not
`asyncio.CancelledError`), asyncio logs a "Task exception was never retrieved" warning but the
exception is otherwise lost. The `_run_backtest_task` only wraps its DB update in a
`try/except`, not its `asyncio.sleep` — so a `CancelledError` during the sleep would also
leave the row in `status='pending'` forever.

**Fix:** Store the task reference on `app.state` and add an exception-logging callback:

```python
task = asyncio.create_task(
    _run_backtest_task(run_id, request.app.state),
    name=f"backtest_{run_id}",
)
task.add_done_callback(lambda t: t.exception() and _log.error("backtest.task_error", exc=t.exception()))
# Prevent GC: store on app.state (cleanup on app shutdown)
if not hasattr(request.app.state, '_backtest_tasks'):
    request.app.state._backtest_tasks = set()
request.app.state._backtest_tasks.add(task)
task.add_done_callback(request.app.state._backtest_tasks.discard)
```

---

### WR-04: `get_strategy_enabled` conflates strategy-enabled state with engine kill-state

**File:** `packages/trading-core/src/trading_core/storage/duckdb_store.py:757-778`

**Issue:** `get_strategy_enabled` queries the `engine_state` table using `session_id = strategy_id`
as a convention to store per-strategy enabled/disabled state. The `engine_state` table was
designed for engine-level state (`'running'`, `'killed'`, `'paused'`). This creates a semantic
collision: if the engine kill switch is ever triggered with `session_id` accidentally matching
a `strategy_id`, it would disable that strategy. More critically, the check `str(row[0]) != 'killed'`
returns `True` (enabled) for any value including `'running'`, `'paused'`, and any other string.
If a future caller writes `'paused'` for a strategy (e.g., via a separate pause feature), the
strategy would be incorrectly reported as enabled.

**Fix:** Add a dedicated `strategy_enabled` table or a dedicated column. Minimally, restrict the
check to only the two expected values:

```python
state = str(row[0])
return state in ('running', 'enabled', '')  # only these mean "enabled"
```

Or better: add a `strategy_state` table with a `boolean enabled` column.

---

### WR-05: `ORBConfigUpdate` validator only covers 3 of the 6 displayed fields — silent partial validation

**File:** `packages/api/src/api/routes/strategies.py:61-92`

**Issue:** `ORBConfigUpdate` defines validators for `opening_range_minutes`, `atr_stop_mult`,
and `r_target`. But `StrategyControlsPane.tsx` displays 6 editable fields including `atr_period`,
`ema_period`, and `min_range_ticks` (line 52-58 of `StrategyControlsPane.tsx`). These three
fields pass through the `PUT /strategies/{id}/params` endpoint without any server-side validation
— a user could send `atr_period: -999` or `ema_period: 0` and the server would silently write
that to the YAML.

**Fix:** Add validators for the remaining fields:

```python
atr_period: int | None = None
ema_period: int | None = None
min_range_ticks: int | None = None

@field_validator('atr_period', 'ema_period', 'min_range_ticks')
@classmethod
def period_positive(cls, v: int | None) -> int | None:
    if v is not None and v <= 0:
        raise ValueError('period fields must be positive (> 0)')
    return v
```

---

### WR-06: `test_ws_seq.py` uses deprecated `asyncio.get_event_loop().run_until_complete()` — test reliability

**File:** `packages/api/tests/test_ws_seq.py:68, 84, 116, 141`

**Issue:** The tests call `asyncio.get_event_loop().run_until_complete(...)` inside a
synchronous test body. In Python 3.10+, `asyncio.get_event_loop()` emits a `DeprecationWarning`
when there is no running event loop, and in Python 3.12 it raises `RuntimeError` in certain
contexts. The `TestClient` from FastAPI's Starlette runs its own event loop internally. Calling
`run_until_complete` from outside may reuse or conflict with that loop depending on the OS and
pytest-asyncio mode, making tests fragile across Python minor versions.

**Fix:** Use `asyncio.get_event_loop().run_until_complete()` only in test environments where
the event loop is guaranteed, or switch to `pytest-asyncio` with `asyncio_mode = "auto"` and
mark the tests as `async`:

```python
@pytest.mark.asyncio
async def test_first_message_has_seq_one(self, tmp_path: Path) -> None:
    ...
    await app.state.bus.publish(TOPIC_DEGRADED_STATE, event)
```

---

### WR-07: `useEquityTrades` called twice for same `latestRunId` — comment claims dedup but dependency is wrong

**File:** `apps/web/app/dashboard/page.tsx:163-168`

**Issue:** The comment at line 164 says TanStack Query deduplicates the two calls to
`useEquityTrades(latestRunId)` because they share the same `queryKey ['trades', latestRunId]`.
This is correct when both hooks are called with the same `runId`. However, `TradeHistoryPane`
at line 111 computes `effectiveRunId = runId ?? (backtests?.[0]?.run_id ?? null)`. If `runId`
(passed as `latestRunId` from the parent) and `backtests?.[0]?.run_id` differ (they should not,
but race conditions between the parent's `useBacktests()` and the child's `useBacktests()` can
produce different cache snapshots during a brief window), the two hooks may use different keys
and fire two separate requests. Additionally, `TradeHistoryPane` calls `useBacktests()` again
internally (line 110), creating a third query for the same data. This is wasteful and creates
a subtle timing gap: the parent may have `latestRunId = 'run-abc'` while the child's internal
`useBacktests()` is still loading, causing `effectiveRunId` to be `null` until the child's
query resolves.

**Fix:** Remove the `useBacktests()` call from inside `TradeHistoryPane` — the parent always
passes `runId` explicitly. Use `runId` directly without the `??` fallback:

```tsx
// In TradeHistoryPane:
const effectiveRunId = runId  // trust the prop; parent owns the backtest query
```

---

## Info

### IN-01: Magic number `POINT_VALUE = 50` hardcoded in client code contradicts FND-06

**File:** `apps/web/components/TradeHistoryPane.tsx:63`

**Issue:** The comment at line 59 notes the contradiction: "D-13: hardcode 50 for ES; client
doesn't call instruments.py". The `BlotterPane.tsx` correctly uses `pos.point_value` from the
API (line 289), but `TradeHistoryPane.tsx` hardcodes `POINT_VALUE = 50` for slippage calculation.
If the system ever trades MES (point value = 5) or SPY (point value depends on contract size),
slippage will be reported incorrectly. The server already returns `TradeRow` with `slippage_ticks`
and `size`; it could also return `slippage_dollars` directly to avoid the client-side calculation.

**Fix:** Either add `slippage_dollars` to the `TradeRow` API response, or include `point_value`
in the `TradeRow` shape and use it in the computation.

---

### IN-02: `ConfirmationDialog` uses both `autoFocus` attribute and `setTimeout` focus — redundant

**File:** `apps/web/components/ConfirmationDialog.tsx:135, 55`

**Issue:** The `<input>` element has `autoFocus` at line 135, and the `useEffect` at line 55
also calls `setTimeout(() => inputRef.current?.focus(), 0)`. These are redundant — both attempt
to focus the input when the dialog opens. The `setTimeout` approach exists to handle cases where
the DOM isn't ready yet, but `autoFocus` combined with the dialog's `if (!open) return null`
pattern means the element is freshly mounted each time the dialog opens, making `autoFocus`
sufficient on its own. The dual approach can cause focus to be set twice and may interfere with
accessibility tools.

**Fix:** Remove the `setTimeout` focus call and rely on `autoFocus`.

---

### IN-03: `test_get_strategies_returns_list` asserts `len(data) >= 1` — depends on repo state

**File:** `packages/api/tests/test_strategies.py:87`

**Issue:** The test asserts `len(data) >= 1`, which means it implicitly depends on there being
at least one `*.yaml` file in `config/strategies/`. If tests are run in an environment where
that directory is empty or missing, the test fails for an environmental reason rather than a
code defect. This makes the test fragile in CI without the strategy YAML files present.

**Fix:** Either create a temporary strategy YAML in the test using `tmp_path`, or assert that
the response is a list (without requiring non-empty) and separately test the content of a known
seeded strategy.

---

### IN-04: Unused `import` of `Decimal` in `test_ws_seq.py`

**File:** `packages/api/tests/test_ws_seq.py:16`

**Issue:** `from decimal import Decimal` is imported at line 16 but never used anywhere in the
test file. This is dead import noise.

**Fix:** Remove the unused import:
```python
# Remove this line:
from decimal import Decimal
```

---

_Reviewed: 2026-05-20T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
