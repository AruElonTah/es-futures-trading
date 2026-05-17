"""Wave 0 placeholder for reproducibility CI test — BT-09, FND-08.

Requirements:
  BT-09 — Backtest CLI run_backtest.py produces runs + backtests + trades rows.
  FND-08 — Same git_sha + data_hash + param_hash + seed must produce bitwise-identical
            equity-curve Parquet (ROADMAP success criterion #3 — reproducibility CI).

  The test runs run_backtest() twice with identical args and asserts:
    path1.read_bytes() == path2.read_bytes()

Analog: packages/trading-core/tests/integration/test_seed_bars_e2e.py (subprocess/CLI pattern)

This file is a Wave 0 stub. Wave 3 Plan 03 implements the run_backtest CLI and fills
in the real reproducibility integration test.
"""

import pytest


@pytest.mark.xfail(reason="Wave 3 Plan 03 — not yet implemented", strict=True)
def test_placeholder_until_wave_3():
    raise NotImplementedError
