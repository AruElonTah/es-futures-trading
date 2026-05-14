# Phase 1: Foundation + Data In - Context

**Gathered:** 2026-05-14
**Status:** Ready for planning

<domain>
## Phase Boundary

A scaffolded monorepo with repo-wide UTC/RTH discipline can backfill RTH-only ES/SPY bars from the configured `DataSource` into DuckDB + Parquet with idempotent upserts, gap detection, and rollover-seam flags. All four `Protocol` seams (`DataSource`, `Strategy`, `RiskManager`, `Executor`) are *defined* even though only `DataSource` has live implementations. `EventBus` (asyncio in-process) ships so Phase 3 can wire bars → strategy → risk → executor without re-plumbing. The `runs` table infrastructure ships here; CI reproducibility test (FND-08) is introduced in Phase 3 when an equity curve exists to compare.

**In scope:** uv workspace + pyproject.toml + uv.lock; `pnpm` workspace + `pnpm-lock.yaml`; runnable `apps/web/` Next.js stub; `packages/{trading-core,api,tv-bridge}`; `instruments.py` SoT; `DataSource` Protocol with TV-primary impl + Twelve-Data secondary impl on SPY; DuckDB schema (`bars`, `bar_gaps`, `runs`, `instruments`); `seed_bars.py` CLI; pre-commit hooks (no-naive-tz + gitleaks); per-package pytest with hypothesis property-based risk-math tests; DST-transition test fixtures.

**Out of scope:** strategy logic (Phase 2); backtester (Phase 3); ORB box / signal arrows / chart markers (Phase 3); optimization (Phase 4); full risk manager (Phase 5); TVBridge supervisor (Phase 6); UI panels beyond a placeholder home page (Phases 3 + 7); operational hardening + Replay (Phase 8).

</domain>

<decisions>
## Implementation Decisions

### Workspace Shape

- **D-01: JS scaffold ships in Phase 1.** A *runnable* Next.js 16.2 stub in `apps/web/` — App Router, React 19, TypeScript 5.x, Tailwind with default config. `lightweight-charts@5.2.0`, `@tanstack/react-query@5.x`, and `zustand@5.x` are installed but unused in this phase. `app/page.tsx` renders a placeholder ("ES Trading System — Phase 3 will render charts here"). Acceptance: `pnpm dev` runs on Windows; `pnpm build` succeeds; `tsc --noEmit` passes. Rationale: discovers Windows JS-toolchain issues now instead of mid-Phase-3 vertical-MVP push; aligns with PROJECT.md's published shape; Phase 3 just adds real pages.

- **D-02: 3-package Python split per PROJECT.md.** `packages/trading-core/` (domain + protocols + `instruments.py` + indicators landing in Phase 2), `packages/api/` (FastAPI app, WebSocket fan-out), `packages/tv-bridge/` (Phase 6 home, scaffolded as an *empty importable Python package* with `__init__.py` + `pyproject.toml` + `tests/` in Phase 1 — no implementation code yet). Each package is its own uv-workspace member. Import paths look like `from trading_core.data.protocols import DataSource`. Rationale: matches PROJECT.md's stack commitment; reserves Phase 6's home so the tv-bridge isn't an afterthought refactor.

- **D-03: Domain-grouped modules inside `trading-core`.** Concrete module shape:
  ```
  packages/trading-core/src/trading_core/
    __init__.py
    instruments.py             # SoT registry (tick_value, point_value, session_times)
    data/
      __init__.py
      protocols.py            # DataSource Protocol
      models.py               # Bar (Pydantic v2)
    strategy/
      __init__.py
      protocols.py            # Strategy Protocol (signature only; logic in Phase 2)
      models.py               # Signal, StrategyContext (Pydantic v2)
    risk/
      __init__.py
      protocols.py            # RiskManager Protocol (signature only; impl in Phase 5)
      models.py               # RiskConfig (Pydantic v2)
    execution/
      __init__.py
      protocols.py            # Executor Protocol (signature only; impl in Phase 5)
      models.py               # Fill (Pydantic v2)
    events/
      __init__.py
      bus.py                  # EventBus (asyncio in-process pub/sub)
      models.py               # Event base + concrete event types
    storage/
      __init__.py
      duckdb_store.py         # DuckDB connection, schema, upserts
      schema.sql              # bars, bar_gaps, runs, instruments tables
    calendars/
      __init__.py
      rth.py                  # RTH session filter, DST handling via pandas_market_calendars
  ```
  Rationale: each domain owns its protocol + models in adjacent files; downstream packages (`api`, `tv-bridge`) import only the seams they need (`trading_core.data`, `trading_core.events`); no circular-import risk because models don't reference Protocols.

