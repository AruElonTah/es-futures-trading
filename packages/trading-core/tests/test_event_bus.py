"""EventBus tests (FND-07, Pattern 5).

The bus is in-process asyncio pub/sub with FIFO ordering per topic, no
backpressure (unbounded queues), no replay buffer. Phase 5/7 may add
bounded queues; Phase 1 v1 only ships the shape.

asyncio_mode = "auto" is set in the root pyproject.toml, so test coroutines
are auto-awaited without an explicit @pytest.mark.asyncio decorator.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from trading_core.data.models import Bar
from trading_core.events import (
    TOPIC_BARS,
    TOPIC_DEGRADED_STATE,
    TOPIC_FILLS,
    BarReceived,
    DegradedStateEvent,
)

UTC = ZoneInfo("UTC")


def _make_bar_event(*, minute: int = 30) -> BarReceived:
    """Helper: a valid BarReceived with synthetic SPY bar."""
    return BarReceived(
        topic=TOPIC_BARS,
        emitted_at=datetime(2024, 6, 12, 13, minute, tzinfo=UTC),
        bar=Bar(
            symbol="SPY",
            timeframe="1m",
            ts_utc=datetime(2024, 6, 12, 13, minute, tzinfo=UTC),
            open=Decimal("500.00"),
            high=Decimal("500.50"),
            low=Decimal("499.90"),
            close=Decimal("500.25"),
            volume=10000,
        ),
    )


class TestImports:
    def test_eventbus_importable_from_module(self) -> None:
        from trading_core.events.bus import EventBus, Subscription

        assert EventBus is not None
        assert Subscription is not None

    def test_eventbus_reexported_from_package(self) -> None:
        from trading_core.events import EventBus, Subscription

        assert EventBus is not None
        assert Subscription is not None


class TestSinglePublishSingleSubscribe:
    async def test_one_subscriber_receives_one_event(self) -> None:
        from trading_core.events.bus import EventBus

        bus = EventBus()
        event = _make_bar_event()
        received: list = []

        async def consumer() -> None:
            async with bus.subscribe(TOPIC_BARS) as sub:
                async for ev in sub:
                    received.append(ev)
                    break  # done after first event

        consumer_task = asyncio.create_task(consumer())
        # Give the subscriber time to register
        await asyncio.sleep(0.01)
        await bus.publish(TOPIC_BARS, event)
        await asyncio.wait_for(consumer_task, timeout=1.0)

        assert len(received) == 1
        assert received[0] is event


class TestFanout:
    async def test_two_subscribers_both_receive_same_event(self) -> None:
        from trading_core.events.bus import EventBus

        bus = EventBus()
        event = _make_bar_event()
        recv_a: list = []
        recv_b: list = []

        async def consumer(buf: list) -> None:
            async with bus.subscribe(TOPIC_BARS) as sub:
                async for ev in sub:
                    buf.append(ev)
                    break

        task_a = asyncio.create_task(consumer(recv_a))
        task_b = asyncio.create_task(consumer(recv_b))
        await asyncio.sleep(0.01)
        await bus.publish(TOPIC_BARS, event)
        await asyncio.gather(task_a, task_b)

        assert recv_a == [event]
        assert recv_b == [event]


class TestTopicIsolation:
    async def test_subscriber_on_other_topic_does_not_receive(self) -> None:
        from trading_core.events.bus import EventBus

        bus = EventBus()
        bar_event = _make_bar_event()
        degraded_recv: list = []
        bars_recv: list = []
        bars_done = asyncio.Event()

        async def degraded_consumer() -> None:
            async with bus.subscribe(TOPIC_DEGRADED_STATE) as sub:
                async for ev in sub:
                    degraded_recv.append(ev)
                    break

        async def bars_consumer() -> None:
            async with bus.subscribe(TOPIC_BARS) as sub:
                async for ev in sub:
                    bars_recv.append(ev)
                    bars_done.set()
                    break

        d_task = asyncio.create_task(degraded_consumer())
        b_task = asyncio.create_task(bars_consumer())
        await asyncio.sleep(0.01)
        await bus.publish(TOPIC_BARS, bar_event)

        # Wait for bars_consumer to receive; give the bus a moment after.
        await asyncio.wait_for(bars_done.wait(), timeout=1.0)
        await asyncio.sleep(0.01)

        assert bars_recv == [bar_event]
        assert degraded_recv == []  # other-topic subscriber received nothing

        # Cleanup: cancel the still-running degraded consumer
        d_task.cancel()
        try:
            await d_task
        except asyncio.CancelledError:
            pass
        await b_task


class TestFifoPerTopic:
    async def test_ten_events_published_in_order_received_in_order(self) -> None:
        from trading_core.events.bus import EventBus

        bus = EventBus()
        n = 10
        events = [_make_bar_event(minute=30 + i) for i in range(n)]
        received: list = []

        async def consumer() -> None:
            async with bus.subscribe(TOPIC_BARS) as sub:
                async for ev in sub:
                    received.append(ev)
                    if len(received) == n:
                        break

        c_task = asyncio.create_task(consumer())
        await asyncio.sleep(0.01)
        for ev in events:
            await bus.publish(TOPIC_BARS, ev)
        await asyncio.wait_for(c_task, timeout=2.0)

        assert received == events


class TestNoReplayBuffer:
    async def test_late_subscriber_misses_prior_events(self) -> None:
        from trading_core.events.bus import EventBus

        bus = EventBus()
        early = _make_bar_event(minute=30)
        late = _make_bar_event(minute=31)

        # Publish twice with NO subscribers
        await bus.publish(TOPIC_BARS, early)
        await bus.publish(TOPIC_BARS, early)

        received: list = []

        async def consumer() -> None:
            async with bus.subscribe(TOPIC_BARS) as sub:
                async for ev in sub:
                    received.append(ev)
                    break

        c_task = asyncio.create_task(consumer())
        await asyncio.sleep(0.01)
        # Now publish ONE more event; consumer should ONLY see `late`
        await bus.publish(TOPIC_BARS, late)
        await asyncio.wait_for(c_task, timeout=1.0)

        assert received == [late]


class TestSubscriptionLifecycle:
    async def test_exiting_subscribe_removes_queue(self) -> None:
        """After `async with bus.subscribe(...)` exits, the queue is dropped.

        We test this by: subscribe, exit, publish, re-subscribe — the new
        subscription must see the post-exit publish AND the count of active
        subscribers must be 1 (not 2 with a leaked queue).
        """
        from trading_core.events.bus import EventBus

        bus = EventBus()
        event_one = _make_bar_event(minute=30)
        event_two = _make_bar_event(minute=31)

        # Phase 1: subscribe + immediately exit
        async with bus.subscribe(TOPIC_BARS) as sub:
            pass  # exit without consuming

        # Confirm internal state: no queues left for TOPIC_BARS
        assert bus._subscribers.get(TOPIC_BARS, []) == []

        # Phase 2: publish event_one to nobody (no replay buffer)
        await bus.publish(TOPIC_BARS, event_one)

        # Phase 3: new subscriber should not see event_one, only event_two
        received: list = []

        async def consumer() -> None:
            async with bus.subscribe(TOPIC_BARS) as sub:
                async for ev in sub:
                    received.append(ev)
                    break

        c_task = asyncio.create_task(consumer())
        await asyncio.sleep(0.01)
        await bus.publish(TOPIC_BARS, event_two)
        await asyncio.wait_for(c_task, timeout=1.0)

        assert received == [event_two]


class TestPublishWithoutSubscribers:
    async def test_publish_with_no_subscribers_is_noop(self) -> None:
        """Plain `await bus.publish(...)` must succeed even when no one listens."""
        from trading_core.events.bus import EventBus

        bus = EventBus()
        # No subscribers — should not raise, should not block
        await asyncio.wait_for(bus.publish(TOPIC_FILLS, _make_bar_event()), timeout=0.5)


class TestConcurrentProducers:
    async def test_concurrent_publishers_preserve_per_topic_fifo(self) -> None:
        """Two coroutines publishing serially on the same topic — order preserved.

        Note: 'FIFO per topic' in v1 means the per-queue put order is the
        await order on `publish`. We test the stronger property that a
        sequential `await pub1(); await pub2()` produces (a, b) ordering at
        the consumer.
        """
        from trading_core.events.bus import EventBus

        bus = EventBus()
        a = _make_bar_event(minute=30)
        b = _make_bar_event(minute=31)
        received: list = []

        async def consumer() -> None:
            async with bus.subscribe(TOPIC_BARS) as sub:
                async for ev in sub:
                    received.append(ev)
                    if len(received) == 2:
                        break

        async def pub_first() -> None:
            await bus.publish(TOPIC_BARS, a)

        async def pub_second() -> None:
            await bus.publish(TOPIC_BARS, b)

        c_task = asyncio.create_task(consumer())
        await asyncio.sleep(0.01)
        # Sequential awaits — a must reach the queue before b
        await pub_first()
        await pub_second()
        await asyncio.wait_for(c_task, timeout=1.0)

        assert received == [a, b]


class TestEventPayloadTypes:
    async def test_degraded_state_event_routes_correctly(self) -> None:
        """Non-Bar event payloads (DegradedStateEvent) also route through the bus."""
        from trading_core.events.bus import EventBus

        bus = EventBus()
        ev = DegradedStateEvent(
            topic=TOPIC_DEGRADED_STATE,
            emitted_at=datetime(2024, 6, 12, 13, 30, tzinfo=UTC),
            source="tradingview_mcp",
            reason="CDP disconnect",
        )
        received: list = []

        async def consumer() -> None:
            async with bus.subscribe(TOPIC_DEGRADED_STATE) as sub:
                async for got in sub:
                    received.append(got)
                    break

        c_task = asyncio.create_task(consumer())
        await asyncio.sleep(0.01)
        await bus.publish(TOPIC_DEGRADED_STATE, ev)
        await asyncio.wait_for(c_task, timeout=1.0)

        assert received == [ev]
        assert isinstance(received[0], DegradedStateEvent)
