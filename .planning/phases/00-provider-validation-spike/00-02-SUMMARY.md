---
phase: 00-provider-validation-spike
plan: 02
subsystem: data-provider
tags: [tradingview-mcp, cdp, python-mcp-sdk, restart-resilience, phase-0]

requires:
  - phase: pre-phase-0
    provides: tradingview-mcp-jackson server v2.0.0 installed at C:\Users\Admin\tradingview-mcp-jackson\
provides:
  - End-to-end proof: Python mcp SDK can drive the Node MCP server on Windows
  - All 4 required tools confirmed present on operator's server (81 tools total)
  - Restart-cycle resilience verdict: CONCLUSIVE (MCP stdio survives TV restart)
  - Bootstrap finding: TV Desktop requires CDP-mode launch (tv_launch tool)
affects: [phase-1, phase-6, phase-0-plan-3-adr]

tech-stack:
  added: [mcp Python SDK (>=1.0,<2.0) in .venv-spike (throwaway)]
  patterns:
    - "Pattern: tools allowlist guardrail. Every _call() asserts the tool name is in ALLOWED_TOOLS / RESTART_ALLOWED_TOOLS BEFORE dispatch. Even a typo cannot reach draw_shape, alert_create, or pine_set_source."
    - "Pattern: restore-on-exit. Smoke test captures initial chart symbol/timeframe at session start; try/finally restores on exit (including crash exit)."
    - "Pattern: resume-signal-as-file. Restart cycle accepts both ENTER (TTY) and a marker file at .planning/research/spike-0/.resume-restart-now (non-TTY). The non-TTY path is the one used when the orchestrator drives the test."
    - "Pattern: UTF-8 stdout reconfigure on Windows. Defensive reconfigure of sys.stdout/stderr to utf-8 at script entry — protects against cp1252 crashes on background-piped runs (em dashes, arrows, etc. in log output)."

key-files:
  created:
    - scripts/spike/tv_mcp_smoke.py (happy-path: 81 tools, ES1!, 1m, scroll, 300 bars, restore)
    - scripts/spike/tv_mcp_restart.py (restart cycle: pre-OK -> FAIL window -> post-OK)
    - .planning/research/spike-0/tv-mcp-tools.json (sorted tool list + required-tools verification block)
    - .planning/research/spike-0/tv-mcp-transcript.log (51 lines, all 3 critical tool-call markers present)
    - .planning/research/spike-0/tv-mcp-stderr.log (placeholder — mcp 1.x stdio_client does not expose subprocess stderr)
    - .planning/research/spike-0/tv-restart-test.log (30 lines, RESULT: conclusive)

key-decisions:
  - "TV MCP integration is VIABLE for v1. Smoke + restart both passed against the operator's actual server (v2.0.0, 81 tools)."
  - "Phase 6's TVBridge must own the CDP bootstrap. TV Desktop launched normally does NOT enable CDP. The tradingview-mcp-jackson server's tv_launch tool is the documented bootstrap path (forks the TV.exe with --remote-debugging-port=9222)."
  - "Tool count drift is real: RESEARCH.md said ~78, server reports 81. Plan 1's adr_hash check will pin the exact count at decision time."
  - "Quote staleness >5s under quote_get is NOT proof of stale market data — TV returns the bar's start timestamp, not the last tick. Phase 6's freshness logic should rely on tick events or a websocket subscription, not bar timestamps."
  - "Restart resilience is NOT zero-downtime. There is a measurable window where CDP attaches to a partially-loaded target (cycle 14 of the restart log: 'Cannot read properties of undefined (reading _activeChartWidgetWV)'). TVBridge must tolerate this transient state."

patterns-established:
  - "Pattern: spawn-with-stdio_client. async with AsyncExitStack() as stack: stdio_transport = await stack.enter_async_context(stdio_client(server_params)). Asyncio.wait_for(session.initialize(), timeout=15s) catches the 'TV not running' case loudly."
  - "Pattern: file-marker resume signal in non-TTY contexts. Plan 2 supports BOTH ENTER (TTY) and a marker file (.resume-restart-now). Either fires the AFTER_RESTART_MARKER transition."

requirements-completed:
  - FND-10  # partial — full satisfaction requires Plan 3's ADR

duration: ~50min (including 3 failed runs to debug cp1252 / asyncio-task interactions)
completed: 2026-05-14
---

# Plan 00-02: TradingView MCP Smoke + Restart Resilience — Summary

**Python mcp SDK successfully drove the existing tradingview-mcp-jackson server end-to-end on Windows and conclusively survived a deliberate TV Desktop restart cycle — Plan 3's ADR can lock TradingView MCP as the v1 primary data feed with raw evidence.**

