"""Integration tests for scripts/run_opt.py CLI (OPT-04, OPT-05, OPT-08).

Tests:
    test_adr_gate_no_adr:          script exits 1 when no opt-*.md ADR exists
    test_adr_gate_missing_fields:  script exits 1 when ADR lacks required fields
    test_holdout_quota_exceeded:   4th burn in same quarter is refused (OPT-08)
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import duckdb
import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parent.parent.parent.parent.parent  # worktree root
_RUN_OPT_SCRIPT = _REPO_ROOT / "scripts" / "run_opt.py"


def _run_opt(*extra_args: str, cwd: Path | None = None, env_overrides: dict | None = None) -> subprocess.CompletedProcess:
    """Run scripts/run_opt.py as a subprocess and capture output.

    Uses sys.executable (already inside uv venv) so we don't need 'uv run'.
    Uses UTF-8 encoding explicitly to avoid Windows cp1252 decode errors (Pitfall 5).
    """
    import os
    env = os.environ.copy()
    # Force UTF-8 output from the subprocess on Windows
    env["PYTHONIOENCODING"] = "utf-8"
    if env_overrides:
        env.update(env_overrides)

    cmd = [sys.executable, str(_RUN_OPT_SCRIPT), *extra_args]
    return subprocess.run(
        cmd,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(cwd or _REPO_ROOT),
        env=env,
        timeout=30,
    )


# ---------------------------------------------------------------------------
# ADR Gate tests (D-09 / OPT-04)
# ---------------------------------------------------------------------------


class TestAdrGate:
    """run_opt.py refuses to start without a committed opt-*.md ADR."""

    def test_adr_gate_no_adr(self, tmp_path: Path):
        """Script exits 1 when the .planning/decisions/ dir has no opt-*.md file.

        Strategy: subprocess with GSD_OPT_REPO_ROOT=tmp_path so the ADR gate
        looks in tmp_path/.planning/decisions/ (which has no opt-*.md files).
        """
        # Create the planning/decisions directory structure but no opt-*.md
        decisions_dir = tmp_path / ".planning" / "decisions"
        decisions_dir.mkdir(parents=True)

        # Override GSD_OPT_REPO_ROOT so the ADR gate scans tmp_path, not the real repo
        result = _run_opt(
            "--space", "config/strategies/orb.optspace.yaml",
            "--symbol", "SPY",
            "--tf", "1m",
            "--from", "2024-01-01",
            "--to", "2024-06-01",
            env_overrides={"GSD_OPT_REPO_ROOT": str(tmp_path)},
        )

        assert result.returncode == 1, (
            f"Expected exit code 1, got {result.returncode}.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "No optimization ADR" in result.stderr or "No optimization ADR" in result.stdout, (
            f"Expected 'No optimization ADR' error message.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_adr_gate_missing_fields(self, tmp_path: Path):
        """Script exits 1 when opt-*.md exists but lacks required fields.

        Creates opt-0001-test.md missing 'is_oos_split' — verifies the field
        is listed in the error output.
        """
        decisions_dir = tmp_path / ".planning" / "decisions"
        decisions_dir.mkdir(parents=True)

        # ADR missing 'is_oos_split' field
        adr_content = """# Optimization ADR — Test

## Decision

| Field | Value |
|-------|-------|
| `optspace_path` | config/strategies/orb.optspace.yaml |
| `objective` | oos_sharpe |
| `seed` | 42 |
"""
        (decisions_dir / "opt-0001-test.md").write_text(adr_content, encoding="utf-8")

        result = _run_opt(
            "--space", "config/strategies/orb.optspace.yaml",
            "--symbol", "SPY",
            "--tf", "1m",
            "--from", "2024-01-01",
            "--to", "2024-06-01",
            env_overrides={"GSD_OPT_REPO_ROOT": str(tmp_path)},
        )

        assert result.returncode == 1, (
            f"Expected exit code 1, got {result.returncode}.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        # Should mention the missing field
        combined_output = result.stdout + result.stderr
        assert "is_oos_split" in combined_output, (
            f"Expected 'is_oos_split' in error output.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_adr_gate_valid_adr(self, tmp_path: Path):
        """Script proceeds past ADR gate when ADR has all required fields.

        Note: script will fail AFTER the ADR gate (e.g., missing space file or
        DuckDB error), but the ADR gate itself passes. We verify exit!=1 due to ADR.
        """
        decisions_dir = tmp_path / ".planning" / "decisions"
        decisions_dir.mkdir(parents=True)

        # Valid ADR with all required fields
        adr_content = """# Optimization ADR — Test Run

## Decision

