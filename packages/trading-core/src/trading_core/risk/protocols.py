"""RiskManager Protocol seam — signature only.

Locked here by Plan 01-02; Phase 5 implements the prop-firm-style RiskManager
against this seam. NO runtime-checkable decorator (see 01-RESEARCH.md §Anti-Patterns).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from trading_core.strategy.models import Signal

    from .models import RiskDecision, RiskState


class RiskManager(Protocol):
    """Pre-trade risk check. Phase 5 ships the first implementation."""

    async def check(self, signal: "Signal", state: "RiskState") -> "RiskDecision":
        """Approve/reject/size-adjust the signal. Phase 5 owns the body."""
        ...
