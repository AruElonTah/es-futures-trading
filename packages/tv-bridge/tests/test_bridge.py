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

Xfail stubs (Task 3 will convert):
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

from trading_core.events import TOPIC_DEGRADED_STATE, TOPIC_SIGNALS, EventBus
from trading_core.strategy.models import Signal
from trading_core.storage.duckdb_store import DuckDBStore
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
    in_memory_store: DuckDBStore,
    mock_settings,
) -> None:
    """TVBridge reconnects after session drop with capped exponential backoff.

    Simulates:
    1. First connect: health-gate returns api_available=False, raises RuntimeError.
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

    original_sleep = asyncio.sleep

    async def _tracked_sleep(seconds: float) -> None:
        """Record the sleep call then do a minimal real sleep to not block."""
        sleep_calls.append(seconds)
        sleep_event.set()
        # Don't actually sleep long — just yield control briefly
        await original_sleep(0.001)

    # Build a session mock that fails health check (api_available=False)
    def _make_failing_session():
        session = AsyncMock()
        session.initialize = AsyncMock(return_value=None)
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
# ---------------------------------------------------------------------------

async def test_draw_on_signal(
    in_memory_store: DuckDBStore,
    mock_settings,
    mock_mcp_session: AsyncMock,
) -> None:
    """Four draw_shape calls fired after Signal on TOPIC_SIGNALS; 4 tv_overlays rows written.

    Steps:
    1. Start bridge with mocked session injected (_session = mock_mcp_session).
    2. Patch mock_mcp_session.call_tool to return {"entity_id": "tv_42"}.
    3. Publish a Signal on TOPIC_SIGNALS via real EventBus.
    4. Await one event-loop cycle for create_task to fire.
    5. Assert: 4 draw_shape calls, 4 tv_overlays rows with distinct shape_kinds.
    """
    # Configure mock_mcp_session to return a valid entity_id
    content_item = MagicMock()
    content_item.text = '{"entity_id": "tv_42", "success": true}'
    result = MagicMock()
    result.content = [content_item]
    mock_mcp_session.call_tool.return_value = result

    real_bus = EventBus()
    bridge = TVBridge(store=in_memory_store, bus=real_bus, settings=mock_settings)

    # Inject mock session directly (bypass supervisor loop)
    bridge._session = mock_mcp_session

    # Start subscriber tasks (not supervisor)
    bridge._sig_task = asyncio.create_task(
        bridge._subscribe_signals(), name="tv_bridge.sig_sub"
    )
    bridge._fill_task = asyncio.create_task(
        bridge._subscribe_fills(), name="tv_bridge.fill_sub"
    )

    # Give subscriber coroutines time to enter the bus.subscribe() context manager.
    # EventBus.subscribe is an asynccontextmanager that acquires a lock (2+ yield points)
    # before yielding the Subscription. Need at least 3 event-loop ticks.
    for _ in range(5):
        await asyncio.sleep(0)

    signal = Signal(
        strategy_id="orb_v1",
        strategy_version="1.0",
        ts_utc=datetime(2024, 6, 12, 14, 30, 0, tzinfo=timezone.utc),
        side="long",
        entry=Decimal("5500.00"),
        stop=Decimal("5490.00"),
        target=Decimal("5520.00"),
        size_hint=Decimal("1"),
        signal_id="sig-draw-test",
    )

    # Publish signal to bus
    await real_bus.publish(TOPIC_SIGNALS, signal)

    # Give event loop cycles to: process subscriber, create draw task, run draw task
    # Draw tasks run as fire-and-forget; we wait for them to complete
    for _ in range(50):
        await asyncio.sleep(0)

    # Allow draw tasks to complete (mock calls are async, need event loop cycles)
    await asyncio.sleep(0.2)

    # Stop subscriber tasks (after draw tasks complete)
    for t in (bridge._sig_task, bridge._fill_task):
        if t is not None:
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass
    bridge._sig_task = None
    bridge._fill_task = None

    # Verify 4 draw_shape calls were made (orb_box + entry_arrow + stop_line + target_line)
    # mock_mcp_session.call_tool records calls as call(tool_name, args_dict)
    # e.g. call('draw_shape', {'shape': 'horizontal_line', ...})
    shape_calls = [
        c for c in mock_mcp_session.call_tool.call_args_list
        if c.args and c.args[0] == "draw_shape"
    ]

    assert len(shape_calls) == 4, (
        f"Expected 4 draw_shape calls, got {len(shape_calls)}. "
        f"All calls: {[str(c) for c in mock_mcp_session.call_tool.call_args_list]}"
    )

    # Verify 4 tv_overlays rows with distinct shape_kinds
    rows = in_memory_store._conn.execute(
        "SELECT shape_kind FROM tv_overlays WHERE signal_id = 'sig-draw-test'"
    ).fetchall()
    shape_kinds = {r[0] for r in rows}
    assert len(rows) == 4, f"Expected 4 tv_overlays rows, got {len(rows)}"
    expected_kinds = {"entry_arrow", "stop_line", "target_line", "orb_box"}
    assert shape_kinds == expected_kinds, (
        f"Expected shape_kinds {expected_kinds}, got {shape_kinds}"
    )

    # Verify semaphore is released (not stuck)
    assert bridge._draw_semaphore._value == 3, (
        "draw_semaphore should be fully released after draw completes"
    )


# ---------------------------------------------------------------------------
# Task 2: test_draw_timeout_nonblocking — bus dispatch not blocked by MCP timeout
# ---------------------------------------------------------------------------

async def test_draw_timeout_nonblocking(
    in_memory_store: DuckDBStore,
    mock_settings,
    mock_mcp_session: AsyncMock,
) -> None:
    """Bus publish returns immediately even when draw_shape times out.

    Behavior:
    - mock_mcp_session.call_tool() sleeps 20s (forces asyncio.timeout(5s) to fire).
    - bus.publish() must complete in < 100ms (fire-and-forget via create_task).
    - Within 6s, an audit_log row with topic='tv_draw_timeout' must appear.
    """
    # Make call_tool hang for 20s to force timeout
    async def _slow_call_tool(*args, **kwargs):
        await asyncio.sleep(20.0)
        return MagicMock()  # never reached in this test

    mock_mcp_session.call_tool.side_effect = _slow_call_tool

    real_bus = EventBus()
    bridge = TVBridge(store=in_memory_store, bus=real_bus, settings=mock_settings)
    bridge._session = mock_mcp_session

    bridge._sig_task = asyncio.create_task(
        bridge._subscribe_signals(), name="tv_bridge.sig_sub"
    )

    # Let subscriber register in the bus (needs 3+ event-loop ticks)
    for _ in range(5):
        await asyncio.sleep(0)

    try:
        signal = Signal(
            strategy_id="orb_v1",
            strategy_version="1.0",
            ts_utc=datetime(2024, 6, 12, 14, 30, 0, tzinfo=timezone.utc),
            side="long",
            entry=Decimal("5500.00"),
            stop=Decimal("5490.00"),
            target=Decimal("5520.00"),
            size_hint=Decimal("1"),
            signal_id="sig-timeout-test",
        )

        # Publish and time the bus call
        start = asyncio.get_event_loop().time()
        await real_bus.publish(TOPIC_SIGNALS, signal)
        elapsed = asyncio.get_event_loop().time() - start

        # Bus dispatch must return in << 100ms (fire-and-forget, not blocking)
        assert elapsed < 0.1, (
            f"bus.publish took {elapsed:.3f}s — should be < 100ms (draw task is create_task, not awaited)"
        )

        # Give the event loop time to: subscriber receives signal, create_task fires,
        # safe_draw_signal enters semaphore + timeout block, call_tool hangs,
        # asyncio.timeout(5s) fires, audit_log written.
        await asyncio.sleep(6.0)  # wait for 5s timeout + margin

    finally:
        bridge._sig_task.cancel()
        try:
            await bridge._sig_task
        except asyncio.CancelledError:
            pass
        bridge._sig_task = None

    # Audit log row with topic='tv_draw_timeout' must exist
    audit_row = in_memory_store._conn.execute(
        "SELECT topic, reason_code FROM audit_log WHERE topic = 'tv_draw_timeout'",
    ).fetchone()
    assert audit_row is not None, (
        "Expected audit_log row with topic='tv_draw_timeout' after 5s MCP timeout"
    )
    assert audit_row[1] == "draw_timeout"


# ---------------------------------------------------------------------------
# Task 3: test_focus_call_sequence — TV-05 sequence contract (BLOCKER 1 fix)
# Proves chart_set_symbol → chart_set_timeframe → chart_scroll_to_date ordering
# ---------------------------------------------------------------------------

async def test_focus_call_sequence(
    in_memory_store: DuckDBStore,
    mock_settings,
    mock_mcp_session: AsyncMock,
) -> None:
    """focus() calls chart_set_symbol → chart_set_timeframe → chart_set_visible_range in order.

    BLOCKER 1 fix: verifies TV-05 ordered sequence contract without a live TV session.
    chart_scroll_to_date was replaced by chart_set_visible_range (UAT Gap 1 fix) because
    TV auto-scroll immediately overrides chart_scroll_to_date.

    Assertions:
    - call_tool was awaited exactly 3 times
    - Call 1: ("chart_set_symbol", {...})
    - Call 2: ("chart_set_timeframe", {...})
    - Call 3: ("chart_set_visible_range", {"from": <ts>, "to": <ts>}) with from < to
    """
    bridge = TVBridge(store=in_memory_store, bus=EventBus(), settings=mock_settings)
    # Inject mock session
    bridge._session = mock_mcp_session

    await bridge.focus("ES", "2024-06-12", "1")

    # Verify exactly 3 calls
    assert mock_mcp_session.call_tool.await_count == 3, (
        f"Expected 3 call_tool awaits, got {mock_mcp_session.call_tool.await_count}"
    )

    # Verify call order via call_args_list
    calls = mock_mcp_session.call_tool.call_args_list
    assert calls[0].args[0] == "chart_set_symbol", (
        f"Call 1 should be chart_set_symbol, got {calls[0].args[0]!r}"
    )
    assert calls[1].args[0] == "chart_set_timeframe", (
        f"Call 2 should be chart_set_timeframe, got {calls[1].args[0]!r}"
    )
    assert calls[2].args[0] == "chart_set_visible_range", (
        f"Call 3 should be chart_set_visible_range, got {calls[2].args[0]!r}"
    )
    args_dict = calls[2].args[1]
    assert "from" in args_dict and "to" in args_dict, (
        f"chart_set_visible_range payload must have 'from' and 'to' keys, got {args_dict!r}"
    )
    assert args_dict["from"] < args_dict["to"], (
        f"'from' must be before 'to', got from={args_dict['from']!r} to={args_dict['to']!r}"
    )
