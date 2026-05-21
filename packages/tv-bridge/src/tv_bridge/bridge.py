"""TVBridge — long-lived supervised MCP stdio client for TradingView Desktop (TV-01).

Phase 6 Wave 2 scope (Plan 06-02):
    Full supervisor loop with capped exponential-backoff reconnect, bus
    subscriber tasks (TOPIC_SIGNALS, TOPIC_FILLS), fire-and-forget safe-draw
    orchestration, 200-shape cap enforcement, overlay registry writes, and
    focus/create_alert/delete_alert helper methods.

Plan 06-01 contributions (preserved):
    Constructor, call_tool(), _server_params(), _parse_tool_payload(),
    _publish_degraded(), start()/stop() lifecycle, module-level constants.

Single-writer convention (from DuckDBStore):
    TVBridge receives a DuckDBStore reference via constructor injection and
    calls store methods directly. It NEVER opens its own DuckDB connection.

Security notes:
    T-06-01-02 / T-06-02-04: MCP subprocess stderr goes to sys.stderr (the
    default). io.StringIO cannot be used on Windows (Popen requires a real fd).
    Plan 04 may surface a sanitized last-error string via a temp-file or pipe.
    T-06-02-02 (shape cap race): count_active_overlays() check is inside
    ``async with self._draw_semaphore:`` so at most 3 racing tasks can
    over-count by 2. Documented as accepted residual race.
    T-06-02-03 (injection via signal data): all numeric fields pass through
    float()/int() in shapes.py; text fields capped to 64 chars.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import structlog
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from trading_core.config import Settings
from trading_core.events import (
    TOPIC_DEGRADED_STATE,
    TOPIC_FILLS,
    TOPIC_SIGNALS,
    DegradedStateEvent,
    EventBus,
)
from trading_core.storage.duckdb_store import DuckDBStore
from trading_core.storage.runs import new_run_id

from tv_bridge.shapes import (
    entry_arrow_args,
    orb_box_args,
    stop_line_args,
    target_line_args,
)

_log = structlog.get_logger(__name__)

# Eastern timezone for date calculations
_ET = ZoneInfo("America/New_York")

# WR-06: fallback used only when mcp_server_path kwarg is explicitly passed.
# Production code reads settings.tv_mcp_server_path (set in config/system.yaml
# or TV_MCP_SERVER_PATH env var) via the constructor default below.
_DEFAULT_MCP_SERVER_PATH = Path(r"C:\Users\Admin\tradingview-mcp-jackson")

_SYMBOL_MAP: dict[str, str] = {
    "ES": "CME_MINI:ES1!",
    "MES": "CME_MINI:MES1!",
    "SPY": "AMEX:SPY",
}

_INIT_TIMEOUT_SECONDS = 15.0
_TOOL_TIMEOUT_SECONDS = 12.0

# Allowlist used by focus() validation (symbol injected into MCP chart_set_symbol).
# Declare here as the one-place-of-truth (T-06-01 / RESEARCH.md §Known Threat Patterns).
# Also declared in packages/api/src/api/routes/tv.py for the REST layer.
_SYMBOL_ALLOWLIST: frozenset[str] = frozenset({"ES", "MES", "SPY"})


class TVBridge:
    """Supervised long-lived MCP stdio client.

    Lifecycle:
        bridge = TVBridge(store=store, bus=bus, settings=settings)
        await bridge.start()   # spawns supervisor + subscriber tasks
        # ... operate ...
        await bridge.stop()    # cancels all tasks, clears session

    Thread/task safety:
        ``_session`` is guarded by ``_session_lock`` — always copy the
        reference under the lock, then release before using the copy.
        Never hold ``_session_lock`` across an ``await`` that may block
        (RESEARCH.md Pitfall 3).
    """

    name = "tv_bridge"

    # Reconnect backoff schedule (seconds). Supervisor loop iterates
    # through this list; capped at the last value (30s) on repeated failures.
    _BACKOFF_SECONDS: list[int] = [1, 2, 4, 8, 16, 30]

    def __init__(
        self,
        *,
        store: DuckDBStore,
        bus: EventBus,
        settings: Settings,
        mcp_server_path: Path | None = None,
    ) -> None:
        """Construct TVBridge with injected dependencies.

        Does NOT spawn a subprocess — construction is pure attribute setup.
        Call ``await start()`` to begin the supervisor loop.
        """
        self._store = store
        self._bus = bus
        self._settings = settings
        # WR-06: prefer settings.tv_mcp_server_path so the path is not hardcoded.
        # mcp_server_path kwarg overrides (used in tests / dev).
        self._mcp_server_path: Path = mcp_server_path or Path(settings.tv_mcp_server_path)

        # Session state — guarded by _session_lock.
        self._session: ClientSession | None = None
        self._session_lock: asyncio.Lock = asyncio.Lock()

        # Semaphore limits concurrent draw_shape calls (single-threaded Node.js
        # MCP server; RESEARCH.md §Pitfall 5 for cap-race analysis).
        self._draw_semaphore: asyncio.Semaphore = asyncio.Semaphore(3)

        # Capture MCP server stderr in-memory for debugging (T-06-02-04).
        # Stderr from the MCP subprocess goes to sys.stderr (the default).
        # io.StringIO is not usable here on Windows — Popen requires a real fd.

        # Task handles — set by start(), cancelled by stop().
        self._supervisor_task: asyncio.Task[None] | None = None
        self._sig_task: asyncio.Task[None] | None = None
        self._fill_task: asyncio.Task[None] | None = None

    # ---- properties -------------------------------------------------------

    @property
    def is_connected(self) -> bool:
        """True when a live ClientSession is held."""
        return self._session is not None

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

        Returns an empty dict on any parse failure — callers must handle
        missing keys gracefully.
        """
        import json  # noqa: PLC0415 (lazy import fine here)

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

    async def _publish_degraded(self, reason: str) -> None:
        """Emit ``DegradedStateEvent`` on the bus. Never raises."""
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

    # ---- MCP tool call surface -------------------------------------------

    async def call_tool(
        self, tool: str, args: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Safely call an MCP tool on the current session.

        Returns:
            Parsed response dict, or None on any failure (no session, timeout,
            or exception). NEVER re-raises — TV failure must be non-blocking
            to the signal pipeline (TV-06).

        Pattern (RESEARCH.md Pattern 3):
            1. Acquire lock, copy session reference, release lock.
            2. If no session: log warning, return None.
            3. Call tool with a hard timeout.
            4. On any error: log, return None.
        """
        async with self._session_lock:
            session = self._session
        if session is None:
            _log.warning("tv_bridge.no_session", tool=tool)
            return None
        try:
            result = await asyncio.wait_for(
                session.call_tool(tool, args),
                timeout=_TOOL_TIMEOUT_SECONDS,
            )
            return self._parse_tool_payload(result)
        except asyncio.TimeoutError:
            _log.warning("tv_bridge.tool_timeout", tool=tool)
            return None
        except Exception:
            _log.exception("tv_bridge.tool_error", tool=tool)
            return None

    # ---- supervisor lifecycle --------------------------------------------

    async def _supervisor_loop(self) -> None:
        """Supervisor loop — manages the long-lived MCP session lifetime.

        Reconnect pattern (RESEARCH.md Pattern 1):
        - Connects via stdio_client + ClientSession.
        - Health-gate: calls tv_health_check; raises on api_available=False.
        - On success: stores session, logs connected, holds via asyncio.Future().
        - On any failure: clears session, publishes DegradedStateEvent,
          sleeps with capped exponential backoff, increments attempt counter.
        - On CancelledError: exits cleanly.

        The asyncio.Future() idiom holds the context manager alive without
        consuming CPU. When the underlying stdio process dies, anyio's
        task group propagates the exception, breaking out of the async with
        block and triggering the retry (RESEARCH.md §A5 assumption).
        """
        attempt = 0
        while True:
            try:
                async with stdio_client(
                    self._server_params()
                ) as (r, w):
                    async with ClientSession(r, w) as session:
                        await asyncio.wait_for(
                            session.initialize(),
                            timeout=_INIT_TIMEOUT_SECONDS,
                        )
                        # Health gate: must have api_available == True
                        health_result = await session.call_tool("tv_health_check", {})
                        health = self._parse_tool_payload(health_result)
                        if not health.get("api_available"):
                            raise RuntimeError(
                                f"health_check failed: {health!r}"
                            )
                        # Session healthy — store it and reset attempt counter
                        async with self._session_lock:
                            self._session = session
                        attempt = 0
                        _log.info("tv_bridge.connected")
                        # Hold context manager alive until the session breaks
                        await asyncio.Future()  # suspended until exception
            except asyncio.CancelledError:
                # WR-03: clear session before exiting so is_connected returns False.
                async with self._session_lock:
                    self._session = None
                return
            except Exception as exc:
                # Clear session on any disconnect/error
                async with self._session_lock:
                    self._session = None
                await self._publish_degraded(
                    f"tv_bridge disconnect: {type(exc).__name__}: {exc}"
                )
                backoff = self._BACKOFF_SECONDS[
                    min(attempt, len(self._BACKOFF_SECONDS) - 1)
                ]
                _log.warning(
                    "tv_bridge.reconnecting",
                    attempt=attempt,
                    backoff=backoff,
                    error=repr(exc),
                )
                await asyncio.sleep(backoff)
                attempt += 1

    # ---- bus subscriber tasks -------------------------------------------

    async def _subscribe_signals(self) -> None:
        """Subscribe to TOPIC_SIGNALS and fire-and-forget draw tasks per event.

        The async-for loop returns immediately per event by using
        asyncio.create_task — bus dispatch is NEVER blocked (TV-06,
        RESEARCH.md Anti-Pattern 4).
        """
        async with self._bus.subscribe(TOPIC_SIGNALS) as sub:
            async for event in sub:
                asyncio.create_task(
                    self._safe_draw_signal(event),
                    name=f"tv_draw_signal_{getattr(event, 'signal_id', 'unknown')}",
                )

    async def _subscribe_fills(self) -> None:
        """Subscribe to TOPIC_FILLS and fire-and-forget draw tasks per event.

        Wave 2 minimal: logs only. Plan 04 may extend to update entry arrow
        position on fill confirmation.
        """
        async with self._bus.subscribe(TOPIC_FILLS) as sub:
            async for event in sub:
                asyncio.create_task(
                    self._safe_draw_fill(event),
                    name=f"tv_draw_fill_{getattr(event, 'fill_id', 'unknown')}",
                )

    # ---- safe draw orchestration ----------------------------------------

    async def _safe_draw_signal(self, signal: Any) -> None:
        """Draw all shapes for a signal with timeout + error suppression.

        Shape sequence: orb_box (idempotent per session), entry_arrow,
        stop_line, target_line.

        200-shape cap (T-06-02-02): count check is INSIDE the semaphore
        block so at most 3 racing tasks can over-count by 2. This residual
        race is accepted for v1 (201 shapes is non-catastrophic).

        Timeout (T-06-02-08): 5s total budget for all 4 draw calls inside
        the semaphore. asyncio.create_task per event ensures the bus
        subscriber's async-for loop returns in microseconds.

        Never re-raises — TV failure must be non-blocking to the pipeline.
        """
        import json  # noqa: PLC0415

        signal_id = getattr(signal, "signal_id", "unknown")
        try:
            async with asyncio.timeout(5.0):
                # T-06-02-02: cap check inside semaphore to limit race window
                async with self._draw_semaphore:
                    if self._store.count_active_overlays() >= 200:
                        _log.warning(
                            "tv_bridge.draw_refused",
                            reason="shape_cap",
                            signal_id=signal_id,
                        )
                        self._store.write_audit_event(
                            event_id=new_run_id(),
                            ts_utc=datetime.now(timezone.utc),
                            topic="tv_draw_refused",
                            entity_id=signal_id,
                            reason_code="shape_cap",
                            payload_json=json.dumps(
                                {"signal_id": signal_id, "cap": 200}
                            ),
                        )
                        return
                    await self._draw_orb_box_if_new(signal)
                    await self._draw_entry_arrow(signal)
                    await self._draw_stop_line(signal)
                    await self._draw_target_line(signal)
        except asyncio.TimeoutError:
            _log.warning("tv_bridge.draw_timeout", signal_id=signal_id)
            try:
                import json as _json  # noqa: PLC0415

                self._store.write_audit_event(
                    event_id=new_run_id(),
                    ts_utc=datetime.now(timezone.utc),
                    topic="tv_draw_timeout",
                    entity_id=signal_id,
                    reason_code="draw_timeout",
                    payload_json=_json.dumps({"signal_id": signal_id}),
                )
            except Exception:
                pass
        except Exception:
            _log.exception("tv_bridge.draw_error", signal_id=signal_id)
            try:
                import json as _json  # noqa: PLC0415

                self._store.write_audit_event(
                    event_id=new_run_id(),
                    ts_utc=datetime.now(timezone.utc),
                    topic="tv_draw_error",
                    entity_id=signal_id,
                    reason_code="draw_error",
                    payload_json=_json.dumps({"signal_id": signal_id}),
                )
            except Exception:
                pass

    async def _safe_draw_fill(self, fill: Any) -> None:
        """Wave 2 minimal fill handler — log only.

        Plan 04 may extend this to update the entry arrow's price level
        to match the actual fill price when different from signal.entry.
        """
        fill_id = getattr(fill, "fill_id", "unknown")
        _log.debug("tv_bridge.fill_received", fill_id=fill_id)

    # ---- per-shape draw helpers -----------------------------------------

    async def _draw_entry_arrow(self, signal: Any) -> None:
        """Draw a horizontal_line entry marker for the signal."""
        payload = entry_arrow_args(
            side=str(signal.side),
            entry_price=float(signal.entry),
            signal_id=str(signal.signal_id),
        )
        response = await self.call_tool("draw_shape", payload)
        if response is None:
            return
        # entity_id field confirmed from tradingview-mcp-jackson/src/core/drawing.js line 34
        # See 06-RESEARCH.md §Wave 0 Verification
        shape_id = response.get("entity_id", "")
        if not shape_id:
            _log.warning("tv_bridge.missing_entity_id", shape_kind="entry_arrow")
            return
        trading_date = signal.ts_utc.astimezone(_ET).date()
        self._record_overlay(
            overlay_id=new_run_id(),
            strategy_id=str(signal.strategy_id),
            signal_id=str(signal.signal_id),
            shape_kind="entry_arrow",
            shape_id=shape_id,
            trading_date=trading_date,
        )

    async def _draw_stop_line(self, signal: Any) -> None:
        """Draw a dashed horizontal_line stop marker for the signal."""
        payload = stop_line_args(
            stop_price=float(signal.stop),
            signal_id=str(signal.signal_id),
        )
        response = await self.call_tool("draw_shape", payload)
        if response is None:
            return
        shape_id = response.get("entity_id", "")
        if not shape_id:
            _log.warning("tv_bridge.missing_entity_id", shape_kind="stop_line")
            return
        trading_date = signal.ts_utc.astimezone(_ET).date()
        self._record_overlay(
            overlay_id=new_run_id(),
            strategy_id=str(signal.strategy_id),
            signal_id=str(signal.signal_id),
            shape_kind="stop_line",
            shape_id=shape_id,
            trading_date=trading_date,
        )

    async def _draw_target_line(self, signal: Any) -> None:
        """Draw a dashed horizontal_line target marker for the signal."""
        payload = target_line_args(
            target_price=float(signal.target),
            signal_id=str(signal.signal_id),
        )
        response = await self.call_tool("draw_shape", payload)
        if response is None:
            return
        shape_id = response.get("entity_id", "")
        if not shape_id:
            _log.warning("tv_bridge.missing_entity_id", shape_kind="target_line")
            return
        trading_date = signal.ts_utc.astimezone(_ET).date()
        self._record_overlay(
            overlay_id=new_run_id(),
            strategy_id=str(signal.strategy_id),
            signal_id=str(signal.signal_id),
            shape_kind="target_line",
            shape_id=shape_id,
            trading_date=trading_date,
        )

    async def _draw_orb_box_if_new(self, signal: Any) -> None:
        """Draw the ORB rectangle if one does not already exist for this session.

        Idempotent: skips draw if a tv_overlays row with shape_kind='orb_box'
        already exists for the same trading_date + strategy_id. This prevents
        duplicate ORB boxes when multiple signals fire in the same session.

        Wave 2 minimal: uses signal.ts_utc for a stub orb_high/orb_low
        (0/0 to produce a valid but placeholder box). Plan 04 will wire in
        the real ORB high/low from the strategy context.
        """
        import json  # noqa: PLC0415

        trading_date = signal.ts_utc.astimezone(_ET).date()
        strategy_id = str(signal.strategy_id)

        # Skip if ORB box already drawn for this session (uses public store method — CR-02)
        try:
            if self._store.is_orb_box_drawn(trading_date, strategy_id):
                return
        except Exception:
            pass  # If query fails, proceed to draw anyway

        # Wave 2 stub ORB box: uses placeholder timestamps
        # Plan 04 will wire in real session_open_ts and orb_end_ts from strategy context
        ts_epoch = int(signal.ts_utc.timestamp())
        payload = orb_box_args(
            orb_high=float(signal.entry) * 1.001,  # stub: 0.1% above entry
            orb_low=float(signal.entry) * 0.999,   # stub: 0.1% below entry
            session_open_ts=ts_epoch - 900,         # stub: 15 min before signal
            orb_end_ts=ts_epoch,
        )
        response = await self.call_tool("draw_shape", payload)
        if response is None:
            return
        shape_id = response.get("entity_id", "")
        if not shape_id:
            _log.warning("tv_bridge.missing_entity_id", shape_kind="orb_box")
            return
        self._record_overlay(
            overlay_id=new_run_id(),
            strategy_id=strategy_id,
            signal_id=str(signal.signal_id),
            shape_kind="orb_box",
            shape_id=shape_id,
            trading_date=trading_date,
        )

    def _record_overlay(
        self,
        *,
        overlay_id: str,
        strategy_id: str,
        signal_id: str,
        shape_kind: str,
        shape_id: str,
        trading_date: Any,
    ) -> None:
        """Persist a tv_overlays row via DuckDBStore.

        Synchronous call — DuckDB writes are serialized by _LockedConn.
        """
        self._store.write_tv_overlay(
            overlay_id=overlay_id,
            strategy_id=strategy_id,
            signal_id=signal_id,
            shape_kind=shape_kind,
            shape_id=shape_id,
            trading_date=trading_date,
        )

    # ---- focus / alert methods ------------------------------------------

    async def focus(self, symbol: str, date: str, timeframe: str = "1") -> None:
        """Drive the TradingView chart to a specific symbol, date, and timeframe.

        TV-05 ordered sequence (RESEARCH.md Pattern — TV-05 contract):
            1. chart_set_symbol  (up to 11s cold)
            2. chart_set_timeframe (~1.5s)
            3. chart_scroll_to_date (~0.5s)

        This method awaits all three calls sequentially. It is called via
        asyncio.create_task from the POST /tv/focus route so the HTTP
        response returns immediately (202 Accepted) without waiting.

        Args:
            symbol: Internal symbol string (must be in _SYMBOL_ALLOWLIST).
            date: ISO date string "YYYY-MM-DD" (ET).
            timeframe: TV timeframe string ("1", "5", "15"). Default "1".
        """
        tv_symbol = _SYMBOL_MAP.get(symbol, symbol)
        await self.call_tool("chart_set_symbol", {"symbol": tv_symbol})
        await self.call_tool("chart_set_timeframe", {"timeframe": timeframe})
        await self.call_tool(
            "chart_scroll_to_date", {"date": f"{date}T09:30:00-05:00"}
        )
        _log.info("tv_bridge.focus_complete", symbol=symbol, date=date)

    async def create_alert(self, condition: str, message: str) -> str | None:
        """Create a TradingView alert via alert_create MCP tool.

        Args:
            condition: Alert condition string (max 256 chars via Pydantic validation).
            message: Alert message text (max 256 chars via Pydantic validation).

        Returns:
            tv_alert_id string from alert_create response, or None on failure.
        """
        response = await self.call_tool(
            "alert_create",
            {"condition": str(condition)[:256], "message": str(message)[:256]},
        )
        if response is None:
            return None
        tv_alert_id = response.get("alert_id") or response.get("id")
        if not tv_alert_id:
            _log.warning("tv_bridge.missing_alert_id", response=repr(response))
            return None
        return str(tv_alert_id)

    async def delete_alert(self, tv_alert_id: str) -> None:
        """Delete a TradingView alert via alert_delete MCP tool.

        Args:
            tv_alert_id: The alert ID returned by alert_create (stored in tv_alerts).
        """
        await self.call_tool("alert_delete", {"alert_id": str(tv_alert_id)})

    # ---- lifecycle -------------------------------------------------------

    async def start(self) -> None:
        """Spawn supervisor + bus subscriber tasks.

        Creates three asyncio Tasks:
          - tv_bridge.supervisor: manages the long-lived MCP session
          - tv_bridge.sig_sub: subscribes to TOPIC_SIGNALS
          - tv_bridge.fill_sub: subscribes to TOPIC_FILLS

        Idempotent: if already started, a second call creates duplicate tasks.
        Guard against double-start in callers if needed.
        """
        self._supervisor_task = asyncio.create_task(
            self._supervisor_loop(),
            name="tv_bridge.supervisor",
        )
        self._sig_task = asyncio.create_task(
            self._subscribe_signals(),
            name="tv_bridge.sig_sub",
        )
        self._fill_task = asyncio.create_task(
            self._subscribe_fills(),
            name="tv_bridge.fill_sub",
        )

    async def stop(self) -> None:
        """Cancel and await all tasks; clear the session reference."""
        for task in (self._supervisor_task, self._sig_task, self._fill_task):
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        self._supervisor_task = None
        self._sig_task = None
        self._fill_task = None

        async with self._session_lock:
            self._session = None
