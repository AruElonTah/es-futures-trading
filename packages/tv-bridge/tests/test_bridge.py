"""Tests for TVBridge skeleton (Phase 6 Wave 1) and supervisor loop (Plan 02).

Task IDs: 06-01-03, 06-02-01, 06-02-02, 06-02-03

Real tests (Wave 1):
    - test_bridge_importable
    - test_call_tool_returns_none_when_no_session
    - test_start_creates_supervisor_task

Real tests (Wave 2 / Plan 02):
    - test_reconnect                  (Task 1 — supervisor loop)
    - test_draw_on_signal             (Task 2 — bus subscriber + safe draw)
    - test_draw_timeout_nonblocking   (Task 2 — bus subscriber non-blocking)
    - test_focus_call_sequence        (Task 3 — TV-05 sequence contract)

Xfail stubs (Task 2/3 will convert):
    - test_draw_on_signal
    - test_draw_timeout_nonblocking
    - test_focus_call_sequence
"""

from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from trading_core.events import TOPIC_DEGRADED_STATE, EventBus
from trading_core.strategy.models import Signal
from tv_bridge import TVBridge


def test_bridge_importable(bridge: TVBridge) -> None:
    """TVBridge is importable and constructable; construction does NOT spawn a subprocess."""
    # Import succeeded (fixture constructed the bridge).
    assert isinstance(bridge, TVBridge)
    # No session spawned during construction.
    assert bridge._session is None
    # No supervisor task spawned during construction.
    assert bridge._supervisor_task is None


async def test_call_tool_returns_none_when_no_session(bridge: TVBridge) -> None:
    """call_tool returns None and does not raise when _session is None."""
    result = await bridge.call_tool("any_tool", {})
    assert result is None


async def test_start_creates_supervisor_task(bridge: TVBridge) -> None:
    """start() creates a supervisor asyncio.Task; stop() cancels it cleanly."""
    await bridge.start()
    assert bridge._supervisor_task is not None
    assert isinstance(bridge._supervisor_task, asyncio.Task)
    # stop() must cancel cleanly without raising
    await bridge.stop()
    # After stop, session is cleared
    assert bridge._session is None


# ---------------------------------------------------------------------------
# Task 1: test_reconnect — supervisor loop with capped backoff reconnect
# ---------------------------------------------------------------------------

async def test_reconnect(
    in_memory_store,
    mock_settings,
) -> None:
    """TVBridge reconnects after session drop with capped exponential backoff.

    Simulates:
    1. First connect: health-gate raises RuntimeError (simulates failed health check).
    2. After failure: DegradedStateEvent published, backoff tracked.
    3. Verifies: backoff value comes from _BACKOFF_SECONDS[0] = 1s on first attempt.
    """
    # Use a real EventBus to capture DegradedStateEvent
    real_bus = EventBus()
    degraded_events: list = []

    async def _capture_degraded() -> None:
        async with real_bus.subscribe(TOPIC_DEGRADED_STATE) as sub:
            async for event in sub:
                degraded_events.append(event)
                break  # capture one

    capture_task = asyncio.create_task(_capture_degraded())
    await asyncio.sleep(0)  # let subscribe register

    bridge2 = TVBridge(
        store=in_memory_store, bus=real_bus, settings=mock_settings
    )

    # Track sleep calls from _supervisor_loop
    sleep_calls: list[float] = []
    # Event to signal when the first sleep happens (first reconnect attempt)
    sleep_event = asyncio.Event()
    # Event to stop the supervisor after first backoff
    stop_event = asyncio.Event()

    original_sleep = asyncio.sleep

    async def _tracked_sleep(seconds: float) -> None:
        """Record the sleep call then do a minimal real sleep to not block."""
        sleep_calls.append(seconds)
        sleep_event.set()
        # Don't actually sleep long — just yield control briefly
        await original_sleep(0.001)

    # Build a session mock that fails health check
    def _make_failing_session():
        session = AsyncMock()
        session.initialize = AsyncMock(return_value=None)
        # Health check response: api_available = False => RuntimeError
        content_item = MagicMock()
        content_item.text = '{"api_available": false}'
        result = MagicMock()
        result.content = [content_item]
        session.call_tool = AsyncMock(return_value=result)
        return session

    _session_obj = _make_failing_session()

    @asynccontextmanager
    async def _mock_stdio_client(params, errlog=None):
        yield (AsyncMock(), AsyncMock())  # r, w

    @asynccontextmanager
    async def _mock_client_session(r, w):
        yield _session_obj

    with (
        patch("tv_bridge.bridge.stdio_client", _mock_stdio_client),
        patch("tv_bridge.bridge.ClientSession", _mock_client_session),
        patch("tv_bridge.bridge.asyncio.sleep", _tracked_sleep),
    ):
        await bridge2.start()
        # Wait until the first backoff sleep fires (indicates one reconnect attempt failed)
        try:
            await asyncio.wait_for(sleep_event.wait(), timeout=2.0)
        except asyncio.TimeoutError:
            pass
        await bridge2.stop()

    capture_task.cancel()
    try:
        await capture_task
    except asyncio.CancelledError:
        pass

    # DegradedStateEvent must have been published on the failed health gate
    assert len(degraded_events) >= 1, (
        f"Expected at least one DegradedStateEvent. Got: {degraded_events!r}"
    )
    assert degraded_events[0].source == "tv_bridge"

    # Backoff sleep must have been called with a value from _BACKOFF_SECONDS
    assert len(sleep_calls) >= 1, (
        f"Expected at least one backoff sleep call. Got: {sleep_calls!r}"
    )
    assert sleep_calls[0] == TVBridge._BACKOFF_SECONDS[0], (
        f"Expected first backoff = {TVBridge._BACKOFF_SECONDS[0]}, got {sleep_calls[0]}"
    )
    # The first backoff (attempt=0) must be _BACKOFF_SECONDS[0] = 1
    assert sleep_calls[0] in TVBridge._BACKOFF_SECONDS


# ---------------------------------------------------------------------------
# Task 2: test_draw_on_signal — bus subscribers + safe draw
# (Converted in Task 2 — left as xfail until then)
# ---------------------------------------------------------------------------

@pytest.mark.xfail(reason="implemented in Task 2 of Plan 02", strict=True)
async def test_draw_on_signal(bridge: TVBridge) -> None:
    """draw_shape calls fired for entry_arrow + stop_line + target_line + orb_box after signal event."""
    pytest.fail("Task 2 of Plan 02 implements")


@pytest.mark.xfail(reason="implemented in Task 2 of Plan 02", strict=True)
async def test_draw_timeout_nonblocking(bridge: TVBridge) -> None:
    """Bus dispatch not blocked when draw_shape times out; asyncio.create_task returns immediately."""
    pytest.fail("Task 2 of Plan 02 implements")


# ---------------------------------------------------------------------------
# Task 3 (stub): test_focus_call_sequence — TV-05 sequence contract
# BLOCKER 1 fix: proves chart_set_symbol → chart_set_timeframe → chart_scroll_to_date order
# Converted in Task 3
# ---------------------------------------------------------------------------

@pytest.mark.xfail(reason="implemented in Task 3 of Plan 02 (focus method)", strict=True)
async def test_focus_call_sequence(bridge: TVBridge) -> None:
    """focus() calls chart_set_symbol → chart_set_timeframe → chart_scroll_to_date in order."""
    pytest.fail("Task 3 of Plan 02 implements")
