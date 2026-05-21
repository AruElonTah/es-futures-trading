---
phase: 08-operational-hardening-reproducibility-ci
plan: 01
subsystem: testing
tags: [replay, audit-log, reproducibility, duckdb, csv, golden-fixture, subprocess-test, sp-04]

# Dependency graph
requires:
  - phase: 05-risk-manager-full-audit-controls
    provides: DuckDBStore.write_audit_event, FullRiskManager, PaperExecutor, audit_log schema
  - phase: 02-strategy-core
    provides: ORBStrategy, ORBConfig, orb_day_bars fixture

provides:
  - scripts/replay.py CLI re-feeding DuckDB bars through the live engine path (SP-04)
  - scripts/gen_golden.py generating the deterministic golden audit-log CSV
  - test_replay_audit_log.py with engine-path and subprocess CLI CI assertions
  - packages/trading-core/tests/fixtures/golden_audit/2024-06-12.csv committed golden CSV
  - --update-golden pytest option registered in conftest.py

affects:
  - 08-02 (CI workflow — replay tests must pass on windows-latest)
  - future-strategy-changes (golden fixture must be regenerated on audit schema changes)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Deterministic replay output: counter-based event_id (replay-NNNNNNNNNN) and signal_id (signal-NNNNNN) instead of UUID4/UUID7 for byte-identical CSV output"
    - "Golden fixture comparison: byte-identical CSV assertion via read_bytes() — same pattern as FND-08 equity-Parquet reproducibility test"
    - "--duckdb-path CLI override: lets subprocess tests point replay.py at an isolated test DuckDB without touching the live data/duckdb/trading.duckdb"
    - "Risk config alignment: in-process tests load config/risk.yaml via yaml.safe_load to match the CLI's behavior (max_contracts, account_equity, etc.)"

key-files:
  created:
    - scripts/replay.py
    - scripts/gen_golden.py
    - packages/trading-core/tests/integration/test_replay_audit_log.py
    - packages/trading-core/tests/fixtures/golden_audit/2024-06-12.csv
  modified:
    - packages/trading-core/tests/conftest.py

key-decisions:
  - "Deterministic output IDs: counter-based event_id and entity_id in the output CSV (not UUID7/UUID4) so byte-identical comparison works across runs without seeding a PRNG"
  - "Risk config alignment: gen_golden.py and in-process tests load config/risk.yaml via yaml.safe_load to match the CLI (critical for identical fill_qty and PnL values)"
  - "In-process tests initialize FullRiskManager with symbol=SPY (matching the CLI --symbol SPY) since point_value differs by instrument and affects sizing"
  - "Output CSV path: {output-dir}/audit/{date}.csv with date derived from first bar's ET timestamp -- never touches live data/logs/audit/ (D-04)"
  - "Golden CSV has 3 events for the 2024-06-12 synthetic ORB day: risk_decision (approved, size=2), entry_fill (fill_price=471.26, 2 contracts), eod_flat exit (pnl=-0.02)"

patterns-established:
  - "Replay loop order: snapshot (ctx from prior bar) -> on_bar -> _push_bar (BL-1 gate enforced)"
  - "Exit check before new signal processing in the replay loop"
  - "Subprocess test pattern: populate test DuckDB -> time.sleep(0.2) -> subprocess.run with --duckdb-path -> byte compare output"

requirements-completed: [SP-04]

# Metrics
duration: 80min
completed: 2026-05-21
---

# Phase 08 Plan 01: Replay Pipeline + Audit-Log Golden Fixture Summary

**Bar-by-bar replay CLI (ORBStrategy -> FullRiskManager -> PaperExecutor -> CSV) with deterministic output and byte-identical golden-fixture CI assertion via both in-process and subprocess tests**

## Performance

- **Duration:** ~80 min
- **Started:** 2026-05-20T23:30:00Z
- **Completed:** 2026-05-21T00:13:41Z
- **Tasks:** 3
- **Files modified/created:** 5

## Accomplishments

- `scripts/replay.py` CLI drives the full live engine path bar-by-bar, reading bars from DuckDB (`--duckdb-path` override for CI isolation), writing isolated audit CSV to `--output-dir/audit/{date}.csv`
- `scripts/gen_golden.py` generates the deterministic golden CSV (`tests/fixtures/golden_audit/2024-06-12.csv`) from `orb_day_bars(date_str="2024-06-12")` -- idempotent (re-running produces zero diff)
- Three CI tests: engine-path byte comparison, UTF-8 no-BOM assertion, subprocess CLI validation
- Full suite (539 tests) passes green with no regressions

## Task Commits

1. **Task 1: Implement scripts/replay.py CLI** - `c31b091` (feat)
2. **Task 2: Register --update-golden option and implement gen_golden.py** - `88454d8` (feat)
3. **Task 3: Write test_replay_audit_log.py, generate and commit golden fixture** - `f9db7d2` (feat)

## Files Created/Modified

- `scripts/replay.py` - Bar-by-bar replay CLI with argparse whitelist, parameterized SQL, --duckdb-path override, deterministic output CSV
- `scripts/gen_golden.py` - Golden fixture generator (no argparse, hard-coded 2024-06-12, deterministic)
- `packages/trading-core/tests/conftest.py` - Added pytest_addoption for --update-golden flag
- `packages/trading-core/tests/integration/test_replay_audit_log.py` - Three tests: engine-path, UTF-8, subprocess CLI
- `packages/trading-core/tests/fixtures/golden_audit/2024-06-12.csv` - Committed golden CSV (3 events, header + data)

## Decisions Made

