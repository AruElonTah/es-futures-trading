---
phase: 04-optimization-grid-walk-forward
reviewed: 2026-05-17T00:00:00Z
depth: standard
files_reviewed: 11
files_reviewed_list:
  - packages/trading-core/src/trading_core/optimization/space.py
  - packages/trading-core/src/trading_core/optimization/splitter.py
  - packages/trading-core/src/trading_core/storage/duckdb_store.py
  - packages/trading-core/src/trading_core/storage/schema.sql
  - packages/api/src/api/routes/optimizations.py
  - packages/api/src/api/app.py
  - apps/web/app/optimizations/page.tsx
  - apps/web/app/dashboard/page.tsx
  - packages/trading-core/tests/optimization/test_space.py
  - packages/trading-core/tests/optimization/test_splitter.py
  - packages/trading-core/tests/optimization/test_holdout.py
  - packages/api/tests/test_optimizations.py
findings:
  critical: 5
  warning: 6
  info: 3
  total: 14
status: issues_found
---

# Phase 04: Code Review Report

**Reviewed:** 2026-05-17T00:00:00Z
**Depth:** standard
**Files Reviewed:** 11 (of 16 listed; 5 files absent from disk — see CR-01)
**Status:** issues_found

## Summary

Phase 4 adds the optimization grid + walk-forward infrastructure: `OptSpace` (parameter space model), `get_fold_boundaries` (rolling splitter), `DuckDBStore` extensions for opt tables, three GET routes under `/optimizations`, and the React optimization leaderboard/heatmap page.

The most serious finding is that five files listed in the review scope do not exist on disk — `worker.py`, `run_opt.py`, `test_worker.py`, `test_run_opt.py` — meaning the core execution engine and integration test layer have not been implemented. The remaining code is generally well-structured, but several correctness and security issues are present in the code that does exist.

---

## Critical Issues

### CR-01: Core Worker and CLI Script Are Not Implemented

**Files:** `packages/trading-core/src/trading_core/optimization/worker.py`, `scripts/run_opt.py`, `packages/trading-core/tests/optimization/test_worker.py`, `packages/trading-core/tests/integration/test_run_opt.py`

**Issue:** All four files are listed in the phase scope and referenced throughout planning documents but do not exist on disk. `worker.py` is the `ProcessPoolExecutor` worker that runs individual (fold, param_combo) backtests. `run_opt.py` is the CLI entry point that drives the full optimization loop. Without these, the optimization grid system cannot run at all — `OptSpace`, `splitter.py`, and the `DuckDBStore` opt tables exist but have nothing connecting them to actual backtest execution. The `/optimizations` API endpoints return data from tables that can never be populated by the missing components.

**Fix:** Implement the missing files. At minimum `worker.py` must define a picklable top-level function accepted by `ProcessPoolExecutor` (on Windows, `spawn` context requires no closures or lambdas), and `run_opt.py` must wire `OptSpace.combos()` → fold boundaries → worker dispatch → `DuckDBStore.write_opt_results()`.

---

### CR-02: `RollingSplitter` Instantiation Is Incorrect for VBT 1.0.0 OSS

**File:** `packages/trading-core/src/trading_core/optimization/splitter.py:93-101`

**Issue:** `vbt.RollingSplitter()` is instantiated with no arguments, then `.split()` is called on it. In VBT 1.0.0 OSS the splitter API is class-level and the correct call form is `vbt.RollingSplitter.split(X, n=n_folds, window_len=..., set_lens=(...,))` (a classmethod/staticmethod pattern), not `instance.split(...)`. The research file (04-RESEARCH.md) documented this exact pitfall. If `vbt.RollingSplitter()` actually accepts no-arg construction, calling `.split()` on the returned object may silently return an empty iterator rather than raising, resulting in `result = []` with no folds and no error — breaking every downstream consumer that depends on fold data.

Additionally, the return value of `splitter.split(...)` is wrapped in `list(...)` and iterated as `(is_idx, oos_idx)` pairs. The actual VBT 1.0.0 split return type needs to be verified — if it returns index arrays rather than two-tuples, the destructure at line 104 will raise `ValueError: too many values to unpack` at runtime.

