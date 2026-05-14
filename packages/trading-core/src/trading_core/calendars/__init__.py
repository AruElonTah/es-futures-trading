"""Calendars + RTH-window discipline.

Plan 01-03 ships:
- `rth.py` — hybrid CME_Equity / NYSE calendar filter that derives the
  9:30–16:00 ET cash session from `instruments.py`. Honors early-close
  half-days. `is_rth`, `expected_rth_timestamps`, `trading_days`,
  `rth_window_utc` are module-level helpers. `RthFilter` is the
  DataFrame-level convenience wrapper.
- `rth.py` also exports `third_friday`, `is_rollover_seam`, and
  `RolloverDetector` (Pattern 4) — the 3rd-Friday-of-quarter detector
  consumed by storage layer to flag `rollover_seam` on bars.

Why a separate `calendars/` package and not a single `calendars.py`?
Phase 1 v1 fits in one file; we leave room for future per-exchange or
per-asset-class submodules without re-shuffling imports.
"""

from __future__ import annotations

from .rth import (
    RolloverDetector,
    RthFilter,
    expected_rth_timestamps,
    is_rollover_seam,
    is_rth,
    rth_window_utc,
    third_friday,
    trading_days,
)

__all__ = [
    "RolloverDetector",
    "RthFilter",
    "expected_rth_timestamps",
    "is_rollover_seam",
    "is_rth",
    "rth_window_utc",
    "third_friday",
    "trading_days",
]
