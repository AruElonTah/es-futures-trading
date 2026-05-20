"""Shared pytest fixtures for the trading-core package.

Plan 01-02 + 01-03 + 01-04 extend this file with shared fixtures. Downstream
packages (`api`, `tv-bridge`) re-export the shared set via
`pytest_plugins = ["trading_core.tests.conftest"]` in their own conftest (the
re-export mechanism still works under pytest's --import-mode=importlib because
conftest discovery is file-path-based, not Python-package-based; see Plan 01-01
SUMMARY.md "Deviations" #1).

Plan 03 owns the DST + half-day + rollover fixtures and prepends the tests/
directory to sys.path so test modules can `from fixtures.dst_bars import ...`
under --import-mode=importlib (no tests/__init__.py per Plan 01-01).

Plan 08-01 adds the --update-golden option for the replay audit-log golden
fixture test (SP-04 reproducibility CI).
"""

from __future__ import annotations

import sys
from pathlib import Path


def pytest_addoption(parser):
    """Register --update-golden flag for regenerating golden audit-log fixtures.

    When set, test_replay_audit_log_byte_identical (and related tests) will
    regenerate the committed golden CSV instead of asserting against it.

    Usage:
        uv run pytest packages/trading-core/tests/integration/test_replay_audit_log.py --update-golden

    Run without the flag to assert (CI mode).
    """
    parser.addoption(
        "--update-golden",
        action="store_true",
        default=False,
        help=(
            "Regenerate golden audit-log CSV fixture instead of asserting against it. "
            "Run: uv run pytest packages/trading-core/tests/integration/"
            "test_replay_audit_log.py --update-golden"
        ),
    )

# Make `fixtures/` importable from any test module under --import-mode=importlib.
# Plan 01-01 decision: no tests/__init__.py to avoid the cross-package conftest
# plugin-registration collision. Consequence: pytest does NOT add the tests/
# dir to sys.path. We do it here once, at conftest load time.
_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

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


# ---------------------------------------------------------------------------
# Plan 01-03 — DST + half-day + synthetic-day fixtures (Pattern 3 evidence)
# ---------------------------------------------------------------------------


@pytest.fixture
def dst_spring_forward_2026_03_09():
    """390-row 1m DataFrame for Mon 2026-03-09 (first trading day after DST starts)."""
    from fixtures.dst_bars import make_dst_spring_forward_2026_03_09_bars

    return make_dst_spring_forward_2026_03_09_bars()


@pytest.fixture
def dst_fall_back_2026_11_02():
    """390-row 1m DataFrame for Mon 2026-11-02 (first trading day after DST ends)."""
    from fixtures.dst_bars import make_dst_fall_back_2026_11_02_bars

    return make_dst_fall_back_2026_11_02_bars()


@pytest.fixture
def cme_half_day_thanksgiving_2024_11_29():
    """210-row 1m DataFrame for Black Friday 2024 (early close at 13:00 ET)."""
    from fixtures.dst_bars import make_cme_half_day_2024_11_29_bars

    return make_cme_half_day_2024_11_29_bars()


@pytest.fixture
def synthetic_spy_day():
    """Factory that yields `make_synthetic_spy_day_bars(date)` — for parametric tests."""
    from fixtures.dst_bars import make_synthetic_spy_day_bars

    return make_synthetic_spy_day_bars
