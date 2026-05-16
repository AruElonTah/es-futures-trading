"""Average Daily Range indicator (Plan 02-01).

Resamples accumulated 1m bars to daily OHLC using pandas, then computes a
rolling mean of daily ranges. BL-3 invariant: daily_ranges.shift(1) ensures
today's partial range never leaks into today's ADR reading.

The pandas resampling uses float internally (Decimal→float→Decimal round-trip
at the boundary) — this is acceptable per CLAUDE.md: "ADR resampler may use
pandas float internally with explicit Decimal round-trip at the boundary."

warmup_bars = (period + 1) * 390: conservative upper bound requiring at least
period+1 complete trading days. Actual warmup depends on session structure.
"""

from __future__ import annotations

from decimal import Decimal

import pandas as pd

from trading_core.data.models import Bar
from trading_core.indicators.base import IndicatorBase


class ADR(IndicatorBase):
    """Average Daily Range over `period` complete trading days.

    BL-3 (look-ahead prevention for HTF features):
        After resampling 1m bars to daily OHLC, shift the range series by 1
        day before computing the rolling mean. Today's partial bar range is
        therefore never included in today's ADR reading.
    """

    def __init__(self, period: int = 10) -> None:
        super().__init__()
        self._period = period

    def warmup_bars(self) -> int:
        # Need period+1 complete days (for the shift to give period values)
        return (self._period + 1) * 390

    def _compute_current(self) -> Decimal | None:
        bars = self._bars
        if len(bars) < 2:
            return None

        # Build DataFrame with float high/low for pandas resampling
        df = pd.DataFrame(
            {
                "ts_utc": [b.ts_utc for b in bars],
                "high": [float(b.high) for b in bars],
                "low": [float(b.low) for b in bars],
            }
        )
        df = df.set_index("ts_utc")
        df.index = pd.DatetimeIndex(df.index, tz="UTC")

        # Resample to daily in ET so session boundaries align with trading days
        daily = (
            df.tz_convert("America/New_York")
            .resample("1D")
            .agg({"high": "max", "low": "min"})
            .dropna()
        )
        daily["range"] = daily["high"] - daily["low"]

        # BL-3: shift by 1 day so today's partial range never appears in ADR
        adr_series = daily["range"].shift(1).rolling(self._period).mean()

        if len(adr_series) == 0 or pd.isna(adr_series.iloc[-1]):
            return None

        return Decimal(str(round(adr_series.iloc[-1], 4)))
