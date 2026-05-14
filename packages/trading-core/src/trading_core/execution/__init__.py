"""Execution domain — Protocol seam (signature-only Phase 1).

Phase 5 fills in `Fill` body and ships the paper Executor (next-bar entry,
slippage in ticks, round-turn commission).
"""

from __future__ import annotations

from .models import Fill
from .protocols import Executor

__all__ = ["Executor", "Fill"]
