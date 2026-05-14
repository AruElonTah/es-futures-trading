"""Executor Protocol seam — signature only.

Locked here by Plan 01-02; Phase 5 implements the paper Executor against this
seam. NO runtime-checkable decorator (see 01-RESEARCH.md §Anti-Patterns).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from trading_core.risk.models import RiskDecision
    from trading_core.strategy.models import Signal

    from .models import Fill


class Executor(Protocol):
    """Paper-fill execution against the next bar. Phase 5 ships the body."""

    async def fill(self, signal: "Signal", decision: "RiskDecision") -> "Fill":
        """Simulate (or eventually live-route) a fill. Phase 5 owns the body."""
        ...
