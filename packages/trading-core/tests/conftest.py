"""Shared pytest fixtures for the trading-core package.

Plan 01-02 + 01-03 + 01-04 extend this file with shared fixtures. Downstream
packages (`api`, `tv-bridge`) re-export the shared set via
`pytest_plugins = ["trading_core.tests.conftest"]` in their own conftest (the
re-export mechanism still works under pytest's --import-mode=importlib because
conftest discovery is file-path-based, not Python-package-based; see Plan 01-01
SUMMARY.md "Deviations" #1).

Plan 03 will own the DST + rollover fixtures. Plan 01-02 only registers the
three Instrument fixtures.
"""

from __future__ import annotations

import pytest

from trading_core.instruments import Instrument, get


@pytest.fixture
def es_instrument() -> Instrument:
    """The ES (E-mini S&P 500) Instrument from the SoT registry."""
    return get("ES")


@pytest.fixture
def mes_instrument() -> Instrument:
    """The MES (Micro E-mini S&P 500) Instrument from the SoT registry."""
    return get("MES")


@pytest.fixture
def spy_instrument() -> Instrument:
    """The SPY (SPDR S&P 500 ETF) Instrument from the SoT registry."""
    return get("SPY")
