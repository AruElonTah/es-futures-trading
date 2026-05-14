"""Pre-commit hook integration tests (FND-04 gitleaks + FND-05 no-naive-tz).

These tests gate the two pre-commit hooks that future commits will be
subject to. Plan 01-05 Task 1.

Coverage:
- The local no-naive-tz hook rejects a Python file with bare `datetime.now()`
  / `datetime.utcnow()` calls and accepts a clean file.
- `pre-commit run no-naive-tz --files <bad>` rejects the bad fixture (full
  pre-commit-framework round-trip).
- gitleaks rejects a fixture file containing a synthetic 32-char hex API key
  (invoked directly via the gitleaks binary because the pre-commit gitleaks
  hook's entry is `gitleaks git --pre-commit --staged --verbose` — it only
  scans STAGED content, so `pre-commit run --files <bad>` returns vacuous
  Passed if the file isn't staged; the gitleaks rule is what we're really
  validating).
- gitleaks accepts the current repo's working tree against `.gitleaks.toml`
  (invoked directly via the gitleaks binary in `--no-git --source .` mode).
  This proves the `<TWELVEDATA_API_KEY>` Phase 0 sentinel allowlist works
  (Pitfall 7) — without it gitleaks would flag the literal in `.env.example`
  and `.planning/research/spike-0/twelvedata-probe.json`.

Plan-action note: the plan's <action> said `pre-commit run gitleaks --files`
and `pre-commit run gitleaks --all-files`. We discovered during execution
that pre-commit's bundled `gitleaks` entry runs `gitleaks git --pre-commit
--staged --verbose` — it consults the git INDEX, not the file content
pre-commit passes via --files. That makes both invocations vacuously Pass
unless the fixture is staged. The semantic intent — proving the gitleaks
RULE rejects the synthetic key AND the allowlist suppresses sentinel
false-positives — is preserved by calling the cached gitleaks binary
directly (`pre-commit run --files` populated the binary cache as a side
effect during the no-naive-tz test above).
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


def _find_gitleaks_binary() -> Path | None:
    """Locate the gitleaks executable cached by pre-commit (if any).

    The pre-commit framework downloads gitleaks into
    `~/.cache/pre-commit/repo*/golangenv-default/bin/gitleaks(.exe)` after
    its first invocation. Returns None if no cached binary is found yet.
    """
    cache_root = Path.home() / ".cache" / "pre-commit"
    if not cache_root.exists():
        return None
    candidates = list(cache_root.glob("repo*/golangenv-default/bin/gitleaks*"))
    candidates = [p for p in candidates if p.is_file()]
    if not candidates:
        return None
    # Prefer .exe on Windows.
    for p in candidates:
        if p.name.lower().startswith("gitleaks") and p.suffix.lower() == ".exe":
            return p
    return candidates[0]


@pytest.mark.integration
class TestPreCommitFramework:
    """Subprocess-driven pre-commit + gitleaks invocations.

    These tests are slow (gitleaks must be fetched + initialized on first
    run). They are marked `integration` so they can be skipped via
    `pytest -m "not integration"`.
    """

    def test_no_naive_tz_hook_via_precommit(self, tmp_path: Path) -> None:
        """`pre-commit run no-naive-tz --files <bad-not-fixture>` must reject.

        The committed `bad_naive_datetime.py` fixture is excluded from the
        hook in `.pre-commit-config.yaml` (so `pre-commit run --all-files`
        is green per the plan's success criterion). To exercise the
        framework -> hook -> rejection round-trip we use a freshly written
        temp file with the same shape — pre-commit's `exclude` regex does
        NOT match the tmp path.
        """
        if not _have_precommit():
            pytest.skip("pre-commit not on PATH")
        bad_tmp = tmp_path / "bad_via_precommit.py"
        bad_tmp.write_text(
            "from datetime import datetime\n"
            "def bad():\n"
            "    return datetime.now()\n",
            encoding="utf-8",
        )
        result = subprocess.run(
            [
                "uv",
                "run",
                "pre-commit",
                "run",
                "no-naive-tz",
                "--files",
                str(bad_tmp),
            ],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=180,
        )
        # Non-zero exit = hook rejected the file.
        assert result.returncode != 0, result.stdout + result.stderr

    def test_gitleaks_binary_rejects_bad_api_key(self) -> None:
        """The gitleaks RULE flags the synthetic 32-char hex key in the fixture.

        Invoked directly via the gitleaks binary (`--no-git --source <bad>`)
        because the pre-commit gitleaks entry is `gitleaks git --staged`,
        which only scans the git index — not file content given via --files.
        """
        binary = _find_gitleaks_binary()
        if binary is None:
            pytest.skip(
                "gitleaks binary not yet cached by pre-commit; "
                "run `uv run pre-commit run --all-files` once to populate"
            )
        result = subprocess.run(
            [
                str(binary),
                "detect",
                "--no-banner",
                "--no-git",
                "--source",
                str(_BAD_API_KEY),
            ],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
        assert result.returncode != 0, (
            "gitleaks should have rejected the synthetic API key fixture; "
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        # Sanity: the diagnostic should mention generic-api-key (gitleaks's
        # rule for high-entropy strings assigned to API-like variable names).
        combined = (result.stdout + result.stderr).lower()
        assert "leak" in combined or "secret" in combined or "finding" in combined, (
            f"gitleaks output did not mention a finding: {combined!r}"
        )

    def test_gitleaks_allowlist_suppresses_sentinel(self) -> None:
        """Working-tree scan honors `.gitleaks.toml` allowlist for the sentinel.

        Scans `.env.example` + `.planning/research/spike-0/twelvedata-probe.json`
        — both contain the literal `<TWELVEDATA_API_KEY>` Phase 0 sentinel —
        and asserts gitleaks does NOT fire. Without the allowlist, gitleaks's
        generic-api-key heuristic would flag both.
        """
        binary = _find_gitleaks_binary()
        if binary is None:
            pytest.skip(
                "gitleaks binary not yet cached by pre-commit; "
                "run `uv run pre-commit run --all-files` once to populate"
            )
        gitleaks_toml = _REPO_ROOT / ".gitleaks.toml"
        assert gitleaks_toml.exists(), (
            f"{gitleaks_toml} must exist for the allowlist to be honored"
        )

        # Scan the two sentinel-bearing paths together. gitleaks `--source`
        # accepts a single path, so we run it twice and assert both green.
        for sentinel_path in (
            _REPO_ROOT / ".env.example",
            _REPO_ROOT
            / ".planning"
            / "research"
            / "spike-0"
            / "twelvedata-probe.json",
        ):
            if not sentinel_path.exists():
                pytest.skip(f"sentinel artifact missing: {sentinel_path}")
            result = subprocess.run(
                [
                    str(binary),
                    "detect",
                    "--no-banner",
                    "--no-git",
                    "--config",
                    str(gitleaks_toml),
                    "--source",
                    str(sentinel_path),
                ],
                cwd=_REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
                timeout=120,
            )
            assert result.returncode == 0, (
                f"gitleaks should allowlist <TWELVEDATA_API_KEY> in {sentinel_path}; "
                f"stdout={result.stdout!r} stderr={result.stderr!r}"
            )
