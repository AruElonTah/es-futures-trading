"""REST endpoint tests — GET /bars + GET /backtests.

Plan 03-04 Task 1 — proves UI-01 minimal REST surface:
  - GET /bars: DuckDB-backed bar fetch with Pydantic Query validation (D-07 cold-load)
  - GET /backtests: DuckDB-backed backtest listing (D-01)
  - Pydantic Query validation rejects invalid symbol/tf/limit with HTTP 422 (T-03-04-01)
  - SQL injection attempt via symbol is blocked at the validator boundary (T-03-04-02)
  - Limit DoS guard: le=10_000 (T-03-04-03)
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# _make_test_app is defined in conftest.py (shared with test_ws_stream.py)
# Under --import-mode=importlib, conftest.py functions are NOT automatically
# importable as a module. Use a local alias that mirrors the conftest function.
# conftest.make_test_app is loaded by pytest but not importable as a module.
# Instead we inline a thin local wrapper that delegates to conftest's factory.
# The cleanest approach: define _make_test_app locally by re-importing the
# factory from conftest directly.

def _make_test_app(duckdb_path: Path):
    """Delegate to conftest.make_test_app."""
    import sys, pathlib
    # conftest.py is in the same directory — add to sys.path if needed
    tests_dir = str(pathlib.Path(__file__).parent)
    if tests_dir not in sys.path:
        sys.path.insert(0, tests_dir)
    # conftest is loaded by pytest; also importable via sys.path
    import importlib
    _conftest = importlib.import_module("conftest")
    return _conftest.make_test_app(duckdb_path)


# ---------------------------------------------------------------------------
# GET /bars tests
# ---------------------------------------------------------------------------

class TestGetBars:
    def test_get_bars_returns_200_empty_when_no_data(self, tmp_path: Path) -> None:
        """Empty table returns [] with HTTP 200 (not 404)."""
        app = _make_test_app(tmp_path / "t.duckdb")
        with TestClient(app) as client:
            response = client.get("/bars?symbol=SPY&tf=1m&limit=10")
        assert response.status_code == 200
        assert response.json() == []

    def test_get_bars_returns_seeded_rows_asc(self, tmp_path: Path) -> None:
        """Returns seeded bars in ts_utc ASC order."""
        from trading_core.storage.duckdb_store import DuckDBStore

        db_path = tmp_path / "t.duckdb"
        store = DuckDBStore(db_path)
        store.ensure_schema()
        # Insert 3 bars in reverse order to prove ASC sort
        rows = [
            ("SPY", "1m", datetime(2024, 1, 2, 14, 32, tzinfo=timezone.utc),
             471.0, 472.0, 470.0, 471.5, 1000, False, "twelve_data"),
            ("SPY", "1m", datetime(2024, 1, 2, 14, 31, tzinfo=timezone.utc),
             470.5, 471.5, 470.0, 471.0, 1200, False, "twelve_data"),
            ("SPY", "1m", datetime(2024, 1, 2, 14, 30, tzinfo=timezone.utc),
             470.0, 471.0, 469.5, 470.5, 1500, True, "twelve_data"),
        ]
        store._conn.executemany(
            "INSERT INTO bars (symbol, timeframe, ts_utc, open, high, low, close, "
            "volume, rollover_seam, provider) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        store.close()

        app = _make_test_app(db_path)
        with TestClient(app) as client:
            response = client.get("/bars?symbol=SPY&tf=1m&limit=10")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 3
        # ASC order — earliest bar has volume 1500
        assert data[0]["volume"] == 1500
        assert data[2]["volume"] == 1000
        # Key shape checks
        first = data[0]
        assert "ts_utc" in first
        assert "open" in first
        assert "high" in first
        assert "low" in first
        assert "close" in first
        assert "volume" in first
        assert "rollover_seam" in first
        assert isinstance(first["open"], float)
        assert isinstance(first["volume"], int)
        assert isinstance(first["rollover_seam"], bool)
        assert first["rollover_seam"] is True

    def test_get_bars_limit_returns_most_recent(self, tmp_path: Path) -> None:
        """When limit < total rows, the MOST RECENT `limit` bars are returned."""
        from trading_core.storage.duckdb_store import DuckDBStore

        db_path = tmp_path / "t.duckdb"
        store = DuckDBStore(db_path)
        store.ensure_schema()
        rows = [
            ("SPY", "1m",
             datetime(2024, 1, 2, 14, 30 + i, tzinfo=timezone.utc),
             470.0 + i, 471.0 + i, 469.0 + i, 470.5 + i, 1000 + i, False, "twelve_data")
            for i in range(5)
        ]
        store._conn.executemany(
            "INSERT INTO bars (symbol, timeframe, ts_utc, open, high, low, close, "
            "volume, rollover_seam, provider) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        store.close()

        app = _make_test_app(db_path)
        with TestClient(app) as client:
            response = client.get("/bars?symbol=SPY&tf=1m&limit=2")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        # Should be the 2 most-recent bars (index 3 and 4), returned in ASC order
        assert data[0]["volume"] == 1003
        assert data[1]["volume"] == 1004

    def test_get_bars_invalid_symbol_returns_422(self, tmp_path: Path) -> None:
        """Unknown symbol returns HTTP 422 (Pydantic rejects non-{ES,MES,SPY})."""
        app = _make_test_app(tmp_path / "t.duckdb")
        with TestClient(app) as client:
            response = client.get("/bars?symbol=AAPL&tf=1m&limit=10")
        assert response.status_code == 422

    def test_get_bars_invalid_tf_returns_422(self, tmp_path: Path) -> None:
        """Unknown timeframe returns HTTP 422 (Pydantic rejects non-{1m,5m,15m})."""
        app = _make_test_app(tmp_path / "t.duckdb")
        with TestClient(app) as client:
            response = client.get("/bars?symbol=SPY&tf=2m&limit=10")
        assert response.status_code == 422

    def test_get_bars_limit_too_large_returns_422(self, tmp_path: Path) -> None:
        """limit > 10_000 returns HTTP 422 (DoS guard, T-03-04-03)."""
        app = _make_test_app(tmp_path / "t.duckdb")
        with TestClient(app) as client:
            response = client.get("/bars?symbol=SPY&tf=1m&limit=99999")
        assert response.status_code == 422

    def test_get_bars_limit_zero_returns_422(self, tmp_path: Path) -> None:
        """limit=0 returns HTTP 422 (must be >= 1)."""
        app = _make_test_app(tmp_path / "t.duckdb")
        with TestClient(app) as client:
            response = client.get("/bars?symbol=SPY&tf=1m&limit=0")
        assert response.status_code == 422

    def test_get_bars_sql_injection_returns_422(self, tmp_path: Path) -> None:
        """SQL injection via symbol blocked at Pydantic validator; bars table untouched.

        T-03-04-02 mitigation: even with parameterized queries as the second
        line of defense, the Pydantic Literal whitelist rejects before DB access.
        """
        from trading_core.storage.duckdb_store import DuckDBStore

        db_path = tmp_path / "t.duckdb"
        store = DuckDBStore(db_path)
        store.ensure_schema()
        # Seed one bar so we can verify the table is untouched after the attack
        store._conn.execute(
            "INSERT INTO bars (symbol, timeframe, ts_utc, open, high, low, close, "
            "volume, rollover_seam, provider) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ["SPY", "1m", datetime(2024, 1, 2, 14, 30, tzinfo=timezone.utc),
             470.0, 471.0, 469.5, 470.5, 1000, False, "twelve_data"],
        )
        store.close()

        app = _make_test_app(db_path)
        with TestClient(app) as client:
            # URL-encoded: symbol=SPY'; DROP TABLE bars;--
            response = client.get(
                "/bars?symbol=SPY%27%3B+DROP+TABLE+bars%3B--&tf=1m"
            )
        assert response.status_code == 422

        # Verify bars table is untouched (bars are still there)
        store2 = DuckDBStore(db_path)
        count = store2._conn.execute("SELECT COUNT(*) FROM bars").fetchone()[0]
        store2.close()
        assert count == 1


# ---------------------------------------------------------------------------
# GET /backtests tests
# ---------------------------------------------------------------------------

class TestGetBacktests:
    def test_get_backtests_returns_200_empty_when_no_data(
        self, tmp_path: Path
    ) -> None:
        """Empty table returns [] with HTTP 200."""
        app = _make_test_app(tmp_path / "t.duckdb")
        with TestClient(app) as client:
            response = client.get("/backtests")
        assert response.status_code == 200
        assert response.json() == []

    def test_get_backtests_returns_rows_ordered_by_created_at_desc(
        self, tmp_path: Path
    ) -> None:
        """Rows returned in created_at DESC order (most-recent run first)."""
        from trading_core.storage.duckdb_store import DuckDBStore

        db_path = tmp_path / "t.duckdb"
        store = DuckDBStore(db_path)
        store.ensure_schema()

        from_ts = datetime(2024, 1, 2, 14, 30, tzinfo=timezone.utc)
        to_ts = datetime(2024, 1, 2, 21, 0, tzinfo=timezone.utc)

        # Insert first backtest
        store.write_backtest(
            run_id="run-001",
            strategy_id="orb",
            symbol="SPY",
            timeframe="1m",
            from_ts=from_ts,
            to_ts=to_ts,
            param_hash="abc123",
            equity_curve_path="data/parquet/equity/run-001.parquet",
            total_return=0.05,
            cagr=0.12,
            sharpe=1.5,
            sortino=2.0,
            calmar=3.0,
            max_dd=-0.02,
            max_dd_duration_bars=30,
            win_rate=0.55,
            expectancy=0.3,
            profit_factor=1.8,
            trade_count=10,
            avg_hold_bars=15.0,
        )
        # Small sleep to ensure different created_at timestamps
        time.sleep(0.05)

        # Insert second backtest
        store.write_backtest(
            run_id="run-002",
            strategy_id="orb",
            symbol="SPY",
            timeframe="1m",
            from_ts=from_ts,
            to_ts=to_ts,
            param_hash="def456",
            equity_curve_path="data/parquet/equity/run-002.parquet",
            total_return=0.08,
            cagr=0.15,
            sharpe=2.0,
            sortino=2.5,
            calmar=4.0,
            max_dd=-0.015,
            max_dd_duration_bars=20,
            win_rate=0.60,
            expectancy=0.4,
            profit_factor=2.0,
            trade_count=12,
            avg_hold_bars=12.0,
        )
        store.close()

        app = _make_test_app(db_path)
        with TestClient(app) as client:
            response = client.get("/backtests")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        # Most-recent first
        assert data[0]["run_id"] == "run-002"
        assert data[1]["run_id"] == "run-001"

    def test_get_backtests_response_shape(self, tmp_path: Path) -> None:
        """Each row has all expected backtests columns including created_at."""
        from trading_core.storage.duckdb_store import DuckDBStore

        db_path = tmp_path / "t.duckdb"
        store = DuckDBStore(db_path)
        store.ensure_schema()

        from_ts = datetime(2024, 1, 2, 14, 30, tzinfo=timezone.utc)
        to_ts = datetime(2024, 1, 2, 21, 0, tzinfo=timezone.utc)

        store.write_backtest(
            run_id="run-shape",
            strategy_id="orb",
            symbol="SPY",
            timeframe="1m",
            from_ts=from_ts,
            to_ts=to_ts,
            param_hash="abc",
            equity_curve_path="data/parquet/equity/run-shape.parquet",
            total_return=0.05,
            cagr=0.12,
            sharpe=1.5,
            sortino=2.0,
            calmar=3.0,
            max_dd=-0.02,
            max_dd_duration_bars=30,
            win_rate=0.55,
            expectancy=0.3,
            profit_factor=1.8,
            trade_count=10,
            avg_hold_bars=15.0,
        )
        store.close()

        app = _make_test_app(db_path)
        with TestClient(app) as client:
            response = client.get("/backtests")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        row = data[0]
        expected_keys = {
            "run_id", "strategy_id", "symbol", "timeframe", "from_ts", "to_ts",
            "param_hash", "equity_curve_path", "total_return", "cagr", "sharpe",
            "sortino", "calmar", "max_dd", "max_dd_duration_bars", "win_rate",
            "expectancy", "profit_factor", "trade_count", "avg_hold_bars", "created_at",
        }
        assert set(row.keys()) == expected_keys
        assert row["run_id"] == "run-shape"
        assert row["symbol"] == "SPY"
        assert isinstance(row["total_return"], float)
        assert isinstance(row["trade_count"], int)
        # created_at is an ISO 8601 string
        assert isinstance(row["created_at"], str)
        assert "T" in row["created_at"]


# ---------------------------------------------------------------------------
# GET /backtests/{run_id}/equity tests  (Task 1 — T-03-05-01)
# ---------------------------------------------------------------------------

class TestEquityRoute:
    """Tests for GET /backtests/{run_id}/equity (T-03-05-01 path-traversal guard)."""

    def _seed_backtest(self, store, run_id: str, equity_path: str) -> None:
        """Insert a backtests row with the given equity_curve_path."""
        from datetime import datetime, timezone
        store.write_backtest(
            run_id=run_id,
            strategy_id="orb",
            symbol="SPY",
            timeframe="1m",
            from_ts=datetime(2024, 1, 2, 14, 30, tzinfo=timezone.utc),
            to_ts=datetime(2024, 1, 2, 21, 0, tzinfo=timezone.utc),
            param_hash="abc",
            equity_curve_path=equity_path,
            total_return=0.05,
            cagr=0.12,
            sharpe=1.5,
            sortino=2.0,
            calmar=3.0,
            max_dd=-0.02,
            max_dd_duration_bars=30,
            win_rate=0.55,
            expectancy=0.3,
            profit_factor=1.8,
            trade_count=10,
            avg_hold_bars=15.0,
        )

    def _write_equity_parquet(self, path) -> None:
        """Write a minimal equity parquet file at the given path."""
        import pandas as pd
        from pathlib import Path
        from trading_core.backtest.engine import write_equity_parquet
        from datetime import datetime, timezone
        path = Path(path)
        df = pd.DataFrame({
            "ts_utc": [datetime(2024, 1, 2, 14, 30, tzinfo=timezone.utc),
                       datetime(2024, 1, 2, 14, 31, tzinfo=timezone.utc)],
            "equity_$": [10000.0, 10050.0],
            "drawdown_$": [0.0, 0.0],
        })
        write_equity_parquet(df, path)

    def test_equity_returns_200_with_data(self, tmp_path: Path) -> None:
        """GET /backtests/{run_id}/equity returns 200 with the equity rows."""
        from trading_core.storage.duckdb_store import DuckDBStore
        from pathlib import Path

        db_path = tmp_path / "t.duckdb"
        run_id = "run-equity-01"
        # equity path must be relative to repo root under data/parquet/equity/
        # We'll set up a fake repo-rooted path by patching _EQUITY_ROOT in the route
        # Instead, write the parquet to a location the route will resolve correctly.
        # The route resolves equity_curve_path relative to repo root (4 parents up from
        # packages/api/src/api/routes/backtests.py). We use the actual tmp_path here
        # and set equity_curve_path to a path under data/parquet/equity in tmp_path.
        equity_dir = tmp_path / "data" / "parquet" / "equity"
        equity_dir.mkdir(parents=True)
        parquet_path = equity_dir / f"{run_id}.parquet"
        self._write_equity_parquet(parquet_path)

        store = DuckDBStore(db_path)
        store.ensure_schema()
        # Use absolute path so route resolves it (route checks relative_to _EQUITY_ROOT)
        # We need to override _EQUITY_ROOT or use absolute path trick:
        # Simplest: write relative path as absolute path string so route path.resolve() passes
        # Actually the route uses:
        #   abs_path = (repo_root / equity_curve_path).resolve()
        #   abs_path.relative_to(_EQUITY_ROOT)
        # We'll set equity_curve_path to the absolute str so (repo_root / abs_str).resolve()
        # = abs_str.resolve() on posix; on Windows we need to pass it as absolute path
        # The safest approach for testing: store the absolute path and patch the route's
        # _EQUITY_ROOT to tmp_path / "data" / "parquet" / "equity"
        self._seed_backtest(store, run_id, str(parquet_path))
        store.close()

        # Patch _EQUITY_ROOT to allow the tmp parquet path
        import api.routes.backtests as bt_module
        original_equity_root = bt_module._EQUITY_ROOT
        bt_module._EQUITY_ROOT = equity_dir.resolve()
        try:
            app = _make_test_app(db_path)
            with TestClient(app) as client:
                response = client.get(f"/backtests/{run_id}/equity")
        finally:
            bt_module._EQUITY_ROOT = original_equity_root

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 2
        row = data[0]
        assert "ts_utc" in row
        assert "equity" in row
        assert "drawdown" in row
        assert isinstance(row["equity"], float)

    def test_equity_404_unknown_run_id(self, tmp_path: Path) -> None:
        """GET /backtests/unknown/equity returns 404 with detail message."""
        app = _make_test_app(tmp_path / "t.duckdb")
        with TestClient(app) as client:
            response = client.get("/backtests/nonexistent-run/equity")
        assert response.status_code == 404
        assert response.json()["detail"] == "backtest not found"

    def test_equity_404_missing_parquet_file(self, tmp_path: Path) -> None:
        """GET /backtests/{run_id}/equity returns 404 when parquet file is gone."""
        from trading_core.storage.duckdb_store import DuckDBStore

        db_path = tmp_path / "t.duckdb"
        run_id = "run-missing-parquet"
        equity_dir = tmp_path / "data" / "parquet" / "equity"
        equity_dir.mkdir(parents=True)
        # parquet file does NOT exist
        parquet_path = equity_dir / f"{run_id}.parquet"

        store = DuckDBStore(db_path)
        store.ensure_schema()
        self._seed_backtest(store, run_id, str(parquet_path))
        store.close()

        import api.routes.backtests as bt_module
        original_equity_root = bt_module._EQUITY_ROOT
        bt_module._EQUITY_ROOT = equity_dir.resolve()
        try:
            app = _make_test_app(db_path)
            with TestClient(app) as client:
                response = client.get(f"/backtests/{run_id}/equity")
        finally:
            bt_module._EQUITY_ROOT = original_equity_root

        assert response.status_code == 404
        assert response.json()["detail"] == "equity curve not found"

    def test_equity_403_path_traversal(self, tmp_path: Path) -> None:
        """GET /backtests/{run_id}/equity returns 403 when equity_curve_path escapes root."""
        from trading_core.storage.duckdb_store import DuckDBStore

        db_path = tmp_path / "t.duckdb"
        run_id = "run-traversal"
        equity_dir = tmp_path / "data" / "parquet" / "equity"
        equity_dir.mkdir(parents=True)

        store = DuckDBStore(db_path)
        store.ensure_schema()
        # Manually insert a row with a path traversal attack
        store._conn.execute(
            "UPDATE backtests SET equity_curve_path = ? WHERE run_id = ?",
            ["../../etc/passwd", run_id],
        ) if False else None  # table is empty; insert directly
        from datetime import datetime, timezone
        store._conn.execute(
            "INSERT INTO backtests (run_id, strategy_id, symbol, timeframe, from_ts, to_ts, "
            "param_hash, equity_curve_path, total_return, cagr, sharpe, sortino, calmar, "
            "max_dd, max_dd_duration_bars, win_rate, expectancy, profit_factor, "
            "trade_count, avg_hold_bars) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [run_id, "orb", "SPY", "1m",
             datetime(2024, 1, 2, 14, 30, tzinfo=timezone.utc),
             datetime(2024, 1, 2, 21, 0, tzinfo=timezone.utc),
             "abc", "../../etc/passwd",
             0.05, 0.12, 1.5, 2.0, 3.0, -0.02, 30, 0.55, 0.3, 1.8, 10, 15.0],
        )
        store.close()

        import api.routes.backtests as bt_module
        original_equity_root = bt_module._EQUITY_ROOT
        bt_module._EQUITY_ROOT = equity_dir.resolve()
        try:
            app = _make_test_app(db_path)
            with TestClient(app) as client:
                response = client.get(f"/backtests/{run_id}/equity")
        finally:
            bt_module._EQUITY_ROOT = original_equity_root

        assert response.status_code == 403
        assert response.json()["detail"] == "forbidden equity path"


# ---------------------------------------------------------------------------
# GET /backtests/{run_id}/trades tests  (Task 1)
# ---------------------------------------------------------------------------

class TestTradesRoute:
    """Tests for GET /backtests/{run_id}/trades."""

    def _seed_backtest_and_trade(self, store, run_id: str) -> None:
        """Insert a backtests + trades row for testing."""
        from datetime import datetime, timezone
        store.write_backtest(
            run_id=run_id,
            strategy_id="orb",
            symbol="SPY",
            timeframe="1m",
            from_ts=datetime(2024, 1, 2, 14, 30, tzinfo=timezone.utc),
            to_ts=datetime(2024, 1, 2, 21, 0, tzinfo=timezone.utc),
            param_hash="abc",
            equity_curve_path=f"data/parquet/equity/{run_id}.parquet",
            total_return=0.05,
            cagr=0.12,
            sharpe=1.5,
            sortino=2.0,
            calmar=3.0,
            max_dd=-0.02,
            max_dd_duration_bars=30,
            win_rate=0.55,
            expectancy=0.3,
            profit_factor=1.8,
            trade_count=1,
            avg_hold_bars=15.0,
        )
        store.write_trades([{
            "trade_id": "trade-001",
            "run_id": run_id,
            "signal_id": "sig-001",
            "strategy_id": "orb",
            "side": "long",
            "entry_price": 470.0,
            "exit_price": 472.5,
            "exit_reason": "target",
            "entry_ts_utc": datetime(2024, 1, 2, 14, 45, tzinfo=timezone.utc),
            "exit_ts_utc": datetime(2024, 1, 2, 15, 30, tzinfo=timezone.utc),
            "pnl": 250.0,
            "size": 1,
            "slippage_ticks": 1,
            "mae": -0.25,
            "mfe": 3.0,
            "stop_price": 468.5,
            "target_price": 474.0,
        }])

    def test_trades_returns_200_with_rows(self, tmp_path: Path) -> None:
        """GET /backtests/{run_id}/trades returns 200 with correct fields."""
        from trading_core.storage.duckdb_store import DuckDBStore

        db_path = tmp_path / "t.duckdb"
        run_id = "run-trades-01"
        store = DuckDBStore(db_path)
        store.ensure_schema()
        self._seed_backtest_and_trade(store, run_id)
        store.close()

        app = _make_test_app(db_path)
        with TestClient(app) as client:
            response = client.get(f"/backtests/{run_id}/trades")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 1
        trade = data[0]
        assert trade["trade_id"] == "trade-001"
        assert trade["side"] == "long"
        assert trade["entry_price"] == pytest.approx(470.0)
        assert trade["exit_price"] == pytest.approx(472.5)
        assert trade["exit_reason"] == "target"
        assert "entry_ts_utc" in trade
        assert "exit_ts_utc" in trade
        assert trade["stop_price"] == pytest.approx(468.5)
        assert trade["target_price"] == pytest.approx(474.0)
        assert isinstance(trade["stop_price"], float)
        assert isinstance(trade["target_price"], float)

    def test_trades_404_unknown_run_id(self, tmp_path: Path) -> None:
        """GET /backtests/unknown/trades returns 404."""
        app = _make_test_app(tmp_path / "t.duckdb")
        with TestClient(app) as client:
            response = client.get("/backtests/nonexistent/trades")
        assert response.status_code == 404
        assert response.json()["detail"] == "backtest not found"

    def test_trades_returns_empty_list_when_no_trades(self, tmp_path: Path) -> None:
        """GET /backtests/{run_id}/trades returns 200 [] when trades table is empty for run."""
        from trading_core.storage.duckdb_store import DuckDBStore
        from datetime import datetime, timezone

        db_path = tmp_path / "t.duckdb"
        run_id = "run-no-trades"
        store = DuckDBStore(db_path)
        store.ensure_schema()
        store.write_backtest(
            run_id=run_id,
            strategy_id="orb",
            symbol="SPY",
            timeframe="1m",
            from_ts=datetime(2024, 1, 2, 14, 30, tzinfo=timezone.utc),
            to_ts=datetime(2024, 1, 2, 21, 0, tzinfo=timezone.utc),
            param_hash="abc",
            equity_curve_path=f"data/parquet/equity/{run_id}.parquet",
            total_return=0.0,
            cagr=0.0,
            sharpe=0.0,
            sortino=0.0,
            calmar=0.0,
            max_dd=0.0,
            max_dd_duration_bars=0,
            win_rate=0.0,
            expectancy=0.0,
            profit_factor=0.0,
            trade_count=0,
            avg_hold_bars=0.0,
        )
        store.close()

        app = _make_test_app(db_path)
        with TestClient(app) as client:
            response = client.get(f"/backtests/{run_id}/trades")
        assert response.status_code == 200
        assert response.json() == []

    def test_trades_nullable_stop_target(self, tmp_path: Path) -> None:
        """stop_price and target_price may be None; route returns them as null."""
        from trading_core.storage.duckdb_store import DuckDBStore
        from datetime import datetime, timezone

        db_path = tmp_path / "t.duckdb"
        run_id = "run-nullable"
        store = DuckDBStore(db_path)
        store.ensure_schema()
        from datetime import datetime, timezone
        store.write_backtest(
            run_id=run_id,
            strategy_id="orb",
            symbol="SPY",
            timeframe="1m",
            from_ts=datetime(2024, 1, 2, 14, 30, tzinfo=timezone.utc),
            to_ts=datetime(2024, 1, 2, 21, 0, tzinfo=timezone.utc),
            param_hash="abc",
            equity_curve_path=f"data/parquet/equity/{run_id}.parquet",
            total_return=0.05,
            cagr=0.12,
            sharpe=1.5,
            sortino=2.0,
            calmar=3.0,
            max_dd=-0.02,
            max_dd_duration_bars=30,
            win_rate=0.55,
            expectancy=0.3,
            profit_factor=1.8,
            trade_count=1,
            avg_hold_bars=15.0,
        )
        store.write_trades([{
            "trade_id": "trade-null",
            "run_id": run_id,
            "signal_id": "sig-null",
            "strategy_id": "orb",
            "side": "long",
            "entry_price": 470.0,
            "exit_price": 472.0,
            "exit_reason": "eod_flat",
            "entry_ts_utc": datetime(2024, 1, 2, 14, 45, tzinfo=timezone.utc),
            "exit_ts_utc": datetime(2024, 1, 2, 21, 0, tzinfo=timezone.utc),
            "pnl": 200.0,
            "size": 1,
            "slippage_ticks": 1,
            "mae": -0.5,
            "mfe": 2.5,
            "stop_price": None,
            "target_price": None,
        }])
        store.close()

        app = _make_test_app(db_path)
        with TestClient(app) as client:
            response = client.get(f"/backtests/{run_id}/trades")
        assert response.status_code == 200
        trade = response.json()[0]
        assert trade["stop_price"] is None
        assert trade["target_price"] is None


# ---------------------------------------------------------------------------
# CORS tests  (Task 1 — T-03-05-02)
# ---------------------------------------------------------------------------

class TestCORS:
    """CORS allows localhost:3000; rejects other origins (T-03-05-02)."""

    def test_cors_allows_localhost_3000(self, tmp_path: Path) -> None:
        """GET /bars with Origin: http://localhost:3000 receives allow header."""
        app = _make_test_app(tmp_path / "t.duckdb")
        with TestClient(app) as client:
            response = client.get(
                "/bars?symbol=SPY&tf=1m&limit=1",
                headers={"Origin": "http://localhost:3000"},
            )
        assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"

    def test_cors_rejects_unknown_origin(self, tmp_path: Path) -> None:
        """GET /bars with a non-allowed origin does NOT receive allow header."""
        app = _make_test_app(tmp_path / "t.duckdb")
        with TestClient(app) as client:
            response = client.get(
                "/bars?symbol=SPY&tf=1m&limit=1",
                headers={"Origin": "http://evil.example.com"},
            )
        assert "access-control-allow-origin" not in response.headers
