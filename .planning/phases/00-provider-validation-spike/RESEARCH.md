# Phase 0: Provider Validation Spike — Research

**Researched:** 2026-05-14
**Domain:** Data-vendor validation for an ES futures trading system (Twelve Data + TradingView MCP), ADR authoring, vendor cost/coverage comparison.
**Confidence:** HIGH on TV MCP local server shape (read from source); HIGH on Twelve Data API mechanics (verified against support docs); MEDIUM on competitor pricing (verified live on vendor sites today, but vendor pricing pages frequently change — re-verify in the actual spike).

## Summary

Phase 0 is a research/decision spike, not implementation. It produces three concrete artifacts:

1. **A committed ADR** at `.planning/decisions/0001-data-provider.md` documenting (a) Twelve Data's ES coverage as of today, (b) why TradingView MCP is the v1 primary feed, (c) the named swap candidate (Databento by default).
2. **Smoke-test transcripts** under `.planning/research/spike-0/` proving TV MCP can be driven from Python end-to-end with a deliberate restart cycle.
3. **A SPY backfill budget worksheet** showing the per-tier call math for a 2-year 1m backfill so Phase 1's `seed_bars.py` doesn't surprise the user with rate-limit truncation.

The planner should split this into **3 parallel-ish plans** (see Recommended Task Split). Plans 1 and 2 can run independently; Plan 3 (the ADR) consumes the outputs of both.

**Primary recommendation:** Use the MADR (Markdown ADR) format with YAML frontmatter as the ADR template — it has a YAML frontmatter the system can hash for `runs.adr_hash` traceability (a requirement of FND-08 + OPT-04 downstream). Don't invent a custom format.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Twelve Data API probing | Local CLI / Python script | — | Pure HTTP — no app surface. Goes in `scripts/spike/`. |
| TV MCP stdio smoke test | Local CLI / Python script | TradingView Desktop (CDP target) | Spawned subprocess pattern; the eventual `tv-bridge` package will host the production version. |
| ADR authoring | Documentation (`.planning/decisions/`) | — | Markdown only. No code seam. |
| Spike artifact storage | Filesystem (`.planning/research/spike-0/`) | git | Plain files committed alongside the ADR for forensic recall. |
| Vendor pricing comparison | Web research → markdown table | — | Pure documentation; the table is transcribed into the ADR's "Considered Options". |

**Why this matters for Phase 0:** Everything in Phase 0 is local + documentation. No FastAPI, no DuckDB, no Next.js. The planner should not introduce production package layout yet — that's Phase 1's job per the roadmap. Phase 0 lives in throwaway `scripts/spike/` paths.

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| FND-10 | Provider-validation ADR committed to `.planning/decisions/` documenting (a) Twelve Data's ES coverage as of the ADR date, (b) the chosen v1 primary feed (TradingView MCP) and rationale, (c) the eventual futures-aware swap candidate (Databento / Polygon Futures / IB) | This entire document — Twelve Data Verification Protocol section (a), TV MCP Smoke-Test Design section (b), Futures-Aware Vendor Comparison section (c). |

## Project Constraints (from CLAUDE.md / PROJECT.md)

PROJECT.md is the binding source for this phase (no project-level CLAUDE.md exists). Constraints:

