"""Risk domain models — D-10 minimal fields (Phase 3 Plan 01).

Phase 3 fills in the minimal fields required for the backtester:
- RiskConfig: max_contracts (Phase 5 adds account_equity, max_risk_per_trade_pct, daily_dd_limit)
- RiskState: realized_pnl_today (Phase 5 adds equity_high_water, open_exposure_$)
- RiskDecision: approved, reason, adjusted_size

Note: RiskConfig and RiskState are NOT frozen — Phase 5 can extend cleanly.
RiskDecision fields have no defaults — caller MUST supply all three.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class RiskConfig(BaseModel):
    """Risk-manager configuration — D-10 minimal fields.

    Phase 5 adds: account_equity, max_risk_per_trade_pct, daily_dd_limit,
    max_contracts_per_strategy.
    """

    model_config = ConfigDict(extra="forbid")

    max_contracts: int = 1


class RiskState(BaseModel):
    """Per-day risk state — D-10 minimal fields.

    Phase 5 adds: equity_high_water, open_exposure_$.
    """

    model_config = ConfigDict(extra="forbid")

    realized_pnl_today: Decimal = Decimal("0")


class RiskDecision(BaseModel):
    """RiskManager output — D-10 minimal fields.

    All three fields are required (no defaults) — caller MUST supply them.
    """

    model_config = ConfigDict(extra="forbid")

    approved: bool
    reason: str
    adjusted_size: int
