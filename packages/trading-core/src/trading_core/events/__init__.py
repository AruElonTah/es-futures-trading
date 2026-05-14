"""Events domain — Event base + concrete event types + topic constants + EventBus.

Plan 01-02 shipped `events/models.py` (Event hierarchy + topic constants).
Plan 01-03 ships `events/bus.py` (the asyncio in-process EventBus
implementing FIFO-per-topic pub/sub) — both re-exported here.
"""

from __future__ import annotations

from .bus import EventBus, Subscription
from .models import (
    TOPIC_BARS,
    TOPIC_DEGRADED_STATE,
    TOPIC_EQUITY,
    TOPIC_FILLS,
    TOPIC_POSITIONS,
    TOPIC_RISK_DECISIONS,
    TOPIC_SIGNALS,
    BarReceived,
    DegradedStateEvent,
    Event,
)

__all__ = [
    "BarReceived",
    "DegradedStateEvent",
    "Event",
    "EventBus",
    "Subscription",
    "TOPIC_BARS",
    "TOPIC_DEGRADED_STATE",
    "TOPIC_EQUITY",
    "TOPIC_FILLS",
    "TOPIC_POSITIONS",
    "TOPIC_RISK_DECISIONS",
    "TOPIC_SIGNALS",
]
