"""Tests for ``trading_core.data.twelvedata.TwelveDataSource`` (MD-03).

Behavior covered:
- happy path: HTTP 200 → DataFrame with [symbol, timeframe, ts_utc, open,
  high, low, close, volume, provider] columns; UTC timestamps
- HTTP 429 raises ``RateLimited``; log entry contains ``event="ratelimited"``
- HTTP 503 raises ``DataSourceUnavailable``
- API key is redacted in structlog log lines (NEVER the literal value)
- ``rate-limit`` headers are read and logged (``credits_left`` key in log)
- pacing: ``await asyncio.sleep(self._pacing_seconds)`` runs with ≥ 9.0
- ``subscribe_bars`` raises NotImplementedError

The adapter is exercised against a ``respx`` mock — no live network access.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import httpx
import pandas as pd
import pytest
import respx
import structlog

from trading_core.config import Settings
from trading_core.data.protocols import (
    DataSourceUnavailable,
    RateLimited,
)
from trading_core.data.twelvedata import TwelveDataSource


FAKE_KEY = "FAKEKEY12345"


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Build a Settings with the fake API key injected via env."""
    monkeypatch.setenv("TWELVEDATA_API_KEY", FAKE_KEY)
    return Settings()


@pytest.fixture
def start_end() -> tuple[datetime, datetime]:
    start = datetime(2024, 6, 12, 13, 30, tzinfo=timezone.utc)
    end = datetime(2024, 6, 12, 16, 0, tzinfo=timezone.utc)
    return start, end


# ---------------------------------------------------------------------------
# happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_fetch_bars_happy_path(
    settings: Settings, start_end: tuple[datetime, datetime]
) -> None:
    start, end = start_end
    # respx route: any GET to /time_series → 200 with a 3-bar payload.
    respx.get("https://api.twelvedata.com/time_series").respond(
        status_code=200,
        headers={
            "api-credits-used": "1",
            "api-credits-left": "7",
        },
        json={
            "meta": {
                "symbol": "SPY",
                "interval": "1min",
                "currency": "USD",
                "exchange_timezone": "UTC",
            },
            "values": [
                {
                    "datetime": "2024-06-12 13:30:00",
                    "open": "537.50",
                    "high": "537.75",
                    "low": "537.40",
                    "close": "537.70",
                    "volume": "12345",
                },
                {
                    "datetime": "2024-06-12 13:31:00",
                    "open": "537.70",
                    "high": "537.80",
                    "low": "537.60",
                    "close": "537.65",
                    "volume": "9876",
                },
                {
                    "datetime": "2024-06-12 13:32:00",
                    "open": "537.65",
                    "high": "537.90",
                    "low": "537.55",
                    "close": "537.85",
                    "volume": "11111",
                },
            ],
            "status": "ok",
        },
    )

    source = TwelveDataSource(settings, pacing_seconds=0.0)
    df = await source.fetch_bars("SPY", "1m", start, end)
    assert list(df.columns) == [
        "symbol",
        "timeframe",
        "ts_utc",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "provider",
    ]
    assert len(df) == 3
    # ts_utc must be tz-aware UTC
    assert df["ts_utc"].iloc[0].tzinfo is not None
    assert df["ts_utc"].iloc[0].utcoffset().total_seconds() == 0
    # provider stamped from the adapter
    assert (df["provider"] == "twelve_data").all()
    # symbol/timeframe injected
    assert (df["symbol"] == "SPY").all()
    assert (df["timeframe"] == "1m").all()


# ---------------------------------------------------------------------------
# 429 → RateLimited
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_429_raises_rate_limited(
    settings: Settings, start_end: tuple[datetime, datetime]
) -> None:
    start, end = start_end
    respx.get("https://api.twelvedata.com/time_series").respond(
        status_code=429,
        json={"code": 429, "message": "You have run out of API credits"},
    )

    source = TwelveDataSource(settings, pacing_seconds=0.0)

    log_events: list[dict] = []
    with structlog.testing.capture_logs() as logs:
        with pytest.raises(RateLimited):
            await source.fetch_bars("SPY", "1m", start, end)
        log_events = list(logs)

    assert any(
        e.get("event") == "ratelimited" and e.get("status") == 429
        for e in log_events
    ), f"No ratelimited log event found in {log_events}"


