"""Bar Pydantic v2 model tests (MD-06).

Plan 01-02 / Task 2. Covers the `<behavior>` block:
- Constructs cleanly from tz-aware UTC datetime + Decimal OHLC + nonneg volume.
- Rejects naive datetime.
- Rejects tz-aware non-UTC datetime with a message containing "must be tz-aware UTC".
- Rejects volume < 0.
- Is frozen (immutable post-construction).
- Documents the OPEN-time convention in the model docstring.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pydantic
import pytest

from trading_core.data import Bar


def _good_kwargs(**overrides):
    base = dict(
        symbol="SPY",
        timeframe="1m",
        ts_utc=datetime(2024, 1, 2, 14, 30, tzinfo=timezone.utc),
        open=Decimal("470.0"),
        high=Decimal("470.5"),
        low=Decimal("469.9"),
        close=Decimal("470.2"),
        volume=12345,
    )
    base.update(overrides)
    return base


class TestBarHappyPath:
    def test_constructs_with_utc_datetime(self):
        bar = Bar(**_good_kwargs())
        assert bar.symbol == "SPY"
        assert bar.timeframe == "1m"
        assert bar.volume == 12345
        assert bar.rollover_seam is False

    def test_rollover_seam_defaults_false(self):
        assert Bar(**_good_kwargs()).rollover_seam is False

    def test_rollover_seam_can_be_set(self):
        assert Bar(**_good_kwargs(rollover_seam=True)).rollover_seam is True


class TestBarTimestampValidation:
    def test_rejects_naive_datetime(self):
        with pytest.raises(pydantic.ValidationError):
            Bar(**_good_kwargs(ts_utc=datetime(2024, 1, 2, 14, 30)))

    def test_rejects_tz_aware_non_utc(self):
        ny = ZoneInfo("America/New_York")
        with pytest.raises(pydantic.ValidationError) as exc:
            Bar(**_good_kwargs(ts_utc=datetime(2024, 1, 2, 9, 30, tzinfo=ny)))
        assert "must be tz-aware UTC" in str(exc.value)


class TestBarVolumeValidation:
    def test_rejects_negative_volume(self):
        with pytest.raises(pydantic.ValidationError):
            Bar(**_good_kwargs(volume=-1))

    def test_accepts_zero_volume(self):
        # A bar with zero volume is rare but legitimate (illiquid 1m bar) — must not raise.
        bar = Bar(**_good_kwargs(volume=0))
        assert bar.volume == 0


class TestBarFrozen:
    def test_mutation_raises(self):
        bar = Bar(**_good_kwargs())
        with pytest.raises(pydantic.ValidationError):
            bar.symbol = "ES"  # type: ignore[misc]


class TestBarOpenTimeConvention:
    def test_docstring_documents_open_time_convention(self):
        # MD-06 — the model docstring must mention the OPEN-time convention.
        from trading_core.data.models import Bar as BarModel

        doc = BarModel.__doc__ or ""
        assert "OPEN" in doc.upper()
        assert "09:30" in doc or "open" in doc.lower()