| Field | Value |
|-------|-------|
| `is_oos_split` | IS=6m OOS=1m rolling step=1m |
| `optspace_path` | config/strategies/orb.optspace.yaml |
| `objective` | oos_sharpe |
| `seed` | 42 |
"""
        (decisions_dir / "opt-0001-valid.md").write_text(adr_content, encoding="utf-8")

        result = _run_opt(
            "--space", "config/strategies/orb.optspace.yaml",
            "--symbol", "SPY",
            "--tf", "1m",
            "--from", "2024-01-01",
            "--to", "2024-06-01",
            env_overrides={"GSD_OPT_REPO_ROOT": str(tmp_path)},
        )

        # Should NOT produce the "No optimization ADR" error
        combined_output = result.stdout + result.stderr
        assert "No optimization ADR" not in combined_output, (
            f"Script should pass ADR gate when valid ADR exists.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "is_oos_split" not in combined_output or "missing" not in combined_output.lower(), (
            f"Script should not report missing is_oos_split.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )


# ---------------------------------------------------------------------------
# Holdout quota tests (D-10 / OPT-08)
# ---------------------------------------------------------------------------


class TestHoldoutQuota:
    """Holdout burn quota: at most 3 burns per calendar quarter."""

    def test_holdout_quota_three_allowed(self, tmp_path: Path):
        """3rd burn succeeds: check_holdout_quota returns True for count < 3."""
        from trading_core.storage.duckdb_store import DuckDBStore  # noqa: PLC0415
        from trading_core.storage.runs import new_run_id  # noqa: PLC0415

        db_path = tmp_path / "test.duckdb"
        store = DuckDBStore(db_path)
        store.ensure_schema()

        quarter = "2026Q2"
        # Insert 2 burns
        store.write_holdout_burn(burn_id=new_run_id(), run_id=new_run_id(), quarter=quarter)
        store.write_holdout_burn(burn_id=new_run_id(), run_id=new_run_id(), quarter=quarter)

        # 2 burns → quota allows a 3rd
        assert store.check_holdout_quota(quarter) is True, (
            "With 2 burns, the 3rd should be allowed"
        )

        # Insert 3rd burn
        store.write_holdout_burn(burn_id=new_run_id(), run_id=new_run_id(), quarter=quarter)

        # 3 burns → quota exhausted (4th refused)
        assert store.check_holdout_quota(quarter) is False, (
            "With 3 burns, the 4th should be refused"
        )
        store.close()

    def test_holdout_quota_exceeded(self, tmp_path: Path):
        """After 3 burns, check_holdout_quota returns False (4th burn refused).

        This is the canonical OPT-08 test: 4th burn within a quarter is refused.
        """
        from trading_core.storage.duckdb_store import DuckDBStore  # noqa: PLC0415
        from trading_core.storage.runs import new_run_id  # noqa: PLC0415

        db_path = tmp_path / "test_quota.duckdb"
        store = DuckDBStore(db_path)
        store.ensure_schema()

        quarter = "2026Q2"
        # Insert exactly 3 burns
        for _ in range(3):
            store.write_holdout_burn(burn_id=new_run_id(), run_id=new_run_id(), quarter=quarter)

        # 4th burn must be refused
        allowed = store.check_holdout_quota(quarter)
        assert allowed is False, (
            f"Expected 4th burn to be refused (quota=3), but check_holdout_quota returned {allowed}"
        )
        store.close()

    def test_holdout_quota_different_quarters(self, tmp_path: Path):
        """Burns in different quarters do not count against each other."""
        from trading_core.storage.duckdb_store import DuckDBStore  # noqa: PLC0415
        from trading_core.storage.runs import new_run_id  # noqa: PLC0415

        db_path = tmp_path / "test_quarters.duckdb"
        store = DuckDBStore(db_path)
        store.ensure_schema()

        # Insert 3 burns in Q1
        for _ in range(3):
            store.write_holdout_burn(burn_id=new_run_id(), run_id=new_run_id(), quarter="2026Q1")

        # Q2 should still have full quota (0 burns in Q2)
        assert store.check_holdout_quota("2026Q2") is True, (
            "Quota in Q2 should be fresh even if Q1 is exhausted"
        )
        store.close()

    def test_holdout_quota_zero_burns(self, tmp_path: Path):
        """With 0 burns, quota allows a burn."""
        from trading_core.storage.duckdb_store import DuckDBStore  # noqa: PLC0415

        db_path = tmp_path / "test_zero.duckdb"
        store = DuckDBStore(db_path)
        store.ensure_schema()

        assert store.check_holdout_quota("2026Q3") is True, (
            "With 0 burns, quota should allow a burn"
        )
        store.close()


# ---------------------------------------------------------------------------
# CLI help test (smoke test)
# ---------------------------------------------------------------------------


class TestCliHelp:
    """run_opt.py --help exits 0 and shows key flags."""

    def test_help_exits_zero(self):
        """--help exits 0."""
        result = _run_opt("--help")
        assert result.returncode == 0, (
            f"Expected exit code 0 for --help.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_help_shows_space_flag(self):
        """--help output shows --space flag."""
        result = _run_opt("--help")
        assert "--space" in result.stdout, (
            f"Expected --space in --help output.\nstdout: {result.stdout}"
        )

    def test_help_shows_burn_holdout_flag(self):
        """--help output shows --burn-holdout flag."""
        result = _run_opt("--help")
        assert "--burn-holdout" in result.stdout, (
            f"Expected --burn-holdout in --help output.\nstdout: {result.stdout}"
        )
