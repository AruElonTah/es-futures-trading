"""Pre-commit hook integration tests (FND-04 gitleaks + FND-05 no-naive-tz).

These tests gate the two pre-commit hooks that future commits will be
subject to. Plan 01-05 Task 1.

Coverage:
- The local no-naive-tz hook rejects a Python file with bare `datetime.now()`
  / `datetime.utcnow()` calls and accepts a clean file.
- gitleaks (run via the `pre-commit run gitleaks --files ...` shim) rejects a
  fixture file containing a synthetic 32-char hex API key.
- gitleaks (run via `pre-commit run gitleaks --all-files`) accepts the
  current repo — i.e., the `.gitleaks.toml` allowlist correctly whitelists the
  `<TWELVEDATA_API_KEY>` Phase 0 sentinel in `.env.example` and
  `.planning/research/spike-0/twelvedata-probe.json` (Pitfall 7).

Per the plan's <action>: parts (a) and (b) call the AST scanner in-process
for speed; parts (c) and (d) shell out to `pre-commit run` because they
exercise the gitleaks integration. The pre-commit tests are marked
`integration` so the default unit-test suite can opt in / out.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[4]
_HOOK_SCRIPT = _REPO_ROOT / "scripts" / "hooks" / "no_naive_tz.py"
_BAD_NAIVE = (
    _REPO_ROOT
    / "packages"
    / "trading-core"
    / "tests"
    / "fixtures"
    / "bad_naive_datetime.py"
)
_BAD_API_KEY = (
    _REPO_ROOT
    / "packages"
    / "trading-core"
    / "tests"
    / "fixtures"
    / "bad_api_key.py"
)


# ---------------------------------------------------------------------------
# no-naive-tz — in-process AST scanner (fast)
# ---------------------------------------------------------------------------


def _run_hook(*paths: Path) -> subprocess.CompletedProcess[str]:
    """Invoke `python scripts/hooks/no_naive_tz.py <paths...>` as a subprocess."""
    return subprocess.run(
        [sys.executable, str(_HOOK_SCRIPT), *(str(p) for p in paths)],
        capture_output=True,
        text=True,
        check=False,
    )


class TestNoNaiveTzHook:
    def test_rejects_naive_datetime_now(self, tmp_path: Path) -> None:
        """A file with `datetime.now()` (no tz=) must exit 1."""
        f = tmp_path / "bad.py"
        f.write_text(
            "from datetime import datetime\n"
            "def bad():\n"
            "    return datetime.now()\n",
            encoding="utf-8",
        )
        result = _run_hook(f)
        assert result.returncode == 1, result.stdout + result.stderr
        assert "datetime.now() without tz=" in result.stdout

    def test_rejects_datetime_utcnow(self, tmp_path: Path) -> None:
        """A file with `datetime.utcnow()` (deprecated + naive) must exit 1."""
        f = tmp_path / "bad.py"
        f.write_text(
            "from datetime import datetime\n"
            "def bad():\n"
            "    return datetime.utcnow()\n",
            encoding="utf-8",
        )
        result = _run_hook(f)
        assert result.returncode == 1, result.stdout + result.stderr
        # The hook should mention utcnow in the diagnostic.
        assert "utcnow" in result.stdout

    def test_rejects_both_violations_in_fixture(self) -> None:
        """The committed fixture must be rejected by the hook (two violations)."""
        result = _run_hook(_BAD_NAIVE)
        assert result.returncode == 1, result.stdout + result.stderr
        # Two violations, two output lines.
        out_lines = [
            line
            for line in result.stdout.splitlines()
            if "datetime" in line and ".py:" in line
        ]
        assert len(out_lines) >= 2, result.stdout

    def test_accepts_tz_aware_now(self, tmp_path: Path) -> None:
        """`datetime.now(tz=timezone.utc)` must NOT trigger."""
        f = tmp_path / "ok.py"
        f.write_text(
            "from datetime import datetime, timezone\n"
            "def ok():\n"
            "    return datetime.now(tz=timezone.utc)\n",
            encoding="utf-8",
        )
        result = _run_hook(f)
        assert result.returncode == 0, result.stdout + result.stderr

    def test_accepts_tz_positional(self, tmp_path: Path) -> None:
        """`datetime.now(timezone.utc)` (positional) must NOT trigger."""
        f = tmp_path / "ok.py"
        f.write_text(
            "from datetime import datetime, timezone\n"
            "def ok():\n"
            "    return datetime.now(timezone.utc)\n",
            encoding="utf-8",
        )
        result = _run_hook(f)
        assert result.returncode == 0, result.stdout + result.stderr

    def test_ignores_datetime_in_comment(self, tmp_path: Path) -> None:
        """A comment mentioning `datetime.now()` must NOT trigger (AST > regex)."""
        f = tmp_path / "ok.py"
        f.write_text(
            "# comment about datetime.now() being naive\n"
            "def ok():\n"
            "    return 1\n",
            encoding="utf-8",
        )
        result = _run_hook(f)
        assert result.returncode == 0, result.stdout + result.stderr

    def test_ignores_datetime_in_docstring(self, tmp_path: Path) -> None:
        """A docstring mentioning `datetime.now()` must NOT trigger."""
        f = tmp_path / "ok.py"
        f.write_text(
            '"""Module docstring mentioning datetime.now()."""\n'
            "def ok():\n"
            "    return 1\n",
            encoding="utf-8",
        )
        result = _run_hook(f)
        assert result.returncode == 0, result.stdout + result.stderr

    def test_clean_file_exits_zero(self, tmp_path: Path) -> None:
        """A plain Python file with no datetime calls must exit 0."""
        f = tmp_path / "ok.py"
        f.write_text("def ok():\n    return 1\n", encoding="utf-8")
        result = _run_hook(f)
        assert result.returncode == 0, result.stdout + result.stderr


# ---------------------------------------------------------------------------
# pre-commit + gitleaks integration — slower; gated as integration tests
# ---------------------------------------------------------------------------


def _have_precommit() -> bool:
    """Probe whether `pre-commit` is on PATH (via uv run)."""
    try:
        subprocess.run(
            ["uv", "run", "pre-commit", "--version"],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return False


@pytest.mark.integration
class TestPreCommitFramework:
    """Subprocess-driven pre-commit invocations.

    These tests are slow (gitleaks must be fetched + initialized on first
    run). They are marked `integration` so they can be skipped via
    `pytest -m "not integration"`.
    """

    def test_no_naive_tz_hook_via_precommit(self, tmp_path: Path) -> None:
        """`pre-commit run no-naive-tz --files <bad>` must reject."""
        if not _have_precommit():
            pytest.skip("pre-commit not on PATH")
        result = subprocess.run(
            [
                "uv",
                "run",
                "pre-commit",
                "run",
                "no-naive-tz",
                "--files",
                str(_BAD_NAIVE),
            ],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=180,
        )
        # Non-zero exit = hook rejected the file.
        assert result.returncode != 0, result.stdout + result.stderr

    def test_gitleaks_rejects_bad_api_key(self, tmp_path: Path) -> None:
        """`pre-commit run gitleaks --files <bad_api_key>` must exit non-zero."""
        if not _have_precommit():
            pytest.skip("pre-commit not on PATH")
        result = subprocess.run(
            [
                "uv",
                "run",
                "pre-commit",
                "run",
                "gitleaks",
                "--files",
                str(_BAD_API_KEY),
            ],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=300,
        )
        assert result.returncode != 0, (
            "gitleaks should have rejected the synthetic API key fixture; "
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )

    def test_gitleaks_allows_existing_repo(self) -> None:
        """`pre-commit run gitleaks --all-files` exits 0 — allowlist works."""
        if not _have_precommit():
            pytest.skip("pre-commit not on PATH")
        # Exclude the deliberately-bad fixture from the all-files scan.
        # `pre-commit run --all-files` reads from git ls-files, so the
        # bad_api_key.py fixture WILL be included if it's staged. We solve
        # this with a path-level allowlist for the fixture in .gitleaks.toml.
        result = subprocess.run(
            [
                "uv",
                "run",
                "pre-commit",
                "run",
                "gitleaks",
                "--all-files",
            ],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=300,
        )
        assert result.returncode == 0, (
            "gitleaks should accept the current repo "
            "(<TWELVEDATA_API_KEY> sentinel must be allowlisted; "
            "bad_api_key.py fixture must be path-allowlisted).\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