**Fix:** Verify the exact VBT 1.0.0 OSS API against the installed package and align the call site. Based on the research doc's Pitfall 1, the correct pattern is:
```python
folds_raw = vbt.RollingSplitter.split(
    X,
    n=n_folds,
    window_len=IS_DAYS + OOS_DAYS,
    set_lens=(IS_DAYS,),
)
```
Then confirm the iteration shape of the returned object before indexing `[is_idx[0]]` etc.

---

### CR-03: `AssertionError` Used for Data Invariant That Should Be `ValueError`

**File:** `packages/trading-core/src/trading_core/optimization/splitter.py:112-115`

**Issue:** The BL-4 invariant (`is_end < oos_start`) is enforced with `assert`. Python `assert` statements are stripped when the interpreter runs with `-O` (optimize flag). Many production runners and packaging tools use `-O` or `-OO`. If the splitter produces overlapping IS/OOS windows due to a VBT API bug or parameter edge case, the assertion is silently skipped and corrupt fold data propagates into backtest runs and the database — the exact "trust the numbers" failure mode this system is designed to prevent.

**Fix:**
```python
if is_end >= oos_start:
    raise ValueError(
        f"Fold {fold_idx}: is_end ({is_end}) >= oos_start ({oos_start}) — "
        "BL-4 violated (IS/OOS overlap detected)"
    )
```

---

### CR-04: Route Registration Order Creates an Unreachable Endpoint

**File:** `packages/api/src/api/routes/optimizations.py:154` vs `287`

**Issue:** FastAPI matches routes in registration order. The `GET /optimizations/{run_id}/results` route (line 154) and `GET /optimizations/{run_id}/heatmap` (line 194) are registered **before** `GET /optimizations/{run_id}` (line 287). This ordering is correct in the file, but the `{run_id}` path parameter in the single-run route will never match a literal path segment like `results` or `heatmap` because FastAPI evaluates more-specific paths before catch-all ones — **only if they are registered first**. Since `/results` and `/heatmap` routes come earlier in the file, they take priority. However, this only works because of the sub-path suffix. The real risk is if a `run_id` value of `"results"` or `"heatmap"` is passed: `GET /optimizations/results` would be routed to `get_opt_results` with `run_id="results"` interpreted as a run ID, silently returning an empty list instead of a 404. While unlikely with uuid7 IDs, this is an ambiguous API design. The more concrete bug is: `GET /optimizations/{run_id}` is declared **after** the sub-resource routes in the same file — if FastAPI's router processes them in reverse order or re-sorts, the single-run endpoint shadows the sub-resource endpoints. This ordering must be verified.

**Fix:** Register the most-specific routes before the catch-all `{run_id}` route, which the current file already does. Document this ordering constraint explicitly with a comment. Additionally, add a path constraint or prefix to disambiguate: e.g., validate that `run_id` matches a uuid7 pattern in the single-run endpoint.

---

### CR-05: `DuckDBStore.close()` Silently Swallows All Exceptions

**File:** `packages/trading-core/src/trading_core/storage/duckdb_store.py:526-529`

**Issue:** The `close()` method wraps `self._conn.close()` in a bare `except Exception: pass`. If DuckDB fails to flush pending writes on close (e.g., in-flight `executemany` was interrupted), the data loss is silently ignored and the caller has no signal that close failed. In the context manager `__exit__`, this means a failed optimization run that was mid-write could lose its final batch of `opt_results` rows with no log message, no exception, and no way to detect the corruption after the fact.

**Fix:**
```python
def close(self) -> None:
    try:
        self._conn.close()
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning(
            "DuckDBStore.close() failed — possible data loss: %s", exc
        )
        raise
```
At minimum, log the exception. Re-raising is preferable so callers are aware.

---

## Warnings

### WR-01: `n_folds` Derivation Formula Is Inconsistent with Rolling Window Semantics

**File:** `packages/trading-core/src/trading_core/optimization/splitter.py:84`

