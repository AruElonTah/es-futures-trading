"""Strategy domain models — signature-only stubs for Plan 01-02.

Phase 2 fills in the concrete fields (side, entry, stop, target, size_hint,
strategy_id, timestamp on Signal; warmup state, ATR readings, etc. on
StrategyContext). Plan 01-02 only ships the empty importable classes so the
Strategy Protocol can name-reference them in its signature.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class Signal(BaseModel):
    """Strategy output. Phase 2 fills in: side, entry, stop, target, size_hint,
    strategy_id, ts_utc."""

    model_config = ConfigDict(extra="forbid")


class StrategyContext(BaseModel):
    """Per-bar context passed to `Strategy.on_bar`. Phase 2 fills in: ATR
    readings, warmup state, prior bars window, current daily ORB high/low."""

    model_config = ConfigDict(extra="forbid")
