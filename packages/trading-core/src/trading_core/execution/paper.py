"""PaperExecutor — next-bar fill simulation for Phase 3 backtesting.

Implements:
  - fill_entry(signal, decision, next_bar) → Fill
    Fill price = next_bar.open ± session-phase-aware slippage (adverse direction).
  - check_exit(side, entry_price, stop, target, bar, is_last_rth_bar) → (reason, price) | None
    Stop-first conflict resolution when both stop and target touched (D-12).
    EOD flatten when is_last_rth_bar=True (BT-08).
  - fill_exit(signal, exit_reason, exit_price, exit_ts_utc, fill_qty) → Fill

Session-phase slippage (Architectural Responsibility Map — instruments.py is SoT):
  - 9:30–9:45 ET window (exclusive end): 2 ticks adverse (≥1.5 ticks spec; 2 is integer)
  - Outside that window: 1 tick adverse (off-peak default; 0.5 rounded up to 1)
  - EOD flatten: 0 ticks (fills at bar.close, no adverse adjustment needed)

Architectural responsibility:
  - PaperExecutor does NOT own calendar logic (is_last_rth_bar is caller's responsibility)
  - All price math uses Decimal — no float() in the price path (T-03-02-04)
  - tick_size sourced exclusively from instruments.py (T-03-02-03)

NOTE: exit_reason='target' on entry fills is a sentinel — entry fills use this
as a placeholder because Fill.exit_reason is a Literal that requires one of the
four values. The driver loop in Plan 03 distinguishes entry fills from exit fills
by maintaining separate lists. Phase 5 may split entry/exit into separate models.
See 03-02-SUMMARY.md §Known Debt for the Phase 5 refinement item.
"""

from __future__ import annotations

from datetime import time as dt_time
from decimal import Decimal
from zoneinfo import ZoneInfo

from trading_core.data.models import Bar
from trading_core.execution.models import Fill
from trading_core.instruments import get as get_instrument
from trading_core.logging import get_logger
from trading_core.risk.models import RiskDecision
from trading_core.strategy.models import Signal

log = get_logger(__name__)

_ET = ZoneInfo("America/New_York")

# Session open window: [9:30, 9:45) ET — higher slippage due to spread widening
_OPEN_WINDOW_START = dt_time(9, 30)
_OPEN_WINDOW_END = dt_time(9, 45)

# Slippage constants
_OPEN_WINDOW_SLIPPAGE_TICKS = 2  # >= 1.5 ticks adverse during 9:30-9:45 ET (FR-1 pitfall)
_OFF_PEAK_SLIPPAGE_TICKS = 1  # off-peak default (0.5 rounded up to integer 1)


def _slippage_ticks(bar_ts_utc, symbol: str) -> int:  # noqa: ARG001
    """Session-phase-aware slippage ticks.

    Returns 2 during 9:30-9:45 ET open window, 1 off-peak.
    The symbol parameter is accepted but not currently used (tick_size comes
    from instruments.py in the caller).

    Args:
        bar_ts_utc: tz-aware UTC timestamp of the bar.
        symbol:     Instrument symbol (unused; kept for future per-instrument tuning).

    Returns:
        int: slippage ticks (2 or 1).
    """
    et_time = bar_ts_utc.astimezone(_ET).time()
    if _OPEN_WINDOW_START <= et_time < _OPEN_WINDOW_END:
        return _OPEN_WINDOW_SLIPPAGE_TICKS
    return _OFF_PEAK_SLIPPAGE_TICKS


