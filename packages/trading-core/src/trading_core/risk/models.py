"""Risk domain models — Phase 5 extended (Plan 01).

Phase 3 established the minimal fields required for the backtester.
Phase 5 extends RiskConfig and RiskState with drawdown-tracking fields
and adds the DrawdownModel enum. RiskDecision is unchanged.

Extension rules (D-10 from Phase 3 context):
- RiskConfig and RiskState are NOT frozen — extensions add fields with defaults.
- extra="forbid" is preserved on all models.
- RiskDecision fields have no defaults — caller MUST supply all three.
"""

from __future__ import annotations

from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict


class DrawdownModel(str, Enum):
    """Active drawdown tracking model (D-04).

    Inherits ``str`` so pydantic loads it from a YAML string value without
    a custom validator. All three models are tracked side-by-side in the
    ``risk_state`` DuckDB table; this enum selects the active circuit-breaker.

    Values:
        STATIC: HWM is fixed at session start (``account_equity``). The DD
            floor never rises intraday — most conservative.
        TRAILING_EOD: HWM updates at session close each day. Intraday it
            behaves like STATIC; the ratchet happens overnight.
        TRAILING_INTRADAY: HWM updates in real time (Apex-style). The floor
            rises as unrealized gains accumulate — strictest intraday.
    """

    STATIC = "STATIC"
    TRAILING_EOD = "TRAILING_EOD"
    TRAILING_INTRADAY = "TRAILING_INTRADAY"

    def __str__(self) -> str:  # noqa: D105
        # Python 3.11+ changed str(StrEnum) to include the class name.
        # Override to return the bare value so YAML round-trips cleanly.
        return self.value


class RiskConfig(BaseModel):
    """Risk-manager configuration.

    Phase 3 fields (backward-compatible defaults):
        max_contracts: Maximum contracts allowed per signal.

    Phase 5 fields (D-01 / D-02 / D-03 / D-04):
        account_equity: Static starting equity for sizing math (paper-only).
        max_risk_per_trade_pct: Fraction of equity risked per trade.
        daily_dd_limit: Dollar amount that triggers the daily circuit breaker.
        drawdown_model: Which HWM model gates the circuit breaker.
    """

    model_config = ConfigDict(extra="forbid")

    max_contracts: int = 1

    # Phase 5 extensions — all have safe defaults so Phase 3 callers continue
    # to instantiate RiskConfig() without arguments.
    account_equity: Decimal = Decimal("50000")
    max_risk_per_trade_pct: Decimal = Decimal("0.01")
    daily_dd_limit: Decimal = Decimal("2000")
    drawdown_model: DrawdownModel = DrawdownModel.TRAILING_INTRADAY


class RiskState(BaseModel):
    """Per-day risk state.

    Phase 3 fields (backward-compatible defaults):
        realized_pnl_today: Sum of closed-trade P&L for the current session.

    Phase 5 fields (D-13):
        equity_high_water: HWM value for the active DD model.
        open_exposure_dollars: Current unrealized exposure (mark-to-market).
        drawdown_model: Which model is tracking the HWM (mirrors RiskConfig).
    """

    model_config = ConfigDict(extra="forbid")

    realized_pnl_today: Decimal = Decimal("0")

    # Phase 5 extensions — safe defaults preserve Phase 3 backward compat.
    equity_high_water: Decimal = Decimal("0")
    open_exposure_dollars: Decimal = Decimal("0")
    drawdown_model: DrawdownModel = DrawdownModel.TRAILING_INTRADAY


class RiskDecision(BaseModel):
    """RiskManager output — D-10 minimal fields.

    All three fields are required (no defaults) — caller MUST supply them.
    """

    model_config = ConfigDict(extra="forbid")

    approved: bool
    reason: str
    adjusted_size: int