**Issue:** The formula `n_folds = max(1, total_days // OOS_DAYS - is_months)` is dimensionally inconsistent. `total_days // OOS_DAYS` is in units of OOS windows (e.g., 210 // 21 = 10 months). Subtracting `is_months` (e.g., 6, an integer) gives 4 — but "4 folds" for a 10-month range with a 6-month IS + 1-month OOS window is incorrect. The correct rolling fold count for a step=1 OOS window is `(total_days - IS_DAYS) // OOS_DAYS`, which for 210 days, IS_DAYS=126, OOS_DAYS=21 gives `(210-126)//21 = 4`. These happen to produce the same result in this example, but the formula is wrong and will diverge for different `is_months`/`oos_months` combinations. For example, with `is_months=3, oos_months=2` on a 10-month range: correct = `(210-63)//42 = 3` folds; formula gives `210//42 - 3 = 5-3 = 2` folds — one fewer than available.

**Fix:**
```python
n_folds = max(1, (total_days - IS_DAYS) // OOS_DAYS)
```

---

### WR-02: Heatmap Axis Normalization Loses Integer Consistency for `opening_range_minutes`

**File:** `packages/api/src/api/routes/optimizations.py:267-274`

**Issue:** The `x_vals` normalization logic (`int(v) if isinstance(v, float) and v == int(v) else float(v) if isinstance(v, float) else v`) correctly converts whole-number floats to int — but only for `x_vals`. The `y_vals` list (lines 271-273) applies `float(v)` unconditionally for float values. If `axis_y=opening_range_minutes`, those values (5, 10, 15...) come back from DuckDB as integers or whole-number floats and will be normalized to `float` (5.0, 10.0...) in `y_vals` but `int` (5, 10...) in `x_vals`. This inconsistency means the same parameter has different JSON types depending on which axis it appears on. The frontend `HeatmapData` interface types both as `number[]` so no crash occurs, but callers comparing axis values across requests will get inconsistent results.

**Fix:** Apply the same int-coercion logic to both `x_vals` and `y_vals`:
```python
def _coerce_axis_val(v):
    if isinstance(v, float) and v == int(v):
        return int(v)
    return v

x_vals = [_coerce_axis_val(v) for v in x_vals_raw]
y_vals = [_coerce_axis_val(v) for v in y_vals_raw]
```

---

### WR-03: Direct `store._conn` Access in Route Handlers Bypasses Encapsulation

**File:** `packages/api/src/api/routes/optimizations.py:148`, `243`, `300`

**Issue:** Three route handlers access `store._conn.execute(...)` directly, bypassing the `DuckDBStore` public API. The `_conn` attribute is a private implementation detail. This means: (1) any future change to the store's connection lifecycle (e.g., connection pooling, read replica) breaks these routes silently; (2) the `get_optimizations` and `get_optimization` routes do not benefit from the store's parameter handling or error normalization conventions. This is already causing drift — `read_opt_results` on the store returns `list[dict]` but the inline query in `get_optimizations` returns `list[tuple]` requiring a separate serializer.

**Fix:** Move the `_OPT_RUNS_SQL` and `_OPT_RUN_BY_ID_SQL` queries into `DuckDBStore` as methods (e.g., `list_opt_runs()` and `get_opt_run(run_id)`) following the same pattern as `read_opt_results`.

---

### WR-04: `OptSpace.validate_axes` Is Hardcoded to `ORBConfig` Only

**File:** `packages/trading-core/src/trading_core/optimization/space.py:62-76`

**Issue:** The `model_validator` imports `ORBConfig` directly and validates param names only against its fields. The `strategy` field on `OptSpace` is parsed from the YAML but never used to select which config class to validate against. Any non-ORB strategy YAML will always fail validation with "Unknown param" errors, making `OptSpace` non-reusable. More specifically, if the `strategy` field is `"orb"` the validation passes, but nothing checks that `self.strategy == "orb"` before using `ORBConfig` — a YAML with `strategy: mes` and ORB-compatible param names would silently validate against ORBConfig.

**Fix:** Either document explicitly that `OptSpace` is ORB-only for v1 (remove the `strategy` field or add a validator enforcing `strategy == "orb"`), or build a registry dispatch: `CONFIG_CLASSES = {"orb": ORBConfig}` and look up `CONFIG_CLASSES.get(self.strategy)` with a clear error when not found.

---

### WR-05: `write_parquet_partition` Calls `root.parent.mkdir()` Instead of `root.mkdir()`

**File:** `packages/trading-core/src/trading_core/storage/duckdb_store.py:371`

**Issue:** The Parquet write method calls `root.parent.mkdir(parents=True, exist_ok=True)` but `root` is the target directory itself (e.g., `data/parquet/bars`). Creating `root.parent` (`data/parquet`) without creating `root` means the `COPY ... TO '{target}'` DuckDB call may fail if `data/parquet/bars` does not exist yet, since DuckDB's Parquet writer requires the root partition directory to exist on some platforms.

**Fix:**
```python
root.mkdir(parents=True, exist_ok=True)
```

---

### WR-06: `test_quota_allows_three_burns` Has a Misleading Comment and Wrong Intermediate Assertion

**File:** `packages/trading-core/tests/optimization/test_holdout.py:40-54`

**Issue:** The test name is `test_quota_allows_three_burns` and the comment says "After each burn, check: should still be True (< 3 threshold) until 3rd" — but no intermediate assertions are actually made. The loop inserts 3 burns without calling `check_holdout_quota` after each insertion. The only assertion is at the end, checking that quota is False after all 3. This means the test does not actually verify that burns 1 and 2 are allowed (return True). Additionally, `test_quota_allows_three_burns` and `test_quota_refuses_fourth_burn` test the same final condition (3 burns → False), providing no incremental coverage for the 1-burn and 2-burn states. A real bug where the quota check always returns False would pass both tests.

**Fix:** Add intermediate assertions:
```python
for i in range(3):
    burn_id = new_run_id()
    assert tmp_store.check_holdout_quota(quarter) is True, f"burn {i+1} should be allowed"
    tmp_store.write_holdout_burn(burn_id=burn_id, run_id=run_id, quarter=quarter)
assert tmp_store.check_holdout_quota(quarter) is False
```

---

## Info

### IN-01: `HeatmapData.z` Typed as `number[][]` but API Returns `(float | None)[][]`

**File:** `apps/web/app/optimizations/page.tsx:58-62`

**Issue:** The TypeScript interface types `z` as `number[][]` but the API can return `null` values in the z grid for (x, y) cells that have no data (the `lookup.get(...)` returns `None`/`null`). The `Plot` component from `react-plotly.js` handles null gracefully, but any TypeScript code that calls `.toFixed()` or arithmetic on `z[i][j]` values without null-checking will produce a runtime error. The type should be `(number | null)[][]`.

**Fix:** Update the interface:
```typescript
interface HeatmapData {
  x: number[]
  y: number[]
  z: (number | null)[][]
}
```

---

### IN-02: `dashboard/page.tsx` `computeORB` Falls Back to Index 0 When No 09:30 Bar Found

**File:** `apps/web/app/dashboard/page.tsx:71-73`

**Issue:** When no bar with `formatted === '09:30'` is found (e.g., data covers only the afternoon, or a holiday), `sessionStartIdx` is set to `0` and the ORB is computed from the first available bar regardless of its actual time. This can produce an ORB high/low from bars outside the RTH open window, causing visually misleading overlays on the chart. The fallback is silently wrong rather than returning `undefined`.

**Fix:**
```typescript
if (sessionStartIdx === -1) {
  return { orbHigh: undefined, orbLow: undefined }
}
```

---

### IN-03: `Suspense` Wrapping a `dynamic()` Component with `ssr: false` Is Redundant

**File:** `apps/web/app/optimizations/page.tsx:486-517`

**Issue:** `dynamic(() => import('react-plotly.js'), { ssr: false })` already handles the loading state internally via Next.js dynamic import. Wrapping it in a `<Suspense fallback={...}>` is redundant — the `fallback` in `Suspense` will never render because dynamic with `ssr: false` does not use React Suspense boundaries; it renders nothing until loaded, then the component. The "Loading chart..." text will never appear.

**Fix:** Remove the `<Suspense>` wrapper. If a loading indicator is desired, pass a `loading` prop to `dynamic()`:
```typescript
const Plot = dynamic(() => import('react-plotly.js'), {
  ssr: false,
  loading: () => <div style={{ color: '#555', fontSize: '12px' }}>Loading chart...</div>,
})
```

---

_Reviewed: 2026-05-17T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
