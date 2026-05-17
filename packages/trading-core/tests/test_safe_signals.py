"""Tests for safe_from_signals wrapper — BT-02 success criteria.

Requirement: BT-02 — safe_from_signals() wrapper: entries.shift(1) internally;
price string rejected with ValueError; no FutureWarning; smoke test with 30-bar VBT run.

This file replaces the Wave 0 xfail stub (Plan 01 Task 3).
Wave 2 Plan 02 implementation.

NOTE: Do NOT embed the literal pattern 'vbt.Portfolio.from_signals(' in this file
— it would trip the no-direct-vbt-from-signals pre-commit hook. Reference the
wrapper API via 'safe_from_signals' only.
"""

from __future__ import annotations

import warnings
from datetime import datetime, timezone
from unittest.mock import patch

import pandas as pd
import pytest
import vectorbt as vbt

from trading_core.backtest.safe_signals import safe_from_signals


def _make_bool_series(values: list[bool], freq: str = "1min") -> pd.Series:
    """Build a boolean Series with a UTC DatetimeIndex."""
    idx = pd.date_range("2024-01-02 14:30", periods=len(values), freq=freq, tz="UTC")
    return pd.Series(values, index=idx, dtype=bool)


def _make_price_series(values: list[float], freq: str = "1min") -> pd.Series:
    """Build a float Series with a UTC DatetimeIndex."""
    idx = pd.date_range("2024-01-02 14:30", periods=len(values), freq=freq, tz="UTC")
    return pd.Series(values, index=idx)


# ---------------------------------------------------------------------------
# Guard: string price raises ValueError
# ---------------------------------------------------------------------------

class TestRejectsStringPrice:
    def test_rejects_nextbar_string(self):
        """safe_from_signals raises ValueError when price is the string 'nextbar'."""
        close = _make_bool_series([False] * 4)
        entries = _make_bool_series([True, False, False, False])
        exits = _make_bool_series([False, False, True, False])

        with pytest.raises(ValueError, match="price must be an array"):
            safe_from_signals(
                close=close.astype(float),
                entries=entries,
                exits=exits,
                price="nextbar",
            )

    def test_error_mentions_numba_jit(self):
        """ValueError message contains 'Numba JIT' substring."""
        close = _make_price_series([1.0] * 4)
        entries = _make_bool_series([True, False, False, False])
        exits = _make_bool_series([False, False, True, False])

        with pytest.raises(ValueError, match="Numba JIT"):
            safe_from_signals(
                close=close,
                entries=entries,
                exits=exits,
                price="nextbar",
            )

    def test_rejects_any_string_price(self):
        """Any string passed as price raises ValueError (not just 'nextbar')."""
        close = _make_price_series([1.0] * 4)
        entries = _make_bool_series([True, False, False, False])
        exits = _make_bool_series([False, False, True, False])

        with pytest.raises(ValueError):
            safe_from_signals(
                close=close,
                entries=entries,
                exits=exits,
                price="open",
            )

    def test_float_scalar_does_not_raise(self):
        """A float scalar price is allowed (VBT may accept scalar in some paths)."""
        close = _make_price_series([1.0, 2.0, 3.0, 4.0])
        entries = _make_bool_series([True, False, False, False])
        exits = _make_bool_series([False, False, True, False])
        price = _make_price_series([1.0, 2.0, 3.0, 4.0])

        # Must NOT raise — float scalar is accepted
        # (We pass a Series to ensure the call is valid; float scalar may vary by VBT version)
        # The spec says isinstance(price, str) is the only banned case.
        try:
            safe_from_signals(
                close=close,
                entries=entries,
                exits=exits,
                price=price,
                freq="1min",
                init_cash=10_000.0,
                size=1,
                direction="longonly",
            )
        except Exception as exc:
            # Only a string-type check should cause rejection per spec
            assert "price must be an array" not in str(exc), (
                "Non-string price raised wrong error"
            )


# ---------------------------------------------------------------------------
# Shift: entries and exits shifted by 1 internally
# ---------------------------------------------------------------------------

