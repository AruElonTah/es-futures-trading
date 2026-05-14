---
status: accepted
deciders: [Nathaniel Greene]
date: 2026-05-14
adr_id: 0001
slug: data-provider
supersedes: []
superseded_by: []
tags: [data, foundation, phase-0]
---

# 0001 — Data Provider for v1 (TradingView MCP as primary, Twelve Data as secondary)

## Status

Accepted (2026-05-14). The Phase 0 validation spike completed with `RESULT: conclusive` on the TradingView MCP restart-cycle test and a confirmed negative on Twelve Data's CME futures coverage. This ADR locks the v1 data-provider choice and names the eventual swap candidate.

## Context

The project's load-bearing invariant is **trust the numbers** — every Phase 4+ optimization run hashes this ADR and stores the hash in `runs.adr_hash` (FND-08 + OPT-04). Changing the data provider after this point means writing a superseding ADR, not amending this one.

Phase 0 ran a two-front validation spike to remove the data-provider unknown before Phase 1 commits a `DataSource` implementation:

- **Plan 00-01** probed Twelve Data's REST API for ES futures coverage (4 endpoints, 9-second pacing, stdlib-only). Result: `commodities_ES.body.data == []` — **Twelve Data does NOT serve ES futures** as of the probe date. `/stocks?symbol=ES` returns the Eversource Energy equity (NYSE/BMV/VSE) — the equity-ticker-collision pitfall is real. SPY 1m IS available on the operator's Free tier (`timeseries_SPY` returned 5 bars at `interval=1min`, credit headers 1 used / 7 left, confirming the 8/min ceiling).
- **Plan 00-02** drove the existing `tradingview-mcp-jackson` server (v2.0.0, 81 tools at `C:\Users\Admin\tradingview-mcp-jackson\`) end-to-end from a Python asyncio script using the official `mcp` SDK. Result: happy path completed (`chart_set_symbol(CME_MINI:ES1!)` → `chart_set_timeframe(1)` → `chart_scroll_to_date` → `data_get_ohlcv(390)` returned 300 bars of legitimate ES price action). Restart-cycle test produced `RESULT: conclusive` — MCP stdio pipe stayed alive across a deliberate TV Desktop quit-and-relaunch cycle, and the CDP connection re-established automatically after relaunch.

The spike also surfaced two non-obvious operational constraints documented under Consequences below.

## Decision Drivers

1. **ES coverage today, not "coming soon".** The strategy is ES-specific; a provider without ES is non-starter for the primary feed.
2. **Cost.** Single-operator project running paper-only in v1. Free or near-free tiers should be sufficient unless data volume changes drive a structural reason to pay.
3. **Reproducibility.** Backfills must be byte-deterministic across re-runs; vendor switches must not silently change OHLC values mid-history (FND-08).
4. **Failure-mode isolation.** When the primary feed degrades, the operator must be able to tell *which* layer broke — data layer vs. broker layer — without ambiguous shared state.
5. **Headless + CI compatibility (eventual).** Phase 1's `seed_bars.py` and Phase 8's reproducibility CI gate need a `DataSource` that can run without a GUI. TradingView MCP needs TV Desktop; that's fine for the operator's local box but inadequate for CI alone.

## Considered Options

1. **TradingView MCP primary + Twelve Data on SPY as secondary.** TV MCP for live ES + integrated chart; Twelve Data for headless SPY backfills and daily reconciliation.
2. **Twelve Data primary on SPY (as a proxy for ES).** Single vendor, no GUI dependency. Costs $0 if Free tier is sufficient.
3. **Databento primary.** First-party CME Globex MDP 3.0 access (ES + MES in one dataset), pay-as-you-go historical.
4. **Polygon / Massive Futures primary.** Futures-aware vendor with public REST + WebSocket. Pricing remains opaque (sales-only) as of 2026-05-14.
5. **Interactive Brokers historical via `ib_async`.** Real ES, $0 if an IB account exists, but requires the broker scope we've explicitly ruled out for v1 (paper-only).

## Decision

**v1 primary feed: TradingView Desktop via the `tradingview-mcp-jackson` MCP server.**
**v1 secondary feed: Twelve Data REST on SPY (for headless / CI / reconciliation).**
**Named swap candidate when budget opens: Databento (GLBX.MDP3 dataset, pay-as-you-go historical).**

Rationale:

- The Phase 0 spike proved Python-driven MCP control on Windows works end-to-end (`tv-mcp-tools.json`, `tv-mcp-transcript.log`) and survives a deliberate TV Desktop restart with the MCP stdio pipe intact (`tv-restart-test.log` → `RESULT: conclusive`). This was the primary technical risk for Option 1; it is retired.
- Twelve Data does not serve ES (`twelvedata-probe.json` `commodities_ES.body.data == []`) — Option 2 cannot satisfy Decision Driver #1 unless we redefine the strategy as SPY-only. Phase 1 retains the `DataSource` interface so SPY can still ship as a working proxy alongside the ES TV feed.
- Option 3 (Databento) is best-in-class for futures but at $199/month Standard is excess for a single-operator paper-trade build that already has a working free CME feed. The pay-as-you-go path is a clean upgrade once strategy edge is empirically established (see `### When to revisit`).
- Option 4 (Massive) is operationally indistinguishable from Option 3 except pricing is opaque and the rebrand maturity is uncertain. No advantage over Databento at this stage.
- Option 5 (IB historical) is explicitly out of scope per the paper-only constraint in PROJECT.md.

## Consequences

### Positive

- **Zero out-of-pocket cost for v1.** TV Desktop subscription is sunk cost (the operator's existing paid TV plan with real-time CME); Twelve Data Free tier covers SPY backfills (40 calls = 196,560 bars, ~5 min wall-clock with 9 s pacing per `spy-bar-budget.md`).
- **Live ES + integrated visualization in one place.** Phase 6's TVBridge can author overlays (ORB box, signal arrows, stop/target lines) directly on the operator's working chart — no separate viewer to glue together.
- **Failure-mode isolation is concrete.** Data layer degradation surfaces as either (a) TV MCP CDP disconnect (clear log line in `tv-restart-test.log` pattern) or (b) Twelve Data HTTP error codes; broker layer is paper-only so it can't degrade.

### Negative

- **CDP bootstrap is non-trivial.** TV Desktop launched normally (Start menu) does NOT enable Chrome DevTools Protocol; `tv_health_check` returns `CDP connection failed after 5 attempts: fetch failed` with `hint: TradingView is not running with CDP enabled. Use the tv_launch tool to start it automatically.` Phase 6's TVBridge supervisor MUST own the CDP-mode bootstrap (either by invoking the server's `tv_launch` tool or by launching TV with `--remote-debugging-port=9222` directly).
- **Mid-restart partial-load state is observable.** During the restart cycle, the cycle right after TV relaunch returned `JS evaluation error: Cannot read properties of undefined (reading '_activeChartWidgetWV')` — CDP attached to a partially-loaded target where the chart widget had not yet initialized. TVBridge must treat `cdp_connected=true` as necessary-but-not-sufficient and gate on `api_available=true` from `tv_health_check`.
- **MCP Python SDK 1.0's `stdio_client` does not expose the subprocess's stderr to the client.** Diagnostic output from the `tradingview-mcp-jackson` server is not directly capturable via the canonical SDK pattern. Phase 0's spike works around this by writing a placeholder note to `tv-mcp-stderr.log` (see Plan 02 Task 2). Phase 6 TVBridge MUST use `subprocess.Popen` directly (or a custom MCP transport) to capture server stderr for real operational observability.
- **TV's `quote_get` returns bar-start time, not last-tick time.** Quote staleness > 5 s under `quote_get` is NOT proof of stale market data — for a 1-minute bar, the latest closed bar's `time` field is 0–60 s old by construction. Freshness checks must rely on tick/event streams, not bar timestamps.
- **Tool count drift is real.** RESEARCH.md said the server reports ~78 tools; the actual probed count on 2026-05-14 was 81. The ADR pins 81 for forensic recall; if a future TV MCP version renames or removes the 4 required tools, this ADR's `runs.adr_hash` will no longer apply to results from that version and a superseding ADR is required.

### Neutral

- Twelve Data's catalog endpoints (`/stocks`, `/commodities`, `/etf`) do NOT emit `api-credits-used` / `api-credits-left` response headers. Only `/time_series` and (presumably) other data endpoints do. Phase 1's pacing layer must read credit headers from `/time_series` responses, never from catalog calls.

### When to revisit

This ADR should be re-opened (with a superseding ADR `0002-*.md`, never an amend) when any of the following trigger:

- ORB strategy survives walk-forward with positive OOS Sharpe across at least 3 folds.
- Operator commits to ≥ 4 weeks of daily forward paper-trading on a single strategy.
- Databento Standard tier ($199/mo as of 2026-05-14) is approved as a recurring budget line.
- TV MCP CDP disconnect rate exceeds 1/hour during normal operation (would force a swap regardless of strategy edge — the operator cannot sit on a flaky data source).
- Twelve Data adds ES to its catalog with documented OHLCV coverage on `/commodities` or a new `/futures` endpoint (would re-open Option 2 as a viable primary or robust secondary).
- The `tradingview-mcp-jackson` server is deprecated or undergoes a breaking rename of any of the 4 required tools (`tv_health_check`, `chart_set_symbol`, `chart_set_timeframe`, `data_get_ohlcv`).

## Verification artifacts

The decision is grounded in raw evidence committed under `.planning/research/spike-0/`. All six paths exist on disk at the date of this ADR; `scripts/spike/verify_artifacts.py` is the re-runnable check that they remain present and non-empty.

- `.planning/research/spike-0/twelvedata-probe.json` — Raw verbatim probe results for Twelve Data's `/stocks`, `/commodities`, `/etf`, `/time_series` endpoints, with rate-limit headers and redacted URLs.
- `.planning/research/spike-0/spy-bar-budget.md` — 2-year SPY 1m backfill rate-limit math (196,560 bars / 40 calls / ~5 min wall-clock) and per-tier feasibility recommendation.
- `.planning/research/spike-0/tv-mcp-tools.json` — TV MCP tool inventory (`tool_count: 81`, `all_required_present: true`).
- `.planning/research/spike-0/tv-mcp-transcript.log` — Happy-path smoke transcript (51 lines): `tv_health_check` → `chart_get_state` → `chart_set_symbol` → `chart_set_timeframe` → `chart_scroll_to_date` → `data_get_ohlcv(390) = 300 bars` → `quote_get` → restore.
- `.planning/research/spike-0/tv-restart-test.log` — Restart-cycle log (30 lines, `RESULT: conclusive`): 3 pre-restart OK cycles, `BEFORE_RESTART_MARKER`, FAIL window (cycles 13–14), `AFTER_RESTART_MARKER`, 3 post-restart OK cycles.
- `.planning/research/spike-0/comparison-table.md` — Re-verified vendor comparison table (Twelve Data / Databento / Massive / IB historical / CME DataMine).

## Pros and Cons of the Options

### Option 1 (chosen) — TradingView MCP primary + Twelve Data SPY secondary

Pros:
- Real-time CME ES with operator's existing paid TV subscription. Zero marginal cost.
- Integrated chart visualization for ORB box / signal arrows / stop & target lines (Phase 6 dependency).
- Twelve Data secondary fills the headless / CI / reconciliation gap that TV Desktop alone cannot.
- Smoke + restart spike validated empirically (`tv-mcp-transcript.log`, `tv-restart-test.log`).

Cons:
- Two providers means two `DataSource` adapters in Phase 1 (mitigated: the `Protocol` seam absorbs this; one selector switch in config).
- TV Desktop dependency makes the primary path non-headless. Phase 8's reproducibility CI gate must run against the Twelve Data path for the parts of the strategy graph it can.
- CDP bootstrap requirement is operator-visible.

### Option 2 — Twelve Data primary on SPY

Pros: Zero cost on Free tier, no GUI dependency, single vendor, well-documented Python SDK.
Cons: SPY ≠ ES (point value differs 10×, tick value differs 10×, microstructure differs subtly). All "ES results" become "SPY results in disguise" — undermines the trust-the-numbers invariant for the actual asset the operator trades.

### Option 3 — Databento primary

Pros: Best-in-class CME futures coverage; ES + MES in one dataset; pay-as-you-go historical is cheap for one-time backfills; rollover-stitched continuous contracts are a documented product.
Cons: $199/mo Standard tier is the entry monthly price for live subscriptions; no integrated chart; no obvious advantage over Option 1 until strategy edge is empirically established.

### Option 4 — Polygon / Massive Futures primary

Pros: Futures-aware; documented WebSocket + REST.
Cons: Pricing is opaque (sales-only, page returns title only when scraped); rebrand maturity uncertain; same chart-integration gap as Databento; no clear advantage to choose this over Databento at the swap moment.

### Option 5 — IB historical via `ib_async`

Pros: Real ES; $0 if IB account exists.
Cons: Requires live broker scope (explicitly out of v1 per PROJECT.md); historical pacing is harsh (60 reqs / 10 min); TWS / Gateway must be running.

## Notes for the planner

This ADR will be hashed (SHA-256 of its full bytes including frontmatter) and stored in every Phase 4+ optimization run's `runs.adr_hash` column (FND-08 + OPT-04). Editing this ADR post-commit invalidates that hash chain for all future runs. The correct path to "revise the decision" is **write a superseding ADR** (`0002-...md`) and set `supersedes: [0001]` in its frontmatter — and set `superseded_by: [0002]` in this one in the same commit. Never edit the body of an accepted ADR after the closing Phase 0 commit lands on `main`.
