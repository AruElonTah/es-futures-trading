"""Tests for the `trading_core.instruments` Single-Source-of-Truth registry.

Plan 01-02 / Task 1. Covers every `<behavior>` bullet:
- ES / MES / SPY pre-constructed Instruments with exact Decimal pricing.
- `get('UNKNOWN')` raises KeyError with the known-instruments list in the message.
- Frozen + extra='forbid' enforced via pydantic.ValidationError.
- All three instruments record RTH window strings (09:30 / 16:00).
"""

from __future__ import annotations

from decimal import Decimal

import pydantic
import pytest

from trading_core.instruments import REGISTRY, Instrument, get


class TestESInstrument:
    def test_es_tick_value(self):
        assert get("ES").tick_value == Decimal("12.50")

    def test_es_point_value(self):
        assert get("ES").point_value == Decimal("50.00")

    def test_es_tick_size(self):
        assert get("ES").tick_size == Decimal("0.25")

    def test_es_calendar_name(self):
        assert get("ES").calendar_name == "CME_Equity"

    def test_es_asset_class(self):
        assert get("ES").asset_class == "future"

    def test_es_is_continuous(self):
        assert get("ES").is_continuous is True


class TestMESInstrument:
    def test_mes_tick_value(self):
        assert get("MES").tick_value == Decimal("1.25")

    def test_mes_point_value(self):
        assert get("MES").point_value == Decimal("5.00")

    def test_mes_tick_size(self):
        assert get("MES").tick_size == Decimal("0.25")

    def test_mes_calendar_name(self):
        assert get("MES").calendar_name == "CME_Equity"


class TestSPYInstrument:
    def test_spy_tick_value(self):
        assert get("SPY").tick_value == Decimal("0.01")

    def test_spy_point_value(self):
        assert get("SPY").point_value == Decimal("1.00")

    def test_spy_tick_size(self):
        assert get("SPY").tick_size == Decimal("0.01")

    def test_spy_calendar_name(self):
        assert get("SPY").calendar_name == "NYSE"

    def test_spy_asset_class(self):
        assert get("SPY").asset_class == "etf"

    def test_spy_is_continuous(self):
        assert get("SPY").is_continuous is False


class TestRegistryShape:
    def test_registry_known_symbols(self):
        assert set(REGISTRY.keys()) == {"ES", "MES", "SPY"}

    def test_get_unknown_raises_key_error_with_known_list(self):
        with pytest.raises(KeyError) as exc:
            get("UNKNOWN")
        msg = str(exc.value)
        # The message must enumerate the known instruments so operators see options.
        assert "ES" in msg
        assert "MES" in msg
        assert "SPY" in msg

    def test_all_instruments_rth_open_0930(self):
        for symbol in ("ES", "MES", "SPY"):
            assert get(symbol).rth_open_et == "09:30"

    def test_all_instruments_rth_close_1600(self):
        for symbol in ("ES", "MES", "SPY"):
            assert get(symbol).rth_close_et == "16:00"


class TestInstrumentFrozen:
    def test_mutation_raises_validation_error(self):
        inst = get("ES")
        with pytest.raises(pydantic.ValidationError):
            inst.tick_value = Decimal("0.5")  # type: ignore[misc]

    def test_extra_field_rejected(self):
        with pytest.raises(pydantic.ValidationError):
            Instrument(
                symbol="X",
                description="bogus",
                tick_size=Decimal("0.01"),
                tick_value=Decimal("0.01"),
                point_value=Decimal("1.00"),
                calendar_name="NYSE",
                rth_open_et="09:30",
                rth_close_et="16:00",
                asset_class="etf",
                is_continuous=False,
                extra_field=1,  # type: ignore[call-arg]
            )

    def test_invalid_rth_pattern_rejected(self):
        # Pattern enforces HH:MM — "9:30" (single-digit hour) must fail.
        with pytest.raises(pydantic.ValidationError):
            Instrument(
                symbol="TEST",
                description="bogus",
                tick_size=Decimal("0.01"),
                tick_value=Decimal("0.01"),
                point_value=Decimal("1.00"),
                calendar_name="NYSE",
                rth_open_et="9:30",
                rth_close_et="16:00",
                asset_class="etf",
                is_continuous=False,
            )
