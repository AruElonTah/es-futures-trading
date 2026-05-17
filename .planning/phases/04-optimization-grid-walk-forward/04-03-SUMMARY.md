---
phase: 04-optimization-grid-walk-forward
plan: 03
subsystem: api, ui
tags: [fastapi, next.js, react-plotly.js, plotly.js, duckdb, tanstack-query, optimization, heatmap, leaderboard]

# Dependency graph
requires:
  - phase: 04-01
    provides: DuckDB opt_runs + opt_results tables + DuckDBStore opt methods
  - phase: 03
    provides: FastAPI app.py + backtests route pattern + Next.js dashboard

provides:
  - FastAPI GET /optimizations — list opt_runs sorted by created_at DESC
  - FastAPI GET /optimizations/{run_id} — single run with progress fields
  - FastAPI GET /optimizations/{run_id}/results — OOS-ranked opt_results rows
  - FastAPI GET /optimizations/{run_id}/heatmap — 2D grid {x, y, z} with SQL injection guard
  - Next.js /optimizations page — leaderboard + Plotly heatmap
  - Dashboard header "Optimizations" link to /optimizations
affects:
  - Phase 7 (strategy controls panel — optimization run triggering deferred)
  - Phase 4-02 worker harness (produces rows read by these routes)

# Tech tracking
tech-stack:
  added:
    - react-plotly.js@2.6.0
    - plotly.js@3.5.1
    - "@types/react-plotly.js@2.6.4"
  patterns:
    - "dynamic(() => import('react-plotly.js'), { ssr: false }) — required for any plotly.js usage in Next.js App Router (window access at import time)"
    - "ALLOWED_AXES whitelist pattern for axis column injection prevention (before any SQL interpolation)"
    - "TanStack Query refetchInterval returning 2000 when status=running, false otherwise"
    - "edge_ratio > 2.0 red-flag styling in leaderboard table"

key-files:
  created:
    - packages/api/src/api/routes/optimizations.py
    - packages/api/tests/test_optimizations.py
    - apps/web/app/optimizations/page.tsx
  modified:
    - packages/api/src/api/app.py
    - apps/web/app/dashboard/page.tsx
    - apps/web/package.json

key-decisions:
  - "ALLOWED_AXES = frozenset({'opening_range_minutes', 'atr_stop_mult', 'r_target'}) — whitelist before any SQL construction (T-04-03-01)"
  - "react-plotly.js MUST use dynamic() with ssr:false — plotly.js accesses window at module load time"
  - "edge_ratio > 2.0 flags overfitting: is_sharpe/oos_sharpe ratio; NULL renders as em dash"
  - "Layout title/xaxis/yaxis use object form {text: ...} not string — required by @types/plotly.js@3.0.10"

patterns-established:
  - "Pattern: FastAPI router uses request.app.state.store._conn directly (no Depends) — matches backtests.py"
  - "Pattern: Heatmap endpoint validates axis names then safe-interpolates column names into GROUP BY query"
  - "Pattern: 2D pivot — build (x_vals, y_vals) sets, fill z[y_idx][x_idx] from row lookup dict"

requirements-completed: [OPT-07, OPT-08, OPT-09]

# Metrics
duration: 60min
completed: 2026-05-17
---

# Phase 4 Plan 03: Optimization API Routes + Next.js Leaderboard Summary

**FastAPI /optimizations routes with SQL injection guard + Next.js leaderboard with edge_ratio red-flag styling and dynamic react-plotly.js heatmap**

## Performance

- **Duration:** ~60 min (across two execution waves: checkpoint at Task 1 verified, Task 2 completed)
- **Started:** 2026-05-17T00:00:00Z
- **Completed:** 2026-05-17
- **Tasks:** 2 (+ checkpoint)
- **Files modified:** 6

## Accomplishments

- FastAPI optimization routes (4 endpoints) registered in app.py with SQL injection guard on heatmap axis params
- 10 API tests passing — empty list, invalid axis 422, valid heatmap 2D shape, opt_runs insert round-trip
- Next.js /optimizations page with leaderboard (edge_ratio > 2 red cells), axis selectors, and Plotly heatmap
- Dashboard header "Optimizations" link — surgical single-element addition, no chart/equity changes
- pnpm run build exits 0 — TypeScript clean

## Task Commits

