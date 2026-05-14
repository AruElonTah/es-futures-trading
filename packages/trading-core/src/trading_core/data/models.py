"""Bar Pydantic v2 model (MD-06).

Bar OPEN time convention (MD-06):
    A bar labeled 09:30 covers the half-open interval [09:30:00, 09:30:59] for
    a 1m bar (i.e., the bar's timestamp is its OPEN time). Twelve Data and
    TradingView both label bars this way; legacy CLOSE-time vendors must have
    `ts_utc` shifted by -timeframe at the adapter boundary.

Why AwareDatetime + must_be_utc validator:
    Phase 0's piecewise tz handling produced multiple silent off-by-one-hour
    bugs at DST transitions. Centralizing tz-aware-UTC enforcement at the
    model boundary makes those bugs unrepresentable — a naive datetime or a
    tz-aware non-UTC datetime cannot construct a Bar.

Why frozen:
    Bars are immutable historical facts. Mutating one mid-pipeline would
    corrupt the audit-log → ledger → equity-curve chain.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator


class Bar(BaseModel):
    """Single OHLCV bar.

    `ts_utc` is the bar OPEN time, tz-aware UTC. See module docstring for the
    full OPEN-time convention (09:30 covers [09:30:00, 09:30:59] for 1m).
    """

    model_config = ConfigDict(frozen=True)

    symbol: str
    timeframe: str  # "1m" | "5m" | "15m"
    ts_utc: AwareDatetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int = Field(ge=0)
    rollover_seam: bool = False

    @field_validator("ts_utc")
    @classmethod
    def must_be_utc(cls, v: datetime) -> datetime:
        """Reject offsets != 0. AwareDatetime already rejects naive."""
        offset = v.utcoffset()
        if offset is None or offset.total_seconds() != 0:
            raise ValueError(
                f"ts_utc must be tz-aware UTC; got offset {offset}"
            )
        return v