- **D-04: Per-package `tests/` next to each `src/`.** `packages/trading-core/tests/`, `packages/api/tests/`, `packages/tv-bridge/tests/`. Each package owns its tests and is independently runnable via `cd packages/<name> && pytest`. Repo-root `pytest` discovers all of them via the uv-workspace. Shared fixtures (synthetic ORB day, DST-transition bars, `2026-03-08`/`2026-11-01` test cases) live in `packages/trading-core/tests/conftest.py` and are re-exported via a `pytest_plugins` entry in each downstream package's `conftest.py`. Coverage gates from PROJECT.md (`risk/`, `execution/`, `backtest/`) map directly to `packages/trading-core/src/trading_core/{risk,execution}/**` and the future `packages/api/src/.../backtest/` once Phase 3 ships.

### Claude's Discretion

The remaining three gray areas were deferred to the researcher and planner with the following guardrails:

- **DataSource protocol surface + error model** — Researcher/planner pick a concrete shape from the constraints: async (PROJECT.md leans async), tz-aware UTC `datetime` inputs, returns `pandas.DataFrame` for `get_bars`, raises specific exceptions (`DataSourceUnavailable`, `RateLimited`, `GapDetected`) — but the planner may also model CDP-disconnect as an event published on the bus (not a raised exception) given the operator's interest in surfacing degraded state via the UI banner (PROJECT.md §"degraded state"). **Twelve Data adapter ships in Phase 1** per FND-10's mandate that the ADR named it as the v1 secondary feed — defer-to-Phase-3 would orphan FND-10 evidence.

- **`instruments.py` registry shape + v1 symbol set** — Pydantic v2 `BaseModel` registry (NOT YAML, NOT dataclasses) for type-checking parity with the rest of the codebase. **Symbols shipping in v1: ES, MES, SPY.** Specific contract months (ESM2026, ESU2026) are tracked via the rollover-seam detector, not as separate registry entries. Session times derive *exclusively* from `pandas_market_calendars` (single source of truth); `instruments.py` records the *calendar name* (`"CME_Equity"` / `"NYSE"`), not duplicated times. Pricing fields (`tick_value`, `point_value`, `tick_size`) are required and frozen at registration time.

