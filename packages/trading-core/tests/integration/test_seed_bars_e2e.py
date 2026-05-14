"""End-to-end integration tests for `scripts/seed_bars.py` (MD-09).

These tests prove the seed CLI composes Plan 02 (Settings/logging) + Plan 03
(RthFilter/RolloverDetector) + Plan 04 (DuckDBStore/runs + TwelveDataSource)
into a working backfill pipeline. No network, no real DuckDB file — every
external surface is mocked or scoped to `tmp_path`.

Coverage:
    (a) Happy path: 390-row mocked /time_series → bars table has 390 rows,
        runs table has 1 row with status='ok' AND adr_hash matching
        sha256(.planning/decisions/0001-data-provider.md).
    (b) Idempotent re-run: second invocation = 2 runs rows, still 390 bars,
        and data_hash is identical across runs.
    (c) Partial-with-gaps: respx returns 385 of 390 bars → bar_gaps table
        has 5 rows AND CLI exits with the documented partial-status code.
    (d) Adapter failure (HTTP 429): CLI exits 1; runs row written with
        status='failed' and notes containing 'RateLimited'.

These tests are marked @pytest.mark.integration so the default unit-test
suite can opt in / out.

Plan 01-05 Task 2.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import duckdb
import pytest

_REPO_ROOT = Path(__file__).resolve().parents[4]
_SEED_SCRIPT = _REPO_ROOT / "scripts" / "seed_bars.py"
_ADR_PATH = _REPO_ROOT / ".planning" / "decisions" / "0001-data-provider.md"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_390_bar_payload(
    day: date = date(2024, 1, 2),
    *,
    drop_count: int = 0,
) -> dict:
    """Construct a Twelve Data /time_series response for the given trading day.

    The response is shaped exactly as Twelve Data Free tier returns it: a
    JSON dict with a `values` array of bar dicts (newest-first), each with
    `datetime`, `open`, `high`, `low`, `close`, `volume` string fields.

    Args:
        day: trading day (must be RTH-valid — 2024-01-02 (Tue) works).
        drop_count: how many bars to drop from the middle of the session
            (simulates an upstream gap). Default 0 = full 390-bar day.

    Returns:
        Twelve Data response dict.
    """
    # 9:30 ET on 2024-01-02 = 14:30 UTC (EST = UTC-5).
    start_utc = datetime(day.year, day.month, day.day, 14, 30, tzinfo=timezone.utc)
    bars = []
    total = 390
    # Indices to drop (drop from the middle to ensure RTH membership).
    drop_indices = set(range(200, 200 + drop_count)) if drop_count > 0 else set()
    for i in range(total):
        if i in drop_indices:
            continue
        ts = start_utc + timedelta(minutes=i)
        base = 470.0 + i * 0.01
        bars.append(
            {
                "datetime": ts.strftime("%Y-%m-%d %H:%M:%S"),
                "open": f"{base:.4f}",
                "high": f"{base + 0.05:.4f}",
                "low": f"{base - 0.05:.4f}",
                "close": f"{base + 0.02:.4f}",
                "volume": str(1000 + i),
            }
        )
    # Twelve Data returns newest-first by default.
    bars.reverse()
    return {
        "meta": {
            "symbol": "SPY",
            "interval": "1min",
            "currency": "USD",
            "exchange_timezone": "America/New_York",
            "exchange": "NASDAQ",
            "type": "Common Stock",
        },
        "values": bars,
        "status": "ok",
    }


def _adr_hash() -> str:
    """sha256 hex of the ADR contents — the canonical Phase 1 baseline."""
    return hashlib.sha256(_ADR_PATH.read_bytes()).hexdigest()


def _run_seed_bars(
    *,
    duckdb_path: Path,
    parquet_root: Path,
    audit_log_dir: Path,
    api_key: str = "FAKEKEY12345",
    extra_env: dict[str, str] | None = None,
    args: list[str] | None = None,
    twelvedata_mock: object | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run `scripts/seed_bars.py` as a subprocess with respx-mocked Twelve Data.

    The mock is set up in-process via a small bootstrap script appended to
    PYTHONPATH so the child process registers `respx.mock` around the
    httpx.AsyncClient before the adapter fires. Args default to the canonical
    happy-path command.
    """
    if args is None:
        args = [
            "--symbol",
            "SPY",
            "--tf",
            "1m",
            "--from",
            "2024-01-02",
            "--to",
            "2024-01-03",
            "--provider",
            "twelvedata",
        ]

    env = os.environ.copy()
    env["TWELVEDATA_API_KEY"] = api_key
    env["DUCKDB_PATH"] = str(duckdb_path)
    env["PARQUET_ROOT"] = str(parquet_root)
    env["AUDIT_LOG_DIR"] = str(audit_log_dir)
    env["PYTHONIOENCODING"] = "utf-8"
    if extra_env:
        env.update(extra_env)

    cmd = ["uv", "run", "python", str(_SEED_SCRIPT), *args]
    return subprocess.run(
        cmd,
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
        env=env,
    )


