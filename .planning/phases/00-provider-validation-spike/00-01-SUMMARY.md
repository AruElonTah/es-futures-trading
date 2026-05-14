---
phase: 00-provider-validation-spike
plan: 01
subsystem: data-provider
tags: [twelve-data, rest-api, futures-coverage, spike, phase-0]

requires:
  - phase: pre-phase-0
    provides: ROADMAP + REQUIREMENTS lock the FND-10 ADR mandate
provides:
  - Verified negative finding: Twelve Data does not cover ES futures
  - Verified positive finding: 1min SPY is available on Free tier (no upgrade required)
  - 196,560-bar / 40-call / 5-minute backfill budget for SPY 1m
  - .env / .env.example / .gitignore wiring so the operator's API key never enters git
affects: [phase-1, phase-0-plan-3-adr]

tech-stack:
  added: [stdlib urllib.request (no httpx/requests dependency)]
  patterns:
    - "API-key redaction sentinel — every URL passes through `_redact(url, api_key)` before being written to disk."
    - "Manual .env parsing helper `_load_env_file()` — honors pre-exported shell env vars, no python-dotenv dep."
    - "9-second pacing between probes — gives ~6.6 calls/min under Free tier's 8/min ceiling."
    - "Hard exit on rate-limit (HTTP 429) instead of silent retry — prevents 'rate-limited' being misread as 'feature unavailable'."

key-files:
  created:
    - .gitignore (excludes .env, .env.local, .venv-spike/)
    - .env.example (committed template documenting TWELVEDATA_API_KEY)
    - scripts/spike/twelvedata_probe.py (stdlib-only 4-endpoint probe)
    - .planning/research/spike-0/twelvedata-probe.json (raw verbatim probe results)
    - .planning/research/spike-0/spy-bar-budget.md (per-tier feasibility + observed credit headers)

key-decisions:
  - "ES futures coverage on Twelve Data: NEGATIVE (commodities_ES.data == []). The /stocks?symbol=ES result is Eversource Energy (equity ticker collision), not the CME futures contract."
  - "SPY 1m on the operator's current Free tier: AVAILABLE (timeseries_SPY status=ok, 5 bars returned, credit headers 1 used / 7 left)."
  - "Free tier is sufficient for the eventual 2-year SPY 1m backfill (~5min wall-clock with 9s pacing, 5% daily-budget consumption). No tier upgrade required for Phase 1."
  - "Catalog endpoints (/stocks, /commodities, /etf) do NOT emit api-credits-used / api-credits-left headers. Phase 1 pacing logic must rely on /time_series response headers, not catalog calls."

patterns-established:
  - "Pattern: stdlib-only spike scripts. Phase 1's pyproject.toml has not yet shipped — spike code must run as `python scripts/spike/<name>.py` with zero third-party imports."
  - "Pattern: API-key redaction in committed JSON. Every URL with `apikey=<KEY>` is rewritten to `apikey=<TWELVEDATA_API_KEY>` before write. Verify gate counts `apikey=` occurrences and asserts they all match the redacted form."
  - "Pattern: .gitignore the secret BEFORE the operator pastes it. Task 1 enforces `.gitignore` excludes `.env` and `git check-ignore .env` returns 0 BEFORE the human-action checkpoint that creates the file."

requirements-completed:
  - FND-10  # partial — full satisfaction requires Plan 3's ADR

duration: ~25min
completed: 2026-05-14
---

# Plan 00-01: Twelve Data Probe + SPY Backfill Budget — Summary

**Confirmed strong negative on Twelve Data ES coverage and strong positive on SPY 1m availability — Plan 3's ADR can now lock TradingView MCP as the v1 primary feed with verifiable evidence.**

## Performance

- **Duration:** ~25 min (mostly waiting on 9s probe pacing × 3 = 27s + human-action checkpoint for the API key)
- **Started:** 2026-05-14 ~17:00 UTC
- **Completed:** 2026-05-14 17:11 UTC (twelvedata-probe.json `probed_at_utc`)
- **Tasks:** 5/5 (1 human-action checkpoint, 4 auto)
- **Files created:** 5 (probe script, probe JSON, budget worksheet, .env.example, .gitignore)

## Accomplishments

