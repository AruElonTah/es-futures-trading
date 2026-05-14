"""``TradingViewDataSource`` — DataSource adapter over the TradingView MCP server (MD-02).

Phase 1 scope: this adapter assumes the operator's TV Desktop is already
running in CDP mode and the ``tradingview-mcp-jackson`` server is reachable
via stdio. CDP bootstrap (``--remote-debugging-port=9222``, restart
resilience, supervisor) is **Phase 6 territory** — see
``00-02-SUMMARY.md`` for the spike evidence.

Pitfall 9 (RESEARCH.md lines 1080-1082) — INHERITED FROM PHASE 0:
    The mcp SDK 1.x ``stdio_client`` does NOT expose the subprocess's
    stderr to the client. Diagnostic output from the
    ``tradingview-mcp-jackson`` server is not directly capturable via the
    canonical SDK pattern. Phase 1's adapter operates blind to server-side
    stderr; Phase 6 TVBridge will replace ``stdio_client`` with a custom
    ``subprocess.Popen`` transport that captures stderr for operational
    observability.

CDP-disconnect contract:
    - ``fetch_bars`` is a one-shot historical call: on any transport failure
      (initialize timeout, ``tv_health_check.api_available == False``, mcp
      protocol exception) the adapter publishes ``DegradedStateEvent`` to
      the EventBus **AND** raises ``DataSourceUnavailable``. Callers that
      catch the exception should not need to consult the bus — but Phase 3's
      UI banner subscriber gets the signal too.
    - ``subscribe_bars`` (live polling iterator) publishes
      ``DegradedStateEvent`` on disconnect and **stops iterating** — does
      NOT raise. Per the ``DataSource`` Protocol contract in
      ``data/protocols.py``: "CDP/connection failures should be published
      as DegradedStateEvent on the bus rather than raised — the caller
      would otherwise have to catch and re-establish, which is the bridge's
      job (Phase 6)."
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, AsyncIterator, cast

import pandas as pd
import structlog
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from trading_core.config import Settings
from trading_core.data.models import Bar
from trading_core.data.protocols import DataSourceUnavailable
from trading_core.events import (
    TOPIC_DEGRADED_STATE,
    DegradedStateEvent,
    EventBus,
)

_log = structlog.get_logger(__name__)

# Plan-1 -> TV-canonical symbol map. SPY uses the TwelveDataSource — TV
# adapter explicitly rejects it.
_SYMBOL_MAP: dict[str, str] = {
    "ES": "CME_MINI:ES1!",
    "MES": "CME_MINI:MES1!",
}

# Plan-1 timeframe -> TV ``timeframe`` argument (TV uses minute counts as
# strings for intraday).
_TF_TO_TV: dict[str, str] = {
    "1m": "1",
    "5m": "5",
    "15m": "15",
}

# Poll cadence for ``subscribe_bars`` per timeframe.
_TF_TO_POLL_SECONDS: dict[str, float] = {
    "1m": 60.0,
    "5m": 300.0,
    "15m": 900.0,
}

# Default MCP server path — overridable via constructor kwarg.
_DEFAULT_MCP_SERVER_PATH = Path(r"C:\Users\Admin\tradingview-mcp-jackson")

_INIT_TIMEOUT_SECONDS = 15.0


class TradingViewDataSource:
    """Async DataSource adapter over the TV MCP server.

    Construction does NOT spawn the MCP subprocess — every call to
    ``fetch_bars`` opens a fresh ``stdio_client`` + ``ClientSession`` and
    tears it down on exit. That keeps Phase 1's footprint small and matches
    Plan 05's CLI ergonomics (single-shot backfills).
    """

    name = "tradingview_mcp"

    def __init__(
        self,
        settings: Settings,
        *,
        bus: EventBus,
        mcp_server_path: Path | None = None,
    ) -> None:
        self._settings = settings
        self._bus = bus
        self._mcp_server_path = mcp_server_path or _DEFAULT_MCP_SERVER_PATH

    # ---- helpers ----------------------------------------------------------

    def _map_symbol(self, symbol: str) -> str:
        """Map Plan-1 symbol to TV-canonical form. SPY is rejected."""
        if symbol == "SPY":
            raise ValueError(
                "TradingViewDataSource does not support SPY in Phase 1; "
                "use TwelveDataSource for SPY backfill"
            )
        tv = _SYMBOL_MAP.get(symbol)
        if tv is None:
            raise ValueError(
                f"Unknown symbol for TradingView adapter: {symbol!r}; "
                f"known: {sorted(_SYMBOL_MAP)}"
            )
        return tv

    def _server_params(self) -> StdioServerParameters:
        """Build the StdioServerParameters spawning the Node MCP server.

        Mirrors the Phase 0 spike pattern (``scripts/spike/tv_mcp_smoke.py``
        lines 261-265) — ``node`` + the absolute ``src/server.js`` path.
        """
        server_js = self._mcp_server_path / "src" / "server.js"
        return StdioServerParameters(
            command="node",
            args=[str(server_js)],
            env=None,
        )

    async def _publish_degraded(self, reason: str) -> None:
        """Emit ``DegradedStateEvent`` on the bus. Safe to await on any path."""
        try:
            await self._bus.publish(
                TOPIC_DEGRADED_STATE,
                DegradedStateEvent(
                    topic=TOPIC_DEGRADED_STATE,
                    emitted_at=datetime.now(tz=timezone.utc),
                    source=self.name,
                    reason=reason,
                ),
            )
        except Exception as e:
            # Never let the degraded-state publish path mask the underlying
            # error — log and continue.
            _log.warning("degraded_publish_failed", error=repr(e))

    @staticmethod
    def _parse_tool_payload(result: object) -> dict[str, object]:
        """Decode the first text-content blob of an mcp tool-call result."""
        content = getattr(result, "content", None)
        if not content:
            return {}
        try:
            text = content[0].text
        except (AttributeError, IndexError):
            return {}
        try:
            payload = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return {"_raw": text}
        return payload if isinstance(payload, dict) else {"_value": payload}

    @staticmethod
    def _bar_time_to_utc(value: object) -> datetime:
        """Convert the bar.time field to tz-aware UTC datetime.

        Phase 0 transcript shows TV emits Unix epoch SECONDS for intraday
        bars (e.g., ``time=1778761980`` for 2026-05-13 19:13 UTC). Heuristic:
        13-digit numbers are millis, 10-digit are seconds. ISO 8601 strings
        are accepted for forward compatibility.
        """
        if isinstance(value, (int, float)):
            seconds = float(value) / 1000.0 if value > 10_000_000_000 else float(value)
            return datetime.fromtimestamp(seconds, tz=timezone.utc)
        if isinstance(value, str):
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
                timezone.utc
            )
        raise ValueError(f"Cannot parse bar time field: {value!r}")

    # ---- DataSource Protocol surface --------------------------------------

    async def fetch_bars(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> pd.DataFrame:
        """Historical pull via the MCP ``data_get_ohlcv`` tool.

        Raises:
            ValueError: on SPY or unsupported timeframe.
            DataSourceUnavailable: on init timeout / health-check fail /
                mcp protocol exception. Always paired with a
                DegradedStateEvent published to the bus.
        """
        if timeframe not in _TF_TO_TV:
            raise ValueError(
                f"Unsupported timeframe {timeframe!r}; "
                f"supported: {sorted(_TF_TO_TV)}"
            )
        tv_symbol = self._map_symbol(symbol)
        tv_timeframe = _TF_TO_TV[timeframe]

        _log.info(
            "fetch_bars.request",
            tv_symbol=tv_symbol,
            timeframe=timeframe,
            start=start.isoformat(),
            end=end.isoformat(),
        )

        # Compute a generous bar-count budget. The TV server caps at 300 in
        # practice (Phase 0 transcript) but we ask for the full window.
        seconds = max(int((end - start).total_seconds()), 60)
        tf_seconds = {"1m": 60, "5m": 300, "15m": 900}[timeframe]
        count = max(seconds // tf_seconds, 1)

        try:
            async with stdio_client(self._server_params()) as (read, write):
                session_ctx = ClientSession(read, write)
                async with session_ctx as session:
                    try:
                        await asyncio.wait_for(
                            session.initialize(), timeout=_INIT_TIMEOUT_SECONDS
                        )
                    except asyncio.TimeoutError:
                        await self._publish_degraded("mcp initialize timed out")
                        raise DataSourceUnavailable("mcp initialize timed out")
                    except Exception as e:
                        await self._publish_degraded(
                            f"mcp initialize failed: {type(e).__name__}: {e}"
                        )
                        raise DataSourceUnavailable(
                            f"mcp initialize failed: {e}"
                        ) from e

                    # Health gate — Phase 0 found api_available=True is the
                    # real "TV is ready" signal (cdp_connected can be True
                    # against a partially-loaded target where
                    # _activeChartWidgetWV is undefined).
                    health_result = await session.call_tool("tv_health_check", {})
                    health = self._parse_tool_payload(health_result)
                    if not health.get("api_available"):
                        reason = (
                            f"tv_health_check api_available={health.get('api_available')!r}; "
                            f"error={health.get('error')!r}"
                        )
                        await self._publish_degraded(reason)
                        raise DataSourceUnavailable(reason)

                    # Actual data pull.
                    ohlcv_result = await session.call_tool(
                        "data_get_ohlcv",
                        {
                            "symbol": tv_symbol,
                            "timeframe": tv_timeframe,
                            "count": int(count),
                            "end": end.isoformat(),
                        },
                    )
                    ohlcv = self._parse_tool_payload(ohlcv_result)
                    if not ohlcv.get("success", True):
                        reason = (
                            f"data_get_ohlcv failed: "
                            f"{ohlcv.get('error') or ohlcv.get('hint') or 'unknown'}"
                        )
                        await self._publish_degraded(reason)
                        raise DataSourceUnavailable(reason)

                    raw_bars = ohlcv.get("bars") or ohlcv.get("data") or []
                    bars: list[dict[str, Any]] = (
                        cast(list[dict[str, Any]], list(raw_bars))
                        if isinstance(raw_bars, list)
                        else []
                    )
        except DataSourceUnavailable:
            raise
        except Exception as e:
            # Any mcp / stdio exception lands here.
            await self._publish_degraded(
                f"mcp transport error: {type(e).__name__}: {e}"
            )
            raise DataSourceUnavailable(
                f"mcp transport error: {e}"
            ) from e

        if not bars:
            return pd.DataFrame(
                columns=[
                    "symbol", "timeframe", "ts_utc", "open", "high",
                    "low", "close", "volume", "provider",
                ]
            )

        ts = [self._bar_time_to_utc(b.get("time") or b.get("datetime")) for b in bars]
        df = pd.DataFrame(
            {
                "symbol": [symbol] * len(bars),
                "timeframe": [timeframe] * len(bars),
                "ts_utc": ts,
                "open": [float(b["open"]) for b in bars],
                "high": [float(b["high"]) for b in bars],
                "low": [float(b["low"]) for b in bars],
                "close": [float(b["close"]) for b in bars],
                "volume": [int(b.get("volume") or 0) for b in bars],
                "provider": [self.name] * len(bars),
            }
        )
        return df.sort_values("ts_utc").reset_index(drop=True)

    async def subscribe_bars(
        self,
        symbol: str,
        timeframe: str,
    ) -> AsyncIterator[Bar]:
        """Live polling.

        Phase 1 implementation: open a long-lived ClientSession, then
        periodically call ``data_get_ohlcv(count=2)`` and yield the
        most-recently-closed bar. On any transport failure: publish
        ``DegradedStateEvent`` to the bus and STOP iterating — does not
        raise (per DataSource Protocol contract).

        Phase 6 will own a richer implementation backed by a TV websocket /
        Pine alert stream — this v1 polling shim is enough to wire the
        signal path end-to-end.
        """
        if timeframe not in _TF_TO_TV:
            raise ValueError(
                f"Unsupported timeframe {timeframe!r}; "
                f"supported: {sorted(_TF_TO_TV)}"
            )
        tv_symbol = self._map_symbol(symbol)
        tv_timeframe = _TF_TO_TV[timeframe]
        poll_seconds = _TF_TO_POLL_SECONDS[timeframe]

        last_ts: datetime | None = None
        try:
            async with stdio_client(self._server_params()) as (read, write):
                async with ClientSession(read, write) as session:
                    try:
                        await asyncio.wait_for(
                            session.initialize(), timeout=_INIT_TIMEOUT_SECONDS
                        )
                    except Exception as e:
                        await self._publish_degraded(
                            f"subscribe initialize failed: {type(e).__name__}: {e}"
                        )
                        return

                    while True:
                        try:
                            ohlcv_result = await session.call_tool(
                                "data_get_ohlcv",
                                {
                                    "symbol": tv_symbol,
                                    "timeframe": tv_timeframe,
                                    "count": 2,
                                },
                            )
                        except Exception as e:
                            await self._publish_degraded(
                                f"subscribe call_tool failed: "
                                f"{type(e).__name__}: {e}"
                            )
                            return

                        ohlcv = self._parse_tool_payload(ohlcv_result)
                        raw_sub_bars = ohlcv.get("bars") or []
                        bars: list[dict[str, Any]] = (
                            cast(list[dict[str, Any]], list(raw_sub_bars))
                            if isinstance(raw_sub_bars, list)
                            else []
                        )
                        if bars:
                            # Yield the second-to-last (last closed) bar — the
                            # final entry is the still-forming bar.
                            b = bars[-2] if len(bars) >= 2 else bars[-1]
                            ts_utc = self._bar_time_to_utc(
                                b.get("time") or b.get("datetime")
                            )
                            if last_ts is None or ts_utc > last_ts:
                                last_ts = ts_utc
                                yield Bar(
                                    symbol=symbol,
                                    timeframe=timeframe,
                                    ts_utc=ts_utc,
                                    open=b["open"],
                                    high=b["high"],
                                    low=b["low"],
                                    close=b["close"],
                                    volume=int(b.get("volume") or 0),
                                )
                        await asyncio.sleep(poll_seconds)
        except Exception as e:
            await self._publish_degraded(
                f"subscribe transport error: {type(e).__name__}: {e}"
            )
            return
