"""Rolling walk-forward fold generator — OPT-03.

Wraps ``vbt.RollingSplitter`` (VBT 1.0.0 OSS) to produce IS/OOS fold boundaries
as picklable ISO date strings. Uses ``pandas_market_calendars`` for trading-day
counting so month approximations are calendar-correct.

Key design decisions:
    D-05: ``vbt.RollingSplitter`` (NOT ``vbt.Splitter.from_n_rolling`` — that
          attribute does not exist in VBT 1.0.0 OSS; see 04-RESEARCH.md Pitfall 1).
    Pitfall 4: fold boundaries are ISO strings, never ``pd.Timestamp`` objects,
               so they survive ``ProcessPoolExecutor`` pickling on Windows.
    BL-4: Asserts ``is_end < oos_start`` for every fold before returning.

Usage::

    folds = get_fold_boundaries(bar_df, is_months=6, oos_months=1)
    for fold in folds:
        print(fold["fold_idx"], fold["is_start"], "→", fold["oos_end"])
"""

from __future__ import annotations

import pandas as pd
import pandas_market_calendars as mcal
import vectorbt as vbt


def get_fold_boundaries(
    bar_df: pd.DataFrame,
    is_months: int = 6,
    oos_months: int = 1,
    n_folds: int | None = None,
) -> list[dict]:
    """Generate rolling IS/OOS fold boundaries as picklable ISO date strings.

    Args:
        bar_df: DataFrame with a ``ts_utc`` column containing bar timestamps.
            Typically 1m bars; splitter works on a daily trading-day index so
            bar granularity does not affect fold count.
        is_months: In-sample window length in calendar months.
            Converted to approximate trading days via ``21 * is_months``.
        oos_months: Out-of-sample window length in calendar months.
            Converted to approximate trading days via ``21 * oos_months``.
        n_folds: Number of folds to generate. If ``None``, computed from the
            available trading days as
            ``max(1, len(trading_days) // oos_days - is_months)``.
            This matches the ``step=1m`` rolling convention from D-04.

    Returns:
        List of fold dicts, each containing:
            ``fold_idx`` (int), ``is_start`` (ISO str), ``is_end`` (ISO str),
            ``oos_start`` (ISO str), ``oos_end`` (ISO str).
        All date strings are ISO 8601 format (``YYYY-MM-DD``), picklable
        across ``ProcessPoolExecutor`` boundaries (Pitfall 4).

    Raises:
        ValueError: If the bar_df date range is too short to generate any folds.
        AssertionError: If any fold violates ``is_end < oos_start`` (BL-4).
    """
    # Build a daily trading-day index from the bar date range.
    # CME_Equity calendar gives ~21 trading days/month for ES futures.
    cal = mcal.get_calendar("CME_Equity")
    first_bar_date = pd.Timestamp(bar_df["ts_utc"].min()).date()
    last_bar_date = pd.Timestamp(bar_df["ts_utc"].max()).date()
    schedule = cal.schedule(
        start_date=str(first_bar_date), end_date=str(last_bar_date)
    )
    trading_days = schedule.index  # DatetimeIndex of trading days

    # Approximate IS and OOS sizes in trading days.
    IS_DAYS = 21 * is_months   # e.g., 126 for IS=6m
    OOS_DAYS = 21 * oos_months  # e.g., 21 for OOS=1m

    total_days = len(trading_days)
    if total_days < IS_DAYS + OOS_DAYS:
        raise ValueError(
            f"Not enough trading days ({total_days}) to form a single fold "
            f"(IS={IS_DAYS} + OOS={OOS_DAYS} = {IS_DAYS + OOS_DAYS} required)"
        )

    if n_folds is None:
        # Derive fold count from available trading months minus IS window.
        # step=1m → one fold per OOS window worth of trading days.
        n_folds = max(1, total_days // OOS_DAYS - is_months)

    # Build a Series with a DatetimeIndex — RollingSplitter requires a Series
    # with an index that corresponds to the time axis.
    X = pd.Series(range(total_days), index=trading_days)

    # vbt.RollingSplitter (VBT 1.0.0 OSS).
    # window_len = IS_DAYS + OOS_DAYS (total window — see Pitfall 6).
    # set_lens=(IS_DAYS,) means first set = IS; remainder = OOS.
    splitter = vbt.RollingSplitter()
    folds_raw = list(
        splitter.split(
            X,
            n=n_folds,
            window_len=IS_DAYS + OOS_DAYS,
            set_lens=(IS_DAYS,),
        )
    )

    result: list[dict] = []
    for fold_idx, (is_idx, oos_idx) in enumerate(folds_raw):
        # Convert numpy integer indices to ISO date strings (Pitfall 4).
        is_start = trading_days[is_idx[0]].date().isoformat()
        is_end = trading_days[is_idx[-1]].date().isoformat()
        oos_start = trading_days[oos_idx[0]].date().isoformat()
        oos_end = trading_days[oos_idx[-1]].date().isoformat()

        # BL-4 invariant: IS window must end before OOS window begins.
        assert is_end < oos_start, (
            f"Fold {fold_idx}: is_end ({is_end}) >= oos_start ({oos_start}) — "
            "BL-4 violated (IS/OOS overlap detected)"
        )

        result.append(
            {
                "fold_idx": fold_idx,
                "is_start": is_start,
                "is_end": is_end,
                "oos_start": oos_start,
                "oos_end": oos_end,
            }
        )

    return result
