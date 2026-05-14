"""Phase 0 spike — TradingView MCP restart-cycle resilience test.

PHASE 0 SPIKE — DO NOT IMPORT FROM PRODUCTION CODE.

Per RESEARCH.md sections:
- "The restart-cycle test"
- "Definition of success" (CDP breaks, stdio pipe stays alive)
- "Common Pitfalls #3" (BEFORE/AFTER markers, observed_failure flag)

Loops tv_health_check + quote_get every 10 seconds across a deliberate
TV Desktop quit-and-relaunch cycle. The script blocks the operator's
restart action with an explicit checkpoint, and the cycle thread keeps
running concurrently so it observes the TV-down period as FAIL cycles.

Exit codes:
  0 — restart conclusively observed (pre-OK, FAIL window, post-OK)
  5 — inconclusive (no FAIL ever observed; operator likely did not actually quit TV)
  6 — MCP stdio pipe broke during the test (Node MCP server died)
"""

import asyncio
import json
import os
import sys
from contextlib import AsyncExitStack
from datetime import datetime, timezone
from pathlib import Path

# Reconfigure stdout / stderr to UTF-8 BEFORE any prints. On Windows the
# default piped-stdout encoding is cp1252, which raises UnicodeEncodeError on
# non-ASCII characters and breaks background runs (#cp1252-trap).
for stream_attr in ("stdout", "stderr"):
    stream = getattr(sys, stream_attr, None)
    if stream is not None and hasattr(stream, "reconfigure"):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

# Reuse smoke-script constants. Smoke and restart live in the same dir.
sys.path.insert(0, str(Path(__file__).parent))
from tv_mcp_smoke import (  # noqa: E402  (intentional sys.path manipulation)
    MCP_SERVER_PATH,
    MCP_SERVER_CWD,
    ES_SYMBOL,
    INIT_TIMEOUT_SECONDS,
)

from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

RESTART_LOG_PATH = Path(".planning/research/spike-0/tv-restart-test.log")
RESUME_MARKER_PATH = Path(".planning/research/spike-0/.resume-restart-now")
CYCLE_INTERVAL_SECONDS = 10.0
MAX_CYCLES = 30  # 5 min total wall-clock budget
PRE_RESTART_OK_REQUIRED = 3
POST_RESTART_OK_REQUIRED = 3
BEFORE_MARKER = "===== BEFORE_RESTART_MARKER ====="
AFTER_MARKER = "===== AFTER_RESTART_MARKER ====="

# Restart script's allowlist — TIGHTER than smoke. Only the two health-probe
# tools are needed; nothing else may be invoked (defense-in-depth per
# RESEARCH.md Threat T-03).
RESTART_ALLOWED_TOOLS = {"tv_health_check", "quote_get"}

PER_CALL_TIMEOUT_SECONDS = 12.0


# --------------------------------------------------------------------------
# Logging
# --------------------------------------------------------------------------

_LOG_FILE_HANDLE: object = None  # set in main() once the log path is resolved


def _log(transcript: list[str], line: str) -> None:
    stamped = f"{datetime.now(timezone.utc).isoformat()} | {line}"
    transcript.append(stamped)
    print(stamped, flush=True)
    # Incremental write — gives the orchestrator (or any tail watcher) live
    # visibility into progress instead of one big dump at exit (#2070-style).
    fh = _LOG_FILE_HANDLE
    if fh is not None:
        try:
            fh.write(stamped + "\n")
            fh.flush()
        except Exception:
            pass


# --------------------------------------------------------------------------
# Safe call wrapper — restart-script flavor
# --------------------------------------------------------------------------

class StdioBroken(Exception):
    """Raised when the MCP stdio pipe itself has died (Node process crashed).
    Distinct from `success=False` in a tool payload."""


