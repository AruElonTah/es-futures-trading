"""Phase 0 spike — TradingView MCP happy-path smoke test.

PHASE 0 SPIKE — DO NOT IMPORT FROM PRODUCTION CODE.

Per RESEARCH.md sections:
- "MCP Python SDK pattern (canonical)"
- "Critical implementation notes" (timeouts, allowlist, restore-on-exit)
- "Local server confirmed shape" (CME_MINI:ES1!, timeframe '1')
- "The 4 probe calls" downstream
"""

import asyncio
import json
import os
import sys
from contextlib import AsyncExitStack
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Reconfigure stdout / stderr to UTF-8 BEFORE any prints. On Windows the
# default piped-stdout encoding is cp1252, which raises UnicodeEncodeError on
# non-ASCII characters (e.g., em dashes in log lines) and breaks background runs.
for _stream_attr in ("stdout", "stderr"):
    _stream = getattr(sys, _stream_attr, None)
    if _stream is not None and hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

MCP_SERVER_PATH = Path(r"C:\Users\Admin\tradingview-mcp-jackson\src\server.js")
MCP_SERVER_CWD = MCP_SERVER_PATH.parent.parent  # C:\Users\Admin\tradingview-mcp-jackson\

ES_SYMBOL = "CME_MINI:ES1!"
ES_TIMEFRAME = "1"  # TV uses minute counts as strings for intraday
INIT_TIMEOUT_SECONDS = 15.0
OHLCV_COUNT = 390  # one RTH session

TRANSCRIPT_PATH = Path(".planning/research/spike-0/tv-mcp-transcript.log")
STDERR_PATH = Path(".planning/research/spike-0/tv-mcp-stderr.log")
TOOLS_PATH = Path(".planning/research/spike-0/tv-mcp-tools.json")

# Allowlist — every _call() asserts the name is in this set. Hard guard against
# accidentally invoking a destructive tool (RESEARCH.md Threat T-03).
ALLOWED_TOOLS = {
    "tv_health_check",
    "chart_get_state",
    "chart_set_symbol",
    "chart_set_timeframe",
    "chart_scroll_to_date",
    "data_get_ohlcv",
    "quote_get",
}

# REQUIRED tools — these MUST be in list_tools() output or the spike aborts.
REQUIRED_TOOLS = {
    "tv_health_check",
    "chart_set_symbol",
    "chart_set_timeframe",
    "data_get_ohlcv",
}


# --------------------------------------------------------------------------
# Logging helper
# --------------------------------------------------------------------------

def _log(transcript: list[str], line: str) -> None:
    """Append timestamped line to transcript list AND stdout."""
    stamped = f"{datetime.now(timezone.utc).isoformat()} | {line}"
    transcript.append(stamped)
    print(stamped, flush=True)


# --------------------------------------------------------------------------
# Safe tool-call wrapper
# --------------------------------------------------------------------------

