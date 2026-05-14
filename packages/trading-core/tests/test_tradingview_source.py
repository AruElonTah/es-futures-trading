"""Tests for ``trading_core.data.tradingview.TradingViewDataSource`` (MD-02).

Behavior covered:
- happy path: ``tv_health_check`` returns ``api_available=True`` ->
  ``data_get_ohlcv`` returns N bars -> DataFrame with the canonical column
  set, tz-aware UTC ts_utc, provider='tradingview_mcp'
- ``tv_health_check`` returns ``api_available=False`` -> publishes
  ``DegradedStateEvent`` and raises ``DataSourceUnavailable``
- ``session.initialize`` raises ``asyncio.TimeoutError`` -> publishes
  ``DegradedStateEvent`` + raises ``DataSourceUnavailable``
- ``fetch_bars('SPY', ...)`` raises ``ValueError`` (TV adapter is ES/MES only)
- Symbol ``'ES'`` is mapped to ``'CME_MINI:ES1!'`` in the captured
  ``data_get_ohlcv`` tool-call args

Mocking strategy: patch ``trading_core.data.tradingview.stdio_client`` and
``trading_core.data.tradingview.ClientSession`` so NO real subprocess spawns.
"""

from __future__ import annotations

import asyncio
import json
import types
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

from trading_core.config import Settings
from trading_core.data.protocols import DataSourceUnavailable
from trading_core.data.tradingview import TradingViewDataSource
from trading_core.events import (
    TOPIC_DEGRADED_STATE,
    DegradedStateEvent,
    EventBus,
)


# ---------------------------------------------------------------------------
# Mock infrastructure — fake stdio_client + ClientSession
# ---------------------------------------------------------------------------


def _make_tool_result(payload: dict) -> MagicMock:
    """Build a fake mcp tool-call result with one TextContent item."""
    content = MagicMock()
    content.text = json.dumps(payload)
    result = MagicMock()
    result.content = [content]
    return result


def _patch_mcp(
    monkeypatch: pytest.MonkeyPatch,
    *,
    initialize_raises: type[BaseException] | None = None,
    health_payload: dict | None = None,
    ohlcv_payload: dict | None = None,
    tool_call_recorder: list | None = None,
) -> None:
    """Patch ``stdio_client`` and ``ClientSession`` on the adapter module.

    Each invocation of the patched ``stdio_client`` returns an async
    context-manager yielding ``(read, write)`` placeholders. The patched
    ``ClientSession`` constructor returns an object whose ``__aenter__``
    yields a session with ``initialize`` and ``call_tool`` AsyncMocks.
    """

    @asynccontextmanager
    async def fake_stdio_client(*args, **kwargs):
        yield (object(), object())

    monkeypatch.setattr(
        "trading_core.data.tradingview.stdio_client", fake_stdio_client
    )

    health = health_payload or {"success": True, "api_available": True}
    ohlcv = ohlcv_payload or {
        "success": True,
        "bar_count": 0,
        "total_available": 0,
        "source": "direct_bars",
        "bars": [],
    }

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def initialize(self):
            if initialize_raises is not None:
                raise initialize_raises()

        async def call_tool(self, name: str, args: dict):
            if tool_call_recorder is not None:
                tool_call_recorder.append((name, args))
            if name == "tv_health_check":
                return _make_tool_result(health)
            if name == "data_get_ohlcv":
                return _make_tool_result(ohlcv)
            return _make_tool_result({"success": False, "error": f"unknown tool {name}"})

    def fake_client_session_ctor(read, write):
        return FakeSession()

    monkeypatch.setattr(
        "trading_core.data.tradingview.ClientSession",
        fake_client_session_ctor,
    )


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def settings() -> Settings:
    return Settings()


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


@pytest.fixture
def fetch_window() -> tuple[datetime, datetime]:
    start = datetime(2026, 5, 13, 13, 30, tzinfo=timezone.utc)
    end = datetime(2026, 5, 13, 20, 0, tzinfo=timezone.utc)
    return start, end


