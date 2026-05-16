"""Synthetic test fixtures for Phase 1.

Plan 03 lands the DST-transition + CME half-day + rollover-seam fixtures.
Future plans extend this package with more fixture factories.

Convention: every factory returns a tz-aware-UTC-indexed pandas DataFrame
with the canonical Bar shape (symbol, timeframe, ts_utc, open, high, low,
close, volume). All timestamps are bar-OPEN times per MD-06.
"""

from __future__ import annotations

from .dst_bars import (
    make_cme_half_day_2024_11_29_bars,
    make_dst_fall_back_2026_11_02_bars,
    make_dst_spring_forward_2026_03_09_bars,
    make_synthetic_spy_day_bars,
)
from .orb_day import orb_day_bars, rollover_seam_day_bars

__all__ = [
    "make_cme_half_day_2024_11_29_bars",
    "make_dst_fall_back_2026_11_02_bars",
    "make_dst_spring_forward_2026_03_09_bars",
    "make_synthetic_spy_day_bars",
    "orb_day_bars",
    "rollover_seam_day_bars",
]
