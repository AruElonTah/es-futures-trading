# Phase 1: Foundation + Data In - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-14
**Phase:** 01-foundation-data-in
**Areas discussed:** Workspace shape (4 sub-decisions)

---

## Gray-area Selection (multi-select)

| Option | Description | Selected |
|--------|-------------|----------|
| Workspace shape — what scaffolds in Phase 1 | Monorepo shape decision: which packages, which apps, what gets a runnable stub | ✓ |
| DataSource protocol surface + error model | Method set, sync/async, error model, CDP-disconnect surfacing, Twelve Data adapter timing | |
| instruments.py registry shape + v1 symbol set | Pydantic vs dataclass vs YAML, symbol set, session-time SoT | |
| DuckDB schema + seed_bars.py + runs-table | Composite PK, rollover detection, CLI shape, idempotency, runs-table fields | |

**User's choice:** Workspace shape only
**Notes:** The other 3 areas were explicitly deferred. After the area completed, the user delegated those to Claude's Discretion ("proceed with next steps the way you see fit").

---

## Workspace shape

### Sub-question 1: Does the Next.js / Tailwind / TypeScript frontend ship in Phase 1?

| Option | Description | Selected |
|--------|-------------|----------|
| Scaffold a runnable JS stub in Phase 1 (Recommended) | Next.js 16.2 + React 19 + TS 5 + Tailwind; lightweight-charts + TanStack Query + Zustand installed but unused; placeholder page; `pnpm dev`/`build`/`tsc --noEmit` all work | ✓ (via Claude's discretion) |
| Python-only scaffold; defer JS to Phase 3 | No `apps/web/` yet; Phase 3 owns the entire frontend bootstrap | |
| Skeleton-only JS scaffold (package.json + tsconfig, no runtime) | Half-built JS: pnpm-workspace shape committed but `pnpm dev` doesn't work | |

**User's choice:** "create based on what you know"
**Notes:** Treated as Claude's discretion. Selected the recommended option based on (a) ROADMAP Phase 1 explicitly listing `apps/web/` as a deliverable, (b) PROJECT.md committing to Next.js 16.2 + lightweight-charts 5.2.0 + pnpm workspaces for v1, (c) Phase 3 staying focused on the integration gate rather than frontend bootstrap, (d) Windows JS-toolchain risk being cheaper to discover now than during Phase 3's vertical-MVP push.

### Sub-question 2: Python directory shape — how many uv-workspace packages?

| Option | Description | Selected |
|--------|-------------|----------|
| 3-package split per PROJECT.md (Recommended) | `packages/{trading-core,api,tv-bridge}`; each is its own uv-workspace member; `tv-bridge/` reserved for Phase 6 | ✓ |
| Single-package layout: `apps/api/` only | One pyproject.toml; refactor needed before Phase 6 | |
| 2-package split: `trading-core` + `api`, defer `tv-bridge` to Phase 6 | Compromise: no empty `tv-bridge/` until it has code | |

**User's choice:** "proceed with option 1"
**Notes:** Locked the PROJECT.md-committed shape with `tv-bridge/` as an empty importable Python package in Phase 1 (no implementation, just `__init__.py` + `pyproject.toml` + `tests/`).

### Sub-question 3: Internal structure of `packages/trading-core/`

| Option | Description | Selected |
|--------|-------------|----------|
| Domain-grouped modules (Recommended) | `data/`, `strategy/`, `risk/`, `execution/`, `events/` subpackages; each with `protocols.py` + `models.py`; `instruments.py` at top level | ✓ |
| Flat: all protocols in one file, all models in one file | Single `protocols.py` + single `models.py`; simpler to navigate but balloons over time | |
| Domain-grouped subpackages, no inner files | `__init__.py` exports as the source of truth; shortest imports but harder to grep | |

**User's choice:** Domain-grouped modules (Recommended)
**Notes:** Locked the concrete module shape with adjacent `protocols.py` + `models.py` files per domain. `EventBus` lives at `trading_core.events.bus`. `instruments.py` stays at the top of `trading_core` because it crosses every domain.

### Sub-question 4: Test organization

| Option | Description | Selected |
|--------|-------------|----------|
| Per-package `tests/` next to each `src/` (Recommended) | Each package owns its tests; repo-root pytest discovers via uv-workspace; shared fixtures in `trading-core/tests/conftest.py` re-exported via `pytest_plugins` | ✓ |
| Single repo-root `tests/` tree | Simpler one-command run; deviates from per-package coverage-gate alignment | |
| Hybrid: trading-core tests in package; integration tests at root | Unit tests close to code; integration concerns visible at top | |

**User's choice:** Per-package tests/ next to each src/ (Recommended)
**Notes:** Coverage gates from PROJECT.md (`risk/`, `execution/`, `backtest/`) map cleanly to per-package paths. Synthetic ORB day fixture + DST-transition fixtures (`2026-03-08`, `2026-11-01`) live in `packages/trading-core/tests/conftest.py`.

---

## Where-to-next prompt (post-discussion)

| Option | Description | Selected |
|--------|-------------|----------|
| I'm ready — write CONTEXT.md (Recommended) | Lock the 4 Workspace decisions; flag remaining 3 areas as Claude's Discretion | ✓ (via Claude's discretion) |
| Discuss DataSource protocol surface + error model | ~4 sub-questions: method set, async, error model, CDP-disconnect, Twelve Data timing | |
| Discuss instruments.py registry + v1 symbol set | ~4 sub-questions: shape, symbol set, session-time SoT | |
| Discuss DuckDB schema + seed_bars.py + runs-table | ~4 sub-questions: PK shape, rollover detection, CLI, idempotency, runs-table fields | |

**User's choice:** "Please proceed with next steps the way you see fit"
**Notes:** Treated as Claude's discretion. Selected the "write CONTEXT.md" path with the remaining 3 areas flagged as Claude's Discretion + bounded by explicit guardrails the planner must honor (async DataSource, Pydantic registry, ES+MES+SPY symbol set, INSERT OR REPLACE idempotency, full `runs` field set this phase).

---

## Claude's Discretion

The user delegated 4 implementation choices to Claude:

1. **JS scaffold question** ("create based on what you know") — locked to the recommended runnable-stub option (D-01).
2. **DataSource protocol surface + error model** — guardrails written into CONTEXT.md (async; tz-aware UTC inputs; pandas.DataFrame returns; specific exceptions; CDP-disconnect via EventBus event; Twelve Data adapter ships in Phase 1, not Phase 3).
3. **`instruments.py` shape + v1 symbol set** — guardrails: Pydantic v2 BaseModel (not YAML, not dataclasses); ES + MES + SPY symbols only; session_times derived from `pandas_market_calendars` (single SoT); pricing fields required and frozen at registration.
4. **DuckDB schema + `seed_bars.py` + `runs` table scope** — guardrails: composite PK `(symbol, timeframe, ts)`; calendar-method rollover detection (NOT volume heuristic); `INSERT OR REPLACE` idempotency; `rich` progress bar; full `runs` field set shipping this phase (run_id uuid7, git_sha, data_hash, param_hash, seed, adr_hash, started_at, finished_at, status, notes).

The planner and plan-checker will validate these guardrails are honored in PLAN.md.

---

## Deferred Ideas

- CI lane (GitHub Actions / Windows runner) — Phase 8 owns this; Phase 1 uses pre-commit hooks instead.
- `prometheus-client` / Grafana / Plotly heatmap deps — out of scope per PROJECT.md §"Observability"; structlog only in Phase 1.
- Full TVBridge supervisor (auto-launch, overlay registry, restart-resilience) — Phase 6 home.
- Pre-commit framework choice (pre-commit.com vs raw `.git/hooks`) — planner picks; default lean toward pre-commit.com for cross-platform parity.
- JS test framework — Phase 3 owns when the JS side has logic to test; Phase 1 ships zero JS tests.
