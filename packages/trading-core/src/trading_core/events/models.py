"""Event hierarchy + topic constants.

Phase 1 ships:
- `Event` base (topic + emitted_at, frozen)
- `BarReceived` — produced by every DataSource adapter when a bar closes
- `DegradedStateEvent` — produced when a provider's transport drops (e.g.,
  TradingView CDP disconnect). Phase 3 wires it to a UI banner.

Topic constants are `Final[str]`. They are the bus's stable contract — adding
a topic is a deliberate ADR, not an offhand commit.
"""

from __future__ import annotations

from typing import Final

from pydantic import AwareDatetime, BaseModel, ConfigDict

from trading_core.data.models import Bar

# ---------------------------------------------------------------------------
# Topic constants — Final[str] to lock the public contract.
# ---------------------------------------------------------------------------
TOPIC_BARS: Final[str] = "bars"
TOPIC_SIGNALS: Final[str] = "signals"
TOPIC_RISK_DECISIONS: Final[str] = "risk_decisions"
TOPIC_FILLS: Final[str] = "fills"
TOPIC_POSITIONS: Final[str] = "positions"
TOPIC_EQUITY: Final[str] = "equity"
TOPIC_DEGRADED_STATE: Final[str] = "degraded_state"
# Phase 5: Audit log topic (SP-03 / D-09) and engine state change topic (D-10/D-11).
TOPIC_AUDIT: Final[str] = "audit"
TOPIC_ENGINE_STATE: Final[str] = "engine_state"
# Phase 7: Strategy hot-reload topic (D-14).
TOPIC_STRATEGY_RELOAD: Final[str] = "strategy_reload"


class Event(BaseModel):
    """Base event. Concrete events extend with payload fields."""

    model_config = ConfigDict(frozen=True)

    topic: str
    emitted_at: AwareDatetime


class BarReceived(Event):
    """A new bar closed and was received by a DataSource adapter."""

    bar: Bar


class DegradedStateEvent(Event):
    """A provider transport entered a degraded state (e.g., CDP disconnect)."""

    source: str  # provider name — "tradingview_mcp" / "twelve_data"
    reason: str  # free-form short description for the UI banner
