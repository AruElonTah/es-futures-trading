---
phase: 08-operational-hardening-reproducibility-ci
verified: 2026-05-20T22:00:00Z
status: passed
score: 6/6 must-haves verified
overrides_applied: 0
---

# Phase 08: Operational Hardening / Reproducibility CI — Verification Report

**Phase Goal:** The system is reproducible across machines and time: a Replay command re-feeds historical bars through the full pipeline and byte-matches the original audit log; the reproducibility CI runs on Windows; backup and audit-log retention are documented.
**Verified:** 2026-05-20T22:00:00Z
**Status:** PASSED
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| #  | Truth                                                                                                                            | Status     | Evidence                                                                                                                  |
|----|----------------------------------------------------------------------------------------------------------------------------------|------------|---------------------------------------------------------------------------------------------------------------------------|
| 1  | `scripts/replay.py` re-feeds DuckDB bars through ORBStrategy -> FullRiskManager -> PaperExecutor and writes an audit-log CSV   | VERIFIED   | File is 471 lines; contains full async bar loop, `write_audit_event`, Decimal OHLC, parameterized SQL, `--duckdb-path`   |
| 2  | A subprocess test invokes `replay.py` as a CLI and byte-compares its output to the committed golden fixture                     | VERIFIED   | `test_replay_cli_subprocess_matches_golden` present; uses `subprocess.run`, `--duckdb-path`, `read_bytes()` comparison    |
| 3  | `--update-golden` pytest option regenerates the golden fixture instead of asserting                                              | VERIFIED   | `conftest.py` registers `--update-golden`; test checks `getoption("--update-golden")` and calls `shutil.copy` then skip  |
| 4  | GitHub Actions CI has two `windows-latest` jobs with `path: "Day Trading"` checkout and UTF-8 env vars                         | VERIFIED   | `ci.yml` confirmed: two jobs, `runs-on: windows-latest`, `path: "Day Trading"`, `PYTHONUTF8`/`PYTHONIOENCODING`          |
| 5  | `docs/operations/backup.md` documents snapshot cadence, file inventory, retention, restore procedure, and encryption            | VERIFIED   | All six required sections present: Purpose, File Inventory, Backup Script, Retention Policy, Restore Procedure, Encryption |
| 6  | `scripts/backup.ps1` performs Copy-Item snapshot with Join-Path and 90-day retention cleanup                                    | VERIFIED   | `Copy-Item` for DuckDB and audit CSV; `Join-Path` chained throughout; retention pipeline present with `AddDays(-$RetentionDays)` |

**Score:** 6/6 truths verified

---

## Required Artifacts

| Artifact                                                                       | Expected                                                | Status     | Details                                                                              |
|--------------------------------------------------------------------------------|---------------------------------------------------------|------------|--------------------------------------------------------------------------------------|
| `scripts/replay.py`                                                            | Bar-by-bar replay CLI driving live engine path          | VERIFIED   | 471 lines; `argparse`, `choices=["ES","MES","SPY"]`, `write_audit_event`, `Decimal(str(` |
| `scripts/gen_golden.py`                                                        | Golden audit-log fixture generator                      | VERIFIED   | File exists; `orb_day_bars`, deterministic counter IDs, writes to `golden_audit/`    |
| `packages/trading-core/tests/integration/test_replay_audit_log.py`            | Byte-identical audit-log CI assertion                   | VERIFIED   | Three tests present; `test_replay_cli_subprocess_matches_golden` confirmed            |
| `packages/trading-core/tests/fixtures/golden_audit/2024-06-12.csv`            | Committed golden audit-log CSV                          | VERIFIED   | Header: `event_id,ts_utc,topic,entity_id,reason_code,payload_json`; 3 data rows      |
| `packages/trading-core/tests/conftest.py`                                     | `--update-golden` pytest option registration            | VERIFIED   | `def pytest_addoption(parser)` with `"--update-golden"` confirmed                    |
| `.github/workflows/ci.yml`                                                    | Windows CI for Python and frontend tests                | VERIFIED   | Two `windows-latest` jobs; `uv run pytest`, `pnpm --filter web exec vitest run`      |
| `docs/operations/backup.md`                                                   | Backup and retention policy runbook                     | VERIFIED   | All six level-2 section headers present; references `backup.ps1`, 90-day retention, BitLocker |
| `scripts/backup.ps1`                                                          | Daily DuckDB + audit-log snapshot script                | VERIFIED   | 64 lines; `Copy-Item`, `Join-Path`, retention pipeline, `param` block with defaults  |

