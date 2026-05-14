"""Single-source-of-truth instrument registry for the ES Trading System.

FND-06 evidence file. Every dollar-denominated calculation downstream (risk math,
position sizing, P&L) reads tick_value / point_value / tick_size from `REGISTRY`
exclusively. Hardcoding these numerics anywhere else is a Phase 1 lint failure.

Decimal — not float — because ATR-based position sizing depends on exact
arithmetic. Float drift produces 1-tick miscounts at boundaries; over a 252-day
backtest those miscounts compound into multi-thousand-dollar reproducibility
gaps. See 01-RESEARCH.md §Pattern 2 for the full rationale.

Frozen — `model_config = ConfigDict(frozen=True, extra="forbid")` — because
mutating an Instrument mid-run silently changes the meaning of every persisted
bar. Mutations require a migration ADR.

D-04 / RESEARCH.md Pattern 2: this module records only the `calendar_name` and
the `rth_open_et` / `rth_close_et` window strings. The actual RTH window
derivation lives in Plan 03's `calendars/rth.py` — *no* session times are
duplicated here.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# Calendars supported in v1. NYSE for SPY (ETF on Arca, NYSE schedule applies);
# CME_Equity for ES/MES (CME-specific half-days; the 23-hour Globex session is
# filtered down to the 09:30–16:00 ET window by Plan 03's RTH derivation).
CalendarName = Literal["CME_Equity", "NYSE"]


class Instrument(BaseModel):
    """Frozen instrument metadata. Mutation requires a migration ADR."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str = Field(min_length=1, max_length=10)
    description: str
    # Smallest price increment (0.25 for ES, 0.01 for SPY).
    tick_size: Decimal
    # Dollar value per tick per contract ($12.50 ES, $1.25 MES, $0.01 SPY).
    tick_value: Decimal
    # Dollar value per 1.00 price move ($50 ES, $5 MES, $1 SPY).
    point_value: Decimal
    # SoT for session times — instruments.py does NOT duplicate hours per D-04.
    calendar_name: CalendarName
    # Open / close of the cash session (paired with calendar to build RTH).
    rth_open_et: str = Field(pattern=r"^\d{2}:\d{2}$")
    rth_close_et: str = Field(pattern=r"^\d{2}:\d{2}$")
    asset_class: Literal["future", "etf"]
    # ES = True (front-month stitched); MES = True; SPY = False.
    is_continuous: bool
    notes: str = ""


REGISTRY: dict[str, Instrument] = {
    "ES": Instrument(
        symbol="ES",
        description="E-mini S&P 500 futures (continuous front-month)",
        tick_size=Decimal("0.25"),
        tick_value=Decimal("12.50"),
        point_value=Decimal("50.00"),
        calendar_name="CME_Equity",
        rth_open_et="09:30",
        rth_close_et="16:00",
        asset_class="future",
        is_continuous=True,
    ),
    "MES": Instrument(
        symbol="MES",
        description="Micro E-mini S&P 500 futures (continuous front-month)",
        tick_size=Decimal("0.25"),
        tick_value=Decimal("1.25"),
        point_value=Decimal("5.00"),
        calendar_name="CME_Equity",
        rth_open_et="09:30",
        rth_close_et="16:00",
        asset_class="future",
        is_continuous=True,
    ),
    "SPY": Instrument(
        symbol="SPY",
        description="SPDR S&P 500 ETF (NYSE Arca)",
        tick_size=Decimal("0.01"),
        tick_value=Decimal("0.01"),
        point_value=Decimal("1.00"),
        calendar_name="NYSE",
        rth_open_et="09:30",
        rth_close_et="16:00",
        asset_class="etf",
        is_continuous=False,
    ),
}


def get(symbol: str) -> Instrument:
    """Return the registered Instrument, or raise KeyError listing known symbols."""
    if symbol not in REGISTRY:
        raise KeyError(
            f"Unknown instrument: {symbol!r}. Known instruments: {list(REGISTRY)}"
        )
    return REGISTRY[symbol]