async def _safe_call(session: ClientSession, name: str, args: dict) -> dict:
    """Wrap a tool call with the restart allowlist and timeout.

    Returns the parsed payload on success-or-tool-error. Raises StdioBroken on
    any underlying transport-layer exception so the caller can exit 6.
    """
    assert name in RESTART_ALLOWED_TOOLS, f"tool {name} not in restart allowlist"
    try:
        result = await asyncio.wait_for(
            session.call_tool(name, args), timeout=PER_CALL_TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError:
        # Timeout on a single call is not a pipe break — treat as FAIL cycle.
        return {"success": False, "error": "tool call timed out"}
    except Exception as e:
        # Anything else from the transport layer is a hard pipe break.
        raise StdioBroken(f"{type(e).__name__}: {e}") from e

    text = result.content[0].text if result.content else ""
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        payload = {"_raw": text}
    if not isinstance(payload, dict):
        payload = {"_value": payload}
    return payload


def _ok(payload: dict) -> bool:
    return payload.get("success") is True


def _short_err(payload: dict) -> str:
    err = payload.get("error") or payload.get("_raw") or ""
    err_str = str(err)
    return err_str[:80].replace("\n", " ")


# --------------------------------------------------------------------------
# Main flow
# --------------------------------------------------------------------------

async def _run_cycle(session: ClientSession) -> tuple[bool, str, bool, str]:
    """Returns (health_ok, health_err, quote_ok, quote_err). Raises StdioBroken."""
    health = await _safe_call(session, "tv_health_check", {})
    quote = await _safe_call(session, "quote_get", {"symbol": ES_SYMBOL})
    return (
        _ok(health),
        "" if _ok(health) else _short_err(health),
        _ok(quote),
        "" if _ok(quote) else _short_err(quote),
    )


async def _wait_for_enter(event: asyncio.Event) -> None:
    """Block an executor thread on input() — keeps the asyncio loop free for
    the concurrent cycle task to keep running during the operator's restart.

    No-op (returns immediately without setting the event) when stdin has no
    TTY. In that case the caller relies on the file-marker path. Catches all
    exceptions so the input task can never bubble into the mcp library's
    anyio task group and tear down stdio_client.
    """
    if not sys.stdin.isatty():
        return
    try:
        await asyncio.get_event_loop().run_in_executor(None, input)
    except BaseException:
        return
    event.set()


async def _wait_for_marker(event: asyncio.Event, marker_path: Path) -> None:
    """Poll for the resume marker file. Sets the event when the file appears.

    Allows external (chat / scripted) resume signaling when there is no TTY.
    Plan deviation from RESEARCH.md: the script supports BOTH input() and a
    file marker — whichever fires first triggers AFTER_RESTART_MARKER.
    """
    # Remove any stale marker from a previous run before we start waiting.
    try:
        if marker_path.exists():
            marker_path.unlink()
    except Exception:
        pass
    try:
        while not event.is_set():
            if marker_path.exists():
                event.set()
                return
            await asyncio.sleep(1.0)
    except asyncio.CancelledError:
        return


def _print_runbook() -> None:
    # ASCII-only — Windows cp1252 stdout cannot encode Unicode arrows (U+2192).
    print(
        "\n"
        "=================================================================\n"
        "RESTART CHECKPOINT\n"
        "=================================================================\n"
        "Right-click the TradingView tray icon -> Quit TradingView.\n"
        "Wait until the TV Desktop window AND tray icon are BOTH gone.\n"
        "Then reopen TradingView Desktop from the Start menu.\n"
        "Wait until your chart re-renders.\n"
        "\n"
        "RESUME SIGNAL (either works):\n"
        "  TTY:  press ENTER in THIS terminal\n"
        f"  File: create {RESUME_MARKER_PATH} (any content)\n"
        "=================================================================\n",
        flush=True,
    )


async def main() -> int:
    transcript: list[str] = []

    RESTART_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Resolve to absolute BEFORE chdir, same trick as smoke script.
    log_path = RESTART_LOG_PATH.resolve()
    marker_path = RESUME_MARKER_PATH.resolve()

    # Open the log file in append-and-flush mode for live updates.
    global _LOG_FILE_HANDLE
    _LOG_FILE_HANDLE = log_path.open("w", encoding="utf-8")

    _log(transcript, f"phase=0 spike=tv_mcp_restart server={MCP_SERVER_PATH}")
    _log(transcript, f"python={sys.version.split()[0]} cwd={Path.cwd()}")
    _log(transcript, f"config max_cycles={MAX_CYCLES} cycle_interval={CYCLE_INTERVAL_SECONDS}s")
    _log(transcript, f"config pre_ok_required={PRE_RESTART_OK_REQUIRED} post_ok_required={POST_RESTART_OK_REQUIRED}")
    _log(transcript, f"config per_call_timeout={PER_CALL_TIMEOUT_SECONDS}s")

    if not MCP_SERVER_PATH.exists():
        _log(transcript, f"FATAL: MCP server not found at {MCP_SERVER_PATH}")
        log_path.write_text("\n".join(transcript) + "\nRESULT: error_no_server\n", encoding="utf-8")
        return 1

    os.chdir(MCP_SERVER_CWD)
    env = os.environ.copy()
    env["NODE_OPTIONS"] = "--no-warnings"
    server_params = StdioServerParameters(
        command="node",
        args=[str(MCP_SERVER_PATH)],
        env=env,
    )

    cycles_pre_ok = 0
    cycles_post_ok = 0
    observed_failure_during_restart = False
    state = "PRE_RESTART"  # → WAITING_FOR_RESTART → POST_RESTART
    exit_code = 5  # default: inconclusive
    verdict = "inconclusive"
    has_tty = sys.stdin.isatty()

    try:
        async with AsyncExitStack() as stack:
            try:
                stdio_transport = await stack.enter_async_context(stdio_client(server_params))
            except Exception as e:
                _log(transcript, f"FATAL stdio_client failed: {type(e).__name__}: {e}")
                return 6
            read, write = stdio_transport
            session = await stack.enter_async_context(ClientSession(read, write))

            try:
                await asyncio.wait_for(session.initialize(), timeout=INIT_TIMEOUT_SECONDS)
            except asyncio.TimeoutError:
                _log(transcript, "INIT TIMEOUT — is TV Desktop running with CDP?")
                return 6

            _log(transcript, "session initialized; entering cycle loop")

            for cycle in range(1, MAX_CYCLES + 1):
                try:
                    health_ok, health_err, quote_ok, quote_err = await _run_cycle(session)
                except StdioBroken as e:
                    _log(transcript, f"FATAL stdio pipe broke: {e}")
                    _log(transcript, "RESULT: stdio_pipe_broke")
                    verdict = "stdio_pipe_broke"
                    exit_code = 6
                    break

                cycle_ok = health_ok and quote_ok
                health_part = "OK" if health_ok else f"FAIL:{health_err}"
                quote_part = "OK" if quote_ok else f"FAIL:{quote_err}"
                _log(
                    transcript,
                    f"cycle={cycle}/{MAX_CYCLES} phase={state} "
                    f"health={health_part} quote={quote_part}",
                )

                if state == "PRE_RESTART":
                    if cycle_ok:
                        cycles_pre_ok += 1
                    else:
                        cycles_pre_ok = 0
                    if cycles_pre_ok >= PRE_RESTART_OK_REQUIRED:
                        _log(transcript, f"pre-restart OK count reached {cycles_pre_ok}")
                        _log(transcript, BEFORE_MARKER)
                        _print_runbook()
                        # Wipe any stale marker file so a previous run's leftover
                        # cannot prematurely transition us out of WAITING.
                        try:
                            if marker_path.exists():
                                marker_path.unlink()
                        except Exception:
                            pass
                        state = "WAITING_FOR_RESTART"

                elif state == "WAITING_FOR_RESTART":
                    if not cycle_ok:
                        observed_failure_during_restart = True
                    if marker_path.exists():
                        _log(transcript, AFTER_MARKER)
                        if not observed_failure_during_restart:
                            _log(transcript, "note: resume signaled without any FAIL cycle observed yet")
                        state = "POST_RESTART"
                        cycles_post_ok = 1 if cycle_ok else 0

                elif state == "POST_RESTART":
                    if cycle_ok:
                        cycles_post_ok += 1
                    else:
                        # A post-AFTER failure is still tracked — gives Plan 3
                        # evidence of any flaky-reconnect behavior.
                        observed_failure_during_restart = True
                        cycles_post_ok = 0
                    if cycles_post_ok >= POST_RESTART_OK_REQUIRED and observed_failure_during_restart:
                        _log(
                            transcript,
                            f"post-restart OK count reached {cycles_post_ok}; conclusive",
                        )
                        verdict = "conclusive"
                        exit_code = 0
                        break

                await asyncio.sleep(CYCLE_INTERVAL_SECONDS)

            else:
                # Loop completed without break — MAX_CYCLES exhausted
                if observed_failure_during_restart and cycles_post_ok >= POST_RESTART_OK_REQUIRED:
                    verdict = "conclusive"
                    exit_code = 0
                else:
                    verdict = "inconclusive"
                    exit_code = 5
                _log(transcript, f"MAX_CYCLES={MAX_CYCLES} reached")

    except BaseException as e:
        import traceback
        tb = traceback.format_exc()
        _log(transcript, f"unexpected error: {type(e).__name__}: {e}")
        for tb_line in tb.splitlines():
            _log(transcript, f"  tb: {tb_line}")
        exit_code = 6
        verdict = "stdio_pipe_broke"
    finally:
        _log(
            transcript,
            f"summary cycles_pre_ok={cycles_pre_ok} cycles_post_ok={cycles_post_ok} "
            f"observed_failure_during_restart={observed_failure_during_restart} has_tty={has_tty}",
        )
        _log(transcript, f"RESULT: {verdict}")
        # _log already wrote incrementally; close the live handle and re-write
        # once more from the in-memory transcript to guarantee a clean,
        # complete file even if the handle suffered a partial flush failure.
        try:
            if _LOG_FILE_HANDLE is not None:
                _LOG_FILE_HANDLE.close()
        except Exception:
            pass
        log_path.write_text("\n".join(transcript) + "\n", encoding="utf-8")
        # Clean up the resume marker if it was used.
        try:
            if marker_path.exists():
                marker_path.unlink()
        except Exception:
            pass

    return exit_code


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        sys.exit(130)
