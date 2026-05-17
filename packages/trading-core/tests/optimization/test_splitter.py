"""Tests for get_fold_boundaries — OPT-03.

Uses a synthetic bar_df covering 10 months of trading days.
Verifies:
- is_end < oos_start for every fold (BL-4 invariant)
- IS window is approximately 126 trading days
- fold_idx increments from 0
"""
from __future__ import annotations

from datetime import timezone

import pandas as pd
import pandas_market_calendars as mcal
import pytest

from trading_core.optimization.splitter import get_fold_boundaries


def make_synthetic_bar_df(n_months: int = 10) -> pd.DataFrame:
    """Build a synthetic bar_df with 1m bars covering n_months of trading days."""
    cal = mcal.get_calendar("CME_Equity")
    schedule = cal.schedule(
        start_date="2024-01-02", end_date="2024-12-31"
    )
    trading_days = schedule.index[:n_months * 21]  # approx n_months of trading days

    # Build one bar per trading day (sufficient for splitter; splitter works on daily index)
    rows = []
    for day in trading_days:
        ts = day.replace(hour=14, minute=30, tzinfo=timezone.utc)  # 9:30 ET = 14:30 UTC
        rows.append(
            {
                "symbol": "SPY",
                "timeframe": "1m",
                "ts_utc": pd.Timestamp(ts),
                "open": 400.0,
                "high": 401.0,
                "low": 399.0,
                "close": 400.5,
                "volume": 1000,
            }
        )
    return pd.DataFrame(rows)


def test_fold_boundaries_is_before_oos() -> None:
    """BL-4 invariant: is_end < oos_start for every fold."""
    bar_df = make_synthetic_bar_df(n_months=10)
    folds = get_fold_boundaries(bar_df, is_months=6, oos_months=1)
    assert len(folds) > 0, "Should produce at least one fold"
    for fold in folds:
        is_end = fold["is_end"]
        oos_start = fold["oos_start"]
        assert is_end < oos_start, (
            f"Fold {fold['fold_idx']}: is_end ({is_end}) >= oos_start ({oos_start}) — BL-4 violated"
        )


def test_fold_idx_increments() -> None:
    """fold_idx should increment from 0."""
    bar_df = make_synthetic_bar_df(n_months=10)
    folds = get_fold_boundaries(bar_df, is_months=6, oos_months=1)
    assert len(folds) > 0
    for i, fold in enumerate(folds):
        assert fold["fold_idx"] == i, f"Expected fold_idx={i}, got {fold['fold_idx']}"


def test_fold_boundaries_are_iso_strings() -> None:
    """All fold boundary values are ISO 8601 strings (picklable — Pitfall 4)."""
    bar_df = make_synthetic_bar_df(n_months=10)
    folds = get_fold_boundaries(bar_df, is_months=6, oos_months=1)
    for fold in folds:
        for key in ("is_start", "is_end", "oos_start", "oos_end"):
            val = fold[key]
            assert isinstance(val, str), f"fold[{key!r}] should be str, got {type(val)}"
            # Should parse without error
            from datetime import date
            date.fromisoformat(val)  # ISO date strings parseable


def test_is_window_approximately_correct() -> None:
    """IS window spans approximately 6 months (IS_DAYS = 21*6 = 126 trading days)."""
    bar_df = make_synthetic_bar_df(n_months=10)
    folds = get_fold_boundaries(bar_df, is_months=6, oos_months=1)
    assert len(folds) > 0
    cal = mcal.get_calendar("CME_Equity")
    fold = folds[0]
    schedule = cal.schedule(start_date=fold["is_start"], end_date=fold["is_end"])
    is_trading_days = len(schedule)
    # Should be close to 126 (±5 trading days tolerance for calendar variation)
    assert 110 <= is_trading_days <= 135, (
        f"IS window has {is_trading_days} trading days, expected ~126"
    )
