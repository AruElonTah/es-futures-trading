"""Wave 0 placeholder for FastAPI REST route tests — UI-01.

Requirement: UI-01 — FastAPI REST surface (Phase 3 minimal):
  GET /bars — returns RTH bars for a symbol+timeframe (D-07 cold-load state)
  GET /backtests — returns BacktestResult rows from DuckDB

Analog: packages/api/tests/test_health.py (TestClient pattern)

This file is a Wave 0 stub. Wave 4 Plan 04 implements /bars + /backtests routes
and fills in the real integration tests.
"""

import pytest


@pytest.mark.xfail(reason="Wave 4 Plan 04 — not yet implemented", strict=True)
def test_placeholder_until_wave_4():
    raise NotImplementedError
