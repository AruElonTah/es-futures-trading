"""Strategy Protocol seam — signature only.

Locked here by Plan 01-02; Phase 2 implements the body of the first concrete
Strategy (Opening Range Breakout) against this seam. NO runtime-checkable
decorator (see 01-RESEARCH.md §Anti-Patterns line 948).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from trading_core.data.models import Bar

    from .models import Signal, StrategyContext


class Strategy(Protocol):
    """Per-bar strategy contract. Phase 2 ships the first implementation."""

    name: str
    version: str

    def warmup_bars(self) -> int:
        """Number of bars to feed before signals are valid."""
        ...

    def on_bar(self, bar: "Bar", ctx: "StrategyContext") -> "Signal | None":
        """Consume one bar; optionally emit a Signal. Phase 2 owns the body."""
        ...