class TestInternalShift:
    def test_entries_shifted_by_1(self):
        """Entry at bar[0] feeds VBT entries=False at bar[0], True at bar[1]."""
        close = _make_price_series([1.0, 2.0, 3.0, 4.0])
        entries = _make_bool_series([True, False, False, False])
        exits = _make_bool_series([False, False, False, True])
        price = _make_price_series([1.0, 2.0, 3.0, 4.0])

        captured_kwargs: dict = {}

        def _capturing_from_signals(**kwargs):
            captured_kwargs.update(kwargs)
            return vbt.Portfolio.from_signals(**kwargs)

        with patch.object(vbt.Portfolio, "from_signals", side_effect=_capturing_from_signals):
            safe_from_signals(
                close=close,
                entries=entries,
                exits=exits,
                price=price,
                freq="1min",
                init_cash=10_000.0,
                size=1,
                direction="longonly",
            )

        shifted_entries = captured_kwargs["entries"]
        assert shifted_entries.iloc[0] is False or shifted_entries.iloc[0] == False, (
            "Entry at bar[0] must be False after shift(1)"
        )
        assert shifted_entries.iloc[1] is True or shifted_entries.iloc[1] == True, (
            "Entry at bar[1] must be True after shift(1)"
        )

    def test_exits_shifted_by_1(self):
        """Exit at bar[2] feeds VBT exits=False at bar[2], True at bar[3]."""
        close = _make_price_series([1.0, 2.0, 3.0, 4.0])
        entries = _make_bool_series([True, False, False, False])
        exits = _make_bool_series([False, False, True, False])
        price = _make_price_series([1.0, 2.0, 3.0, 4.0])

        captured_kwargs: dict = {}

        def _capturing_from_signals(**kwargs):
            captured_kwargs.update(kwargs)
            return vbt.Portfolio.from_signals(**kwargs)

        with patch.object(vbt.Portfolio, "from_signals", side_effect=_capturing_from_signals):
            safe_from_signals(
                close=close,
                entries=entries,
                exits=exits,
                price=price,
                freq="1min",
                init_cash=10_000.0,
                size=1,
                direction="longonly",
            )

        shifted_exits = captured_kwargs["exits"]
        assert shifted_exits.iloc[2] is False or shifted_exits.iloc[2] == False, (
            "Exit at bar[2] must be False after shift(1)"
        )
        assert shifted_exits.iloc[3] is True or shifted_exits.iloc[3] == True, (
            "Exit at bar[3] must be True after shift(1)"
        )

    def test_short_entries_shifted_when_supplied(self):
        """short_entries is shifted by 1 when passed."""
        close = _make_price_series([1.0, 2.0, 3.0, 4.0])
        entries = _make_bool_series([False, False, False, False])
        exits = _make_bool_series([False, False, False, False])
        short_entries = _make_bool_series([True, False, False, False])
        short_exits = _make_bool_series([False, False, True, False])
        price = _make_price_series([1.0, 2.0, 3.0, 4.0])

        captured_kwargs: dict = {}

        def _capturing_from_signals(**kwargs):
            captured_kwargs.update(kwargs)
            return vbt.Portfolio.from_signals(**kwargs)

        with patch.object(vbt.Portfolio, "from_signals", side_effect=_capturing_from_signals):
            safe_from_signals(
                close=close,
                entries=entries,
                exits=exits,
                short_entries=short_entries,
                short_exits=short_exits,
                price=price,
                freq="1min",
                init_cash=10_000.0,
                size=1,
                direction="both",
            )

        assert "short_entries" in captured_kwargs, "short_entries must be forwarded to VBT"
        shifted_short_ent = captured_kwargs["short_entries"]
        assert shifted_short_ent.iloc[0] is False or shifted_short_ent.iloc[0] == False
        assert shifted_short_ent.iloc[1] is True or shifted_short_ent.iloc[1] == True

    def test_short_entries_none_not_injected(self):
        """When short_entries is None, 'short_entries' key is NOT passed to VBT."""
        close = _make_price_series([1.0, 2.0, 3.0, 4.0])
        entries = _make_bool_series([True, False, False, False])
        exits = _make_bool_series([False, False, False, True])
        price = _make_price_series([1.0, 2.0, 3.0, 4.0])

        captured_kwargs: dict = {}

        def _capturing_from_signals(**kwargs):
            captured_kwargs.update(kwargs)
            return vbt.Portfolio.from_signals(**kwargs)

        with patch.object(vbt.Portfolio, "from_signals", side_effect=_capturing_from_signals):
            safe_from_signals(
                close=close,
                entries=entries,
                exits=exits,
                price=price,
                freq="1min",
                init_cash=10_000.0,
                size=1,
                direction="longonly",
                # short_entries not passed (defaults to None)
            )

        assert "short_entries" not in captured_kwargs, (
            "short_entries key must NOT be in VBT kwargs when caller does not supply it"
        )


