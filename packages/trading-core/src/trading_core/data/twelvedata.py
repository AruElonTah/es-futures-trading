"""``TwelveDataSource`` — Twelve Data REST adapter (MD-03).

ADR 0001 demoted Twelve Data to **secondary** — TradingView MCP is primary.
This adapter exists for headless reconciliation and SPY-proxy backfills
(Phase 0 spike found Twelve Data does NOT cover ES futures). It implements
the ``trading_core.data.protocols.DataSource`` Protocol so the Phase 6
TVBridge and this REST shim are interchangeable at the seam.

Why raw httpx and NOT the official ``twelvedata`` SDK?
    The SDK hides ``api-credits-used`` / ``api-credits-left`` response
    headers — Phase 0 found these are the only reliable pacing signal on
    the Free tier (catalog endpoints emit no headers; ``/time_series``
    does). Without header reads, pacing falls back to time-based heuristics
    that produce 429s under bursty load. See 01-RESEARCH.md §Pitfall 6.

Why redact ``apikey`` in logs?
    Threat T-01-04-01 — the API key value sits in the query string of every
    ``/time_series`` URL. ``_redact_url`` substitutes ``apikey=<value>``
    with ``apikey=<TWELVEDATA_API_KEY>`` before any structlog call.
    The sentinel ``<TWELVEDATA_API_KEY>`` matches Phase 0's redaction
    pattern in ``.planning/research/spike-0/twelvedata-probe.json``.

Subscribe (live) is out of scope for Phase 1 — backfill only. Use
``TradingViewDataSource`` for live polling.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime
from typing import AsyncIterator

import httpx
import pandas as pd
import structlog

from trading_core.config import Settings
from trading_core.data.models import Bar
from trading_core.data.protocols import (
    DataSourceUnavailable,
    RateLimited,
)

_TWELVE_DATA_BASE_URL = "https://api.twelvedata.com"
_TIME_SERIES_ENDPOINT = f"{_TWELVE_DATA_BASE_URL}/time_series"
_REDACTION_SENTINEL = "<TWELVEDATA_API_KEY>"
_REDACT_RE = re.compile(r"apikey=[^&]+")

# Map Plan-1 timeframe strings to Twelve Data's ``interval`` query value.
_TF_TO_INTERVAL: dict[str, str] = {
    "1m": "1min",
    "5m": "5min",
    "15m": "15min",
}

_log = structlog.get_logger(__name__)


def _redact_url(url: str) -> str:
    """Replace the ``apikey=`` query value with the redaction sentinel."""
    return _REDACT_RE.sub(f"apikey={_REDACTION_SENTINEL}", url)


class TwelveDataSource:
    """Async DataSource adapter for Twelve Data REST ``/time_series``.

    Phase 1 scope: backfill only. ``subscribe_bars`` raises
    ``NotImplementedError`` — live streaming is not part of MD-03.
    """

    name = "twelve_data"

    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.AsyncClient | None = None,
        pacing_seconds: float = 9.0,
    ) -> None:
        self._settings = settings
        self._client = client
        self._pacing_seconds = pacing_seconds

    # ---- DataSource Protocol surface --------------------------------------

    async def fetch_bars(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> pd.DataFrame:
        """Historical pull via ``/time_series``.

        Raises:
            ValueError: if ``start``/``end`` are not tz-aware UTC, or if
                ``timeframe`` is not 1m/5m/15m.
            RateLimited: on HTTP 429.
            DataSourceUnavailable: on HTTP 5xx.
        """
        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError("start and end must be tz-aware UTC datetimes")
        start_offset = start.utcoffset()
        end_offset = end.utcoffset()
        if (
            start_offset is None
            or end_offset is None
            or start_offset.total_seconds() != 0
            or end_offset.total_seconds() != 0
        ):
            raise ValueError("start and end must be UTC (offset 0)")
        if timeframe not in _TF_TO_INTERVAL:
            raise ValueError(
                f"Unsupported timeframe {timeframe!r}; "
                f"supported: {sorted(_TF_TO_INTERVAL)}"
            )

        # Read the API key lazily — at fetch time, not construction time.
        # This lets the operator hot-swap the .env without rebuilding the
        # adapter (e.g., when rotating credentials).
        api_key = (
            self._settings.twelvedata_api_key.get_secret_value()
            if self._settings.twelvedata_api_key is not None
            else ""
        )

        params = {
            "symbol": symbol,
            "interval": _TF_TO_INTERVAL[timeframe],
            "start_date": start.strftime("%Y-%m-%d %H:%M:%S"),
            "end_date": end.strftime("%Y-%m-%d %H:%M:%S"),
            "format": "JSON",
            "timezone": "UTC",
            "apikey": api_key,
        }

        # Build the URL for the audit log BEFORE the request fires so we can
        # log a request-attempt line even if the call raises.
        request = httpx.Request("GET", _TIME_SERIES_ENDPOINT, params=params)
        redacted_url = _redact_url(str(request.url))
        _log.info(
            "fetch_bars.request",
            url=redacted_url,
            symbol=symbol,
            timeframe=timeframe,
        )

        # Use the injected client (for respx mocking) or open a one-shot one.
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=30.0)
        try:
            response = await client.send(request)
        finally:
            if owns_client:
                await client.aclose()

        credits_left = response.headers.get("api-credits-left")
        credits_used = response.headers.get("api-credits-used")

        if response.status_code == 429:
            _log.warning(
                "ratelimited",
                status=429,
                url=redacted_url,
                credits_left=credits_left,
                credits_used=credits_used,
            )
            raise RateLimited(
                f"Twelve Data 429 ratelimited (credits_left={credits_left}): "
                f"{response.text[:200]}"
            )
        if response.status_code >= 500:
            _log.error(
                "fetch_bars.unavailable",
                status=response.status_code,
                url=redacted_url,
            )
            raise DataSourceUnavailable(
                f"Twelve Data {response.status_code}: {response.text[:200]}"
            )

        _log.info(
            "fetch_bars.response",
            status=response.status_code,
            url=redacted_url,
            credits_left=credits_left,
            credits_used=credits_used,
        )

        payload = response.json()
        values = payload.get("values") or []

        # Pace AFTER the request fires so rapid back-to-back calls cannot
        # outpace the free-tier 8-credits-per-minute window. The caller
        # (seed_bars.py) loops over multiple windows; this sleep prevents
        # 429s on the next iteration.
        await asyncio.sleep(self._pacing_seconds)

        if not values:
            return pd.DataFrame(
                columns=[
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
            )

        # Twelve Data returns ``values`` newest-first by default. Convert each
        # row and re-sort ascending by ts_utc so downstream consumers (gap
        # detector, DuckDB upserts) see chronological order.
        ts = [
            pd.Timestamp(v["datetime"], tz="UTC").to_pydatetime()
            for v in values
        ]
        df = pd.DataFrame(
            {
                "symbol": [symbol] * len(values),
                "timeframe": [timeframe] * len(values),
                "ts_utc": ts,
                "open": [float(v["open"]) for v in values],
                "high": [float(v["high"]) for v in values],
                "low": [float(v["low"]) for v in values],
                "close": [float(v["close"]) for v in values],
                "volume": [int(v.get("volume") or 0) for v in values],
                "provider": [self.name] * len(values),
            }
        )
        return df.sort_values("ts_utc").reset_index(drop=True)

    async def subscribe_bars(
        self,
        symbol: str,
        timeframe: str,
    ) -> AsyncIterator[Bar]:
        """Live polling — NOT implemented for Phase 1.

        CONTEXT.md scope for this adapter is backfill only. Use
        ``TradingViewDataSource`` for live data flow; this method exists to
        satisfy the ``DataSource`` Protocol surface so mypy does not flag
        the missing method.
        """
        raise NotImplementedError(
            "Twelve Data live subscribe is out of scope for Phase 1; "
            "backfill only — use TradingViewDataSource for live"
        )
        # The unreachable yield below makes this function an async-generator
        # per the Protocol's AsyncIterator[Bar] return — mypy/Pyright
        # otherwise infer this as ``Coroutine[..., AsyncIterator[Bar]]``.
        if False:
            yield  # pragma: no cover