---

## Key Link Verification

| From                                        | To                                                  | Via                        | Status   | Details                                                                   |
|---------------------------------------------|-----------------------------------------------------|----------------------------|----------|---------------------------------------------------------------------------|
| `scripts/replay.py`                         | `DuckDBStore.write_audit_event`                     | per-bar audit event write  | WIRED    | `store.write_audit_event(...)` called inside bar loop for risk decision, entry fill, and exit |
| `test_replay_audit_log.py`                  | `scripts/replay.py`                                 | `subprocess.run` CLI       | WIRED    | `subprocess.run([sys.executable, "scripts/replay.py", ...], cwd=_REPO_ROOT)` |
| `test_replay_audit_log.py`                  | `golden_audit/2024-06-12.csv`                       | `read_bytes()` comparison  | WIRED    | `cli_output_path.read_bytes() == _GOLDEN_CSV.read_bytes()`                |
| `scripts/backup.ps1`                        | `data/backups/{date}/`                              | `Copy-Item` snapshot       | WIRED    | `Copy-Item -Path $srcDb -Destination $dstDb -Force` present               |
| `docs/operations/backup.md`                 | `scripts/backup.ps1`                                | documented runbook reference | WIRED  | Multiple explicit references to `scripts/backup.ps1` and its parameters   |

---

## Probe Execution

| Probe                                                                          | Command                                                                           | Result             | Status |
|--------------------------------------------------------------------------------|-----------------------------------------------------------------------------------|--------------------|--------|
| `packages/trading-core/tests/integration/test_replay_audit_log.py` (3 tests) | `uv run pytest packages/trading-core/tests/integration/test_replay_audit_log.py --tb=short -q` | 3 passed in 25.45s | PASS   |

---

## Behavioral Spot-Checks

| Behavior                                                           | Command / Observation                                      | Result       | Status |
|--------------------------------------------------------------------|------------------------------------------------------------|--------------|--------|
| `replay.py` contains parameterized SQL (no f-string injection)    | Grep for `? ` placeholders in SELECT                       | Confirmed    | PASS   |
| Golden CSV header matches required schema                          | First line of `2024-06-12.csv`                             | `event_id,ts_utc,topic,entity_id,reason_code,payload_json` | PASS |
| `ci.yml` triggers on push and pull_request to master/main          | Read `.github/workflows/ci.yml`                            | Confirmed    | PASS   |
| `backup.ps1` uses `Join-Path` for all path composition            | Full read of `backup.ps1`                                  | Only `Join-Path` used; no string concatenation | PASS |
| `backup.md` has all six required sections                          | Full read of `backup.md`                                   | Purpose, File Inventory, Backup Script, Retention Policy, Restore Procedure, Encryption present | PASS |

---

## Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| — | — | — | — | No debt markers (TBD/FIXME/XXX), no empty stubs, no hardcoded empty data found in any phase-08 files |

---

## Requirements Coverage

| Requirement | Source Plan | Description                                                              | Status    | Evidence                                                                      |
|-------------|-------------|--------------------------------------------------------------------------|-----------|-------------------------------------------------------------------------------|
| SP-04       | 08-01       | Replay command re-feeds bars through full pipeline; audit log byte-identical | SATISFIED | `replay.py` drives full engine path; subprocess test confirms byte match; 3 tests pass |

---

## Human Verification Required

None — all must-haves are verified programmatically. The test suite (3 tests) passes with exit 0 confirming the byte-identical invariant holds end-to-end through the subprocess CLI path.

---

## Gaps Summary

No gaps. All six must-haves are verified at every level: artifacts exist, are substantive (not stubs), are correctly wired to their data sources, and the key behavioral probe (pytest subprocess test) passes with exit 0.

---

_Verified: 2026-05-20T22:00:00Z_
_Verifier: Claude (gsd-verifier)_
