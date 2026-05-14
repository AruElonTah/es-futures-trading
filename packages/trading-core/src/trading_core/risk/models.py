"""Risk domain models — signature-only stubs for Plan 01-02.

Phase 5 fills in the concrete fields:
- RiskConfig: account_equity, max_risk_per_trade_pct, daily_dd_limit, max_contracts_per_strategy
- RiskState: realized_pnl_today, equity_high_water, open_exposure_$
- RiskDecision: approved, reason, adjusted_size
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class RiskConfig(BaseModel):
    """Risk-manager config. Phase 5 fills in: account_equity,
    max_risk_per_trade_pct, daily_dd_limit, max_contracts_per_strategy."""

    model_config = ConfigDict(extra="forbid")


class RiskState(BaseModel):
    """Per-day risk state. Phase 5 fills in: realized_pnl_today,
    equity_high_water, open_exposure_$."""

    model_config = ConfigDict(extra="forbid")


class RiskDecision(BaseModel):
    """RiskManager output. Phase 5 fills in: approved, reason, adjusted_size."""

    model_config = ConfigDict(extra="forbid")
