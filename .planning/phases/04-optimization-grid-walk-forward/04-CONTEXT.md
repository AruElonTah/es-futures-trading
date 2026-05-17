# Phase 4: Optimization Grid + Walk-Forward - Context

**Gathered:** 2026-05-17
**Status:** Ready for planning

<domain>
## Phase Boundary

A user can launch a grid + walk-forward optimization run from a committed ADR, watch progress live in the UI, and inspect an OOS-ranked leaderboard plus 2-param heatmaps — with the most-recent 6 months of bars guarded against accidental burn.

**In scope:** `optspace.yaml` parameter space definition; `run_opt.py` CLI with pre-run ADR gate; `ProcessPoolExecutor` worker harness (per-param-combo workers, read-only DuckDB, per-worker Parquet shards); walk-forward rolling-window splitter (IS=6m, OOS=1m, step=1m); per-fold persistence into `opt_runs` + `opt_results` DuckDB tables with full hashes; true-holdout guard (6-month barrier, 3-burn quarterly quota, `holdout_burns` table); coarse-grid-first enforcement (≥5 points per axis or requires documented prior coarser run); OOS Sharpe as default ranking metric; IS/OOS edge-ratio red-flag column; new `/optimizations` Next.js route with leaderboard + 2-param Plotly heatmap; `GET /optimizations`, `GET /optimizations/{run_id}` FastAPI routes.

**Out of scope:** Bayesian / Optuna / genetic optimization (v2-only, explicit project constraint); Prometheus metrics / Grafana (v1 uses `/metrics` JSON endpoint); multi-strategy concurrency in optimization workers (Phase 5+); dockable multi-pane integration of `/optimizations` into dashboard (Phase 7); optimization run triggering from the Strategy Controls UI panel (Phase 7).

</domain>

<decisions>
## Implementation Decisions

### optspace.yaml Format + First ORB Grid

- **D-01: Standalone file at `config/strategies/orb.optspace.yaml`.** Not embedded in `orb.yaml`. The separation keeps the strategy config (behavior) distinct from the optimization config (search bounds). Naming convention: `{strategy_slug}.optspace.yaml`.

