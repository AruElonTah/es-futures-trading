"""Backtesting sub-package — Phase 3.

Provides:
  safe_signals.py   — safe_from_signals() wrapper (the ONLY legitimate VBT call site)
  engine.py         — BacktestEngine: hybrid driver loop + VBT metrics pass (Plan 03)
"""

from trading_core.backtest.engine import BacktestEngine, BacktestResult, write_equity_parquet
from trading_core.backtest.safe_signals import safe_from_signals

__all__ = [
    "BacktestEngine",
    "BacktestResult",
    "safe_from_signals",
    "write_equity_parquet",
]
