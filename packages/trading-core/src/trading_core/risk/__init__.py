"""Risk domain — Protocol seam + Phase 3 minimal implementations + Phase 5 full manager.

Phase 3 (Plan 02) adds:
  - PassThroughRiskManager: always approves, clamps adjusted_size to max_contracts

Phase 5 (Plan 02) adds:
  - FullRiskManager: prop-firm-style risk gate ($50k account, 1% per-trade risk,
    $2k daily DD circuit breaker, all three DrawdownModel variants tracked,
    asyncio.Event kill-switch, per-strategy concurrency cap)
  - size_for_stop: pure function for ATR-based position sizing (RM-01)
"""

from __future__ import annotations

from .full_risk_manager import FullRiskManager, size_for_stop
from .models import RiskConfig, RiskDecision, RiskState
from .pass_through import PassThroughRiskManager
from .protocols import RiskManager

__all__ = [
    "FullRiskManager",
    "PassThroughRiskManager",
    "RiskConfig",
    "RiskDecision",
    "RiskManager",
    "RiskState",
    "size_for_stop",
]
