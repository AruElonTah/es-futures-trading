"""WebSocket fan-out — D-04 (7-topic mirror), D-05 ({type,payload} envelope),
D-06 (in-process asyncio.Queue, no broadcaster dep).

ConnectionManager subscribes to all 7 EventBus topics in a background task and
fans out every received event as a JSON string onto every connected client's
per-client asyncio.Queue. The WS /stream route in app.py drains that queue
and forwards to the browser.

Why asyncio.Queue per client and not broadcaster?
    broadcaster is alpha + multi-backend (Redis/Kafka) — pure overhead for a
    single-process single-operator app. 40 lines of asyncio that are fully
    unit-testable are the right fit. D-06 decision.
"""

from __future__ import annotations

import asyncio
import json

from fastapi import WebSocket

from trading_core.events import EventBus
from trading_core.events.models import (
    TOPIC_BARS,
    TOPIC_DEGRADED_STATE,
    TOPIC_ENGINE_STATE,
    TOPIC_EQUITY,
    TOPIC_FILLS,
    TOPIC_POSITIONS,
    TOPIC_RISK_DECISIONS,
    TOPIC_SIGNALS,
)
from trading_core.logging import get_logger

log = get_logger(__name__)

# D-04: all 8 EventBus topics that /stream mirrors to every connected client
# Phase 5 adds TOPIC_ENGINE_STATE for kill/flatten/pause notifications to the blotter.
ALL_TOPICS: tuple[str, ...] = (
    TOPIC_BARS,
    TOPIC_SIGNALS,
    TOPIC_RISK_DECISIONS,
    TOPIC_FILLS,
    TOPIC_POSITIONS,
    TOPIC_EQUITY,
    TOPIC_DEGRADED_STATE,
    TOPIC_ENGINE_STATE,
)


class ConnectionManager:
    """Per-client asyncio.Queue fan-out — D-04, D-05, D-06.

    Lifecycle:
        1. ``await manager.connect(ws)`` — accept the WebSocket, allocate a
           per-client queue, and return it to the caller.
        2. ``await manager.start_background_fan_out()`` — long-running task
           that subscribes to all 7 EventBus topics and enqueues JSON strings
           onto every connected client's queue. Started once in the lifespan.
        3. ``manager.disconnect(q)`` — remove the client's queue (called in
           the route's ``finally`` block).
    """

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        # D-06: per-client asyncio.Queue fan-out, no broadcaster dep.
        self._clients: set[asyncio.Queue] = set()
        # SP-06 / D-19: monotonic sequence counter for WS gap detection.
        # Starts at 0; incremented to 1 before the first message is dispatched.
        # Never reset on reconnect — the client uses gaps to detect missed events.
        self._seq: int = 0

    async def connect(self, websocket: WebSocket) -> asyncio.Queue:
        """Accept the WS connection, register a per-client queue, return it."""
        await websocket.accept()
        q: asyncio.Queue = asyncio.Queue()
        self._clients.add(q)
        return q

    def disconnect(self, q: asyncio.Queue) -> None:
        """Remove the client's queue — no error if already absent (discard)."""
        self._clients.discard(q)

    async def start_background_fan_out(self) -> None:
        """Subscribe to all 7 topics and fan out events to every connected client.

        Runs until cancelled (lifespan shutdown). Each topic runs as a concurrent
        coroutine so a slow topic cannot starve the others.
        """

        async def _subscribe_topic(topic: str) -> None:
            try:
                async with self._bus.subscribe(topic) as sub:
                    async for event in sub:
                        # SP-06 / D-19: increment seq before building each message.
                        # The counter is per-ConnectionManager-instance (per server start).
                        # Monotonic across all topics — single counter, never resets.
                        self._seq += 1
                        seq = self._seq

                        # D-05 envelope: {"type": "<topic>", "seq": N, "payload": {...}}
                        # EventBus accepts both typed Event subclasses (topic + model_dump)
                        # and plain dicts (e.g. TOPIC_ENGINE_STATE publish from risk routes).
                        if isinstance(event, dict):
                            # Plain dict published directly — inject seq into a copy.
                            payload = dict(event)
                            payload["seq"] = seq
                            msg = json.dumps(payload)
                        else:
                            msg = json.dumps(
                                {
                                    "type": event.topic,
                                    "seq": seq,
                                    "payload": event.model_dump(mode="json"),
                                }
                            )
                        # D-06: per-client asyncio.Queue fan-out, no broadcaster dep.
                        for q in list(self._clients):
                            await q.put(msg)
            except asyncio.CancelledError:
                raise

        await asyncio.gather(*[_subscribe_topic(t) for t in ALL_TOPICS])
