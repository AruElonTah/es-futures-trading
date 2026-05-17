"""Risk domain — Protocol seam + Phase 3 minimal implementations.

Phase 3 (Plan 02) adds:
  - PassThroughRiskManager: always approves, clamps adjusted_size to max_contracts

Phase 5 fills in the prop-firm-style RiskManager ($50k account, 2% per-trade
risk, $2k daily DD circuit breaker) against the same RiskManager Protocol seam.
"""

from __future__ import annotations

from .models import RiskConfig, RiskDecision, RiskState
from .pass_through import PassThroughRiskManager
from .protocols import RiskManager

__all__ = [
    "PassThroughRiskManager",
    "RiskConfig",
    "RiskDecision",
    "RiskManager",
    "RiskState",
]
