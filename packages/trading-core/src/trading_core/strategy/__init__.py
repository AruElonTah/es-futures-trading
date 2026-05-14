"""Strategy domain — Protocol seam (signature-only Phase 1).

Phase 2 fills in `Signal` / `StrategyContext` bodies and ships the first concrete
Strategy (Opening Range Breakout). Phase 1 ships the seam so Plan 03/04 can
import it without dangling references.
"""

from __future__ import annotations

from .models import Signal, StrategyContext
from .protocols import Strategy

__all__ = ["Signal", "Strategy", "StrategyContext"]
