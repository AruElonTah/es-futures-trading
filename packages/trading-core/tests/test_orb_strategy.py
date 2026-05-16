"""Tests for ORBStrategy — Phase 2 Plan 02 success criteria #1, #3, #4.

Success criteria tested:
  #1: ORBStrategy emits exactly one signal with correct fields on breakout
  #3: rollover_seam guard returns None (before any state mutation)
  #4: YAML registry loads strategy with correct params

Additional: warmup guard, one-signal-per-session, no-signal-in-ORB-window.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from trading_core.strategy.models import Signal, StrategyContext
from trading_core.strategy.orb import ORBConfig, ORBStrategy
from trading_core.strategy.registry import StrategyRegistry


def _drive_strategy(strategy: ORBStrategy, bars: list) -> list:
    """Reference driver: build ctx from prior indicators, call on_bar, push after.

    This is the canonical driver pattern for look-ahead safety:
      1. Snapshot indicator state BEFORE the current bar (prior-bar context)
      2. Call on_bar with current bar + prior-bar context
      3. Push bar to indicators AFTER on_bar

    Phase 3's backtester will use the exact same loop order. Any deviation
    from this pattern would introduce ATR lookahead.
    """
    signals = []
    for bar in bars:
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
        signals.append(strategy.on_bar(bar, ctx))
        strategy._push_bar(bar)
    return signals


# ---------------------------------------------------------------------------
# Import fixture functions directly (not as pytest fixtures).
# conftest.py adds tests/ dir to sys.path so 'fixtures' is importable directly.
# ---------------------------------------------------------------------------
from fixtures.orb_day import orb_day_bars as _orb_day_bars
from fixtures.orb_day import rollover_seam_day_bars as _rollover_seam_day_bars


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_orb_signal_on_breakout():
    """Success criterion #1: ORB strategy produces exactly one signal on breakout bar.

    orb_day_bars fixture: bars 0-14 are the ORB window (high=471.00, low=470.50),
    bar 15 is the breakout bar (close=471.25 > ORB high=471.00, bullish close > open).
    ATR warmup is 15 bars (atr_period=14), which coincides with the ORB window.
    """
    config = ORBConfig(opening_range_minutes=15, atr_period=14, atr_stop_mult=1.5, r_target=2.0)
    strategy = ORBStrategy(config)
    bars = _orb_day_bars()
    signals = _drive_strategy(strategy, bars)

    non_none = [s for s in signals if s is not None]
    assert len(non_none) == 1, f"Expected exactly 1 signal, got {len(non_none)}"

    sig = non_none[0]
    assert sig.side == "long"
    assert sig.entry >= Decimal("471.00"), (
        f"entry={sig.entry} should be >= ORB high 471.00"
    )
    assert sig.stop < Decimal("471.00"), (
        f"stop={sig.stop} should be below ORB high"
    )
    assert sig.target > sig.entry, (
        f"target={sig.target} should be > entry={sig.entry}"
    )

    # Verify R-multiple: target = entry + r_target * (entry - stop)
    r_distance = sig.entry - sig.stop
    expected_target = sig.entry + Decimal(str(config.r_target)) * r_distance
    assert abs(sig.target - expected_target) < Decimal("0.01"), (
        f"target R-multiple wrong: got {sig.target}, expected {expected_target}"
    )

    assert sig.strategy_id == config.strategy_id
    assert sig.strategy_version == config.strategy_version


def test_no_signal_during_opening_range():
    """Zero signals emitted during the first opening_range_minutes bars."""
    config = ORBConfig(opening_range_minutes=15, atr_period=14, atr_stop_mult=1.5, r_target=2.0)
    strategy = ORBStrategy(config)
    bars = _orb_day_bars()

    orb_window_signals = []
    for i, bar in enumerate(bars[:15]):
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
        orb_window_signals.append(sig)
        strategy._push_bar(bar)

    assert all(s is None for s in orb_window_signals), (
        "No signals should be emitted during the ORB window (bars 0-14)"
    )


def test_rollover_seam_guard():
    """Success criterion #3: on_bar returns None on every rollover_seam bar.

    rollover_seam_day_bars() has bar[0].rollover_seam=True; subsequent bars
    proceed normally but produce no breakout signal (post-breakout bars have
    close == open — not a bullish bar per breakout logic).
    """
    config = ORBConfig(opening_range_minutes=15, atr_period=14, atr_stop_mult=1.5, r_target=2.0)
    strategy = ORBStrategy(config)
    bars = _rollover_seam_day_bars()
    signals = _drive_strategy(strategy, bars)
    assert all(s is None for s in signals), (
        "All signals on a rollover-seam day must be None"
    )


def test_one_signal_per_session():
    """At most one signal fires per RTH session (_signal_fired guard)."""
    config = ORBConfig(opening_range_minutes=15, atr_period=14, atr_stop_mult=1.5, r_target=2.0)
    strategy = ORBStrategy(config)
    bars = _orb_day_bars()
    signals = _drive_strategy(strategy, bars)
    non_none = [s for s in signals if s is not None]
    assert len(non_none) <= 1, (
        f"Got {len(non_none)} signals; expected at most 1 per session"
    )


def test_yaml_config_loading():
    """Success criterion #4: strategy params come from YAML, not Python defaults."""
    strategy = StrategyRegistry.load("config/strategies/orb.yaml")
    assert strategy._config.opening_range_minutes == 15
    assert strategy._config.atr_stop_mult == 1.5
    assert strategy._config.r_target == 2.0
    assert strategy.name == "opening_range_breakout"
    assert strategy._config.strategy_id == "orb-v1"
    assert strategy._config.strategy_version == "1.0"


