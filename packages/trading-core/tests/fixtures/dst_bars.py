"""Synthetic OHLCV fixtures for DST transitions + CME half-day + rollover seams.

The factories produce DataFrames whose UTC index spans the RTH window for the
given day. They are intentionally minimal — fixed OHLC values — because their
purpose is to lock the *bar count* and the *timestamp set*, not the prices.

DST date facts (computed at module import via zoneinfo and re-asserted by
test_rth_filter.py):

- 2026-03-08 is a Sunday — non-trading. The spring-forward effect (02:00 EST →
  03:00 EDT on Sun 03-08) is observed on the FIRST trading day after the
  switch, which is Mon 2026-03-09. RTH on Mar 9 starts at 13:30 UTC (= 09:30
  EDT).

- 2026-11-01 is a Sunday — non-trading. The fall-back effect (02:00 EDT →
  01:00 EST on Sun 11-01) is observed on the FIRST trading day after the
  switch, which is Mon 2026-11-02. RTH on Nov 2 starts at 14:30 UTC (= 09:30
  EST) — note the offset differs from the Mar 9 fixture by exactly one hour.

- 2024-11-29 (Black Friday): CME_Equity + NYSE half-day; cash close at 13:00
  ET (= 18:00 UTC). The bar count is 210 (= 3.5 hours × 60), NOT 390.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pandas as pd

ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")


def _build_minute_bars(
    *,
    symbol: str,
    open_utc: datetime,
    close_utc: datetime,
) -> pd.DataFrame:
    """Build a 1m OHLCV DataFrame whose UTC index is [open_utc, close_utc).

    Synthetic prices: open=high=low=close=100.00; volume=1000. Tests only need
    a real index — they assert against bar count and timestamp positions, not
    price values.
    """
    idx = pd.date_range(open_utc, close_utc, freq="1min", inclusive="left", tz="UTC")
    n = len(idx)
    df = pd.DataFrame(
        {
            "symbol": [symbol] * n,
            "timeframe": ["1m"] * n,
            "open": [Decimal("100.00")] * n,
            "high": [Decimal("100.00")] * n,
            "low": [Decimal("100.00")] * n,
            "close": [Decimal("100.00")] * n,
            "volume": [1000] * n,
        },
        index=idx,
    )
    df.index.name = "ts_utc"
    return df


def make_synthetic_spy_day_bars(day: date, *, symbol: str = "SPY") -> pd.DataFrame:
    """Generic 390-row 1m RTH fixture for `day`. Day must be a trading day.

    Used as the baseline for tests that don't care about DST — they just want
    "a synthetic RTH day with 390 bars."
    """
    open_et = datetime.combine(day, datetime.min.time()).replace(
        hour=9, minute=30, tzinfo=ET
    )
    close_et = datetime.combine(day, datetime.min.time()).replace(
        hour=16, minute=0, tzinfo=ET
    )
    return _build_minute_bars(
        symbol=symbol,
        open_utc=open_et.astimezone(UTC),
        close_utc=close_et.astimezone(UTC),
    )


def make_dst_spring_forward_2026_03_09_bars() -> pd.DataFrame:
    """Monday after the 2026 spring-forward (Sun 2026-03-08).

    On 2026-03-09 the US is in EDT (UTC-04:00). RTH window:
        09:30 EDT = 13:30 UTC  →  16:00 EDT = 20:00 UTC
    Length: 390 minutes.
    """
    return make_synthetic_spy_day_bars(date(2026, 3, 9))


def make_dst_fall_back_2026_11_02_bars() -> pd.DataFrame:
    """Monday after the 2026 fall-back (Sun 2026-11-01).

    On 2026-11-02 the US is back on EST (UTC-05:00). RTH window:
        09:30 EST = 14:30 UTC  →  16:00 EST = 21:00 UTC
    Length: 390 minutes.

    The UTC start differs from Mar 9 by exactly one hour — that is the entire
    point of this fixture (proves UTC-monotonic storage + ET-derived view).
    """
    return make_synthetic_spy_day_bars(date(2026, 11, 2))


def make_cme_half_day_2024_11_29_bars() -> pd.DataFrame:
    """Black Friday 2024 — CME_Equity + NYSE half-day, cash close at 13:00 ET.

    RTH window: 09:30 ET (= 14:30 UTC, EST) → 13:00 ET (= 18:00 UTC, EST).
    Length: 3.5 hours × 60 = 210 minutes. RthFilter must NOT return 390.
    """
    day = date(2024, 11, 29)
    open_et = datetime.combine(day, datetime.min.time()).replace(
        hour=9, minute=30, tzinfo=ET
    )
    close_et = datetime.combine(day, datetime.min.time()).replace(
        hour=13, minute=0, tzinfo=ET
    )
    return _build_minute_bars(
        symbol="SPY",
        open_utc=open_et.astimezone(UTC),
        close_utc=close_et.astimezone(UTC),
    )


def make_eth_bars_2024_06_12() -> pd.DataFrame:
    """One day of synthetic ETH-only 1m bars (NOT inside the RTH window).

    Used to prove `RthFilter.filter` correctly excludes everything when fed
    only ETH bars. The index spans 00:00–13:29 UTC on 2024-06-12 (= 20:00 ET
    prev day through 09:29 ET) — 100% pre-open, 100% ETH.
    """
    day = date(2024, 6, 12)
    open_utc = datetime(day.year, day.month, day.day, 0, 0, tzinfo=UTC)
    close_utc = datetime(day.year, day.month, day.day, 13, 30, tzinfo=UTC)
    return _build_minute_bars(
        symbol="SPY",
        open_utc=open_utc,
        close_utc=close_utc,
    )
