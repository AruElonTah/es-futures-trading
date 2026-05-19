"""TVBridge — long-lived supervised MCP stdio client for TradingView Desktop (TV-01).

Phase 6 Wave 1 scope (Plan 06-01):
    Skeleton only. Constructor, start(), stop(), call_tool() are fully wired.
    The supervisor loop body is a stub (``await asyncio.Future()``) — Plan 02
    (Wave 2) replaces it with the full reconnect loop and health-gate logic.

Single-writer convention (from DuckDBStore):
    TVBridge receives a DuckDBStore reference via constructor injection and
    calls store methods directly. It NEVER opens its own DuckDB connection.

Security note (T-06-01-02):
    ``_stderr_capture`` (io.StringIO) is in-memory only and is never written
    to disk in Wave 1. Plan 02 must NOT write captured stderr to audit_log
    without sanitization — MCP server stderr may include price data or
    session tokens.
"""

from __future__ import annotations

import asyncio
import io
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from trading_core.config import Settings
from trading_core.events import (
    TOPIC_DEGRADED_STATE,
    DegradedStateEvent,
    EventBus,
)
from trading_core.storage.duckdb_store import DuckDBStore

_log = structlog.get_logger(__name__)

# Mirror tradingview.py module-level constants so bridge.py is the one-place-of-truth
# for Phase 6 TV connection parameters.
_DEFAULT_MCP_SERVER_PATH = Path(r"C:\Users\Admin\tradingview-mcp-jackson")

_SYMBOL_MAP: dict[str, str] = {
    "ES": "CME_MINI:ES1!",
    "MES": "CME_MINI:MES1!",
}

_INIT_TIMEOUT_SECONDS = 15.0
_TOOL_TIMEOUT_SECONDS = 12.0

# Allowlist used by Plan 02's focus() validation (symbol injected into MCP chart_set_symbol).
# Declare here as the one-place-of-truth (T-06-01 / RESEARCH.md §Known Threat Patterns).
_SYMBOL_ALLOWLIST: frozenset[str] = frozenset({"ES", "MES", "SPY"})


class TVBridge:
    """Supervised long-lived MCP stdio client.

    Lifecycle:
        bridge = TVBridge(store=store, bus=bus, settings=settings)
        await bridge.start()   # spawns supervisor task
        # ... operate ...
        await bridge.stop()    # cancels supervisor task, clears session

    Thread/task safety:
        ``_session`` is guarded by ``_session_lock`` — always copy the
        reference under the lock, then release before using the copy.
        Never hold ``_session_lock`` across an ``await`` that may block.
    """

    name = "tv_bridge"

    # Reconnect backoff schedule (seconds). Plan 02 supervisor loop iterates
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
        self._mcp_server_path: Path = mcp_server_path or _DEFAULT_MCP_SERVER_PATH

        # Session state — guarded by _session_lock.
        self._session: ClientSession | None = None
        self._session_lock: asyncio.Lock = asyncio.Lock()

        # Semaphore limits concurrent draw_shape calls (single-threaded Node.js
        # MCP server; see RESEARCH.md §Pitfall 5 for cap-race analysis).
        self._draw_semaphore: asyncio.Semaphore = asyncio.Semaphore(3)

        # Capture MCP server stderr in-memory for debugging (T-06-01-02).
        self._stderr_capture: io.StringIO = io.StringIO()

        # Supervisor task handle — set by start(), cancelled by stop().
        self._supervisor_task: asyncio.Task[None] | None = None

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
        """Supervisor loop stub — Plan 02 (Wave 2) replaces this body.

        Wave 1 provides the minimal implementation that makes start()/stop()
        safe and test_start_creates_supervisor_task pass. The stub suspends
        indefinitely until cancelled, which is the correct Wave 1 behaviour:
        no subprocess is spawned, no reconnect is attempted.
        """
        # Wave 2 (Plan 02) implements the supervisor loop; this stub keeps
        # start()/stop() safe without spawning any Node.js subprocess.
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            return

    async def start(self) -> None:
        """Spawn the supervisor task.

        Idempotent: calling start() twice creates a second task (Plan 02
        should guard against double-start if needed; Wave 1 does not).
        """
        self._supervisor_task = asyncio.create_task(
            self._supervisor_loop(),
            name="tv_bridge.supervisor",
        )

    async def stop(self) -> None:
        """Cancel and await the supervisor task; clear the session reference."""
        if self._supervisor_task is not None:
            self._supervisor_task.cancel()
            try:
                await self._supervisor_task
            except asyncio.CancelledError:
                pass
            self._supervisor_task = None
        async with self._session_lock:
            self._session = None