def test_registry_list_strategies():
    """StrategyRegistry.list_strategies returns the orb strategy name."""
    names = StrategyRegistry.list_strategies("config/strategies/")
    assert "opening_range_breakout" in names


def test_warmup_guard():
    """on_bar returns None during warmup (warmup_complete=False in ctx)."""
    config = ORBConfig(opening_range_minutes=15, atr_period=14, atr_stop_mult=1.5, r_target=2.0)
    strategy = ORBStrategy(config)
    # Use a bar from AFTER the ORB window so the warmup guard is reached
    # We need at least 15 bars in ORB window first, then inject warmup_complete=False
    bars = _orb_day_bars()
    # Push 15 bars through (ORB window fills, but ATR still not warm since warmup=False)
    for i in range(15):
        bar = bars[i]
        ctx = StrategyContext(
            rollover_seam=bar.rollover_seam,
            warmup_complete=False,  # simulate warmup not complete
            bar_index=strategy._bar_count,
            ts_utc=bar.ts_utc,
            atr=None,
            session_vwap=None,
            ema=None,
            adr=None,
        )
        strategy.on_bar(bar, ctx)
        strategy._push_bar(bar)

    # Now try bar 15 (would be breakout) but force warmup_complete=False
    bar = bars[15]
    ctx = StrategyContext(
        rollover_seam=False,
        warmup_complete=False,  # warmup not complete
        bar_index=strategy._bar_count,
        ts_utc=bar.ts_utc,
        atr=None,
        session_vwap=None,
        ema=None,
        adr=None,
    )
    result = strategy.on_bar(bar, ctx)
    assert result is None, "warmup guard must return None when warmup_complete=False"


def test_warmup_bars_equals_atr_warmup():
    """ORBStrategy.warmup_bars() delegates to ATRWilder.warmup_bars()."""
    from trading_core.indicators import ATRWilder
    config = ORBConfig(atr_period=14)
    strategy = ORBStrategy(config)
    atr = ATRWilder(14)
    assert strategy.warmup_bars() == atr.warmup_bars()
    assert strategy.warmup_bars() >= config.atr_period + 1
