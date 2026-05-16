"""Wilder's ATR indicator — look-ahead-safe incremental implementation.

Uses Decimal arithmetic throughout. No float() in the price computation path.

warmup_bars = period + 1:
    Bar 0 has no prev_close so can't compute TR. Bar 1 gives TR_1.
    The first SMA uses TRs from bars[1..period] (period TRs), which requires
    bars[0..period] to be present — i.e. period+1 bars total.
"""

from __future__ import annotations

from decimal import Decimal

from trading_core.data.models import Bar
from trading_core.indicators.base import IndicatorBase


class ATRWilder(IndicatorBase):
    """Wilder's smoothed Average True Range.

    True Range at bar i (i >= 1):
        max(high_i - low_i,
            |high_i - close_{i-1}|,
            |low_i  - close_{i-1}|)

    First ATR value (when len == period+1): simple mean of TR[1..period].
    Subsequent: (prev_atr * (period-1) + tr) / period.
    """

    def __init__(self, period: int = 14) -> None:
        super().__init__()
        self._period = period

    def warmup_bars(self) -> int:
        return self._period + 1

    def _compute_current(self) -> Decimal | None:
        bars = self._bars
        n = len(bars)
        if n < self._period + 1:
            return None

        # Compute all TRs from index 1 onwards
        def _tr(i: int) -> Decimal:
            h = bars[i].high
            lo = bars[i].low
            pc = bars[i - 1].close
            return max(h - lo, abs(h - pc), abs(lo - pc))

        if n == self._period + 1:
            # Initial: SMA of TR[1..period]
            trs = [_tr(i) for i in range(1, self._period + 1)]
            return sum(trs, Decimal("0")) / Decimal(self._period)

        # Subsequent: Wilder smoothing
        prev_atr = self._values[-1]  # value from the previous push
        if prev_atr is None:
            # Should not happen if warmup logic is correct, but guard anyway
            trs = [_tr(i) for i in range(1, self._period + 1)]
            return sum(trs, Decimal("0")) / Decimal(self._period)
        tr_now = _tr(n - 1)
        return (prev_atr * Decimal(self._period - 1) + tr_now) / Decimal(self._period)
