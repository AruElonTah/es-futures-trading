"""Wave 0 placeholder for safe_from_signals wrapper tests — BT-02.

Requirement: BT-02 — safe_from_signals() wrapper: entries.shift(1) + price='nextbar'
blocked; direct vbt.Portfolio calls blocked by pre-commit hook.

Analog: packages/trading-core/tests/test_orb_strategy.py

This file is a Wave 0 stub. Wave 2 Plan 02 implements safe_from_signals and
fills in the real tests.

NOTE: Do NOT embed the literal pattern 'vbt.Portfolio.from_signals(' in this file
— it would trip the no-direct-vbt-from-signals pre-commit hook. Reference the
wrapper API via 'safe_from_signals' only.
"""

import pytest


@pytest.mark.xfail(reason="Wave 2 Plan 02 — not yet implemented", strict=True)
def test_placeholder_until_wave_2():
    raise NotImplementedError