## Performance

- **Duration:** ~50 min including 3 failed restart-script runs to debug the cp1252 stdout-encoding crash and the asyncio-task interaction with mcp's anyio context.
- **Smoke test wall-clock:** ~30s (subprocess spawn + 7 tool calls + 1.5s render pause + restore).
- **Restart cycle wall-clock:** ~3m 36s (cycle 1 → RESULT: conclusive). 18 of 30 max cycles used.

## Accomplishments

- **End-to-end MCP drive proven.** 81 tools enumerated, all 4 required present, full happy path executed against `CME_MINI:ES1!` 1m with 300 bars returned and chart restored on exit.
- **Restart resilience proven CONCLUSIVE.** 3 pre-restart OK cycles → operator quit TV → 2 FAIL cycles observed (1 timeout, 1 mid-restart JS error) → 3 post-restart OK cycles → exit 0. MCP stdio pipe stayed alive throughout (no exit code 6).
- **Bootstrap dependency documented.** TV Desktop launched from Start menu does NOT enable CDP. The server's `tv_launch` tool is the documented mechanism — it forks `TradingView.Desktop_n534cwy3pjxzj!TradingView.Desktop` with `--remote-debugging-port=9222`. Phase 6's TVBridge supervisor must own this.
- **Mid-restart transient state surfaced.** Restart-cycle log line 21 shows `health=FAIL:tool call timed out quote=FAIL:JS evaluation error: TypeError: Cannot read properties of undefined (reading '_a...` — CDP can attach to a partially-loaded TV target where the chart widget is undefined. TVBridge must tolerate this.

## Task Commits

All 6 task outputs landed in one atomic commit per the plan's spec:

1. **Tasks 1–6 bundled:** `c7d005a` — `docs(00): plan 2 — tradingview mcp smoke + restart test`