- **Deterministic output IDs:** Used `replay-NNNNNNNNNN` counter-based event_ids and `signal-NNNNNN` entity_ids instead of UUID7/UUID4 for the output CSV. The internal `store.write_audit_event()` still uses `new_run_id()` for DuckDB audit trail (non-deterministic is fine there). Only the output CSV must be byte-stable.
- **Risk config alignment:** gen_golden.py and the in-process test helper both load `config/risk.yaml` via `yaml.safe_load`. Initial version used `RiskConfig()` (defaults), which disagreed with the CLI's `max_contracts=2` from the YAML -- producing different fill sizes and PnL values.
- **FullRiskManager symbol=SPY:** The instrument symbol affects `point_value` (SPY=1.00, MES=5.00) which in turn affects ATR-based sizing. All replay/test code passes `symbol="SPY"` to match the `--symbol SPY` subprocess arg.
- **--to date for subprocess test:** The `--to 2024-06-12` arg produces an empty range since bars start at 14:30 UTC (midnight-to-midnight). Fixed to pass `--to 2024-06-13` so all bars on the fixture date are included.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Non-deterministic UUID4/UUID7 event_ids in output CSV**
- **Found during:** Task 3 (generating golden and byte comparison)
- **Issue:** Plan called for `write_audit_event` calls producing the output CSV, but `new_run_id()` generates UUID7s (time-based) that differ between runs. Signal.signal_id is UUID4 (random). Both land in the output CSV columns, breaking byte-identical comparison.
- **Fix:** Output CSV uses counter-based `event_id=f"replay-{n:010d}"` and `entity_id=f"signal-{n:06d}"` instead of UUIDs. Internal DuckDB writes still use `new_run_id()`.
- **Files modified:** scripts/replay.py, scripts/gen_golden.py, test_replay_audit_log.py
- **Verification:** golden fixture idempotent (zero diff on re-run), all 3 tests pass
- **Committed in:** c31b091, 88454d8, f9db7d2

**2. [Rule 1 - Bug] --to date same as --from produces empty DuckDB query range**
- **Found during:** Task 3 (subprocess test debugging)
- **Issue:** `--from 2024-06-12 --to 2024-06-12` both parse to `2024-06-12 00:00:00+00:00`; the parameterized SELECT `ts_utc >= frm AND ts_utc < to` returns zero rows since all bars start at 14:30 UTC.
- **Fix:** Subprocess test passes `--to 2024-06-13` (day after fixture date) so bars are included.
- **Files modified:** test_replay_audit_log.py
- **Verification:** subprocess test produces bars and matches golden
- **Committed in:** f9db7d2

**3. [Rule 1 - Bug] RiskConfig defaults disagree with config/risk.yaml for subprocess**
- **Found during:** Task 3 (byte comparison showing -0.01 vs -0.02 PnL)
- **Issue:** In-process test used `RiskConfig()` defaults (`max_contracts=1`); CLI loads `config/risk.yaml` (`max_contracts=2`). Different sizing -> different fill_qty -> different PnL -> byte mismatch.
- **Fix:** gen_golden.py and in-process test load `config/risk.yaml` via `yaml.safe_load`.
- **Files modified:** scripts/gen_golden.py, test_replay_audit_log.py
- **Verification:** All 3 tests pass with identical golden CSV
- **Committed in:** f9db7d2

---

**Total deviations:** 3 auto-fixed (Rule 1 bugs)
**Impact on plan:** All three bugs were discovered during Task 3 testing and resolved before commit. No scope creep — fixes were necessary for the byte-identical comparison to work correctly.

## Issues Encountered

- Non-deterministic UUIDs in audit events required a redesign of the output CSV ID scheme. The fix (counter-based IDs) is cleaner and makes the reproducibility guarantee explicit.
- The `--to` date must be exclusive and set to the next calendar day when using bare dates (no time component), since bars start at 14:30 UTC, not midnight.
- Risk config must be loaded from the same source in all code paths (CLI, gen_golden.py, in-process tests) to produce identical sizing results.

## Known Stubs

None - the replay loop drives the full live engine path. The golden CSV contains real engine output (3 events for the synthetic 2024-06-12 ORB day: risk approval + entry fill + EOD flatten).

## Threat Flags

No new network endpoints, auth paths, or trust boundary changes introduced. T-08-01 (SQL injection via `--symbol`/`--tf`), T-08-02 (path traversal via `--output-dir`), and T-08-03 (YAML code execution) are all mitigated as specified in the plan.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- SP-04 replay pipeline complete and CI-tested
- Phase 08 Plan 02 (GitHub Actions CI workflow) can now include `uv run pytest packages/trading-core/tests/integration/test_replay_audit_log.py` as a required step
- Any intentional change to the audit-log schema requires running `uv run python scripts/gen_golden.py` and committing the updated golden fixture

## Self-Check: PASSED

All created files exist and commits are verified:

- FOUND: `scripts/replay.py`
- FOUND: `scripts/gen_golden.py`
- FOUND: `packages/trading-core/tests/integration/test_replay_audit_log.py`
- FOUND: `packages/trading-core/tests/fixtures/golden_audit/2024-06-12.csv`
- FOUND: `.planning/phases/08-operational-hardening-reproducibility-ci/08-01-SUMMARY.md`

Commits:
- `c31b091` feat(08-01): implement scripts/replay.py CLI for SP-04 replay pipeline
- `88454d8` feat(08-01): add --update-golden pytest option and gen_golden.py fixture generator
- `f9db7d2` feat(08-01): write test_replay_audit_log.py and generate+commit golden fixture

Golden CSV header: `event_id,ts_utc,topic,entity_id,reason_code,payload_json` (correct)

---
*Phase: 08-operational-hardening-reproducibility-ci*
*Completed: 2026-05-21*
