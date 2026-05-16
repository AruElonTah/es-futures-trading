"""Session VWAP indicator — resets on ET calendar date boundary.

Typical price = (high + low + close) / 3.
VWAP = cumulative(tp * volume) / cumulative(volume).

Resets to zero accumulator when the ET date of the current bar differs
from the previous bar's ET date (session boundary crossing).

Uses Decimal arithmetic. warmup_bars = 1 (valid from the first bar).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from zoneinfo import ZoneInfo

from trading_core.data.models import Bar
from trading_core.indicators.base import IndicatorBase

_ET = ZoneInfo("America/New_York")


class SessionVWAP(IndicatorBase):
    """Intraday Volume-Weighted Average Price, resetting per RTH session."""

    def __init__(self) -> None:
        super().__init__()
        self._cum_tpv: Decimal = Decimal("0")
        self._cum_vol: Decimal = Decimal("0")
        self._last_date: date | None = None

    def warmup_bars(self) -> int:
        return 1

    def _compute_current(self) -> Decimal | None:
        bar = self._bars[-1]
        bar_date: date = bar.ts_utc.astimezone(_ET).date()

        if bar_date != self._last_date:
            # New session — reset accumulators
            self._cum_tpv = Decimal("0")
            self._cum_vol = Decimal("0")
            self._last_date = bar_date

        tp = (bar.high + bar.low + bar.close) / Decimal("3")
        self._cum_tpv += tp * Decimal(bar.volume)
        self._cum_vol += Decimal(bar.volume)

        if self._cum_vol == Decimal("0"):
            return None
        return self._cum_tpv / self._cum_vol