- **DuckDB schema + `seed_bars.py` ergonomics + `runs`-table scope** — Composite primary key `(symbol, timeframe, ts)` on `bars`. Rollover seam detected via the *calendar method* (3rd-Friday-of-Mar/Jun/Sep/Dec per `pandas_market_calendars` CME equity-index conventions) — NOT volume-jump heuristic (CLAUDE.md §"Hand-rolled" notes that 20-line functions are easier to test than upstream definitions). `seed_bars.py` CLI: `python scripts/seed_bars.py --symbol SPY --tf 1m --from 2024-01-01 --to 2024-02-01 [--provider twelvedata]`. Idempotency: `INSERT OR REPLACE` keyed on the composite PK (DuckDB native). Progress: `rich` library progress bar (already a transitive dep of `structlog`'s nice tracebacks; no new explicit dep). **`runs` table fields shipping in Phase 1 (full set per ROADMAP §4):** `run_id` (uuid7 — time-sortable per CLAUDE.md §audit log), `git_sha`, `data_hash` (sha256 of seeded-bar payload), `param_hash` (sha256 of CLI arg dict, JSON-canonicalized), `seed` (integer; defaults to 42), `adr_hash` (sha256 of `.planning/decisions/0001-data-provider.md` bytes), `started_at`, `finished_at`, `status` (`ok`/`failed`/`partial`), `notes` (free text).
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Architecture + Stack

- `.planning/PROJECT.md` — Project value, requirements, tech-stack picks, "What NOT to use" table. The Stack Summary table is the master version pin.
- `CLAUDE.md` — Project instructions, version matrix, conventions guidance, GSD workflow enforcement.
- `.planning/ROADMAP.md` §"Phase 1: Foundation + Data In" — Goal, success criteria, requirements mapping (FND-01..09 + MD-01..09), Notes.
- `.planning/REQUIREMENTS.md` — Requirement spec (the 18 FND + MD rows targeted by this phase).

### Decisions Already Locked

- `.planning/decisions/0001-data-provider.md` — TV MCP primary + Twelve Data SPY secondary + Databento as named swap. Hashed into `runs.adr_hash` for every Phase 4+ optimization run (FND-08, OPT-04). **Editing post-commit requires a superseding ADR — do NOT amend.**

### Phase 0 Spike Evidence (referenced by ADR; useful for planner)

- `.planning/research/spike-0/twelvedata-probe.json` — Live ES/SPY probe results. Phase 1's Twelve Data adapter must replicate the redaction + rate-limit-header reading patterns.
- `.planning/research/spike-0/spy-bar-budget.md` — 196,560-bar / 40-call / ~5-min wall-clock backfill budget at 9 s pacing. `seed_bars.py` pacing should default to 9 s on Free tier with retry-on-429.
- `.planning/research/spike-0/tv-mcp-tools.json` — 81 tools available on `tradingview-mcp-jackson` v2.0.0; the 4 load-bearing tools (`tv_health_check`, `chart_set_symbol`, `chart_set_timeframe`, `data_get_ohlcv`) are confirmed present.
- `.planning/research/spike-0/tv-mcp-transcript.log` — Reference for the canonical happy-path call sequence Phase 1's TV `DataSource` adapter should replicate.
- `.planning/phases/00-provider-validation-spike/00-02-SUMMARY.md` §"Decisions Made" — Critical operational findings for the TV adapter: CDP-mode launch requirement (Phase 6 owns bootstrap; Phase 1 assumes CDP is up), mid-restart partial-load state (`api_available=true` gate), `quote_get` returns bar-start time not last-tick time.

### Calendar + RTH Discipline

- `pandas_market_calendars` v5.x — `mcal.get_calendar("CME_Equity")` / `mcal.get_calendar("NYSE")` + `.schedule(start_date, end_date)`. Half-day handling (Black Friday, Christmas Eve) is the test target.
- DST-transition fixtures must cover **`2026-03-08`** (spring forward) and **`2026-11-01`** (fall back) per ROADMAP Phase 1 Success Criterion #3.

### What NOT to Use (PROJECT.md §"What NOT to Use" — re-read before adding any dep)

- pandas 3.0 (use 2.2.x); Python 3.13+ (use 3.11/3.12); Poetry (use uv); `requests` / `aiohttp` (use httpx); `pandas-ta` original (use `pandas-ta-classic` or hand-roll); socket.io (use native WebSocket); Loguru (use structlog); Postgres / SQLite (use DuckDB); `backtrader` / `zipline` / `backtesting.py` (use vectorbt — but vectorbt does not ship in Phase 1; it ships in Phase 3); `yfinance` as primary feed (only sanity-check use); Conda (use uv); Docker (out of scope).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets

- `scripts/spike/twelvedata_probe.py` — Stdlib-only HTTP probe pattern. **Do NOT import** (carries `PHASE 0 SPIKE — DO NOT IMPORT FROM PRODUCTION CODE` sentinel). Phase 1's Twelve Data adapter is a fresh httpx-based implementation; the spike pattern is a *reference* for how to read rate-limit headers and how to handle 429 (exit-not-retry on free tier).
- `scripts/spike/tv_mcp_smoke.py` — Async MCP client pattern using `mcp.ClientSession` + `stdio_client`. **Do NOT import.** Phase 1's TV adapter (which will eventually become Phase 6's `TVBridge`) consumes the same SDK but the spike's allowlist + restore-on-exit are spike-only patterns; Phase 6 owns the production version. Phase 1's TV adapter is the *thin DataSource shim* that talks to an already-running CDP-enabled TV via the MCP server — it does NOT own CDP bootstrap.