- **Verified negative on Twelve Data ES coverage** with raw committed JSON evidence. `commodities_ES.body.data == []`; `stocks_ES` matches Eversource Energy equity, not CME futures. Plan 3's ADR has the artifact it needs to cite verbatim.
- **Verified positive on SPY 1m availability** on the operator's current Free tier. Probe #4 returned status=ok with 5 1-minute bars; credit headers 1 used / 7 left confirm the 8/min ceiling and the 1-credit-per-call cost. No tier upgrade required for the 2-year backfill.
- **Authored the 196,560-bar / 40-call / 5-minute backfill worksheet** that Phase 1's `seed_bars.py` will plan against, including the caveat that catalog endpoints do not emit credit headers (rate-limit logic must lean on `/time_series` responses).
- **Wired the API-key handling end-to-end** so the operator's key is read from `.env`, never logged, never written to disk in raw form, and never committed (`git check-ignore .env` returns 0; cached-diff scan in Task 5 confirms key value never appeared in the commit).

## Task Commits

All 5 task outputs landed in one atomic commit per the plan's spec:

1. **Tasks 1–5 bundled:** `22ddb9c` — `docs(00): plan 1 — twelve data probe results`

(Plan 00-01's spec explicitly mandated a single atomic commit at Task 5, not per-task commits, because the artifacts are co-dependent and the API-key leak check must happen against the full staged set.)

## Files Created/Modified

- `.gitignore` — excludes `.env`, `.env.local`, `.venv-spike/` (the last anticipates Plan 00-02's throwaway venv).
- `.env.example` — committed template with the `TWELVEDATA_API_KEY=` line and a comment block pointing at twelvedata.com/register and the account API-keys page.
- `scripts/spike/twelvedata_probe.py` — 173-line stdlib-only script. Reads `.env`, 4 probes with 9s pacing, redaction sentinel, hard exit on 429, JSON output. Carries the `PHASE 0 SPIKE — DO NOT IMPORT FROM PRODUCTION CODE` sentinel per RESEARCH Pitfall #1.
- `.planning/research/spike-0/twelvedata-probe.json` — raw verbatim probe results. Top-level: `probed_at_utc`, `twelvedata_endpoint_base`, `probes` (4 entries with `url` redacted, `http_status`, `headers`, `body`).
- `.planning/research/spike-0/spy-bar-budget.md` — 8-section worksheet: inputs table, per-tier feasibility, recommendation, 1min-availability verification (branch (a) — available), observed-headers table, calculation block, rate-reset footnote.

## Decisions Made

- **No tier upgrade for Phase 1.** Free tier (8 credits/min, 800/day) is sufficient. Decision is in `spy-bar-budget.md`'s Recommendation section; Plan 3's ADR will repeat this in the Consequences block.
- **Catalog endpoints (`/stocks`, `/commodities`, `/etf`) cannot be used for credit-header observation.** Worksheet documents this so Phase 1's pacing layer doesn't accidentally depend on headers that never arrive.
- **Equity-ticker collision is real.** Plan 3's ADR will explicitly cite the `stocks_ES` → Eversource Energy result as the example of why probing only `/stocks?symbol=ES` would have produced a false positive on Twelve Data's ES support.

## Deviations from Plan

None — plan executed exactly as written, including all 5 verify gates and the cached-diff leak check.

## Notable Observations for Plan 00-03 (ADR)

| Finding | Plan 3 use |
|---------|-----------|
| `commodities_ES.body.data == []` | Cite as the load-bearing evidence in the ADR's Context section |
| `stocks_ES` → 3× Eversource Energy hits | Cite as the equity-ticker-collision example |
| `timeseries_SPY` status=ok, 1 credit used, 7 left | Cite in Consequences — SPY is the v1 working symbol, Free tier is enough |
| Catalog endpoints emit no credit headers | Cite as a known constraint on Twelve-Data-as-secondary-DataSource |

## Verification

All 5 plan-level verifications passed:
- [x] `.env.example` committed; `.env` in `.gitignore`; `git check-ignore .env` returns `.env`.
- [x] `scripts/spike/twelvedata_probe.py` is stdlib-only (`urllib.request`, no `httpx`/`requests`), exits hard on missing key, redacts URLs.
- [x] `.planning/research/spike-0/twelvedata-probe.json` has 4 probe entries with rate-limit headers; `apikey=<TWELVEDATA_API_KEY>` count matches total `apikey=` count (no raw key leaked).
- [x] `.planning/research/spike-0/spy-bar-budget.md` quotes the 196,560-bar math, per-tier table, observed-headers, and the 1min-available branch matched to probe #4.
- [x] Plan-1 files in single atomic commit `22ddb9c`; `.env` NOT in commit; raw key NOT in commit diff.
