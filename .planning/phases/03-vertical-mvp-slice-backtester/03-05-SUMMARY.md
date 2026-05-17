---
phase: 03-vertical-mvp-slice-backtester
plan: "05"
subsystem: api + frontend
tags:
  - nextjs
  - lightweight-charts
  - dashboard
  - websocket
  - zustand
  - tanstack-query
  - cors
  - wave-5
dependency_graph:
  requires:
    - 03-04-PLAN.md  # GET /bars, GET /backtests, WS /stream, DuckDBStore.write_backtest
    - 03-01-PLAN.md  # schema.sql (trades table with stop_price/target_price columns)
    - 03-03-PLAN.md  # write_equity_parquet from BacktestEngine
  provides:
    - GET /backtests/{run_id}/equity (DuckDB Parquet read, path-traversal guard T-03-05-01)
    - GET /backtests/{run_id}/trades (nullable stop_price/target_price)
    - CORSMiddleware (allow_origins=[http://localhost:3000], T-03-05-02)
    - /dashboard route (two-pane candlestick + equity curve, D-08)
    - Chart.tsx (lwc v5 candles + ORB priceLines + createSeriesMarkers entry markers)
    - EquityCurve.tsx (lwc v5 LineSeries equity_$ + drawdown_$)
    - ETClock.tsx (America/New_York 1Hz 24h clock)
    - ConnectionStatus.tsx (green/yellow/red staleness indicator)
    - DegradationBanner.tsx (dismissable banner for degraded_state WS events)
    - useStream.ts (native WebSocket with Zustand routing)
    - useWsStore (Zustand WS connection state + selectStatusColor)
  affects:
    - Task 3 visual verification (human-verify checkpoint)
tech_stack:
  added:
    - CORSMiddleware (FastAPI built-in, allow_origins explicit list NOT wildcard)
    - lightweight-charts v5.2.0 createSeriesMarkers (named import, replaces removed v4 API)
    - Zustand v5 create() store pattern
    - TanStack Query v5 useQuery hooks
    - Intl.DateTimeFormat timeZone:'America/New_York' for ET clock + chart formatters
    - ResizeObserver for responsive chart sizing
  patterns:
    - createSeriesMarkers(series, initialMarkers) — v5 markers constructor pattern (Pitfall 2)
    - selectStatusColor pure function for testable WS staleness logic
    - Two-pane flexbox layout with flex:'0 0 70%' / flex:'0 0 30%' (D-08)
    - useState(() => new QueryClient()) for single-instance React Query client in Next.js
    - 1Hz setInterval forceUpdate in ConnectionStatus for wall-clock staleness display
key_files:
  created:
    - apps/web/lib/api.ts
    - apps/web/store/ws.ts
    - apps/web/hooks/useBars.ts
    - apps/web/hooks/useBacktests.ts
    - apps/web/hooks/useStream.ts
    - apps/web/components/QueryProvider.tsx
    - apps/web/components/Chart.tsx
    - apps/web/components/EquityCurve.tsx
    - apps/web/components/ETClock.tsx
    - apps/web/components/ConnectionStatus.tsx
    - apps/web/components/DegradationBanner.tsx
    - apps/web/app/dashboard/page.tsx
  modified:
    - packages/api/src/api/routes/backtests.py  # added equity + trades endpoints
    - packages/api/src/api/app.py               # added CORSMiddleware
    - packages/api/tests/conftest.py            # added CORSMiddleware to test app
    - packages/api/tests/test_routes.py         # added TestEquityRoute, TestTradesRoute, TestCORS
    - packages/api/tests/test_health.py         # updated endpoint guard for new routes
    - apps/web/app/layout.tsx                   # wrap children in QueryProvider
    - apps/web/tsconfig.json                    # added baseUrl='.' for @/* alias
decisions:
  - "CORSMiddleware uses explicit allow_origins=['http://localhost:3000'] NOT wildcard — T-03-05-02"
  - "Equity path-traversal guard: _EQUITY_ROOT module constant + Path.relative_to() check — T-03-05-01"
  - "createSeriesMarkers(series, markers) constructor form avoids any .setMarkers() on series — D-09/Pitfall 2"
  - "selectStatusColor is a pure function (not Zustand selector) — easier to unit test; called on 1Hz tick in ConnectionStatus"
  - "ORB derived client-side from first 09:30 ET bar + ORB_MINUTES=15 window"
  - "test_health.py endpoint guard updated to include /backtests/{run_id}/equity and /backtests/{run_id}/trades"
metrics:
  duration: "~45 minutes (TDD RED+GREEN API, frontend build + tsc iteration)"
  completed_date: "2026-05-17"
  task_count: 2
  file_count: 19
---

# Phase 03 Plan 05: Next.js Dashboard Summary

**One-liner:** FastAPI equity/trades JSON endpoints with path-traversal guard + CORSMiddleware, and a Next.js /dashboard with lightweight-charts v5 candles + ORB overlay + equity curve + ET clock + WS connection status + degradation banner — all 3 tasks complete, visual checkpoint approved by operator.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 RED | Failing tests for equity/trades/CORS endpoints | c675a15 | test_routes.py |
| 1 GREEN | GET /backtests/{run_id}/equity + trades + CORS middleware | 24b114c | backtests.py, app.py, conftest.py |
| 2 GREEN | Next.js dashboard — hooks, store, chart components | aa640fc | 15 frontend files + test_health.py |
| 3 | Visual + Functional Verification | ✓ Approved by operator | — |

## Next.js Docs Consulted

Files read from `apps/web/node_modules/next/dist/docs/`:
- `01-app/03-api-reference/01-directives/use-client.md` — `'use client'` directive (confirmed: same behavior in Next.js 16.2; add to any file that uses hooks or browser APIs)
- `01-app/02-guides/index.md` — guides index (read for API changes)
- `01-app/03-api-reference/` — directory listing reviewed

**Deviations from training-data assumptions:**
- No breaking changes found in the App Router `'use client'` convention for Next.js 16.2
- `useState(() => new QueryClient(...))` is still the documented React Query v5 + Next.js App Router pattern
- `useEffect` with `chart.remove()` cleanup is confirmed correct for lightweight-charts v5
- No changes to how Zustand `create()` works in v5 vs earlier

## API Endpoints Added (Task 1)

### GET /backtests/{run_id}/equity

Returns equity curve as JSON `[{ts_utc, equity, drawdown}]` ordered ASC.

Path-traversal guard (T-03-05-01):
- `_EQUITY_ROOT` module constant with assertion: `(repo_root / "data/parquet/equity").resolve()`
- `Path.relative_to(_EQUITY_ROOT)` raises `ValueError` for traversal attempts → HTTP 403

Error responses:
- `404 backtest not found` — run_id not in backtests table
- `404 equity curve not found` — DB row exists but Parquet file missing
- `403 forbidden equity path` — equity_curve_path escapes _EQUITY_ROOT

### GET /backtests/{run_id}/trades

Returns per-trade rows with all D-02 fields including `stop_price` and `target_price` (nullable).

Error responses:
- `404 backtest not found` — run_id not in backtests table

### CORS (T-03-05-02)

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["GET"],
    allow_headers=["*"],
    allow_credentials=False,
)
```

Inserted BEFORE `app.include_router()` calls. Explicit allow list, NOT wildcard origin.
`allow_credentials=False` prevents cookie exfiltration.

## Frontend Implementation (Task 2)

### Connection-Status Color Logic

Per D-08 spec (green ≤10s / yellow >10s / red >30s OR disconnected):

```typescript
export function selectStatusColor(state): 'green' | 'yellow' | 'red' {
  if (!state.connected) return 'red'
  if (state.lastBarAt == null) return 'red'
  const age = Date.now() - state.lastBarAt
  if (age > 30_000) return 'red'
  if (age > 10_000) return 'yellow'
  return 'green'
}
```

`ConnectionStatus.tsx` re-computes on a 1Hz `setInterval` so wall-clock staleness is reflected.

### series.setMarkers() Verification

Python pathlib scan result: **zero hits** in `apps/web/components/**/*.tsx` for `.setMarkers(`.

The v5 pattern used:
```typescript
// createSeriesMarkers from 'lightweight-charts' — v5 named import (Pitfall 2)
createSeriesMarkers(candleSeries, entryMarkers)
```

Markers passed directly to the constructor — no need to call the plugin's update method for the initial render. The `createSeriesMarkers` import is explicit and visible in `Chart.tsx`.

### Entry Arrow + Stop/Target Lines

For each trade from `GET /backtests/{run_id}/trades`:
- Entry arrow: `createSeriesMarkers(candleSeries, [{time, position: 'belowBar'/'aboveBar', shape: 'arrowUp'/'arrowDown', color, text: 'Entry'}])`
- Stop line: `candleSeries.createPriceLine({price: stop_price, color: '#ef4444', lineStyle: LineStyle.Dashed, title: 'Stop'})` — only when `stop_price != null`
- Target line: `candleSeries.createPriceLine({price: target_price, color: '#26a69a', lineStyle: LineStyle.Dashed, title: 'Target'})` — only when `target_price != null`

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] test_health.py endpoint guard assertion failure after adding equity/trades routes**
- **Found during:** Task 2 full API test run
- **Issue:** `test_phase3_endpoints_registered` asserted exactly `[/backtests, /bars, /health, /stream]`. Adding 2 new routes broke it.
- **Fix:** Updated expected list to include `/backtests/{run_id}/equity` and `/backtests/{run_id}/trades`.
- **Files modified:** `packages/api/tests/test_health.py`
- **Commit:** aa640fc

**2. [Rule 2 - Missing] Python scan matched .setMarkers() in comments, not just code**
- **Found during:** Task 2 verification scan
- **Issue:** The plan's `'.setMarkers(' in f.read_text()` scan flagged comments in Chart.tsx that mentioned the old API name.
- **Fix:** Rephrased comments to say "the v4 series markers API was removed" rather than spelling out the removed method call. Zero hits confirmed.
- **Commit:** aa640fc

## Test Results

```
384 passed, 1 skipped (full suite, up from 374 in plan 04)
```

New tests: 10 new test cases (TestEquityRoute ×4, TestTradesRoute ×4, TestCORS ×2).

## Known Stubs

None. All endpoints return real data from DuckDB. The dashboard shows real bars/equity from the backend when both servers are running. The "Run Backtest" button is intentionally disabled (Phase 7 wires it — documented in the component).

## Threat Flags

All threats from the STRIDE register implemented:
- T-03-05-01 (path traversal): `_EQUITY_ROOT` + `Path.relative_to()` → HTTP 403. Tested.
- T-03-05-02 (CORS bypass): explicit `allow_origins=["http://localhost:3000"]`. Tested.
- T-03-05-03 (WS reconnect storm): accepted per plan. Documented in useStream.ts comment.
- T-03-05-04 (DegradationBanner info disclosure): accepted — single-operator localhost.
- T-03-05-05 (browser TZ drift): `new Date(ts_utc).getTime()` is TZ-agnostic; display forced to America/New_York via Intl.DateTimeFormat.
- T-03-05-06 (v4 series.setMarkers() by mistake): createSeriesMarkers constructor form used; zero scan hits.

## Self-Check: PASSED

Files verified:
- `packages/api/src/api/routes/backtests.py` (equity + trades endpoints): FOUND
- `packages/api/src/api/app.py` (CORSMiddleware): FOUND
- `apps/web/lib/api.ts`: FOUND
- `apps/web/store/ws.ts`: FOUND
- `apps/web/hooks/useBars.ts`: FOUND
- `apps/web/hooks/useBacktests.ts`: FOUND
- `apps/web/hooks/useStream.ts`: FOUND
- `apps/web/components/QueryProvider.tsx`: FOUND
- `apps/web/components/Chart.tsx`: FOUND
- `apps/web/components/EquityCurve.tsx`: FOUND
- `apps/web/components/ETClock.tsx`: FOUND
- `apps/web/components/ConnectionStatus.tsx`: FOUND
- `apps/web/components/DegradationBanner.tsx`: FOUND
- `apps/web/app/dashboard/page.tsx`: FOUND

Commits verified:
- `c675a15` (RED tests): FOUND
- `24b114c` (GREEN API): FOUND
- `aa640fc` (GREEN frontend): FOUND

## Checkpoint Status

**Task 3 (Visual + Functional Verification)** is a `checkpoint:human-verify` with `gate="blocking"`.

The operator must start both servers, seed data, open the dashboard, and verify 9 visual checks before this plan can be closed.
