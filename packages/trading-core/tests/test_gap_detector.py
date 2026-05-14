"""GapDetector tests (MD-07).

The gap detector flags expected-but-missing RTH bars. It is the source of
truth for the `bar_gaps` table populated by `seed_bars.py` and surfaced in
the UI Data Health panel.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

UTC = ZoneInfo("UTC")


class TestFindGaps:
    def test_complete_390_bar_day_no_gaps(self, synthetic_spy_day) -> None:
        from trading_core.calendars import RthFilter

        df = synthetic_spy_day(date(2024, 6, 12))
        gaps = RthFilter().find_gaps(
            df,
            "SPY",
            "1m",
            datetime(2024, 6, 12, 0, 0, tzinfo=UTC),
            datetime(2024, 6, 13, 0, 0, tzinfo=UTC),
        )
        assert gaps == []

    def test_five_missing_bars_returned_sorted(self, synthetic_spy_day) -> None:
        from trading_core.calendars import RthFilter

        df = synthetic_spy_day(date(2024, 6, 12))
        missing = [
            pd.Timestamp("2024-06-12 13:35:00+0000"),
            pd.Timestamp("2024-06-12 14:12:00+0000"),
            pd.Timestamp("2024-06-12 15:45:00+0000"),
            pd.Timestamp("2024-06-12 17:30:00+0000"),
            pd.Timestamp("2024-06-12 19:00:00+0000"),
        ]
        df_with_gaps = df.drop(missing)
        gaps = RthFilter().find_gaps(
            df_with_gaps,
            "SPY",
            "1m",
            datetime(2024, 6, 12, 0, 0, tzinfo=UTC),
            datetime(2024, 6, 13, 0, 0, tzinfo=UTC),
        )
        assert len(gaps) == 5
        assert gaps == sorted(gaps)
        assert [g.replace(tzinfo=UTC) for g in gaps] == [
            m.to_pydatetime() for m in missing
        ]

    def test_eth_only_df_does_not_produce_gap_for_eth_minutes(self) -> None:
        """ETH bars supplied with no RTH bars: gaps = full 390-minute RTH window.

        The point of this test is the *negative* direction: any 'gap' the
        detector flags is for an RTH minute, never an ETH minute. We assert
        the entire returned list lives inside the RTH window.
        """
        from trading_core.calendars import RthFilter
        from fixtures.dst_bars import make_eth_bars_2024_06_12

        df = make_eth_bars_2024_06_12()  # 00:00–13:29 UTC on 2024-06-12
        gaps = RthFilter().find_gaps(
            df,
            "SPY",
            "1m",
            datetime(2024, 6, 12, 0, 0, tzinfo=UTC),
            datetime(2024, 6, 13, 0, 0, tzinfo=UTC),
        )
        # All 390 RTH minutes are missing
        assert len(gaps) == 390
        # And every reported gap is inside the RTH window 13:30 UTC <= t < 20:00 UTC
        rth_open = datetime(2024, 6, 12, 13, 30, tzinfo=UTC)
        rth_close = datetime(2024, 6, 12, 20, 0, tzinfo=UTC)
        assert all(rth_open <= g < rth_close for g in gaps)

    def test_5m_timeframe_yields_correct_gap_count(self, synthetic_spy_day) -> None:
        """A 5m DataFrame missing one bar produces a 5m gap, not a 1m one."""
        from trading_core.calendars import RthFilter

        # Build a 5m DataFrame from the 1m baseline (resample by stride)
        df_1m = synthetic_spy_day(date(2024, 6, 12))
        # Pick every 5th 1m row to get the 5m bar OPEN times
        df_5m = df_1m.iloc[::5].copy()
        # Drop one row
        missing = df_5m.index[10]  # arbitrary mid-day 5m bar
        df_5m_with_gap = df_5m.drop(missing)
        gaps = RthFilter().find_gaps(
            df_5m_with_gap,
            "SPY",
            "5m",
            datetime(2024, 6, 12, 0, 0, tzinfo=UTC),
            datetime(2024, 6, 13, 0, 0, tzinfo=UTC),
        )
        assert len(gaps) == 1
        assert gaps[0] == missing.to_pydatetime()

    def test_dst_day_complete_returns_empty(
        self, dst_spring_forward_2026_03_09
    ) -> None:
        """The DST fixture is a complete 390-bar day; gap detector returns empty."""
        from trading_core.calendars import RthFilter

        gaps = RthFilter().find_gaps(
            dst_spring_forward_2026_03_09,
            "SPY",
            "1m",
            datetime(2026, 3, 8, 0, 0, tzinfo=UTC),
            datetime(2026, 3, 10, 0, 0, tzinfo=UTC),
        )
        assert gaps == []

    def test_half_day_complete_returns_empty(
        self, cme_half_day_thanksgiving_2024_11_29
    ) -> None:
        """Black Friday 210-bar fixture is complete; gap detector returns empty."""
        from trading_core.calendars import RthFilter

        gaps = RthFilter().find_gaps(
            cme_half_day_thanksgiving_2024_11_29,
            "SPY",
            "1m",
            datetime(2024, 11, 29, 0, 0, tzinfo=UTC),
            datetime(2024, 11, 30, 0, 0, tzinfo=UTC),
        )
        assert gaps == []

    def test_gaps_returns_list_of_datetime(self, synthetic_spy_day) -> None:
        """Output must be `list[datetime]`, not pandas Timestamps, for DuckDB."""
        from trading_core.calendars import RthFilter

        df = synthetic_spy_day(date(2024, 6, 12))
        # Drop one bar
        df = df.drop(pd.Timestamp("2024-06-12 14:00:00+0000"))
        gaps = RthFilter().find_gaps(
            df,
            "SPY",
            "1m",
            datetime(2024, 6, 12, 0, 0, tzinfo=UTC),
            datetime(2024, 6, 13, 0, 0, tzinfo=UTC),
        )
        assert len(gaps) == 1
        assert isinstance(gaps[0], datetime)
        assert not isinstance(gaps[0], pd.Timestamp)


class TestFindGapsAsDataFrame:
    def test_to_dataframe_yields_duckdb_upsert_shape(self, synthetic_spy_day) -> None:
        """Plan 04's DuckDBStore.upsert_gaps expects [symbol, timeframe, ts_utc]."""
        from trading_core.calendars import RthFilter

        df = synthetic_spy_day(date(2024, 6, 12))
        df = df.drop(pd.Timestamp("2024-06-12 14:00:00+0000"))
        rth = RthFilter()
        gaps_df = rth.find_gaps_as_dataframe(
            df,
            "SPY",
            "1m",
            datetime(2024, 6, 12, 0, 0, tzinfo=UTC),
            datetime(2024, 6, 13, 0, 0, tzinfo=UTC),
        )
        assert list(gaps_df.columns) == ["symbol", "timeframe", "ts_utc"]
        assert len(gaps_df) == 1
        assert gaps_df.iloc[0]["symbol"] == "SPY"
        assert gaps_df.iloc[0]["timeframe"] == "1m"
        assert gaps_df.iloc[0]["ts_utc"] == pd.Timestamp("2024-06-12 14:00:00+0000")

    def test_to_dataframe_empty_when_no_gaps(self, synthetic_spy_day) -> None:
        from trading_core.calendars import RthFilter

        df = synthetic_spy_day(date(2024, 6, 12))
        gaps_df = RthFilter().find_gaps_as_dataframe(
            df,
            "SPY",
            "1m",
            datetime(2024, 6, 12, 0, 0, tzinfo=UTC),
            datetime(2024, 6, 13, 0, 0, tzinfo=UTC),
        )
        assert len(gaps_df) == 0
        assert list(gaps_df.columns) == ["symbol", "timeframe", "ts_utc"]
