"""Hybrid RTH window derivation + helpers (Pattern 3) — MD-05.

The load-bearing invariant: every bar that flows into a strategy / backtest
sits inside the 9:30 ET (inclusive) → 16:00 ET (exclusive) cash session for
its instrument, on a real trading day for that instrument's calendar.

Why a hybrid (calendar + manual window)?
    `pandas_market_calendars.get_calendar("CME_Equity").schedule(...)`
    returns the 23-hour Globex electronic session (≈18:00 ET previous day →
    17:00 ET, with a daily break). That is NOT the cash session strategies
    want — using it directly silently corrupts every ORB-style backtest.
    See RESEARCH.md §Pitfall 1 + §Pitfall 3.

    Resolution:
        - The calendar is consulted only for (a) trading-day determination
          (weekends + holidays excluded) and (b) early-close half-day reads.
        - The cash-session times come from `instruments.py` (single source of
          truth: `rth_open_et`, `rth_close_et`, `calendar_name`).
        - Result: a 1m bar at 2024-06-12 13:30 UTC (= 09:30 ET) is RTH for
          SPY; the same UTC minute on 2024-07-04 is not (NYSE holiday); the
          1m bar at 2024-11-29 18:30 UTC (= 13:30 ET) is not RTH because the
          calendar's early close is 18:00 UTC (= 13:00 ET).

All timestamps in this module's public surface are tz-aware UTC. Functions
that accept a datetime raise `ValueError` on naive input (T-01-03-03).
"""

from __future__ import annotations

import calendar as _calendar
from collections.abc import Sequence
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import pandas_market_calendars as mcal

from trading_core.instruments import get

# ET / UTC zone constants. Computed once at module load (zoneinfo lookups are
# cheap but doing them per-call is sloppy).
ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")

# Timeframe → pandas freq mapping. Limited to Phase 1's three supported tfs.
_TF_TO_FREQ: dict[str, str] = {"1m": "1min", "5m": "5min", "15m": "15min"}


# ---------------------------------------------------------------------------
# Calendar helpers (Pattern 3 — RESEARCH.md lines 519–604)
# ---------------------------------------------------------------------------


def trading_days(
    calendar_name: str, start: datetime | date, end: datetime | date
) -> pd.DatetimeIndex:
    """Return the trading-day index from the calendar.

    Semantics: half-open `[start, end)` at the calendar-day level.
        - When `start == end` (same date passed to both), the calendar is
          consulted for that single day inclusively (so `is_rth` can ask
          "is today a trading day?" without phantom-empty results).
        - When `end > start`, the schedule call excludes `end.date()` to
          give clean "one trading day per 24-hour UTC window" semantics for
          callers like `expected_rth_timestamps`.

    Output dates are tz-naive `pd.Timestamp` values at midnight. Weekends +
    exchange holidays are excluded. Early-close half-days remain trading days
    (the caller must consult `rth_window_utc` to honor the early close).
    """
    cal = mcal.get_calendar(calendar_name)
    start_d = start.date() if isinstance(start, datetime) else start
    end_d = end.date() if isinstance(end, datetime) else end
    # Exclusive end at the day level for normal ranges. Special-case
    # `start == end` so single-day inclusive queries (`is_rth`) still work.
    if end_d > start_d:
        end_d = end_d - timedelta(days=1)
    sched = cal.schedule(start_date=start_d, end_date=end_d)
    return sched.index