(Like Plan 1, Plan 2's spec mandated a single atomic commit at Task 6 — the pre-commit hygiene scan must run against the full staged set, not per-task fragments.)

## Files Created/Modified

- `scripts/spike/tv_mcp_smoke.py` — 320-line async script. Stdio_client + ClientSession with 15s init timeout, ALLOWED_TOOLS allowlist, REQUIRED_TOOLS gate, chart-state capture-and-restore. Sample-bar logging (first 5 / last 5) and end-of-run summary block lift the transcript over the 50-line gate.
- `scripts/spike/tv_mcp_restart.py` — 280-line restart-cycle test. PRE_RESTART → WAITING_FOR_RESTART → POST_RESTART state machine. Both ENTER (TTY) and file marker (`.resume-restart-now`) resume paths. Incremental log writes for live progress visibility. PER_CALL_TIMEOUT_SECONDS=12 prevents cycles from hanging when CDP times out.
- `.planning/research/spike-0/tv-mcp-tools.json` — `tool_count=81`, `all_required_present=true`. Full sorted list of 81 tool names.
- `.planning/research/spike-0/tv-mcp-transcript.log` — 51 lines. Verbose per-call detail lines, sampled OHLCV bars (price action 7493–7517 on ES1! 1m), end-of-happy-path summary block.
- `.planning/research/spike-0/tv-mcp-stderr.log` — Placeholder note explaining mcp SDK 1.x's stdio_client does not expose subprocess stderr. Operator can re-run manually for diagnostics.
- `.planning/research/spike-0/tv-restart-test.log` — 30 lines. Pre-restart OK cycles, BEFORE_RESTART_MARKER, FAIL window, AFTER_RESTART_MARKER, post-restart OK cycles, `RESULT: conclusive`.

## Decisions Made

- **Adopt the file-marker resume path as a permanent feature, not a temporary hack.** The plan envisioned ENTER as the sole resume signal. In practice the orchestrator drives Plan 2 from a non-TTY context, so the marker file is the load-bearing path. Keeping both keeps the script usable from either driver.
- **Reconfigure stdout/stderr to UTF-8 at script entry.** Python on Windows defaults piped stdout to cp1252, which cannot encode `→` / `—`. The cp1252-trap caused the first 2 restart-script runs to crash with an `ExceptionGroup` from mcp's anyio task group. Both spike scripts now defensively reconfigure to utf-8 with `errors="replace"` at entry.
- **Per-call timeout of 12s on the restart script.** Prevents the loop from hanging indefinitely on a single CDP-unreachable call (a single 12s timeout produces a FAIL cycle line, then continues).
- **`api_available=true` is the real "TV is ready" signal, not `cdp_connected=true`.** During the initial TV launch, CDP can attach to the tooltip overlay (where `_activeChartWidgetWV` is undefined). Phase 6 must check `tv_health_check.api_available` not just `cdp_connected`.

## Deviations from Plan

**1. [Plan §Task 5 - input() handling] Added file-marker resume path**
- **Found during:** Task 5 first execution attempt (background, no TTY).
- **Issue:** Plan called for `await asyncio.get_event_loop().run_in_executor(None, input)` as the only resume signal. In a non-TTY background context, `input()` raises EOFError immediately AND the exception propagates through mcp's anyio task group, killing the whole stdio_client session.
- **Fix:** Added `RESUME_MARKER_PATH` (`.planning/research/spike-0/.resume-restart-now`). When the marker file exists, the cycle loop transitions to POST_RESTART. ENTER path is retained for human-driven TTY runs.
- **Files modified:** `scripts/spike/tv_mcp_restart.py`
- **Verification:** Final run exited `RESULT: conclusive` with `has_tty=False` summary line — the file marker was the path used.
- **Committed in:** `c7d005a` (Task 6 atomic commit).

**2. [Plan §Task 4 - asyncio.create_task with input executor] Removed concurrent input task**
- **Found during:** Task 5 second execution attempt (after isatty() check).
- **Issue:** Even with `isatty()` returning False and the input task being a no-op, creating any asyncio task inside the mcp stdio_client's anyio context appeared to destabilize teardown.
- **Fix:** Removed `asyncio.create_task` calls entirely from the cycle loop. The loop checks `marker_path.exists()` directly each cycle. No concurrent tasks needed.
- **Files modified:** `scripts/spike/tv_mcp_restart.py`
- **Verification:** Third (final) run completed successfully; cycle 16 detected the marker file and transitioned to POST_RESTART within 10s of the marker being dropped.
- **Committed in:** `c7d005a` (Task 6 atomic commit).

**3. [Plan §Task 2 - transcript min_lines: 50] Enhanced per-call logging**
- **Found during:** Task 3 first verify-gate run.
- **Issue:** Initial smoke transcript was only 17 lines because each tool call emitted a single summary line. Plan's `min_lines: 50` gate failed.
- **Fix:** Added per-call attempt + detail lines, plus a 10-bar sample (first 5, last 5) from `data_get_ohlcv`, plus a 4-line end-of-run summary block. Final transcript is 51 lines and substantively richer.
- **Files modified:** `scripts/spike/tv_mcp_smoke.py`
- **Verification:** `tools.json + transcript + stderr` all 3 files present, `tool_count=81 >= 60`, `transcript_lines=51 >= 50`, all 3 critical tool-call markers present.
- **Committed in:** `c7d005a` (Task 6 atomic commit).

## Notable Observations for Plan 00-03 (ADR)

| Finding | Plan 3 use |
|---------|-----------|
| 81 tools (not 78) on installed server | Cite as the exact tool count at ADR-date in the Consequences block |
| All 4 required tools present | Cite as Decision-Drivers evidence for picking TV MCP as v1 primary |
| MCP stdio survives TV restart | Cite as Consequences — TVBridge supervisor design becomes simpler |
| CDP-mode launch required (not Start-menu launch) | Cite as When-to-revisit trigger — if TV ships a default-CDP MSIX, revisit auto-launch policy |
| Mid-restart partial-load state | Cite as a known transient TVBridge must tolerate (api_available=False but cdp_connected=True) |
| Quote staleness measures bar-start not tick time | Cite as Consequences — Phase 6 freshness check must use tick events |

## Verification

All 6 plan-level verifications passed:
- [x] `.venv-spike/` exists, contains `mcp>=1.0,<2.0`, and is gitignored (verified via `git check-ignore`).
- [x] `scripts/spike/tv_mcp_smoke.py` enforces ALLOWED_TOOLS allowlist and restores chart state on exit (verified: chart back to ESM2026/3 after run).
- [x] `scripts/spike/tv_mcp_restart.py` uses explicit BEFORE/AFTER markers and emits conclusive/inconclusive verdict.
- [x] `tv-mcp-tools.json` exists with `all_required_present: true` and `tool_count=81`.
- [x] `tv-mcp-transcript.log` has 51 lines and includes `tool=tv_health_check`, `tool=chart_set_symbol`, `tool=data_get_ohlcv`.
- [x] `tv-restart-test.log` shows pre-OK, BEFORE marker, FAIL window (cycles 13–14), AFTER marker, post-OK, `RESULT: conclusive`.
- [x] `tv-mcp-stderr.log` exists with placeholder note; sensitive-content scan (`Cookie:`, `Authorization:`, CDP target URLs) found 0 matches across all 3 logs.
- [x] All 6 spike artifacts in single atomic commit `c7d005a`; `.venv-spike/` and `.env` NOT in that commit.
