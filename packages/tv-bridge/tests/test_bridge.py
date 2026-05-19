"""Tests for TVBridge skeleton (Phase 6 Wave 1).

Task ID: 06-01-03

Real tests (Wave 1):
    - test_bridge_importable
    - test_call_tool_returns_none_when_no_session
    - test_start_creates_supervisor_task

Xfail stubs (Wave 2 / Plan 02):
    - test_reconnect
    - test_draw_on_signal
    - test_draw_timeout_nonblocking
"""

from __future__ import annotations

import asyncio

import pytest

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


@pytest.mark.xfail(reason="implemented in Plan 02", strict=True)
async def test_reconnect(bridge: TVBridge) -> None:
    """TVBridge reconnects after session drop (simulated by cancelling mock session)."""
    pytest.fail("Plan 02 implements")


@pytest.mark.xfail(reason="implemented in Plan 02", strict=True)
async def test_draw_on_signal(bridge: TVBridge) -> None:
    """draw_shape calls fired for entry_arrow + stop_line + target_line + orb_box after signal event."""
    pytest.fail("Plan 02 implements")


@pytest.mark.xfail(reason="implemented in Plan 02", strict=True)
async def test_draw_timeout_nonblocking(bridge: TVBridge) -> None:
    """Bus dispatch not blocked when draw_shape times out; asyncio.create_task returns immediately."""
    pytest.fail("Plan 02 implements")
