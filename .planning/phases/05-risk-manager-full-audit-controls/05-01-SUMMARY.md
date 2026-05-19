---
phase: "05"
plan: "01"
subsystem: risk-data-contracts
tags: [risk, drawdown, schema, audit, duckdb]
dependency_graph:
  requires: []
  provides:
    - DrawdownModel enum importable from trading_core.risk.models
    - RiskConfig with Phase 5 fields (account_equity, max_risk_per_trade_pct, daily_dd_limit, drawdown_model)
    - RiskState with Phase 5 fields (equity_high_water, open_exposure_dollars, drawdown_model)
    - schema.sql DDL for risk_state (13 cols), audit_log (6 cols), engine_state (4 cols)
    - TOPIC_AUDIT and TOPIC_ENGINE_STATE constants from events/models.py
    - DuckDBStore methods: write_risk_state, write_audit_event, get_last_risk_state, write_engine_state, get_engine_state
    - config/risk.yaml with all 5 ROADMAP-locked risk parameters
  affects:
    - All Phase 5 plans (02-05) depend on these contracts
    - Phase 3 backtests (backward-compat preserved)
tech_stack:
  added: []
  patterns:
    - DrawdownModel(str, Enum) with __str__ override for Python 3.11+ clean YAML round-trip
    - Append-only DuckDB tables with uuid7 PKs (no upsert needed)
    - Synchronous DuckDB INSERT + CSV flush for kill-9 audit durability (SP-03)
    - Decimal-to-str conversion before DuckDB DECIMAL(20,10) columns
key_files:
  created:
    - config/risk.yaml
    - packages/trading-core/tests/risk/test_models_phase5.py
  modified:
    - packages/trading-core/src/trading_core/risk/models.py
    - packages/trading-core/src/trading_core/storage/schema.sql
    - packages/trading-core/src/trading_core/events/models.py
    - packages/trading-core/src/trading_core/storage/duckdb_store.py
    - packages/trading-core/tests/test_models_phase3_fields.py
decisions:
  - "DrawdownModel uses (str, Enum) with explicit __str__ override — Python 3.11+ changed str(StrEnum) to include class prefix, so override returns bare .value for clean YAML round-trips"
  - "write_audit_event derives ET date from ts_utc.astimezone(ZoneInfo('America/New_York')) for the CSV filename — correct for DST transitions"
  - "CSV path uses self._db_path.parent / 'logs' / 'audit' — co-located with DuckDB so both are on the same filesystem (atomic at disk level)"
  - "test_models_phase3_fields.py extra-field test updated from daily_dd_limit to unknown_phase3_field — daily_dd_limit is a valid Phase 5 field now"
  - "write_engine_state uses lazy import of new_run_id to avoid circular dependency between storage.duckdb_store and storage.runs"
metrics:
  duration: "~13m"
  completed_date: "2026-05-19"
  tasks_completed: 2
  files_changed: 7
---

# Phase 05 Plan 01: Data Contract Foundation Summary

**One-liner:** Schema DDL + DrawdownModel enum + extended RiskConfig/RiskState + DuckDBStore audit methods establishing the complete data contract for Phase 5 risk manager.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 (RED) | Failing tests for DrawdownModel + RiskConfig/RiskState Phase 5 fields | 574becb | tests/risk/test_models_phase5.py |
| 1 (GREEN) | Implement DrawdownModel enum + RiskConfig/RiskState extensions + config/risk.yaml | 6186808 | risk/models.py, config/risk.yaml, test_models_phase3_fields.py |
| 2 | Schema DDL + events constants + DuckDBStore 5 new methods | ed1dd53 | schema.sql, events/models.py, duckdb_store.py |

## What Was Built

### Task 1 — Risk Domain Models (TDD)

**DrawdownModel enum** (`str, Enum` inheritance):
- `STATIC` — HWM fixed at session start (never rises intraday)
- `TRAILING_EOD` — HWM ratchets at session close each day
- `TRAILING_INTRADAY` — HWM ratchets in real time (Apex-style)
- `__str__` override returns bare `.value` — Python 3.11+ compatibility fix

**RiskConfig extensions** (all with backward-compatible defaults):
- `account_equity: Decimal = Decimal("50000")` — static sizing equity (D-02)
- `max_risk_per_trade_pct: Decimal = Decimal("0.01")` — 1% per trade (D-03)
- `daily_dd_limit: Decimal = Decimal("2000")` — circuit breaker (D-04)
- `drawdown_model: DrawdownModel = DrawdownModel.TRAILING_INTRADAY` — active model (D-04)

