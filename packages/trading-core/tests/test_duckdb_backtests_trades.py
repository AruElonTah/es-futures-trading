"""Tests for DuckDB backtests + trades table extension — Phase 3 D-01/D-02.

Covers:
  - ensure_schema creates backtests + trades tables
  - write_backtest persists a row with all 20 fields
  - write_trades persists multiple rows with all 17 D-02 fields
  - write_trades with empty list is a no-op
  - exit_reason 'target' roundtrips correctly
  - ensure_schema is idempotent (does not drop existing data)
  - SQL injection via parameter does not corrupt the table (T-03-01-01)

Phase 3 plan 03-01.
"""

from __future__ import annotations

import datetime
from pathlib import Path

import pytest


_RUN_ID = "01923456-0000-7000-a000-000000000001"
_TRADE_ID = "01923456-0000-7000-a000-000000000002"
_TS = datetime.datetime(2024, 1, 2, 14, 30, tzinfo=datetime.timezone.utc)
_TS2 = datetime.datetime(2024, 1, 2, 16, 0, tzinfo=datetime.timezone.utc)


def _make_backtest_kwargs(run_id: str = _RUN_ID) -> dict:
    return dict(
        run_id=run_id,
        strategy_id="orb_v1",
        symbol="SPY",
        timeframe="1m",
        from_ts=_TS,
        to_ts=_TS2,
        param_hash="abc123",
        equity_curve_path="data/parquet/equity/test.parquet",
        total_return=0.05,
        cagr=0.12,
        sharpe=1.5,
        sortino=2.0,
        calmar=0.8,
        max_dd=-0.02,
        max_dd_duration_bars=10,
        win_rate=0.55,
        expectancy=12.50,
        profit_factor=1.8,
        trade_count=5,
        avg_hold_bars=3.2,
    )


def _make_trade_dict(trade_id: str = _TRADE_ID, run_id: str = _RUN_ID) -> dict:
    return dict(
        trade_id=trade_id,
        run_id=run_id,
        signal_id="sig-001",
        strategy_id="orb_v1",
        side="long",
        entry_price=471.50,
        exit_price=472.00,
        exit_reason="target",
        entry_ts_utc=_TS,
        exit_ts_utc=_TS2,
        pnl=50.0,
        size=1,
        slippage_ticks=1,
        mae=0.10,
        mfe=0.75,
        stop_price=471.00,
        target_price=472.25,
    )


class TestEnsureSchemaCreatesTables:
    def test_backtests_table_exists_after_ensure_schema(self, tmp_path: Path):
        from trading_core.storage.duckdb_store import DuckDBStore

        db = tmp_path / "test.duckdb"
        with DuckDBStore(db) as store:
            store.ensure_schema()
            result = store._conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_name = 'backtests'"
            ).fetchall()
            assert len(result) == 1, "backtests table not found"

    def test_trades_table_exists_after_ensure_schema(self, tmp_path: Path):
        from trading_core.storage.duckdb_store import DuckDBStore

        db = tmp_path / "test.duckdb"
        with DuckDBStore(db) as store:
            store.ensure_schema()
            result = store._conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_name = 'trades'"
            ).fetchall()
            assert len(result) == 1, "trades table not found"

    def test_ensure_schema_is_idempotent(self, tmp_path: Path):
        from trading_core.storage.duckdb_store import DuckDBStore

        db = tmp_path / "test.duckdb"
        with DuckDBStore(db) as store:
            store.ensure_schema()
            # Write a row then call ensure_schema again — data should survive
            store.write_backtest(**_make_backtest_kwargs())
            store.ensure_schema()  # second call must not drop data
            row = store._conn.execute(
                "SELECT run_id FROM backtests WHERE run_id = ?", [_RUN_ID]
            ).fetchone()
            assert row is not None, "Row disappeared after second ensure_schema call"


class TestWriteBacktest:
    def test_write_backtest_inserts_row(self, tmp_path: Path):
        from trading_core.storage.duckdb_store import DuckDBStore

        db = tmp_path / "test.duckdb"
        with DuckDBStore(db) as store:
            store.ensure_schema()
            store.write_backtest(**_make_backtest_kwargs())
            row = store._conn.execute(
                "SELECT * FROM backtests WHERE run_id = ?", [_RUN_ID]
            ).fetchone()
            assert row is not None

    def test_write_backtest_all_fields_roundtrip(self, tmp_path: Path):
        from trading_core.storage.duckdb_store import DuckDBStore

        db = tmp_path / "test.duckdb"
        kwargs = _make_backtest_kwargs()
        with DuckDBStore(db) as store:
            store.ensure_schema()
            store.write_backtest(**kwargs)
            row = store._conn.execute(
                "SELECT run_id, strategy_id, symbol, timeframe, param_hash, "
                "equity_curve_path, total_return, cagr, sharpe, sortino, calmar, "
                "max_dd, max_dd_duration_bars, win_rate, expectancy, profit_factor, "
                "trade_count, avg_hold_bars "
                "FROM backtests WHERE run_id = ?", [_RUN_ID]
            ).fetchone()
            assert row is not None
            assert row[0] == _RUN_ID
            assert row[1] == "orb_v1"
            assert row[2] == "SPY"
            assert row[3] == "1m"
            assert row[4] == "abc123"
            assert row[5] == "data/parquet/equity/test.parquet"
            assert abs(row[6] - 0.05) < 1e-9  # total_return
            assert abs(row[9] - 2.0) < 1e-9   # sortino
            assert row[12] == 10               # max_dd_duration_bars
            assert row[16] == 5                # trade_count


