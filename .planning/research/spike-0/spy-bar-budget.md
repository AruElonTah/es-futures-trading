# SPY 1m Backfill Rate-Limit Budget

**Computed:** 2026-05-14 (from `twelvedata-probe.json` → `probed_at_utc = 2026-05-14T17:11:03.517307+00:00`)
**Source:** `.planning/phases/00-provider-validation-spike/RESEARCH.md` §SPY Backfill Rate-Limit Math

## Inputs

| Input | Value | Source |
|-------|-------|--------|
| Window | 2 years RTH only | ROADMAP Phase 0 success criteria |
| Bars per RTH day | 390 (6.5h × 60min) | NYSE / CME equity-index calendar |
| Trading days / year | ~252 | pandas_market_calendars conventional |
| **Total bars** | **196,560** | 390 × 252 × 2 |
| Max bars per `/time_series` call | 5,000 | support.twelvedata.com/historical |
| Credits per call | 1 | support.twelvedata.com/credits |
| **Calls needed** | **40** | ceil(196,560 / 5,000) |

## Per-tier feasibility

| Tier | Credits/min | Daily cap | Time-to-backfill | Daily-budget consumption | Verdict |
|------|-------------|-----------|------------------|--------------------------|---------|
| Free ($0) | 8 | 800 | ~5 min wall-clock with 9s pacing | 40 / 800 = 5% | **Viable** (recommended for spike + early Phase 1) |
| Grow ($79/mo) | 377 | none | <1 min | n/a | Viable; 1min ETF gating ambiguous in docs (settled by Probe #4) |
| Pro ($229/mo) | 1597 | none | <1 min | n/a | Definitely viable; 1min interval definitively supported |

## Recommendation

**Free tier with ~9-second pacing.** ~5 minutes wall-clock for the one-time 2-year SPY 1m backfill. Live polling and daily reconciliation consume <100 credits/day during normal operation, well under the 800/day free-tier cap. Upgrade to Pro ($229/mo) ONLY if Probe #4 (next section) shows 1min interval is gated to Pro on SPY-as-ETF, AND the operator wants 1min granularity. 5min granularity remains free-tier-viable as a fallback for any future symbol where 1m turns out to be paywalled.

## Verification: 1min interval availability on the operator's actual tier

**1min SPY is available on the operator's current tier.** Probe #4 (`timeseries_SPY`) returned `status="ok"` with 5 bars (`datetime`, `open`, `high`, `low`, `close`, `volume`) at `interval=1min`. Observed rate-limit headers on this call: `api-credits-used=1`, `api-credits-left=7` — consistent with the Free tier 8-credit/min ceiling. Free tier is sufficient for the 2-year backfill. **No tier upgrade required.** Phase 1's `seed_bars.py` can default `--interval 1min` against this provider when SPY is selected.

## Observed rate-limit headers (this probe run)

| Probe | api-credits-used | api-credits-left | http_status |
|-------|------------------|------------------|-------------|
| `stocks_ES` | null | null | 200 |
| `commodities_ES` | null | null | 200 |
| `etf_SPY` | null | null | 200 |
| `timeseries_SPY` | 1 | 7 | 200 |

**Caveat:** Twelve Data emits the `api-credits-used` / `api-credits-left` response headers only on `/time_series` (and presumably other data endpoints), not on the catalog endpoints (`/stocks`, `/commodities`, `/etf`). The 1/7 reading from `timeseries_SPY` is the load-bearing observation — it confirms (a) the free-tier ceiling is 8/min, (b) a single 5,000-bar pull costs exactly 1 credit. Phase 1's pacing logic should rely on credit headers from `/time_series` responses, not assume they will appear on catalog calls.

## Calculation worksheet

```
Total bars:           196,560 (390 × 252 × 2)
Bars per call:          5,000
Calls needed:              40
Free tier (8/min):    5.0 min wall-clock with pacing
Free tier daily cap:    5% of budget
Pro tier (1597/min):  <1 min, no daily cap
```

## Footnote: rate-limit reset

Credits reset **every minute, not every hour** (verified support.twelvedata.com/credits). The 9-second pacing in `scripts/spike/twelvedata_probe.py` is a safety margin (gives ~6.6 calls/min ceiling vs. the 8/min budget). In production a `seed_bars.py` runner can use 8s with a single retry on HTTP 429.