**RiskState extensions** (all with backward-compatible defaults):
- `equity_high_water: Decimal = Decimal("0")` — HWM for active DD tracking (D-13)
- `open_exposure_dollars: Decimal = Decimal("0")` — unrealized exposure (D-13)
- `drawdown_model: DrawdownModel = DrawdownModel.TRAILING_INTRADAY` — which model is active

**config/risk.yaml** — new file with all 5 ROADMAP-locked D-04 defaults.

**Test coverage:** 20 tests across 6 test classes; all pass.

### Task 2 — Schema + Events + DuckDBStore

**schema.sql** — 3 new append-only tables:
- `risk_state` (13 cols): Full audit trail of all 3 DD models side-by-side on every update
- `audit_log` (6 cols): Every event with synchronous DuckDB + CSV persistence (SP-03)
- `engine_state` (4 cols): Kill/pause/flatten state; most-recent row = current state

**events/models.py** — 2 new Final[str] topic constants:
- `TOPIC_AUDIT = "audit"` — for SP-03 audit bus events
- `TOPIC_ENGINE_STATE = "engine_state"` — for D-10/D-11 state changes

**DuckDBStore** — 5 new methods:
- `write_risk_state(row)` — INSERT with Decimal→str conversion for precision
- `write_audit_event(...)` — DuckDB INSERT + daily CSV append + explicit flush (kill-9 durability)
- `get_last_risk_state(date_str)` — most-recent row for a trading date or None
- `write_engine_state(session_id, state)` — append with `now()` timestamp
- `get_engine_state()` — most-recent state or `'running'` (safe startup default)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Python 3.11+ str(StrEnum) includes class prefix**
- **Found during:** Task 1 GREEN phase test run
- **Issue:** `str(DrawdownModel.STATIC)` returned `"DrawdownModel.STATIC"` instead of `"STATIC"` — Python 3.11 changed the behavior of `str(str_enum_member)` to include the class name
- **Fix:** Added `def __str__(self) -> str: return self.value` override to DrawdownModel
- **Files modified:** `packages/trading-core/src/trading_core/risk/models.py`
- **Commit:** 6186808

**2. [Rule 1 - Bug] Phase 3 extra-field test used a now-valid Phase 5 field**
- **Found during:** Task 1 GREEN phase full suite run
- **Issue:** `test_models_phase3_fields.py::TestRiskConfig::test_risk_config_rejects_extra_fields` used `daily_dd_limit=500` as the "extra field" sentinel — but Phase 5 adds `daily_dd_limit` as a real field
- **Fix:** Updated test to use `unknown_phase3_field=500` as the genuinely unknown field
- **Files modified:** `packages/trading-core/tests/test_models_phase3_fields.py`
- **Commit:** 6186808

## Success Criteria Verification

- [x] DrawdownModel enum importable and str-coercible from YAML values
- [x] RiskConfig and RiskState extended without breaking existing Phase 3 tests
- [x] schema.sql has risk_state (13 cols), audit_log (6 cols), engine_state (4 cols) DDL
- [x] TOPIC_AUDIT and TOPIC_ENGINE_STATE constants exported from events/models.py
- [x] DuckDBStore has write_risk_state, write_audit_event (with CSV mirror), get_last_risk_state, write_engine_state, get_engine_state
- [x] config/risk.yaml created with all 5 params matching D-01/D-04 locked defaults
- [x] Full test suite (trading-core, excluding integration) still green

## Known Stubs

None — all contracts are fully implemented. No placeholder data or TODO stubs.

## Threat Flags

None — no new network endpoints, auth paths, or trust-boundary changes. The audit CSV path is derived from the operator-controlled DuckDB path (T-05-01-04 mitigated by co-location pattern).

## Self-Check: PASSED

- config/risk.yaml: FOUND
- risk/models.py: FOUND (DrawdownModel, RiskConfig Phase 5 fields, RiskState Phase 5 fields)
- schema.sql: FOUND (risk_state, audit_log, engine_state DDL)
- events/models.py: FOUND (TOPIC_AUDIT, TOPIC_ENGINE_STATE)
- duckdb_store.py: FOUND (5 new methods verified via runtime check)
- test_models_phase5.py: FOUND (20 tests passing)
- Commits 574becb, 6186808, ed1dd53: FOUND in git log
