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
