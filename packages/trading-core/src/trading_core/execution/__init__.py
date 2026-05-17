"""Execution domain — Protocol seam + Phase 3 minimal implementations.

Phase 3 (Plan 02) adds:
  - PaperExecutor: next-bar fill simulation with session-phase slippage, stop-first
    intrabar conflict resolution (D-12), and EOD flatten (BT-08)

Phase 5 extends PaperExecutor with commission tracking and live broker adapters.
"""

from __future__ import annotations

from .models import Fill
from .paper import PaperExecutor
from .protocols import Executor

__all__ = ["Executor", "Fill", "PaperExecutor"]