def _run_seed_bars_in_process(
    *,
    duckdb_path: Path,
    parquet_root: Path,
    audit_log_dir: Path,
    api_key: str = "FAKEKEY12345",
    mock_payload: dict | None = None,
    mock_status_code: int = 200,
    args_dict: dict | None = None,
) -> tuple[int, str]:
    """Invoke `seed_bars.main(args)` in-process with respx-mocked HTTP.

    Subprocess invocation cannot register respx in the child, so we exercise
    the same async pipeline in-process. Env writes are scoped to this call —
    pre-existing values are restored on exit so the wider test suite is not
    polluted (FAKEKEY12345 etc. must not leak into test_config or
    test_twelvedata_source).

    Returns:
        (exit_code, captured_stdout_or_stderr_text).
    """
    import asyncio
    import importlib
    import io
    from contextlib import redirect_stderr, redirect_stdout

    import httpx
    import respx

    # Capture pre-existing env values so we can restore them on exit. This
    # is what monkeypatch.setenv does, but we can't pass monkeypatch through
    # a helper — so we DIY scoped writes via try/finally.
    env_keys = (
        "TWELVEDATA_API_KEY",
        "DUCKDB_PATH",
        "PARQUET_ROOT",
        "AUDIT_LOG_DIR",
        "DEFAULT_PROVIDER",
    )
    prev_env: dict[str, str | None] = {
        k: os.environ.get(k) for k in env_keys
    }

    os.environ["TWELVEDATA_API_KEY"] = api_key
    os.environ["DUCKDB_PATH"] = str(duckdb_path)
    os.environ["PARQUET_ROOT"] = str(parquet_root)
    os.environ["AUDIT_LOG_DIR"] = str(audit_log_dir)
    os.environ["DEFAULT_PROVIDER"] = "twelvedata"

    try:
        # Re-import seed_bars to pick up fresh Settings. The module imports
        # Settings at module scope, but Settings() is constructed inside
        # main() — so a stale module reference is fine.
        if str(_SEED_SCRIPT.parent) not in sys.path:
            sys.path.insert(0, str(_SEED_SCRIPT.parent))
        import seed_bars as seed_bars_module  # type: ignore[import-not-found]

        importlib.reload(seed_bars_module)

        args = type("Args", (), {})()
        defaults = {
            "symbol": "SPY",
            "tf": "1m",
            "frm": datetime(2024, 1, 2, 0, 0, tzinfo=timezone.utc),
            "to": datetime(2024, 1, 3, 0, 0, tzinfo=timezone.utc),
            "provider": "twelvedata",
            "seed": 42,
            "duckdb_path": duckdb_path,
        }
        if args_dict:
            defaults.update(args_dict)
        for k, v in defaults.items():
            setattr(args, k, v)

        out_buf = io.StringIO()
        err_buf = io.StringIO()

        async def runner() -> int:
            with respx.mock(assert_all_called=False) as router:
                route = router.get(
                    url__startswith="https://api.twelvedata.com/time_series"
                )
                if mock_status_code == 429:
                    route.return_value = httpx.Response(
                        429,
                        json={"code": 429, "message": "ratelimited"},
                        headers={
                            "api-credits-left": "0",
                            "api-credits-used": "8",
                        },
                    )
                else:
                    route.return_value = httpx.Response(
                        mock_status_code,
                        json=mock_payload or _build_390_bar_payload(),
                        headers={
                            "api-credits-left": "7",
                            "api-credits-used": "1",
                        },
                    )
                return await seed_bars_module.main(args)

        with redirect_stdout(out_buf), redirect_stderr(err_buf):
            rc = asyncio.run(runner())

        return rc, out_buf.getvalue() + err_buf.getvalue()
    finally:
        # Restore pre-existing env (or delete if it wasn't set before).
        for k, original in prev_env.items():
            if original is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = original


