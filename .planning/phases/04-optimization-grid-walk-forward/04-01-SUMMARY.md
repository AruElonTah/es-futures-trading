---
phase: 04-optimization-grid-walk-forward
plan: 01
subsystem: database, optimization
tags: [duckdb, vectorbt, pydantic, walk-forward, grid-search, optimization]

# Dependency graph
requires:
  - phase: 03-vertical-mvp-slice-backtester
    provides: DuckDBStore pattern, schema.sql conventions, BacktestEngine, param_hash()
  - phase: 01-foundation
    provides: storage/runs.py (new_run_id, param_hash), ORBConfig dataclass fields

provides:
  - DuckDB opt_runs, opt_results, holdout_burns schema tables (IF NOT EXISTS DDL)
  - DuckDBStore.write_opt_run(), write_opt_results(), write_holdout_burn(), check_holdout_quota(), read_opt_results()
  - OptSpace Pydantic model with combos() and param_grid_hash() (125-combo 5x5x5 coarse ORB grid)
  - get_fold_boundaries() wrapping vbt.RollingSplitter with BL-4 IS/OOS invariant
  - orb.optspace.yaml: 3 axes x 5 values = 125 combos (D-02)
  - opt-template.md: MADR ADR template for optimization runs
  - 16 tests in packages/trading-core/tests/optimization/ (all pass)

affects:
  - 04-02 (run_opt.py CLI + worker harness uses these interfaces)
  - 04-03 (FastAPI routes + UI consume opt_runs/opt_results)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - OptSpace Pydantic model validates YAML param names against ORBConfig dataclass.fields() at parse time
    - vbt.RollingSplitter used on day-level trading-day index (not bar-level) for calendar-correct fold sizing
    - Fold boundaries as ISO date strings (never pd.Timestamp) for ProcessPoolExecutor pickling safety
    - holdout_burns quota check: SELECT COUNT(*) WHERE quarter = ? → count < 3

key-files:
  created:
    - packages/trading-core/src/trading_core/optimization/__init__.py
    - packages/trading-core/src/trading_core/optimization/space.py
    - packages/trading-core/src/trading_core/optimization/splitter.py
    - config/strategies/orb.optspace.yaml
    - .planning/decisions/opt-template.md
    - packages/trading-core/tests/optimization/__init__.py
    - packages/trading-core/tests/optimization/test_space.py
    - packages/trading-core/tests/optimization/test_splitter.py
    - packages/trading-core/tests/optimization/test_holdout.py
  modified:
    - packages/trading-core/src/trading_core/storage/schema.sql
    - packages/trading-core/src/trading_core/storage/duckdb_store.py

key-decisions:
  - "vbt.RollingSplitter().split() is the correct VBT 1.0.0 OSS API — not vbt.Splitter.from_n_rolling() which does not exist"
  - "Splitter operates on daily trading-day index (CME_Equity calendar, ~21 days/month) not 1m bar-level index for calendar-correct fold boundaries"
  - "Fold boundaries serialized as ISO date strings before returning to prevent pd.Timestamp pickling issues in ProcessPoolExecutor (Pitfall 4)"
  - "OptSpace.validate_axes imports ORBConfig inline (not at module level) to avoid potential circular import (A2)"
  - "param_grid_hash reuses existing param_hash() from storage/runs.py (SHA256 of sorted canonical JSON) for consistency"

patterns-established:
  - "OptSpace.load() classmethod pattern: yaml.safe_load → model_validate → @model_validator runs validation"
  - "BL-4 assertion: is_end < oos_start asserted in function body before returning fold list"
  - "Optimization SQL constants at module level (WRITE_OPT_RUN_SQL etc.) following existing WRITE_RUN_SQL pattern"

requirements-completed:
  - OPT-01
  - OPT-03
  - OPT-04
  - OPT-06
  - OPT-08

# Metrics
duration: 45min
completed: 2026-05-17
---

# Phase 04 Plan 01: Optimization Foundation Summary

**DuckDB schema extended with opt_runs/opt_results/holdout_burns tables, OptSpace Pydantic model (125-combo coarse ORB grid), and vbt.RollingSplitter-based fold generator — all tested with 16 unit tests passing**

## Performance

- **Duration:** ~45 min
- **Started:** 2026-05-17T21:00:00Z
- **Completed:** 2026-05-17T21:45:34Z
- **Tasks:** 2
- **Files modified:** 11

## Accomplishments

