"""EventBus — in-process asyncio pub/sub (FND-07, Pattern 5).

Topic-keyed asyncio.Queue per subscriber, FIFO order per topic. No
backpressure — queues are unbounded for v1 (single operator, small message
rate; Phase 5/7 may add bounded queues with drop-oldest semantics if a
runaway producer is observed). No replay buffer — events published before a
subscription started are NOT delivered to that subscription.

Why hand-rolled and not `broadcaster` or `aiopubsub`?
    `broadcaster` is alpha + multi-backend (Redis/Kafka) — pure overhead for
    a single-process single-operator app. `aiopubsub` is unmaintained. The
    pattern here is ~40 lines of asyncio that we can unit-test against
    every behavior bullet — RESEARCH.md Pattern 5.

Threat model T-01-03-04 (Unbounded queue DoS) is accepted for v1 with this
docstring as the disclosure. Producer-side rate is bounded by the data
feeds themselves (1m bar cadence + signal generation per bar) so the
queue cannot grow without bound under normal operation.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from .models import Event

Topic = str


class Subscription:
    """View on a single subscriber's queue.

    Returned by `EventBus.subscribe()` (via its async context manager).
    Implements ``async for`` so consumers can write:

        async with bus.subscribe(TOPIC_BARS) as sub:
            async for event in sub:
                handle(event)
                if done:
                    break
    """

    def __init__(self, queue: asyncio.Queue) -> None:
        self._q: asyncio.Queue = queue

    async def __aiter__(self) -> AsyncIterator[Event]:
        while True:
            yield await self._q.get()


class EventBus:
    """In-process asyncio pub/sub with FIFO per-topic ordering.

    Concurrency model:
        - A single `asyncio.Lock` guards mutation of the subscriber map.
        - `publish` takes a snapshot of the queue list under the lock, then
          awaits `queue.put(event)` for each (the put itself does not block
          on the lock — preventing back-pressure leak between subscribers).
        - `subscribe()` is an async context manager: on enter a new
          unbounded queue is registered; on exit the queue is removed.
    """

    def __init__(self) -> None:
        self._subscribers: dict[Topic, list[asyncio.Queue]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def publish(self, topic: Topic, event: Event) -> None:
        """Deliver `event` to every active subscriber on `topic`.

        Idempotent on the "no subscribers" path — returns without raising.
        Per-subscriber `put` calls are awaited in registration order to
        preserve deterministic ordering for tests; in production the queues
        are unbounded so puts complete synchronously without yielding.
        """
        async with self._lock:
            queues = list(self._subscribers.get(topic, []))
        for q in queues:
            await q.put(event)

    @asynccontextmanager
    async def subscribe(self, topic: Topic) -> AsyncIterator[Subscription]:
        """Register a subscriber on `topic` for the lifetime of the `async with`.

        On enter: a new unbounded `asyncio.Queue` is allocated and added to
        the topic's subscriber list; a `Subscription` view over the queue is
        yielded. On exit: the queue is removed from the topic's subscriber
        list. Events published before this enter are NOT delivered (no
        replay buffer).
        """
        q: asyncio.Queue = asyncio.Queue()
        async with self._lock:
            self._subscribers[topic].append(q)
        try:
            yield Subscription(q)
        finally:
            async with self._lock:
                if q in self._subscribers.get(topic, []):
                    self._subscribers[topic].remove(q)