def rth_window_utc(
    calendar_name: str,
    trading_day: date | pd.Timestamp,
    open_et: str,
    close_et: str,
) -> tuple[datetime, datetime]:
    """Build the (open_utc, close_utc) cash-session window for `trading_day`.

    `open_et` and `close_et` are "HH:MM" strings (read from `instruments.py`).
    The window is constructed in ET first (so DST is handled by `zoneinfo`),
    then converted to UTC. If `calendar_name` reports an early close for
    `trading_day` (e.g., Black Friday 13:00 ET cash close), the returned
    close is clamped to that early close.

    Returns:
        Tuple of two tz-aware UTC datetimes. Both are inclusive on the open
        side; `is_rth` treats the close as exclusive (RTH window is half-open
        [open, close)).
    """
    open_h, open_m = map(int, open_et.split(":"))
    close_h, close_m = map(int, close_et.split(":"))

    if isinstance(trading_day, pd.Timestamp):
        day_date = trading_day.date()
    else:
        day_date = trading_day

    open_et_dt = datetime.combine(day_date, time(open_h, open_m), tzinfo=ET)
    close_et_dt = datetime.combine(day_date, time(close_h, close_m), tzinfo=ET)

    # Half-day check: the calendar's market_close for this day may be earlier
    # than our default 16:00 ET close. When it is, the early close wins.
    cal = mcal.get_calendar(calendar_name)
    sched = cal.schedule(start_date=day_date, end_date=day_date)
    if not sched.empty:
        # `market_close` is a tz-aware UTC pd.Timestamp in mcal 5.x.
        market_close_utc = sched.iloc[0]["market_close"]
        # Convert to a stdlib datetime for comparison.
        if isinstance(market_close_utc, pd.Timestamp):
            market_close_utc_dt = market_close_utc.to_pydatetime()
        else:
            market_close_utc_dt = market_close_utc
        if market_close_utc_dt < close_et_dt.astimezone(UTC):
            close_et_dt = market_close_utc_dt.astimezone(ET)

    return open_et_dt.astimezone(UTC), close_et_dt.astimezone(UTC)


def is_rth(ts_utc: datetime, *, instrument_symbol: str) -> bool:
    """True iff `ts_utc` falls inside the cash session for `instrument_symbol`.

    Inclusive on open, exclusive on close. Raises ValueError if `ts_utc` is
    naive (T-01-03-03 — defensive belt over the bar-model AwareDatetime).
    """
    if ts_utc.tzinfo is None:
        raise ValueError("ts must be tz-aware")
    inst = get(instrument_symbol)

    # The trading-day check needs the ET-local date, not the UTC date, because
    # a UTC bar near midnight may belong to either of two ET dates and only
    # one is the right trading day.
    ts_et = ts_utc.astimezone(ET)
    et_date = ts_et.date()
    days = trading_days(inst.calendar_name, et_date, et_date)
    if pd.Timestamp(et_date) not in days:
        return False

    open_utc, close_utc = rth_window_utc(
        inst.calendar_name, et_date, inst.rth_open_et, inst.rth_close_et
    )
    return open_utc <= ts_utc < close_utc


def expected_rth_timestamps(
    symbol: str, timeframe: str, start: datetime, end: datetime
) -> pd.DatetimeIndex:
    """All expected bar-OPEN timestamps inside RTH between [start, end].

    Used by the gap detector (Pattern 4 / MD-07). Output is tz-aware UTC and
    sorted ascending. Spans every trading day from `start.date()` (inclusive)
    to `end.date()` (inclusive); the caller filters further if needed.
    """
    inst = get(symbol)
    if timeframe not in _TF_TO_FREQ:
        raise ValueError(
            f"Unsupported timeframe {timeframe!r}; supported: {sorted(_TF_TO_FREQ)}"
        )
    freq = _TF_TO_FREQ[timeframe]
    days = trading_days(inst.calendar_name, start, end)
    pieces: list[pd.DatetimeIndex] = []
    for d in days:
        o_utc, c_utc = rth_window_utc(
            inst.calendar_name, d.date(), inst.rth_open_et, inst.rth_close_et
        )
        # `inclusive='left'` -> [o_utc, c_utc) -> bar OPEN times only.
        pieces.append(pd.date_range(o_utc, c_utc, freq=freq, inclusive="left"))
    if not pieces:
        return pd.DatetimeIndex([], tz="UTC")
    out = pieces[0]
    for piece in pieces[1:]:
        out = out.append(piece)
    return out


# ---------------------------------------------------------------------------
# RthFilter — DataFrame-level convenience wrapper
# ---------------------------------------------------------------------------


