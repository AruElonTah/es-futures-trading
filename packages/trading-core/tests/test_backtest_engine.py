"""Tests for BacktestEngine — Phase 3 success criteria BT-01, BT-04, BT-05, BT-06.

Success criteria tested:
  BT-01: BacktestEngine runs driver loop + produces BacktestResult
  BT-04: Standard metrics computed correctly
  BT-05: Per-trade MAE/MFE correct against known bar fixture
  BT-06: Attribution chain: signal_id in Fill in trades table
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest

# Import fixture functions directly — not as pytest fixtures
# (--import-mode=importlib + no tests/__init__.py pattern from Plan 01-01)
from fixtures.orb_day import orb_day_bars as _orb_day_bars
from fixtures.orb_day import rollover_seam_day_bars as _rollover_seam_day_bars

from trading_core.backtest.engine import BacktestEngine, BacktestResult, write_equity_parquet
from trading_core.execution.paper import PaperExecutor
from trading_core.risk.models import RiskConfig
from trading_core.risk.pass_through import PassThroughRiskManager
from trading_core.strategy.orb import ORBConfig, ORBStrategy


def _make_engine() -> BacktestEngine:
    return BacktestEngine(symbol="SPY")


def _make_strategy() -> ORBStrategy:
    return ORBStrategy(ORBConfig())


def _make_risk_manager() -> PassThroughRiskManager:
    return PassThroughRiskManager(RiskConfig())


def _make_executor() -> PaperExecutor:
    return PaperExecutor("SPY")


def _run_engine(bars=None, run_id="test-run-001") -> BacktestResult:
    """Synchronous helper to run BacktestEngine over orb_day_bars."""
    if bars is None:
        bars = _orb_day_bars()
    engine = _make_engine()
    strategy = _make_strategy()
    risk_manager = _make_risk_manager()
    executor = _make_executor()
    return asyncio.run(
        engine.run(
            run_id=run_id,
            bars=bars,
            strategy=strategy,
            risk_manager=risk_manager,
            executor=executor,
            seed=42,
            init_cash=10_000.0,
        )
    )


class TestBacktestEngineDriverLoop:
    def test_produces_backtest_result(self):
        """BT-01: Engine produces a BacktestResult with trades, metrics, equity_df."""
        result = _run_engine()
        assert isinstance(result, BacktestResult)
        assert isinstance(result.trades, list)
        assert isinstance(result.metrics, dict)
        import pandas as pd
        assert isinstance(result.equity_df, pd.DataFrame)

    def test_single_trade_on_orb_day(self):
        """BT-01: orb_day_bars produces exactly 1 trade (bar 15 is breakout)."""
        result = _run_engine()
        assert len(result.trades) == 1

    def test_trade_is_long(self):
        """orb_day_bars produces a long trade (close > ORB high on bar 15)."""
        result = _run_engine()
        trade = result.trades[0]
        assert trade["side"] == "long"

    def test_exit_reason_is_eod_flat(self):
        """orb_day_bars fixture: neither target nor stop fires → eod_flat."""
        result = _run_engine()
        trade = result.trades[0]
        # Post-breakout bars have high=471.50, low=471.00
        # Entry is at bar[16].open + 1tick slippage = 471.25 + 0.01 = 471.26
        # Stop = ORB_high - ctx.atr * 1.5 (will be well below 471.00 low)
        # Target = entry + 2 * (entry - stop) (will be well above 471.50 high)
        # So neither fires → eod_flat
        assert trade["exit_reason"] == "eod_flat"

    def test_equity_df_has_390_rows(self):
        """Equity curve has one row per bar (390 bars in orb_day_bars)."""
        result = _run_engine()
        assert len(result.equity_df) == 390

    def test_equity_df_columns(self):
        """Equity curve has ts_utc, equity_$, drawdown_$ columns."""
        result = _run_engine()
        cols = set(result.equity_df.columns)
        assert "ts_utc" in cols
        assert "equity_$" in cols
        assert "drawdown_$" in cols

    def test_equity_df_ts_utc_monotonic(self):
        """Equity curve ts_utc must be monotonically increasing."""
        result = _run_engine()
        ts = result.equity_df["ts_utc"]
        assert ts.is_monotonic_increasing


class TestRolloverSeam:
    def test_no_trades_on_rollover_day(self):
        """bar[0].rollover_seam=True → strategy returns None for first bar → 0 trades."""
        bars = _rollover_seam_day_bars()
        result = _run_engine(bars=bars)
        assert len(result.trades) == 0

    def test_equity_df_still_has_390_rows_on_rollover(self):
        """Even with no trades, equity_df should have 390 rows."""
        bars = _rollover_seam_day_bars()
        result = _run_engine(bars=bars)
        assert len(result.equity_df) == 390

    def test_equity_constant_on_rollover(self):
        """With no trades, equity should equal init_cash throughout."""
        bars = _rollover_seam_day_bars()
        result = _run_engine(bars=bars)
        # All equity values should be init_cash=10_000.0
        equity = result.equity_df["equity_$"]
        assert (equity == 10_000.0).all(), (
            f"Expected all equity=10000.0 but got: {equity.unique()}"
        )


class TestMetrics:
    def test_metrics_keys_present(self):
        """BT-04: metrics dict has all 12 keys + max_dd_duration_bars."""
        result = _run_engine()
        expected_keys = {
            "total_return", "cagr", "sharpe", "sortino", "calmar",
            "max_dd", "max_dd_duration_bars", "win_rate", "expectancy",
            "profit_factor", "trade_count", "avg_hold_bars",
        }
        assert expected_keys.issubset(set(result.metrics.keys())), (
            f"Missing keys: {expected_keys - set(result.metrics.keys())}"
        )

    def test_trade_count_is_1(self):
        """trade_count metric == 1 for orb_day_bars."""
        result = _run_engine()
        assert result.metrics["trade_count"] == 1

    def test_total_return_is_float_or_none(self):
        """total_return is a float (or None if coerced from NaN)."""
        result = _run_engine()
        val = result.metrics["total_return"]
        assert isinstance(val, (float, type(None)))

    def test_max_dd_is_float_or_none(self):
        """max_dd is float or None."""
        result = _run_engine()
        val = result.metrics["max_dd"]
        assert isinstance(val, (float, type(None)))

    def test_max_dd_duration_bars_is_int_or_zero(self):
        """max_dd_duration_bars is int."""
        result = _run_engine()
        val = result.metrics["max_dd_duration_bars"]
        assert isinstance(val, int)

    def test_no_nan_metrics(self):
        """All metrics must be float, int, or None — never bare float('nan')."""
        import math
        result = _run_engine()
        for key, val in result.metrics.items():
            if isinstance(val, float):
                assert not math.isnan(val), (
                    f"metrics['{key}'] is NaN — should be coerced to None"
                )


class TestMAEMFE:
    def test_mae_mfe_present_in_trade(self):
        """BT-05: trade dict has mae and mfe keys."""
        result = _run_engine()
        trade = result.trades[0]
        assert "mae" in trade
        assert "mfe" in trade

    def test_mae_is_non_negative(self):
        """MAE must be >= 0 (can't have negative adverse excursion)."""
        result = _run_engine()
        trade = result.trades[0]
        assert trade["mae"] >= 0.0

    def test_mfe_is_non_negative(self):
        """MFE must be >= 0."""
        result = _run_engine()
        trade = result.trades[0]
        assert trade["mfe"] >= 0.0

    def test_mae_mfe_correct_against_fixture(self):
        """BT-05: hand-computed MAE/MFE must match engine output within tolerance.

        orb_day_bars fixture:
          - Bar 15 is breakout signal bar; bar 16 is entry bar
          - Entry fill: bar[16].open + 1 tick slippage = 471.25 + 0.01 = 471.26
          - Post-breakout bars (17-389): high=471.50, low=471.00, close=471.25
          - Exit at bar 389 (eod_flat): close = 471.25
          - MAE for long = entry_price - min(low[entry_idx:exit_idx+1])
                        = 471.26 - 471.00 = 0.26
          - MFE for long = max(high[entry_idx:exit_idx+1]) - entry_price
                        = 471.50 - 471.26 = 0.24
        """
        bars = _orb_day_bars()
        result = _run_engine(bars=bars)
        trade = result.trades[0]

        entry_price = Decimal(str(trade["entry_price"]))
        mae = trade["mae"]
        mfe = trade["mfe"]

        # entry_price = 471.25 (bar[16].open) + 1 tick (0.01) = 471.26
        assert abs(float(entry_price) - 471.26) < 0.01, (
            f"Unexpected entry_price: {entry_price}"
        )
        # MAE: entry_price - min(low in range) = 471.26 - 471.00 = 0.26
        expected_mae = float(entry_price) - 471.00
        assert abs(mae - expected_mae) < 0.02, (
            f"MAE mismatch: got {mae:.4f}, expected ~{expected_mae:.4f}"
        )
        # MFE: max(high in range) - entry_price = 471.50 - 471.26 = 0.24
        expected_mfe = 471.50 - float(entry_price)
        assert abs(mfe - expected_mfe) < 0.02, (
            f"MFE mismatch: got {mfe:.4f}, expected ~{expected_mfe:.4f}"
        )


class TestAttributionChain:
    def test_signal_id_in_trade_row(self):
        """BT-06: trade has signal_id that is a non-empty string."""
        result = _run_engine()
        trade = result.trades[0]
        assert "signal_id" in trade
        assert isinstance(trade["signal_id"], str)
        assert len(trade["signal_id"]) > 0

    def test_strategy_id_in_trade_row(self):
        """BT-06: trade has strategy_id = 'orb-v1'."""
        result = _run_engine()
        trade = result.trades[0]
        assert trade["strategy_id"] == "orb-v1"

    def test_stop_price_in_trade_row(self):
        """BT-06: trade has stop_price sourced from Signal.stop."""
        result = _run_engine()
        trade = result.trades[0]
        assert "stop_price" in trade
        assert trade["stop_price"] is not None
        assert isinstance(trade["stop_price"], float)
        assert trade["stop_price"] > 0

    def test_target_price_in_trade_row(self):
        """BT-06: trade has target_price sourced from Signal.target."""
        result = _run_engine()
        trade = result.trades[0]
        assert "target_price" in trade
        assert trade["target_price"] is not None
        assert isinstance(trade["target_price"], float)
        assert trade["target_price"] > 0

    def test_run_id_in_trade_row(self):
        """BT-06: trade has run_id matching what was passed to engine.run()."""
        result = _run_engine(run_id="sentinel-run-42")
        trade = result.trades[0]
        assert trade["run_id"] == "sentinel-run-42"

    def test_trade_id_is_unique_string(self):
        """BT-06: trade has a unique trade_id (uuid7)."""
        result = _run_engine()
        trade = result.trades[0]
        assert "trade_id" in trade
        assert isinstance(trade["trade_id"], str)
        assert len(trade["trade_id"]) > 0

    def test_entry_exit_ts_utc_present(self):
        """BT-06: entry_ts_utc and exit_ts_utc are present and aware datetimes."""
        from datetime import datetime, timezone
        result = _run_engine()
        trade = result.trades[0]
        assert "entry_ts_utc" in trade
        assert "exit_ts_utc" in trade
        entry_ts = trade["entry_ts_utc"]
        exit_ts = trade["exit_ts_utc"]
        # Should be datetime objects with UTC timezone
        assert isinstance(entry_ts, datetime)
        assert isinstance(exit_ts, datetime)
        assert entry_ts.tzinfo is not None
        assert exit_ts > entry_ts

    def test_pnl_field_present(self):
        """BT-06: trade has pnl field (can be negative on eod_flat loss)."""
        result = _run_engine()
        trade = result.trades[0]
        assert "pnl" in trade
        assert isinstance(trade["pnl"], float)


class TestEquityParquet:
    def test_parquet_byte_stability(self, tmp_path: Path):
        """write_equity_parquet produces byte-identical files on two calls."""
        import pandas as pd
        # Build a simple equity DataFrame to test byte stability
        bars = _orb_day_bars()
        result = _run_engine(bars=bars)

        path_a = tmp_path / "a.parquet"
        path_b = tmp_path / "b.parquet"

        write_equity_parquet(result.equity_df, path_a)
        write_equity_parquet(result.equity_df, path_b)

        assert path_a.read_bytes() == path_b.read_bytes(), (
            "write_equity_parquet is not byte-stable — check pyarrow flags"
        )

    def test_parquet_has_correct_columns(self, tmp_path: Path):
        """Equity Parquet file has ts_utc, equity_$, drawdown_$ columns."""
        import pyarrow.parquet as pq
        result = _run_engine()
        path = tmp_path / "equity.parquet"
        write_equity_parquet(result.equity_df, path)

        table = pq.read_table(str(path))
        cols = set(table.schema.names)
        assert "ts_utc" in cols
        assert "equity_$" in cols
        assert "drawdown_$" in cols

    def test_parquet_row_count(self, tmp_path: Path):
        """Equity Parquet has 390 rows for orb_day_bars."""
        import pyarrow.parquet as pq
        result = _run_engine()
        path = tmp_path / "equity.parquet"
        write_equity_parquet(result.equity_df, path)
        table = pq.read_table(str(path))
        assert table.num_rows == 390


class TestEngineSafeFromSignals:
    def test_engine_uses_safe_from_signals(self):
        """Engine calls safe_from_signals (not direct vbt.Portfolio.from_signals)."""
        # Import the module-level reference we want to spy on
        import trading_core.backtest.engine as engine_module
        call_count = {"n": 0}
        original = engine_module.safe_from_signals

        def spy(*args, **kwargs):
            call_count["n"] += 1
            return original(*args, **kwargs)

        with patch.object(engine_module, "safe_from_signals", side_effect=spy):
            _run_engine()

        assert call_count["n"] >= 1, (
            "BacktestEngine did not call safe_from_signals — VBT calls must go through the wrapper"
        )
