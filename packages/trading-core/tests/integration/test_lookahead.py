"""Wave 0 placeholder for BL-1 lookahead-leakage detector — BT-07, D-14.

Requirement: BT-07 — BL-1 lookahead detector CI test.
  A deliberately-leaking ORB variant (close.shift(-1) as entry basis) is routed
  through safe_from_signals(). The resulting Sharpe must be finite (not inf) and
  win rate must be in the 35-65% band — proving lookahead is neutralized.

  This test is required to pass in CI for any PR merge (ROADMAP cross-phase guardrail).

Analog: packages/trading-core/tests/integration/test_indicator_leakage.py (exact template)

This file is a Wave 0 stub. Wave 3 Plan 03 wires safe_from_signals and the
leaking-entry fixture to produce the real integration test.

NOTE: Do NOT embed the literal string 'vbt.Portfolio.from_signals(' in this file —
use safe_from_signals() in the real implementation (excluded from the hook).
"""

import pytest


@pytest.mark.xfail(reason="Wave 3 Plan 03 — not yet implemented", strict=True)
def test_placeholder_until_wave_3():
    raise NotImplementedError
