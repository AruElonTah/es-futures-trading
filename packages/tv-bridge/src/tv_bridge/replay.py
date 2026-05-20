"""``TVReplayDataSource`` — DataSource backed by TradingView replay session (TV-04).

Phase 6 Plan 03 scope: implements the DataSource protocol via per-call
stdio_client subprocesses so the operator can drive a backtest from a TV
replay session through the same Strategy.on_bar path as historical-Parquet runs.

Per-call subprocess strategy (PATTERNS.md Pitfall 4):
    Each fetch_bars call opens its own stdio_client + ClientSession subprocess.
    This means replay and the shared TVBridge live-drawing session do NOT
    contend for the same MCP subprocess (WARNING 3 fix).

Subscribe semantics not supported in v1 (TV streaming is Phase 7 territory).
Callers that need live streaming should use TradingViewDataSource instead.

Security note (T-06-03-01):
    TVReplayDataSource is only used when --data-source tv-replay is passed
    (constrained by argparse choices= in run_backtest.py). No user-supplied
    strings are interpolated into the MCP call — symbol is mapped through
    _SYMBOL_MAP and SPY falls through unchanged.

DoS mitigation (T-06-03-02):
    asyncio.wait_for(_REPLAY_STEP_TIMEOUT) on each replay_step call prevents
    infinite blocking. replay_stop is in a finally block so partial reads
    always tear down the replay session.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, AsyncIterator

import pandas as pd
import structlog
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from trading_core.config import Settings
from trading_core.data.models import Bar
from trading_core.data.protocols import DataSourceUnavailable
from trading_core.events import TOPIC_DEGRADED_STATE, DegradedStateEvent, EventBus

_log = structlog.get_logger(__name__)

# Plan-1 symbol map — SPY falls through unchanged (reconciliation uses SPY directly).
_SYMBOL_MAP: dict[str, str] = {"ES": "CME_MINI:ES1!", "MES": "CME_MINI:MES1!"}

# Plan-1 timeframe -> TV ``timeframe`` argument (TV uses minute counts as strings).
_TF_TO_TV: dict[str, str] = {"1m": "1", "5m": "5", "15m": "15"}

# Default MCP server path — overridable via constructor kwarg.
_DEFAULT_MCP_SERVER_PATH = Path(r"C:\Users\Admin\tradingview-mcp-jackson")

_INIT_TIMEOUT_SECONDS = 15.0
_REPLAY_STEP_TIMEOUT = 5.0


class TVReplayDataSource:
    """DataSource backed by a TradingView replay session (TV-04).

    Opens a fresh per-call stdio_client subprocess on every fetch_bars call —
    never reuses the shared TVBridge session — so replay and live drawing can
    co-exist without contention (PATTERNS.md Pitfall 4, WARNING 3 fix).

    subscribe_bars raises NotImplementedError — replay is fetch-only in v1.
    Phase 7 streaming will implement it via a dedicated supervised session.
    """

    name = "tradingview_replay"

    def __init__(
        self,
        settings: Settings,
        *,
        bus: EventBus | None = None,
        mcp_server_path: Path | None = None,
    ) -> None:
        """Construct TVReplayDataSource.

        Does NOT spawn a subprocess — construction is pure attribute setup.
        Call fetch_bars() to open a per-call subprocess.

        Args:
            settings: Application settings (for future config extension).
            bus: Optional EventBus for publishing DegradedStateEvent on failure.
                 None means degraded events are silently logged only.
            mcp_server_path: Override for the MCP server path (testing / dev).
        """
        self._settings = settings
        self._bus = bus
        self._mcp_server_path = mcp_server_path or _DEFAULT_MCP_SERVER_PATH

    # ---- helpers ----------------------------------------------------------

    def _server_params(self) -> StdioServerParameters:
        """Build StdioServerParameters for the tradingview-mcp-jackson Node server."""
        server_js = self._mcp_server_path / "src" / "server.js"
        return StdioServerParameters(
            command="node",
            args=[str(server_js)],
            env=None,
        )

    @staticmethod
    def _parse_tool_payload(result: object) -> dict[str, Any]:
        """Decode the first text-content blob of an MCP tool-call result.

        Returns an empty dict on any parse failure.
        """
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
        bars (e.g., ``time=1778761980``). Heuristic: 13-digit numbers are
        millis, 10-digit are seconds. ISO 8601 strings are accepted for
        forward compatibility.
        """
        if isinstance(value, (int, float)):
            seconds = float(value) / 1000.0 if value > 10_000_000_000 else float(value)
            return datetime.fromtimestamp(seconds, tz=timezone.utc)
        if isinstance(value, str):
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
                timezone.utc
            )
        raise ValueError(f"Cannot parse bar time field: {value!r}")

    async def _publish_degraded(self, reason: str) -> None:
        """Emit DegradedStateEvent on the bus if available. Never raises."""
        if self._bus is None:
            _log.warning("tv_replay.degraded_no_bus", reason=reason)
            return
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
        except Exception as exc:
            _log.warning("degraded_publish_failed", error=repr(exc))

    # ---- DataSource Protocol surface -------------------------------------

    async def fetch_bars(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> pd.DataFrame:
        """Historical pull via TV replay session.

        Opens a fresh per-call stdio subprocess. Uses replay_start to position
        the replay at ``start``, then calls replay_step repeatedly until a bar
        timestamp >= ``end`` is encountered. Always calls replay_stop in a
        finally block (T-06-03-02 DoS mitigation).

        Args:
            symbol: Instrument symbol (e.g. "ES", "MES", "SPY").
            timeframe: Bar timeframe ("1m" | "5m" | "15m").
            start: tz-aware UTC start (inclusive).
            end: tz-aware UTC end (exclusive — bars at or after end not included).

        Returns:
            DataFrame with columns:
                symbol, timeframe, ts_utc, open, high, low, close, volume, provider
            Empty DataFrame (same columns) if no bars are in the window.

        Raises:
            DataSourceUnavailable: on init timeout, health-check failure,
                or any MCP transport exception. Always paired with a
                DegradedStateEvent published to the bus (if bus is set).
        """
        tv_symbol = _SYMBOL_MAP.get(symbol, symbol)  # SPY falls through unchanged
        tv_timeframe = _TF_TO_TV.get(timeframe, timeframe)
        empty_columns = [
            "symbol", "timeframe", "ts_utc",
            "open", "high", "low", "close", "volume", "provider",
        ]

        _log.info(
            "tv_replay.fetch_bars",
            symbol=symbol,
            tv_symbol=tv_symbol,
            timeframe=timeframe,
            start=start.isoformat(),
            end=end.isoformat(),
        )

        try:
            async with stdio_client(self._server_params()) as (read, write):
                async with ClientSession(read, write) as session:
                    try:
                        await asyncio.wait_for(
                            session.initialize(), timeout=_INIT_TIMEOUT_SECONDS
                        )
                    except Exception as e:
                        await self._publish_degraded(
                            f"tv_replay initialize failed: {type(e).__name__}: {e}"
                        )
                        raise DataSourceUnavailable(
                            f"tv_replay initialize failed: {e}"
                        ) from e

                    # Health gate — same pattern as TradingViewDataSource.
                    health_result = await session.call_tool("tv_health_check", {})
                    health = self._parse_tool_payload(health_result)
                    if not health.get("api_available"):
                        reason = (
                            f"tv_health_check api_available={health.get('api_available')!r}; "
                            f"error={health.get('error')!r}"
                        )
                        await self._publish_degraded(reason)
                        raise DataSourceUnavailable(reason)

                    # Start replay at the requested date.
                    start_result = await session.call_tool(
                        "replay_start",
                        {
                            "symbol": tv_symbol,
                            "date": start.isoformat(),
                            "timeframe": tv_timeframe,
                        },
                    )
                    start_payload = self._parse_tool_payload(start_result)
                    if not start_payload.get("success", True):
                        reason = f"replay_start failed: {start_payload}"
                        await self._publish_degraded(reason)
                        raise DataSourceUnavailable(reason)

                    bars: list[dict[str, Any]] = []
                    try:
                        while True:
                            step_result = await asyncio.wait_for(
                                session.call_tool("replay_step", {"count": 1}),
                                timeout=_REPLAY_STEP_TIMEOUT,
                            )
                            step = self._parse_tool_payload(step_result)
                            bar = step.get("bar") or step.get("last_bar")
                            if not bar:
                                # No bar in payload — replay exhausted.
                                break
                            ts = self._bar_time_to_utc(
                                bar.get("time") or bar.get("datetime")
                            )
                            if ts >= end:
                                # Reached or passed end boundary — stop.
                                break
                            bars.append({**bar, "_ts": ts})
                    finally:
                        # Always tear down replay even on partial success (T-06-03-02).
                        # CR-04: wrap with timeout so an unresponsive TV Desktop cannot
                        # hang the finally block indefinitely.
                        try:
                            await asyncio.wait_for(
                                session.call_tool("replay_stop", {}),
                                timeout=_REPLAY_STEP_TIMEOUT,
                            )
                        except asyncio.TimeoutError:
                            _log.warning("tv_replay.replay_stop_timeout")

        except DataSourceUnavailable:
            raise
        except Exception as e:
            await self._publish_degraded(
                f"tv_replay transport: {type(e).__name__}: {e}"
            )
            raise DataSourceUnavailable(f"tv_replay transport: {e}") from e

        if not bars:
            return pd.DataFrame(columns=empty_columns)

        df = pd.DataFrame(
            {
                "symbol": [symbol] * len(bars),
                "timeframe": [timeframe] * len(bars),
                "ts_utc": [b["_ts"] for b in bars],
                "open": [float(b["open"]) for b in bars],
                "high": [float(b["high"]) for b in bars],
                "low": [float(b["low"]) for b in bars],
                "close": [float(b["close"]) for b in bars],
                "volume": [int(b.get("volume") or 0) for b in bars],
                "provider": [self.name] * len(bars),
            }
        )
        return df.sort_values("ts_utc").reset_index(drop=True)

    async def subscribe_bars(  # type: ignore[override]
        self,
        symbol: str,
        timeframe: str,
    ) -> AsyncIterator[Bar]:
        """Not implemented in v1 — replay is fetch-only.

        Phase 7 streaming will implement live subscription backed by a
        dedicated supervised session. Callers that need live streaming should
        use TradingViewDataSource.subscribe_bars() instead.

        Raises:
            NotImplementedError: always. The coroutine signature satisfies
                the DataSource protocol so static type-checkers are satisfied;
                the NotImplementedError communicates the runtime limitation.
        """
        raise NotImplementedError(
            "TVReplayDataSource is fetch-only in v1; "
            "subscribe semantics require Phase 7 streaming. "
            "Use TradingViewDataSource for live polling."
        )
        # Dead code below satisfies the AsyncIterator return annotation.
        # inspect.iscoroutinefunction returns True for `async def` regardless.
        return  # type: ignore[return-value]
