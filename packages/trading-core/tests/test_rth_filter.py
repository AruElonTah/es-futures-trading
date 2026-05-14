"""RthFilter + is_rth + expected_rth_timestamps tests (MD-05, Pattern 3).

Hybrid CME_Equity (trading-day + half-day reads) + manual 9:30–16:00 ET
window. The behaviors locked here are the load-bearing invariants the rest
of Phase 1's data ingestion depends on. RESEARCH.md Pitfalls 1 + 3 are the
two bugs we are explicitly defending against.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")


# ---------------------------------------------------------------------------
# is_rth — direct point-in-time queries
# ---------------------------------------------------------------------------


class TestIsRthCore:
    def test_rejects_naive_datetime(self) -> None:
        from trading_core.calendars import is_rth

        with pytest.raises(ValueError, match="tz-aware"):
            is_rth(datetime(2024, 6, 12, 13, 30), instrument_symbol="SPY")

    def test_open_is_inclusive(self) -> None:
        from trading_core.calendars import is_rth

        # 2024-06-12 09:30 ET = 13:30 UTC (EDT, UTC-4)
        ts = datetime(2024, 6, 12, 13, 30, tzinfo=UTC)
        assert is_rth(ts, instrument_symbol="SPY") is True

    def test_close_is_exclusive(self) -> None:
        from trading_core.calendars import is_rth

        # 2024-06-12 16:00 ET = 20:00 UTC — RTH window is [open, close)
        ts = datetime(2024, 6, 12, 20, 0, tzinfo=UTC)
        assert is_rth(ts, instrument_symbol="SPY") is False

    def test_one_minute_before_close_is_in_rth(self) -> None:
        from trading_core.calendars import is_rth

        # 2024-06-12 15:59 ET = 19:59 UTC — last 1m bar of the session
        ts = datetime(2024, 6, 12, 19, 59, tzinfo=UTC)
        assert is_rth(ts, instrument_symbol="SPY") is True

    def test_eth_bar_previous_day_evening_excluded(self) -> None:
        from trading_core.calendars import is_rth

        # 2024-06-12 02:00 UTC = 2024-06-11 22:00 ET — pure ETH, must be False
        ts = datetime(2024, 6, 12, 2, 0, tzinfo=UTC)
        assert is_rth(ts, instrument_symbol="SPY") is False

    def test_pre_open_same_day_excluded(self) -> None:
        from trading_core.calendars import is_rth

        # 2024-06-12 13:00 UTC = 09:00 ET — 30 min before open
        ts = datetime(2024, 6, 12, 13, 0, tzinfo=UTC)
        assert is_rth(ts, instrument_symbol="SPY") is False

    def test_nyse_holiday_july_4_excluded(self) -> None:
        from trading_core.calendars import is_rth

        # 2024-07-04 14:30 UTC = 10:30 ET on July 4 — NYSE closed
        ts = datetime(2024, 7, 4, 14, 30, tzinfo=UTC)
        assert is_rth(ts, instrument_symbol="SPY") is False

    def test_weekend_excluded(self) -> None:
        from trading_core.calendars import is_rth

        # 2024-06-15 was a Saturday
        ts = datetime(2024, 6, 15, 14, 30, tzinfo=UTC)
        assert is_rth(ts, instrument_symbol="SPY") is False


# ---------------------------------------------------------------------------
# CME half-day (Black Friday 2024-11-29 early close at 13:00 ET = 18:00 UTC)
# ---------------------------------------------------------------------------


class TestHalfDay:
    def test_pre_early_close_in_rth(self) -> None:
        from trading_core.calendars import is_rth

        # 10:00 ET on Black Friday = 15:00 UTC (EST, UTC-5)
        ts = datetime(2024, 11, 29, 15, 0, tzinfo=UTC)
        assert is_rth(ts, instrument_symbol="SPY") is True

    def test_after_early_close_excluded(self) -> None:
        from trading_core.calendars import is_rth

        # 13:30 ET = 18:30 UTC — past the 13:00 ET early close
        ts = datetime(2024, 11, 29, 18, 30, tzinfo=UTC)
        assert is_rth(ts, instrument_symbol="SPY") is False

    def test_exactly_at_early_close_excluded(self) -> None:
        from trading_core.calendars import is_rth

        # 13:00 ET = 18:00 UTC — close is exclusive
        ts = datetime(2024, 11, 29, 18, 0, tzinfo=UTC)
        assert is_rth(ts, instrument_symbol="SPY") is False


# ---------------------------------------------------------------------------
# expected_rth_timestamps — used by the gap detector
# ---------------------------------------------------------------------------


class TestExpectedRthTimestamps:
    def test_normal_day_yields_390_bars_1m(self) -> None:
        from trading_core.calendars import expected_rth_timestamps

        start = datetime(2024, 6, 12, 0, 0, tzinfo=UTC)
        end = datetime(2024, 6, 13, 0, 0, tzinfo=UTC)
        ts = expected_rth_timestamps("SPY", "1m", start, end)
        assert len(ts) == 390
        assert ts[0] == pd.Timestamp("2024-06-12 13:30:00+0000")
        assert ts[-1] == pd.Timestamp("2024-06-12 19:59:00+0000")

    def test_normal_day_yields_78_bars_5m(self) -> None:
        from trading_core.calendars import expected_rth_timestamps

        start = datetime(2024, 6, 12, 0, 0, tzinfo=UTC)
        end = datetime(2024, 6, 13, 0, 0, tzinfo=UTC)
        ts = expected_rth_timestamps("SPY", "5m", start, end)
        assert len(ts) == 78  # 390 / 5

    def test_normal_day_yields_26_bars_15m(self) -> None:
        from trading_core.calendars import expected_rth_timestamps

        start = datetime(2024, 6, 12, 0, 0, tzinfo=UTC)
        end = datetime(2024, 6, 13, 0, 0, tzinfo=UTC)
        ts = expected_rth_timestamps("SPY", "15m", start, end)
        assert len(ts) == 26  # 390 / 15

    def test_dst_spring_forward_390_bars_starting_1330_utc(self) -> None:
        """2026-03-09 (Mon after spring forward): RTH starts at 13:30 UTC = 09:30 EDT."""
        from trading_core.calendars import expected_rth_timestamps

        # 2026-03-08 is a Sunday — non-trading; the trading day is Mar 9
        start = datetime(2026, 3, 8, 0, 0, tzinfo=UTC)
        end = datetime(2026, 3, 10, 0, 0, tzinfo=UTC)
        ts = expected_rth_timestamps("SPY", "1m", start, end)
        # Only Mar 9 is a trading day in this range
        assert len(ts) == 390
        assert ts[0] == pd.Timestamp("2026-03-09 13:30:00+0000")
        assert ts[-1] == pd.Timestamp("2026-03-09 19:59:00+0000")

    def test_dst_fall_back_390_bars_starting_1430_utc(self) -> None:
        """2026-11-02 (Mon after fall-back): RTH starts at 14:30 UTC = 09:30 EST."""
        from trading_core.calendars import expected_rth_timestamps

        # 2026-11-01 is a Sunday — non-trading; the trading day is Nov 2
        start = datetime(2026, 11, 1, 0, 0, tzinfo=UTC)
        end = datetime(2026, 11, 3, 0, 0, tzinfo=UTC)
        ts = expected_rth_timestamps("SPY", "1m", start, end)
        # Only Nov 2 is a trading day in this range
        assert len(ts) == 390
        assert ts[0] == pd.Timestamp("2026-11-02 14:30:00+0000")
        assert ts[-1] == pd.Timestamp("2026-11-02 20:59:00+0000")

    def test_dst_offset_difference_is_exactly_one_hour(self) -> None:
        """UTC start of Nov 2 RTH = UTC start of Mar 9 RTH + 1 hour (EST vs EDT)."""
        from trading_core.calendars import expected_rth_timestamps

        spring = expected_rth_timestamps(
            "SPY",
            "1m",
            datetime(2026, 3, 9, 0, 0, tzinfo=UTC),
            datetime(2026, 3, 10, 0, 0, tzinfo=UTC),
        )
        fall = expected_rth_timestamps(
            "SPY",
            "1m",
            datetime(2026, 11, 2, 0, 0, tzinfo=UTC),
            datetime(2026, 11, 3, 0, 0, tzinfo=UTC),
        )
        # Both 390-bar windows; UTC starts differ by exactly 1 hour
        assert len(spring) == 390 and len(fall) == 390
        assert (fall[0] - spring[0]) == timedelta(hours=243 * 24 + 1) or (
            (fall[0].time() == pd.Timestamp("14:30").time())
            and (spring[0].time() == pd.Timestamp("13:30").time())
        )

    def test_half_day_yields_210_bars(self) -> None:
        """2024-11-29 (Black Friday): early close at 13:00 ET → 210 1m bars."""
        from trading_core.calendars import expected_rth_timestamps

        start = datetime(2024, 11, 29, 0, 0, tzinfo=UTC)
        end = datetime(2024, 11, 30, 0, 0, tzinfo=UTC)
        ts = expected_rth_timestamps("SPY", "1m", start, end)
        # 9:30 ET → 13:00 ET = 3.5 hours = 210 minutes
        assert len(ts) == 210
        assert ts[0] == pd.Timestamp("2024-11-29 14:30:00+0000")  # 09:30 EST
        assert ts[-1] == pd.Timestamp("2024-11-29 17:59:00+0000")  # 12:59 EST

    def test_weekend_yields_zero_bars(self) -> None:
        from trading_core.calendars import expected_rth_timestamps

        # 2024-06-15 (Sat) and 2024-06-16 (Sun) — no trading days
        start = datetime(2024, 6, 15, 0, 0, tzinfo=UTC)
        end = datetime(2024, 6, 17, 0, 0, tzinfo=UTC)
        ts = expected_rth_timestamps("SPY", "1m", start, end)
        assert len(ts) == 0


# ---------------------------------------------------------------------------
# RthFilter.filter — DataFrame-level filtering
# ---------------------------------------------------------------------------


class TestRthFilterFilter:
    def test_keeps_all_rth_bars(self, synthetic_spy_day) -> None:
        """A pure-RTH fixture should pass through .filter unchanged."""
        from trading_core.calendars import RthFilter

        df = synthetic_spy_day(date(2024, 6, 12))
        out = RthFilter().filter(df, symbol="SPY")
        assert len(out) == 390
        assert (out.index == df.index).all()

    def test_strips_eth_bars(self) -> None:
        """An ETH-only fixture should produce an empty DataFrame after filter."""
        from trading_core.calendars import RthFilter
        from fixtures.dst_bars import make_eth_bars_2024_06_12

        df = make_eth_bars_2024_06_12()
        out = RthFilter().filter(df, symbol="SPY")
        assert len(out) == 0

    def test_mixed_eth_plus_rth_keeps_only_rth(self, synthetic_spy_day) -> None:
        from trading_core.calendars import RthFilter
        from fixtures.dst_bars import make_eth_bars_2024_06_12

        rth_df = synthetic_spy_day(date(2024, 6, 12))
        eth_df = make_eth_bars_2024_06_12()
        mixed = pd.concat([eth_df, rth_df]).sort_index()
        out = RthFilter().filter(mixed, symbol="SPY")
        assert len(out) == 390
        # Every kept timestamp is in the original RTH index
        assert out.index.equals(rth_df.index)

    def test_dst_spring_forward_390_after_filter(
        self, dst_spring_forward_2026_03_09
    ) -> None:
        from trading_core.calendars import RthFilter

        out = RthFilter().filter(dst_spring_forward_2026_03_09, symbol="SPY")
        assert len(out) == 390

    def test_dst_fall_back_390_after_filter(self, dst_fall_back_2026_11_02) -> None:
        from trading_core.calendars import RthFilter

        out = RthFilter().filter(dst_fall_back_2026_11_02, symbol="SPY")
        assert len(out) == 390

    def test_half_day_210_after_filter(
        self, cme_half_day_thanksgiving_2024_11_29
    ) -> None:
        from trading_core.calendars import RthFilter

        out = RthFilter().filter(cme_half_day_thanksgiving_2024_11_29, symbol="SPY")
        # The fixture is constructed at exactly the half-day RTH window
        assert len(out) == 210


# ---------------------------------------------------------------------------
# RthFilter.find_gaps — wraps expected_rth_timestamps + set difference
# ---------------------------------------------------------------------------


class TestFindGaps:
    def test_complete_day_no_gaps(self, synthetic_spy_day) -> None:
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

    def test_one_missing_bar_detected(self, synthetic_spy_day) -> None:
        from trading_core.calendars import RthFilter

        df = synthetic_spy_day(date(2024, 6, 12))
        missing_ts = pd.Timestamp("2024-06-12 14:00:00+0000")
        df_with_gap = df.drop(missing_ts)
        gaps = RthFilter().find_gaps(
            df_with_gap,
            "SPY",
            "1m",
            datetime(2024, 6, 12, 0, 0, tzinfo=UTC),
            datetime(2024, 6, 13, 0, 0, tzinfo=UTC),
        )
        assert len(gaps) == 1
        assert gaps[0] == missing_ts.to_pydatetime()

    def test_multiple_gaps_returned_sorted_ascending(self, synthetic_spy_day) -> None:
        from trading_core.calendars import RthFilter

        df = synthetic_spy_day(date(2024, 6, 12))
        to_drop = [
            pd.Timestamp("2024-06-12 14:00:00+0000"),
            pd.Timestamp("2024-06-12 17:15:00+0000"),
            pd.Timestamp("2024-06-12 19:00:00+0000"),
        ]
        df_with_gaps = df.drop(to_drop)
        gaps = RthFilter().find_gaps(
            df_with_gaps,
            "SPY",
            "1m",
            datetime(2024, 6, 12, 0, 0, tzinfo=UTC),
            datetime(2024, 6, 13, 0, 0, tzinfo=UTC),
        )
        assert len(gaps) == 3
        assert gaps == sorted(gaps)
        assert all(isinstance(g, datetime) for g in gaps)
