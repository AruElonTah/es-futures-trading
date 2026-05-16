"""Strategy domain models — Signal + StrategyContext (Plan 02-01).

Signal: immutable record of a trade signal emitted by a strategy. All price
fields use Decimal to prevent float drift in downstream risk math.

StrategyContext: per-bar context injected by the strategy driver. Indicator
values (atr, session_vwap, ema, adr) are look-ahead-safe snapshots from
BEFORE the current bar — computed with snapshot_at(t) on bars[0:t-1].

Both models are frozen (extra='forbid') so mutations or typos are caught at
construction time rather than silently corrupting the audit trail.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator


class Signal(BaseModel):
    """Immutable trade signal emitted by a strategy.

    Frozen + extra='forbid' so downstream consumers can trust the shape.
    signal_id is auto-generated (UUID4 str) if not supplied.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    strategy_id: str
    strategy_version: str
    ts_utc: AwareDatetime
    side: Literal["long", "short"]
    entry: Decimal = Field(gt=Decimal("0"))
    stop: Decimal = Field(gt=Decimal("0"))
    target: Decimal = Field(gt=Decimal("0"))
    size_hint: Decimal = Field(gt=Decimal("0"))
    signal_id: str = Field(default_factory=lambda: str(uuid.uuid4()))

    @field_validator("ts_utc")
    @classmethod
    def must_be_utc(cls, v):  # type: ignore[override]
        """Reject offsets != 0. AwareDatetime already rejects naive."""
        offset = v.utcoffset()
        if offset is None or offset.total_seconds() != 0:
            raise ValueError(
                f"ts_utc must be tz-aware UTC; got offset {offset}"
            )
        return v


class StrategyContext(BaseModel):
    """Per-bar context injected by the strategy driver into Strategy.on_bar.

    Indicator values (atr, session_vwap, ema, adr) are look-ahead-safe:
    they reflect only bars BEFORE the current bar (snapshot_at(t) pattern).
    During warmup they are None.

    Frozen + extra='forbid' — the driver constructs a fresh context each bar;
    strategies must not mutate it.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    rollover_seam: bool
    warmup_complete: bool
    bar_index: int
    ts_utc: AwareDatetime
    atr: Decimal | None = None
    session_vwap: Decimal | None = None
    ema: Decimal | None = None
    adr: Decimal | None = None