1. **test(04-03): add failing tests for optimization API routes** — `58e6ff7` (TDD RED)
2. **feat(04-03): FastAPI optimization routes + app registration** — `b74b162` (TDD GREEN)
3. **feat(04-03): Next.js /optimizations page + plotly install + dashboard link** — `75e7458`

## Files Created/Modified

- `packages/api/src/api/routes/optimizations.py` — 4 endpoints: GET /optimizations, /{id}, /{id}/results, /{id}/heatmap with ALLOWED_AXES whitelist
- `packages/api/src/api/app.py` — registered optimizations_routes.router
- `packages/api/tests/test_optimizations.py` — 10 tests covering all route behaviors
- `apps/web/app/optimizations/page.tsx` — "use client" + dynamic react-plotly.js (ssr:false) + leaderboard + heatmap
- `apps/web/app/dashboard/page.tsx` — added Link import + Optimizations nav link in header
- `apps/web/package.json` — added react-plotly.js, plotly.js, @types/react-plotly.js

## Decisions Made

- Used `ALLOWED_AXES` frozenset validated before any SQL construction — T-04-03-01 mitigation. Column names from whitelist are safe to interpolate after validation; run_id uses parameterized query.
- `layout.title`, `xaxis.title`, `yaxis.title` use `{text: "..."}` object form not string — required by `@types/plotly.js@3.0.10` which ships with `@types/react-plotly.js@2.6.4`. The RESEARCH.md example showed string form which triggers TS error; fixed to object form.
- Removed `import type { Layout, PlotData } from 'plotly.js'` — `plotly.js` package has no standalone type declarations; types flow through `@types/react-plotly.js` which re-exports from `@types/plotly.js`. Direct import caused "Could not find declaration file" TS error resolved by dropping the import and letting `react-plotly.js` dynamic component infer types.
- Polling interval: `refetchInterval` returns `2000` when any run has `status === "running"`, `false` otherwise — avoids unnecessary poll when all runs are complete.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] plotly.js type import causes TS build error**
- **Found during:** Task 2 (frontend build verification)
- **Issue:** `import type { Layout, PlotData } from 'plotly.js'` → "Could not find a declaration file for module 'plotly.js'" — plotly.js 3.5.1 ships no bundled TypeScript types; they live in `@types/plotly.js` which is a transitive dep only visible to TypeScript via `@types/react-plotly.js`
- **Fix:** Removed the direct `plotly.js` type import; used `react-plotly.js` dynamic component without explicit type annotation; fixed `layout.title` / `xaxis.title` / `yaxis.title` to use `{ text: "..." }` object form as required by the installed `@types/plotly.js@3.0.10`
- **Files modified:** `apps/web/app/optimizations/page.tsx`
- **Verification:** `pnpm run build` exits 0, TypeScript passes in 10.6s
- **Committed in:** 75e7458

---

**Total deviations:** 1 auto-fixed (Rule 1 — build error from type import mismatch)
**Impact on plan:** Necessary correction for build to pass. No scope creep. Behavior unchanged from plan spec.

## Issues Encountered

- `@types/plotly.js` is installed in the pnpm store as a transitive dependency of `@types/react-plotly.js`, but the TypeScript compiler only finds it via the `@types/react-plotly.js` path. Direct `import type ... from 'plotly.js'` bypasses this and fails. Resolution: remove the direct import and rely on the `Plot` component's inferred prop types from the dynamic wrapper.

## Known Stubs

None — the page renders correctly with empty state when no optimization runs exist. All data flows from real API endpoints; no hardcoded or placeholder data.

## Threat Flags

None — no new network endpoints or auth surfaces beyond what the plan's threat model covers. T-04-03-01 (SQL injection) was mitigated via `ALLOWED_AXES`. T-04-03-02 (path traversal) accepted (deferred to Phase 7 per plan). T-04-03-03 (bundle size) accepted (dynamic import).

## User Setup Required

None — no external service configuration required. Both API and frontend changes are self-contained.

## Next Phase Readiness

- Phase 4 end-to-end slice is complete: CLI (Phase 4-02) → DuckDB (Phase 4-01) → API (this plan) → UI (this plan)
- `/optimizations` page will populate automatically once `run_opt.py` is executed with valid data
- Phase 7 deferred items: optimization run triggering from Strategy Controls, live WebSocket progress bar, docking /optimizations as a resizable pane

---
*Phase: 04-optimization-grid-walk-forward*
*Completed: 2026-05-17*