- Extended schema.sql with `opt_runs`, `opt_results`, `holdout_burns` DDL (IF NOT EXISTS, idempotent)
- Added 5 new DuckDBStore methods: `write_opt_run`, `write_opt_results`, `write_holdout_burn`, `check_holdout_quota`, `read_opt_results`
- Built `OptSpace` Pydantic model validating param names against `ORBConfig.dataclass_fields()` at parse time and enforcing ≥5 values per axis (OPT-06)
- Created `get_fold_boundaries()` wrapping `vbt.RollingSplitter` on a trading-day index (CME_Equity calendar); returns picklable ISO date strings with BL-4 `is_end < oos_start` assertion
- Shipped `orb.optspace.yaml` with 5×5×5 = 125 combos across `opening_range_minutes`, `atr_stop_mult`, `r_target` (D-02)
- Created `opt-template.md` MADR ADR template with required `is_oos_split`, `optspace_path`, `objective`, `seed` fields
- 16 tests across test_holdout.py, test_space.py, test_splitter.py — all passing

## Task Commits

1. **Task 1: DuckDB schema extensions + DuckDBStore opt methods** - `fe0547a` (feat)
2. **Task 2: OptSpace model + orb.optspace.yaml + fold splitter + test stubs** - `35e1b18` (feat)

## Files Created/Modified

- `packages/trading-core/src/trading_core/storage/schema.sql` — Appended opt_runs, opt_results, holdout_burns CREATE TABLE IF NOT EXISTS blocks
- `packages/trading-core/src/trading_core/storage/duckdb_store.py` — Added 4 SQL constants + 5 new methods
- `packages/trading-core/src/trading_core/optimization/__init__.py` — Subpackage init, exports OptSpace, ParamAxis, get_fold_boundaries
- `packages/trading-core/src/trading_core/optimization/space.py` — OptSpace + ParamAxis Pydantic models
- `packages/trading-core/src/trading_core/optimization/splitter.py` — get_fold_boundaries() wrapper
- `config/strategies/orb.optspace.yaml` — 125-combo coarse ORB parameter grid
- `.planning/decisions/opt-template.md` — MADR ADR template for optimization runs
- `packages/trading-core/tests/optimization/__init__.py` — Empty test subpackage marker
- `packages/trading-core/tests/optimization/test_holdout.py` — 6 tests: schema tables, quota enforcement, write round-trips
- `packages/trading-core/tests/optimization/test_space.py` — 6 tests: combo count, hash stability, axis validation, param name validation
- `packages/trading-core/tests/optimization/test_splitter.py` — 4 tests: BL-4 invariant, fold_idx, ISO strings, IS window size

## Decisions Made

- **VBT API**: Used `vbt.RollingSplitter().split()` — `vbt.Splitter.from_n_rolling()` does not exist in VBT 1.0.0 OSS (04-RESEARCH.md Pitfall 1 confirmed during implementation)
- **Splitter index**: Day-level trading-day index (not bar-level) for calendar-correct IS/OOS window sizing; workers then filter bar DataFrame by date range
- **ISO date strings**: All fold boundaries are `YYYY-MM-DD` ISO strings, not `pd.Timestamp` objects — prevents pickling failures across `ProcessPoolExecutor` on Windows (Pitfall 4)
- **Inline import in model_validator**: `ORBConfig` imported inside `validate_axes()` body to avoid circular import risk (A2 from research)
- **param_grid_hash reuse**: Delegates to existing `param_hash()` from `storage/runs.py` for SHA256 consistency with existing `runs` table

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

None — all implementations worked first-try after following the verified patterns in 04-RESEARCH.md.

## Known Stubs

None — all implementations are functional. OptSpace, get_fold_boundaries(), and DuckDBStore methods are fully wired.

## Threat Flags

No new network endpoints, auth paths, or trust boundary expansions introduced. All file access is local; parameterized SQL used throughout. T-04-01-01 and T-04-01-02 mitigations implemented as specified in the plan's threat model.

## Next Phase Readiness

- Wave 2 (04-02): `run_opt.py` CLI + worker harness can now use `OptSpace.load()`, `get_fold_boundaries()`, `DuckDBStore.write_opt_run()`, `write_opt_results()`, `write_holdout_burn()`, `check_holdout_quota()`
- All 3 DuckDB tables ready for writes
- `orb.optspace.yaml` and `opt-template.md` ready for the ADR gate validation in `run_opt.py`
- No blockers

## Self-Check

- [x] schema.sql contains opt_runs, opt_results, holdout_burns CREATE TABLE IF NOT EXISTS
- [x] DuckDBStore has 5 new methods (verified by test_holdout.py)
- [x] OptSpace.load("config/strategies/orb.optspace.yaml") returns 125 combos (verified inline)
- [x] get_fold_boundaries() produces is_end < oos_start for all folds (verified by test_splitter.py)
- [x] opt-template.md has is_oos_split, optspace_path, objective, seed fields documented
- [x] All 16 optimization tests pass

---
*Phase: 04-optimization-grid-walk-forward*
*Completed: 2026-05-17*