class RthFilter:
    """Apply the RTH window to a tz-aware-UTC-indexed OHLCV DataFrame.

    Phase 1 v1 has no per-instance state. The class exists so that Plan 04
    (TwelveDataSource) can hold a single `RthFilter()` instance and call
    `.filter` / `.find_gaps` against it.
    """

    def filter(self, df: pd.DataFrame, *, symbol: str) -> pd.DataFrame:
        """Return only the rows whose index is inside RTH for `symbol`.

        `df.index` must be tz-aware UTC. Rows are kept in their original
        order. If the input is empty, an empty DataFrame is returned (same
        columns / index dtype).
        """
        if len(df) == 0:
            return df

        # Vectorized membership: build the expected-RTH index spanning the
        # min..max of df.index and use a set-membership mask.
        idx = df.index
        if idx.tz is None:
            raise ValueError("DataFrame index must be tz-aware UTC")

        start = idx.min().to_pydatetime()
        end = idx.max().to_pydatetime() + timedelta(days=1)
        inst = get(symbol)
        # Use the smallest supported tf for the membership universe — if the
        # df is 5m / 15m the indices still align because 5m/15m bars sit on
        # 1m grid points (09:30, 09:35, ...).
        tf = "1m"
        expected = expected_rth_timestamps(symbol, tf, start, end)
        mask = idx.isin(expected)
        return df[mask]

    def find_gaps(
        self,
        df: pd.DataFrame,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> list[datetime]:
        """Return the sorted-ascending list of expected-but-missing RTH timestamps.

        Compares `df.index` against `expected_rth_timestamps(symbol, timeframe,
        start, end)`. The output is a list of stdlib `datetime` objects (UTC)
        so Plan 04's `DuckDBStore.upsert_gaps` can persist them directly.
        """
        expected = expected_rth_timestamps(symbol, timeframe, start, end)
        if len(expected) == 0:
            return []
        present = pd.DatetimeIndex(df.index) if len(df) > 0 else pd.DatetimeIndex(
            [], tz="UTC"
        )
        missing = expected.difference(present)
        return [ts.to_pydatetime() for ts in missing.sort_values()]


# ---------------------------------------------------------------------------
# Rollover-seam detector (Pattern 4) — MD-08
# ---------------------------------------------------------------------------


def third_friday(year: int, month: int) -> date:
    """Return the 3rd-Friday-of-month date.

    Used as the rollover-seam anchor: ES/MES contracts roll on the 3rd Friday
    of Mar / Jun / Sep / Dec. Calling with month ∉ {3,6,9,12} still returns
    the 3rd Friday for that month (the caller decides whether to consult).
    """
    cal = _calendar.Calendar()
    fridays = [
        d
        for d in cal.itermonthdates(year, month)
        if d.month == month and d.weekday() == _calendar.FRIDAY
    ]
    return fridays[2]


def is_rollover_seam(ts_utc: datetime) -> bool:
    """True iff `ts_utc` is on or within 1 calendar day of a quarterly roll.

    The quarterly roll dates are the 3rd Fridays of Mar / Jun / Sep / Dec.
    A bar is flagged if `abs(date(ts_utc_ET) - third_friday)` ≤ 1 day,
    matching the conservative "+/- 1 trading day" window strategies use to
    skip seams.

    Raises ValueError on naive input (T-01-03-03).
    """
    if ts_utc.tzinfo is None:
        raise ValueError("ts must be tz-aware")
    et = ts_utc.astimezone(ET)
    d = et.date()
    for month in (3, 6, 9, 12):
        tf = third_friday(d.year, month)
        if abs((d - tf).days) <= 1:
            return True
    return False


class RolloverDetector:
    """Annotate a bar DataFrame with a `rollover_seam` boolean column.

    Accepts either:
    - tz-aware UTC `DatetimeIndex`-indexed DataFrames (the default Plan 04
      adapter output), OR
    - DataFrames carrying a `ts_utc` column instead of an index (older
      pre-index shape — still seen in seed scripts).
    """

    def annotate(self, df: pd.DataFrame) -> pd.DataFrame:
        if "ts_utc" in df.columns:
            ts = df["ts_utc"]
        else:
            ts = pd.Series(df.index, index=df.index)
        df = df.copy()
        df["rollover_seam"] = [
            is_rollover_seam(t.to_pydatetime() if isinstance(t, pd.Timestamp) else t)
            for t in ts
        ]
        return df