class PaperExecutor:
    """Paper-fill executor for Phase 3 backtesting.

    Simulates next-bar-open entry fills with session-phase-aware slippage.
    Stop-first intrabar conflict resolution (D-12). EOD flatten support (BT-08).

    Structurally satisfies the Executor Protocol via fill_entry (the Protocol
    signature is fill(signal, decision) → Fill; fill_entry extends this with the
    next_bar arg required by the backtester driver loop).
    """

    def __init__(self, symbol: str) -> None:
        self._symbol = symbol
        self._instrument = get_instrument(symbol)

    async def fill_entry(
        self,
        signal: Signal,
        decision: RiskDecision,
        next_bar: Bar,
    ) -> Fill:
        """Simulate an entry fill at next_bar.open with adverse slippage.

        Adverse direction:
          - Long: buy higher → fill_price = next_bar.open + slippage_adj
          - Short: sell lower → fill_price = next_bar.open - slippage_adj

        exit_reason='target' is a sentinel (not exit semantics) — see module docstring.

        Args:
            signal:   The trading signal that triggered the entry.
            decision: Risk manager's decision (approved=True, adjusted_size).
            next_bar: The bar following the signal bar (next-bar open execution).

        Returns:
            Fill with fill_price, fill_qty, slippage_ticks set correctly.
        """
        ticks = _slippage_ticks(next_bar.ts_utc, self._symbol)
        adj = self._instrument.tick_size * Decimal(ticks)

        if signal.side == "long":
            fill_price = next_bar.open + adj  # adverse: pay more on entry
        else:
            fill_price = next_bar.open - adj  # adverse: receive less on entry

        log.debug(
            "executor.fill_entry",
            signal_id=signal.signal_id,
            side=signal.side,
            fill_price=str(fill_price),
            slippage_ticks=ticks,
            next_bar_open=str(next_bar.open),
        )

        return Fill(
            signal_id=signal.signal_id,
            fill_price=fill_price,
            fill_qty=decision.adjusted_size,
            side=signal.side,
            slippage_ticks=ticks,
            ts_utc=next_bar.ts_utc,
            exit_reason="target",  # sentinel — entry fills use 'target' as placeholder (D-11)
        )

    def check_exit(
        self,
        *,
        side: str,
        entry_price: Decimal,
        stop: Decimal,
        target: Decimal,
        bar: Bar,
        is_last_rth_bar: bool,
    ) -> tuple[str, Decimal] | None:
        """Check whether the open position should exit on this bar.

        Priority order:
          1. Stop hit (or both stop+target) → 'stop' (D-12: conservative/worst-case)
          2. Target hit only → 'target'
          3. is_last_rth_bar=True → 'eod_flat' (BT-08)
          4. Nothing → None

        Caller owns calendar logic (is_last_rth_bar computation). PaperExecutor
        does NOT compute session boundaries — Architectural Responsibility Map.

        Args:
            side:           Position side ('long' or 'short').
            entry_price:    Entry fill price (used for future slippage calc if needed).
            stop:           Stop-loss price level.
            target:         Take-profit price level.
            bar:            Current bar to check.
            is_last_rth_bar: True if this is the last bar of the RTH session.

        Returns:
            (exit_reason, exit_price) tuple, or None if no exit triggered.
        """
        ticks = _slippage_ticks(bar.ts_utc, self._symbol)
        adj = self._instrument.tick_size * Decimal(ticks)

        if side == "long":
            hit_stop = bar.low <= stop
            hit_target = bar.high >= target

            if hit_stop:
                # D-12: stop wins even when both touched on same bar
                # Adverse fill: exit long = sell → fill below stop level
                exit_price = stop - adj
                log.debug(
                    "executor.check_exit.stop",
                    side=side,
                    stop=str(stop),
                    exit_price=str(exit_price),
                    hit_target=hit_target,
                )
                return ("stop", exit_price)

            if hit_target:
                # Target hit only; adverse fill: exit long = sell → fill below target
                exit_price = target - adj
                log.debug(
                    "executor.check_exit.target",
                    side=side,
                    target=str(target),
                    exit_price=str(exit_price),
                )
                return ("target", exit_price)

        else:  # short
            hit_stop = bar.high >= stop
            hit_target = bar.low <= target

            if hit_stop:
                # D-12: stop wins for short too
                # Adverse fill: exit short = buy → fill above stop level
                exit_price = stop + adj
                log.debug(
                    "executor.check_exit.stop",
                    side=side,
                    stop=str(stop),
                    exit_price=str(exit_price),
                    hit_target=hit_target,
                )
                return ("stop", exit_price)

            if hit_target:
                # Target hit only; adverse fill: exit short = buy → fill above target
                exit_price = target + adj
                log.debug(
                    "executor.check_exit.target",
                    side=side,
                    target=str(target),
                    exit_price=str(exit_price),
                )
                return ("target", exit_price)

        # No stop or target hit; check EOD flatten last
        if is_last_rth_bar:
            # BT-08: EOD flatten at close price, no slippage applied
            log.debug(
                "executor.check_exit.eod_flat",
                side=side,
                close=str(bar.close),
            )
            return ("eod_flat", bar.close)

        return None

    async def fill_exit(
        self,
        *,
        signal: Signal,
        exit_reason: str,
        exit_price: Decimal,
        exit_ts_utc,
        fill_qty: int,
    ) -> Fill:
        """Build a Fill record for an exit.

        The exit Fill has the opposite side from the entry:
          - Long entry exit → side='short'
          - Short entry exit → side='long'

        slippage_ticks for EOD flat is 0 (fill price is bar.close, no adj applied).

        Args:
            signal:       Original entry signal (for signal_id).
            exit_reason:  'stop' | 'target' | 'eod_flat' | 'manual'.
            exit_price:   Computed exit fill price (already includes adverse adj).
            exit_ts_utc:  tz-aware UTC timestamp of the exit bar.
            fill_qty:     Number of contracts being exited.

        Returns:
            Fill for the exit.
        """
        exit_side = "short" if signal.side == "long" else "long"

        # For EOD flat, no slippage was applied to exit_price (it's bar.close)
        if exit_reason == "eod_flat":
            slippage_ticks = 0
        else:
            slippage_ticks = _slippage_ticks(exit_ts_utc, self._symbol)

        log.debug(
            "executor.fill_exit",
            signal_id=signal.signal_id,
            exit_reason=exit_reason,
            exit_price=str(exit_price),
            exit_side=exit_side,
            slippage_ticks=slippage_ticks,
        )

        return Fill(
            signal_id=signal.signal_id,
            fill_price=exit_price,
            fill_qty=fill_qty,
            side=exit_side,
            slippage_ticks=slippage_ticks,
            ts_utc=exit_ts_utc,
            exit_reason=exit_reason,  # type: ignore[arg-type]
        )
