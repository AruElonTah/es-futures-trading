"""Risk domain — Protocol seam (signature-only Phase 1).

Phase 5 fills in `RiskConfig` / `RiskState` / `RiskDecision` bodies and ships
the prop-firm-style RiskManager ($50k account, 2% per-trade risk, $2k daily DD
circuit breaker).
"""

from __future__ import annotations

from .models import RiskConfig, RiskDecision, RiskState
from .protocols import RiskManager

__all__ = ["RiskConfig", "RiskDecision", "RiskManager", "RiskState"]
