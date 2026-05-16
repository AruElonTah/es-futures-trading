"""Integration: drive ORBStrategy through orb_day_bars; verify look-ahead safety.

This is the end-to-end leakage gate for the strategy layer. It complements
test_indicators.py (which tests indicators in isolation) by testing that
the driver pattern correctly constructs StrategyContext from PRIOR indicators
before each on_bar call.

Phase 2 success criterion #2: no ATR lookahead.

The key assertion: the signal's stop distance must equal
    atr_before_breakout_bar * atr_stop_mult

If the strategy were using the CURRENT bar's ATR (lookahead), the stop
distance would match atr_after_breakout_bar * atr_stop_mult instead.
We verify the former — and when the two ATR values differ, this test is
capable of distinguishing them.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from trading_core.indicators import ATRWilder
from trading_core.strategy.models import StrategyContext
from trading_core.strategy.orb import ORBConfig, ORBStrategy


def test_orb_strategy_no_lookahead():
    """The ATR used in the breakout signal was computed BEFORE the breakout bar.

    Drive ORBStrategy through orb_day_bars using the canonical driver pattern
    (snapshot indicators before on_bar, push after). Assert that the signal's
    stop distance matches the ATR available BEFORE the breakout bar —
    not the ATR that includes the breakout bar itself.

    The breakout bar (bar 15) has volume=50000 and a wider range (471.00-471.50),
    which shifts ATR upward. If lookahead were present, the stop would be wider
    than expected by the pre-breakout ATR.
    """
    from fixtures.orb_day import orb_day_bars

    config = ORBConfig(opening_range_minutes=15, atr_period=14, atr_stop_mult=1.5, r_target=2.0)
    strategy = ORBStrategy(config)
    bars = orb_day_bars()

    signal = None
    breakout_bar_idx: int | None = None
    atr_before_breakout: Decimal | None = None

    for i, bar in enumerate(bars):
        # Snapshot ATR BEFORE pushing this bar — this is what on_bar sees
        current_atr = strategy._atr.current

        ctx = StrategyContext(
            rollover_seam=bar.rollover_seam,
            warmup_complete=strategy.is_warm(),
            bar_index=strategy._bar_count,
            ts_utc=bar.ts_utc,
            atr=current_atr,
            session_vwap=strategy._vwap.current,
            ema=strategy._ema.current,
            adr=None,
        )
        sig = strategy.on_bar(bar, ctx)

        if sig is not None and signal is None:
            signal = sig
            breakout_bar_idx = i
            atr_before_breakout = current_atr  # ATR available to on_bar at breakout

        # Push AFTER on_bar — this is the look-ahead-safe contract
        strategy._push_bar(bar)

    assert signal is not None, (
        "No signal emitted — leakage test cannot run (fixture may be wrong)"
    )
    assert breakout_bar_idx is not None
    assert atr_before_breakout is not None, (
        "Signal fired before ATR was warm — check ORB/warmup interaction"
    )

    # Core assertion: stop distance == atr_before_breakout * atr_stop_mult
    # This is what correctly-look-ahead-safe on_bar computes.
    stop_distance = signal.entry - signal.stop
    expected_distance = atr_before_breakout * Decimal(str(config.atr_stop_mult))
    assert abs(stop_distance - expected_distance) < Decimal("0.01"), (
        f"Stop distance {stop_distance} != expected {expected_distance}. "
        "This indicates ATR lookahead: the signal used ATR from the breakout bar itself."
    )

    # Secondary check: compute ATR AFTER including the breakout bar.
    # If it differs from atr_before_breakout, the test is sensitive enough to
    # distinguish lookahead. Log both values for the SUMMARY.
    atr_after_indicator = ATRWilder(config.atr_period)
    for b in bars[: breakout_bar_idx + 1]:
        atr_after_indicator.push(b)
    atr_after = atr_after_indicator.current

    # The two values should differ (breakout bar has a wider range).
    # If they are equal (numerically), the test still passes but is less sensitive.
    if atr_after is not None and atr_after != atr_before_breakout:
        # Confirm: stop distance matches PRE-breakout ATR, not POST-breakout ATR
        post_distance = atr_after * Decimal(str(config.atr_stop_mult))
        assert abs(stop_distance - expected_distance) < abs(stop_distance - post_distance), (
            f"Stop distance is closer to post-breakout ATR ({post_distance}) than "
            f"pre-breakout ATR ({expected_distance}). Possible lookahead detected."
        )


def test_no_lookahead_breakout_bar_index():
    """Signal fires at bar 15 — the first bar AFTER the ORB window closes.

    This test verifies the driver produces the signal at the correct index.
    If ORB high/low collection and warmup overlap correctly, the breakout
    bar is bar 15 (index 0-based in a 390-bar day).
    """
    from fixtures.orb_day import orb_day_bars

    config = ORBConfig(opening_range_minutes=15, atr_period=14, atr_stop_mult=1.5, r_target=2.0)
    strategy = ORBStrategy(config)
    bars = orb_day_bars()

    signal_bar_idx: int | None = None
    for i, bar in enumerate(bars):
        ctx = StrategyContext(
            rollover_seam=bar.rollover_seam,
            warmup_complete=strategy.is_warm(),
            bar_index=strategy._bar_count,
            ts_utc=bar.ts_utc,
            atr=strategy._atr.current,
            session_vwap=strategy._vwap.current,
            ema=strategy._ema.current,
            adr=None,
        )
        sig = strategy.on_bar(bar, ctx)
        strategy._push_bar(bar)
        if sig is not None:
            signal_bar_idx = i
            break

    assert signal_bar_idx == 15, (
        f"Expected signal at bar 15 (first bar after ORB window + warmup), "
        f"got {signal_bar_idx}"
    )
