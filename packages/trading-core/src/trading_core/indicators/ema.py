"""Exponential Moving Average indicator — look-ahead-safe.

First value (when history == period): simple mean of first `period` closes.
Subsequent: close * multiplier + prev_ema * (1 - multiplier)
where multiplier = 2 / (period + 1).

Uses Decimal arithmetic. warmup_bars = period.
"""

from __future__ import annotations

from decimal import Decimal

from trading_core.data.models import Bar
from trading_core.indicators.base import IndicatorBase


class EMA(IndicatorBase):
    """Exponential Moving Average with configurable period."""

    def __init__(self, period: int = 20) -> None:
        super().__init__()
        self._period = period
        self._multiplier = Decimal("2") / Decimal(period + 1)

    def warmup_bars(self) -> int:
        return self._period

    def _compute_current(self) -> Decimal | None:
        n = len(self._bars)
        if n < self._period:
            return None

        if n == self._period:
            # Initial EMA: SMA of first `period` closes
            closes = [b.close for b in self._bars]
            return sum(closes, Decimal("0")) / Decimal(self._period)

        # Incremental: use stored previous EMA
        prev_ema = self._values[-1]
        if prev_ema is None:
            # Recompute SMA seed (defensive, handles edge cases)
            closes = [b.close for b in self._bars[: self._period]]
            prev_ema = sum(closes, Decimal("0")) / Decimal(self._period)

        close = self._bars[-1].close
        return close * self._multiplier + prev_ema * (Decimal("1") - self._multiplier)
