"""Strategy domain — Protocol seam (signature-only Phase 1).

Phase 2 fills in `Signal` / `StrategyContext` bodies and ships the first concrete
Strategy (Opening Range Breakout). Phase 1 ships the seam so Plan 03/04 can
import it without dangling references.

Phase 2 Plan 02 adds:
  - ORBConfig + ORBStrategy (opening_range_breakout)
  - StrategyRegistry (YAML-based loader)
"""

from __future__ import annotations

from .models import Signal, StrategyContext
from .orb import ORBConfig, ORBStrategy
from .protocols import Strategy
from .registry import StrategyRegistry

__all__ = [
    "Signal",
    "Strategy",
    "StrategyContext",
    "ORBConfig",
    "ORBStrategy",
    "StrategyRegistry",
]
