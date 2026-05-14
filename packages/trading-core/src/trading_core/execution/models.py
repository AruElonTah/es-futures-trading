"""Execution domain models — signature-only stubs for Plan 01-02.

Phase 5 fills in the concrete `Fill` fields:
- signal_id, fill_price, fill_qty, side, slippage_ticks, commission_$
- ts_utc, exit_reason (entry|target|stop|eod_flat|manual)
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class Fill(BaseModel):
    """Paper-executor fill record. Phase 5 fills in: signal_id, fill_price,
    fill_qty, side, slippage_ticks, commission_$, ts_utc, exit_reason."""

    model_config = ConfigDict(extra="forbid")
