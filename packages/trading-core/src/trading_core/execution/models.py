"""Execution domain models — D-10 minimal fields (Phase 3 Plan 01).

Phase 3 fills in the minimal fields required for the backtester:
- Fill: signal_id, fill_price, fill_qty, side, slippage_ticks, ts_utc, exit_reason

Phase 5 adds:
- fill_id: UUID7 primary key for audit_log entity_id (SP-03).
- remaining fields (commission_$, etc.) reserved for later phases.

D-11: exit_reason is a four-value Literal: target | stop | eod_flat | manual.
  'manual' is reserved for Phase 5's kill-switch/flatten.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from trading_core.storage.runs import new_run_id


class Fill(BaseModel):
    """Paper-executor fill record — D-10 minimal fields + Phase 5 fill_id.

    Frozen + extra='forbid' so downstream consumers can trust the shape
    and mutations are caught at construction time rather than silently
    corrupting the audit trail.

    fill_id is a UUID7 that uniquely identifies this fill in the audit_log
    (SP-03). It is auto-generated if not supplied.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    fill_id: str = Field(default_factory=new_run_id)
    signal_id: str
    fill_price: Decimal = Field(gt=Decimal("0"))
    fill_qty: int = Field(gt=0)
    side: Literal["long", "short"]
    slippage_ticks: int = Field(ge=0)
    ts_utc: AwareDatetime
    exit_reason: Literal["target", "stop", "eod_flat", "manual"]

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
