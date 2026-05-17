"""Wave 0 placeholder for BacktestEngine tests — BT-01, BT-04, BT-05, BT-06.

Requirements:
  BT-01 — BacktestEngine consuming (DataSource, Strategy, RiskManager, Executor, config),
           emitting BacktestResult.
  BT-04 — Standard metrics: total_return, CAGR, Sharpe, Sortino, Calmar, max DD,
           max DD duration, win rate, expectancy, profit factor, trade count, avg hold.
  BT-05 — Per-trade MAE/MFE persisted.
  BT-06 — Full attribution chain: fill → signal → risk_decision (signal_id threaded
           through Fill into trades table).

Analog: packages/trading-core/tests/test_orb_strategy.py (driver loop + fixture import)

This file is a Wave 0 stub. Wave 3 Plan 03 implements BacktestEngine and fills in
the real tests.
"""

import pytest


@pytest.mark.xfail(reason="Wave 3 Plan 03 — not yet implemented", strict=True)
def test_placeholder_until_wave_3():
    raise NotImplementedError
