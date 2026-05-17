---
phase: 04-optimization-grid-walk-forward
verified: 2026-05-17T23:30:00Z
status: human_needed
score: 14/14
overrides_applied: 0
human_verification:
  - test: "Start the API (uv run uvicorn api.app:app --host 127.0.0.1 --port 8000) and visit http://localhost:3000/optimizations in the browser"
    expected: "Page loads without a white-screen / SSR crash; shows the leaderboard table (empty if no runs yet), axis selectors, and a placeholder or empty heatmap area; no JavaScript console errors"
    why_human: "react-plotly.js dynamic import with ssr:false and the full leaderboard rendering path require a live browser to confirm there are no runtime crashes (CORS, hydration errors, or dynamic import failures only appear in a real browser session)"
  - test: "Verify the Dashboard header Optimizations link: open http://localhost:3000/dashboard and confirm an 'Optimizations' link is visible in the header and navigates to /optimizations"
    expected: "The link is rendered in the header area; clicking it navigates to /optimizations without a full-page reload error"
    why_human: "Header rendering and client-side navigation are not exercised by the Python API test suite and require a live Next.js dev/build session to confirm"
---

# Phase 4: Optimization Grid + Walk-Forward Verification Report

**Phase Goal:** A user can launch a grid + walk-forward optimization run from a committed ADR, watch progress live, and inspect an OOS-ranked leaderboard plus 2-param heatmaps — with the most-recent 6 months of bars guarded against accidental burn.
**Verified:** 2026-05-17T23:30:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Pre-run ADR gate: run_opt.py refuses to start without opt-*.md ADR | VERIFIED | `_check_adr_gate()` in `scripts/run_opt.py` line 176 globs `.planning/decisions/opt-*.md`, prints error and calls `sys.exit(1)` if none found; `test_adr_gate_no_adr` test exercises this path |
| 2 | Coarse grid (125 configs) runs in ProcessPoolExecutor, workers read DuckDB read-only, orchestrator aggregates in single-process pass | VERIFIED | `worker.py` line 140: `conn = duckdb.connect(db_path, read_only=True)`; `run_opt.py` line 359: `ProcessPoolExecutor(max_workers=max_workers)`; results aggregated at lines 397-402 in one DuckDB write pass |
| 3 | True-holdout guard: bars from last 6 months refused without --burn-holdout; 4th burn refused | VERIFIED | `_check_holdout_guard()` in `run_opt.py` lines 212-248 implements full logic; `check_holdout_quota()` in `duckdb_store.py` returns `count < 3`; `test_quota_refuses_fourth_burn` in `test_holdout.py` and `test_holdout_quota_exceeded` in `test_run_opt.py` verify behavior |
| 4 | UI optimization browser ranks by OOS Sharpe (never IS), shows edge_ratio > 2 in red, lets user pick 2 grid axes and render heatmap | VERIFIED | `optimizations.py` `_OPT_RUNS_SQL` orders by `created_at DESC`; `read_opt_results` orders by `oos_sharpe DESC NULLS LAST`; `page.tsx` lines 336-390: edge_ratio > 2.0 applied inline style `backgroundColor: '#7f1d1d'`; axis selectors at lines 440-475 drive heatmap query |
| 5 | Ranges narrower than 5 points per axis refused | VERIFIED | `OptSpace.validate_axes()` in `space.py` raises `ValueError("Axis '{name}' has {len} values — minimum 5 (OPT-06)")` at parse time; `test_axis_too_narrow` passes; model_validator also enforces in `run_opt.py` when `OptSpace.load()` is called |
| 6 | ADR hash written to every opt_runs row and recoverable forensically | VERIFIED | `_check_adr_gate()` returns `adr_hash(adr_path)` string; `store.write_opt_run(adr_hash=adr_hash_str, ...)` at `run_opt.py` line 337; `opt_runs.adr_hash VARCHAR NOT NULL` in schema.sql |
| 7 | OptSpace.load('config/strategies/orb.optspace.yaml') returns 125 combos across 3 axes | VERIFIED | `orb.optspace.yaml` has 3 axes each with 5 values (5×5×5=125); `test_combo_count` asserts `len(combos()) == 125` |
| 8 | Any axis with < 5 values raises ValueError at parse time | VERIFIED | `space.py` model_validator line 68-71; `test_axis_too_narrow` covers this path |
| 9 | Unknown param names raise ValueError at parse time | VERIFIED | `space.py` model_validator lines 72-75; `test_unknown_param_name` covers this path |
| 10 | get_fold_boundaries() returns IS/OOS date ranges where is_end < oos_start for every fold | VERIFIED | `splitter.py` line 112: `assert is_end < oos_start` enforced in function body before returning; `test_splitter.py` verifies this invariant |
| 11 | DuckDB schema has opt_runs, opt_results, holdout_burns tables (all IF NOT EXISTS) | VERIFIED | `schema.sql` lines 107-148 contain all three CREATE TABLE IF NOT EXISTS blocks; `test_schema_tables` confirms all three present after `ensure_schema()` |
| 12 | check_holdout_quota() returns False for the 4th burn in the same calendar quarter | VERIFIED | `duckdb_store.py` line 500: `return count < 3`; `test_quota_refuses_fourth_burn` inserts 3 burns then asserts `check_holdout_quota() is False` |
| 13 | GET /optimizations routes registered in FastAPI app | VERIFIED | `app.py` line 123: `app.include_router(optimizations_routes.router)`; `optimizations.py` defines 4 endpoints including GET /optimizations, /{id}, /{id}/results, /{id}/heatmap with ALLOWED_AXES whitelist |
| 14 | Next.js /optimizations page uses dynamic import with ssr:false; dashboard has Optimizations header link | VERIFIED (code) / UNCERTAIN (runtime) | `page.tsx` line 27: `const Plot = dynamic(() => import("react-plotly.js"), { ssr: false })`; `dashboard/page.tsx` line 142: `href="/optimizations"` with "Optimizations" text; `package.json` has react-plotly.js@^2.6.0 and plotly.js@^3.5.1; runtime behavior requires human verification |