### Established Patterns

- **Stdout UTF-8 reconfiguration on Windows** — every script that may run via piped stdout must reconfigure `sys.stdout` / `sys.stderr` to `errors="replace"` at script entry. Discovered in Phase 0 Plan 2 (cp1252 trap). This becomes a base-class behavior in `trading_core` (e.g., a `setup_logging()` helper).
- **API-key redaction sentinel** — Phase 0 established the `<TWELVEDATA_API_KEY>` redaction pattern in JSON outputs. Phase 1's adapter must use the same sentinel when writing structured logs (`structlog`) so audit logs never carry the raw key.
- **Atomic per-plan commit** — Phase 0 used one commit per plan (not per task). Phase 1's planner should decide commit granularity based on each task's deviation surface — for hermetic infrastructure tasks (scaffold uv workspace, write pyproject.toml), per-task commits are fine; for tasks that build on each other (write DataSource Protocol + write TV impl + write Twelve Data impl), batch into one commit per plan.

### Integration Points

- `.planning/decisions/0001-data-provider.md` content-addressing — Phase 1's `runs` table writer must compute `sha256(adr_bytes)` at run start and store it. Phase 4+ optimization runs will hash this same file; the chain of hashes is the audit trail.
- `.gitignore` and `.env.example` (from Phase 0 Plan 1) — Already commit-clean for `.env` exclusion. Phase 1 extends with `.venv-spike/` (already done) and `.venv/` (the real one), plus DuckDB files in a writable location (e.g., `data/duckdb/*.duckdb`) and Parquet under `data/parquet/`.
- TV CDP bootstrap — Phase 1's TV adapter assumes CDP is already enabled (operator launched TV via Phase 6's eventual `tv_launch` mechanism, or manually with `--remote-debugging-port=9222`). Phase 1's adapter does NOT launch TV. CDP-disconnect surfaces via the EventBus (`DegradedState` event); Phase 3 wires it to a UI banner.

</code_context>

<specifics>
## Specific Ideas

- **Windows-first development.** All scripts must work via the absolute Python path `C:\Users\Admin\AppData\Local\Programs\Python\Python312\python.exe` because the Microsoft Store stub shadows `python` on the operator's PATH. The `uv` install path resolves this (uv pinned interpreter), but documentation should call this out so future shell-based scripts include the absolute path or use `uv run`.
- **The repo path contains a space (`C:\Users\Admin\Desktop\Day Trading`).** All path handling must use `pathlib.Path` — never string concatenation. PowerShell here-strings or shell quoting must be inspected at every shell-out site.

</specifics>

<deferred>
## Deferred Ideas

- **CI lane (GitHub Actions / Windows runner).** PROJECT.md mentions a reproducibility CI gate that's introduced in Phase 3 and expanded in Phase 8. Phase 1 should NOT ship a CI workflow — Phase 8 owns that. Pre-commit hooks are the Phase 1 enforcement surface.
- **`prometheus-client` / Grafana / Plotly heatmap deps.** Out of scope for Phase 1 per PROJECT.md §"Observability". Phase 1 ships structlog only; metrics endpoints land in Phase 3, real dashboards (if ever) land in Phase 7+.
- **TVBridge supervisor proper.** Phase 6 owns the auto-launch (`tv_launch`), restart-resilience, and overlay registry. Phase 1's TV `DataSource` is the thin shim that assumes CDP is up.
- **Pre-commit framework choice (pre-commit.com vs raw `.git/hooks`).** Planner picks based on Phase 1 RESEARCH.md once it spawns; default to `pre-commit.com` framework with `.pre-commit-config.yaml` for cross-platform parity.
- **Test-runner choice for the JS side.** PROJECT.md does not commit to a JS test framework. Defer to Phase 3 when the JS side actually has logic to test; Phase 1's `apps/web/` ships zero JS tests.

</deferred>

---

*Phase: 01-foundation-data-in*
*Context gathered: 2026-05-14*
