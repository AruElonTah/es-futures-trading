---
phase: "03"
plan: "01"
subsystem: models-schema-hooks
tags:
  - foundation
  - models
  - duckdb
  - pre-commit
  - wave-1
dependency_graph:
  requires:
    - 01-02-SUMMARY  # execution/models.py + risk/models.py stubs
    - 01-04-SUMMARY  # DuckDBStore pattern established
    - 01-05-SUMMARY  # pre-commit hook infrastructure
  provides:
    - D-10-fields     # Fill, RiskDecision, RiskState, RiskConfig with minimal fields
    - D-01-schema     # backtests table (20 cols)
    - D-02-schema     # trades table (17 cols, nullable stop_price/target_price)
    - D-13-hook       # no-direct-vbt-from-signals pre-commit guard
    - wave-0-stubs    # 7 xfail placeholder test files for subsequent plans
  affects:
    - 03-02-PLAN  # safe_from_signals wrapper (inherits D-13 hook)
    - 03-03-PLAN  # BacktestEngine (uses Fill, backtests, trades)
    - 03-04-PLAN  # FastAPI routes (uses backtests table)
tech_stack:
  added:
    - pydantic AwareDatetime + field_validator UTC guard (Fill)
    - Decimal(gt=0) field constraint (fill_price, fill_qty)
    - Literal["long","short"] + Literal["target","stop","eod_flat","manual"] (Fill)
    - DuckDB CREATE TABLE IF NOT EXISTS backtests + trades (schema.sql)
    - DuckDBStore.write_backtest() + write_trades() with parameterized queries
    - no-direct-vbt-from-signals pre-commit hook (regex-based, D-13)
  patterns:
    - TDD RED-GREEN on all three tasks
    - parameterized DuckDB queries for all new inserts (T-03-01-01 mitigation)
    - xfail strict=True Wave 0 stubs (7 files, downstream plans fill them in)
key_files:
  created:
    - packages/trading-core/tests/test_models_phase3_fields.py
    - packages/trading-core/tests/test_duckdb_backtests_trades.py
    - scripts/hooks/no_direct_vbt.py
    - packages/trading-core/tests/test_safe_signals.py
    - packages/trading-core/tests/test_backtest_engine.py
    - packages/trading-core/tests/test_paper_executor.py
    - packages/trading-core/tests/integration/test_lookahead.py
    - packages/trading-core/tests/integration/test_reproducibility.py
    - packages/api/tests/test_routes.py
    - packages/api/tests/test_ws_stream.py
  modified:
    - packages/trading-core/src/trading_core/execution/models.py
    - packages/trading-core/src/trading_core/risk/models.py
    - packages/trading-core/src/trading_core/storage/schema.sql
    - packages/trading-core/src/trading_core/storage/duckdb_store.py
    - .pre-commit-config.yaml
    - packages/trading-core/tests/test_duckdb_store.py
decisions:
  - "RiskConfig + RiskState: NOT frozen (Phase 5 can extend cleanly); Fill: frozen=True (immutable audit record)"
  - "write_trades returns int (row count) for caller validation; 0 on empty list"
  - "stop_price + target_price nullable in trades table (non-ORB strategies omit them)"
  - "no_direct_vbt.py uses regex not AST (unambiguous pattern, T-03-01-04 accept)"
  - "Wave 0 stubs use strict=True xfail so unexpected passes cause failures (future-proofing)"
  - "test_duckdb_store.py test_creates_all_tables updated from exact-set to subset assert to accommodate new tables"
metrics:
  duration: "~26 minutes"
  completed: "2026-05-17"
  tasks: 3
  files: 16
---

# Phase 03 Plan 01: Foundation — Models, Schema, Pre-commit Hook Summary

## One-liner

Pydantic D-10 minimal fields on Fill/RiskDecision/RiskState/RiskConfig, DuckDB backtests+trades tables with parameterized writers, no-direct-vbt pre-commit hook, and 7 Wave 0 xfail stubs — locking data shapes before Waves 2-5 build on them.

## What Was Built

### Task 1 — D-10 Minimal Fields on Models

Filled in the existing empty stubs in `execution/models.py` and `risk/models.py`:

**Fill** (frozen=True, extra="forbid"):
- `signal_id: str`
- `fill_price: Decimal = Field(gt=Decimal("0"))`
- `fill_qty: int = Field(gt=0)`
- `side: Literal["long", "short"]`
- `slippage_ticks: int = Field(ge=0)`
- `ts_utc: AwareDatetime` + `must_be_utc` validator (rejects non-UTC offsets)
- `exit_reason: Literal["target", "stop", "eod_flat", "manual"]` (D-11)

**RiskDecision** (extra="forbid", NOT frozen):
- `approved: bool`, `reason: str`, `adjusted_size: int` — all required, no defaults

**RiskState** (extra="forbid", NOT frozen):
- `realized_pnl_today: Decimal = Decimal("0")`

**RiskConfig** (extra="forbid", NOT frozen):
- `max_contracts: int = 1`

Test coverage: 19 tests covering all fields, Literal rejection, AwareDatetime + UTC guard, frozen enforcement, extra field rejection.

