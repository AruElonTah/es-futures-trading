# Futures-Aware Data Vendor Comparison

**Verified:** 2026-05-14
**Source:** Phase 0 spike, re-verified against live vendor pricing pages on the date above.
**Companion to:** `.planning/decisions/0001-data-provider.md`

## Comparison Table

| Vendor | ES coverage | MES coverage | Live | Historical | Monthly cost (verified 2026-05-14) | Python SDK | Verification source |
|--------|-------------|--------------|------|------------|------------------------------------|------------|---------------------|
| **Twelve Data** | NO (catalog excludes CME futures — `probes.commodities_ES.body.data == []` in `twelvedata-probe.json`) | NO | Yes (WebSocket for stocks/forex/crypto, **NOT futures**) | Yes (5,000 bars/call max, full SPY 1m history reachable in ~40 calls) | Basic Free (8 cred/min, 800/day) → Grow $79/mo (377/min, no cap) → Pro $229/mo (1,597/min) → Ultra $999/mo (10,946/min) **[RE-VERIFIED 2026-05-14 — UNCHANGED from RESEARCH]** | `twelvedata` (official) | twelvedata.com/pricing |
| **Databento** | YES (CME Globex MDP 3.0 — GLBX.MDP3 dataset) | YES (same dataset) | Yes (flat-rate subscription) | Yes (15+ years L0/MBP-1/MBO schemas, **usage-based pay-as-you-go in $/GB**; $125 free credits for new users) | Standard $199/mo (monthly) → Plus $1,399/mo (annual contract) → Unlimited $3,500/mo (annual contract) **[RE-VERIFIED 2026-05-14 — UNCHANGED from RESEARCH]** | `databento` (official) | databento.com/pricing |
| **Massive (formerly Polygon.io Futures)** | Likely YES (rebrand markets CME Globex coverage; CBOT/CME/NYMEX/COMEX) | Likely YES | Yes (WebSocket + REST) | Yes (aggregates, trades, quotes) | **OPAQUE — pricing page returned title only on 2026-05-14 (JS-rendered, no scrape-friendly content)** | `massive-com/client-python` | massive.com/futures |
| **IB historical (`ib_async`)** | YES (true ES contracts via TWS / IB Gateway) | YES | Yes (while TWS / Gateway session is alive) | Yes (rate-limited: **60 historical requests / 10 minutes**, hard pacing per IB docs) | $0 if an IB brokerage account exists | `ib_async` (community fork of `ib_insync`) | interactivebrokers.github.io/tws-api/historical_limitations.html |
| **CME DataMine** | YES (canonical exchange source) | YES | No (historical only — not a live feed for retail use) | Yes (full tick / order-book) | **Institutional pricing only** — requires sales contract; no public per-month figure | None (FTP / S3 / BBR delivery models) | Industry standard (CME Group) |

## Why Databento is named as the swap candidate

- **Cost shape matches our usage profile.** A single-strategy intraday operator pulls trivial bytes/day during live operation and modest GB during a one-time multi-year backfill. Databento's **usage-based historical** path (and the $125 free credits) means the eventual swap costs roughly the price of one 2-year ES 1m backfill, *not* a recurring $199/mo subscription — Standard tier is only needed if we move to multi-symbol live subscriptions, which is out of scope for v1.
- **One vendor, one dataset, one symbology.** Both ES (front-month rolling) and MES (the MES1! continuous) live in `GLBX.MDP3`. Rollover handling collapses to a single dataset query rather than glueing two providers together. Databento ships rollover-stitched continuous contracts as a documented product, which we'd otherwise have to re-implement.
- **First-party Python SDK and `pandas` DataFrame outputs.** `databento` is the official package; the `DBN` (Databento Binary Encoding) format is decoded directly into DataFrames with timestamps already in nanosecond UTC. That matches Phase 1's UTC discipline mandate (FND-03) with zero translation glue.

## Do-not-swap-to list

- **CME DataMine** — institutional only; pricing requires a sales contract; delivery is FTP/S3/BBR rather than a Python SDK.
- **`yfinance`** for futures — does not reliably serve continuous CME contracts; "free but unreliable, no SLA" per PROJECT.md `What NOT to Use`.
- **Alpaca** — confirmed has no futures (PROJECT.md `What NOT to Use`).
- **Polygon.io (stocks)** — separate product from Massive/Polygon Futures; the stocks side does NOT cover futures (verified May 2026 per CLAUDE.md).

## Findings from the Phase 0 spike

- **Twelve Data probe result** (from `twelvedata-probe.json` probed 2026-05-14T17:11:03Z): **ES is NOT in Twelve Data's commodities catalog.** `probes.commodities_ES.body.data` returned an empty array (`[]`) with `status="ok"`. `probes.stocks_ES.body.data` returns three "Eversource Energy" equity-ticker entries (NYSE / BMV / VSE) — confirming the equity-ticker collision pitfall flagged in RESEARCH.md. SPY 1m is confirmed available on the operator's current Free tier (`probes.timeseries_SPY.body.values` = 5 bars at `interval=1min` with `api-credits-used=1`, `api-credits-left=7`).
- **TV MCP smoke** (from `tv-mcp-tools.json` + `tv-mcp-transcript.log` run 2026-05-14T17:32Z): **81 tools enumerated, all 4 required tools present** (`tv_health_check`, `chart_set_symbol`, `chart_set_timeframe`, `data_get_ohlcv`). Happy path completed: chart set to `CME_MINI:ES1!`, timeframe `1`, scrolled to previous RTH close (2026-05-13T20:00:00Z), `data_get_ohlcv(count=390)` returned **300 bars** of legitimate ES price action (~7493–7517 range). Quote staleness recorded at 31.6s — caveat: TV's `quote_get` returns the most-recent CLOSED-bar start time, not the last tick time, so this is bar-start staleness, not market-feed lag.
- **TV MCP restart cycle** (from `tv-restart-test.log` run 2026-05-14T17:44–17:47Z): **RESULT: conclusive.** 3 pre-restart OK cycles → operator quit TV Desktop → cycle 13 timed out (CDP unreachable) → cycle 14 returned `JS evaluation error: Cannot read properties of undefined (reading '_activeChartWidgetWV')` (mid-restart partial-load state) → cycles 15+ recovered to OK → 3 post-restart OK cycles reached. MCP stdio pipe stayed alive throughout (no exit-code-6 broken-pipe condition).

## Notes on this verification

- All three live-pricing fetches on 2026-05-14 returned values **unchanged from the cached RESEARCH.md baseline** (Twelve Data tiers, Databento tiers, Massive's opaque page).
- Massive's pricing page remains JS-rendered with no scrape-friendly content; the row is honest about this rather than fabricating numbers.
- IB does not have a "monthly cost" line in the conventional sense — the $0 figure assumes an IB brokerage account already exists; the implicit cost is the platform fee (waived for sufficient monthly commission) plus the live-broker scope cost we have explicitly ruled out for v1.
