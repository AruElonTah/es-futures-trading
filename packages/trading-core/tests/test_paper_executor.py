"""Tests for PaperExecutor — BT-03, BT-08.

Requirements:
  BT-03 — Fill simulation: next-bar-open entry, session-phase-aware slippage
           (2 ticks during 9:30-9:45 ET window, 1 tick off-peak), worst-case
           intrabar stop/target (D-12: stop-first when both hit same bar).
  BT-08 — EOD forced flat at last RTH bar: sum(positions) == 0 after session end.

This file replaces the Wave 0 xfail stub (Plan 01 Task 3).
Wave 2 Plan 02 implementation.

Test classes:
  TestSlippageWindow   — session-phase-aware slippage ticks (9:30-9:45 ET = 2, else 1)
  TestEntryFill        — fill_entry produces correct fill_price and fill fields
  TestIntrabarConflict — check_exit returns stop-first when both hit (D-12)
  TestEODFlatten       — eod_flat when is_last_rth_bar=True; sum(positions)==0
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from trading_core.data.models import Bar
from trading_core.execution.models import Fill
from trading_core.execution.paper import PaperExecutor
from trading_core.risk.models import RiskConfig, RiskDecision, RiskState
from trading_core.risk.pass_through import PassThroughRiskManager
from trading_core.strategy.models import Signal

# Import fixture directly — --import-mode=importlib pattern from Plan 01
from fixtures.orb_day import orb_day_bars as _orb_day_bars

_UTC = timezone.utc


def _make_signal(
    side: str = "long",
    entry: Decimal = Decimal("471.00"),
    stop: Decimal = Decimal("470.25"),
    target: Decimal = Decimal("472.50"),
    size_hint: Decimal = Decimal("1"),
) -> Signal:
    """Build a minimal valid Signal."""
    return Signal(
        strategy_id="orb-v1",
        strategy_version="1.0",
        ts_utc=datetime(2024, 1, 2, 14, 30, tzinfo=_UTC),
        side=side,
        entry=entry,
        stop=stop,
        target=target,
        size_hint=size_hint,
    )


def _make_bar(
    ts_utc: datetime,
    open_: Decimal = Decimal("471.00"),
    high: Decimal = Decimal("471.50"),
    low_: Decimal = Decimal("470.75"),
    close: Decimal = Decimal("471.25"),
    symbol: str = "SPY",
) -> Bar:
    """Build a minimal Bar. Note: low_ with trailing underscore to avoid keyword conflict."""
    return Bar(
        symbol=symbol,
        timeframe="1m",
        ts_utc=ts_utc,
        open=open_,
        high=high,
        low=low_,
        close=close,
        volume=1000,
    )


def _make_decision(approved: bool = True, adjusted_size: int = 1) -> RiskDecision:
    return RiskDecision(approved=approved, reason="pass_through", adjusted_size=adjusted_size)


# ---------------------------------------------------------------------------
# Session-phase-aware slippage
# ---------------------------------------------------------------------------

class TestSlippageWindow:
    """Verify 2-tick slippage in 9:30-9:45 ET open window; 1-tick off-peak."""

    async def test_930_et_bar_uses_2_tick_slippage(self):
        """A bar at 9:30 ET (14:30 UTC on EST day) gets 2-tick slippage (open window)."""
        # 2024-01-02 = EST day (UTC-5); 9:30 ET = 14:30 UTC
        bar_ts = datetime(2024, 1, 2, 14, 30, tzinfo=_UTC)
        bar = _make_bar(bar_ts, open_=Decimal("471.50"))
        executor = PaperExecutor("SPY")
        signal = _make_signal()
        decision = _make_decision()
        fill = await executor.fill_entry(signal, decision, bar)
        # SPY tick_size=0.01; 2 ticks = 0.02; long fill = open + 0.02
        assert fill.slippage_ticks == 2
        assert fill.fill_price == Decimal("471.52")

    async def test_944_et_bar_uses_2_tick_slippage(self):
        """A bar at 9:44 ET is still within [9:30, 9:45) window — 2 ticks."""
        # 9:44 ET on 2024-01-02 = 14:44 UTC
        bar_ts = datetime(2024, 1, 2, 14, 44, tzinfo=_UTC)
        bar = _make_bar(bar_ts, open_=Decimal("471.50"))
        executor = PaperExecutor("SPY")
        signal = _make_signal()
        decision = _make_decision()
        fill = await executor.fill_entry(signal, decision, bar)
        assert fill.slippage_ticks == 2

    async def test_945_et_bar_uses_1_tick_slippage(self):
        """A bar at 9:45 ET is at the window boundary (exclusive) — 1 tick."""
        # 9:45 ET on 2024-01-02 = 14:45 UTC
        bar_ts = datetime(2024, 1, 2, 14, 45, tzinfo=_UTC)
        bar = _make_bar(bar_ts, open_=Decimal("471.50"))
        executor = PaperExecutor("SPY")
        signal = _make_signal()
        decision = _make_decision()
        fill = await executor.fill_entry(signal, decision, bar)
        assert fill.slippage_ticks == 1
        # SPY tick_size=0.01; 1 tick = 0.01; long fill = open + 0.01
        assert fill.fill_price == Decimal("471.51")

    async def test_1030_et_bar_uses_1_tick_slippage(self):
        """A bar at 10:30 ET is off-peak — 1 tick slippage."""
        # 10:30 ET on 2024-01-02 = 15:30 UTC
        bar_ts = datetime(2024, 1, 2, 15, 30, tzinfo=_UTC)
        bar = _make_bar(bar_ts, open_=Decimal("471.50"))
        executor = PaperExecutor("SPY")
        signal = _make_signal()
        decision = _make_decision()
        fill = await executor.fill_entry(signal, decision, bar)
        assert fill.slippage_ticks == 1

    async def test_dst_edt_930_bar_uses_2_tick_slippage(self):
        """DST-spring-forward day (2026-03-08): 9:30 EDT = 13:30 UTC — 2 ticks."""
        # 2026-03-08 is spring-forward day (EST→EDT). 9:30 EDT = UTC-4 = 13:30 UTC
        bar_ts = datetime(2026, 3, 9, 13, 30, tzinfo=_UTC)
        bar = _make_bar(bar_ts, open_=Decimal("471.50"))
        executor = PaperExecutor("SPY")
        signal = _make_signal()
        decision = _make_decision()
        fill = await executor.fill_entry(signal, decision, bar)
        assert fill.slippage_ticks == 2

    async def test_dst_edt_945_bar_uses_1_tick_slippage(self):
        """DST-spring-forward day: 9:45 EDT = 13:45 UTC — 1 tick (boundary exclusive)."""
        bar_ts = datetime(2026, 3, 9, 13, 45, tzinfo=_UTC)
        bar = _make_bar(bar_ts, open_=Decimal("471.50"))
        executor = PaperExecutor("SPY")
        signal = _make_signal()
        decision = _make_decision()
        fill = await executor.fill_entry(signal, decision, bar)
        assert fill.slippage_ticks == 1


# ---------------------------------------------------------------------------
# Entry fill
# ---------------------------------------------------------------------------

class TestEntryFill:
    """Verify fill_entry produces correct Fill fields."""

    async def test_long_fill_price_open_plus_slippage(self):
        """Long entry: fill_price = next_bar.open + tick_size * slippage_ticks."""
        bar_ts = datetime(2024, 1, 2, 14, 30, tzinfo=_UTC)  # 9:30 ET = 2 ticks
        bar = _make_bar(bar_ts, open_=Decimal("471.50"))
        executor = PaperExecutor("SPY")
        signal = _make_signal(side="long")
        decision = _make_decision(adjusted_size=1)
        fill = await executor.fill_entry(signal, decision, bar)
        # SPY tick_size=0.01; 2 ticks = 0.02; long = open + 0.02
        assert fill.fill_price == Decimal("471.52")

    async def test_short_fill_price_open_minus_slippage(self):
        """Short entry: fill_price = next_bar.open - tick_size * slippage_ticks."""
        bar_ts = datetime(2024, 1, 2, 14, 30, tzinfo=_UTC)  # 9:30 ET = 2 ticks
        bar = _make_bar(bar_ts, open_=Decimal("471.50"))
        executor = PaperExecutor("SPY")
        signal = _make_signal(side="short")
        decision = _make_decision(adjusted_size=1)
        fill = await executor.fill_entry(signal, decision, bar)
        # SPY tick_size=0.01; 2 ticks = 0.02; short = open - 0.02
        assert fill.fill_price == Decimal("471.48")

    async def test_es_1_tick_slippage_fills_correctly(self):
        """ES (tick_size=0.25): long fill at 10:30 ET = open + 0.25 (1 tick)."""
        bar_ts = datetime(2024, 1, 2, 15, 30, tzinfo=_UTC)  # 10:30 ET = 1 tick
        bar = _make_bar(bar_ts, open_=Decimal("471.50"), symbol="ES")
        executor = PaperExecutor("ES")
        signal = _make_signal()
        decision = _make_decision(adjusted_size=1)
        fill = await executor.fill_entry(signal, decision, bar)
        # ES tick_size=0.25; 1 tick = 0.25; long = open + 0.25
        assert fill.fill_price == Decimal("471.75")

    async def test_fill_fields_correct(self):
        """fill_entry sets signal_id, fill_qty, side, ts_utc correctly."""
        bar_ts = datetime(2024, 1, 2, 15, 30, tzinfo=_UTC)
        bar = _make_bar(bar_ts)
        executor = PaperExecutor("SPY")
        signal = _make_signal(side="long")
        decision = _make_decision(adjusted_size=2)
        fill = await executor.fill_entry(signal, decision, bar)
        assert fill.signal_id == signal.signal_id
        assert fill.fill_qty == 2
        assert fill.side == "long"
        assert fill.ts_utc == bar.ts_utc

    async def test_fill_is_Fill_instance(self):
        """fill_entry returns a Fill instance."""
        bar_ts = datetime(2024, 1, 2, 15, 30, tzinfo=_UTC)
        bar = _make_bar(bar_ts)
        executor = PaperExecutor("SPY")
        signal = _make_signal()
        decision = _make_decision()
        fill = await executor.fill_entry(signal, decision, bar)
        assert isinstance(fill, Fill)


# ---------------------------------------------------------------------------
# Intrabar stop/target conflict (D-12)
# ---------------------------------------------------------------------------

class TestIntrabarConflict:
    """D-12: stop-first when both stop and target touched on same bar."""

    # Signal: long, stop=470.25, target=472.50
    _stop = Decimal("470.25")
    _target = Decimal("472.50")

    def _executor(self) -> PaperExecutor:
        return PaperExecutor("SPY")

    def _bar(self, low_: Decimal, high: Decimal, ts_utc: datetime | None = None) -> Bar:
        ts = ts_utc or datetime(2024, 1, 2, 15, 30, tzinfo=_UTC)
        return _make_bar(ts, low_=low_, high=high)

    def test_stop_hit_only_returns_stop(self):
        """Bar (low=470.00, high=471.00) → stop hit only → exit_reason='stop'."""
        executor = self._executor()
        bar = _make_bar(
            datetime(2024, 1, 2, 15, 30, tzinfo=_UTC),
            low_=Decimal("470.00"),
            high=Decimal("471.00"),
        )
        result = executor.check_exit(
            side="long",
            entry_price=Decimal("471.00"),
            stop=self._stop,
            target=self._target,
            bar=bar,
            is_last_rth_bar=False,
        )
        assert result is not None
        exit_reason, exit_price = result
        assert exit_reason == "stop"
        # fill_price = stop - tick_size * slippage_ticks (adverse long exit)
        # SPY tick_size=0.01, 1 tick (off-peak 10:30 ET)
        assert exit_price == Decimal("470.24")  # 470.25 - 0.01

    def test_target_hit_only_returns_target(self):
        """Bar (low=471.00, high=472.75) → target hit only → exit_reason='target'."""
        executor = self._executor()
        bar = _make_bar(
            datetime(2024, 1, 2, 15, 30, tzinfo=_UTC),
            low_=Decimal("471.00"),
            high=Decimal("472.75"),
        )
        result = executor.check_exit(
            side="long",
            entry_price=Decimal("471.00"),
            stop=self._stop,
            target=self._target,
            bar=bar,
            is_last_rth_bar=False,
        )
        assert result is not None
        exit_reason, exit_price = result
        assert exit_reason == "target"
        # fill_price = target - tick_size * slippage_ticks (adverse long exit)
        # SPY tick_size=0.01, 1 tick (off-peak 10:30 ET)
        assert exit_price == Decimal("472.49")  # 472.50 - 0.01

    def test_both_hit_stop_wins_d12(self):
        """Bar (low=470.00, high=472.75) → both hit → exit_reason='stop' (D-12)."""
        executor = self._executor()
        bar = _make_bar(
            datetime(2024, 1, 2, 15, 30, tzinfo=_UTC),
            low_=Decimal("470.00"),
            high=Decimal("472.75"),
        )
        result = executor.check_exit(
            side="long",
            entry_price=Decimal("471.00"),
            stop=self._stop,
            target=self._target,
            bar=bar,
            is_last_rth_bar=False,
        )
        assert result is not None
        exit_reason, exit_price = result
        assert exit_reason == "stop", (
            f"D-12: stop must win when both stop and target touched. Got: {exit_reason}"
        )

    def test_neither_hit_returns_none(self):
        """Bar (low=470.75, high=471.50) → neither touched → returns None."""
        executor = self._executor()
        bar = _make_bar(
            datetime(2024, 1, 2, 15, 30, tzinfo=_UTC),
            low_=Decimal("470.75"),
            high=Decimal("471.50"),
        )
        result = executor.check_exit(
            side="long",
            entry_price=Decimal("471.00"),
            stop=self._stop,
            target=self._target,
            bar=bar,
            is_last_rth_bar=False,
        )
        assert result is None

    def test_short_stop_hit_only(self):
        """Short position: stop hit when bar.high >= stop → exit_reason='stop'."""
        # Short signal: stop=472.50 (above), target=469.00 (below)
        executor = self._executor()
        bar = _make_bar(
            datetime(2024, 1, 2, 15, 30, tzinfo=_UTC),
            low_=Decimal("471.00"),
            high=Decimal("473.00"),
        )
        result = executor.check_exit(
            side="short",
            entry_price=Decimal("471.50"),
            stop=Decimal("472.50"),
            target=Decimal("469.00"),
            bar=bar,
            is_last_rth_bar=False,
        )
        assert result is not None
        exit_reason, _ = result
        assert exit_reason == "stop"

    def test_short_both_hit_stop_wins_d12(self):
        """Short: both stop and target touched → stop wins (D-12)."""
        executor = self._executor()
        bar = _make_bar(
            datetime(2024, 1, 2, 15, 30, tzinfo=_UTC),
            low_=Decimal("468.00"),
            high=Decimal("473.00"),
        )
        result = executor.check_exit(
            side="short",
            entry_price=Decimal("471.50"),
            stop=Decimal("472.50"),
            target=Decimal("469.00"),
            bar=bar,
            is_last_rth_bar=False,
        )
        assert result is not None
        exit_reason, _ = result
        assert exit_reason == "stop", "D-12: stop must win for short positions too"


# ---------------------------------------------------------------------------
# EOD flatten (BT-08)
# ---------------------------------------------------------------------------

class TestEODFlatten:
    """BT-08: is_last_rth_bar=True → exit_reason='eod_flat', fill_price=bar.close."""

    async def test_eod_flat_exit_reason(self):
        """check_exit returns ('eod_flat', bar.close) on is_last_rth_bar=True."""
        executor = PaperExecutor("SPY")
        bar = _make_bar(
            datetime(2024, 1, 2, 20, 59, tzinfo=_UTC),  # 15:59 ET = last RTH bar
            low_=Decimal("471.00"),
            high=Decimal("471.20"),
            close=Decimal("471.15"),
        )
        result = executor.check_exit(
            side="long",
            entry_price=Decimal("471.00"),
            stop=Decimal("470.00"),
            target=Decimal("473.00"),
            bar=bar,
            is_last_rth_bar=True,
        )
        assert result is not None
        exit_reason, exit_price = result
        assert exit_reason == "eod_flat"
        # EOD flat fills at close — no slippage applied per Phase 3 spec
        assert exit_price == Decimal("471.15")

    async def test_sum_of_positions_is_zero(self):
        """Entry + EOD-flat exit: net signed qty sums to zero."""
        bars = _orb_day_bars()
        executor = PaperExecutor("SPY")
        signal = _make_signal()
        decision = _make_decision(adjusted_size=1)

        # Entry fill at bar[16] (next-bar after breakout bar[15])
        entry_bar = bars[16]
        entry_fill = await executor.fill_entry(signal, decision, entry_bar)

        # EOD flat exit at last bar
        last_bar = bars[-1]
        eod_result = executor.check_exit(
            side="long",
            entry_price=entry_fill.fill_price,
            stop=signal.stop,
            target=signal.target,
            bar=last_bar,
            is_last_rth_bar=True,
        )
        assert eod_result is not None
        _, exit_price = eod_result

        exit_fill = await executor.fill_exit(
            signal=signal,
            exit_reason="eod_flat",
            exit_price=exit_price,
            exit_ts_utc=last_bar.ts_utc,
            fill_qty=entry_fill.fill_qty,
        )

        # Long entry = +qty, exit side = "short" = -qty; net = 0
        fills = [entry_fill, exit_fill]
        # Entry fill has side="long" (+), exit fill has side="short" (-)
        net = sum(
            f.fill_qty if f.side == "long" else -f.fill_qty
            for f in fills
        )
        assert net == 0, f"Expected sum of positions == 0, got {net}"

    async def test_eod_flat_slippage_ticks_is_zero(self):
        """EOD-flat fill has slippage_ticks=0 (no adverse adjustment on market close)."""
        bars = _orb_day_bars()
        executor = PaperExecutor("SPY")
        signal = _make_signal()

        last_bar = bars[-1]
        exit_fill = await executor.fill_exit(
            signal=signal,
            exit_reason="eod_flat",
            exit_price=last_bar.close,
            exit_ts_utc=last_bar.ts_utc,
            fill_qty=1,
        )
        assert exit_fill.slippage_ticks == 0

    async def test_eod_flat_takes_priority_over_neither_hit(self):
        """When no stop/target touched but is_last_rth_bar=True → eod_flat."""
        executor = PaperExecutor("SPY")
        bar = _make_bar(
            datetime(2024, 1, 2, 20, 59, tzinfo=_UTC),
            low_=Decimal("471.10"),  # above stop
            high=Decimal("471.40"),  # below target
            close=Decimal("471.20"),
        )
        result = executor.check_exit(
            side="long",
            entry_price=Decimal("471.00"),
            stop=Decimal("470.25"),
            target=Decimal("472.50"),
            bar=bar,
            is_last_rth_bar=True,
        )
        assert result is not None
        exit_reason, _ = result
        assert exit_reason == "eod_flat"