### Task 2 — DuckDB Schema Extension + DuckDBStore Writers

Extended `schema.sql` with two new tables:

**`backtests`** (D-01): `run_id` (PK), `strategy_id`, `symbol`, `timeframe`, `from_ts`, `to_ts`, `param_hash`, `equity_curve_path`, plus 12 scalar metrics (`total_return`, `cagr`, `sharpe`, `sortino`, `calmar`, `max_dd`, `max_dd_duration_bars`, `win_rate`, `expectancy`, `profit_factor`, `trade_count`, `avg_hold_bars`), `created_at`.

**`trades`** (D-02): `trade_id` (PK), `run_id`, `signal_id`, `strategy_id`, `side`, `entry_price`, `exit_price`, `exit_reason` (D-11), `entry_ts_utc`, `exit_ts_utc`, `pnl`, `size`, `slippage_ticks`, `mae`, `mfe`, nullable `stop_price` + `target_price`, `created_at`.

Added to `duckdb_store.py`:
- `WRITE_BACKTEST_SQL` + `WRITE_TRADE_SQL` module-level constants (parameterized `?` placeholders)
- `write_backtest(*, ...)` — 20 keyword-only args, plain INSERT
- `write_trades(trades: list[dict]) -> int` — returns row count, handles nullable stop/target, 0 on empty list

Test coverage: 11 tests covering table creation, idempotency, write roundtrip, nullable fields, SQL injection defense (T-03-01-01).

### Task 3 — Pre-commit Hook + Wave 0 Test Stubs

**`scripts/hooks/no_direct_vbt.py`**: Regex-based hook using `r'vbt\.Portfolio\.from_signals\s*\('`. Mirrors `no_naive_tz.py` CLI shape — prints `path:lineno: message`, exits 1 on violations, 0 clean. Handles unreadable files silently.

**`.pre-commit-config.yaml`**: Registered `no-direct-vbt-from-signals` hook in the existing `- repo: local` block with exclusions for `safe_signals.py` (the only legitimate call site), the hook script itself, `test_safe_signals.py`, and `integration/test_lookahead.py`.

**7 Wave 0 test stubs** (all xfail strict=True, collect without error):
- `test_safe_signals.py` — BT-02 (Wave 2 Plan 02)
- `test_backtest_engine.py` — BT-01/04/05/06 (Wave 3 Plan 03)
- `test_paper_executor.py` — BT-03/08 (Wave 2 Plan 02)
- `integration/test_lookahead.py` — BT-07/D-14 BL-1 gate (Wave 3 Plan 03)
- `integration/test_reproducibility.py` — BT-09/FND-08 (Wave 3 Plan 03)
- `api/tests/test_routes.py` — UI-01 (Wave 4 Plan 04)
- `api/tests/test_ws_stream.py` — SP-01/D-04/D-05 (Wave 4 Plan 04)

## Commits

| Task | Commit | Files |
|------|--------|-------|
| 1: D-10 model fields | 0890d4f | execution/models.py, risk/models.py, test_models_phase3_fields.py |
| 2: DuckDB backtests+trades | 23932c7 | schema.sql, duckdb_store.py, test_duckdb_backtests_trades.py, test_duckdb_store.py |
| 3: Pre-commit hook + Wave 0 | 14d148f | no_direct_vbt.py, .pre-commit-config.yaml, 7 Wave 0 stubs |

## Test Results

- Task 1: 19 passing
- Task 2: 11 passing (+ 1 existing test updated — test_creates_all_tables)
- Task 3: 30 passing + 7 xfailed (all expected)
- Pre-existing test_health.py API import failure: pre-existing, not caused by this plan (confirmed by stash test)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] test_duckdb_store.py expected exactly 4 tables, now 6**
- **Found during:** Task 2 integration check
- **Issue:** `test_creates_all_four_tables` asserted `tables == {"bars", "bar_gaps", "instruments", "runs"}` — failed after adding `backtests` + `trades`
- **Fix:** Renamed to `test_creates_all_tables`; replaced equality assertion with `issubset` check plus explicit assertions for new tables, preserving the spirit of the test
- **Files modified:** `packages/trading-core/tests/test_duckdb_store.py`
- **Commit:** 23932c7

**2. [Rule 1 - Bug] Docstring escape sequence SyntaxWarning in no_direct_vbt.py**
- **Found during:** Task 3 hook testing
- **Issue:** `r'vbt\.Portfolio\.from_signals\s*\('` in a docstring (non-raw string) caused `SyntaxWarning: invalid escape sequence '\.'`
- **Fix:** Replaced the regex pattern in the docstring with plain English description `'vbt.Portfolio.from_signals('`
- **Files modified:** `scripts/hooks/no_direct_vbt.py`
- **Commit:** 14d148f

## Threat Surface Scan

No new network endpoints, auth paths, or file access patterns introduced. The `write_backtest` and `write_trades` methods use parameterized queries exclusively — T-03-01-01 mitigation is complete and tested. The pre-commit hook (T-03-01-03) is active and passes on the current repo.

## Self-Check: PASSED

Verified all created files exist and all commits are in git history.
