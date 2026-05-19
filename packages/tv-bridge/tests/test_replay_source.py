"""Tests for TVReplayDataSource (Plan 03, Task 1).

Converted from xfail-strict stubs to real tests.
Task ID: 06-03-01, 06-03-02
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

from trading_core.config import Settings
from trading_core.data.protocols import DataSourceUnavailable
from tv_bridge import TVReplayDataSource


def _make_mock_result(data: dict) -> MagicMock:
    """Build a mock MCP tool result with .content[0].text = json.dumps(data)."""
    import json

    item = MagicMock()
    item.text = json.dumps(data)
    result = MagicMock()
    result.content = [item]
    return result


def _make_bar_result(ts_epoch: int, o: float, h: float, lo: float, c: float, v: int) -> MagicMock:
    return _make_mock_result({
        "bar": {
            "time": ts_epoch,
            "open": o,
            "high": h,
            "low": lo,
            "close": c,
            "volume": v,
        }
    })


@pytest.fixture
def settings() -> Settings:
    return Settings()


@pytest.fixture
def source(settings: Settings) -> TVReplayDataSource:
    return TVReplayDataSource(settings=settings)


@pytest.mark.asyncio
async def test_fetch_bars(source: TVReplayDataSource) -> None:
    """TVReplayDataSource.fetch_bars returns DataFrame with correct Bar columns."""
    start = datetime(2024, 6, 12, 13, 30, tzinfo=timezone.utc)
    end = datetime(2024, 6, 12, 14, 0, tzinfo=timezone.utc)

    # Three bar timestamps inside the window, then a timestamp at/after end
    bar_ts_1 = int(start.timestamp()) + 60
    bar_ts_2 = int(start.timestamp()) + 120
    bar_ts_3 = int(start.timestamp()) + 180
    bar_ts_end = int(end.timestamp())  # >= end → should break

    health_result = _make_mock_result({"api_available": True})
    start_result = _make_mock_result({"success": True})
    bar_result_1 = _make_bar_result(bar_ts_1, 5300.0, 5305.0, 5298.0, 5302.0, 1000)
    bar_result_2 = _make_bar_result(bar_ts_2, 5302.0, 5308.0, 5301.0, 5306.0, 1100)
    bar_result_3 = _make_bar_result(bar_ts_3, 5306.0, 5310.0, 5304.0, 5308.0, 900)
    # 4th call returns a bar at ts >= end → loop breaks
    bar_result_at_end = _make_bar_result(bar_ts_end, 5308.0, 5312.0, 5306.0, 5310.0, 800)
    stop_result = _make_mock_result({"success": True})

    mock_session = AsyncMock()
    mock_session.call_tool.side_effect = [
        health_result,   # tv_health_check
        start_result,    # replay_start
        bar_result_1,    # replay_step 1
        bar_result_2,    # replay_step 2
        bar_result_3,    # replay_step 3
        bar_result_at_end,  # replay_step 4 — ts >= end, loop breaks
        stop_result,     # replay_stop (in finally)
    ]

    @asynccontextmanager
    async def mock_stdio_client(_params):
        yield (AsyncMock(), AsyncMock())

    @asynccontextmanager
    async def mock_client_session(_read, _write):
        yield mock_session

    with patch("tv_bridge.replay.stdio_client", mock_stdio_client), \
         patch("tv_bridge.replay.ClientSession", mock_client_session):
        df = await source.fetch_bars("SPY", "1m", start, end)

    expected_columns = ["symbol", "timeframe", "ts_utc", "open", "high", "low", "close", "volume", "provider"]
    assert list(df.columns) == expected_columns
    assert len(df) == 3
    for ts in df["ts_utc"]:
        assert ts.tzinfo is not None, "ts_utc must be tz-aware"
        assert ts.tzinfo == timezone.utc or hasattr(ts.tzinfo, "utcoffset")
    assert df["provider"].iloc[0] == "tradingview_replay"
    assert df["symbol"].iloc[0] == "SPY"


@pytest.mark.asyncio
async def test_fetch_bars_empty(source: TVReplayDataSource) -> None:
    """fetch_bars returns empty DataFrame with correct columns when no bars returned."""
    start = datetime(2024, 6, 12, 13, 30, tzinfo=timezone.utc)
    end = datetime(2024, 6, 12, 14, 0, tzinfo=timezone.utc)

    # First bar is already >= end so loop breaks immediately after start
    ts_at_end = int(end.timestamp())
    health_result = _make_mock_result({"api_available": True})
    start_result = _make_mock_result({"success": True})
    bar_at_end = _make_bar_result(ts_at_end, 5300.0, 5305.0, 5298.0, 5302.0, 1000)
    stop_result = _make_mock_result({"success": True})

    mock_session = AsyncMock()
    mock_session.call_tool.side_effect = [
        health_result,
        start_result,
        bar_at_end,  # ts >= end immediately
        stop_result,
    ]

    @asynccontextmanager
    async def mock_stdio_client(_params):
        yield (AsyncMock(), AsyncMock())

    @asynccontextmanager
    async def mock_client_session(_read, _write):
        yield mock_session

    with patch("tv_bridge.replay.stdio_client", mock_stdio_client), \
         patch("tv_bridge.replay.ClientSession", mock_client_session):
        df = await source.fetch_bars("SPY", "1m", start, end)

    assert df.empty
    expected_columns = ["symbol", "timeframe", "ts_utc", "open", "high", "low", "close", "volume", "provider"]
    assert list(df.columns) == expected_columns


@pytest.mark.asyncio
async def test_fetch_bars_disconnect(source: TVReplayDataSource, mock_bus) -> None:
    """fetch_bars raises DataSourceUnavailable when session.initialize() times out."""
    from unittest.mock import AsyncMock as _AM

    source_with_bus = TVReplayDataSource(settings=Settings(), bus=mock_bus)

    start = datetime(2024, 6, 12, 13, 30, tzinfo=timezone.utc)
    end = datetime(2024, 6, 12, 14, 0, tzinfo=timezone.utc)

    mock_session = _AM()
    mock_session.initialize.side_effect = TimeoutError("connection timed out")

    @asynccontextmanager
    async def mock_stdio_client(_params):
        yield (AsyncMock(), AsyncMock())

    @asynccontextmanager
    async def mock_client_session(_read, _write):
        yield mock_session

    with patch("tv_bridge.replay.stdio_client", mock_stdio_client), \
         patch("tv_bridge.replay.ClientSession", mock_client_session):
        with pytest.raises(DataSourceUnavailable):
            await source_with_bus.fetch_bars("SPY", "1m", start, end)

    # DegradedStateEvent should have been published
    assert len(mock_bus.published_events) >= 1
    topics = [t for t, _ in mock_bus.published_events]
    assert "degraded_state" in topics
