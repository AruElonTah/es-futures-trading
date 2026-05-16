"""Indicator tests: behavior + leakage proofs (Plan 02-01 Tasks 2 & 3).

Tests cover:
1. Cold-state and warmup behavior for all 4 indicators
2. Basic value correctness (first warm value, session reset, etc.)
3. Leakage proof: snapshot_at(t) == recompute-from-scratch for all t
4. ADR BL-3 test: today's outlier does NOT appear in today's ADR
5. SessionVWAP session-reset test across ET date boundary
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from decimal import Decimal

import pytest

from trading_core.data.models import Bar
from trading_core.indicators import ATRWilder, SessionVWAP, EMA, ADR

_UTC = timezone.utc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bar(
    close: float = 100.0,
    high: float | None = None,
    low: float | None = None,
    volume: int = 1000,
    ts: datetime | None = None,
    symbol: str = "SPY",
) -> Bar:
    if high is None:
        high = close + 0.5
    if low is None:
        low = close - 0.5
    if ts is None:
        ts = datetime(2024, 1, 2, 14, 30, tzinfo=_UTC)
    return Bar(
        symbol=symbol,
        timeframe="1m",
        ts_utc=ts,
        open=Decimal(str(close)),
        high=Decimal(str(high)),
        low=Decimal(str(low)),
        close=Decimal(str(close)),
        volume=volume,
    )


def _make_bars(n: int, base_ts: datetime | None = None) -> list[Bar]:
    """n sequential 1-minute bars with synthetic prices."""
    if base_ts is None:
        base_ts = datetime(2024, 1, 2, 14, 30, tzinfo=_UTC)
    bars = []
    for i in range(n):
        ts = base_ts + timedelta(minutes=i)
        close = 100.0 + i * 0.1
        bars.append(
            Bar(
                symbol="SPY",
                timeframe="1m",
                ts_utc=ts,
                open=Decimal(str(close)),
                high=Decimal(str(close + 0.5)),
                low=Decimal(str(close - 0.5)),
                close=Decimal(str(close)),
                volume=1000,
            )
        )
    return bars


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def orb_bars():
    from fixtures.orb_day import orb_day_bars
    return orb_day_bars()


# ---------------------------------------------------------------------------
# ATRWilder — behavior
# ---------------------------------------------------------------------------


def test_atr_cold_state():
    atr = ATRWilder(14)
    assert atr.current is None
    assert atr.is_warm is False


def test_atr_not_warm_after_14_bars():
    atr = ATRWilder(14)
    for bar in _make_bars(14):
        atr.push(bar)
    assert atr.current is None


def test_atr_warm_after_15_bars():
    atr = ATRWilder(14)
    for bar in _make_bars(15):
        atr.push(bar)
    assert atr.current is not None
    assert atr.current > Decimal("0")


def test_atr_snapshot_at_0_is_none():
    atr = ATRWilder(14)
    for bar in _make_bars(15):
        atr.push(bar)
    assert atr.snapshot_at(0) is None


def test_atr_snapshot_at_beyond_pushed_is_none():
    atr = ATRWilder(14)
    for bar in _make_bars(15):
        atr.push(bar)
    assert atr.snapshot_at(100) is None


def test_atr_warmup_bars():
    assert ATRWilder(14).warmup_bars() == 15
    assert ATRWilder(5).warmup_bars() == 6


# ---------------------------------------------------------------------------
# ATRWilder — leakage proof
# ---------------------------------------------------------------------------


def test_atr_leakage_proof(orb_bars):
    """snapshot_at(t) must equal recomputing from scratch on bars[0:t]."""
    bars = orb_bars
    indicator = ATRWilder(14)
    for bar in bars:
        indicator.push(bar)

    # Check a sample of t values (not all 390 to keep test fast)
    for t in list(range(0, 50)) + list(range(100, 110)):
        fresh = ATRWilder(14)
        for b in bars[:t]:
            fresh.push(b)
        expected = fresh.current
        actual = indicator.snapshot_at(t)
        assert actual == expected, f"ATR leakage at t={t}: got {actual}, expected {expected}"


def test_atr_no_future_bleed(orb_bars):
    """snapshot_at(t) is not affected by bars pushed after t."""
    bars = orb_bars
    # Build indicator with only first 30 bars
    ind_partial = ATRWilder(14)
    for bar in bars[:30]:
        ind_partial.push(bar)
    snapshot_before = ind_partial.snapshot_at(20)

    # Push 60 more bars
    for bar in bars[30:90]:
        ind_partial.push(bar)
    snapshot_after = ind_partial.snapshot_at(20)

    assert snapshot_before == snapshot_after


# ---------------------------------------------------------------------------
# SessionVWAP — behavior
# ---------------------------------------------------------------------------


def test_vwap_cold_state():
    v = SessionVWAP()
    assert v.current is None
    assert v.is_warm is False


def test_vwap_warm_after_1_bar():
    v = SessionVWAP()
    b = _bar(close=100.0, high=100.5, low=99.5, volume=1000)
    v.push(b)
    tp = (Decimal("100.5") + Decimal("99.5") + Decimal("100.0")) / Decimal("3")
    assert v.current == tp


def test_vwap_snapshot_at_1(orb_bars):
    v = SessionVWAP()
    v.push(orb_bars[0])
    bar0 = orb_bars[0]
    expected = (bar0.high + bar0.low + bar0.close) / Decimal("3")
    assert v.snapshot_at(1) == expected


def test_vwap_warmup_bars():
    assert SessionVWAP().warmup_bars() == 1


def test_vwap_snapshot_at_0_is_none(orb_bars):
    v = SessionVWAP()
    for bar in orb_bars[:30]:
        v.push(bar)
    assert v.snapshot_at(0) is None


# ---------------------------------------------------------------------------
# SessionVWAP — session reset test
# ---------------------------------------------------------------------------


def test_vwap_session_reset():
    """When bars cross an ET date boundary, VWAP resets to the new session."""
    # Day 1: 2024-01-02 14:30 UTC (= 09:30 EST)
    day1_ts = datetime(2024, 1, 2, 14, 30, tzinfo=_UTC)
    # Day 2: 2024-01-03 14:30 UTC (= 09:30 EST)
    day2_ts = datetime(2024, 1, 3, 14, 30, tzinfo=_UTC)

    b1 = Bar(
        symbol="SPY", timeframe="1m", ts_utc=day1_ts,
        open=Decimal("100"), high=Decimal("101"), low=Decimal("99"),
        close=Decimal("100"), volume=1000,
    )
    b2 = Bar(
        symbol="SPY", timeframe="1m", ts_utc=day2_ts,
        open=Decimal("200"), high=Decimal("202"), low=Decimal("198"),
        close=Decimal("200"), volume=500,
    )

    v = SessionVWAP()
    v.push(b1)
    v.push(b2)

    # snapshot_at(2) = VWAP for bar at index 1 (day 2, first bar of new session)
    # It should only reflect b2 (session reset)
    tp_b2 = (Decimal("202") + Decimal("198") + Decimal("200")) / Decimal("3")
    assert v.snapshot_at(2) == tp_b2


# ---------------------------------------------------------------------------
# SessionVWAP — leakage proof
# ---------------------------------------------------------------------------


def test_vwap_leakage_proof(orb_bars):
    """snapshot_at(t) must equal recomputing from scratch on bars[0:t]."""
    bars = orb_bars
    indicator = SessionVWAP()
    for bar in bars:
        indicator.push(bar)

    for t in list(range(0, 30)) + list(range(100, 110)):
        fresh = SessionVWAP()
        for b in bars[:t]:
            fresh.push(b)
        expected = fresh.current
        actual = indicator.snapshot_at(t)
        assert actual == expected, f"VWAP leakage at t={t}: got {actual}, expected {expected}"


# ---------------------------------------------------------------------------
# EMA — behavior
# ---------------------------------------------------------------------------


def test_ema_cold_state():
    e = EMA(20)
    assert e.current is None
    assert e.is_warm is False


def test_ema_not_warm_after_19_bars():
    e = EMA(20)
    for bar in _make_bars(19):
        e.push(bar)
    assert e.current is None


def test_ema_warm_after_20_bars():
    e = EMA(20)
    bars = _make_bars(20)
    for bar in bars:
        e.push(bar)
    # First EMA = SMA of first 20 closes
    expected = sum(b.close for b in bars) / Decimal("20")
    assert e.current == expected


def test_ema_snapshot_at_20_equals_sma(orb_bars):
    bars = orb_bars
    e = EMA(20)
    for bar in bars:
        e.push(bar)
    expected = sum(b.close for b in bars[:20]) / Decimal("20")
    assert e.snapshot_at(20) == expected


def test_ema_snapshot_at_0_is_none(orb_bars):
    e = EMA(20)
    for bar in orb_bars[:25]:
        e.push(bar)
    assert e.snapshot_at(0) is None


def test_ema_warmup_bars():
    assert EMA(20).warmup_bars() == 20
    assert EMA(9).warmup_bars() == 9


# ---------------------------------------------------------------------------
# EMA — leakage proof
# ---------------------------------------------------------------------------


def test_ema_leakage_proof(orb_bars):
    """snapshot_at(t) must equal recomputing from scratch on bars[0:t]."""
    bars = orb_bars
    indicator = EMA(20)
    for bar in bars:
        indicator.push(bar)

    for t in list(range(0, 50)):
        fresh = EMA(20)
        for b in bars[:t]:
            fresh.push(b)
        expected = fresh.current
        actual = indicator.snapshot_at(t)
        assert actual == expected, f"EMA leakage at t={t}: got {actual}, expected {expected}"


# ---------------------------------------------------------------------------
# ADR — helpers
# ---------------------------------------------------------------------------


def _make_multi_day_bars(n_days: int = 15) -> list[Bar]:
    """n_days × 390 1m bars, each day starting at 14:30 UTC."""
    bars: list[Bar] = []
    from datetime import date
    base_date = date(2024, 1, 2)
    # We need n_days trading days; skip weekends
    trading_days: list[date] = []
    d = base_date
    while len(trading_days) < n_days:
        if d.weekday() < 5:  # Mon-Fri
            trading_days.append(d)
        d += timedelta(days=1)

    for day_idx, tday in enumerate(trading_days):
        # Use 14:30 UTC (EST window). Note: some dates may be EDT but for
        # synthetic data this doesn't matter — the day boundary is what counts.
        open_utc = datetime(tday.year, tday.month, tday.day, 14, 30, tzinfo=_UTC)
        # Vary daily range per day: day_idx * 0.5 + 1.0
        day_range = 1.0 + day_idx * 0.1
        for bar_i in range(390):
            ts = open_utc + timedelta(minutes=bar_i)
            close = 100.0 + day_idx * 0.5
            high = close + day_range / 2
            low = close - day_range / 2
            bars.append(
                Bar(
                    symbol="SPY",
                    timeframe="1m",
                    ts_utc=ts,
                    open=Decimal(str(close)),
                    high=Decimal(str(round(high, 4))),
                    low=Decimal(str(round(low, 4))),
                    close=Decimal(str(close)),
                    volume=1000,
                )
            )
    return bars


# ---------------------------------------------------------------------------
# ADR — behavior
# ---------------------------------------------------------------------------


def test_adr_cold_state():
    a = ADR(10)
    assert a.current is None
    assert a.is_warm is False


def test_adr_not_warm_with_insufficient_days():
    """With fewer than 11 complete trading days, ADR should be None."""
    a = ADR(10)
    bars = _make_multi_day_bars(10)  # 10 complete days
    for bar in bars:
        a.push(bar)
    # 10 days: after shift(1), only 9 shifted values available for rolling(10) -> None
    assert a.current is None


def test_adr_warm_after_11_days():
    """With 11+ complete trading days, ADR should be a positive Decimal."""
    a = ADR(10)
    bars = _make_multi_day_bars(12)  # 12 complete days
    for bar in bars:
        a.push(bar)
    assert a.current is not None
    assert a.current > Decimal("0")


# ---------------------------------------------------------------------------
# ADR — BL-3 test: today's partial range excluded
# ---------------------------------------------------------------------------


def test_adr_bl3_today_outlier_excluded():
    """BL-3: an extreme outlier in today's partial bars must NOT appear in ADR.

    We build 11 complete days + 1 bar of a 12th day with an extreme range,
    then verify that ADR uses only the complete prior days (shift enforced).
    """
    a_with_outlier = ADR(10)
    a_no_outlier = ADR(10)

    # 11 complete days
    normal_bars = _make_multi_day_bars(11)

    for bar in normal_bars:
        a_with_outlier.push(bar)
        a_no_outlier.push(bar)

    # Add 1 bar for day 12 with extreme range (outlier)
    last_normal = normal_bars[-1]
    next_day = last_normal.ts_utc + timedelta(days=3)  # skip to next week Mon
    outlier_bar = Bar(
        symbol="SPY",
        timeframe="1m",
        ts_utc=datetime(next_day.year, next_day.month, next_day.day, 14, 30, tzinfo=_UTC),
        open=Decimal("100"),
        high=Decimal("999"),  # Extreme outlier range
        low=Decimal("1"),
        close=Decimal("100"),
        volume=1000,
    )
    # Normal day-12 first bar
    normal_bar_12 = Bar(
        symbol="SPY",
        timeframe="1m",
        ts_utc=datetime(next_day.year, next_day.month, next_day.day, 14, 30, tzinfo=_UTC),
        open=Decimal("100"),
        high=Decimal("100.5"),
        low=Decimal("99.5"),
        close=Decimal("100"),
        volume=1000,
    )

    a_with_outlier.push(outlier_bar)
    a_no_outlier.push(normal_bar_12)

    # ADR should be the same (today's partial range excluded by BL-3 shift)
    assert a_with_outlier.current == a_no_outlier.current, (
        f"BL-3 violated: outlier leaked into ADR. "
        f"with={a_with_outlier.current}, without={a_no_outlier.current}"
    )


# ---------------------------------------------------------------------------
# ADR — leakage proof
# ---------------------------------------------------------------------------


def test_adr_leakage_proof():
    """snapshot_at(t) must equal recomputing from scratch on bars[0:t].

    Test at day-boundary t values to verify the BL-3 shift is preserved.
    """
    bars = _make_multi_day_bars(15)
    indicator = ADR(10)
    for bar in bars:
        indicator.push(bar)

    # Test at full-day boundaries (t = 390, 780, ...) and one mid-day value
    day_boundaries = [0, 390, 780, 1170, 2340, 3120, 3900]
    for t in day_boundaries:
        fresh = ADR(10)
        for b in bars[:t]:
            fresh.push(b)
        expected = fresh.current
        actual = indicator.snapshot_at(t)
        assert actual == expected, (
            f"ADR leakage at t={t}: got {actual}, expected {expected}"
        )
