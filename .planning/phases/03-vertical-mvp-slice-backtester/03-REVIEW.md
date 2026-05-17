---
phase: "03"
status: findings
files_reviewed: 27
files_reviewed_list:
  - packages/trading-core/src/trading_core/execution/models.py
  - packages/trading-core/src/trading_core/risk/models.py
  - packages/trading-core/src/trading_core/storage/duckdb_store.py
  - packages/trading-core/src/trading_core/backtest/safe_signals.py
  - packages/trading-core/src/trading_core/risk/pass_through.py
  - packages/trading-core/src/trading_core/execution/paper.py
  - packages/trading-core/src/trading_core/backtest/engine.py
  - scripts/run_backtest.py
  - scripts/hooks/no_direct_vbt.py
  - packages/api/src/api/deps.py
  - packages/api/src/api/routes/bars.py
  - packages/api/src/api/routes/backtests.py
  - packages/api/src/api/ws.py
  - packages/api/src/api/app.py
  - apps/web/lib/api.ts
  - apps/web/store/ws.ts
  - apps/web/hooks/useBars.ts
  - apps/web/hooks/useBacktests.ts
  - apps/web/hooks/useStream.ts
  - apps/web/components/QueryProvider.tsx
  - apps/web/components/Chart.tsx
  - apps/web/components/EquityCurve.tsx
  - apps/web/components/ETClock.tsx
  - apps/web/components/ConnectionStatus.tsx
  - apps/web/components/DegradationBanner.tsx
  - apps/web/app/dashboard/page.tsx
  - apps/web/app/layout.tsx
findings:
  critical: 3
  warning: 4
  info: 3
  total: 10
---

# Phase 03: Code Review Report

**Reviewed:** 2026-05-17T00:00:00Z
**Depth:** standard
**Files Reviewed:** 27
**Status:** issues_found

## Summary

Reviewed the full Phase 3 vertical slice: Python backtesting engine + FastAPI REST/WS layer + Next.js dashboard. The domain models, risk pass-through, safe_signals wrapper, pre-commit hook, WebSocket fan-out, and frontend components are all well-structured. Three bugs that affect result correctness were found — two in the BacktestEngine driver loop and one in the equity endpoint SQL — along with four warnings covering error handling, path-count fragility, and type-safety gaps.

---

## Critical Issues

### CR-001 — Exit check fires on signal bar before entry fills

**File:** `packages/trading-core/src/trading_core/backtest/engine.py:230-244`
**Severity:** Critical
**Issue:** The driver loop sets `open_position` in Step 4 (bar index `i`, the signal bar), then immediately falls through to Step 5 where `check_exit` is called with `bar=bars[i]`. The entry fill was placed on `bars[i+1]` (next-bar open). On the signal bar `i` the position does not yet exist; checking whether the stop or target of that bar was hit is conceptually wrong and can produce an immediate same-bar exit. For ORB entries this means the signal bar's high/low can trigger the stop or target even though the trader has not yet entered the position. The trade would be recorded with `entry_ts_utc == exit_ts_utc` and a PnL calculated against a fill that never happened on that bar.

**Fix:** Gate the exit check so it only runs when the current bar index is strictly greater than `entry_idx`. Add a single guard at the top of Step 5:

```python
# Step 5: check exit on open position
if open_position is not None:
    sig = open_position["signal"]
    ef = open_position["entry_fill"]
    entry_idx = open_position["entry_idx"]
    fill_qty = open_position["fill_qty"]

    # Do not check exit on the bar where the entry fires; the fill
    # executes at the OPEN of bars[entry_idx], so exit checks must
    # begin at entry_idx, not at the signal bar (entry_idx - 1).
    if i < entry_idx:          # <-- add this guard
        continue                # signal bar: skip exit check entirely

    is_last_rth_bar = (i == n - 1)
    exit_result = executor.check_exit(...)
```

---

### CR-002 — Equity curve uses `init_cash` instead of `prev_equity` for unrealized PnL

**File:** `packages/trading-core/src/trading_core/backtest/engine.py:311`
**Severity:** Critical
**Issue:** During an open position the bar-level equity is computed as:

```python
equity_per_bar[i] = init_cash + unrealized
```

This resets to starting capital on every bar that the position is held, discarding any realized PnL from prior closed trades. A second trade open after a profitable first trade will show equity _below_ the true equity during the holding period, producing an incorrect drawdown series and an incorrect equity curve Parquet that is written to disk and served via `GET /backtests/{run_id}/equity`. Because the equity Parquet is read back by the frontend, the chart will display wrong numbers.

**Fix:** Replace `init_cash` with the running realized equity. Track a `realized_equity` variable that updates when a trade closes:

