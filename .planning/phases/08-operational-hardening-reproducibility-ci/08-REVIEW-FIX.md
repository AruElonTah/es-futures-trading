---
phase: 08-operational-hardening-reproducibility-ci
fixed_at: 2026-05-20T00:00:00Z
review_path: .planning/phases/08-operational-hardening-reproducibility-ci/08-REVIEW.md
iteration: 1
findings_in_scope: 9
fixed: 9
skipped: 0
status: all_fixed
---

# Phase 08: Code Review Fix Report

**Fixed at:** 2026-05-20T00:00:00Z
**Source review:** `.planning/phases/08-operational-hardening-reproducibility-ci/08-REVIEW.md`
**Iteration:** 1

**Summary:**
- Findings in scope: 9 (3 Critical + 6 Warning; 3 Info findings excluded per fix_scope=critical_warning)
- Fixed: 9
- Skipped: 0

## Fixed Issues

### CR-01: Output CSV file handle not closed on exception in `replay.py`

**Files modified:** `scripts/replay.py`
**Commit:** `9fc9d49`
**Applied fix:** Replaced the explicit `output_csv_fh = output_csv_path.open(...)` / `flush()` / `close()` pattern with a `with output_csv_path.open(...) as output_csv_fh:` block that wraps the entire bar-by-bar loop and all event-writing code (lines 248-444). The `flush()` and `close()` calls were removed since the context manager's `__exit__` handles both. This ensures the file handle is always closed, even when an exception is raised during replay.

---

### CR-02: `open_exposure` calculation uses stale `bar.close` instead of fill price

**Files modified:** `scripts/replay.py`, `scripts/gen_golden.py`, `packages/trading-core/tests/integration/test_replay_audit_log.py`
**Commit:** `25d4e14`
**Applied fix:** Replaced the incorrect `open_exposure = (bar.close - entry_fill.fill_price) * qty` calculation with `open_exposure_dollars=Decimal("0")` in all three copies of the replay loop. At the instant of fill, unrealized P&L is zero by definition — the mark-to-market exposure only begins accruing on subsequent bar closes. The stale `bar.close` value (from the signal bar, one bar prior to fill) was producing an incorrect and potentially negative initial exposure value.

**Note: requires human verification of logic correctness** — the choice of zero vs. marking to `next_bar.close` depends on intended semantics. The REVIEW.md recommends zero as the correct initial value.

---

### CR-03: CI workflow has no Python version pin

**Files modified:** `.github/workflows/ci.yml`
**Commit:** `3879ad1`
**Applied fix:** Added `python-version: "3.12"` and `uv-version: "0.11.14"` to the `astral-sh/setup-uv@v5` step in the `python-tests` job. Added `actions/setup-node@v4` with `node-version: "20"` to the `frontend-tests` job before the `pnpm/action-setup` step. This ensures reproducible Python and Node.js environments aligned with CLAUDE.md requirements.

---

### WR-01: `subprocess.run` in CI test has no timeout

**Files modified:** `packages/trading-core/tests/integration/test_replay_audit_log.py`
**Commit:** `e676af7`
**Applied fix:** Added `timeout=120` to the `subprocess.run()` call in `test_replay_cli_subprocess_matches_golden`. The test now raises `subprocess.TimeoutExpired` after 2 minutes if `replay.py` deadlocks, preventing the CI job from hanging indefinitely.

---

### WR-02: `backup.ps1` uses `CreationTime` for retention pruning

**Files modified:** `scripts/backup.ps1`
**Commit:** `f5b8b76`
**Applied fix:** Replaced the `Where-Object { $_.CreationTime -lt ... }` retention filter with a `[datetime]::TryParseExact` parse of the directory name (`yyyy-MM-dd` format). Directories whose names cannot be parsed as a date are left untouched (`$false` branch). This makes the retention logic reliable after xcopy, robocopy, OneDrive restores, and drive migrations which reset `CreationTime`.

---

### WR-03: `gen_golden.py` `print` statements reference `_counters` after `with` block

**Files modified:** `scripts/gen_golden.py`
**Commit:** `2f5815b`
**Applied fix:** Moved the two `print(f"...")` statements from after the `with tempfile.TemporaryDirectory` block to inside it (after `store.close()` in the `finally` block). Removed the redundant `fh.flush()` call inside the `with output_csv_fh` block — the context manager's `__exit__` already flushes and closes the file.

---

### WR-04: Dead `import pandas as pd_` in test file

**Files modified:** `packages/trading-core/tests/integration/test_replay_audit_log.py`
**Commit:** `f1ce6eb`
**Applied fix:** Removed the `import pandas as pd_  # noqa: PLC0415, F401 (needed for type)` line entirely. The `pd_` alias was unused — no type annotation or code in the function referenced it. The `# noqa: F401` suppression was masking the linter signal.

---

### WR-05: `conftest.py` `sys.path` mutation is not at top of file

**Files modified:** `packages/trading-core/tests/conftest.py`
**Commit:** `7daa620`
**Applied fix:** Moved the `_TESTS_DIR` / `sys.path.insert` block to immediately after the stdlib imports (`import sys`, `from pathlib import Path`) — before the `pytest_addoption` function definition and before `import pytest` / `from trading_core.instruments import ...`. Added `# noqa: E402` to the `import pytest` and `from trading_core.instruments` lines since they now legitimately follow a `sys.path` mutation.

---

### WR-06: `replay.py` accesses private `store._conn` directly

**Files modified:** `scripts/replay.py`, `packages/trading-core/src/trading_core/storage/duckdb_store.py`
**Commit:** `9d71fe4`
**Applied fix:** Added a `query_bars(symbol, timeframe, frm, to) -> pd.DataFrame` public method to `DuckDBStore` that encapsulates the parameterized bars SELECT query. Updated `replay.py` to call `store.query_bars(args.symbol, args.tf, args.frm, args.to)` instead of `store._conn.execute(...)`. The new method preserves all T-08-01 parameterized-binding safety guarantees.

---

## Skipped Issues

None — all 9 in-scope findings were fixed.

## Info Findings (excluded by fix_scope)

The following findings were excluded from the fix run per `fix_scope=critical_warning`:

- **IN-01:** Hard-coded path in `docs/operations/backup.md` — documentation note needed
- **IN-02:** `gen_golden.py` has no `--dry-run` or confirmation guard — feature request
- **IN-03:** CI frontend job does not pin Node.js version — partially addressed by CR-03 fix (Node.js 20 added to frontend job)

---

_Fixed: 2026-05-20T00:00:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