**Score:** 14/14 truths verified in code. Runtime browser behavior (truth 14) requires human confirmation.

---

## Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `packages/trading-core/src/trading_core/optimization/space.py` | OptSpace Pydantic model with combos() and param_grid_hash() | VERIFIED | 122 lines; full implementation with model_validator, combos(), param_grid_hash(), load() classmethod |
| `packages/trading-core/src/trading_core/optimization/splitter.py` | get_fold_boundaries() wrapping vbt.RollingSplitter | VERIFIED | 128 lines; full implementation using vbt.RollingSplitter, CME_Equity calendar, ISO string output, BL-4 assertion |
| `config/strategies/orb.optspace.yaml` | 125-combo coarse ORB grid | VERIFIED | 3 axes (opening_range_minutes, atr_stop_mult, r_target) each with exactly 5 values = 125 combos |
| `packages/trading-core/src/trading_core/storage/schema.sql` | DDL for opt_runs, opt_results, holdout_burns | VERIFIED | All three tables present as CREATE TABLE IF NOT EXISTS at lines 107-148 |
| `.planning/decisions/opt-template.md` | ADR template with required fields | VERIFIED | Contains is_oos_split, optspace_path, objective, seed fields in the Required Fields table |
| `packages/trading-core/src/trading_core/optimization/worker.py` | Module-level run_combo() (Windows spawn-safe, read-only DuckDB) | VERIFIED | 334 lines; run_combo at module level (line 100); duckdb.connect(read_only=True) at line 140; D-07 comment at line 26 |
| `scripts/run_opt.py` | CLI with ADR gate, holdout guard, ProcessPoolExecutor dispatch | VERIFIED | 452 lines; full pipeline implementation; _check_adr_gate(), _check_holdout_guard(), ProcessPoolExecutor, aggregate → write |
| `packages/trading-core/tests/optimization/test_worker.py` | Worker tests | VERIFIED | File exists with test_worker_importable, test_worker_no_api_import, fold result shape tests |
| `packages/trading-core/tests/integration/test_run_opt.py` | Integration tests: ADR gate, fold persistence | VERIFIED | File exists with TestAdrGate class, test_adr_gate_no_adr, test_adr_gate_missing_fields |
| `packages/api/src/api/routes/optimizations.py` | 4 GET endpoints with ALLOWED_AXES whitelist | VERIFIED | 306 lines; 4 endpoints defined; ALLOWED_AXES = frozenset at line 36 |
| `apps/web/app/optimizations/page.tsx` | Next.js /optimizations page with leaderboard + heatmap | VERIFIED | 567 lines; "use client", dynamic import ssr:false, leaderboard table, edge_ratio red-flag, axis selectors, Plotly heatmap |
| `packages/api/tests/test_optimizations.py` | API route tests | VERIFIED | 279 lines; 10 tests covering empty list, unknown run, heatmap shape, invalid axis 422 |

---

## Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| optimization/space.py OptSpace.validate_axes | trading_core.strategy.orb.ORBConfig | dataclasses.fields(ORBConfig) inline import | WIRED | Line 62: `from trading_core.strategy.orb import ORBConfig`; line 64: `valid_names = {f.name for f in dataclasses.fields(ORBConfig)}` |
| duckdb_store.py check_holdout_quota | holdout_burns table | SELECT COUNT(*) WHERE quarter = ? | WIRED | Line 500: `count = self._conn.execute(CHECK_HOLDOUT_QUOTA_SQL, [quarter]).fetchone()[0]`; SQL at line 117 |
| optimization/splitter.py get_fold_boundaries | vbt.RollingSplitter | splitter.split(X, n=n_folds, window_len=IS+OOS, set_lens=(IS,)) | WIRED | Lines 93-101: `splitter = vbt.RollingSplitter(); folds_raw = list(splitter.split(X, n=n_folds, window_len=IS_DAYS+OOS_DAYS, set_lens=(IS_DAYS,)))` |
| scripts/run_opt.py ProcessPoolExecutor | trading_core.optimization.worker.run_combo | executor.submit(run_combo, combo_dict=..., fold_boundaries=..., db_path=str(...)) | WIRED | Line 64: import; lines 359-373: `ProcessPoolExecutor` submits `run_combo` with all kwargs |
| run_combo worker | duckdb read-only connection | duckdb.connect(db_path, read_only=True) | WIRED | Line 140: `conn = duckdb.connect(db_path, read_only=True)` |
| orchestrator | DuckDBStore.write_opt_run + write_opt_results | single-process pass after all futures collected | WIRED | Lines 337-352: `store.write_opt_run(...)` with status='running'; lines 402: `store.write_opt_results(all_rows)` after futures |
| packages/api/src/api/app.py | optimizations.router | app.include_router(optimizations_routes.router) | WIRED | Line 123: `app.include_router(optimizations_routes.router)` |
| apps/web/app/optimizations/page.tsx | GET /optimizations/{run_id}/heatmap | TanStack Query useQuery at refetchInterval=2000 while status=running | WIRED | Lines 136-141: `useQuery` fetches heatmap; `queryFn: () => fetchHeatmap(selectedRunId!, axisX, axisY)`; line 130 refetchInterval returns 2000 when running |
| heatmap endpoint | opt_results table axis columns | ALLOWED_AXES whitelist before DuckDB GROUP BY | WIRED | Lines 217-232: axis_x and axis_y validated against ALLOWED_AXES before SQL construction at line 237 |

---

## Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| `apps/web/app/optimizations/page.tsx` | `runs` (OptRun[]) | `useQuery` → `fetchRuns()` → `GET /optimizations` → DuckDB `opt_runs` table | Yes — SQL query against real DuckDB table; empty list is valid initial state | FLOWING |
| `apps/web/app/optimizations/page.tsx` | `results` (OptResult[]) | `useQuery` → `fetchResults()` → `GET /optimizations/{id}/results` → `read_opt_results()` → DuckDB `opt_results` | Yes — parameterized SELECT from real DuckDB table | FLOWING |
| `apps/web/app/optimizations/page.tsx` | `heatmapData` (HeatmapData) | `useQuery` → `fetchHeatmap()` → `GET /optimizations/{id}/heatmap` → GROUP BY query on opt_results | Yes — real GROUP BY aggregation; returns {x:[],y:[],z:[]} when empty | FLOWING |
| `packages/api/src/api/routes/optimizations.py` | `rows` (opt_runs) | `store._conn.execute(_OPT_RUNS_SQL).fetchall()` | Yes — direct DuckDB query; empty list when no runs | FLOWING |

---

## Behavioral Spot-Checks

Step 7b: SKIPPED for live server checks (would require starting uvicorn + Next.js dev server). Python test suite is runnable without a running server.

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| OptSpace 125 combos from YAML | `OptSpace.load("config/strategies/orb.optspace.yaml").combos()` length check — covered by test_combo_count | test_combo_count asserts len==125 | PASS (test covers it) |
| run_opt.py ADR gate exits 1 without ADR | test_adr_gate_no_adr subprocess test | test asserts returncode==1 | PASS (test covers it) |
| Heatmap 422 on invalid axis | test_heatmap_invalid_axis_x checks 422 response | TestClient asserts status_code==422 | PASS (test covers it) |
| Worker read-only DuckDB | test_worker_no_api_import verifies no api/tv_bridge imports; line 140 verified | duckdb.connect(db_path, read_only=True) at line 140 | PASS (code verified) |

---

## Probe Execution

Step 7c: No probe scripts found under `scripts/*/tests/probe-*.sh`. Phase 4 does not declare probe-based verification.

---

## Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| OPT-01 | 04-01 | Grid expansion from optspace.yaml | SATISFIED | OptSpace.load() + combos() + orb.optspace.yaml with 125 combos |
| OPT-02 | 04-02 | ProcessPoolExecutor workers, read-only DuckDB, per-worker Parquet shards, single-process aggregation | SATISFIED | worker.py read_only=True; run_opt.py ProcessPoolExecutor; write_equity_parquet per fold; aggregation at lines 397-402 |
| OPT-03 | 04-01, 04-02 | Walk-forward IS/OOS splitter with configurable windows | SATISFIED | get_fold_boundaries() using vbt.RollingSplitter; --is-months, --oos-months args in run_opt.py |
| OPT-04 | 04-02 | Pre-run ADR gate: opt-*.md required, hash logged on opt_runs | SATISFIED | _check_adr_gate() gates all runs; adr_hash field NOT NULL in schema; write_opt_run passes adr_hash |
| OPT-05 | 04-02 | Per-fold persistence: equity curves, metrics, hashes to opt_results | SATISFIED | worker.py writes IS/OOS Parquet per fold; result dict includes equity_curve_path, git_sha, data_hash, seed; write_opt_results stores all |
| OPT-06 | 04-01, 04-02 | Coarse-grid-first: <5 values per axis refused | SATISFIED | model_validator raises ValueError at parse time; enforced before any worker spawns |
| OPT-07 | 04-03 | OOS Sharpe as default ranking metric; edge_ratio > 2 red flag | SATISFIED | read_opt_results orders by oos_sharpe DESC NULLS LAST; page.tsx renders edgeFlagged cells with red background when edge_ratio > 2.0 |
| OPT-08 | 04-01, 04-02 | True-holdout guard: 6-month barrier, 3-burn quarterly quota | SATISFIED | _check_holdout_guard() in run_opt.py; check_holdout_quota() in duckdb_store.py; holdout_burns table in schema.sql |
| OPT-09 | 04-03 | 2-parameter heatmap in UI | SATISFIED | GET /optimizations/{id}/heatmap returns {x,y,z}; page.tsx renders Plotly heatmap with axis selectors |

All 9 OPT requirements claimed by Phase 4 plans are SATISFIED by the codebase.

---

## Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| No TBD/FIXME/XXX markers found | — | — | — | — |
| No stub return null / return {} / return [] patterns found in Phase 4 files | — | — | — | — |

No anti-patterns detected in Phase 4 modified files. No unreferenced debt markers.

---

## Human Verification Required

### 1. Next.js /optimizations Page Runtime Behavior

**Test:** Start both the FastAPI backend (`uv run uvicorn api.app:app --host 127.0.0.1 --port 8000`) and the Next.js dev server (`pnpm dev` in `apps/web`), then navigate a browser to `http://localhost:3000/optimizations`.

**Expected:** Page loads without a white-screen or SSR crash. The page renders: a header with a back link to /dashboard, a "No optimization runs found" empty state (or run list if runs exist), axis selectors for X and Y axis, and either an empty heatmap placeholder or a Plotly heatmap. No JavaScript errors in the browser console. No "window is not defined" server-side error (confirming ssr:false on react-plotly.js is effective).

**Why human:** The dynamic import with `ssr:false` avoids a known plotly.js SSR crash, but only a live browser session can confirm the runtime path is clean (React hydration errors, CORS rejections from the API, and dynamic import failures only appear in the browser console or network tab).

### 2. Dashboard Header Optimizations Link

**Test:** Navigate to `http://localhost:3000/dashboard` in a running browser session.

**Expected:** An "Optimizations" link is visible in the dashboard header area. Clicking it navigates to /optimizations without a Next.js error page.

**Why human:** The link's presence is verified in code (dashboard/page.tsx line 142), but its visual position in the rendered layout and navigation behavior require a live Next.js session to confirm.

---

## Gaps Summary

No blocking gaps found. All 14 observable truths are VERIFIED in the codebase. The only outstanding items are 2 human verification tests that require a live browser session — standard for any UI phase delivery.

The Phase 4 backend pipeline is fully wired end-to-end:
- Foundation (Schema + OptSpace + splitter + holdout enforcement): complete and tested (16 tests)
- Worker harness + CLI (run_combo + run_opt.py + ADR gate + holdout guard + ProcessPoolExecutor): complete and tested (20 tests)
- API routes + UI (4 FastAPI endpoints + /optimizations page + dashboard link): complete and tested (10 API tests)

**Total test count for Phase 4 artifacts:** 46 tests (16 Wave 1 + 10 Wave 2 unit + 10 Wave 2 integration + 10 Wave 3 API).

---

_Verified: 2026-05-17T23:30:00Z_
_Verifier: Claude (gsd-verifier)_
