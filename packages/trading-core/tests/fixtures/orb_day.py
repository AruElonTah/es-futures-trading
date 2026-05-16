"""Synthetic Opening Range Breakout day fixture (Plan 02-01).

orb_day_bars() returns 390 Bar objects for one full RTH session with a known
ORB structure:
  - Bars 0-14 (opening range): oscillate between 470.50 and 471.00
  - Bar 15 (breakout): close = 471.25 > ORB high (471.00), volume = 50000
  - Bars 16-389: trend up then retrace at 471.25, volume = 1000

The data_hash of the 390-bar list is deterministic (same date_str = same hash).

rollover_seam_day_bars() wraps orb_day_bars() with bar[0].rollover_seam=True
to simulate a 3rd-Friday rollover opening.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pandas as pd

from trading_core.data.models import Bar

_UTC = timezone.utc


def orb_day_bars(
    symbol: str = "SPY",
    date_str: str = "2024-01-02",
) -> list[Bar]:
    """Return 390 Bar objects for one RTH session on `date_str`.

    RTH: 09:30-16:00 ET = 14:30-21:00 UTC on a standard EST day (Jan 2 = EST).
    """
    # 2024-01-02 is in EST (UTC-5). 09:30 ET = 14:30 UTC.
    year, month, day = (int(x) for x in date_str.split("-"))
    open_utc = datetime(year, month, day, 14, 30, tzinfo=_UTC)

    # Generate 390 minute timestamps
    timestamps = pd.date_range(open_utc, periods=390, freq="1min", tz="UTC")

    bars: list[Bar] = []
    for i, ts in enumerate(timestamps):
        ts_dt = ts.to_pydatetime()

        if i < 15:
            # Opening range bars: oscillate ORB high=471.00, ORB low=470.50
            bar = Bar(
                symbol=symbol,
                timeframe="1m",
                ts_utc=ts_dt,
                open=Decimal("471.00"),
                high=Decimal("471.00"),
                low=Decimal("470.50"),
                close=Decimal("470.75"),
                volume=1000,
                rollover_seam=False,
            )
        elif i == 15:
            # Breakout bar: close > ORB high
            bar = Bar(
                symbol=symbol,
                timeframe="1m",
                ts_utc=ts_dt,
                open=Decimal("471.00"),
                high=Decimal("471.50"),
                low=Decimal("471.00"),
                close=Decimal("471.25"),
                volume=50000,
                rollover_seam=False,
            )
        else:
            # Post-breakout: trend up then retrace
            bar = Bar(
                symbol=symbol,
                timeframe="1m",
                ts_utc=ts_dt,
                open=Decimal("471.25"),
                high=Decimal("471.50"),
                low=Decimal("471.00"),
                close=Decimal("471.25"),
                volume=1000,
                rollover_seam=False,
            )

        bars.append(bar)

    return bars


def rollover_seam_day_bars(symbol: str = "SPY") -> list[Bar]:
    """Same as orb_day_bars() but bar[0].rollover_seam=True.

    Simulates a 3rd-Friday contract rollover day opening.
    Bar is frozen, so we reconstruct bar[0] with rollover_seam=True.
    """
    bars = orb_day_bars(symbol=symbol)
    first = bars[0]
    replacement = Bar(
        symbol=first.symbol,
        timeframe=first.timeframe,
        ts_utc=first.ts_utc,
        open=first.open,
        high=first.high,
        low=first.low,
        close=first.close,
        volume=first.volume,
        rollover_seam=True,
    )
    return [replacement] + bars[1:]