# ---------------------------------------------------------------------------
# Pacing-sleep neutralization
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _no_pacing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch asyncio.sleep so the 9-second TwelveDataSource pacing is instant."""
    import asyncio as _asyncio

    real_sleep = _asyncio.sleep

    async def fast_sleep(delay: float, *args, **kwargs):  # noqa: ANN401
        if delay >= 1:
            return None
        return await real_sleep(delay, *args, **kwargs)

    monkeypatch.setattr(_asyncio, "sleep", fast_sleep)


@pytest.fixture(autouse=True)
def _isolate_logging(monkeypatch: pytest.MonkeyPatch):
    """Stub `setup_logging` to skip the global structlog/stdlib mutation.

    `seed_bars.main()` calls `setup_logging(audit_log_dir)` which configures
    structlog with `cache_logger_on_first_use=True` AND adds a
    ConcurrentRotatingFileHandler to the root logger. The cache flag causes
    `_log = structlog.get_logger(__name__)` references already evaluated in
    trading_core modules (e.g. data/twelvedata.py line 57) to PERMANENTLY
    cache a BoundLogger pointing at the post-setup pipeline. After cache,
    `structlog.testing.capture_logs()` cannot intercept anymore — breaking
    test_twelvedata_source / test_tradingview_source captures in any later
    test in the same pytest run.

    The Pitfall-5 UTF-8 stdout reconfigure runs at seed_bars.py script-entry
    time (above all imports), so skipping setup_logging in-process does
    NOT regress that defense. Subprocess invocations (test_help_exits_zero)
    still hit the real setup_logging because they go through __main__.

    Plan 01-05 Task 2 deviation: test-isolation safety net (Rule 3 -
    Blocker).
    """
    import logging

    import structlog

    # Snapshot for restoration.
    if structlog.is_configured():
        prev_config = structlog.get_config()
    else:
        prev_config = None
    root = logging.getLogger()
    prev_handlers = list(root.handlers)
    prev_level = root.level

    # Replace setup_logging with a tiny no-op stub that creates the audit
    # dir (the test asserts files / dirs exist below tmp_path in some cases)
    # but does NOT touch structlog config.
    def _noop_setup_logging(audit_dir):  # noqa: ANN001
        audit_dir.mkdir(parents=True, exist_ok=True)

    # Patch in the seed_bars module's namespace — the script does
    # `from trading_core.logging import setup_logging, get_logger`, so the
    # imported name lives in seed_bars's globals. We reload seed_bars per
    # test (helper does importlib.reload) so the patch must apply BEFORE
    # the reload — we set it on the source module too.
    monkeypatch.setattr(
        "trading_core.logging.setup_logging", _noop_setup_logging, raising=True
    )

    try:
        yield
    finally:
        # Restore root-logger state in case our no-op was bypassed.
        root.handlers = prev_handlers
        root.setLevel(prev_level)
        if prev_config is None:
            structlog.reset_defaults()
        else:
            structlog.configure(**prev_config)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestSeedBarsHappyPath:
    def test_happy_path_exit_0_390_bars_and_runs_row(
        self, tmp_path: Path
    ) -> None:
        duckdb_path = tmp_path / "test.duckdb"
        parquet_root = tmp_path / "parquet"
        audit_log_dir = tmp_path / "audit"
        parquet_root.mkdir(parents=True, exist_ok=True)
        audit_log_dir.mkdir(parents=True, exist_ok=True)

        rc, output = _run_seed_bars_in_process(
            duckdb_path=duckdb_path,
            parquet_root=parquet_root,
            audit_log_dir=audit_log_dir,
        )

        assert rc == 0, f"expected exit 0, got {rc}; output={output[:2000]}"

        # Check the DuckDB state.
        conn = duckdb.connect(str(duckdb_path), read_only=True)
        try:
            bars_count = conn.execute("SELECT COUNT(*) FROM bars").fetchone()[0]
            assert bars_count == 390, output[:1000]

            runs_rows = conn.execute(
                "SELECT run_id, git_sha, data_hash, param_hash, seed, "
                "adr_hash, started_at, finished_at, status, notes FROM runs"
            ).fetchall()
            assert len(runs_rows) == 1, output[:1000]
            run = runs_rows[0]
            (
                run_id,
                git_sha_value,
                data_hash_value,
                param_hash_value,
                seed_value,
                adr_hash_value,
                started_at,
                finished_at,
                status,
                notes,
            ) = run

            assert run_id, "run_id must be populated"
            assert git_sha_value, "git_sha must be populated"
            assert (
                data_hash_value
                and len(data_hash_value) == 64
            ), f"data_hash must be sha256 hex; got {data_hash_value!r}"
            assert (
                param_hash_value
                and len(param_hash_value) == 64
            ), f"param_hash must be sha256 hex; got {param_hash_value!r}"
            assert seed_value == 42
            assert adr_hash_value == _adr_hash(), (
                f"adr_hash mismatch — got {adr_hash_value!r}, "
                f"expected {_adr_hash()!r}"
            )
            assert started_at is not None
            assert finished_at is not None
            assert status == "ok", f"got status={status!r}; notes={notes!r}"
        finally:
            conn.close()


@pytest.mark.integration
class TestSeedBarsIdempotent:
    def test_rerun_zero_new_bars_same_data_hash(self, tmp_path: Path) -> None:
        duckdb_path = tmp_path / "test.duckdb"
        parquet_root = tmp_path / "parquet"
        audit_log_dir = tmp_path / "audit"
        parquet_root.mkdir(parents=True, exist_ok=True)
        audit_log_dir.mkdir(parents=True, exist_ok=True)

        rc1, _ = _run_seed_bars_in_process(
            duckdb_path=duckdb_path,
            parquet_root=parquet_root,
            audit_log_dir=audit_log_dir,
        )
        assert rc1 == 0

        rc2, _ = _run_seed_bars_in_process(
            duckdb_path=duckdb_path,
            parquet_root=parquet_root,
            audit_log_dir=audit_log_dir,
        )
        assert rc2 == 0

        conn = duckdb.connect(str(duckdb_path), read_only=True)
        try:
            bars_count = conn.execute("SELECT COUNT(*) FROM bars").fetchone()[0]
            assert bars_count == 390, "re-run must produce ZERO net new bars"

            data_hashes = conn.execute(
                "SELECT data_hash FROM runs ORDER BY started_at"
            ).fetchall()
            assert len(data_hashes) == 2, "two runs rows expected"
            assert data_hashes[0][0] == data_hashes[1][0], (
                "data_hash drift across idempotent re-runs"
            )
        finally:
            conn.close()


@pytest.mark.integration
class TestSeedBarsPartialGaps:
    def test_gaps_populated_and_exit_partial(self, tmp_path: Path) -> None:
        duckdb_path = tmp_path / "test.duckdb"
        parquet_root = tmp_path / "parquet"
        audit_log_dir = tmp_path / "audit"
        parquet_root.mkdir(parents=True, exist_ok=True)
        audit_log_dir.mkdir(parents=True, exist_ok=True)

        payload = _build_390_bar_payload(drop_count=5)
        rc, output = _run_seed_bars_in_process(
            duckdb_path=duckdb_path,
            parquet_root=parquet_root,
            audit_log_dir=audit_log_dir,
            mock_payload=payload,
        )

        # Exit 2 = partial per the plan's design decision (documented in
        # seed_bars.py's --help and in 01-05-SUMMARY.md).
        assert rc == 2, (
            f"expected exit 2 (partial), got {rc}; output={output[:2000]}"
        )

        conn = duckdb.connect(str(duckdb_path), read_only=True)
        try:
            bars_count = conn.execute("SELECT COUNT(*) FROM bars").fetchone()[0]
            assert bars_count == 385, "385 of 390 bars expected"
            gaps_count = conn.execute(
                "SELECT COUNT(*) FROM bar_gaps"
            ).fetchone()[0]
            assert gaps_count == 5, f"5 gaps expected, got {gaps_count}"

            status = conn.execute(
                "SELECT status FROM runs"
            ).fetchone()[0]
            assert status == "partial", f"runs.status should be 'partial', got {status!r}"
        finally:
            conn.close()


@pytest.mark.integration
class TestSeedBarsRateLimited:
    def test_429_exits_1_runs_row_status_failed(self, tmp_path: Path) -> None:
        duckdb_path = tmp_path / "test.duckdb"
        parquet_root = tmp_path / "parquet"
        audit_log_dir = tmp_path / "audit"
        parquet_root.mkdir(parents=True, exist_ok=True)
        audit_log_dir.mkdir(parents=True, exist_ok=True)

        rc, output = _run_seed_bars_in_process(
            duckdb_path=duckdb_path,
            parquet_root=parquet_root,
            audit_log_dir=audit_log_dir,
            mock_status_code=429,
        )

        assert rc == 1, (
            f"expected exit 1 (failure), got {rc}; output={output[:2000]}"
        )

        conn = duckdb.connect(str(duckdb_path), read_only=True)
        try:
            runs_row = conn.execute(
                "SELECT status, notes FROM runs"
            ).fetchone()
            assert runs_row is not None, (
                "runs row MUST be written even on adapter failure"
            )
            status, notes = runs_row
            assert status == "failed", f"got status={status!r}"
            assert "RateLimited" in notes, (
                f"notes should mention RateLimited; got {notes!r}"
            )
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# Subprocess --help smoke test (proves Pitfall-5 UTF-8 reconfigure works)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestSeedBarsCli:
    def test_help_exits_zero_and_lists_flags(self) -> None:
        """`python scripts/seed_bars.py --help` exits 0 and shows all flags."""
        result = subprocess.run(
            ["uv", "run", "python", str(_SEED_SCRIPT), "--help"],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        assert result.returncode == 0, (
            f"--help exited {result.returncode}; "
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        out = result.stdout
        for flag in ("--symbol", "--tf", "--from", "--to", "--provider", "--seed"):
            assert flag in out, f"--help missing {flag} in:\n{out}"