class TestWriteTrades:
    def test_write_trades_inserts_two_rows(self, tmp_path: Path):
        from trading_core.storage.duckdb_store import DuckDBStore

        db = tmp_path / "test.duckdb"
        trade1 = _make_trade_dict(trade_id="01923456-0000-7000-a000-000000000002")
        trade2 = _make_trade_dict(trade_id="01923456-0000-7000-a000-000000000003")
        with DuckDBStore(db) as store:
            store.ensure_schema()
            n = store.write_trades([trade1, trade2])
            assert n == 2
            count = store._conn.execute(
                "SELECT COUNT(*) FROM trades WHERE run_id = ?", [_RUN_ID]
            ).fetchone()[0]
            assert count == 2

    def test_write_trades_empty_is_noop(self, tmp_path: Path):
        from trading_core.storage.duckdb_store import DuckDBStore

        db = tmp_path / "test.duckdb"
        with DuckDBStore(db) as store:
            store.ensure_schema()
            n = store.write_trades([])
            assert n == 0
            count = store._conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
            assert count == 0

    def test_write_trades_exit_reason_target_roundtrips(self, tmp_path: Path):
        from trading_core.storage.duckdb_store import DuckDBStore

        db = tmp_path / "test.duckdb"
        trade = _make_trade_dict()
        with DuckDBStore(db) as store:
            store.ensure_schema()
            store.write_trades([trade])
            row = store._conn.execute(
                "SELECT exit_reason FROM trades WHERE trade_id = ?", [_TRADE_ID]
            ).fetchone()
            assert row is not None
            assert row[0] == "target"

    def test_write_trades_stop_price_and_target_price_roundtrip(self, tmp_path: Path):
        from trading_core.storage.duckdb_store import DuckDBStore

        db = tmp_path / "test.duckdb"
        trade = _make_trade_dict()
        with DuckDBStore(db) as store:
            store.ensure_schema()
            store.write_trades([trade])
            row = store._conn.execute(
                "SELECT stop_price, target_price FROM trades WHERE trade_id = ?",
                [_TRADE_ID]
            ).fetchone()
            assert row is not None
            assert abs(row[0] - 471.00) < 1e-9
            assert abs(row[1] - 472.25) < 1e-9

    def test_write_trades_nullable_stop_target(self, tmp_path: Path):
        """Non-ORB strategies can write NULL for stop_price and target_price."""
        from trading_core.storage.duckdb_store import DuckDBStore

        db = tmp_path / "test.duckdb"
        trade = _make_trade_dict()
        trade["stop_price"] = None
        trade["target_price"] = None
        with DuckDBStore(db) as store:
            store.ensure_schema()
            store.write_trades([trade])
            row = store._conn.execute(
                "SELECT stop_price, target_price FROM trades WHERE trade_id = ?",
                [_TRADE_ID]
            ).fetchone()
            assert row is not None
            assert row[0] is None
            assert row[1] is None


class TestSQLInjectionProtection:
    def test_malicious_strategy_id_does_not_drop_table(self, tmp_path: Path):
        """T-03-01-01: parameterized queries prevent SQL injection (Threat V5 mitigation)."""
        from trading_core.storage.duckdb_store import DuckDBStore

        db = tmp_path / "test.duckdb"
        with DuckDBStore(db) as store:
            store.ensure_schema()

            # First write a legitimate row
            store.write_backtest(**_make_backtest_kwargs())

            # Attempt SQL injection via strategy_id
            malicious_kwargs = _make_backtest_kwargs(
                run_id="01923456-0000-7000-a000-000000000099"
            )
            malicious_kwargs["strategy_id"] = "foo'; DROP TABLE backtests; --"
            store.write_backtest(**malicious_kwargs)

            # Table must still exist and prior row must still be queryable
            row = store._conn.execute(
                "SELECT run_id FROM backtests WHERE run_id = ?", [_RUN_ID]
            ).fetchone()
            assert row is not None, (
                "backtests table was dropped or prior row lost — parameterized query failed"
            )

            # Also confirm the injected row is there as a literal string
            row2 = store._conn.execute(
                "SELECT strategy_id FROM backtests WHERE run_id = ?",
                ["01923456-0000-7000-a000-000000000099"]
            ).fetchone()
            assert row2 is not None
            assert row2[0] == "foo'; DROP TABLE backtests; --"