- **D-02: `type: list` syntax for all three ORB axes.** List is preferred over `range/step` for ORB params because the meaningful values are not evenly spaced in a way that warrants arithmetic ranges. The initial coarse grid (satisfies OPT-06's ≥5 points per axis):
  ```yaml
  strategy: orb
  params:
    opening_range_minutes: { type: list, values: [5, 10, 15, 20, 30] }       # 5 points
    atr_stop_mult:         { type: list, values: [1.0, 1.5, 2.0, 2.5, 3.0] } # 5 points
    r_target:              { type: list, values: [1.5, 2.0, 2.5, 3.0, 3.5] } # 5 points
  ```
  → 125 combos, 3 axes. Matches the ROADMAP success criterion #2 example exactly.

- **D-03: `optspace.yaml` parsed into a typed `OptSpace` Pydantic model.** Loader validates that each param name exists in the strategy's `ORBConfig`, that every axis has ≥5 values (OPT-06 enforcement at parse time), and produces an `itertools.product`-based combo iterator. Unknown param names raise `ValueError` — prevents silent typos.

### Walk-Forward Window Configuration

- **D-04: Rolling walk-forward (fixed-width IS window, slides forward).** Rationale: rolling windows keep IS data recent — anchored windows would train on increasingly stale bars as time advances, which is problematic for regime-sensitive ORB. Default config (specified in the optimization ADR and overridable via `run_opt.py` flags):
  - IS window: 6 months
  - OOS window: 1 month
  - Step: 1 month (rolling forward)
  - Warmup: placed before the IS window start (never spanning into OOS — BL-4 invariant)

- **D-05: Walk-forward implemented via `vbt.Splitter.from_n_rolling()`.** VectorBT OSS 1.0.0 supports this natively. The splitter produces fold boundaries as date ranges; the orchestrator iterates folds, slices the bar DataFrame, passes each fold to workers. Workers never see OOS bars during IS training (warmup bars from before IS window are the only exception).

### ProcessPoolExecutor Architecture

- **D-06: Unit of work = one param-combo across all folds.** Each worker receives: (param_dict, fold_boundaries[], bars_path). Worker loads bars from Parquet once, runs the full walk-forward for its single param set, writes one Parquet shard with per-fold results. Orchestrator submits 125 futures (one per combo), collects shards, aggregates into `opt_runs` + `opt_results` in a single-process pass.

  This is simpler than per-(combo × fold) tasks: fewer IPC boundaries, each worker touches DuckDB only once (read-only bars fetch), and the shard aggregation is a single `pd.concat` pass.

- **D-07: Workers import only `trading-core` (not `api` or `tv-bridge`).** Lint check (similar to the `no-direct-vbt-from-signals` hook) blocks `import api` or `import tv_bridge` in worker modules. Anti-Pattern 5 from ARCHITECTURE.md.

- **D-08: Per-worker Parquet shards written to `data/parquet/opt/{run_id}/worker_{combo_hash}.parquet`.** The orchestrator aggregates from these paths. Shard format: columns `fold_idx`, `param_hash`, `is_sharpe`, `oos_sharpe`, `is_return`, `oos_return`, `equity_curve_path`, `git_sha`, `data_hash`, `param_grid_hash`, `seed`. After aggregation, shards are not deleted (they're the forensic record).

### ADR Gate + Holdout Guard

- **D-09: Pre-run ADR gate reads `.planning/decisions/opt-*.md` glob.** `run_opt.py` refuses to start unless at least one matching ADR exists. The ADR must declare: IS/OOS split, parameter grid (references `optspace.yaml` path), objective function (must be `oos_sharpe`), and seed. The ADR content hash is written to every `opt_runs` row. An ADR template ships at `.planning/decisions/opt-template.md` for the user to copy and fill in before the first run.

- **D-10: True-holdout guard enforced in DuckDB, not application code.** A `holdout_burns` table tracks burn events. `run_opt.py` queries this table before allowing `--burn-holdout`. Quota: 3 burns per calendar quarter (OPT-08 caps at 3, not 4 as the ROADMAP says; the ROADMAP success criterion says "4th burn within a quarter is refused" — this means ≤3 burns allowed, which is 4th refused. Implementation: `WHERE quarter = current_quarter AND COUNT(*) >= 3 → reject`).

### Optimization UI (New `/optimizations` Route)

- **D-11: New Next.js route at `/optimizations`, linked from `/dashboard` header.** Not a panel within the existing dashboard (Phase 7 does multi-pane integration). The route contains two sections:
  1. **Leaderboard table** — columns: rank, param_hash (truncated), `opening_range_minutes`, `atr_stop_mult`, `r_target`, OOS Sharpe, IS Sharpe, IS/OOS edge ratio (red if > 2), OOS return, fold count. Sorted by OOS Sharpe descending. Clicking a row navigates to a detail view.
  2. **2-param heatmap** — two axis selectors (dropdowns from the grid axes), renders OOS Sharpe as a Plotly heatmap. `react-plotly.js` per CLAUDE.md ("de facto choice; vectorbt's own internal plotting is Plotly so we already get the contract").

- **D-12: `GET /optimizations` returns paginated list of optimization runs sorted by `created_at` desc.** `GET /optimizations/{run_id}/results` returns the full leaderboard rows for a run (filtered from `opt_results`). `GET /optimizations/{run_id}/heatmap?axis_x=opening_range_minutes&axis_y=atr_stop_mult` returns the 2D grid for Plotly rendering. No WebSocket streaming for optimization progress in Phase 4 — polling via TanStack Query at 2s interval while a run is in-flight.

### DuckDB Schema Extensions

- **D-13: Two new tables: `opt_runs` + `opt_results`.** `opt_runs`: `run_id`, `strategy_id`, `adr_hash`, `param_grid_hash`, `is_start`, `is_end`, `oos_start`, `oos_end`, `seed`, `fold_count`, `created_at`, `status` (running|complete|failed). `opt_results`: `result_id`, `run_id`, `fold_idx`, `param_hash`, `opening_range_minutes`, `atr_stop_mult`, `r_target`, `is_sharpe`, `oos_sharpe`, `is_return`, `oos_return`, `edge_ratio`, `equity_curve_path`, `git_sha`, `data_hash`, `seed`. `holdout_burns` table: `burn_id`, `run_id`, `burned_at`, `quarter` (YYYYQ format).

- **D-14: `param_hash` = SHA256 of the sorted JSON-serialized param dict.** Matches the existing `param_hash` convention already in the `runs` table. Enables forensic lookup: "which runs used these exact params?"

### Claude's Discretion

- Worker process count defaults to `os.cpu_count() - 1` (leaves one core for the orchestrator / UI). No user-configurable max-workers in Phase 4 — add to `run_opt.py` flags in Phase 7 if needed.
- Progress reporting during optimization: orchestrator logs completed futures as they land (structlog `opt.fold.complete` events). No live UI progress bar in Phase 4 — the 2s poll on `/optimizations` shows when status flips from `running` to `complete`.
- Coarse-grid-first enforcement: if any axis has < 5 values, `run_opt.py` emits an audit-log warning AND checks `opt_runs` for a prior run with `param_grid_hash` that used wider ranges. If no prior coarser run exists, `run_opt.py` refuses. This enforces OPT-06 structurally, not just advisory.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase Goal + Requirements

- `.planning/ROADMAP.md` §"Phase 4: Optimization Grid + Walk-Forward" — Goal, 5 success criteria (ADR gate, coarse grid, holdout guard, leaderboard, narrow-range guard), requirements mapping (OPT-01..09), Notes (workers must import only `trading-core`, BL-4 warmup placement).
- `.planning/ROADMAP.md` §"Cross-Phase Guardrails" — Walk-forward ADR-before-first-run gate, Reproducibility CI (must stay green across optimization workers), four Protocol seams (workers call `BacktestEngine.run()` through the same protocol path).
- `.planning/REQUIREMENTS.md` — OPT-01..OPT-09 full requirement specs.
- `CLAUDE.md` — Stack versions, "What NOT to Use" table (VectorBT 1.0.0, pandas 2.2.x, react-plotly.js for heatmaps, ProcessPoolExecutor not multiprocessing.Pool).

### Prior Phase Decisions

- `.planning/phases/03-vertical-mvp-slice-backtester/03-CONTEXT.md` — D-01 (`backtests` + `trades` DuckDB schema), D-03 (equity Parquet byte-stable flags), D-13 (`safe_from_signals` enforcement), D-14 (BL-1 CI test). Phase 4 workers call `BacktestEngine` + `safe_from_signals` identically.
- `.planning/phases/03-vertical-mvp-slice-backtester/03-02-SUMMARY.md` — `BacktestEngine.run()` signature; `PaperExecutor`, `PassThroughRiskManager` interfaces. Workers instantiate these directly.

### ADR + Data Provider

- `.planning/decisions/0001-data-provider.md` — TV MCP primary + Twelve Data SPY secondary. Workers must use `TwelveDataSource` (headless, no TV Desktop dep) for bar fetches. `adr_hash` of this ADR is already logged in every `runs` row; `opt_runs` does the same.

### Existing Code — Key Files for Phase 4

- `packages/trading-core/src/trading_core/backtest/engine.py` — `BacktestEngine.run()` is the unit of work each worker calls per param-combo per fold. Read fully before planning worker code.
- `packages/trading-core/src/trading_core/backtest/safe_signals.py` — `safe_from_signals()` wrapper. Workers call this; the pre-commit hook still enforces no direct `vbt.Portfolio.from_signals` calls.
- `packages/trading-core/src/trading_core/storage/duckdb_store.py` — `DuckDBStore` existing pattern. Phase 4 adds `write_opt_run()`, `write_opt_result()`, `write_holdout_burn()`. Workers use a read-only connection variant.
- `packages/trading-core/src/trading_core/strategy/orb.py` + `config/strategies/orb.yaml` — `ORBStrategy`, `ORBConfig`. Workers instantiate `ORBStrategy` from param dicts; `optspace.yaml` param names must match `ORBConfig` field names.
- `packages/trading-core/src/trading_core/instruments.py` — Tick values / session bounds. Required in worker scope; no magic numbers.
- `packages/api/src/api/app.py` — Existing FastAPI shell. Phase 4 adds `GET /optimizations`, `GET /optimizations/{run_id}/results`, `GET /optimizations/{run_id}/heatmap`.
- `apps/web/app/dashboard/page.tsx` — Existing `/dashboard`. Phase 4 adds a "Optimizations" link in the header. Do not modify the chart/equity panes.
- `scripts/run_backtest.py` — Pattern for the `run_opt.py` CLI (same CLI shape: `--strategy`, `--space`, `--symbol`, `--tf`, `--from`, `--to`).

### VectorBT Walk-Forward

- VectorBT OSS 1.0.0 — `vbt.Splitter.from_n_rolling()` for rolling fold generation. Parameters: `n` (number of folds, derived from date range ÷ step size), `window_len` (IS bars), `set_lens` (OOS bars ratio). Documentation: `https://vectorbt.dev` / OSS 1.0.0 source.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets

- `BacktestEngine` (`backtest/engine.py`): Async `run()` method is the worker's inner loop. Workers call it synchronously via `asyncio.run()` (each worker process has its own event loop). Phase 3 verified it's deterministic given the same inputs.
- `DuckDBStore` (`storage/duckdb_store.py`): Context manager with `ensure_schema()`. Phase 4 extends `ensure_schema()` with the `opt_runs`, `opt_results`, `holdout_burns` DDL. Workers use a lightweight read-only variant (no `ensure_schema`, no write methods).
- `StrategyRegistry` (`strategy/registry.py`): Workers load `ORBStrategy` via `StrategyRegistry.from_yaml()` with param overrides from the combo dict.
- `write_equity_parquet` (`backtest/engine.py`): Byte-stable Parquet writer (compression=none). Workers call this for per-fold equity curves.
- `new_run_id()` (`storage/runs.py`): UUID7 generator for `run_id`, `result_id` — reuse in Phase 4 IDs.

### Established Patterns

- **CLI script pattern** (`scripts/run_backtest.py`): `argparse` → validate args → instantiate components → call async function via `asyncio.run()`. `run_opt.py` follows the same shape.
- **Single-writer DuckDB**: orchestrator is the only writer; workers write Parquet shards only.
- **Decimal-only arithmetic in price paths**: workers inherit this via `BacktestEngine`.
- **`pytest --import-mode=importlib`**: all new test files follow; no `tests/__init__.py`.
- **Pre-commit hooks**: `no-direct-vbt-from-signals` already enforced; Phase 4 adds `no-api-in-worker` lint rule.

### Integration Points

- `packages/trading-core/`: Add `optimization/` subpackage — `space.py` (OptSpace model + parser), `worker.py` (worker function), `splitter.py` (rolling fold wrapper around VBT Splitter).
- `packages/trading-core/src/trading_core/storage/duckdb_store.py`: Add `write_opt_run()`, `write_opt_result()`, `write_holdout_burn()`, `check_holdout_quota()`, `read_opt_results()`.
- `packages/api/src/api/routes/`: Add `optimizations.py` route file with the three endpoints.
- `apps/web/app/optimizations/page.tsx`: New Next.js App Router page (leaderboard + heatmap). Install `react-plotly.js` + `plotly.js`.
- `scripts/run_opt.py`: New CLI script alongside `run_backtest.py` and `seed_bars.py`.
- `config/strategies/orb.optspace.yaml`: New file defining the first coarse ORB grid (D-02).
- `.planning/decisions/opt-template.md`: ADR template for optimization runs.

</code_context>

<specifics>
## Specific Ideas

- **ADR template at `.planning/decisions/opt-template.md`**: Ships with Phase 4 so the user can copy + fill it in before running `run_opt.py` the first time. Required fields: `is_oos_split` (e.g., "IS=6m OOS=1m rolling"), `optspace_path`, `objective` (must be `oos_sharpe`), `seed`. The `run_opt.py` ADR gate validates these fields by name.
- **IS/OOS edge-ratio visual treatment**: In the leaderboard table, `edge_ratio > 2.0` cells render with a red background. The column header tooltip explains: "IS/OOS edge ratio > 2 indicates potential overfitting — the strategy performed more than 2× better in-sample than out-of-sample."
- **Heatmap axis labels**: The Plotly heatmap uses the actual param values (not indices) as axis tick labels. Colorscale: `RdYlGn` (red = low OOS Sharpe, green = high). Zero/negative Sharpe cells are clamped to the red end.
- **Progress polling**: `/optimizations/{run_id}` returns `{"status": "running", "completed_combos": N, "total_combos": 125}`. The `/optimizations` page polls at 2s while any run is `running`, stops when status is `complete`.
- **Coarse-grid-first check**: The `opt_runs` table stores `param_grid_hash`. When `run_opt.py` detects an axis with < 5 points, it queries `opt_runs WHERE strategy_id = ? AND status = 'complete'` for a run with a different (coarser) `param_grid_hash`. If found, proceeds with audit-log warning. If not found, refuses with: "No prior coarser run found. Run a coarse grid (≥5 points per axis) first."

</specifics>

<deferred>
## Deferred Ideas

- **Optimization run triggering from the Strategy Controls panel** — Phase 7 (after multi-pane layout ships).
- **Docking `/optimizations` into the dashboard as a resizable pane** — Phase 7.
- **Live WebSocket progress bar during optimization** — Phase 7 (Phase 4 uses 2s polling).
- **Bayesian / Optuna / genetic optimization** — v2-only per explicit project constraint.
- **Monte Carlo bootstrap bands on equity curve** — v2 (V2-OPT-03 in REQUIREMENTS.md).
- **Max-workers CLI flag for `run_opt.py`** — deferred to Phase 7 if needed; defaults to `cpu_count - 1` in Phase 4.
- **Optimization run comparison view (diff two runs)** — not in scope for Phase 4 or 7; v2 candidate.

</deferred>

---

*Phase: 04-optimization-grid-walk-forward*
*Context gathered: 2026-05-17*
