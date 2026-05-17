"""Unit tests for trading_core.optimization.worker (OPT-02, T-04-02-01).

Tests:
    test_worker_importable: run_combo is importable as a module-level callable.
    test_worker_no_api_import: worker.py source has no api/tv_bridge imports (D-07/T-04-02-01).
    test_run_combo_returns_list: run_combo returns list[dict] over synthetic bar fold.
    test_fold_result_shape: each result dict has required keys.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import duckdb
import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_WORKER_SRC = (
    Path(__file__).parent.parent.parent
    / "src"
    / "trading_core"
    / "optimization"
    / "worker.py"
)


def _make_synthetic_bars_db(tmp_path: Path) -> Path:
    """Create a tiny DuckDB file with 2 synthetic ORB days (780 bars total).

    Days: 2024-01-02 and 2024-01-03 (both EST days, RTH 14:30-21:00 UTC).
    Returns the path to the .duckdb file.
    """
    from datetime import datetime, timezone
    from decimal import Decimal

    import duckdb
    import pandas as pd

    db_path = tmp_path / "test_bars.duckdb"
    conn = duckdb.connect(str(db_path))

    # Create bars table matching schema.sql
    conn.execute("""
        CREATE TABLE IF NOT EXISTS bars (
            symbol        VARCHAR     NOT NULL,
            timeframe     VARCHAR     NOT NULL,
            ts_utc        TIMESTAMPTZ NOT NULL,
            open          DOUBLE      NOT NULL,
            high          DOUBLE      NOT NULL,
            low           DOUBLE      NOT NULL,
            close         DOUBLE      NOT NULL,
            volume        BIGINT      NOT NULL,
            rollover_seam BOOLEAN     NOT NULL DEFAULT FALSE,
            provider      VARCHAR     NOT NULL DEFAULT 'test',
            ingested_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (symbol, timeframe, ts_utc)
        )
    """)

    rows = []
    for day_str in ["2024-01-02", "2024-01-03"]:
        year, month, day = (int(x) for x in day_str.split("-"))
        open_utc = datetime(year, month, day, 14, 30, tzinfo=timezone.utc)
        timestamps = pd.date_range(open_utc, periods=390, freq="1min", tz="UTC")
        for i, ts in enumerate(timestamps):
            if i < 15:
                o, h, l, c = 471.0, 471.0, 470.5, 470.75
            elif i == 15:
                o, h, l, c = 471.0, 471.5, 471.0, 471.25
            else:
                o, h, l, c = 471.25, 471.5, 471.0, 471.25
            rows.append(("SPY", "1m", ts.to_pydatetime(), o, h, l, c, 1000, False, "test"))

    conn.executemany(
        "INSERT INTO bars (symbol, timeframe, ts_utc, open, high, low, close, volume, rollover_seam, provider) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.close()
    return db_path


def _make_single_fold(db_path: Path) -> list[dict]:
    """Build a single IS/OOS fold boundary covering our 2 synthetic days."""
    # IS covers day 1, OOS covers day 2 — minimal valid fold
    return [
        {
            "fold_idx": 0,
            "is_start": "2024-01-02",
            "is_end": "2024-01-02",
            "oos_start": "2024-01-03",
            "oos_end": "2024-01-03",
        }
    ]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestWorkerImportable:
    """OPT-02: run_combo must be a module-level callable importable by workers."""

    def test_worker_importable(self):
        """run_combo is importable and callable (not nested in __main__ or closure)."""
        from trading_core.optimization.worker import run_combo  # noqa: PLC0415

        assert callable(run_combo), "run_combo must be callable"

    def test_run_combo_is_module_level(self):
        """run_combo is defined at module level (not inside a class or function)."""
        from trading_core.optimization import worker  # noqa: PLC0415
        from trading_core.optimization.worker import run_combo  # noqa: PLC0415

        # Module-level means it's directly in the module's __dict__
        assert "run_combo" in dir(worker), "run_combo must be in module namespace"
        # And it must be a plain function, not a bound method or partial
        assert inspect.isfunction(run_combo), "run_combo must be a plain function"


class TestWorkerNoApiImport:
    """T-04-02-01 / D-07: workers import only trading-core, never api or tv_bridge."""

    def test_worker_no_api_import(self):
        """worker.py source must not have an 'import api' or 'from api' statement."""
        import re  # noqa: PLC0415
        source = _WORKER_SRC.read_text(encoding="utf-8")
        # Match actual Python import statements: "import api" or "from api import ..."
        # Use regex to avoid matching comments like "# must never import api"
        api_import_pattern = re.compile(r"^\s*(import api|from api[\s.]+)", re.MULTILINE)
        assert not api_import_pattern.search(source), (
            "worker.py must not import api (D-07 violation: T-04-02-01)"
        )

    def test_worker_no_tv_bridge_import(self):
        """worker.py source must not have an 'import tv_bridge' or 'from tv_bridge' statement."""
        import re  # noqa: PLC0415
        source = _WORKER_SRC.read_text(encoding="utf-8")
        tv_import_pattern = re.compile(r"^\s*(import tv_bridge|from tv_bridge[\s.]+)", re.MULTILINE)
        assert not tv_import_pattern.search(source), (
            "worker.py must not import tv_bridge (D-07 violation: T-04-02-01)"
        )

    def test_worker_has_d07_comment(self):
        """worker.py source contains the D-07 comment marker for auditability."""
        source = _WORKER_SRC.read_text(encoding="utf-8")
        assert "D-07" in source, (
            "worker.py must contain a D-07 comment marking the import restriction"
        )


class TestRunComboReturnsList:
    """run_combo returns list[dict] with one entry per fold."""

    def test_run_combo_returns_list(self, tmp_path):
        """run_combo returns a list."""
        from trading_core.optimization.worker import run_combo  # noqa: PLC0415

        db_path = _make_synthetic_bars_db(tmp_path)
        fold_boundaries = _make_single_fold(db_path)
        shard_dir = tmp_path / "shards"
        shard_dir.mkdir()

        result = run_combo(
            combo_dict={
                "opening_range_minutes": 15,
                "atr_stop_mult": 1.5,
                "r_target": 2.0,
            },
            fold_boundaries=fold_boundaries,
            db_path=str(db_path),
            run_id="test-run-001",
            symbol="SPY",
            timeframe="1m",
            seed=42,
            shard_dir=str(shard_dir),
            param_hash_str="deadbeef1234",
        )

        assert isinstance(result, list), "run_combo must return a list"

    def test_run_combo_returns_one_per_fold(self, tmp_path):
        """run_combo returns exactly one dict per fold."""
        from trading_core.optimization.worker import run_combo  # noqa: PLC0415

        db_path = _make_synthetic_bars_db(tmp_path)
        fold_boundaries = _make_single_fold(db_path)
        shard_dir = tmp_path / "shards"
        shard_dir.mkdir()

        result = run_combo(
            combo_dict={
                "opening_range_minutes": 15,
                "atr_stop_mult": 1.5,
                "r_target": 2.0,
            },
            fold_boundaries=fold_boundaries,
            db_path=str(db_path),
            run_id="test-run-002",
            symbol="SPY",
            timeframe="1m",
            seed=42,
            shard_dir=str(shard_dir),
            param_hash_str="deadbeef5678",
        )

        assert len(result) == len(fold_boundaries), (
            f"Expected {len(fold_boundaries)} results, got {len(result)}"
        )


class TestFoldResultShape:
    """Each fold result dict must have the required keys."""

    def test_fold_result_shape(self, tmp_path):
        """Result dicts contain fold_idx, param_hash, is_sharpe, oos_sharpe, equity_curve_path."""
        from trading_core.optimization.worker import run_combo  # noqa: PLC0415

        db_path = _make_synthetic_bars_db(tmp_path)
        fold_boundaries = _make_single_fold(db_path)
        shard_dir = tmp_path / "shards"
        shard_dir.mkdir()

        result = run_combo(
            combo_dict={
                "opening_range_minutes": 15,
                "atr_stop_mult": 1.5,
                "r_target": 2.0,
            },
            fold_boundaries=fold_boundaries,
            db_path=str(db_path),
            run_id="test-run-003",
            symbol="SPY",
            timeframe="1m",
            seed=42,
            shard_dir=str(shard_dir),
            param_hash_str="abcdef123456",
        )

        required_keys = {"fold_idx", "param_hash", "is_sharpe", "oos_sharpe", "equity_curve_path"}
        for fold_result in result:
            missing = required_keys - set(fold_result.keys())
            assert not missing, (
                f"Fold result missing required keys: {missing}. Got: {set(fold_result.keys())}"
            )

    def test_fold_result_has_extended_keys(self, tmp_path):
        """Result dicts also contain is_return, oos_return, edge_ratio, git_sha, data_hash, seed."""
        from trading_core.optimization.worker import run_combo  # noqa: PLC0415

        db_path = _make_synthetic_bars_db(tmp_path)
        fold_boundaries = _make_single_fold(db_path)
        shard_dir = tmp_path / "shards"
        shard_dir.mkdir()

        result = run_combo(
            combo_dict={
                "opening_range_minutes": 15,
                "atr_stop_mult": 1.5,
                "r_target": 2.0,
            },
            fold_boundaries=fold_boundaries,
            db_path=str(db_path),
            run_id="test-run-004",
            symbol="SPY",
            timeframe="1m",
            seed=42,
            shard_dir=str(shard_dir),
            param_hash_str="abcdef789012",
        )

        extended_keys = {"is_return", "oos_return", "git_sha", "data_hash", "seed"}
        for fold_result in result:
            missing = extended_keys - set(fold_result.keys())
            assert not missing, (
                f"Fold result missing extended keys: {missing}. Got: {set(fold_result.keys())}"
            )

    def test_fold_result_param_hash_matches_input(self, tmp_path):
        """Result param_hash matches the param_hash_str passed to run_combo."""
        from trading_core.optimization.worker import run_combo  # noqa: PLC0415

        db_path = _make_synthetic_bars_db(tmp_path)
        fold_boundaries = _make_single_fold(db_path)
        shard_dir = tmp_path / "shards"
        shard_dir.mkdir()

        my_hash = "myhash123456"
        result = run_combo(
            combo_dict={
                "opening_range_minutes": 15,
                "atr_stop_mult": 1.5,
                "r_target": 2.0,
            },
            fold_boundaries=fold_boundaries,
            db_path=str(db_path),
            run_id="test-run-005",
            symbol="SPY",
            timeframe="1m",
            seed=42,
            shard_dir=str(shard_dir),
            param_hash_str=my_hash,
        )

        for fold_result in result:
            assert fold_result["param_hash"] == my_hash, (
                f"param_hash mismatch: expected {my_hash!r}, got {fold_result['param_hash']!r}"
            )