# ---------------------------------------------------------------------------
# 503 → DataSourceUnavailable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_503_raises_data_source_unavailable(
    settings: Settings, start_end: tuple[datetime, datetime]
) -> None:
    start, end = start_end
    respx.get("https://api.twelvedata.com/time_series").respond(
        status_code=503,
        text="service unavailable",
    )

    source = TwelveDataSource(settings, pacing_seconds=0.0)
    with pytest.raises(DataSourceUnavailable):
        await source.fetch_bars("SPY", "1m", start, end)


# ---------------------------------------------------------------------------
# redaction: API key NEVER appears in captured log lines
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_api_key_is_redacted_in_logs(
    settings: Settings, start_end: tuple[datetime, datetime]
) -> None:
    start, end = start_end
    respx.get("https://api.twelvedata.com/time_series").respond(
        status_code=200,
        headers={"api-credits-used": "1", "api-credits-left": "7"},
        json={"values": [], "status": "ok"},
    )

    source = TwelveDataSource(settings, pacing_seconds=0.0)
    with structlog.testing.capture_logs() as logs:
        await source.fetch_bars("SPY", "1m", start, end)

    # The fake API key value must not appear ANYWHERE in the captured events.
    joined = " ".join(repr(e) for e in logs)
    assert FAKE_KEY not in joined, (
        f"Raw API key leaked into logs: {joined}"
    )
    # And the sentinel must appear at least once (proves redaction ran).
    assert "<TWELVEDATA_API_KEY>" in joined


# ---------------------------------------------------------------------------
# credits-left header reading
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_credits_left_header_logged(
    settings: Settings, start_end: tuple[datetime, datetime]
) -> None:
    start, end = start_end
    respx.get("https://api.twelvedata.com/time_series").respond(
        status_code=200,
        headers={"api-credits-used": "1", "api-credits-left": "7"},
        json={"values": [], "status": "ok"},
    )

    source = TwelveDataSource(settings, pacing_seconds=0.0)
    with structlog.testing.capture_logs() as logs:
        await source.fetch_bars("SPY", "1m", start, end)

    assert any("credits_left" in e for e in logs), (
        f"No credits_left field in log events: {logs}"
    )


# ---------------------------------------------------------------------------
# pacing: asyncio.sleep called with >= 9.0 by default
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_pacing_default_9s(
    settings: Settings,
    start_end: tuple[datetime, datetime],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start, end = start_end
    respx.get("https://api.twelvedata.com/time_series").respond(
        status_code=200,
        headers={"api-credits-used": "1", "api-credits-left": "7"},
        json={"values": [], "status": "ok"},
    )

    mock_sleep = AsyncMock()
    monkeypatch.setattr(
        "trading_core.data.twelvedata.asyncio.sleep", mock_sleep
    )

    source = TwelveDataSource(settings)  # default pacing_seconds=9.0
    await source.fetch_bars("SPY", "1m", start, end)
    assert mock_sleep.await_count >= 1, "asyncio.sleep was not awaited"
    awaited_value = mock_sleep.await_args_list[0].args[0]
    assert awaited_value >= 9.0, f"Sleep awaited with {awaited_value} (< 9.0)"


# ---------------------------------------------------------------------------
# subscribe_bars → NotImplementedError
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_subscribe_bars_not_implemented(settings: Settings) -> None:
    source = TwelveDataSource(settings, pacing_seconds=0.0)
    with pytest.raises(NotImplementedError):
        # subscribe_bars is declared as ``async def`` returning AsyncIterator.
        # If it's implemented as a coroutine that raises on call, the call
        # itself raises. If it's an async-generator, we need to anext() it —
        # try both patterns.
        result = source.subscribe_bars("SPY", "1m")
        # If result is a coroutine, awaiting it raises directly.
        if hasattr(result, "__aiter__"):
            async for _ in result:
                break
        else:
            await result