async def _call(session: ClientSession, transcript: list[str], name: str, args: dict) -> dict:
    """Allowlist-guarded tool call with structured logging.

    Emits multiple transcript lines per call for forensic recall:
      1. attempt line  (timestamp + tool + args)
      2. summary line  (success + key list)
      3. detail line   (per-tool relevant fields: symbol/bar_count/price/etc.)
      4. error/hint    (only when success is False)

    Returns the parsed JSON payload (or {"_raw": text} if non-JSON).
    """
    assert name in ALLOWED_TOOLS, f"tool {name} not in allowlist"
    _log(transcript, f"call_attempt tool={name} args={args}")
    try:
        result = await session.call_tool(name, args)
    except Exception as e:
        _log(transcript, f"tool={name} args={args} EXCEPTION={type(e).__name__}: {e}")
        return {"_exception": f"{type(e).__name__}: {e}"}

    text = result.content[0].text if result.content else ""
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        payload = {"_raw": text}

    if not isinstance(payload, dict):
        payload = {"_value": payload}

    keys_preview = list(payload.keys())[:6] if isinstance(payload, dict) else []
    _log(
        transcript,
        f"tool={name} args={args} success={payload.get('success')} keys={keys_preview}",
    )

    # Per-tool detail line — pull a few load-bearing fields per call type.
    detail_parts: list[str] = []
    if name == "chart_get_state":
        for k in ("symbol", "resolution", "timeframe", "chartType", "interval"):
            v = payload.get(k)
            if v is not None:
                detail_parts.append(f"{k}={v}")
    elif name == "tv_health_check":
        for k in ("cdp_connected", "target_id", "target_url"):
            v = payload.get(k)
            if v is not None:
                # Truncate target_url to its host+path (it can be very long)
                if k == "target_url" and isinstance(v, str) and len(v) > 100:
                    v = v[:100] + "..."
                detail_parts.append(f"{k}={v}")
    elif name == "chart_set_symbol":
        for k in ("symbol", "chart_ready"):
            v = payload.get(k)
            if v is not None:
                detail_parts.append(f"{k}={v}")
    elif name == "chart_set_timeframe":
        for k in ("timeframe", "chart_ready"):
            v = payload.get(k)
            if v is not None:
                detail_parts.append(f"{k}={v}")
    elif name == "chart_scroll_to_date":
        for k in ("date", "centered_on", "resolution"):
            v = payload.get(k)
            if v is not None:
                detail_parts.append(f"{k}={v}")
    elif name == "data_get_ohlcv":
        for k in ("bar_count", "total_available", "source"):
            v = payload.get(k)
            if v is not None:
                detail_parts.append(f"{k}={v}")
        bars = payload.get("bars") or payload.get("data") or []
        if isinstance(bars, list) and bars:
            first = bars[0]
            last = bars[-1]
            if isinstance(first, dict):
                detail_parts.append(f"first_bar_time={first.get('time') or first.get('datetime')}")
            if isinstance(last, dict):
                detail_parts.append(f"last_bar_time={last.get('time') or last.get('datetime')}")
    elif name == "quote_get":
        for k in ("symbol", "time", "open", "high", "low", "close", "last", "volume"):
            v = payload.get(k)
            if v is not None:
                detail_parts.append(f"{k}={v}")

    if detail_parts:
        _log(transcript, f"  detail tool={name} {' '.join(detail_parts)}")

    if payload.get("success") is False:
        err = payload.get("error")
        hint = payload.get("hint")
        if err is not None:
            _log(transcript, f"  error: {err}")
        if hint is not None:
            _log(transcript, f"  hint: {hint}")
    return payload


# --------------------------------------------------------------------------
# Quote staleness check (defense-in-depth — operator confirmed real-time CME)
# --------------------------------------------------------------------------

def _parse_quote_timestamp(quote: dict) -> datetime | None:
    """Try the common timestamp fields TV's quote_get may use."""
    for k in ("timestamp", "time", "datetime", "last_time"):
        v = quote.get(k)
        if v is None:
            continue
        if isinstance(v, (int, float)):
            # Unix epoch seconds (or millis — heuristic for 13-digit values)
            ts = v / 1000.0 if v > 10_000_000_000 else float(v)
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        if isinstance(v, str):
            try:
                # Try ISO 8601 first
                return datetime.fromisoformat(v.replace("Z", "+00:00"))
            except ValueError:
                continue
    return None


def _is_rth_utc(now_utc: datetime) -> bool:
    """Coarse RTH check (13:30–20:00 UTC). DST nuance is intentionally ignored
    for the spike — the goal is a sanity check, not a calendar engine."""
    minutes = now_utc.hour * 60 + now_utc.minute
    return 13 * 60 + 30 <= minutes < 20 * 60


def _check_quote_staleness(transcript: list[str], quote: dict) -> None:
    ts = _parse_quote_timestamp(quote)
    if ts is None:
        _log(transcript, "quote_staleness_seconds=unknown (timestamp not parsed)")
        return
    now = datetime.now(timezone.utc)
    staleness = (now - ts).total_seconds()
    _log(transcript, f"quote_staleness_seconds={staleness:.1f}")
    if _is_rth_utc(now):
        if staleness > 5.0:
            _log(
                transcript,
                f"WARNING quote_staleness_seconds={staleness:.1f} > 5.0 during RTH "
                "— verify TV CME real-time subscription",
            )
    else:
        _log(transcript, "quote staleness check skipped (non-RTH window)")


# --------------------------------------------------------------------------
# Main async flow
# --------------------------------------------------------------------------