- **Paper / backtest only** — no broker credentials, no order routing. Phase 0 has no fills surface, so this is trivially satisfied.
- **Windows 11 / PowerShell primary**, Bash fallback. All shell snippets in this RESEARCH.md are PowerShell-first.
- **Python 3.11+** with `uv` package manager.
- **No POSIX-only assumptions** — `subprocess` calls must use `Popen` patterns that work on Windows; no `/dev/null`, no `&` backgrounding.
- **`gitleaks` pre-commit hook is a Phase 1 deliverable** — but Phase 0 must still avoid committing the Twelve Data API key in any spike artifact. Use placeholder strings (`<TWELVEDATA_API_KEY>`) when saving raw responses to git.
- **TradingView MCP server location:** `C:\Users\Admin\tradingview-mcp-jackson\` — already wired, do not reinstall. The server is a Node.js stdio MCP, version 2.0.0, 78 tools registered. Source verified by reading `src/server.js` + `src/tools/*.js`.

## Recommended Task Split

The planner should produce **three plans**. Plans 1 and 2 are independent and can run in parallel. Plan 3 consumes both.

### Plan 1: Twelve Data Probe + Backfill Budget Math
- Pure HTTP work. No subprocess, no MCP, no TV.
- Outputs: `.planning/research/spike-0/twelvedata-probe.json`, `.planning/research/spike-0/spy-bar-budget.md`.
- 3–5 tasks: install httpx (or use stdlib `urllib.request`), make 4 probe calls, capture rate-limit headers, write budget worksheet.
- ~30–60 minutes of work for a developer agent.

### Plan 2: TradingView MCP Smoke Test
- Stdio subprocess + MCP Python SDK.
- Outputs: `.planning/research/spike-0/tv-mcp-tools.json`, `.planning/research/spike-0/tv-mcp-transcript.log`, `.planning/research/spike-0/tv-restart-test.log`.
- 5–8 tasks: install `mcp` Python SDK, write spike script, run smoke test, deliberately restart TV Desktop mid-test, capture transcripts.
- Has a manual step (user must restart TV Desktop) — planner should encode this as a human-in-the-loop checkpoint.
- ~1–2 hours of work including the deliberate restart cycle.

### Plan 3: Vendor Comparison + ADR
- Pure research + writing.
- Outputs: `.planning/research/spike-0/comparison-table.md`, `.planning/decisions/0001-data-provider.md`.
- 3–4 tasks: verify each vendor's current pricing (planner may use cached data in this RESEARCH.md as starting point but should re-verify Databento / Polygon-Massive / Twelve Data since pricing changes), write the comparison table, write the ADR citing Plans 1 and 2 artifacts.
- ~1 hour.
- **Dependency:** Plan 3 must not start its ADR-writing task until Plans 1 and 2 have produced their `.json` and `.log` artifacts, because the ADR cites them by path.

## Twelve Data Verification Protocol

### Goal
Definitively answer "Does Twelve Data serve ES futures today?" with raw evidence committed to git. The negative finding from May 2026 is hypothesis, not fact — re-verify at the time of execution.

### The 4 probe calls

All probes go to `https://api.twelvedata.com/<endpoint>` and require `?apikey=<TWELVEDATA_API_KEY>` (free-tier key is sufficient; the user must register at twelvedata.com/register if they don't have one). [VERIFIED: twelvedata.com/docs — endpoint shapes inspected today]

| # | Endpoint | Purpose | Expected "unsupported" signal |
|---|----------|---------|-------------------------------|
| 1 | `GET /stocks?symbol=ES` | Does Twelve Data list ES under stocks? (it shouldn't, but rule out) | `{"data": [], "count": 0, "status": "ok"}` or a hit with `exchange != CME` (i.e., something other than the futures we want) |
| 2 | `GET /commodities?symbol=ES` | Most likely catalog for index futures | Empty `data` array OR a hit with `exchange != "CME"` |
| 3 | `GET /etf?symbol=SPY` | Confirm SPY (proxy fallback) is available | `data` non-empty, includes `{"symbol":"SPY","mic_code":"ARCX","exchange":"NYSE"}` |
| 4 | `GET /time_series?symbol=SPY&interval=1min&outputsize=5&apikey=<KEY>` | Confirm 1m bars are actually fetchable for SPY on the user's tier | HTTP 200 with `status: "ok"` and 5 entries in `values`. Failure mode: HTTP 200 with `status: "error"` and a `code`/`message` describing tier restrictions (1min is **Pro tier and above**) [VERIFIED: Twelve Data pricing page, fetched today] |

### Probe response shape (canonical, from docs)

`/time_series`: [VERIFIED: docs.twelvedata.com]
```json
{
  "meta": {
    "symbol": "SPY",
    "interval": "1min",
    "currency": "USD",
    "exchange_timezone": "America/New_York",
    "exchange": "NYSE",
    "type": "ETF"
  },
  "values": [
    {"datetime":"2026-05-13 15:59:00","open":"...","high":"...","low":"...","close":"...","volume":"..."}
  ],
  "status": "ok"
}
```

`/stocks`, `/etf`, `/commodities` (catalog lookups): paginated `{count, data, status}`. [VERIFIED]

### Failure modes to capture

| Signal | What it means | Action |
|--------|---------------|--------|
| HTTP 200, `status: "error"`, `code: 400`, message mentions "symbol not found" | Symbol genuinely not in catalog | Document as negative finding; ES is unsupported |
| HTTP 200, `status: "error"`, `code: 401` | Bad API key | Fix the key; do not commit it |
| HTTP 200, `status: "error"`, `code: 403` mentioning "plan" | Endpoint requires a paid tier | Document the tier requirement |
| HTTP 429 | Rate limit hit | Document and wait — does NOT count as "ES unavailable" |
| Empty `data` array on `/commodities?symbol=ES` | ES not in commodities catalog | Strong negative signal |
| Non-empty `data` but `exchange != "CME"` and `type != "Futures"` | Twelve Data matched a different ES (e.g., Eros Investments stock ticker) | Document — the ES we want is the CME futures contract, not an equity match |

[CITED: support.twelvedata.com — credit / 429 behavior]

### Rate-limit headers to capture on EVERY response

The Twelve Data API returns two response headers on every call: [VERIFIED: support.twelvedata.com/en/articles/5615854]

- `api-credits-used` — credits consumed by this request
- `api-credits-left` — credits remaining in the current minute window

`/time_series` consumes **1 credit per symbol per request** (so a 5-bar call for SPY = 1 credit). [VERIFIED: support.twelvedata.com] Credits reset every minute, not every hour.

There is no `X-RateLimit-*` header — these are Twelve-Data-specific names.

### Concrete PowerShell + Python probe script

The planner should produce a single `scripts/spike/twelvedata_probe.py` that runs all 4 probes and writes a single JSON document. Pattern:

```python
# scripts/spike/twelvedata_probe.py
"""Phase 0 spike — verify Twelve Data ES coverage and SPY 1m availability.
Reads TWELVEDATA_API_KEY from environment. Writes raw responses + rate-limit
headers to .planning/research/spike-0/twelvedata-probe.json.
Never commits the API key — it is read at runtime only.
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

API_KEY = os.environ.get("TWELVEDATA_API_KEY")
if not API_KEY:
    sys.exit("ERROR: set TWELVEDATA_API_KEY in environment before running")

BASE = "https://api.twelvedata.com"
PROBES = [
    ("stocks_ES",       f"{BASE}/stocks?symbol=ES"),
    ("commodities_ES",  f"{BASE}/commodities?symbol=ES"),
    ("etf_SPY",         f"{BASE}/etf?symbol=SPY"),
    ("timeseries_SPY",  f"{BASE}/time_series?symbol=SPY&interval=1min&outputsize=5&apikey={API_KEY}"),
]

results = {"probed_at_utc": datetime.now(timezone.utc).isoformat(), "probes": {}}
for name, url in PROBES:
    # Strip api-key from logged URL
    logged_url = url.replace(API_KEY, "<TWELVEDATA_API_KEY>")
    req = Request(url, headers={"User-Agent": "es-trading-spike/0.1"})
    try:
        with urlopen(req, timeout=15) as resp:
            body = resp.read().decode("utf-8")
            results["probes"][name] = {
                "url": logged_url,
                "http_status": resp.status,
                "headers": {
                    "api-credits-used": resp.headers.get("api-credits-used"),
                    "api-credits-left": resp.headers.get("api-credits-left"),
                },
                "body": json.loads(body),
            }
    except HTTPError as e:
        results["probes"][name] = {
            "url": logged_url,
            "http_status": e.code,
            "error": e.read().decode("utf-8", errors="replace"),
        }

out_path = Path(".planning/research/spike-0/twelvedata-probe.json")
out_path.parent.mkdir(parents=True, exist_ok=True)
out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
print(f"wrote {out_path}")
```

PowerShell invocation:
```powershell
$env:TWELVEDATA_API_KEY = "<paste-key-here>"
python scripts/spike/twelvedata_probe.py
# To keep the key out of shell history, the user can `Read-Host -AsSecureString`
# but for a one-off spike a plain set is acceptable so long as the .ps1 file
# itself is gitignored. The generated JSON has the key redacted (see logged_url).
```

### Expected committable output

`.planning/research/spike-0/twelvedata-probe.json` — 4 keyed probe results, API key redacted, raw response bodies preserved. The ADR cites this file path.

## TradingView MCP Smoke-Test Design

### Goal
Prove from Python that the existing `tradingview-mcp-jackson` server can be (a) spawned as a stdio subprocess, (b) driven through `chart_set_symbol` → `chart_set_timeframe` → `data_get_ohlcv` for ES 1m, (c) survives a deliberate TradingView Desktop restart and reconnects.

### Local server confirmed shape

[VERIFIED: read `C:\Users\Admin\tradingview-mcp-jackson\src\server.js` + `src/tools/*.js` today]

- **Server:** `node C:\Users\Admin\tradingview-mcp-jackson\src\server.js`
- **Transport:** stdio (uses `StdioServerTransport` from `@modelcontextprotocol/sdk@^1.12.1`)
- **Name:** `tradingview`, **version:** `2.0.0`
- **Tools relevant to this smoke test (confirmed names, not assumed):**
  - `tv_health_check` — verifies CDP connection to TV Desktop is alive (run first)
  - `tv_launch` — auto-launches TV Desktop with CDP remote debugging enabled (use if health check fails)
  - `chart_get_state` — returns current symbol, timeframe, indicators
  - `chart_set_symbol(symbol: string)` — change ticker (e.g., `"CME_MINI:ES1!"`)
  - `chart_set_timeframe(timeframe: string)` — change resolution (e.g., `"1"` for 1m)
  - `data_get_ohlcv(count?: number, summary?: boolean)` — get OHLCV bars; `count` max 500, default 100; **always pass `summary=true` unless you need every bar** (per server's own instructions)
  - `quote_get(symbol?: string)` — real-time price snapshot

ES continuous front-month TradingView symbol: **`CME_MINI:ES1!`** [VERIFIED in STACK.md and TV docs].
ES 1m timeframe string per TV convention: **`"1"`** (TV uses minute count as a string for intraday — `"1"`, `"5"`, `"15"`, `"60"`, `"D"`).

### MCP Python SDK pattern (canonical)

[VERIFIED: modelcontextprotocol.io/docs/develop/build-client]

Required package: **`mcp`** (the official Python SDK on PyPI). Install via `uv add mcp` or `pip install mcp`.

Canonical async pattern:

```python
import asyncio
from contextlib import AsyncExitStack
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

server_params = StdioServerParameters(
    command="node",
    args=[r"C:\Users\Admin\tradingview-mcp-jackson\src\server.js"],
    env=None,  # inherit; the server reads CDP_URL etc. from process env if needed
)

async def main():
    async with AsyncExitStack() as stack:
        stdio_transport = await stack.enter_async_context(stdio_client(server_params))
        read, write = stdio_transport
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()

        # 1. Enumerate tools (proof of life)
        tools_response = await session.list_tools()
        tool_names = sorted(t.name for t in tools_response.tools)
        # tool_names should contain ~78 entries including chart_set_symbol, data_get_ohlcv, etc.

        # 2. Health check
        health = await session.call_tool("tv_health_check", {})

        # 3. Drive the chart
        await session.call_tool("chart_set_symbol", {"symbol": "CME_MINI:ES1!"})
        await session.call_tool("chart_set_timeframe", {"timeframe": "1"})

        # 4. Pull OHLCV for the previous RTH session
        # NOTE: data_get_ohlcv reads the currently loaded bars from the chart.
        # Pass summary=false ONLY when capturing the transcript; in production use summary=true.
        ohlcv = await session.call_tool("data_get_ohlcv", {"count": 390, "summary": False})

        return tool_names, ohlcv

asyncio.run(main())
```

**Critical implementation notes:**

1. **Working directory:** `StdioServerParameters` does **not** expose a `cwd` argument directly. If the server has relative imports, the planner should test whether running from any cwd works. If not, use `command="cmd.exe"`, `args=["/c", "cd /d C:\\Users\\Admin\\tradingview-mcp-jackson && node src\\server.js"]` as a Windows-safe workaround. **Probe this in the first task.** [ASSUMED: untested; the server uses ES modules with absolute imports per `package.json` `"type": "module"`, so cwd should not matter — but verify.]

2. **stderr handling:** `stdio_client` consumes stdout for the MCP protocol. The server's stderr is NOT shown by default. To capture diagnostics, the planner should set up a separate background reader on the subprocess's stderr — OR use `command="node"`, redirect at the shell level when running interactively for debugging. For the committed transcript, write stderr to `.planning/research/spike-0/tv-mcp-stderr.log`.

3. **Initialization timeout:** `session.initialize()` may hang if TV Desktop isn't reachable. Wrap in `asyncio.wait_for(session.initialize(), timeout=15.0)` and fail loudly with "TV Desktop not running — start it manually then re-run".

4. **TV Desktop must be running BEFORE the spike script:** Per the MCP server's `tv_launch` tool description, the server can auto-launch TV Desktop, but for the smoke test the user should launch TV Desktop manually first (deterministic state). The script's first task is `tv_health_check` — if it fails, the script aborts with a clear message.

5. **`data_get_ohlcv` does NOT take date arguments.** [VERIFIED: read `src/tools/data.js`] It reads whatever is currently visible on the chart. To get the previous RTH session, the smoke test must (a) `chart_set_symbol` to ES, (b) `chart_set_timeframe` to "1", (c) `chart_scroll_to_date` to the previous RTH close (e.g., `2026-05-13T20:00:00Z` = 16:00 ET = RTH close), (d) THEN `data_get_ohlcv(count=390, summary=false)` to get the full 6.5-hour RTH session (390 minutes). Document this nuance in the ADR — it affects Phase 1's `TradingViewDataSource` implementation.

### The restart-cycle test

This is the "does it actually recover" test. Sequence:

1. Start spike script — establishes MCP session, calls `chart_set_symbol` for ES, calls `data_get_ohlcv` once → capture transcript line 1 ("baseline call OK").
2. Script enters a loop: every 10 seconds, call `tv_health_check` and `quote_get` for `CME_MINI:ES1!`. Log result with timestamp.
3. **Manual step (instruct the user):** "Now close TradingView Desktop completely (right-click tray icon → Quit). Wait 5 seconds. Reopen TradingView Desktop. Wait for it to fully load."
4. Script continues looping. Expected transcript:
   - Pre-restart: `health_check OK, quote_get OK`
   - During restart: `health_check FAIL: <error>, quote_get FAIL: <error>` (some number of cycles)
   - Post-restart: `health_check OK, quote_get OK` resumes (after user relaunches TV)
5. Loop terminates after 5 minutes total OR after 3 successful post-restart cycles.
6. Full log written to `.planning/research/spike-0/tv-restart-test.log`.

**Definition of success:** The Python process did not crash. The MCP session did not need to be re-established (or — if it did — the script handled the re-establishment cleanly). Specifically:

- **If the underlying CDP connection breaks but the MCP stdio pipe stays alive** (most likely case — the MCP server stays running as a Node process, only its CDP client to TV's debug port disconnects): subsequent tool calls return errors with `{"success": false, "error": "..."}`. Script logs the error, retries on a timer, eventually succeeds when TV is back. This is the expected and required behavior.
- **If the MCP stdio pipe itself breaks** (e.g., the Node server crashes too): the spike script must detect this and re-establish the session. Document in the ADR if this happens — it is a constraint on the eventual `TVBridge` supervisor.

### Expected committable outputs

| File | Content |
|------|---------|
| `.planning/research/spike-0/tv-mcp-tools.json` | Output of `list_tools()` — sorted tool names, count (should be ~78), proof that the tools the spec assumes (`chart_set_symbol`, `data_get_ohlcv`, etc.) actually exist on this server version. |
| `.planning/research/spike-0/tv-mcp-transcript.log` | Timestamped log of every tool call + its response for the happy-path sequence. |
| `.planning/research/spike-0/tv-restart-test.log` | Timestamped log of the restart-cycle test showing pre-fail-post pattern. |
| `.planning/research/spike-0/tv-mcp-stderr.log` | Server stderr (diagnostics, CDP errors) for forensic recall. |

## ADR Template

**Format choice:** MADR (Markdown ADR) with YAML frontmatter. [CITED: github.com/adr/madr] [VERIFIED: today]

**Why MADR over plain Nygard format:**
- YAML frontmatter is **machine-readable** — the system can hash it for `runs.adr_hash` (FND-08 + OPT-04 dependency).
- MADR's explicit "Considered Options" + "Pros and Cons" sections are exactly what this ADR needs to do (compare vendors).
- It's the most widely-used markdown ADR format in 2026 — familiar to future contributors.

**Location:** `.planning/decisions/0001-data-provider.md` (per ROADMAP.md Phase 0 success criteria). The 4-digit prefix is the MADR convention; subsequent ADRs will be `0002-*.md`, `0003-*.md`, etc.

**File-name slug:** Per the FND-10 wording in REQUIREMENTS.md, the slug should be `data-provider`. The roadmap success criteria explicitly cite `0001-data-provider.md`.

### Copy-pasteable skeleton

````markdown
---
status: accepted
deciders: [single-operator (project owner)]
date: 2026-05-14
adr_id: 0001
slug: data-provider
supersedes: []
superseded_by: []
tags: [data, foundation, phase-0]
---

# 0001 — Data Provider for v1 (TradingView MCP as primary, Twelve Data as secondary)

## Status

Accepted.

## Context

The ES Futures Trading System needs a market data source that reliably delivers:
- **1m / 5m / 15m bars for ES (E-mini S&P 500 futures, continuous front-month)** for the strategy and backtest layers.
- **1m / 5m / 15m bars for SPY** for secondary / CI / reconciliation use (Twelve Data's expected coverage).
- **Live polling and historical replay**, both behind the same `DataSource` protocol so the strategy/backtest code is provider-agnostic.

The initial assumption was **Twelve Data REST** as the primary feed. STACK.md surfaced a critical caveat: Twelve Data does not appear to list CME equity-index futures in its catalog. This ADR resolves that unknown with evidence before Phase 1 commits a `DataSource` implementation.

Constraints from PROJECT.md:
- Paper / backtest only — no live broker.
- Windows 11 / PowerShell primary environment.
- Local-only single-operator app.
- TradingView Desktop is already installed and the `tradingview-mcp-jackson` MCP server is already wired and running at `C:\Users\Admin\tradingview-mcp-jackson\`.

## Decision Drivers

- **ES coverage today** — does the candidate provider actually serve ES front-month 1m bars right now?
- **Cost** — paper/research project; v1 budget tolerance is ~$0–$100/mo. Future swap to a richer vendor is acceptable post-v1.
- **Reproducibility** — backfills need to be repeatable (deterministic byte-identical Parquet across re-runs).
- **Failure isolation** — when the primary feed fails, the trading core must not silently corrupt research conclusions.
- **Headless / CI compatibility** — at least one path must work without TV Desktop running (for CI reproducibility tests).

## Considered Options

1. **TradingView MCP (`data_get_ohlcv` via `tradingview-mcp-jackson`) as primary, Twelve Data as secondary** — leverages an already-wired tool, gives real ES data, but requires TV Desktop running.
2. **Twelve Data as primary on SPY (proxy)** — headless, simple HTTP, but SPY is only ~0.1× ES and not the real instrument.
3. **Databento as primary** — gold-standard CME data, but adds a $179–$199/mo subscription before any strategy edge is proven.
4. **Polygon.io / Massive Futures as primary** — newer offering, futures support exists, pricing requires verification.
5. **Interactive Brokers historical via `ib_async`** — free if the user has an IB paper account, but pulls live execution back in scope.

## Decision

**Adopt Option 1 (TradingView MCP primary, Twelve Data SPY-proxy secondary)** for v1. Name **Databento (GLBX.MDP3 dataset)** as the eventual swap candidate when the trading edge is proven enough to justify a paid feed.

Rationale: TradingView MCP is already running, already gives real ES data at the resolutions we need, and the same chart serves as the visualization surface (per the project's "trust the numbers" + "Bloomberg-density UI" requirements). Twelve Data fills the headless / CI gap on SPY without claiming false ES coverage. Databento is the documented swap target because it is the only vendor in the comparison set that gives both live and historical CME equity-index futures at usage-based cost — the right risk profile when the swap actually happens.

## Consequences

**Positive:**
- Zero additional cost for v1.
- ES data is real (not a proxy) when TV Desktop is up.
- The MCP integration that the UI needs anyway (Phase 6) is exercised from Phase 1.

**Negative:**
- TV Desktop must be running for the primary feed to work. CI / headless contexts must fall back to Twelve Data + SPY.
- `data_get_ohlcv` reads whatever is currently loaded on the TV chart; the `TradingViewDataSource` implementation must orchestrate `chart_set_symbol` + `chart_set_timeframe` + `chart_scroll_to_date` before each fetch (documented complexity).
- When the primary feed is the TV chart and TV is the active `DataSource`, MCP disconnects must HALT signal emission (per cross-phase guardrail). Bridge supervisor (Phase 6) is on the critical path.

**Neutral:**
- `DataSource` interface is doing real work — providers will be swapped post-v1 with mechanical changes only.

## Verification artifacts

- Twelve Data probe results: `.planning/research/spike-0/twelvedata-probe.json`
- TV MCP smoke transcript: `.planning/research/spike-0/tv-mcp-transcript.log`
- TV restart-cycle test: `.planning/research/spike-0/tv-restart-test.log`
- SPY backfill budget math: `.planning/research/spike-0/spy-bar-budget.md`
- Vendor comparison table: `.planning/research/spike-0/comparison-table.md`

## Pros and Cons of the Options

### Option 1 — TradingView MCP primary, Twelve Data secondary

- Good, because TV MCP is already wired and gives real ES data at no cost.
- Good, because the same chart is also the visualization surface (the project needs it anyway).
- Good, because Twelve Data still has a real role (SPY-proxy backfills, CI, reconciliation).
- Bad, because TV Desktop must be running.
- Bad, because `data_get_ohlcv` semantics force the DataSource to orchestrate chart state.

### Option 2 — Twelve Data primary on SPY only

- Good, because it's headless / CI-friendly.
- Bad, because SPY is not ES — strategy results don't transfer 1:1 to the real instrument.
- Bad, because the eventual ES port becomes a P1 risk, not a P3 hardening task.

### Option 3 — Databento primary

- Good, because it gives true CME futures with both live and historical.
- Bad, because $179+/mo before any strategy edge is proven.
- Bad, because v2-DATA-01 already plans this — pulling it into v1 inflates scope.

### Option 4 — Polygon / Massive Futures primary

- Good, because futures support exists and is documented.
- Bad, because their futures-tier pricing is not transparent on the public pricing page — requires a sales conversation, which is out of scope for v1.
- Bad, because the company rebrand (Polygon → Massive) introduces documentation churn risk.

### Option 5 — IB historical via `ib_async`

- Good, because free if the user has an IB account.
- Bad, because IB pacing rules (~60 historical requests per 10 minutes for 1m bars) make a 2-year backfill slow.
- Bad, because pulling IB into v1 reopens "live execution" surface area that PROJECT.md explicitly defers to v2.

## Notes for the planner

- Every Phase 4+ optimization run must reference this ADR by hash via `runs.adr_hash` (per FND-08 + OPT-04). The hash is computed over the YAML frontmatter + body bytes.
- When the swap happens (v2-DATA-01), this ADR will be marked `superseded_by: [0002 or later]` and the new ADR will be added.
````

### What the planner must hand-fill into the skeleton

These bracketed items are deliberately left for the ADR-authoring task to populate from the spike artifacts:

- `status` — almost certainly `accepted` once the spike confirms TV MCP works; could be `proposed` if a blocker emerges.
- The Context section's last paragraph — verify the TV MCP server location is still `C:\Users\Admin\tradingview-mcp-jackson\` at execution time.
- Any "Verified findings" subsection inside the Decision section — must quote raw values from `twelvedata-probe.json` and `tv-mcp-tools.json` to make the ADR self-contained.

## Futures-Aware Vendor Comparison

Pricing **verified live today (2026-05-14)**, but vendor pricing pages change frequently. The planner should re-verify the Databento and Massive (formerly Polygon.io) numbers when the spike actually runs. Twelve Data was re-verified directly from `twelvedata.com/pricing`.

### Comparison Table

| Vendor | ES coverage | MES coverage | Live | Historical | Monthly cost (2026-05-14) | Python SDK | Verification source |
|--------|-------------|--------------|------|------------|---------------------------|------------|--------------------|
| **Twelve Data** | NO (catalog excludes CME futures) | NO | Yes (WS for stocks/forex/crypto) | Yes (5000 bars/call, full SPY 1m history available) | Free (8 cred/min, 800/day) → **Grow $79** (377/min, no daily cap) → **Pro $229** (1597/min, 1min interval requires Pro+) → Ultra $999 | `twelvedata` on PyPI (official) | [VERIFIED: twelvedata.com/pricing fetched today; CITED: support.twelvedata.com/credits] |
| **Databento** | YES (front-month + far-month, CME Globex MDP 3.0) | YES (same dataset) | Yes (live data; flat-rate sub since 2025-04-16) | Yes (15+ years L0 schemas) | Usage-based pay-as-you-go for **historical** (no minimum); **Standard $199/mo** (15+yr L0, 1yr L1, 1mo L2/L3 history); **Plus $1,399/mo** (live + entire L1 history); **Unlimited $3,500/mo** | `databento` on PyPI (official) | [VERIFIED: databento.com/pricing fetched today] |
| **Polygon / Massive Futures** | YES (CME Globex incl. CBOT/CME/NYMEX/COMEX) | Likely YES (page mentions "all CME contracts") but not pricing-explicit | Yes (WebSocket + REST) | Yes (Aggregates, trades, quotes, snapshots) | Pricing not transparent on public page — must request directly | `massive-com/client-python` (was `polygon-io/client-python`) | [VERIFIED: massive.com/futures fetched today; pricing details NOT publicly available] |
| **Interactive Brokers historical** | YES (real ES via TWS) | YES | Yes (real-time during TWS session) | Yes (limited by pacing: ~60 historical reqs per 10 min; no hard cap on 1m bars but soft throttle exists) | $0 if you already have an IB account (paper account is free) | `ib_async` (community fork of the original `ib_insync` which is no longer maintained as of 2024) | [VERIFIED: interactivebrokers.github.io/tws-api/historical_limitations.html] |
| **CME DataMine** | YES (canonical source) | YES | No (historical only) | Yes (full tick / book history) | Institutional pricing — call for quote. Effectively unreachable for a single-operator project. | None official (BBR / S3 download model) | [VERIFIED: known industry knowledge — institutional only] |

### Why Databento is named as the swap candidate

1. **Cost shape matches the use case.** Usage-based historical (no minimum) means a one-time 2-year ES backfill is a few dollars, not a $199/mo commitment. Move to Standard ($199/mo) only when paper-trading goes daily.
2. **Single dataset for live + historical.** GLBX.MDP3 covers both modes — no second integration when the project graduates from research to forward paper.
3. **Python SDK is first-class.** `databento.Historical().timeseries.get_range(dataset="GLBX.MDP3", schema="ohlcv-1m", symbols=["ES.FUT"], stype_in="parent")` is the canonical call.
4. **Documented intent to use OHLCV-1m schema.** Databento ships OHLCV at 1s and 1m intervals natively — no client-side resampling for our timeframes.
5. **Polygon / Massive is the alternative but priced opaquely.** Until Polygon publishes futures-tier pricing on their public page, it's not commitable.
6. **IB historical is "free" but reintroduces live broker scope** — out of scope per PROJECT.md v1 constraints.

### The "do not swap to" list

- **CME DataMine** — institutional only; pricing requires a sales contract; not for single operators.
- **`yfinance` for futures** — does not reliably serve continuous CME contracts; STACK.md already documents this as a "do not use".
- **Alpaca** — confirmed in STACK.md as NOT having futures.

## SPY Backfill Rate-Limit Math

### Inputs

- **Window:** 2 years of 1m SPY bars covering RTH only (this matches what Phase 1's `seed_bars.py` will need for backtesting).
- **Bars per RTH day:** 6.5 hours × 60 minutes = **390 bars/day**.
- **Trading days per year:** ~252 (NYSE / CME equity-index calendar — `pandas_market_calendars` will give the exact number for the chosen window).
- **Total bars over 2 years:** 390 × 252 × 2 = **~196,560 bars** ✅ (matches the ROADMAP estimate of "~196k bars").

### Per-call budget

[VERIFIED: support.twelvedata.com/en/articles/5214728-getting-historical-data]

- **Maximum bars per `/time_series` call:** **5,000** (hard cap).
- **Credits per call:** **1 credit/symbol/request** (regardless of how many bars are returned). [VERIFIED: support.twelvedata.com/credits]

### Call count

Calls needed = ceil(196,560 / 5,000) = **40 calls**.

### Per-tier feasibility

| Tier | Credits/min | Daily cap | Calls to drain a minute | Minutes to backfill 40 calls | Daily-budget consumption | Verdict for 2yr SPY 1m |
|------|-------------|-----------|-------------------------|------------------------------|--------------------------|------------------------|
| **Free** | 8 | 800 | 8 | 5 minutes (40/8) | 40/800 = 5% | ✅ Works, easily fits in daily cap. Pacing required (sleep ~8s between calls to stay under 8/min). |
| **Grow ($79/mo)** | 377 | unlimited | 377 | <1 minute (40 < 377) | n/a | ✅ Trivial — runs in seconds. **But** see footnote: 1min interval support is documented as **Pro tier and above** on the current pricing page. Verify in the spike — if 1min on Grow is rejected with a tier error, escalate to Pro. |
| **Pro ($229/mo)** | 1,597 | unlimited | 1,597 | <1 minute | n/a | ✅ Works; 1min interval definitively supported here. Overkill for one backfill. |

### Recommendation for the ADR

**Tier choice: Free, with pacing.** [HIGH confidence — math is deterministic.]

A 2-year SPY 1m backfill consumes ~5% of the free-tier daily quota. The 8-credits/min ceiling means the pull takes ~5 minutes wall-clock with a polite 8-second inter-call sleep. The user does not need to subscribe to Grow or Pro for the initial backfill.

**Footnote on 1min interval on Grow:** Twelve Data's pricing page documents that 1min interval intraday data is "Pro tier and above" for US equities. ETFs (which SPY is classified as) **may** be more permissive. The spike script must include the 5-bar SPY 1m probe call (`/time_series?symbol=SPY&interval=1min&outputsize=5`) on the user's actual key to settle this. If it returns `status: "error"` with a tier-related message on the free tier, the ADR documents "1min SPY requires Pro tier" and the Phase 1 backfill task uses 5min or higher (still useful) or upgrades to Pro for the one-time backfill.

**Daily-budget reservation:** Even on Free, after the one-time backfill the live polling path consumes ~1 credit per refresh. A daily reconciliation pull (per MD-10) is one additional credit per check. Total daily consumption during normal operation is far under 100 credits — well under the 800/day cap.

### Calculation worksheet to commit

`.planning/research/spike-0/spy-bar-budget.md` should contain the table above plus this verification:

```
Total bars:           196,560 (390 × 252 × 2)
Bars per call:          5,000
Calls needed:              40
Free tier (8/min):    5.0 min wall-clock with pacing
Free tier daily cap:    5% of budget
Pro tier (1597/min):  <1 min, no daily cap
```

## Spike Output Layout

After Phase 0 is "done", `.planning/research/spike-0/` must contain exactly these files (the ADR at `.planning/decisions/0001-data-provider.md` cites each by relative path):

| File | Owner plan | Required | Content |
|------|------------|----------|---------|
| `twelvedata-probe.json` | Plan 1 | YES | Raw bodies of the 4 probes + `api-credits-used` / `api-credits-left` headers + redacted URLs. |
| `spy-bar-budget.md` | Plan 1 | YES | The math worksheet above. |
| `tv-mcp-tools.json` | Plan 2 | YES | Output of `list_tools()` — proves chart_set_symbol / chart_set_timeframe / data_get_ohlcv exist. |
| `tv-mcp-transcript.log` | Plan 2 | YES | Timestamped happy-path transcript: launch → tools list → set symbol → set timeframe → get ohlcv. |
| `tv-restart-test.log` | Plan 2 | YES | Timestamped restart-cycle transcript showing pre-restart OK, in-restart errors, post-restart OK. |
| `tv-mcp-stderr.log` | Plan 2 | YES | Server-side stderr for forensic recall. |
| `comparison-table.md` | Plan 3 | YES | Vendor comparison table (transcribed/expanded from this RESEARCH.md). |

After Phase 0, the directory is read-only. Phase 1 and beyond reference these paths but do not modify them. (If a vendor's pricing changes in Phase 2+, the response is to write a new ADR that supersedes this one, not to mutate the spike-0 artifacts.)

## Risks & Mitigations

| Risk | Detection signal | Mitigation |
|------|------------------|------------|
| **TV MCP can't be driven from Python on Windows due to stdio subprocess permissions or buffering.** | `session.initialize()` hangs forever (no response within 15 seconds). | Wrap initialize in `asyncio.wait_for(timeout=15.0)`. If it consistently hangs: capture stderr, try invoking `node src/server.js` directly in PowerShell to confirm it runs interactively, file the finding in the ADR's Consequences ("MCP-from-Python blocked on Windows — falls back to spawning the server via cmd.exe"). |
| **`tradingview-mcp-jackson` server version 2.0.0 doesn't expose the tool names this research assumes.** | `list_tools()` returns names that don't include `chart_set_symbol` or `data_get_ohlcv`. | Plan 2's first task must enumerate tools and validate against the assumed list BEFORE running any tool calls. If a tool is renamed, update the smoke-test script in-place and document the rename in the ADR. (Verified today against `src/tools/*.js` that the names match — risk is low, but verify at execution time.) |
| **Twelve Data updates their docs / catalog mid-spike — the negative ES finding becomes outdated.** | One of the 4 probes returns a non-empty `data` array for ES on `/commodities` or surfaces a CME-exchange match. | Plan 1's probe script captures raw responses verbatim; the ADR cites the probe-run timestamp; if ES IS in the catalog, the Decision section pivots to "Twelve Data primary on ES" and TV MCP becomes secondary. This is a **good** outcome — be prepared to write the alternate decision. |
| **TV Desktop is not running when the spike script starts.** | `tv_health_check` returns failure on first call. | Script's first step calls `tv_health_check`. On failure, output a clear "Start TradingView Desktop manually, then re-run this script" message and exit non-zero. Do NOT auto-launch via `tv_launch` for the smoke test — keep the test deterministic. |
| **Twelve Data 1m interval on free tier is rejected.** | Probe #4 returns `status: "error"`, code suggests tier restriction. | Document in the ADR. Phase 1's `seed_bars.py` task will need to either (a) use 5min as the backfill interval on free tier, (b) upgrade to Pro for the one-time pull, or (c) skip the backfill until later. None of these block Phase 0 completion. |
| **Stdio pipe buffering corrupts MCP messages on Windows.** | `session.list_tools()` returns garbage or times out, but `node src/server.js` runs fine standalone. | Try forcing line-buffered stdio at the Node side (set `NODE_NO_READLINE=1` and `--no-warnings`); try launching with `command="python"`, `args=["-u", node_wrapper.py]` where the wrapper just forwards stdio. If unfixable, document the constraint in the ADR — the eventual `TVBridge` (Phase 6) will need a custom transport. |
| **`gitleaks` is not yet installed (it's a Phase 1 deliverable) — the API key accidentally lands in a committed file.** | Probe script writes the raw URL (with `apikey=...`) into the JSON output. | The probe script in this RESEARCH.md already does `.replace(API_KEY, "<TWELVEDATA_API_KEY>")` before writing — preserve this pattern. **Additionally**, the planner should add a pre-commit check task: `git diff --cached \| grep -c "apikey="` must return 0 before the spike artifacts are committed. |
| **Vendor pricing pages return JS-only content and WebFetch can't extract pricing.** | Massive.com `/pricing` returned title only when fetched today. | Acceptable: the ADR can say "Massive futures pricing not publicly available, requires sales conversation — declined for v1" — that itself is a finding. The Databento and Twelve Data numbers ARE verified today. |

## Definition of Done (smoke-test bar)

Quantitative criteria. The planner should encode each as a verifiable assertion in the spike scripts or in plan-level success criteria.

### Twelve Data probe (Plan 1)
- [ ] All 4 probe calls executed and saved to `twelvedata-probe.json`.
- [ ] Each probe result includes `api-credits-used` and `api-credits-left` headers.
- [ ] API key does not appear anywhere in the JSON file (grep test: `grep -c <key-prefix> twelvedata-probe.json` returns 0).
- [ ] SPY-bar-budget math committed to `spy-bar-budget.md`; total bars = 196,560 ± 5%; chosen tier documented with rationale.

### TV MCP smoke test (Plan 2)
- [ ] `list_tools()` returned ≥ 60 tools (sanity check — server claims 78).
- [ ] The 4 critical tools exist in the result: `chart_set_symbol`, `chart_set_timeframe`, `data_get_ohlcv`, `tv_health_check`.
- [ ] Happy-path sequence completed: set symbol `CME_MINI:ES1!` → set timeframe `"1"` → fetched ≥ 100 OHLCV bars in one call (`data_get_ohlcv(count=390, summary=false)` is the target, but if TV only has 100 visible bars, 100 is acceptable evidence the call works).
- [ ] Restart cycle executed: pre-restart 3 consecutive successful `tv_health_check` calls, 1+ failed calls during restart, 3 consecutive successful calls post-restart. Logged with timestamps.
- [ ] Python process did not crash during the restart cycle.
- [ ] Transcript file is ≥ 50 lines and ≤ 1 MB (sanity bounds — too small = nothing ran, too large = something wrong).

### ADR (Plan 3)
- [ ] File exists at `.planning/decisions/0001-data-provider.md`.
- [ ] YAML frontmatter parses (planner can validate by `python -c "import yaml,sys;yaml.safe_load(open(sys.argv[1]).read().split('---')[1])" .planning/decisions/0001-data-provider.md`).
- [ ] All 5 verification artifacts cited by relative path AND the cited files all exist on disk.
- [ ] Decision section explicitly names: (a) v1 primary feed (TV MCP), (b) v1 secondary feed (Twelve Data SPY), (c) eventual swap candidate (Databento by default unless probe results pivot the decision).
- [ ] Considered Options section has at least 4 options with explicit pros/cons.
- [ ] ADR is ≤ 4 pages rendered — Nygard's "one or two pages" guidance allows two for a foundation-level decision but four is the upper bound before it stops being useful.
- [ ] ADR committed to git (single atomic commit if possible).

### Right-sizing

- Total spike duration target: **2–4 hours of executor time** including waiting for the user to restart TV Desktop.
- No production code is shipped. Anything that touches `packages/`, `apps/`, or `config/` is out of scope. Use `scripts/spike/` and `.planning/research/spike-0/` only.
- Smoke tests are throwaway — they are NOT part of the project's pytest suite. The artifacts they produce are what matters.

## Common Pitfalls

### Pitfall 1: Smoke test grows into production code
**What goes wrong:** The TV MCP spike script gets useful enough that it becomes the prototype for `tv-bridge`. The script accretes error handling, config loading, types — and is then quietly imported by Phase 1. Now spike-quality code is in the load-bearing path.
**Why it happens:** Sunk cost — "we already wrote this, why throw it away?"
**How to avoid:** Keep all Phase 0 code under `scripts/spike/`. Phase 1's `TVBridge` is written from scratch, with the spike scripts treated as documentation. Tag spike scripts with a header comment: `# PHASE 0 SPIKE — DO NOT IMPORT FROM PRODUCTION CODE`.
**Warning signs:** A Phase 1 task imports from `scripts/spike/`; the spike script grows past 300 lines; tests start being written for the spike script.

### Pitfall 2: Probing Twelve Data over the daily cap
**What goes wrong:** The spike re-runs many times during debugging; the 800/day free credit is consumed; subsequent runs return 429 and the developer thinks "ES is unsupported" when actually they're just rate-limited.
**Why it happens:** No client-side accounting of probe runs.
**How to avoid:** The 4 probes consume 4 credits total. Don't loop. If the probe script needs re-running for debugging, cache the response on first success and re-use until the cache is explicitly invalidated.
**Warning signs:** Probes return HTTP 429 — always interpret 429 as "rate limited", never as "feature unavailable".

### Pitfall 3: TV restart cycle doesn't actually test what it claims
**What goes wrong:** The user "restarts TV" by switching to a different chart, not by actually closing and reopening the app. The test passes but doesn't prove resilience.
**Why it happens:** Ambiguous instructions in the smoke-test runbook.
**How to avoid:** The restart-cycle log must include a marker line written by the spike script BEFORE the user is asked to restart, and another marker AFTER. The user-facing instruction must be explicit: "Right-click the TradingView tray icon → Quit TradingView. Wait until the icon is gone. Reopen TradingView Desktop from the Start menu. Wait until your chart re-renders. Press ENTER in this script's terminal."
**Warning signs:** The "during restart" section of the log shows ≤ 1 failure cycle. A real restart of TV takes ≥ 10 seconds; the health-check loop at 10-second cadence should miss at least 1 cycle.

### Pitfall 4: ADR Decision section omits the "when does this get superseded?" criteria
**What goes wrong:** The ADR locks the v1 decision but doesn't say what would trigger a swap. Six months in, the team debates "do we switch to Databento yet?" with no objective criteria.
**Why it happens:** ADR templates emphasize the decision now, not the conditions for revisiting.
**How to avoid:** Include in Consequences a "When to revisit" subsection with explicit triggers: (a) ORB strategy survives walk-forward with positive OOS Sharpe, (b) operator commits to ≥ 4 weeks daily paper trading, (c) Databento Standard tier is approved as a budget line. Any one of those triggers a new ADR.
**Warning signs:** Future contributors ask "why did we pick TV MCP?" and have to read git history instead of the ADR itself.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `tradingview-mcp-jackson` exposes the assumed tool names (`chart_set_symbol`, `data_get_ohlcv`, etc.) | TV MCP Smoke-Test Design | Verified by reading `src/tools/*.js` today, but server may be updated by the time the spike runs. Plan 2's first task must re-verify via `list_tools()`. |
| A2 | TV's `data_get_ohlcv` does NOT take date parameters and reads currently-visible chart bars only | TV MCP Smoke-Test Design | Verified today by reading `src/tools/data.js`. If the server adds date params in a future version, the smoke test still works but the design note in the ADR will be outdated. |
| A3 | `StdioServerParameters` for the `mcp` Python SDK does not require a `cwd` argument because the TV MCP server uses ES modules with package-internal imports | TV MCP Smoke-Test Design | Untested. If the server fails to start from an unrelated cwd, fall back to the cmd.exe wrapper documented in implementation notes. |
| A4 | Twelve Data's 1min interval is gated to Pro tier and above for US equities, possibly more permissive for ETFs | SPY Backfill Rate-Limit Math | Documented on pricing page but ETF gating is ambiguous. The 5-bar SPY 1m probe will settle this empirically. |
| A5 | Massive (formerly Polygon.io) futures-tier pricing is not transparent on the public pricing page | Vendor Comparison | Verified today — both the pricing page and the futures page return only titles when scraped. Re-verify at execution; if pricing is now public, update the comparison table accordingly. |
| A6 | A 2-year SPY 1m backfill is ~196,560 bars | SPY Backfill Rate-Limit Math | Verified math (390 × 252 × 2) but assumes the user actually wants 2 years; the ROADMAP success criteria explicitly cite this figure so the assumption is anchored. |
| A7 | The eventual swap is Databento, not Polygon/Massive or IB | Vendor Comparison | Verified pricing today; Databento Standard ($199/mo) is the right shape for the post-v1 use case. If the user has a specific preference, the ADR's Decision section should reflect it instead. |
| A8 | The free-tier Twelve Data probe will not auto-rate-limit (the 4 probes consume 4 of the 8/min ceiling) | Twelve Data Verification Protocol | Verified math. If the user has burned credits on the key already in the same minute, the probe may need a 60-second wait. The script should not retry automatically — it should fail loudly and let the user re-run after the minute resets. |

**If this table is empty:** All claims in this research were verified or cited — no user confirmation needed. (It is not empty — see A3 and A4 in particular before execution.)

## Validation Architecture

> `workflow.nyquist_validation` is `true` in `.planning/config.json`. Section required.

### Test Framework

| Property | Value |
|----------|-------|
| Framework | `pytest 8.x` — but **not in scope for Phase 0**. Phase 0 produces no production code. |
| Config file | None — `pyproject.toml` with pytest config is a Phase 1 deliverable (FND-02). |
| Quick run command | n/a for Phase 0 (no automated tests) |
| Full suite command | n/a |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| FND-10 | ADR committed at the documented path with all mandatory sections | manual + assertion script | `python scripts/spike/verify_adr.py` (a 30-line script that checks file existence, YAML frontmatter parses, mandatory sections present) | Wave 0 |
| FND-10 | Spike artifacts exist at documented paths | manual + assertion | `python scripts/spike/verify_artifacts.py` (checks `.planning/research/spike-0/{twelvedata-probe.json,tv-mcp-tools.json,tv-mcp-transcript.log,tv-restart-test.log,spy-bar-budget.md,comparison-table.md}` all exist and are non-empty) | Wave 0 |

### Sampling Rate
- **Per task commit:** n/a — Phase 0 has no test suite.
- **Per wave merge:** Run the two `verify_*.py` scripts above as a sanity check before declaring the phase complete.
- **Phase gate:** Manual review of the ADR by the operator. Until the operator reads the ADR and accepts it, Phase 0 is not done.

### Wave 0 Gaps
- [ ] `scripts/spike/verify_adr.py` — verifies the ADR file exists, parses YAML frontmatter, contains required sections.
- [ ] `scripts/spike/verify_artifacts.py` — verifies all 6 spike output files exist and are non-empty.

These are NOT pytest tests — they are bash-runnable assertion scripts. Phase 0 is the wrong place to introduce pytest infrastructure; that comes in Phase 1.

## Security Domain

> `security_enforcement` is not explicitly set in config.json — treat as enabled (default).

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | NO | Phase 0 is local-only, no auth surface. |
| V3 Session Management | NO | No sessions. |
| V4 Access Control | NO | Single operator, single machine. |
| V5 Input Validation | yes | Twelve Data API responses are external untrusted input. Use `json.loads` only; never `eval`. Reject any response where `status != "ok"` instead of trying to parse partial data. |
| V6 Cryptography | NO | No crypto operations in Phase 0. |
| V14 Configuration | yes | API key handling — must read from environment, must redact when writing artifacts, must not commit. |

### Known Threat Patterns for this Phase

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Twelve Data API key committed to git in a spike artifact | Information Disclosure | Always read key from `os.environ`; always replace `apikey=...` substrings in any URL written to disk; manual `git diff --cached` review before committing artifacts. (Phase 1's `gitleaks` pre-commit hook will mechanize this — Phase 0 must do it manually.) |
| TV MCP server stderr contains TradingView account info / cookies / CDP target URLs that leak host details | Information Disclosure | The committed `tv-mcp-stderr.log` should be reviewed by the operator before commit — redact any session cookies, CDP target URLs with credentials, or local file paths containing the user's name. |
| Spike script accidentally calls a destructive TV MCP tool (e.g., `alert_delete` for a real alert the user has) | Tampering | The smoke test only calls READ tools (`chart_get_state`, `data_get_ohlcv`, `quote_get`, `tv_health_check`, `list_tools`) and TWO writes that are reversible: `chart_set_symbol` and `chart_set_timeframe`. Do NOT call `draw_shape`, `alert_create`, `alert_delete`, `pine_set_source`, or any tool that mutates persistent TV state. Add this as an explicit allowlist in the spike script. |
| Spike script crashes leave the TV chart in a weird state (wrong symbol, wrong timeframe) | Availability (operator UX) | At the end of the smoke test (or in a `try/finally`), reset TV's chart to its original symbol/timeframe (capture initial state via `chart_get_state` at session start, restore at end). |

## Open Questions (RESOLVED)

Resolved during research-to-plan handoff via operator answers; recorded here for traceability.

There should be very few open questions for a spike phase — the spike is itself the answer-finding mechanism. The remaining open items are:

1. **Does the operator have a Twelve Data API key already, or does Phase 0 need to register for one?**
   - What we know: PROJECT.md and STACK.md assume Twelve Data is accessible; no key handling is documented.
   - What's unclear: Whether the key is already in the user's password manager or needs to be obtained.
   - Recommendation: Plan 1's first task is "Confirm `TWELVEDATA_API_KEY` is in environment; if not, instruct user to register at twelvedata.com/register and set the env var. Do NOT proceed without it."

2. **Is TradingView Desktop currently logged into a TradingView account with futures data permissions?**
   - What we know: The user must have at least some TV subscription for ES front-month real-time bars. Free TV accounts can view delayed futures data; real-time CME data requires a TV paid plan (TV Pro or higher) AND a CME exchange subscription.
   - What's unclear: Which TV plan the operator has.
   - Recommendation: Plan 2's first task includes a check — `chart_set_symbol("CME_MINI:ES1!")` then `quote_get()` should return a recent quote. If the quote is > 15 minutes old, document the data is delayed and the ADR reflects this constraint (delayed data is still usable for paper backtest research; live trading is out of scope per v1).

3. **Should the ADR reference the operator by name in `deciders:`?**
   - What we know: PROJECT.md describes a "single operator" but does not name them.
   - What's unclear: Whether the YAML frontmatter should say `deciders: [single-operator]` or use a real name.
   - Recommendation: Default to `deciders: [project-owner]`. The operator can edit the ADR locally before committing if they want their real name in.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.11+ | All spike scripts | ✓ (assumed per PROJECT.md constraint) | Verify with `python --version` | None — must be installed |
| `mcp` Python SDK | Plan 2 | ✗ | Install via `uv add mcp` or `pip install mcp` | None — must be installed |
| Node.js (for `tradingview-mcp-jackson`) | Plan 2 | ✓ (TV MCP server is already wired and running) | Verify with `node --version` | None |
| `tradingview-mcp-jackson` server | Plan 2 | ✓ at `C:\Users\Admin\tradingview-mcp-jackson\` | 2.0.0 (verified in package.json today) | None |
| TradingView Desktop | Plan 2 | ✓ (assumed running on the operator machine) | Any modern version | If not running, smoke test cannot execute — block phase until installed |
| Twelve Data API key | Plan 1 | ? (operator must provide) | n/a | Register at twelvedata.com/register; free tier sufficient |
| `httpx` or stdlib `urllib.request` | Plan 1 | stdlib available | n/a | The spike script in this RESEARCH.md uses `urllib.request` to avoid adding a dependency before Phase 1's package layout exists |
| git | Plan 3 | ✓ (repo already initialized per gitStatus) | Any modern version | None — must be installed |

**Missing dependencies with no fallback:**
- TWELVEDATA_API_KEY env var (operator action required before Plan 1 starts)
- TradingView Desktop must be running (operator action required before Plan 2's smoke test)

**Missing dependencies with fallback:**
- `mcp` Python SDK is missing today but installable in one command — not a blocker, just a Plan 2 task prerequisite.

## Sources

### Primary (HIGH confidence)
- `C:\Users\Admin\tradingview-mcp-jackson\src\server.js` + `src/tools/{data,chart,health}.js` — read today; tool names and signatures verified.
- `C:\Users\Admin\tradingview-mcp-jackson\package.json` — server version 2.0.0, `@modelcontextprotocol/sdk@^1.12.1` confirmed.
- [twelvedata.com/pricing](https://twelvedata.com/pricing) — current tiers and credits/min verified today.
- [support.twelvedata.com/credits](https://support.twelvedata.com/en/articles/5615854-credits) — `api-credits-used` / `api-credits-left` response headers documented; 1 credit per `/time_series` call.
- [support.twelvedata.com/historical](https://support.twelvedata.com/en/articles/5214728-getting-historical-data) — 5,000 bars max per call.
- [databento.com/pricing](https://databento.com/pricing) — Standard $199/mo, Plus $1,399/mo, Unlimited $3,500/mo verified today.
- [github.com/adr/madr](https://github.com/adr/madr) — MADR template structure verified.
- [modelcontextprotocol.io/docs/develop/build-client](https://modelcontextprotocol.io/docs/develop/build-client) — Python SDK stdio_client / ClientSession pattern verified today.

### Secondary (MEDIUM confidence)
- [interactivebrokers.github.io/tws-api/historical_limitations.html](https://interactivebrokers.github.io/tws-api/historical_limitations.html) — IB historical pacing rules.
- [databento.com/blog/introducing-new-cme-pricing-plans](https://databento.com/blog/introducing-new-cme-pricing-plans) — usage-based pricing for CME live data discontinued 2025-04-16.
- [github.com/modelcontextprotocol/python-sdk](https://github.com/modelcontextprotocol/python-sdk) — SDK install commands.

### Tertiary (LOW confidence — flagged for re-verification at execution time)
- Massive (formerly Polygon.io) futures pricing — page returns title only when fetched today; pricing is opaque without a sales conversation.

## Metadata

**Confidence breakdown:**
- Twelve Data API mechanics: HIGH — confirmed against support docs today, response shapes documented.
- TV MCP local server shape: HIGH — read source files today, tool names confirmed.
- MCP Python SDK pattern: HIGH — official docs read today, code pattern is canonical.
- Vendor pricing (Twelve Data, Databento): HIGH — pricing pages verified today.
- Vendor pricing (Massive/Polygon): LOW — public page does not surface futures pricing.
- ADR format choice (MADR): HIGH — well-established convention.
- Spike output design: HIGH — driven directly by Phase 0 success criteria in ROADMAP.md.
- Risk catalog: MEDIUM — drawn from training + the Pitfalls research file; not all risks are reproducible in advance.

**Research date:** 2026-05-14
**Valid until:** 2026-06-13 (30 days for vendor pricing). MADR / MCP SDK / TV MCP server facts are stable longer; re-verify pricing tables in Plan 3 just before writing the ADR.
