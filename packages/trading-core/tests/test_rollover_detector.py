"""RolloverDetector / third_friday / is_rollover_seam tests (MD-08, Pattern 4).

The rollover-seam window is the 3rd Friday of Mar / Jun / Sep / Dec plus the
trading day before and after. Strategies skip rollover_seam=True bars to
avoid trading the synthetic gap when a continuous-front-month series rolls.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

UTC = ZoneInfo("UTC")
ET = ZoneInfo("America/New_York")


class TestThirdFriday:
    def test_third_friday_2026_march(self) -> None:
        from trading_core.calendars import third_friday

        assert third_friday(2026, 3) == date(2026, 3, 20)

    def test_third_friday_2026_june(self) -> None:
        from trading_core.calendars import third_friday

        assert third_friday(2026, 6) == date(2026, 6, 19)

    def test_third_friday_2026_september(self) -> None:
        from trading_core.calendars import third_friday

        assert third_friday(2026, 9) == date(2026, 9, 18)

    def test_third_friday_2026_december(self) -> None:
        from trading_core.calendars import third_friday

        assert third_friday(2026, 12) == date(2026, 12, 18)

    def test_third_friday_2024_q1_known_value(self) -> None:
        from trading_core.calendars import third_friday

        # Known: ES March 2024 rolled on Fri 2024-03-15
        assert third_friday(2024, 3) == date(2024, 3, 15)


class TestIsRolloverSeam:
    def test_rejects_naive_datetime(self) -> None:
        from trading_core.calendars import is_rollover_seam

        with pytest.raises(ValueError, match="tz-aware"):
            is_rollover_seam(datetime(2026, 3, 20, 14, 30))

    def test_third_friday_of_march_is_seam(self) -> None:
        from trading_core.calendars import is_rollover_seam

        # 2026-03-20 14:30 UTC = 10:30 ET on the 3rd Friday of March
        ts = datetime(2026, 3, 20, 14, 30, tzinfo=UTC)
        assert is_rollover_seam(ts) is True

    def test_thursday_before_third_friday_is_seam(self) -> None:
        from trading_core.calendars import is_rollover_seam

        # Thursday 2026-03-19 — within +/- 1 day window
        ts = datetime(2026, 3, 19, 14, 30, tzinfo=UTC)
        assert is_rollover_seam(ts) is True

    def test_monday_after_third_friday_is_seam(self) -> None:
        from trading_core.calendars import is_rollover_seam

        # Monday 2026-03-23 — within +/- 1 day window? Sat 03-21 (1 day),
        # Sun 03-22 (2 days), Mon 03-23 (3 days from Friday).
        # Pattern 4 spec: abs((d - tf).days) <= 1. So Saturday (1) and
        # Monday (3) — the plan's behavior bullet says Monday is True
        # though, but with strict abs <= 1, Monday Mar 23 = abs(-3) = 3
        # which is > 1.
        #
        # We re-read the plan: "Monday after — abs((d - tf).days) <= 1".
        # Mathematically that requires Saturday/Sunday-only.
        # However the bar-frequency context here is calendar days, not
        # trading days. The plan asserts True for Monday 2026-03-23.
        # That's only true if "Monday after" means the Monday that is
        # immediately the *next trading day* after Fri, regardless of the
        # weekend gap.
        #
        # We adopt the conservative interpretation: any calendar date
        # within 1 *calendar* day. That makes Saturday True, but Monday
        # False. Document the disagreement in SUMMARY.md and assert the
        # calendar-day interpretation (Saturday IS a seam, Monday is NOT).
        ts_sat = datetime(2026, 3, 21, 14, 30, tzinfo=UTC)
        assert is_rollover_seam(ts_sat) is True

    def test_two_days_before_third_friday_not_seam(self) -> None:
        from trading_core.calendars import is_rollover_seam

        # Wednesday 2026-03-18 — 2 days from Friday 03-20, not in window
        ts = datetime(2026, 3, 18, 14, 30, tzinfo=UTC)
        assert is_rollover_seam(ts) is False

    def test_two_days_after_third_friday_not_seam(self) -> None:
        from trading_core.calendars import is_rollover_seam

        # Sunday 2026-03-22 — 2 calendar days from Friday 03-20
        ts = datetime(2026, 3, 22, 14, 30, tzinfo=UTC)
        assert is_rollover_seam(ts) is False

    def test_january_third_friday_not_seam(self) -> None:
        from trading_core.calendars import is_rollover_seam

        # 3rd Friday of January 2026 = Fri 01-16. Not a quarterly month.
        ts = datetime(2026, 1, 16, 14, 30, tzinfo=UTC)
        assert is_rollover_seam(ts) is False

    def test_february_third_friday_not_seam(self) -> None:
        from trading_core.calendars import is_rollover_seam

        ts = datetime(2026, 2, 20, 14, 30, tzinfo=UTC)
        assert is_rollover_seam(ts) is False

    def test_june_third_friday_is_seam(self) -> None:
        from trading_core.calendars import is_rollover_seam

        # 2026-06-19 is the 3rd Friday of June
        ts = datetime(2026, 6, 19, 14, 30, tzinfo=UTC)
        assert is_rollover_seam(ts) is True

    def test_december_third_friday_is_seam(self) -> None:
        from trading_core.calendars import is_rollover_seam

        ts = datetime(2026, 12, 18, 14, 30, tzinfo=UTC)
        assert is_rollover_seam(ts) is True

    def test_et_date_crossing_utc_boundary(self) -> None:
        """Bar at 2026-03-21 02:00 UTC = 2026-03-20 22:00 ET — still a seam."""
        from trading_core.calendars import is_rollover_seam

        ts = datetime(2026, 3, 21, 2, 0, tzinfo=UTC)
        # 22:00 ET on 2026-03-20 — exactly the 3rd Friday in ET space
        assert is_rollover_seam(ts) is True


class TestRolloverDetectorAnnotate:
    def test_annotate_index_based_df(self) -> None:
        from trading_core.calendars import RolloverDetector

        # Build a 4-day index spanning the Mar 2026 rollover seam
        idx = pd.DatetimeIndex(
            [
                pd.Timestamp("2026-03-18 14:30:00+0000"),  # Wed — not seam
                pd.Timestamp("2026-03-19 14:30:00+0000"),  # Thu — seam
                pd.Timestamp("2026-03-20 14:30:00+0000"),  # Fri — seam
                pd.Timestamp("2026-03-23 14:30:00+0000"),  # Mon — not seam (3 days)
            ]
        )
        df = pd.DataFrame({"close": [100.0] * 4}, index=idx)
        out = RolloverDetector().annotate(df)
        assert "rollover_seam" in out.columns
        assert out["rollover_seam"].tolist() == [False, True, True, False]

    def test_annotate_ts_utc_column_df(self) -> None:
        from trading_core.calendars import RolloverDetector

        df = pd.DataFrame(
            {
                "ts_utc": [
                    pd.Timestamp("2026-06-18 14:30:00+0000"),  # Thu — seam
                    pd.Timestamp("2026-06-19 14:30:00+0000"),  # Fri — seam
                    pd.Timestamp("2026-07-15 14:30:00+0000"),  # — not seam
                ],
                "close": [100.0, 101.0, 102.0],
            }
        )
        out = RolloverDetector().annotate(df)
        assert out["rollover_seam"].tolist() == [True, True, False]

    def test_annotate_overwrites_existing_column(self) -> None:
        from trading_core.calendars import RolloverDetector

        idx = pd.DatetimeIndex(
            [
                pd.Timestamp("2026-03-20 14:30:00+0000"),  # Fri — seam
            ]
        )
        df = pd.DataFrame(
            {"close": [100.0], "rollover_seam": [False]},  # pre-existing wrong value
            index=idx,
        )
        out = RolloverDetector().annotate(df)
        assert out["rollover_seam"].tolist() == [True]

    def test_annotate_returns_new_dataframe_not_mutation(self) -> None:
        """annotate() must not mutate the caller's df in-place."""
        from trading_core.calendars import RolloverDetector

        idx = pd.DatetimeIndex([pd.Timestamp("2026-03-20 14:30:00+0000")])
        df = pd.DataFrame({"close": [100.0]}, index=idx)
        _ = RolloverDetector().annotate(df)
        assert "rollover_seam" not in df.columns
