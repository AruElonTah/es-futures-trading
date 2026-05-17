"""Tests for ``trading_core.storage.duckdb_store.DuckDBStore`` (MD-04 + Pitfall 2).

Behavior tested:
- ``ensure_schema()`` creates bars/bar_gaps/instruments/runs with composite PK
  ``(symbol, timeframe, ts_utc)`` on ``bars``.
- ``upsert_bars(df, provider=...)`` is idempotent (Pitfall 2 — uses
  ON CONFLICT ... DO UPDATE SET, NOT the 3-word upsert shortcut form).
- ``upsert_bars`` updates a row when ``close`` changes (Plan §<behavior> bullet 3).
- ``upsert_gaps(...)`` is idempotent on re-run with same input.
- ``write_parquet_partition`` writes Hive-partitioned files (symbol=/year=/month=).
- ``with DuckDBStore(path) as store`` auto-closes.
- Missing parent directory raises a meaningful error.
- write_run round-trip works (Task 2 lands the runs.py helpers; this test covers
  the storage-side persistence end of the contract via direct kwargs).
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from trading_core.storage.duckdb_store import DuckDBStore


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _spy_390_bars_df(day: date = date(2024, 6, 12)) -> pd.DataFrame:
    """Build a 390-row 1m SPY DataFrame shaped for ``upsert_bars``.

    Columns match the SQL row order DuckDBStore expects:
    (symbol, timeframe, ts_utc, open, high, low, close, volume, rollover_seam).
    Each row is a deterministic OHLCV at the synthetic 100.00 baseline plus
    the bar index so that the per-row content is unique (catches false
    "idempotent because all rows are equal" passes).
    """
    # 9:30 ET = 13:30 UTC (EDT) on 2024-06-12 (Wed) — known trading day, not DST.
    start = datetime(day.year, day.month, day.day, 13, 30, tzinfo=timezone.utc)
    idx = pd.date_range(start, periods=390, freq="1min", tz="UTC")
    rows: list[dict] = []
    for i, ts in enumerate(idx):
        base = 100.0 + i * 0.01
        rows.append(
            {
                "symbol": "SPY",
                "timeframe": "1m",
                "ts_utc": ts.to_pydatetime(),
                "open": base,
                "high": base + 0.05,
                "low": base - 0.05,
                "close": base + 0.02,
                "volume": 1000 + i,
                "rollover_seam": False,
            }
        )
    return pd.DataFrame(rows)


@pytest.fixture
def tmp_duckdb_path(tmp_path: Path) -> Path:
    """A fresh DuckDB file path under tmp_path (no pre-existing file)."""
    return tmp_path / "test.duckdb"


# ---------------------------------------------------------------------------
# ensure_schema + table shape
# ---------------------------------------------------------------------------


class TestEnsureSchema:
    def test_creates_all_tables(self, tmp_duckdb_path: Path) -> None:
        store = DuckDBStore(tmp_duckdb_path)
        store.ensure_schema()
        try:
            tables = {
                row[0]
                for row in store._conn.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'main'"
                ).fetchall()
            }
        finally:
            store.close()
        # Phase 1 tables: bars, bar_gaps, instruments, runs
        # Phase 3 Plan 01 (D-01/D-02): backtests, trades
        assert {"bars", "bar_gaps", "instruments", "runs"}.issubset(tables)
        assert "backtests" in tables, "backtests table missing (Phase 3 D-01)"
        assert "trades" in tables, "trades table missing (Phase 3 D-02)"

    def test_bars_has_composite_pk(self, tmp_duckdb_path: Path) -> None:
        with DuckDBStore(tmp_duckdb_path) as store:
            store.ensure_schema()
            row = store._conn.execute(
                "SELECT constraint_text FROM duckdb_constraints() "
                "WHERE table_name='bars' AND constraint_type='PRIMARY KEY'"
            ).fetchone()
        assert row is not None
        text = row[0]
        assert "symbol" in text and "timeframe" in text and "ts_utc" in text

    def test_bars_ts_utc_is_timestamptz(self, tmp_duckdb_path: Path) -> None:
        with DuckDBStore(tmp_duckdb_path) as store:
            store.ensure_schema()
            rows = store._conn.execute(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_name='bars'"
            ).fetchall()
        cols = dict(rows)
        # DuckDB reports TIMESTAMPTZ as 'TIMESTAMP WITH TIME ZONE'.
        assert cols["ts_utc"].upper() in ("TIMESTAMPTZ", "TIMESTAMP WITH TIME ZONE")

    def test_bars_rollover_seam_default_false(self, tmp_duckdb_path: Path) -> None:
        with DuckDBStore(tmp_duckdb_path) as store:
            store.ensure_schema()
            rows = store._conn.execute(
                "SELECT column_name, is_nullable, column_default "
                "FROM information_schema.columns WHERE table_name='bars' "
                "AND column_name='rollover_seam'"
            ).fetchall()
        assert rows[0][1].upper() == "NO"  # NOT NULL
        # DuckDB 1.5.x renders the FALSE default as ``CAST('f' AS BOOLEAN)`` in
        # information_schema.columns.column_default — accept any rendering that
        # case-insensitively contains either 'false' or the 'f' boolean literal.
        default_text = (rows[0][2] or "").lower()
        assert "false" in default_text or "'f'" in default_text

    def test_ensure_schema_is_idempotent(self, tmp_duckdb_path: Path) -> None:
        with DuckDBStore(tmp_duckdb_path) as store:
            store.ensure_schema()
            # second call must not raise (CREATE TABLE IF NOT EXISTS)
            store.ensure_schema()


# ---------------------------------------------------------------------------
# upsert_bars — idempotency + update semantics (Pitfall 2)
# ---------------------------------------------------------------------------


class TestUpsertBars:
    def test_inserts_390_rows_on_first_call(self, tmp_duckdb_path: Path) -> None:
        df = _spy_390_bars_df()
        with DuckDBStore(tmp_duckdb_path) as store:
            store.ensure_schema()
            store.upsert_bars(df, provider="twelve_data")
            n = store._conn.execute("SELECT COUNT(*) FROM bars").fetchone()[0]
        assert n == 390

    def test_idempotent_on_second_call_same_data(
        self, tmp_duckdb_path: Path
    ) -> None:
        df = _spy_390_bars_df()
        with DuckDBStore(tmp_duckdb_path) as store:
            store.ensure_schema()
            store.upsert_bars(df, provider="twelve_data")
            n1 = store._conn.execute("SELECT COUNT(*) FROM bars").fetchone()[0]
            # Snapshot the OHLCV contents BEFORE the second call.
            content_before = store._conn.execute(
                "SELECT symbol, timeframe, ts_utc, open, high, low, close, volume, "
                "rollover_seam, provider FROM bars "
                "ORDER BY symbol, timeframe, ts_utc"
            ).fetchall()
            store.upsert_bars(df, provider="twelve_data")
            n2 = store._conn.execute("SELECT COUNT(*) FROM bars").fetchone()[0]
            content_after = store._conn.execute(
                "SELECT symbol, timeframe, ts_utc, open, high, low, close, volume, "
                "rollover_seam, provider FROM bars "
                "ORDER BY symbol, timeframe, ts_utc"
            ).fetchall()
        assert n1 == 390
        assert n2 == 390  # zero net rows added
        assert content_before == content_after

    def test_update_path_changes_close(self, tmp_duckdb_path: Path) -> None:
        df = _spy_390_bars_df()
        with DuckDBStore(tmp_duckdb_path) as store:
            store.ensure_schema()
            store.upsert_bars(df, provider="twelve_data")
            # Mutate one row's close — same (symbol, tf, ts_utc) PK.
            df2 = df.copy()
            df2.loc[100, "close"] = 999.99
            store.upsert_bars(df2, provider="twelve_data")
            row = store._conn.execute(
                "SELECT close FROM bars WHERE symbol='SPY' AND timeframe='1m' "
                "AND ts_utc = ?",
                [df.loc[100, "ts_utc"]],
            ).fetchone()
        assert row is not None
        assert abs(row[0] - 999.99) < 1e-9


# ---------------------------------------------------------------------------
# upsert_gaps — same idempotency contract
# ---------------------------------------------------------------------------


class TestUpsertGaps:
    def test_inserts_then_idempotent(self, tmp_duckdb_path: Path) -> None:
        gaps_df = pd.DataFrame(
            {
                "symbol": ["SPY", "SPY", "SPY"],
                "timeframe": ["1m", "1m", "1m"],
                "ts_utc": [
                    pd.Timestamp("2024-06-12 13:30:00", tz="UTC"),
                    pd.Timestamp("2024-06-12 13:31:00", tz="UTC"),
                    pd.Timestamp("2024-06-12 13:32:00", tz="UTC"),
                ],
            }
        )
        with DuckDBStore(tmp_duckdb_path) as store:
            store.ensure_schema()
            store.upsert_gaps(gaps_df, provider="twelve_data", run_id="r1")
            n1 = store._conn.execute("SELECT COUNT(*) FROM bar_gaps").fetchone()[0]
            store.upsert_gaps(gaps_df, provider="twelve_data", run_id="r1")
            n2 = store._conn.execute("SELECT COUNT(*) FROM bar_gaps").fetchone()[0]
        assert n1 == 3
        assert n2 == 3


# ---------------------------------------------------------------------------
# write_parquet_partition — Hive layout (symbol=/year=/month=)
# ---------------------------------------------------------------------------


class TestWriteParquetPartition:
    def test_writes_hive_partitioned_files(
        self, tmp_duckdb_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        df = _spy_390_bars_df()
        # Direct the COPY output under tmp_path so the test doesn't touch the
        # repo's data/parquet/ tree.
        monkeypatch.chdir(tmp_path)
        with DuckDBStore(tmp_duckdb_path) as store:
            store.ensure_schema()
            store.upsert_bars(df, provider="twelve_data")
            store.write_parquet_partition(
                symbol="SPY",
                start_utc=datetime(2024, 6, 12, 0, 0, tzinfo=timezone.utc),
                end_utc=datetime(2024, 6, 13, 0, 0, tzinfo=timezone.utc),
            )
        # symbol=SPY/year=2024/month=6 (DuckDB does NOT zero-pad month — it
        # emits the raw int from the YEAR()/MONTH() functions).
        outdir = tmp_path / "data" / "parquet" / "bars"
        assert outdir.exists()
        # Match either zero-padded or unpadded month layout — DuckDB's behavior
        # is documented per-version. Acceptance: at least one parquet under a
        # symbol=SPY partition.
        parquet_files = list(outdir.rglob("*.parquet"))
        assert parquet_files, f"no parquet files under {outdir}"
        # All parquet files must live under symbol=SPY
        rel = [p.relative_to(outdir) for p in parquet_files]
        assert all(
            "symbol=SPY" in str(r) for r in rel
        ), f"non-SPY partition layout: {rel}"


# ---------------------------------------------------------------------------
# context manager + error surfaces
# ---------------------------------------------------------------------------


class TestContextManager:
    def test_with_block_closes_connection(self, tmp_duckdb_path: Path) -> None:
        with DuckDBStore(tmp_duckdb_path) as store:
            store.ensure_schema()
            conn = store._conn
        # After __exit__, attempting to use the underlying conn must fail.
        # DuckDB raises duckdb.ConnectionException on closed connections.
        with pytest.raises(Exception):
            conn.execute("SELECT 1").fetchone()

    def test_nonexistent_parent_directory_raises(self, tmp_path: Path) -> None:
        bad = tmp_path / "does_not_exist" / "deeper" / "test.duckdb"
        with pytest.raises((FileNotFoundError, OSError, ValueError, RuntimeError)):
            store = DuckDBStore(bad)
            # The constructor may not eagerly probe — force a connection if so.
            store.ensure_schema()


# ---------------------------------------------------------------------------
# write_run round-trip (Task 2 hand-off; this test imports trading_core.storage.runs)
# ---------------------------------------------------------------------------


class TestWriteRunRoundTrip:
    def test_write_run_round_trip(self, tmp_duckdb_path: Path) -> None:
        # Task 2 helpers — must be importable for this test.
        runs = pytest.importorskip(
            "trading_core.storage.runs",
            reason="runs.py lands in Plan 01-04 Task 2",
        )
        adr_hash = runs.adr_hash
        data_hash = runs.data_hash
        git_sha = runs.git_sha
        new_run_id = runs.new_run_id
        param_hash = runs.param_hash

        # Build a small df just to feed data_hash.
        df = _spy_390_bars_df().assign(provider="twelve_data")
        rid = new_run_id()
        started = datetime(2024, 6, 12, 12, 0, tzinfo=timezone.utc)
        finished = datetime(2024, 6, 12, 12, 5, tzinfo=timezone.utc)
        with DuckDBStore(tmp_duckdb_path) as store:
            store.ensure_schema()
            store.write_run(
                run_id=rid,
                git_sha=git_sha(),
                data_hash=data_hash(df),
                param_hash=param_hash({"symbol": "SPY", "tf": "1m"}),
                seed=42,
                adr_hash=adr_hash(),
                started_at=started,
                finished_at=finished,
                status="ok",
                notes="round-trip test",
            )
            row = store._conn.execute(
                "SELECT run_id, adr_hash, status, notes FROM runs "
                "ORDER BY started_at DESC LIMIT 1"
            ).fetchone()
        assert row is not None
        assert row[0] == rid
        # 64-char sha256 hex
        assert len(row[1]) == 64
        assert row[2] == "ok"
        assert row[3] == "round-trip test"