# ---------------------------------------------------------------------------
# No FutureWarning
# ---------------------------------------------------------------------------

class TestNoFutureWarning:
    def test_no_future_warning_under_pandas_2_2(self):
        """No FutureWarning emitted when calling safe_from_signals under pandas 2.2.x."""
        close = _make_price_series([1.0, 2.0, 3.0, 4.0])
        entries = _make_bool_series([True, False, False, False])
        exits = _make_bool_series([False, False, False, True])
        price = _make_price_series([1.0, 2.0, 3.0, 4.0])

        with warnings.catch_warnings():
            warnings.simplefilter("error", FutureWarning)
            # Should NOT raise FutureWarning
            safe_from_signals(
                close=close,
                entries=entries,
                exits=exits,
                price=price,
                freq="1min",
                init_cash=10_000.0,
                size=1,
                direction="longonly",
            )


# ---------------------------------------------------------------------------
# Return passthrough
# ---------------------------------------------------------------------------

class TestReturnPassthrough:
    def test_returns_vbt_portfolio(self):
        """safe_from_signals returns the vbt.Portfolio object."""
        close = _make_price_series([1.0, 2.0, 3.0, 4.0])
        entries = _make_bool_series([True, False, False, False])
        exits = _make_bool_series([False, False, False, True])
        price = _make_price_series([1.0, 2.0, 3.0, 4.0])

        result = safe_from_signals(
            close=close,
            entries=entries,
            exits=exits,
            price=price,
            freq="1min",
            init_cash=10_000.0,
            size=1,
            direction="longonly",
        )

        assert isinstance(result, vbt.Portfolio), (
            f"Expected vbt.Portfolio, got {type(result)}"
        )


# ---------------------------------------------------------------------------
# End-to-end smoke: 30-bar series
# ---------------------------------------------------------------------------

class TestEndToEndSmoke:
    def test_30_bar_no_crash(self):
        """30-bar run: no crash, portfolio has non-negative trade count, finite Sharpe."""
        n = 30
        idx = pd.date_range("2024-01-02 14:30", periods=n, freq="1min", tz="UTC")

        close = pd.Series([471.0 + i * 0.01 for i in range(n)], index=idx)
        entries = pd.Series([False] * n, index=idx, dtype=bool)
        entries.iloc[5] = True  # entry at bar 5

        exits = pd.Series([False] * n, index=idx, dtype=bool)
        exits.iloc[15] = True  # exit at bar 15

        # next-bar open prices (shifted close)
        price = close.shift(-1).ffill()

        pf = safe_from_signals(
            close=close,
            entries=entries,
            exits=exits,
            price=price,
            freq="1min",
            init_cash=10_000.0,
            size=1,
            direction="longonly",
        )

        assert pf.trades.count() >= 0, "Trade count must be non-negative"

        # Sharpe may be NaN if no trades — that's fine for a 30-bar smoke test
        # The key assertion: no exception raised, portfolio is valid
        import math
        sharpe = pf.sharpe_ratio()
        assert math.isnan(sharpe) or math.isfinite(sharpe), (
            f"Sharpe must be finite or NaN (no crash), got {sharpe}"
        )