# ---------------------------------------------------------------------------
# happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_bars_happy_path(
    monkeypatch: pytest.MonkeyPatch,
    settings: Settings,
    bus: EventBus,
    fetch_window: tuple[datetime, datetime],
) -> None:
    start, end = fetch_window
    bars_payload = {
        "success": True,
        "bar_count": 3,
        "total_available": 3,
        "source": "direct_bars",
        "bars": [
            # epoch seconds — matches Phase 0 transcript bar.time format
            {"time": 1778761980, "open": 7493.75, "high": 7495.5, "low": 7493.5, "close": 7495.25, "volume": 494},
            {"time": 1778762040, "open": 7495.5,  "high": 7496.0, "low": 7495.0, "close": 7496.0,  "volume": 270},
            {"time": 1778762100, "open": 7495.75, "high": 7496.25,"low": 7495.0, "close": 7495.25, "volume": 192},
        ],
    }
    _patch_mcp(monkeypatch, ohlcv_payload=bars_payload)

    source = TradingViewDataSource(settings, bus=bus)
    df = await source.fetch_bars("ES", "1m", start, end)
    assert list(df.columns) == [
        "symbol", "timeframe", "ts_utc", "open", "high", "low",
        "close", "volume", "provider",
    ]
    assert len(df) == 3
    assert df["ts_utc"].iloc[0].tzinfo is not None
    assert df["ts_utc"].iloc[0].utcoffset().total_seconds() == 0
    assert (df["provider"] == "tradingview_mcp").all()
    assert (df["symbol"] == "ES").all()


# ---------------------------------------------------------------------------
# api_available=False -> DegradedStateEvent + DataSourceUnavailable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_check_unavailable_publishes_degraded(
    monkeypatch: pytest.MonkeyPatch,
    settings: Settings,
    bus: EventBus,
    fetch_window: tuple[datetime, datetime],
) -> None:
    start, end = fetch_window
    _patch_mcp(
        monkeypatch,
        health_payload={"success": True, "api_available": False, "error": "CDP unattached"},
    )

    received: list = []

    async def subscriber():
        async with bus.subscribe(TOPIC_DEGRADED_STATE) as sub:
            async for event in sub:
                received.append(event)
                return

    sub_task = asyncio.create_task(subscriber())
    # Give the subscriber a tick to register before publishing.
    await asyncio.sleep(0)

    source = TradingViewDataSource(settings, bus=bus)
    with pytest.raises(DataSourceUnavailable):
        await source.fetch_bars("ES", "1m", start, end)

    # Wait for the subscriber to pick up the event.
    await asyncio.wait_for(sub_task, timeout=2.0)
    assert len(received) == 1
    ev = received[0]
    assert isinstance(ev, DegradedStateEvent)
    assert ev.source == "tradingview_mcp"


# ---------------------------------------------------------------------------
# initialize TimeoutError -> DegradedStateEvent + DataSourceUnavailable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_initialize_timeout_publishes_degraded(
    monkeypatch: pytest.MonkeyPatch,
    settings: Settings,
    bus: EventBus,
    fetch_window: tuple[datetime, datetime],
) -> None:
    start, end = fetch_window
    _patch_mcp(monkeypatch, initialize_raises=asyncio.TimeoutError)

    received: list = []

    async def subscriber():
        async with bus.subscribe(TOPIC_DEGRADED_STATE) as sub:
            async for event in sub:
                received.append(event)
                return

    sub_task = asyncio.create_task(subscriber())
    await asyncio.sleep(0)

    source = TradingViewDataSource(settings, bus=bus)
    with pytest.raises(DataSourceUnavailable):
        await source.fetch_bars("ES", "1m", start, end)

    await asyncio.wait_for(sub_task, timeout=2.0)
    assert len(received) == 1
    assert received[0].source == "tradingview_mcp"


# ---------------------------------------------------------------------------
# fetch_bars('SPY', ...) -> ValueError
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_spy_raises_value_error(
    monkeypatch: pytest.MonkeyPatch,
    settings: Settings,
    bus: EventBus,
    fetch_window: tuple[datetime, datetime],
) -> None:
    start, end = fetch_window
    _patch_mcp(monkeypatch)
    source = TradingViewDataSource(settings, bus=bus)
    with pytest.raises(ValueError, match="SPY"):
        await source.fetch_bars("SPY", "1m", start, end)


# ---------------------------------------------------------------------------
# Symbol mapping ES -> CME_MINI:ES1! visible in tool-call args
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_es_maps_to_cme_mini_es1_continuous(
    monkeypatch: pytest.MonkeyPatch,
    settings: Settings,
    bus: EventBus,
    fetch_window: tuple[datetime, datetime],
) -> None:
    start, end = fetch_window
    recorder: list = []
    _patch_mcp(monkeypatch, tool_call_recorder=recorder)

    source = TradingViewDataSource(settings, bus=bus)
    await source.fetch_bars("ES", "1m", start, end)

    # Find the data_get_ohlcv call; assert its args carry the TV-symbol form.
    ohlcv_calls = [args for (name, args) in recorder if name == "data_get_ohlcv"]
    assert ohlcv_calls, f"data_get_ohlcv never called; recorded: {recorder}"
    assert ohlcv_calls[0].get("symbol") == "CME_MINI:ES1!"