```python
realized_equity: float = init_cash   # tracks cash after each closed trade

# ... inside the exit branch:
realized_equity += pnl
equity_per_bar[i] = realized_equity

# ... inside the no-exit (unrealized) branch:
equity_per_bar[i] = realized_equity + unrealized
```

---

### CR-003 — SQL injection via unescaped apostrophe in Parquet path

**File:** `packages/api/src/api/routes/backtests.py:161-164`
**Severity:** Critical
**Issue:** The equity endpoint builds a DuckDB SQL statement by string-interpolating the resolved absolute path:

```python
parquet_path_str = str(abs_path).replace("\\", "/")
equity_rows = store._conn.execute(
    f"FROM read_parquet('{parquet_path_str}') ORDER BY ts_utc ASC"
)
```

Apostrophes in the path string are not escaped. DuckDB path names on Windows can legitimately contain apostrophes (e.g. `C:/Users/O'Brien/...`), and the `equity_curve_path` value is taken from a database row originally written by the CLI. A path containing a single quote breaks out of the string literal and allows arbitrary SQL injection into the DuckDB engine, even though the path-traversal guard has already validated the location. The correct mitigation is to use DuckDB's `$1` parameter binding for `read_parquet`.

**Fix:** DuckDB supports parameterized file paths in `read_parquet` via the `$1` form:

```python
equity_rows = store._conn.execute(
    "SELECT ts_utc, \"equity_$\" AS equity, \"drawdown_$\" AS drawdown "
    "FROM read_parquet($1) ORDER BY ts_utc ASC",
    [parquet_path_str],
).fetchall()
```

If DuckDB's version does not support `$1` for `read_parquet`, escape at minimum:

```python
parquet_path_str = str(abs_path).replace("\\", "/").replace("'", "''")
```

---

## Warnings

### WR-001 — `_EQUITY_ROOT` parent-count brittle against directory restructure

**File:** `packages/api/src/api/routes/backtests.py:28-33`
**Severity:** Warning
**Issue:** The path-traversal guard root is computed by counting exactly 5 `.parents` steps from the current file's resolved location:

```python
_EQUITY_ROOT = (Path(__file__).resolve().parents[5] / "data" / "parquet" / "equity").resolve()
```

The comment says "Five parents up from `packages/api/src/api/routes/backtests.py` reaches the repo root." If the module is ever moved (or an intermediate directory is added/removed), `parents[5]` silently resolves to a different directory and the guard either blocks all valid paths or stops guarding at all. The `assert` only checks the final component `"equity"`, which would still pass even if `_EQUITY_ROOT` pointed to the wrong parent tree as long as the leaf name is `equity`.

**Fix:** Anchor to a known repo landmark instead of counting parents. A reliable pattern is to walk upward until a sentinel file is found:

```python
def _find_repo_root(start: Path) -> Path:
    for parent in [start, *start.parents]:
        if (parent / "pyproject.toml").exists():
            return parent
    raise RuntimeError("Could not locate repo root from", start)

_EQUITY_ROOT = (_find_repo_root(Path(__file__)) / "data" / "parquet" / "equity").resolve()
```

---

### WR-002 — WebSocket client silently consumes all exceptions, masking real errors

**File:** `apps/web/hooks/useStream.ts:59-61`
**Severity:** Warning
**Issue:** The `onmessage` handler wraps all message processing in a try/catch that discards every exception silently:

```ts
} catch {
  // Malformed JSON — ignore silently
}
```

Only malformed JSON should be swallowed. TypeErrors, ReferenceErrors, and Zustand store errors from the `switch` branches will be silently swallowed. A bug in any topic handler (e.g., `setDegraded` receiving an unexpected payload shape) will produce no visible error in the browser console or in Zustand state, making the system appear healthy while misbehaving.

**Fix:** Narrow the catch to JSON parse errors only:

```ts
ws.onmessage = (event: MessageEvent) => {
  let msg: { type: string; payload: Record<string, unknown> }
  try {
    msg = JSON.parse(event.data as string)
  } catch {
    return  // Malformed JSON — skip
  }
  // Message routing outside the try block so errors surface normally
  switch (msg.type) {
    case 'bars':
      setLastBarAt(Date.now())
      break
    case 'degraded_state':
      setDegraded({ ... })
      break
    default:
      break
  }
}
```

---

### WR-003 — `useBars` URL parameters are not encoded

**File:** `apps/web/hooks/useBars.ts:20-22`
**Severity:** Warning
**Issue:** Query string parameters are concatenated directly into the URL without `encodeURIComponent`:

```ts
const res = await fetch(
  `${API_BASE}/bars?symbol=${symbol}&tf=${tf}&limit=${limit}`
)
```

While the current call sites only pass Pydantic-whitelisted string literals, the hook signature accepts arbitrary `string` inputs. If a caller ever passes a value containing `&`, `=`, or `+` (e.g., a future symbol like `ES+1`), the request will silently send a malformed or misrouted query string. The same issue exists in `useEquityCurve` and `useEquityTrades` for `runId`.

**Fix:** Use `URLSearchParams` or `encodeURIComponent`:

```ts
const params = new URLSearchParams({ symbol, tf, limit: String(limit) })
const res = await fetch(`${API_BASE}/bars?${params}`)
```

---

### WR-004 — `no_direct_vbt.py` hook returns via `sys.exit` inside `main()`, preventing unit testing

**File:** `scripts/hooks/no_direct_vbt.py:63-65`
**Severity:** Warning
**Issue:** `main()` calls `sys.exit(0)` and `sys.exit(1)` directly inside the function body rather than returning the exit code and leaving `sys.exit` to the `__main__` block:

```python
def main(argv: list[str]) -> int:
    ...
    if errors:
        print("\n".join(errors))
        sys.exit(1)    # terminates the process; not testable
    sys.exit(0)        # same
```

The return type annotation says `-> int` but the function never returns — it always calls `sys.exit`. Any unit test that calls `main(["file.py"])` directly will have the test process terminated instead of getting a return code to assert on. This makes the hook difficult to test in isolation and is inconsistent with sibling hooks in the codebase.

**Fix:** Return the exit code and call `sys.exit` only in `__main__`:

```python
def main(argv: list[str]) -> int:
    ...
    if errors:
        print("\n".join(errors))
        return 1
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv))
```

---

## Info

### IN-001 — `Fill.exit_reason` sentinel value conflates entry and exit fills

**File:** `packages/trading-core/src/trading_core/execution/paper.py:135`
**Severity:** Info
**Issue:** Entry fills are created with `exit_reason="target"` as a sentinel because `Fill.exit_reason` is a required `Literal` with no `None` option. The comment acknowledges this as known debt. The issue is that the shared `Fill` model makes it impossible to distinguish an entry fill from a target-exit fill by field value alone; callers must use out-of-band knowledge (which list the fill came from). A future refactor that merges or sorts the fill lists could silently corrupt attribution.

**Fix:** Phase 5 should split `Fill` into `EntryFill` and `ExitFill` models as noted in `03-02-SUMMARY.md`. As a nearer-term guard, add an explicit `fill_type: Literal["entry", "exit"]` field so code can distinguish fill role without relying on list position.

---

### IN-002 — `_max_dd_duration_bars` imports `pandas` inside a function

**File:** `packages/trading-core/src/trading_core/backtest/engine.py:101`
**Severity:** Info
**Issue:** `pandas` is imported at module level elsewhere in this file (`import pandas as pd` at line 31), but `_max_dd_duration_bars` re-imports it locally:

```python
def _max_dd_duration_bars(pf, has_trades: bool) -> int:
    ...
    import pandas as pd
    if pd.isna(dur) or dur is pd.NaT:
```

The local import is a no-op performance-wise (cached in `sys.modules`) but signals careless editing. It also means two different `pd` bindings exist in the same file, and `pd.NaT` from the local import is not the same object as the `pd.NaT` from the module-level import even though they are equal — `is` comparisons between them are technically undefined behavior.

**Fix:** Remove the local import and use the module-level `pd`:

```python
# Remove: import pandas as pd  (inside _max_dd_duration_bars)
# The module-level `import pandas as pd` at line 31 is already present.
```

---

### IN-003 — `computeORB` in dashboard rebuilds `Intl.DateTimeFormat` on every render

**File:** `apps/web/app/dashboard/page.tsx:52-57`
**Severity:** Info
**Issue:** `computeORB` is a plain function called inside `useMemo`. Every time `bars` changes, the function creates a new `Intl.DateTimeFormat` instance inside the loop over all bars. `Intl.DateTimeFormat` construction is expensive relative to `format()` calls, and creating it per-call wastes that cost when there are 390 bars. The `etFormatter` pattern used in `ETClock.tsx` (module-level singleton) is the correct pattern but is not followed here.

**Fix:** Hoist the formatter to module scope in `page.tsx` (or extract it to a shared constant):

```ts
const _orbEtFormatter = new Intl.DateTimeFormat('en-US', {
  timeZone: 'America/New_York',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
})

function computeORB(bars: BarRow[]) {
  // ... use _orbEtFormatter.format(ts) directly
}
```

---

_Reviewed: 2026-05-17T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