async def main() -> int:
    # Resolve artifact paths to absolute BEFORE we chdir into the MCP server
    # directory below — otherwise relative writes land in the server's tree.
    global TRANSCRIPT_PATH, STDERR_PATH, TOOLS_PATH

    # Pre-flight: server file must exist.
    if not MCP_SERVER_PATH.exists():
        print(f"FATAL: MCP server not found at {MCP_SERVER_PATH}", file=sys.stderr)
        return 1
    for p in (TRANSCRIPT_PATH, STDERR_PATH, TOOLS_PATH):
        p.parent.mkdir(parents=True, exist_ok=True)
    TRANSCRIPT_PATH = TRANSCRIPT_PATH.resolve()
    STDERR_PATH = STDERR_PATH.resolve()
    TOOLS_PATH = TOOLS_PATH.resolve()

    transcript: list[str] = []
    _log(transcript, f"phase=0 spike=tv_mcp_smoke server={MCP_SERVER_PATH}")
    _log(transcript, f"python={sys.version.split()[0]} cwd={Path.cwd()}")

    # Safety belt: server uses ES modules with absolute imports per package.json
    # type=module; cwd should not matter, but set it to the server dir anyway.
    os.chdir(MCP_SERVER_CWD)

    env = os.environ.copy()
    env["NODE_OPTIONS"] = "--no-warnings"

    server_params = StdioServerParameters(
        command="node",
        args=[str(MCP_SERVER_PATH)],
        env=env,
    )

    # Restore-on-exit state captured after first chart_get_state call.
    initial_symbol: str | None = None
    initial_timeframe: str | None = None
    exit_code = 0

    try:
        async with AsyncExitStack() as stack:
            try:
                stdio_transport = await stack.enter_async_context(
                    stdio_client(server_params)
                )
            except Exception as e:
                _log(transcript, f"FATAL stdio_client failed: {type(e).__name__}: {e}")
                _write_transcript_and_stderr(transcript)
                return 2

            read, write = stdio_transport
            session = await stack.enter_async_context(ClientSession(read, write))

            try:
                await asyncio.wait_for(session.initialize(), timeout=INIT_TIMEOUT_SECONDS)
            except asyncio.TimeoutError:
                _log(transcript, "INIT TIMEOUT — is TV Desktop running?")
                _write_transcript_and_stderr(transcript)
                return 2

            # 1. List tools — verify the 4 REQUIRED tools are present.
            tools_response = await session.list_tools()
            tool_names = sorted(t.name for t in tools_response.tools)
            tool_block = {
                "captured_at_utc": datetime.now(timezone.utc).isoformat(),
                "tool_count": len(tool_names),
                "tool_names": tool_names,
                "required_tools_present": {t: (t in tool_names) for t in sorted(REQUIRED_TOOLS)},
                "all_required_present": all(t in tool_names for t in REQUIRED_TOOLS),
            }
            TOOLS_PATH.write_text(json.dumps(tool_block, indent=2), encoding="utf-8")
            _log(transcript, f"tool_count={tool_block['tool_count']} all_required_present={tool_block['all_required_present']}")
            if not tool_block["all_required_present"]:
                missing = [t for t in REQUIRED_TOOLS if t not in tool_names]
                _log(transcript, f"REQUIRED tools missing: {missing}")
                _write_transcript_and_stderr(transcript)
                return 3

            # 2. Capture initial chart state for restore-on-exit.
            initial_state = await _call(session, transcript, "chart_get_state", {})
            initial_symbol = initial_state.get("symbol") or initial_state.get("ticker")
            initial_timeframe = initial_state.get("timeframe") or initial_state.get("resolution") or initial_state.get("interval")
            _log(transcript, f"initial_symbol={initial_symbol} initial_timeframe={initial_timeframe}")

            # 3. Health check — abort if unhealthy.
            health = await _call(session, transcript, "tv_health_check", {})
            if health.get("success") is not True:
                _log(transcript, "HEALTH CHECK FAILED — aborting; restart TV Desktop and re-run")
                exit_code = 4
                return exit_code

            # 4. Happy-path sequence.
            await _call(session, transcript, "chart_set_symbol", {"symbol": ES_SYMBOL})
            await _call(session, transcript, "chart_set_timeframe", {"timeframe": ES_TIMEFRAME})

            # 5. Scroll to previous RTH close (yesterday 20:00 UTC = 16:00 ET RTH close).
            target = (
                datetime.now(timezone.utc) - timedelta(days=1)
            ).replace(hour=20, minute=0, second=0, microsecond=0).isoformat()
            await _call(session, transcript, "chart_scroll_to_date", {"date": target})

            await asyncio.sleep(1.5)  # let TV render before reading bars

            # 6. Read OHLCV bars.
            ohlcv = await _call(
                session,
                transcript,
                "data_get_ohlcv",
                {"count": OHLCV_COUNT, "summary": False},
            )
            bars: list = []
            for key in ("bars", "data", "ohlcv", "values"):
                v = ohlcv.get(key) if isinstance(ohlcv, dict) else None
                if isinstance(v, list):
                    bars = v
                    break
            bar_count = len(bars)
            _log(transcript, f"bar_count={bar_count}")

            # Forensic sample: log first 5 and last 5 bars so Plan 3 can verify
            # the bar series is non-empty and well-formed.
            def _bar_str(b: dict) -> str:
                if not isinstance(b, dict):
                    return str(b)
                fields = []
                for k in ("time", "datetime", "open", "high", "low", "close", "volume"):
                    if k in b:
                        fields.append(f"{k}={b[k]}")
                return " ".join(fields)

            for i, b in enumerate(bars[:5]):
                _log(transcript, f"  bar[{i}] {_bar_str(b)}")
            if len(bars) > 10:
                _log(transcript, f"  ... ({len(bars) - 10} bars elided) ...")
            for i, b in enumerate(bars[-5:] if len(bars) > 5 else []):
                idx = len(bars) - 5 + i
                _log(transcript, f"  bar[{idx}] {_bar_str(b)}")

            # 7. Quote for real-time staleness check.
            quote = await _call(session, transcript, "quote_get", {"symbol": ES_SYMBOL})
            _check_quote_staleness(transcript, quote)

            # 8. End-of-happy-path summary block — forensic recall anchor.
            _log(transcript, "----- end of happy path -----")
            _log(transcript, f"summary calls_made=7 tool_count_observed={len(tool_names)} all_required_present=True")
            _log(transcript, f"summary symbol_under_test={ES_SYMBOL} timeframe={ES_TIMEFRAME} ohlcv_bars={bar_count}")
            _log(transcript, f"summary initial_symbol={initial_symbol} initial_timeframe={initial_timeframe}")
            # Spot-list a few tools that ARE present beyond the 4 required —
            # gives Plan 3 evidence of breadth without bloating the artifact.
            extras_present = [
                t for t in (
                    "tv_health_check", "chart_get_state", "chart_set_symbol",
                    "chart_set_timeframe", "chart_scroll_to_date",
                    "data_get_ohlcv", "quote_get",
                    "draw_shape", "alert_create", "replay_start",
                    "pine_smart_compile", "symbol_search", "watchlist_get",
                )
                if t in tool_names
            ]
            _log(transcript, f"summary key_tools_present={extras_present}")

    finally:
        # Restore chart state — best effort, separate session in case the main
        # session is already torn down due to an exception.
        if initial_symbol or initial_timeframe:
            try:
                async with AsyncExitStack() as restore_stack:
                    transport = await restore_stack.enter_async_context(stdio_client(server_params))
                    r_read, r_write = transport
                    restore_session = await restore_stack.enter_async_context(
                        ClientSession(r_read, r_write)
                    )
                    await asyncio.wait_for(restore_session.initialize(), timeout=10.0)
                    if initial_symbol:
                        await _call(restore_session, transcript, "chart_set_symbol", {"symbol": initial_symbol})
                    if initial_timeframe:
                        await _call(restore_session, transcript, "chart_set_timeframe", {"timeframe": str(initial_timeframe)})
                    _log(transcript, f"restored chart to {initial_symbol}/{initial_timeframe}")
            except Exception as e:
                _log(transcript, f"restore failed (non-fatal): {type(e).__name__}: {e}")
        else:
            _log(transcript, "no initial state captured — restore skipped")

        _write_transcript_and_stderr(transcript)

    return exit_code


def _write_transcript_and_stderr(transcript: list[str]) -> None:
    """Persist transcript and a stderr placeholder note."""
    TRANSCRIPT_PATH.parent.mkdir(parents=True, exist_ok=True)
    TRANSCRIPT_PATH.write_text("\n".join(transcript) + "\n", encoding="utf-8")
    # mcp SDK 1.x stdio_client does not expose subprocess stderr directly. The
    # transcript itself captures the call/response sequence; write a placeholder
    # to keep the artifact-set invariant for Plan 3.
    if not STDERR_PATH.exists():
        STDERR_PATH.write_text(
            "# mcp SDK 1.x stdio_client does not expose subprocess stderr.\n"
            "# If diagnostics are needed, launch the server manually via\n"
            "#   node C:\\Users\\Admin\\tradingview-mcp-jackson\\src\\server.js\n"
            "# in a separate PowerShell window and observe its stderr stream.\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
