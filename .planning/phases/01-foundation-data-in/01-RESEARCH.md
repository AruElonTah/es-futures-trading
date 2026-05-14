# Phase 1: Foundation + Data In — Research

**Researched:** 2026-05-14
**Domain:** Python monorepo scaffolding + market-data ingestion (RTH-only, tz-aware UTC) + DuckDB persistence with idempotent upserts + 4-Protocol seam definitions + Next.js stub
**Confidence:** HIGH on locked stack (versions verified live), HIGH on architectural seam shapes, MEDIUM on a handful of edge-case behaviors flagged in Open Questions

## Summary

Phase 1 builds the foundation that every later phase plugs into without re-plumbing. The work splits cleanly along four lines: (a) **workspace scaffold** (uv Python workspace + pnpm JS workspace + a runnable Next.js 16.2 stub), (b) **the four Protocol seams** (`DataSource` with two live impls, plus `Strategy`/`RiskManager`/`Executor` signature-only stubs), (c) **the persistence layer** (DuckDB schema + Hive-partitioned Parquet + the `seed_bars.py` CLI + `runs` table for reproducibility), and (d) **the discipline rails** (pre-commit gates for naive timestamps and leaked secrets, DST-transition tests, structlog audit pipeline). Every CONTEXT.md lock is preserved — the research below assumes them.

The critical pre-resolved questions are:
1. **CME_Equity calendar covers the 23-hour Globex session, NOT 9:30-16:00 ET.** Section "Architecture Pattern: RTH Window Derivation" below resolves this with a hybrid approach (CME calendar for trading-day determination + half-day flags, then a manual 9:30-16:00 ET intra-day window filter).
2. **DuckDB `INSERT OR REPLACE` has known silent-fail edge cases** in transactions on PK tables (Issues #14133, #20743). The planner should default to the explicit `INSERT INTO ... ON CONFLICT (pk) DO UPDATE SET col = EXCLUDED.col` form for robustness.
3. **uv and pnpm are NOT installed on the operator's machine** (verified: `where.exe uv` returns nothing; `node` exists at `C:\Program Files\nodejs\node.exe`; `python` resolves to the WindowsApps stub). The first task of Plan 1 MUST install both, then re-verify with `uv --version` / `pnpm --version`.
4. **Phase 1 ships the `runs` table writer + `data_hash` / `param_hash` / `adr_hash` computation but does NOT ship the reproducibility CI test** — that is introduced in Phase 3 (it needs an equity curve to compare). Plan should make this distinction explicit so the planner doesn't accidentally pull Phase 3 work in.

**Primary recommendation:** Plan as **6 plans** organized into **3 waves** (see Plan Structure Recommendation at the bottom). Wave A scaffolds the empty workspace; Wave B fans out into the data-layer trio (Protocols + DataSources + DuckDB/seed) that can run in parallel because they touch disjoint module trees; Wave C closes the loop with discipline rails (pre-commit + EventBus + smoke test).

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**D-01: JS scaffold ships in Phase 1.** A *runnable* Next.js 16.2 stub in `apps/web/` — App Router, React 19, TypeScript 5.x, Tailwind with default config. `lightweight-charts@5.2.0`, `@tanstack/react-query@5.x`, and `zustand@5.x` are installed but unused in this phase. `app/page.tsx` renders a placeholder ("ES Trading System — Phase 3 will render charts here"). Acceptance: `pnpm dev` runs on Windows; `pnpm build` succeeds; `tsc --noEmit` passes. Rationale: discovers Windows JS-toolchain issues now instead of mid-Phase-3 vertical-MVP push.

**D-02: 3-package Python split per PROJECT.md.** `packages/trading-core/` (domain + protocols + `instruments.py` + indicators landing in Phase 2), `packages/api/` (FastAPI app, WebSocket fan-out), `packages/tv-bridge/` (Phase 6 home, scaffolded as an *empty importable Python package* with `__init__.py` + `pyproject.toml` + `tests/` in Phase 1 — no implementation code yet). Each package is its own uv-workspace member. Import paths look like `from trading_core.data.protocols import DataSource`.

**D-03: Domain-grouped modules inside `trading-core`.** Concrete module shape (locked verbatim from CONTEXT.md):
```
packages/trading-core/src/trading_core/
  __init__.py
  instruments.py
  data/{__init__.py, protocols.py, models.py}
  strategy/{__init__.py, protocols.py, models.py}
  risk/{__init__.py, protocols.py, models.py}
  execution/{__init__.py, protocols.py, models.py}
  events/{__init__.py, bus.py, models.py}
  storage/{__init__.py, duckdb_store.py, schema.sql}
  calendars/{__init__.py, rth.py}
```

**D-04: Per-package `tests/` next to each `src/`.** Shared fixtures (synthetic ORB day, DST-transition bars, `2026-03-08`/`2026-11-01` test cases) live in `packages/trading-core/tests/conftest.py` and are re-exported via `pytest_plugins` in each downstream package's `conftest.py`. Repo-root `pytest` discovers all of them via the uv-workspace.

### Claude's Discretion

- **DataSource protocol surface + error model** — Researcher/planner pick a concrete shape: async, tz-aware UTC `datetime` inputs, returns `pandas.DataFrame` for `get_bars`, raises specific exceptions (`DataSourceUnavailable`, `RateLimited`, `GapDetected`). CDP-disconnect modeled as an **event published on the bus** (not a raised exception). **Twelve Data adapter ships in Phase 1** per FND-10's ADR commitment.
- **`instruments.py` registry shape + v1 symbol set** — Pydantic v2 `BaseModel` registry (NOT YAML, NOT dataclasses). **Symbols shipping in v1: ES, MES, SPY.** Specific contract months tracked via the rollover-seam detector, not as registry entries. Session times derive *exclusively* from `pandas_market_calendars` (single source of truth); `instruments.py` records the *calendar name*, not duplicated times. Pricing fields required and frozen.
- **DuckDB schema + `seed_bars.py` ergonomics + `runs`-table scope** — Composite primary key `(symbol, timeframe, ts)` on `bars`. Rollover seam detected via the calendar method (3rd-Friday-of-Mar/Jun/Sep/Dec). `seed_bars.py` CLI signature: `python scripts/seed_bars.py --symbol SPY --tf 1m --from 2024-01-01 --to 2024-02-01 [--provider twelvedata]`. Idempotency: `INSERT OR REPLACE` keyed on composite PK. Progress: `rich` library progress bar. **`runs` table fields shipping in Phase 1:** `run_id` (uuid7), `git_sha`, `data_hash`, `param_hash`, `seed` (default 42), `adr_hash`, `started_at`, `finished_at`, `status`, `notes`.

### Deferred Ideas (OUT OF SCOPE for Phase 1)

- **CI lane (GitHub Actions / Windows runner)** — Phase 8 owns that.
- **`prometheus-client` / Grafana / Plotly heatmap deps** — Out of scope.
- **TVBridge supervisor proper** — Phase 6 owns auto-launch / restart-resilience / overlay registry.
- **JS test runner choice** — Defer to Phase 3.
- Phase 1's TV `DataSource` is a thin shim that assumes CDP is already up. It does NOT bootstrap TV. CDP-disconnect surfaces via `EventBus`; the UI banner ships Phase 3.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| FND-01 | uv workspace monorepo with `packages/{trading-core, api, tv-bridge}` + `apps/web/`; `uv.lock` committed | Step 1: Workspace Scaffold (`[tool.uv.workspace]` + `members = ["packages/*"]`) — verified via uv docs |
| FND-02 | `pyproject.toml` pins Python 3.11–3.12 + `vectorbt==1.0.0` + `pandas>=2.2,<3.0` + FastAPI + Pydantic v2 + DuckDB + structlog + httpx + pytest + hypothesis + respx + freezegun | Step 1: Verified Stack Table below — every version verified against PyPI on 2026-05-14 |
| FND-03 | Pydantic Settings loader merges `.env` (gitignored) + `config/*.yaml`; `.env.example` committed | Step 2: Pydantic Settings + YAML — `.env.example` already exists from Phase 0; extend with all production keys |
| FND-04 | `gitleaks` pre-commit hook blocks API keys / `.env` content | Step 4: Pre-commit (gitleaks at `v8.24.2`, runs via `pre-commit.com` framework) |
| FND-05 | Repo-wide UTC discipline; pre-commit lints forbid `datetime.now()` / `datetime.utcnow()` without explicit timezone | Step 4: Custom local hook — `ast`-based scanner. Sample code skeleton below. |
| FND-06 | `instruments.py` SoT registry exposes pricing + session metadata for ES, MES, SPY | Step 3: Pydantic v2 BaseModel registry (skeleton below) |
| FND-07 | `EventBus` (asyncio pub/sub) with typed topics; deterministic event ordering | Step 5: In-process `asyncio.Queue`-based bus; do NOT use `broadcaster` (overkill — alpha status, designed for multi-backend Redis/Kafka). Skeleton below. |
| FND-08 | `runs` table logs `git_sha / data_hash / param_hash / seed`; reproducibility CI introduced Phase 3 | Step 6: `runs` table writer ships Phase 1; CI test is Phase 3. Hash recipes below. |
| FND-09 | `structlog` JSON logging with correlation IDs across async boundaries | Step 7: structlog 25.5.0 + `contextvars` for correlation IDs; `WatchedFileHandler` is NOT Windows-safe — use `concurrent-log-handler` instead |
| MD-01 | `DataSource` protocol: `fetch_bars(symbol, tf, start, end) -> DataFrame[Bar]` + `subscribe_bars(symbol, tf) -> AsyncIterator[Bar]` | Step 8: `typing.Protocol` with async methods; do NOT use `@runtime_checkable` (perf cost, doesn't validate signatures). Skeleton below. |
| MD-02 | `TradingViewDataSource` via TV MCP `data_get_ohlcv`; reconnects on restart | Step 8: Reuse Phase 0 spike pattern; assume CDP up; surface disconnect via `DegradedStateEvent` on bus. Phase 1 ships read-only adapter (no draw). |
| MD-03 | `TwelveDataSource` REST for SPY 1m/5m/15m | Step 8: Raw httpx (NOT the `twelvedata` Python SDK — see "Don't Hand-Roll" entry). 9-second default pacing. Read `/time_series` rate-limit headers. |
| MD-04 | Bars to DuckDB + Hive-partitioned Parquet; composite PK `(symbol, tf, ts_utc)`; single-writer FastAPI process | Step 9: DuckDB schema + `INSERT INTO ... ON CONFLICT DO UPDATE` (NOT `INSERT OR REPLACE` — known silent-fail bugs). Hive partition: `symbol=/year=/month=`. |
| MD-05 | RTH filter uses **CME equity-index calendar** including half-days/holidays | Step 10: HYBRID — use CME_Equity for trading-day determination + half-day flag; use manual 09:30–16:00 ET window filter for intra-day. CME_Equity covers the 23-hour Globex session, not the cash session. |
| MD-06 | Bar timestamps documented as **open-time** (TV + Twelve Data convention) | Step 9: Document in `Bar` model + `bars` DDL column comment |
| MD-07 | Bar-gap detector writes missing bars to `bar_gaps` table | Step 9: Compute expected RTH timestamps via `mcal.date_range()`; diff against ingested |
| MD-08 | Continuous-contract rollover-seam: 3rd-Friday-of-Mar/Jun/Sep/Dec; `rollover_seam: bool` column | Step 10: Hand-rolled calendar method (20 lines). NOT volume-jump heuristic. Skeleton below. |
| MD-09 | CLI `seed_bars.py --symbol --tf --from --to` backfills via configured `DataSource` | Step 11: Skeleton below. Uses `rich.progress` for UX; emits `runs` row on completion. |
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Bar fetching (HTTP / MCP) | trading-core (`data/`) | — | Pure I/O behind the Protocol seam. Adapters live next to the contract they implement. |
| Bar persistence (DuckDB + Parquet) | trading-core (`storage/`) | — | Storage is a domain concern, not an API concern. The single-writer convention (MD-04) is enforced by the FastAPI process **holding** the writer connection from `trading-core.storage` — the FastAPI process owns the lifetime; `storage/` owns the schema and queries. |
| RTH window filtering | trading-core (`calendars/`) | — | Calendar semantics belong with domain models, not in the adapter layer (so both TV and Twelve Data impls share one filter). |
| Pydantic models (`Bar`, `Signal`, `Fill`, `RiskConfig`) | trading-core (per-domain `models.py`) | — | Models are shared contracts; both adapters and the future engine consume them. |
| `EventBus` | trading-core (`events/`) | — | Pure in-process pub/sub. No I/O. No FastAPI dependency. |
| `instruments.py` SoT registry | trading-core (root module) | — | Top-level because every domain reads it. |
| `seed_bars.py` CLI | scripts/ (repo root) | trading-core (imports `DataSource`, `DuckDBStore`, `RthFilter`) | CLIs orchestrate domain modules — they don't ship inside a package |
| `runs` table writer | trading-core (`storage/`) | scripts/ | Writer lives in storage; CLIs and (future) engines compose it |
| Next.js stub page | apps/web (`app/page.tsx`) | — | Frontend tier only. No backend wiring this phase. |
| FastAPI app shell | packages/api | trading-core | API ships an empty `app = FastAPI()` + a single `GET /health` endpoint to prove the import graph works. Real endpoints land Phase 3. |
| TV MCP smoke (`tv-bridge`) | packages/tv-bridge | trading-core | Empty importable package; `__init__.py` only. Implementation Phase 6. |
| Pre-commit hooks | repo-root tooling | — | Hooks aren't a package — they're tooling that gates every package |

## Standard Stack (verified versions 2026-05-14)

### Core
| Library | Version (verified) | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `uv` (Astral) | **0.11.14** (May 12, 2026) | Python workspace + venv + lock | 10-100× faster than pip; platform-resolution-complete `uv.lock` (critical for reproducibility); single binary replaces pyenv+pip+pip-tools+Poetry [VERIFIED: PyPI] |
| `pnpm` | **9.x** (use `corepack enable` to pin via `packageManager` field) | JS workspace | Content-addressed `node_modules`; workspaces; no phantom deps [CITED: Next.js docs] |
| Python | **3.11 minimum, 3.12 target** | Language runtime | 3.11 brings asyncio speedups; 3.12 free-threading prep; **DO NOT use 3.13** (wheel lag per CLAUDE.md) |
| Node.js | **20.9+** | JS runtime | Required by Next.js 16 [VERIFIED: nextjs.org/docs] |
| `pandas` | **>=2.2,<3.0** | Bar DataFrames | vectorbt 1.0.0 has not certified pandas 3.0 — must pin upper bound [CITED: CLAUDE.md "What NOT to Use"] |
| `pydantic` | **2.13.4** (May 6, 2026) | Validation for Bar/Signal/Fill/RiskConfig/InstrumentRegistry | Rust-cored; mandatory for FastAPI 0.136+ [VERIFIED: PyPI] |
| `fastapi` | **0.136.1** (Apr 23, 2026) | API shell (real endpoints Phase 3) | Pydantic v2 native; WebSocket support [VERIFIED: PyPI] |
| `uvicorn[standard]` | **0.32.x** | ASGI server | Standard extra; uvloop skipped on Windows automatically [CITED: PROJECT.md] |
| `duckdb` | **1.x latest** | Storage engine | Embedded OLAP; native Parquet; `TIMESTAMPTZ` |
| `pyarrow` | **>=17** | Parquet engine for DuckDB | Required for Hive-partitioned writes |
| `httpx` | **0.27.x** | HTTP client for `TwelveDataSource` | Sync+async same API [VERIFIED: PROJECT.md] |
| `pandas-market-calendars` | **5.3.2** (Apr 5, 2026) | CME_Equity calendar; trading-day determination | NYSE+CME; DST-correct; zoneinfo-based [VERIFIED: PyPI] |
| `structlog` | **25.5.0** (Oct 27, 2025) | JSON audit log + correlation IDs | Processor pipeline; `AsyncBoundLogger` for async [VERIFIED: PyPI] |
| `rich` | **latest** | `seed_bars.py` progress bar | Used by `seed_bars.py` CLI; transitive of structlog tracebacks already [CITED: CONTEXT.md] |
| `uuid6` | **2025.0.1** (Jul 4, 2025) | `uuid7()` for `run_id` | stdlib `uuid` doesn't ship uuid7; this package is the canonical implementation [VERIFIED: PyPI] |
| `mcp` | **>=1.0,<2.0** | TV MCP SDK (carry over from Phase 0 spike) | Reuses pattern from `.venv-spike/`; reinstall into the real `.venv` |
| `concurrent-log-handler` | **latest** | Cross-platform rotating file log | `WatchedFileHandler` is NOT Windows-safe — see Pitfall "WatchedFileHandler on Windows" |

### Testing
| Library | Version | Purpose |
|---------|---------|---------|
| `pytest` | **8.x** | Test runner [CITED: PROJECT.md] |
| `pytest-asyncio` | **0.24.x** | `asyncio_mode = "auto"` in `pyproject.toml` for async EventBus tests |
| `hypothesis` | **6.152.x** | Property tests on `instruments.py` math (will scale to risk math in Phase 5) |
| `respx` | **latest** | httpx mock for `TwelveDataSource` tests |
| `freezegun` | **latest** | Pin time in DST/session-filter tests |
| `pytest-cov` | **latest** | Coverage gates on storage/data/calendars/events |

### Frontend (Phase 1 stub only)
| Library | Version | Purpose |
|---------|---------|---------|
| `next` | **16.2.6** (May 13, 2026 — current as of research date) | App Router, Turbopack default [VERIFIED: nextjs.org/docs] |
| `react` / `react-dom` | **19** | Stable; required by Next.js 16 |
| `typescript` | **5.x** | Required |
| `lightweight-charts` | **5.2.0** | Installed but UNUSED in Phase 1 [VERIFIED: npm] |
| `@tanstack/react-query` | **v5.x** | Installed but UNUSED in Phase 1 |
| `zustand` | **5.x** | Installed but UNUSED in Phase 1 |
| `tailwindcss` | **3.x** (NOT v4) | See "Open Question: Tailwind 3 vs 4" — recommend v3 for stability |

### Tooling (repo-level)
| Library | Version | Purpose |
|---------|---------|---------|
| `pre-commit` | **latest** | Hook orchestrator; cross-platform [CITED: pre-commit.com] |
| `gitleaks` | **v8.24.2** | Secret-scanner hook [VERIFIED: gitleaks/gitleaks README] |

**Installation order (Plan 1 first task):**
```powershell
# 1. Install uv (Windows PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# 2. Enable corepack to get pnpm pinned
corepack enable
corepack prepare pnpm@9.15.0 --activate

# 3. Verify
uv --version    # expect 0.11.x
pnpm --version  # expect 9.x
node --version  # expect 20.9+
```

### Alternatives Considered

| Instead of | Could Use | Tradeoff / Why Rejected |
|------------|-----------|--------------------------|
| `uv` workspace | Poetry workspaces | 10× slower install; not platform-complete lock; community moved to uv in 2026 |
| `httpx` for Twelve Data | Official `twelvedata` Python SDK | SDK hides the rate-limit response headers the Phase 0 spike found are the ONLY reliable pacing signal (see Pitfall) |
| `broadcaster` for EventBus | hand-rolled `asyncio.Queue` pub/sub | broadcaster is alpha + designed for cross-process Redis/Kafka. Phase 1 is in-process single-operator. Adds a dep with no payoff. |
| Tailwind v4 | Tailwind v3 | v4 introduces breaking CSS-first config; less mature ecosystem; "v3 is still the safer bet" per multiple 2026 guides. |
| `@runtime_checkable` Protocol | bare `Protocol` | `isinstance()` checks against runtime-checkable Protocols are slow + don't validate signatures. Use `mypy`/`pyright` for verification. |
| `WatchedFileHandler` | `concurrent-log-handler` | `WatchedFileHandler` cannot rotate open files on Windows (Windows file locks) |
| stdlib `uuid` | `uuid6` package | stdlib has uuid1/3/4/5 only — no uuid7. PEP for uuid7 in stdlib pending; not in 3.11/3.12. |
| YAML for `instruments.py` | Pydantic v2 BaseModel | CONTEXT.md D-04 locks Pydantic v2; type-checking parity with rest of codebase |

## Architecture Patterns

### System Architecture Diagram

```
                ┌──────────────────────────────────────────────────────────┐
                │                  Phase 1 Data Flow                       │
                └──────────────────────────────────────────────────────────┘

  seed_bars.py CLI ─────────────────┐
  (--symbol SPY --tf 1m --from --to)│
                                    ▼
                          ┌─────────────────────┐
                          │  DataSource         │   <-- Protocol seam (trading_core.data.protocols)
                          │  (Protocol)         │
                          └─────────────────────┘
                                    │
                            ┌───────┴───────┐
                            ▼               ▼
               ┌───────────────────┐  ┌─────────────────────┐
               │TwelveDataSource   │  │TradingViewDataSource│
               │ httpx + .env key  │  │ mcp.ClientSession   │
               │ 9s pacing, /time_ │  │ stdio_client subproc│
               │ series headers    │  │ data_get_ohlcv      │
               └───────────────────┘  └─────────────────────┘
                            │               │
                            └───────┬───────┘
                                    ▼
                          DataFrame[Bar]     <-- bar OPEN time, tz-aware UTC
                                    │
                                    ▼
                          ┌─────────────────────┐
                          │ RthFilter           │  <-- trading_core.calendars.rth
                          │ (CME_Equity for     │
                          │  trading days &     │
                          │  half-days +        │
                          │  9:30-16:00 ET win) │
                          └─────────────────────┘
                                    │
                                    ▼
                          ┌─────────────────────┐
                          │ RolloverDetector    │  <-- 3rd Fri of Mar/Jun/Sep/Dec
                          │ (rollover_seam=T/F) │
                          └─────────────────────┘
                                    │
                                    ▼
                          ┌─────────────────────┐
                          │ GapDetector         │  <-- expected vs actual timestamps
                          │ writes bar_gaps     │
                          └─────────────────────┘
                                    │
                                    ▼
                          ┌─────────────────────┐
                          │ DuckDBStore         │  <-- trading_core.storage
                          │  INSERT INTO bars   │
                          │  ON CONFLICT (sym,  │
                          │  tf, ts) DO UPDATE  │
                          │  + COPY TO Parquet  │
                          │  PARTITION BY       │
                          │  (symbol, year,     │
                          │   month) OVERWRITE_ │
                          │   OR_IGNORE         │
                          └─────────────────────┘
                                    │
                                    ▼
                          DuckDB: bars, bar_gaps, instruments
                          Parquet: data/parquet/symbol=SPY/year=2024/month=01/...
                                    │
                                    ▼ (end of CLI run)
                          ┌─────────────────────┐
                          │ runs table writer   │  <-- run_id (uuid7), git_sha,
                          │                     │      data_hash, param_hash,
                          │                     │      seed=42, adr_hash, ...
                          └─────────────────────┘

         ┌──────── EventBus (asyncio in-process, defined but UNWIRED in Phase 1) ─────────┐
         │   topics: bars | signals | risk_decisions | fills | positions | equity         │
         │           degraded_state (TV MCP CDP disconnect surfaces here)                 │
         │   Phase 3 wires producers/consumers; Phase 1 ships the bus + a smoke test      │
         └────────────────────────────────────────────────────────────────────────────────┘

         ┌──────── Other Protocol seams (defined but no live impls in Phase 1) ───────────┐
         │   Strategy.on_bar  → Phase 2 ships ORBStrategy                                 │
         │   RiskManager.check → Phase 5 ships full impl                                  │
         │   Executor.fill    → Phase 5 ships PaperExecutor                               │
         └────────────────────────────────────────────────────────────────────────────────┘
```

Component responsibilities:

| Component | File | Responsibility |
|-----------|------|----------------|
| `DataSource` Protocol | `trading_core/data/protocols.py` | Async contract — implementations cannot bypass |
| `TwelveDataSource` | `trading_core/data/twelvedata.py` | httpx adapter; reads `/time_series` headers for pacing |
| `TradingViewDataSource` | `trading_core/data/tradingview.py` | mcp SDK adapter; assumes CDP up; publishes degraded state to bus |
| `Bar` model | `trading_core/data/models.py` | Pydantic v2; `ts_utc: AwareDatetime`; documents open-time convention |
| `RthFilter` | `trading_core/calendars/rth.py` | `is_rth(ts_utc)` + `expected_rth_timestamps(start, end, tf)` |
| `RolloverDetector` | `trading_core/calendars/rth.py` | `is_rollover_seam(ts_utc)` — 3rd Fri of quarter end months |
| `InstrumentRegistry` | `trading_core/instruments.py` | Pydantic BaseModel registry; ES/MES/SPY |
| `DuckDBStore` | `trading_core/storage/duckdb_store.py` | Connection + schema + upserts + Parquet partitioned writes |
| `schema.sql` | `trading_core/storage/schema.sql` | DDL — single source of truth for table definitions |
| `RunsWriter` | `trading_core/storage/duckdb_store.py` (same module) | Composes hashes + writes `runs` row at CLI completion |
| `EventBus` | `trading_core/events/bus.py` | `asyncio.Queue`-per-topic + `publish` / `subscribe` |
| Event models | `trading_core/events/models.py` | Pydantic events: `BarReceived`, `DegradedState`, ... |

### Recommended Project Structure

```
Day Trading/
├── pyproject.toml                    # workspace root + tooling config
├── uv.lock                           # platform-complete (committed)
├── pnpm-workspace.yaml               # JS workspace
├── pnpm-lock.yaml                    # JS lock (committed)
├── .pre-commit-config.yaml           # gitleaks + no-naive-tz
├── .gitleaks.toml                    # rules (allow <TWELVEDATA_API_KEY> sentinel)
├── .env / .env.example
├── .gitignore                        # extend: .venv/, data/duckdb/*.duckdb, data/parquet/, data/logs/
├── packages/
│   ├── trading-core/
│   │   ├── pyproject.toml
│   │   ├── src/trading_core/
│   │   │   ├── __init__.py
│   │   │   ├── instruments.py
│   │   │   ├── data/{__init__.py, protocols.py, models.py, twelvedata.py, tradingview.py}
│   │   │   ├── strategy/{__init__.py, protocols.py, models.py}
│   │   │   ├── risk/{__init__.py, protocols.py, models.py}
│   │   │   ├── execution/{__init__.py, protocols.py, models.py}
│   │   │   ├── events/{__init__.py, bus.py, models.py}
│   │   │   ├── storage/{__init__.py, duckdb_store.py, schema.sql, runs.py}
│   │   │   ├── calendars/{__init__.py, rth.py}
│   │   │   ├── config.py                  # Pydantic Settings (.env + config/*.yaml)
│   │   │   └── logging.py                 # structlog setup + stdout UTF-8 reconfigure
│   │   └── tests/
│   │       ├── conftest.py                # shared fixtures (DST days, synthetic bars)
│   │       ├── test_instruments.py
│   │       ├── test_rth_filter.py         # DST 2026-03-08 + 2026-11-01
│   │       ├── test_rollover_detector.py
│   │       ├── test_duckdb_store.py
│   │       ├── test_event_bus.py
│   │       └── test_data_sources.py       # respx-mocked Twelve Data; mock TV MCP
│   ├── api/
│   │   ├── pyproject.toml
│   │   ├── src/api/{__init__.py, app.py}  # FastAPI() + GET /health only
│   │   └── tests/{conftest.py, test_health.py}
│   └── tv-bridge/                         # EMPTY importable package — Phase 6 home
│       ├── pyproject.toml
│       ├── src/tv_bridge/__init__.py
│       └── tests/{conftest.py, test_import.py}
├── apps/web/
│   ├── package.json
│   ├── tsconfig.json
│   ├── next.config.ts
│   ├── tailwind.config.ts
│   ├── postcss.config.mjs
│   ├── app/{layout.tsx, page.tsx}         # placeholder page
│   └── public/                            # empty
├── scripts/
│   ├── seed_bars.py
│   └── spike/                             # Phase 0 carry-overs (DO NOT IMPORT)
├── config/
│   ├── system.yaml                        # placeholder for Pydantic Settings merge
│   └── strategies/                        # Phase 2+ home; empty in Phase 1
├── data/                                  # ALL gitignored
│   ├── duckdb/
│   ├── parquet/
│   └── logs/audit/
└── .planning/                             # already exists
```

### Pattern 1: `typing.Protocol` for the four seams (NO `@runtime_checkable`)

**What:** Use `typing.Protocol` for structural typing. The implementation says "duck-typed contract": any class with matching methods satisfies it.
**When to use:** All four seams (`DataSource`, `Strategy`, `RiskManager`, `Executor`). Verified by mypy/pyright, NOT by runtime `isinstance()`.
**Why no `@runtime_checkable`:** It's surprisingly slow for `isinstance()` checks AND doesn't validate signatures or return types (only method *presence*). The trading-core code is fully type-checked statically; runtime guards add overhead with no real safety.
[CITED: docs.python.org/3/library/typing.html, PEP 544; runebook.dev runtime_checkable guide]

```python
# packages/trading-core/src/trading_core/data/protocols.py
from __future__ import annotations
from datetime import datetime
from typing import AsyncIterator, Protocol
import pandas as pd

from .models import Bar  # Pydantic v2 model

class DataSourceError(Exception):
    """Base for all DataSource adapter errors."""

class DataSourceUnavailable(DataSourceError):
    """Provider is reachable but reported a service-level failure."""

class RateLimited(DataSourceError):
    """Provider returned 429 / pacing-budget exhausted."""

class GapDetected(DataSourceError):
    """Provider returned bars but with internal gaps (caller decides recovery)."""


class DataSource(Protocol):
    """Async contract every bar provider implements.

    Inputs are tz-aware UTC datetimes. Outputs are pandas DataFrames whose
    rows match `Bar` model (ts_utc=open time, UTC).
    """

    name: str  # e.g., "twelve_data" or "tradingview_mcp" — used in runs.notes

    async def fetch_bars(
        self,
        symbol: str,
        timeframe: str,        # "1m" | "5m" | "15m" — validated against InstrumentRegistry
        start: datetime,       # tz-aware UTC
        end: datetime,         # tz-aware UTC, exclusive
    ) -> pd.DataFrame:
        """Historical pull. Returns DataFrame indexed by ts_utc with bar OPEN time.

        Raises: DataSourceUnavailable | RateLimited | GapDetected
        """
        ...

    async def subscribe_bars(
        self,
        symbol: str,
        timeframe: str,
    ) -> AsyncIterator[Bar]:
        """Live polling. Yields completed bars as they close.

        Yields tz-aware UTC `Bar` instances. Polling implementations should
        sleep between yields based on timeframe. CDP/connection failures
        should be published as `DegradedStateEvent` on the bus rather than
        raised from this iterator (otherwise the caller must catch and
        re-establish — which is the bridge's job, Phase 6).
        """
        ...
```

The other three seams ship as **signature-only stubs** for Phase 1:

```python
# packages/trading-core/src/trading_core/strategy/protocols.py
class Strategy(Protocol):
    name: str
    version: str
    def warmup_bars(self) -> int: ...
    def on_bar(self, bar: Bar, ctx: "StrategyContext") -> "Signal | None": ...
```

```python
# packages/trading-core/src/trading_core/risk/protocols.py
class RiskManager(Protocol):
    async def check(self, signal: "Signal", state: "RiskState") -> "RiskDecision": ...
```

```python
# packages/trading-core/src/trading_core/execution/protocols.py
class Executor(Protocol):
    async def fill(self, signal: "Signal", decision: "RiskDecision") -> "Fill": ...
```

These are intentionally minimal — Phase 2/5 expand them with `StrategyContext` / `RiskState` / `Fill` model bodies. The signatures are locked here.

### Pattern 2: Pydantic v2 `InstrumentRegistry`

**What:** Frozen Pydantic v2 BaseModel per instrument, with a module-level `REGISTRY: dict[str, Instrument]`.
**When to use:** Anywhere dollar-denominated math reads tick_value / point_value. Lint forbids hardcoded numerics outside this file.

```python
# packages/trading-core/src/trading_core/instruments.py
from __future__ import annotations
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

CalendarName = Literal["CME_Equity", "NYSE"]

class Instrument(BaseModel):
    """Frozen instrument metadata. Mutation requires a migration ADR."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str = Field(min_length=1, max_length=10)
    description: str
    tick_size: Decimal       # smallest price increment (0.25 for ES)
    tick_value: Decimal      # dollar value per tick per contract ($12.50 for ES, $1.25 for MES, $0.01 for SPY)
    point_value: Decimal     # dollar value per 1.00 price move ($50 ES, $5 MES, $1 SPY)
    calendar_name: CalendarName  # SoT for session times; instruments.py does NOT duplicate hours
    # Open-time of cash session (used together with calendar to assemble RTH window)
    rth_open_et: str = Field(pattern=r"^\d{2}:\d{2}$")    # "09:30"
    rth_close_et: str = Field(pattern=r"^\d{2}:\d{2}$")   # "16:00"
    asset_class: Literal["future", "etf"]
    is_continuous: bool      # ES = True (front-month stitched); MES = True; SPY = False
    notes: str = ""

REGISTRY: dict[str, Instrument] = {
    "ES": Instrument(
        symbol="ES",
        description="E-mini S&P 500 futures (continuous front-month)",
        tick_size=Decimal("0.25"),
        tick_value=Decimal("12.50"),
        point_value=Decimal("50.00"),
        calendar_name="CME_Equity",
        rth_open_et="09:30",
        rth_close_et="16:00",
        asset_class="future",
        is_continuous=True,
    ),
    "MES": Instrument(
        symbol="MES",
        description="Micro E-mini S&P 500 futures (continuous front-month)",
        tick_size=Decimal("0.25"),
        tick_value=Decimal("1.25"),
        point_value=Decimal("5.00"),
        calendar_name="CME_Equity",
        rth_open_et="09:30",
        rth_close_et="16:00",
        asset_class="future",
        is_continuous=True,
    ),
    "SPY": Instrument(
        symbol="SPY",
        description="SPDR S&P 500 ETF (NYSE Arca)",
        tick_size=Decimal("0.01"),
        tick_value=Decimal("0.01"),
        point_value=Decimal("1.00"),
        calendar_name="NYSE",
        rth_open_et="09:30",
        rth_close_et="16:00",
        asset_class="etf",
        is_continuous=False,
    ),
}

def get(symbol: str) -> Instrument:
    if symbol not in REGISTRY:
        raise KeyError(f"Unknown instrument: {symbol}. Known: {list(REGISTRY)}")
    return REGISTRY[symbol]
```

Why frozen=True: trading-day session windows must be immutable for reproducibility. Mutating an instrument mid-run would silently change the meaning of every persisted bar.
Why Decimal not float: ATR-based position sizing depends on exact arithmetic; float drift produces 1-tick miscounts at boundaries.

### Pattern 3: RTH Window Derivation (HYBRID — addresses the CME_Equity 23-hour issue)

**Critical context:** `pandas_market_calendars.get_calendar("CME_Equity").schedule(...)` returns the **Globex electronic trading session** (~23 hours: 6:00 PM ET previous day to 5:00 PM ET, with a 4:15-4:35 PM ET daily break). This is **NOT** 9:30-16:00 ET. MD-05 mandates "CME equity-index calendar," but the intent is to use **CME-specific holidays/half-days** (e.g., Good Friday, July 3 when July 4 is Saturday) — not the 23-hour session window.

**Resolution:** Two-step filter — calendar for trading-day determination + manual 9:30-16:00 ET window from `instruments.py`:

```python
# packages/trading-core/src/trading_core/calendars/rth.py
from __future__ import annotations
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
import pandas as pd
import pandas_market_calendars as mcal

ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")

def trading_days(calendar_name: str, start: datetime, end: datetime) -> pd.DatetimeIndex:
    """Return UTC-midnight-anchored trading days from the given calendar.

    Excludes weekends + exchange holidays + (for CME_Equity) early-close half-days
    are still trading days but with a shortened close — caller must handle.
    """
    cal = mcal.get_calendar(calendar_name)
    sched = cal.schedule(start_date=start.date(), end_date=end.date())
    return sched.index  # DatetimeIndex of trading-day dates (tz-naive date)

def rth_window_utc(calendar_name: str, trading_day, open_et: str, close_et: str
                   ) -> tuple[datetime, datetime]:
    """Construct the (open, close) UTC bounds for the cash-session RTH window
    on `trading_day`, honoring CME_Equity early-close half-days from the
    schedule when calendar='CME_Equity'.

    For half-days, the cash session's effective close is min(close_et, market_close).
    """
    open_h, open_m = map(int, open_et.split(":"))
    close_h, close_m = map(int, close_et.split(":"))
    day_date = pd.Timestamp(trading_day).date()
    open_naive = datetime.combine(day_date, time(open_h, open_m))
    close_naive = datetime.combine(day_date, time(close_h, close_m))
    open_et_dt = open_naive.replace(tzinfo=ET)
    close_et_dt = close_naive.replace(tzinfo=ET)

    # Honor early-close half-days when present in the schedule
    cal = mcal.get_calendar(calendar_name)
    sched = cal.schedule(start_date=day_date, end_date=day_date)
    if not sched.empty:
        market_close_utc = sched.iloc[0]["market_close"]   # tz-aware UTC
        market_close_et = market_close_utc.astimezone(ET)
        if market_close_et < close_et_dt:
            close_et_dt = market_close_et   # half-day -> early close wins

    return open_et_dt.astimezone(UTC), close_et_dt.astimezone(UTC)

def is_rth(ts_utc: datetime, *, instrument_symbol: str) -> bool:
    """Inclusive on open, exclusive on close. Reads RTH bounds from instruments.py."""
    from trading_core.instruments import get
    inst = get(instrument_symbol)
    if ts_utc.tzinfo is None:
        raise ValueError("ts must be tz-aware")
    et = ts_utc.astimezone(ET)
    days = trading_days(inst.calendar_name, et, et)
    if pd.Timestamp(et.date()) not in days:
        return False
    open_utc, close_utc = rth_window_utc(inst.calendar_name, et.date(),
                                         inst.rth_open_et, inst.rth_close_et)
    return open_utc <= ts_utc < close_utc

def expected_rth_timestamps(symbol: str, timeframe: str, start: datetime, end: datetime
                            ) -> pd.DatetimeIndex:
    """Generate every expected bar OPEN timestamp inside RTH between start and end.

    Used by the gap detector. Output is tz-aware UTC.
    """
    from trading_core.instruments import get
    inst = get(symbol)
    freq = {"1m": "1min", "5m": "5min", "15m": "15min"}[timeframe]
    days = trading_days(inst.calendar_name, start, end)
    bars = []
    for d in days:
        o_utc, c_utc = rth_window_utc(inst.calendar_name, d.date(),
                                      inst.rth_open_et, inst.rth_close_et)
        # `closed='left'` -> [o_utc, c_utc) -> bar OPEN times only
        bars.append(pd.date_range(o_utc, c_utc, freq=freq, inclusive="left"))
    return pd.DatetimeIndex([]).append(bars) if bars else pd.DatetimeIndex([], tz="UTC")
```

[VERIFIED: CME_Equity hours from pandas_market_calendars/calendars/cme.py via GitHub fetch — 5:00 PM Chicago to 4:00 PM Chicago next day with 3:15-3:30 PM Chicago break]

### Pattern 4: Rollover-seam detector (hand-rolled, 20 lines)

**What:** Return True if the bar's date is on or within 1 trading day of the 3rd Friday of Mar/Jun/Sep/Dec.
**When to use:** Strategies skip `rollover_seam=True` bars (MD-08).
**Source:** Per CLAUDE.md "Hand-rolled" guidance — easier to unit-test than upstream.

```python
# Part of packages/trading-core/src/trading_core/calendars/rth.py
import calendar as _calendar

def third_friday(year: int, month: int) -> "date":
    cal = _calendar.Calendar()
    fridays = [d for d in cal.itermonthdates(year, month)
               if d.month == month and d.weekday() == _calendar.FRIDAY]
    return fridays[2]  # 3rd Friday

def is_rollover_seam(ts_utc: datetime) -> bool:
    """True on the 3rd-Friday-of-quarter and the trading day before/after."""
    if ts_utc.tzinfo is None:
        raise ValueError("ts must be tz-aware")
    et = ts_utc.astimezone(ET)
    d = et.date()
    for month in (3, 6, 9, 12):
        tf = third_friday(d.year, month)
        if abs((d - tf).days) <= 1:
            return True
    return False
```

Tests: `is_rollover_seam(2026-03-20 14:30 UTC)` → True (Friday 3/20/2026 is 3rd Friday of March 2026, ET = 10:30 AM); also test the previous Thursday and following Monday.

### Pattern 5: `EventBus` (asyncio in-process, hand-rolled — NOT broadcaster)

**What:** Topic-keyed asyncio Queue with multiple subscribers per topic, deterministic FIFO order per topic.
**When to use:** All Phase 1 needs is the bus shape — Phase 3 wires producers/consumers.
**Why hand-rolled:** `broadcaster` is alpha + multi-backend (Redis/Kafka). In-process single-operator doesn't need any of that.

```python
# packages/trading-core/src/trading_core/events/bus.py
from __future__ import annotations
import asyncio
from collections import defaultdict
from contextlib import asynccontextmanager
from typing import AsyncIterator
from .models import Event

Topic = str

class EventBus:
    """In-process asyncio pub/sub. FIFO per topic. No backpressure (queues unbounded
    for v1 — single operator, small message rate). Phase 5/7 may add bounded queues
    with drop-oldest semantics if needed."""

    def __init__(self) -> None:
        self._subscribers: dict[Topic, list[asyncio.Queue[Event]]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def publish(self, topic: Topic, event: Event) -> None:
        async with self._lock:
            queues = list(self._subscribers.get(topic, []))
        for q in queues:
            await q.put(event)

    @asynccontextmanager
    async def subscribe(self, topic: Topic) -> AsyncIterator["Subscription"]:
        q: asyncio.Queue[Event] = asyncio.Queue()
        async with self._lock:
            self._subscribers[topic].append(q)
        try:
            yield Subscription(q)
        finally:
            async with self._lock:
                self._subscribers[topic].remove(q)

class Subscription:
    def __init__(self, q: asyncio.Queue) -> None:
        self._q = q
    async def __aiter__(self) -> AsyncIterator[Event]:
        while True:
            yield await self._q.get()
```

**Topics shipping in Phase 1** (defined as `Final` string constants in `events/models.py`):
- `bars` — `BarReceived(symbol, timeframe, bar)`
- `signals` — Phase 2 producer (declared shape only)
- `risk_decisions` — Phase 5 producer (declared shape only)
- `fills` — Phase 5 producer (declared shape only)
- `positions` — Phase 5 producer (declared shape only)
- `equity` — Phase 3 producer (declared shape only)
- `degraded_state` — `DegradedStateEvent(source: str, reason: str)` — TradingViewDataSource publishes here on CDP disconnect

### Pattern 6: DuckDB Schema (with the `INSERT OR REPLACE` workaround)

```sql
-- packages/trading-core/src/trading_core/storage/schema.sql
-- Single source of truth for DDL. DuckDBStore reads this verbatim on init.
-- All timestamps are tz-aware UTC. Bar timestamps are OPEN time (MD-06 convention).

CREATE TABLE IF NOT EXISTS bars (
    symbol     VARCHAR     NOT NULL,
    timeframe  VARCHAR     NOT NULL,  -- '1m' | '5m' | '15m'
    ts_utc     TIMESTAMPTZ NOT NULL,  -- bar OPEN time, UTC (MD-06)
    open       DOUBLE      NOT NULL,
    high       DOUBLE      NOT NULL,
    low        DOUBLE      NOT NULL,
    close      DOUBLE      NOT NULL,
    volume     BIGINT      NOT NULL,
    rollover_seam BOOLEAN  NOT NULL DEFAULT FALSE,
    provider   VARCHAR     NOT NULL,  -- 'twelve_data' | 'tradingview_mcp'
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (symbol, timeframe, ts_utc)
);

CREATE TABLE IF NOT EXISTS bar_gaps (
    symbol     VARCHAR     NOT NULL,
    timeframe  VARCHAR     NOT NULL,
    ts_utc     TIMESTAMPTZ NOT NULL,
    detected_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    provider   VARCHAR     NOT NULL,
    run_id     VARCHAR,                 -- foreign key to runs.run_id (soft FK)
    PRIMARY KEY (symbol, timeframe, ts_utc)
);

CREATE TABLE IF NOT EXISTS instruments (
    symbol     VARCHAR PRIMARY KEY,
    payload    JSON NOT NULL,            -- serialized Instrument Pydantic model
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS runs (
    run_id      VARCHAR PRIMARY KEY,     -- uuid7 (time-sortable)
    git_sha     VARCHAR     NOT NULL,
    data_hash   VARCHAR     NOT NULL,    -- sha256 of bar payload (see Reproducibility Hashing)
    param_hash  VARCHAR     NOT NULL,    -- sha256 of canonical JSON CLI args
    seed        INTEGER     NOT NULL,
    adr_hash    VARCHAR     NOT NULL,    -- sha256 of .planning/decisions/0001-data-provider.md
    started_at  TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    status      VARCHAR     NOT NULL,    -- 'ok' | 'failed' | 'partial'
    notes       VARCHAR     NOT NULL DEFAULT ''
);
```

**Upsert pattern (defensive against INSERT OR REPLACE silent-fail bugs):**

```python
# Defensive form — works around #14133 and #20743
UPSERT_BAR_SQL = """
INSERT INTO bars (symbol, timeframe, ts_utc, open, high, low, close, volume, rollover_seam, provider)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (symbol, timeframe, ts_utc) DO UPDATE SET
    open = EXCLUDED.open,
    high = EXCLUDED.high,
    low = EXCLUDED.low,
    close = EXCLUDED.close,
    volume = EXCLUDED.volume,
    rollover_seam = EXCLUDED.rollover_seam,
    provider = EXCLUDED.provider,
    ingested_at = CURRENT_TIMESTAMP;
"""
```

CONTEXT.md specifies `INSERT OR REPLACE`; research finds it has silent-fail edge cases on PK tables (DuckDB #14133, #20743). The semantically-equivalent `INSERT ... ON CONFLICT DO UPDATE SET col = EXCLUDED.col` is the workaround maintainers recommend AND is what `INSERT OR REPLACE` desugars to per DuckDB's own docs. **The research recommends the explicit form** — same SQL semantics, no known footguns. The planner should treat this as a non-deviation (it's the documented expansion of the locked-in `INSERT OR REPLACE` choice).

**Hive-partitioned Parquet write (for cold storage / external readers):**

```python
# After upsert into DuckDB, also snapshot to Parquet
conn.execute("""
COPY (SELECT * FROM bars WHERE symbol = ? AND ts_utc >= ? AND ts_utc < ?)
TO 'data/parquet/bars'
(FORMAT PARQUET, PARTITION_BY (symbol, year(ts_utc), month(ts_utc)), OVERWRITE_OR_IGNORE)
""", [symbol, start_utc, end_utc])
```

`OVERWRITE_OR_IGNORE` is the right flag: it deletes existing partition directories before writing new files. For local filesystem only; remote FS doesn't support it.
[VERIFIED: duckdb.org/docs/lts/data/partitioning/partitioned_writes]

### Pattern 7: `runs` table writer + data_hash recipe

**Reproducibility hashes (FND-08 — table ships Phase 1; CI test ships Phase 3):**

```python
# packages/trading-core/src/trading_core/storage/runs.py
from __future__ import annotations
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
import uuid6
import pandas as pd

ADR_PATH = Path(".planning/decisions/0001-data-provider.md")

def git_sha() -> str:
    """Current HEAD SHA. Falls back to 'unknown' if not in a git repo."""
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"],
                                       text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return "unknown"

def adr_hash() -> str:
    """Sha256 of the verbatim ADR bytes. The chain of trust for every Phase 4+ run."""
    return hashlib.sha256(ADR_PATH.read_bytes()).hexdigest()

def param_hash(args: dict) -> str:
    """Canonical-JSON sha256 of CLI args. Sorted keys + UTF-8 bytes -> deterministic."""
    canonical = json.dumps(args, sort_keys=True, separators=(",", ":"),
                           default=str)  # date/datetime -> ISO 8601
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

def data_hash(df: pd.DataFrame) -> str:
    """Stable hash of bar payload.

    Recipe: (1) sort by (symbol, timeframe, ts_utc) to remove row-order variance;
    (2) project the columns that matter (drop ingested_at — that's mutation noise);
    (3) write to a deterministic Parquet bytes blob via pyarrow with
        compression=None + use_dictionary=False + write_statistics=False
        so the bytes are byte-stable across pyarrow patch versions; (4) sha256.
    """
    import io
    import pyarrow as pa
    import pyarrow.parquet as pq

    cols = ["symbol", "timeframe", "ts_utc", "open", "high", "low", "close",
            "volume", "rollover_seam", "provider"]
    df = df[cols].sort_values(["symbol", "timeframe", "ts_utc"]).reset_index(drop=True)
    buf = io.BytesIO()
    table = pa.Table.from_pandas(df, preserve_index=False)
    pq.write_table(table, buf, compression="none", use_dictionary=False,
                   write_statistics=False)
    return hashlib.sha256(buf.getvalue()).hexdigest()

def new_run_id() -> str:
    return str(uuid6.uuid7())
```

**Note on `data_hash`:** This is the simpler approach (project + sort + Parquet bytes). The alternative — `pd.util.hash_pandas_object().sum().to_bytes(...)` — is order-sensitive AND has known performance regressions in pandas 2.1+ ([CITED: pandas-dev/pandas#55245]). The sorted-Parquet-bytes approach is order-stable and survives library version bumps as long as we pin `compression=None`, `use_dictionary=False`, `write_statistics=False` (those three flags eliminate pyarrow's nondeterministic compression/metadata layers).

### Pattern 8: `seed_bars.py` CLI top-level shape

```python
# scripts/seed_bars.py
#!/usr/bin/env python3
"""Backfill bars from the configured DataSource into DuckDB + Parquet."""
from __future__ import annotations
import argparse
import asyncio
import sys
from datetime import datetime, timezone

# Defensive: Phase 0 lesson — Windows piped-stdout = cp1252; reconfigure to UTF-8.
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from trading_core.config import Settings
from trading_core.data.twelvedata import TwelveDataSource
from trading_core.data.tradingview import TradingViewDataSource
from trading_core.storage.duckdb_store import DuckDBStore
from trading_core.storage.runs import (
    new_run_id, git_sha, adr_hash, param_hash, data_hash
)
from trading_core.calendars.rth import RthFilter, RolloverDetector
from trading_core.logging import setup_logging, get_logger

PROVIDERS = {"twelvedata": TwelveDataSource, "tradingview": TradingViewDataSource}

async def main(args) -> int:
    log = get_logger(__name__)
    settings = Settings()
    run_id = new_run_id()
    started_at = datetime.now(timezone.utc)
    log = log.bind(run_id=run_id, symbol=args.symbol, tf=args.tf)

    provider_name = args.provider or settings.default_provider
    source = PROVIDERS[provider_name](settings)
    rth = RthFilter()
    rollover = RolloverDetector()
    store = DuckDBStore(settings.duckdb_path)
    store.ensure_schema()

    log.info("backfill.start", provider=provider_name, frm=args.frm.isoformat(),
             to=args.to.isoformat())

    try:
        df = await source.fetch_bars(args.symbol, args.tf, args.frm, args.to)
        df = rth.filter(df, symbol=args.symbol)
        df = rollover.annotate(df)
        store.upsert_bars(df, provider=provider_name)
        gaps = rth.find_gaps(df, args.symbol, args.tf, args.frm, args.to)
        store.upsert_gaps(gaps, provider=provider_name, run_id=run_id)
        status = "ok"
        notes = f"backfilled {len(df)} bars, {len(gaps)} gaps"
    except Exception as exc:
        status = "failed"
        notes = f"{type(exc).__name__}: {exc}"
        log.exception("backfill.failed")
        df = None
    finally:
        store.write_run(
            run_id=run_id,
            git_sha=git_sha(),
            data_hash=data_hash(df) if df is not None else "",
            param_hash=param_hash(vars(args)),
            seed=args.seed,
            adr_hash=adr_hash(),
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
            status=status,
            notes=notes,
        )
    return 0 if status == "ok" else 1

if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Backfill bars to DuckDB+Parquet")
    p.add_argument("--symbol", required=True, choices=["ES", "MES", "SPY"])
    p.add_argument("--tf", required=True, choices=["1m", "5m", "15m"])
    p.add_argument("--from", dest="frm", type=lambda s: datetime.fromisoformat(s).replace(tzinfo=timezone.utc), required=True)
    p.add_argument("--to", type=lambda s: datetime.fromisoformat(s).replace(tzinfo=timezone.utc), required=True)
    p.add_argument("--provider", choices=list(PROVIDERS))
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()
    sys.exit(asyncio.run(main(args)))
```

Notes:
- `args.frm` over `args.from` because `from` is a Python keyword.
- The UTF-8 reconfigure is the first thing the script does — established pattern from Phase 0 Plan 2.
- Every CLI exit (success or failure) writes a `runs` row. The `runs` table is the audit chain.

### Anti-Patterns to Avoid

- **`from datetime import datetime; datetime.now()`** — naive timestamp. Pre-commit AST hook must reject. Use `datetime.now(timezone.utc)`.
- **`pd.Timestamp("...").tz_localize(None)`** — strips timezone info. Banned in production code; use `.tz_convert("UTC")` and keep it tz-aware.
- **Hardcoded $12.50 / $50 / 0.25 outside `instruments.py`** — Phase 5 risk math reads from registry; magic numbers will be caught by lint.
- **Using the official `twelvedata` Python SDK** — hides the response headers Phase 0 found are the only reliable rate-limit signal. Use raw httpx.
- **`broadcaster` library for EventBus** — alpha + multi-backend; in-process asyncio.Queue is simpler.
- **`@runtime_checkable` on the four Protocols** — slow `isinstance()`, doesn't validate signatures. Lean on static type-checking.
- **`logging.handlers.WatchedFileHandler`** — Windows cannot rotate open files. Use `concurrent-log-handler` package.
- **TV `quote_get` for freshness checks** — returns bar-start time, not last-tick. Phase 0 finding. Document explicitly.
- **Importing from `scripts/spike/*.py`** — they carry the `PHASE 0 SPIKE — DO NOT IMPORT` sentinel. Reference for patterns only.
- **Strings for paths** — repo path contains a space. Always `pathlib.Path`. Pre-commit could add a regex check, but a simple convention + code review is enough.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Market calendars (NYSE/CME, holidays, half-days) | Custom holiday list | `pandas_market_calendars` 5.3.2 | DST-correct via zoneinfo; CME-specific half-day rules (Black Friday, etc.) baked in; updated annually by maintainer |
| Secret scanning | Hand-rolled regex | `gitleaks` v8.24.2 via pre-commit | Maintained rule set; cross-platform Go binary |
| Pre-commit orchestration | Raw `.git/hooks/pre-commit` shell script | `pre-commit` framework | Cross-platform, declarative `.pre-commit-config.yaml`, version-pinned hooks |
| JSON structured logging | `print(json.dumps(...))` everywhere | `structlog` 25.5.0 + processors | Async-safe, contextvars-aware, processor pipeline supports redaction |
| Time-sortable IDs | uuid4 + manual timestamp prefix | `uuid6.uuid7()` | RFC 9562 spec; lexically time-sortable; same 128-bit space as uuid4 |
| HTTP retry/backoff | Custom while-loop on httpx | `httpx` built-in `Retry` / `Transport` | Configurable, exhaustively tested |
| Parquet partitioning | Loop + manual file writes | DuckDB `COPY ... TO ... PARTITION_BY ... OVERWRITE_OR_IGNORE` | One-shot atomic; partition cleanup; faster than pyarrow direct |
| In-process pub/sub | (when scale-up needed) | hand-rolled now; `broadcaster` later only if cross-process needed | YAGNI for Phase 1 |
| File log rotation on Windows | `logging.handlers.WatchedFileHandler` | `concurrent-log-handler` | Windows file locks block WatchedFileHandler; concurrent-log-handler designed cross-platform |
| Canonical JSON | `json.dumps(..., sort_keys=True)` is *enough*, but document it | stdlib with explicit flags | UTF-8 bytes + sort_keys=True + tight separators + default=str → byte-stable |

**Key insight:** The 4 cross-cutting infra concerns (calendars, secret scanning, hooks, logging) all have battle-tested libraries with active 2026 maintenance. Hand-rolling them in a "trust the numbers" project would silently introduce bugs (DST off-by-one, half-day mishandling) that destroy backtest credibility years later.

## Runtime State Inventory

Not applicable — this is a greenfield Phase 1. No prior runtime systems to migrate from. Repo is empty except for `.planning/`, `.gitignore`, `.env.example`, `.env`, `.venv-spike/`, `scripts/spike/` (Phase 0 carryovers, marked DO-NOT-IMPORT).

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — fresh DuckDB | Create schema in Plan 4 |
| Live service config | TV MCP server already running at `C:\Users\Admin\tradingview-mcp-jackson\` | None — Phase 1 only consumes it |
| OS-registered state | None | None |
| Secrets/env vars | `TWELVEDATA_API_KEY` already in `.env` from Phase 0 (gitignored) | Extend `.env.example` and Pydantic Settings to declare it |
| Build artifacts | `.venv-spike/` exists (Phase 0 throwaway). `.venv-spike/` already gitignored. | Plan 1 creates `.venv/` via `uv sync`; `.venv-spike/` can be deleted at Phase 1 close |

## Common Pitfalls

### Pitfall 1: CME_Equity calendar returns the 23-hour Globex session, NOT 9:30-16:00 ET

**What goes wrong:** Naively using `mcal.get_calendar("CME_Equity").schedule(...)` returns market_open=18:00 ET prev day, market_close=17:00 ET — the full electronic session. Bars ingested with this filter include overnight, then ORB triggers on 3 AM range = silent backtest corruption (Pitfall MD-2 in research/PITFALLS.md).
**Why it happens:** Documentation says "RTH" without distinguishing cash session from electronic session. CME's own "RTH" terminology means *cash-equivalent RTH* (9:30-16:00 ET for equity index futures).
**How to avoid:** Two-step filter (see Pattern 3): (a) CME_Equity for trading-day determination + half-day flags, (b) hard 9:30-16:00 ET window from `instruments.py`. Test fixture: 1m bar at `2024-06-12 13:30 UTC` (= 09:30 ET) MUST appear in RTH; bar at `2024-06-12 02:00 UTC` (= 22:00 ET prev day) MUST NOT.
**Warning signs:** ORB range > 50 ES points; 24×60×n bars per day instead of 390.

### Pitfall 2: `INSERT OR REPLACE` silent-fail in DuckDB transactions

**What goes wrong:** DuckDB Issues [#14133](https://github.com/duckdb/duckdb/issues/14133) and [#20743](https://github.com/duckdb/duckdb/issues/20743): `INSERT OR REPLACE INTO` on PK tables silently fails to update existing rows in some transaction/file scenarios. The operation reports success but the data is unchanged. Caught by re-run test (criterion: same `seed_bars.py` produces zero new rows AND no changes).
**Why it happens:** Edge case in DuckDB's conflict handler when the existing row is in a different page than the new one, in some contexts.
**How to avoid:** Use the explicit `INSERT INTO ... ON CONFLICT (pk_cols) DO UPDATE SET col = EXCLUDED.col` form (see Pattern 6). DuckDB's own docs say this is what `INSERT OR REPLACE` desugars to — same semantics, no footgun.
**Warning signs:** Idempotency test fails — re-running seed produces "0 new" but the data on disk differs from a fresh ingest.

### Pitfall 3: DST transitions producing duplicate or missing bars

**What goes wrong:** Spring forward (2026-03-08): clocks jump 02:00 → 03:00 ET. If bars are stored as wall-clock ET, the 02:00-03:00 window is missing → gap detector erroneously flags 60 missing bars. Fall back (2026-11-01): clocks rewind 02:00 → 01:00 ET, producing a "duplicate" 01:00-02:00 hour.
**Why it happens:** Mixing wall-clock and UTC reasoning. Naive `.tz_localize` calls.
**How to avoid:** **All bars stored in UTC.** ET is a derived view. The 1m bar at `2026-03-08 06:30 UTC` = 01:30 EST; at `2026-03-08 06:31 UTC` = 01:31 EST; at `2026-03-08 07:00 UTC` = 02:00 EST… and the NEXT minute is `2026-03-08 07:01 UTC` = 03:01 EDT — UTC monotone, ET jumps. RTH starts at `2026-03-08 13:30 UTC` (= 09:30 EDT) — no bars are missing because RTH is 9:30 EDT not 9:30 EST that day. Tests must verify: `2026-03-08 09:30 ET → 13:30 UTC` AND `2026-03-09 09:30 ET → 13:30 UTC` (both produce the same UTC because DST shifted between the two days).
**Warning signs:** Bar count for a DST-transition trading day ≠ 390 (for 1m).

### Pitfall 4: Bar timestamps as bar-CLOSE time vs bar-OPEN time

**What goes wrong:** Twelve Data and TV both label bars by OPEN time. Some legacy data sources use CLOSE time. Treating an open-time bar as close-time = signal generated 60 seconds early = silent lookahead = Pitfall MD-4 in research/PITFALLS.md (Sharpe → infinity).
**How to avoid:** Document open-time in the `Bar` model docstring AND as a SQL column comment AND in the `bars` table DDL comment AND in `tests/test_data_sources.py` (assertion against TV vs Twelve Data for a known day).
**Verification artifact:** A unit test that takes the first bar of an RTH session and asserts `ts_utc == rth_open_utc(symbol, day)` (not `rth_open_utc + 1min`).

### Pitfall 5: Windows piped-stdout cp1252 crashes

**What goes wrong:** When `seed_bars.py` runs with stdout redirected (e.g., `... > log.txt`, or under task scheduler), Windows sets stdout encoding to cp1252. structlog log lines containing `→`, `—`, or any non-Latin-1 character crash with `UnicodeEncodeError`, which crashes the asyncio task group.
**Why it happens:** Phase 0 finding (Plan 2 SUMMARY.md §"Stdout UTF-8 reconfiguration on Windows"). The cp1252-trap caused the first 2 restart-script runs to crash.
**How to avoid:** **Every script entry point** reconfigures stdout/stderr to UTF-8 with `errors="replace"`. Make this a base-class behavior: `trading_core.logging.setup_logging()` does the reconfigure as its first step. Document the pattern in a top-of-`logging.py` comment.
**Warning signs:** Background runs crash, foreground runs succeed.

### Pitfall 6: Twelve Data official Python SDK hides rate-limit headers

**What goes wrong:** `twelvedata` Python SDK presents a clean API but does not expose `api-credits-used` / `api-credits-left` response headers. Phase 0 found these are the **only reliable pacing signal** (catalog endpoints emit no headers; `/time_series` does). Without header reads, pacing falls back to time-based heuristics that produce 429s under bursty load.
**How to avoid:** Use raw `httpx.AsyncClient`. Read `response.headers.get("api-credits-left")` after each `/time_series` call. Default pacing: 9 seconds (Phase 0 budget). Hard exit on 429 with structured error: `RateLimited(...)` raised — the caller in `seed_bars.py` should not silently retry.
**Verification artifact:** `tests/test_twelvedata_pacing.py` uses `respx` to mock a `/time_series` response with `api-credits-left=1` header and asserts the adapter waits ≥ 9s before the next request; another mock with HTTP 429 asserts `RateLimited` is raised.

### Pitfall 7: gitleaks false-positive on the redaction sentinel

**What goes wrong:** gitleaks pre-commit hook scans the Phase 0 spike artifacts (`.planning/research/spike-0/twelvedata-probe.json`) which legitimately contain the literal string `<TWELVEDATA_API_KEY>`. Without rule tuning, gitleaks might match this against a generic API-key regex.
**How to avoid:** Ship a `.gitleaks.toml` that explicitly allowlists the sentinel pattern: `[[rules.allowlists]] regexes = ['<TWELVEDATA_API_KEY>']`. Test by running `pre-commit run gitleaks --all-files` and confirming green.
**Warning signs:** Pre-commit blocks legitimate Phase 0 artifact commits.

### Pitfall 8: Pre-commit AST hook for naive datetime — easy to false-positive

**What goes wrong:** A regex-based hook for `datetime.now()` will fire on string literals containing the phrase (e.g., docstrings, comments). False positives turn the hook into a `# noqa`-spam generator and developers learn to ignore it.
**How to avoid:** Write a small AST-based scanner (Python script invoked as a local hook). The scanner walks Python AST nodes, looks for `Call(Attribute(Name('datetime'), 'now'))` and `Call(Attribute(Name('datetime'), 'utcnow'))` with **fewer than one argument** (a call with a `tz=...` arg is allowed).
**Skeleton:**

```python
# scripts/hooks/no_naive_tz.py
#!/usr/bin/env python3
"""Pre-commit hook: forbid datetime.now() / datetime.utcnow() without tz."""
import ast
import sys
from pathlib import Path

def lint(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    violations = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute):
            continue
        if func.attr not in ("now", "utcnow"):
            continue
        if not (isinstance(func.value, ast.Name) and func.value.id == "datetime"):
            continue
        if func.attr == "utcnow":
            violations.append((node.lineno, f"datetime.utcnow() is deprecated and tz-naive"))
        else:
            # now() — must have tz= kwarg
            kw_names = {kw.arg for kw in node.keywords}
            if "tz" not in kw_names and not node.args:
                violations.append((node.lineno, "datetime.now() without tz= produces naive timestamp"))
    return violations

def main(argv: list[str]) -> int:
    rc = 0
    for arg in argv[1:]:
        p = Path(arg)
        for ln, msg in lint(p):
            print(f"{p}:{ln}: {msg}")
            rc = 1
    return rc

if __name__ == "__main__":
    sys.exit(main(sys.argv))
```

### Pitfall 9: `mcp` SDK `stdio_client` does not expose subprocess stderr

**Inherited from Phase 0.** Phase 1's TradingViewDataSource cannot diagnostically capture the `tradingview-mcp-jackson` server's stderr. **Phase 1 does NOT solve this** — Phase 6's TVBridge will use `subprocess.Popen` directly with a custom MCP transport. Document this constraint in the TradingViewDataSource docstring + module-level comment. The Phase 1 adapter operates blind to server-side stderr.

### Pitfall 10: Pydantic v2 `BaseModel` performance vs `pydantic.dataclasses`

**What goes wrong:** The `instruments.py` registry constructs 3 `Instrument` objects at module import. For 3 objects there is zero perceptible cost difference between `BaseModel` and `pydantic.dataclasses.dataclass`. CONTEXT.md locks `BaseModel`.
**Resolution:** Use `BaseModel(frozen=True, extra='forbid')`. Performance is a non-issue at this scale.

## Code Examples (verified patterns)

### Pydantic v2 `Bar` model with tz-aware UTC enforcement

```python
# packages/trading-core/src/trading_core/data/models.py
from __future__ import annotations
from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, ConfigDict, Field, AwareDatetime, field_validator

class Bar(BaseModel):
    """Single OHLCV bar. ts_utc is the bar OPEN time, tz-aware UTC.

    Bar OPEN time convention (MD-06): bar labeled 09:30 covers the interval
    [09:30:00, 09:30:59] for a 1m bar. Vendor consistency: Twelve Data and TV both
    label bars by open time.
    """
    model_config = ConfigDict(frozen=True)

    symbol: str
    timeframe: str  # "1m" | "5m" | "15m"
    ts_utc: AwareDatetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int = Field(ge=0)
    rollover_seam: bool = False

    @field_validator("ts_utc")
    @classmethod
    def must_be_utc(cls, v: datetime) -> datetime:
        if v.utcoffset().total_seconds() != 0:
            raise ValueError(f"ts_utc must be tz-aware UTC; got offset {v.utcoffset()}")
        return v
```

### structlog setup with correlation IDs (FND-09)

```python
# packages/trading-core/src/trading_core/logging.py
from __future__ import annotations
import logging
import logging.handlers
import sys
from contextvars import ContextVar
from pathlib import Path
import structlog

correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)
signal_id:      ContextVar[str | None] = ContextVar("signal_id", default=None)

def _add_context(logger, method_name, event_dict):
    if cid := correlation_id.get():
        event_dict["correlation_id"] = cid
    if sid := signal_id.get():
        event_dict["signal_id"] = sid
    return event_dict

def setup_logging(audit_dir: Path) -> None:
    """Configure structlog for both stdout (dev) and rotating JSONL audit log."""
    # CRITICAL: defensive UTF-8 reconfigure for Windows piped-stdout safety
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    audit_dir.mkdir(parents=True, exist_ok=True)
    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        _add_context,
        structlog.processors.add_log_level,
        timestamper,
    ]

    # Standard-lib handler with cross-platform rotating JSONL file
    # concurrent_log_handler is Windows-safe (logging.handlers.WatchedFileHandler is NOT)
    from concurrent_log_handler import ConcurrentRotatingFileHandler
    file_handler = ConcurrentRotatingFileHandler(
        filename=str(audit_dir / "audit.jsonl"),
        maxBytes=50 * 1024 * 1024,   # 50 MB per file
        backupCount=20,
        encoding="utf-8",
    )
    file_handler.setFormatter(structlog.stdlib.ProcessorFormatter(
        processor=structlog.processors.JSONRenderer(),
        foreign_pre_chain=shared_processors,
    ))

    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setFormatter(structlog.stdlib.ProcessorFormatter(
        processor=structlog.dev.ConsoleRenderer(colors=False),  # Windows-safe
        foreign_pre_chain=shared_processors,
    ))

    root = logging.getLogger()
    root.handlers = [file_handler, console_handler]
    root.setLevel(logging.INFO)

    structlog.configure(
        processors=shared_processors + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
```

### `.pre-commit-config.yaml` (Phase 1 hooks only)

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.24.2
    hooks:
      - id: gitleaks
  - repo: local
    hooks:
      - id: no-naive-tz
        name: Forbid datetime.now() / datetime.utcnow() without timezone
        entry: python scripts/hooks/no_naive_tz.py
        language: python
        types: [python]
        require_serial: true
```

`.gitleaks.toml` allowlist for the Phase 0 sentinel:

```toml
# .gitleaks.toml — extends default rules with project allowlists
[[allowlists]]
description = "Phase 0 redaction sentinel and committed example placeholders"
regexes = [
    "<TWELVEDATA_API_KEY>",
]
paths = [
    '''.env.example''',
    '''.planning/research/spike-0/twelvedata-probe.json''',
]
```

### `pyproject.toml` (workspace root) — skeleton

```toml
# /pyproject.toml — workspace root, not a published package itself
[project]
name = "es-futures-trading"
version = "0.1.0"
requires-python = ">=3.11,<3.13"

[tool.uv.workspace]
members = ["packages/trading-core", "packages/api", "packages/tv-bridge"]

[tool.uv]
dev-dependencies = [
    "pytest>=8.0,<9.0",
    "pytest-asyncio>=0.24,<0.25",
    "pytest-cov",
    "hypothesis>=6.150,<7.0",
    "respx",
    "freezegun",
    "pre-commit",
]

# Workspace-wide tool configs
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["packages/trading-core/tests", "packages/api/tests", "packages/tv-bridge/tests"]

[tool.coverage.run]
source = ["packages/trading-core/src/trading_core/risk",
          "packages/trading-core/src/trading_core/execution",
          "packages/trading-core/src/trading_core/storage"]
```

```toml
# /packages/trading-core/pyproject.toml
[project]
name = "trading-core"
version = "0.1.0"
requires-python = ">=3.11,<3.13"
dependencies = [
    "pandas>=2.2,<3.0",
    "pyarrow>=17",
    "duckdb>=1.0,<2.0",
    "pydantic>=2.13,<3.0",
    "pydantic-settings>=2.5",
    "httpx>=0.27,<0.28",
    "structlog>=25.0",
    "concurrent-log-handler",
    "pandas-market-calendars>=5.3,<6.0",
    "uuid6>=2025.0,<2026.0",
    "rich",
    "mcp>=1.0,<2.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/trading_core"]
```

```toml
# /packages/api/pyproject.toml
[project]
name = "es-api"
version = "0.1.0"
requires-python = ">=3.11,<3.13"
dependencies = [
    "trading-core",
    "fastapi>=0.136,<0.137",
    "uvicorn[standard]>=0.32,<0.33",
]

[tool.uv.sources]
trading-core = { workspace = true }

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/api"]
```

```toml
# /packages/tv-bridge/pyproject.toml — empty package, Phase 6 home
[project]
name = "tv-bridge"
version = "0.1.0"
requires-python = ">=3.11,<3.13"
dependencies = ["trading-core"]

[tool.uv.sources]
trading-core = { workspace = true }

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/tv_bridge"]
```

### `apps/web/` — Next.js stub setup

```bash
# Initialize via create-next-app with defaults (TypeScript, ESLint, Tailwind, App Router)
cd apps && pnpm create next-app@latest web --yes
# Then add the lib deps that Phase 3 will use:
cd web && pnpm add lightweight-charts@5.2.0 @tanstack/react-query@5 zustand@5
```

```tsx
// apps/web/app/page.tsx — Phase 1 placeholder
export default function Page() {
  return (
    <main className="flex min-h-screen items-center justify-center bg-black font-mono text-gray-200">
      <div className="max-w-xl space-y-2 p-8">
        <h1 className="text-2xl font-bold">ES Futures Trading System</h1>
        <p className="text-sm text-gray-400">
          Phase 1: Foundation scaffold. Real charts ship in Phase 3.
        </p>
        <p className="text-xs text-gray-600">Next.js 16.2 · React 19 · TypeScript 5</p>
      </div>
    </main>
  );
}
```

```yaml
# /pnpm-workspace.yaml
packages:
  - "apps/*"
```

```json
// /package.json (root) — minimal
{
  "name": "es-futures-monorepo",
  "private": true,
  "packageManager": "pnpm@9.15.0",
  "scripts": {
    "dev": "pnpm --filter web dev",
    "build": "pnpm --filter web build",
    "typecheck": "pnpm --filter web tsc --noEmit"
  }
}
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Poetry workspaces | uv workspaces | 2024-2025 | uv community adoption; 10× install speed |
| `requests` + `aiohttp` | `httpx` (single sync+async client) | 2023+ | One client across CLI + FastAPI |
| pandas-ta (original) | `pandas-ta-classic` (active fork) | 2024 | Original effectively unmaintained |
| pydantic v1 | pydantic v2 | 2023; FastAPI 0.136 deprecates v1 | 10-50× faster Rust core |
| `datetime.utcnow()` | `datetime.now(timezone.utc)` | Python 3.12 deprecation | utcnow() returned naive, footgun |
| stdlib `uuid` only | + `uuid6` for uuid7 | 2024 | Time-sortable IDs for audit logs |
| `WatchedFileHandler` on Windows | `concurrent-log-handler` cross-platform | always | Windows file-lock issue is structural |
| Tailwind v3 (config-file based) | Tailwind v4 (CSS-first config) | v4 released 2025 | Still controversial — see Open Question |

**Deprecated/outdated to actively avoid:**
- `datetime.utcnow()` — formally deprecated in 3.12
- `pytz` — pandas_market_calendars 5.0 dropped it in favor of `zoneinfo`
- `Conda/Anaconda` — uv is the modern alternative
- pandas 3.0 — too new; vectorbt 1.0.0 has not certified

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | DuckDB `INSERT INTO ... ON CONFLICT (a,b,c) DO UPDATE SET col = EXCLUDED.col` is fully reliable for composite PK in transactions on DuckDB 1.x. | Pattern 6 / Pitfall 2 | If also buggy, fallback is `DELETE + INSERT` in one transaction (slower but bulletproof). Mitigation: idempotency test runs at end of Plan 4 and fails loudly. |
| A2 | The `mcp` Python SDK 1.x will continue working with `tradingview-mcp-jackson` v2.0.0 from a project-local `.venv` (Phase 0 used `.venv-spike/`). | Pattern 1 (TradingViewDataSource) | If breaks: TradingViewDataSource cannot ship in Phase 1; would defer MD-02 to Phase 6 and use Twelve Data only. Mitigation: smoke test in Plan 3 re-runs Phase 0 happy path against the new `.venv`. |
| A3 | `pandas_market_calendars`'s CME_Equity schedule will correctly mark CME-specific half-days (e.g., July 3 when July 4 is Saturday) that NYSE does not honor. | Pattern 3 | If CME_Equity half-days are incorrect/missing, our session filter mishandles them — quiet bug. Mitigation: cross-check 2024-07-03 (early close per CME website) against `schedule()` output in Plan 4 tests. |
| A4 | The data_hash recipe (sort + project + Parquet bytes with compression=None) produces byte-identical output across pyarrow patch versions. | Pattern 7 | If unstable across patch versions, reproducibility CI in Phase 3 will fail spuriously after a pyarrow upgrade. Mitigation: pin pyarrow to a single patch (e.g., 17.0.0) in uv.lock; revisit if breaks. |
| A5 | `uv sync` on Windows handles paths with spaces ("Day Trading" repo path) without quoting issues. | Stack Installation | Verified by community uses of uv on Windows; if breaks, workaround is to alias the repo path or move it. Mitigation: Plan 1 includes a "uv sync works" smoke test as its acceptance gate. |
| A6 | Tailwind 3 is the safer default for Phase 1 (Open Question O-1). | Stack Standard Stack | If user prefers v4, planner can swap with no architectural impact. |
| A7 | Phase 0 spike found `quote_get` returns bar-start, not last-tick time. Phase 1's TradingViewDataSource freshness checks should reference `data_get_ohlcv` last bar's `ts_utc + timeframe` plus a tolerance, not `quote_get.time`. | Pattern 1 / Pitfall 9 | Documented in Phase 0 SUMMARY 02-02. Low risk — Phase 1 only uses `data_get_ohlcv`. |
| A8 | `corepack enable` is available on the operator's Node 20.9+ install. | Stack Installation | corepack ships with Node 16.10+ — verified yes. Mitigation: fall back to `npm install -g pnpm@9.15.0` if needed. |

**Items needing user confirmation before locking the plan:**
- **A6 (Tailwind 3 vs 4):** Open Question O-1 below. Recommend v3.
- **A2 (mcp SDK reuse):** Plan 3 should re-run a TradingView smoke against `.venv/` as an explicit acceptance gate. If it fails, Plan 3 sheds MD-02 to Phase 6 and the planner accepts that as a known deviation.

## Open Questions

### O-1: Tailwind v3 vs Tailwind v4 for the `apps/web/` stub

- **What we know:** `create-next-app@latest --yes` in Next.js 16.2 enables Tailwind by default. Tailwind v4 released 2025 with CSS-first config (`@theme` directive, no `tailwind.config.ts`); v3 remains the more battle-tested option per 2026 community guidance.
- **What's unclear:** Whether v4's evolving feature set will introduce churn that needs revisiting before Phase 3's real UI work.
- **Recommendation:** **Pin Tailwind v3** for Phase 1. The stub is a placeholder; ergonomics gains from v4 are irrelevant. If/when the dense Bloomberg UI ships in Phase 7 with serious styling work, revisit. Document the choice in the apps/web README + a sentence in CONTEXT.md update at Phase 1 close.

### O-2: Should `tv-bridge` package include a sample import-test in Phase 1?

- **What we know:** D-02 locks `tv-bridge` as an empty importable package. The minimum for `uv sync` to succeed is a `pyproject.toml` + `src/tv_bridge/__init__.py`.
- **What's unclear:** Whether the package needs a single trivial test (`test_can_import.py`) to prove the workspace wiring works.
- **Recommendation:** **Yes — include `tests/test_import.py` with one `def test_module_imports(): import tv_bridge`** test. This proves: (a) the workspace member resolves, (b) the package is editable-installed, (c) pytest discovery sees the test dir. Same minimal stub for `api` package (a `def test_health(client): response = client.get("/health"); assert response.status_code == 200`).

### O-3: Pydantic Settings — single root or per-package?

- **What we know:** FND-03 mandates merging `.env` + `config/*.yaml`. Pydantic Settings can live as one class.
- **What's unclear:** Whether `api` and `tv-bridge` need their own Settings or share `trading_core.config.Settings`.
- **Recommendation:** **Single root `trading_core.config.Settings`.** Both downstream packages import it. Per-package Settings is a v2 refactor if/when configuration concerns diverge.

### O-4: Phase 1 hash for `data_hash` — is sort-by-(symbol,tf,ts) sufficient?

- **What we know:** Bars have a natural primary key. Sorting by it removes row-order variance.
- **What's unclear:** Whether multi-precision floats round-trip through pyarrow bit-stably across patch versions.
- **Recommendation:** Pin pyarrow to one minor (`pyarrow>=17.0,<18.0`). Phase 3's reproducibility CI test will catch any regression at upgrade time. Document the pin reason in a comment in `pyproject.toml`.

### O-5: `seed_bars.py` — where does it live?

- **What we know:** Discretion area; the natural locations are `scripts/seed_bars.py` (repo-root) OR `packages/api/src/api/cli/seed_bars.py` (entry-point exported via `[project.scripts]`).
- **What's unclear:** Whether the operator wants `python scripts/seed_bars.py ...` or `uv run seed-bars ...`.
- **Recommendation:** **`scripts/seed_bars.py`** to match CONTEXT.md's literal example. The ROADMAP success criterion says `python scripts/seed_bars.py --symbol SPY ...` verbatim. Both paths can coexist later if the operator wants `uv run` ergonomics.

### O-6: `apps/web/` package manager — pin via packageManager field?

- **What we know:** pnpm 9.x is the stack pick.
- **What's unclear:** Whether to commit `packageManager: "pnpm@9.15.0"` in root package.json (auto-uses corepack) or leave loose.
- **Recommendation:** **Pin via `packageManager` field.** Corepack picks it up automatically and prevents accidental npm/yarn use.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | All Python work | ✓ | (WindowsApps stub — uv will install a real one) | uv-managed |
| Node.js | apps/web | ✓ | (need to verify >=20.9 in Plan 1) | Install latest LTS |
| `uv` | Plan 1 onward | ✗ | — | **Install via PowerShell one-liner** (Plan 1, Task 1) |
| `pnpm` | apps/web | ✗ | — | **Install via `corepack enable`** (Plan 1, Task 1) |
| `git` | Always | ✓ | — | — |
| TV MCP Server | TradingViewDataSource | ✓ | v2.0.0 at `C:\Users\Admin\tradingview-mcp-jackson\` | — |
| TradingView Desktop | TradingViewDataSource live | ✓ | (operator-managed) | Phase 1 can run on Twelve Data alone |
| Twelve Data API key | TwelveDataSource | ✓ | `.env` (Phase 0 wired) | — |
| `gitleaks` binary | pre-commit hook | (managed by pre-commit) | v8.24.2 pinned | pre-commit auto-fetches Go binary |
| `ffmpeg` / `docker` | — | n/a | — | — |

**Missing dependencies with no fallback:** None — uv and pnpm can both be installed without admin rights via single PowerShell commands.

**Missing dependencies with fallback:**
- uv missing → first task installs it
- pnpm missing → first task enables corepack
- Both verified by `uv --version` / `pnpm --version` smoke before any Python/JS work begins

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.x + pytest-asyncio 0.24.x + hypothesis 6.152.x |
| Config file | root `pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `uv run pytest packages/trading-core/tests/test_<module>.py::<test> -x` |
| Full suite command | `uv run pytest` (discovers all three `packages/*/tests/`) |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|--------------|
| FND-01 | `uv sync` produces working `.venv` with workspace members importable | smoke | `uv sync && uv run python -c "import trading_core, api, tv_bridge"` | ❌ Wave 0 |
| FND-02 | `uv.lock` pins exact versions | smoke | `grep -E "^name = \"vectorbt\"" uv.lock | grep "1.0.0"` (verify; vectorbt pinned but unused this phase OR drop to Phase 3 — see Open Question) | ❌ Wave 0 |
| FND-03 | Pydantic Settings merges `.env` + YAML | unit | `pytest packages/trading-core/tests/test_config.py -x` | ❌ Wave 0 |
| FND-04 | gitleaks blocks API keys | integration | `pre-commit run gitleaks --all-files` against a synthetic leak | ❌ Wave 0 |
| FND-05 | `datetime.now()` lint rejects naive | integration | `pre-commit run no-naive-tz --files tests/fixtures/bad.py` | ❌ Wave 0 |
| FND-06 | `instruments.py` SoT registry round-trips | unit | `pytest packages/trading-core/tests/test_instruments.py -x` | ❌ Wave 0 |
| FND-07 | EventBus publishes / subscribes / FIFO per topic | unit (async) | `pytest packages/trading-core/tests/test_event_bus.py -x` | ❌ Wave 0 |
| FND-08 | `runs` table writer captures all 10 fields including hashes | unit | `pytest packages/trading-core/tests/test_runs.py -x` | ❌ Wave 0 |
| FND-09 | structlog emits JSON with correlation_id contextvar | unit | `pytest packages/trading-core/tests/test_logging.py -x` | ❌ Wave 0 |
| MD-01 | DataSource Protocol mypy-validates two impls | static | `uv run mypy packages/trading-core/src/` | ❌ Wave 0 |
| MD-02 | TradingViewDataSource fetch_bars happy path | integration | `pytest packages/trading-core/tests/test_tradingview_source.py -x` (skips if TV not running) | ❌ Wave 0 |
| MD-03 | TwelveDataSource fetch_bars happy path + pacing | integration | `pytest packages/trading-core/tests/test_twelvedata_source.py -x` (respx-mocked) | ❌ Wave 0 |
| MD-04 | DuckDB upsert idempotent | unit | `pytest packages/trading-core/tests/test_duckdb_store.py::test_upsert_idempotent -x` | ❌ Wave 0 |
| MD-05 | RthFilter excludes ETH; honors half-days | unit + property | `pytest packages/trading-core/tests/test_rth_filter.py -x` | ❌ Wave 0 |
| MD-05a | DST transitions handled (2026-03-08 + 2026-11-01) | unit | `pytest packages/trading-core/tests/test_rth_filter.py::test_dst_spring_forward -x` | ❌ Wave 0 |
| MD-06 | Bar OPEN-time convention enforced in model | unit | `pytest packages/trading-core/tests/test_bar_model.py -x` | ❌ Wave 0 |
| MD-07 | Bar-gap detector writes correct gaps to bar_gaps | unit | `pytest packages/trading-core/tests/test_gap_detector.py -x` | ❌ Wave 0 |
| MD-08 | Rollover seam True on 3rd Friday of quarter month | unit | `pytest packages/trading-core/tests/test_rollover_detector.py -x` | ❌ Wave 0 |
| MD-09 | `seed_bars.py SPY 1m` end-to-end produces non-empty bars + runs row | integration | `python scripts/seed_bars.py --symbol SPY --tf 1m --from 2024-01-02 --to 2024-01-03 && pytest tests/integration/test_seed_bars_e2e.py -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** Quick test for the touched module — e.g., `uv run pytest packages/trading-core/tests/test_rth_filter.py -x`
- **Per wave merge:** Full module's tests + `mypy packages/trading-core/src/`
- **Phase gate:** `uv run pytest && pnpm --filter web build && pnpm --filter web tsc --noEmit && pre-commit run --all-files` all green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] All test files listed above — they don't exist yet. Wave 0 of each plan creates them as part of the plan's primary work.
- [ ] `packages/*/tests/conftest.py` — shared fixtures (synthetic SPY 1m day, DST-transition fixtures, mocked Twelve Data responses)
- [ ] Framework install: `uv add --dev pytest pytest-asyncio hypothesis respx freezegun pytest-cov mypy` — done as part of Plan 1 root-pyproject.toml authoring.

### Required Test Fixtures (load-bearing)

| Fixture | File | Purpose |
|---------|------|---------|
| `synthetic_spy_day` | conftest | 390 1m bars for a known RTH day with hand-computed OHLCV |
| `dst_spring_forward_day` | conftest | Bars spanning 2026-03-08 — verifies UTC monotone + correct ET-RTH window (13:30 UTC = 09:30 EDT, not 14:30 UTC = 09:30 EST) |
| `dst_fall_back_day` | conftest | Bars spanning 2026-11-01 — verifies 390 bars produced |
| `cme_half_day_thanksgiving` | conftest | 2024-11-29 (Black Friday after Thanksgiving) — early close at 13:00 ET |
| `rollover_seam_day` | conftest | 2026-03-20 — 3rd Friday of March 2026, must flag `rollover_seam=True` |
| `twelve_data_mock_responses` | conftest | respx fixture returning `/time_series` + correct rate-limit headers |
| `bad_naive_datetime_py` | tests/fixtures/ | `bad.py` with `datetime.now()` → pre-commit must reject |

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | n/a — local single-operator app, no auth surface |
| V3 Session Management | No | n/a |
| V4 Access Control | No | n/a |
| V5 Input Validation | yes | Pydantic v2 models for all incoming CLI args, env vars, API request bodies (Phase 3+) |
| V6 Cryptography | partial | Hash recipes (data_hash/adr_hash) use stdlib `hashlib.sha256` — appropriate; no encryption-at-rest in Phase 1 |
| V7 Error Handling | yes | Structured exceptions (`DataSourceError` family); structlog redaction processor for API keys |
| V8 Data Protection | yes | `.env` gitignored; `<TWELVEDATA_API_KEY>` redaction sentinel in committed logs; gitleaks gate |
| V14 Configuration | yes | Pydantic Settings + frozen Instrument registry |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| API key leak in commit | Information Disclosure | gitleaks pre-commit hook (v8.24.2) + `<TWELVEDATA_API_KEY>` sentinel pattern + `.env` in gitignore |
| API key leak in log | Information Disclosure | structlog processor that redacts known key names; URL redaction wrapper for httpx |
| Path-traversal via CLI args | Tampering | argparse + Pydantic Settings constrain paths; `pathlib.Path` resolves; no user-supplied path joins to data/ |
| DuckDB file corruption | DoS | single-writer convention — FastAPI process holds the only writer connection; CLIs use read-only or coordinated writes |
| Unbounded EventBus queue | DoS | Phase 1 ships unbounded queues (single-operator low rate); document the limit; Phase 5/7 may add bounded queues + drop-oldest |
| TV MCP CDP target hijack | Tampering | Out of scope — MCP server is operator-controlled local subprocess; CDP localhost-only |

## Plan Structure Recommendation

**Total: 6 plans across 3 waves.**

```
PHASE 1 PLAN GRAPH (waves can run in parallel via worktrees; arrows = file overlap or true dep)

Wave A — Scaffolding (sequential start; everything downstream needs A)
├── 01-01-PLAN: Workspace scaffold + Python/JS toolchain install
│   ├── Install uv + pnpm (Task 1)
│   ├── Author root pyproject.toml + uv.lock first pass (Task 2)
│   ├── Stub packages/trading-core,api,tv-bridge with empty src/ + tests/test_import.py (Task 3)
│   ├── Author pnpm-workspace.yaml + initialize apps/web via create-next-app (Task 4)
│   ├── Install Phase 1 frontend deps (lightweight-charts, TQ, zustand) (Task 5)
│   └── Verify uv sync + pnpm install + pnpm build + tsc --noEmit + pytest (Task 6)
│
└── (deliverable: uv sync works; pnpm build works; pytest collects 3 trivial tests)

Wave B — Three parallel plans, all depend on A only (disjoint module trees, can run in worktrees)

├── 01-02-PLAN: Core domain modules (instruments.py + 4 Protocols + Bar/Signal/Fill/RiskConfig models + logging + config)
│   Touches: packages/trading-core/src/trading_core/{instruments.py, data/, strategy/, risk/, execution/, events/models.py, logging.py, config.py}
│   Plus: packages/trading-core/tests/{test_instruments, test_bar_model, test_logging, test_config}
│   No file overlap with Plans 03, 04.
│
├── 01-03-PLAN: Calendar + RTH filter + rollover detector + gap detector + EventBus
│   Touches: packages/trading-core/src/trading_core/{calendars/, events/bus.py}
│   Plus: tests/{test_rth_filter, test_rollover_detector, test_gap_detector, test_event_bus}
│   Carries the DST-transition fixtures + half-day fixtures into conftest.py — Plan 02 also touches conftest.py BUT only adds non-conflicting fixtures (instruments/bar/logging fixtures). Planner should designate which plan owns conftest.py to avoid worktree merge conflicts. Recommend: Plan 02 owns conftest.py initial creation; Plan 03 extends it.
│
└── 01-04-PLAN: Storage layer (DuckDB schema + upserts + Parquet partitioning + runs writer + data_hash recipe) + DataSources (TwelveData + TradingView adapters)
   Touches: packages/trading-core/src/trading_core/{storage/, data/twelvedata.py, data/tradingview.py}
   Plus: tests/{test_duckdb_store, test_runs, test_twelvedata_source, test_tradingview_source}
   No file overlap with Plans 02, 03 (data/protocols.py and data/models.py are owned by Plan 02; adapters live in their own files).

Wave C — Closing the loop

├── 01-05-PLAN: seed_bars.py CLI + integration test + bar_gaps wiring + pre-commit hooks + .gitleaks.toml
│   Touches: scripts/seed_bars.py, scripts/hooks/no_naive_tz.py, .pre-commit-config.yaml, .gitleaks.toml,
│            tests/integration/test_seed_bars_e2e.py
│   Depends on: B-02 (Protocols, Bar), B-03 (RthFilter, RolloverDetector, GapDetector, EventBus), B-04 (DuckDBStore, DataSources, runs writer)
│
└── 01-06-PLAN: FastAPI shell + apps/web stub page + workspace-wide acceptance smoke
    Touches: packages/api/src/api/app.py, apps/web/app/page.tsx (replace placeholder), tests/test_api_health.py
    Acceptance: uv run pytest && pnpm build && pnpm tsc --noEmit && pre-commit run --all-files && python scripts/seed_bars.py --symbol SPY --tf 1m --from 2024-01-02 --to 2024-01-03
    Plus: ROADMAP table updated, STATE.md advanced, optional CONTEXT.md note re Tailwind 3 choice.
    Depends on: 01-05 (seed_bars must work end-to-end). 
```

### Wave dependencies (for the plan-orchestrator)

| Plan | Depends on |
|------|-----------|
| 01-01 | — (kickoff) |
| 01-02 | 01-01 |
| 01-03 | 01-01 |
| 01-04 | 01-01, **01-02** (imports Bar model + DataSource Protocol from Plan 02) |
| 01-05 | 01-02, 01-03, 01-04 (composes everything) |
| 01-06 | 01-05 (final acceptance smoke includes seed_bars) |

Wave B has a hidden dep: Plan 01-04 imports from Plan 01-02 (Protocols and models). If the planner wants Plan 04 to start before Plan 02 completes, Plan 02's deliverable can be sliced into 02a (Protocols + models only, ~1 hour) and 02b (everything else). Recommend instead: keep Plan 02 atomic, let Plan 04 start ~30 min after Plan 02 starts (Plan 02's first commit drops the Protocols, then Plan 04 unblocks).

### Per-plan commit recommendation

Per CONTEXT.md §"Atomic per-plan commit": Phase 0 used one commit per plan, not per task. Phase 1 has more independent tasks within plans, so:
- **Plans 01-01, 01-05, 01-06:** One atomic commit per plan (tasks tightly co-dependent)
- **Plans 01-02, 01-03, 01-04:** **One commit per task** is acceptable because each task ships a coherent module unit (instruments.py + tests can commit independently from logging.py + tests). Planner picks based on each task's stability.

### Required gate before phase close

The phase-verifier must confirm ALL of:
1. `uv sync` from a clean clone produces `.venv` with vectorbt 1.0.0 / pandas 2.2.x / FastAPI / Pydantic v2 / DuckDB / structlog / httpx / pytest / hypothesis / respx / freezegun pinned in `uv.lock`. (FND-02)
2. `python scripts/seed_bars.py --symbol SPY --tf 1m --from 2024-01-02 --to 2024-01-03` produces a bars table with all 1m bars in RTH (390 bars), `rollover_seam` correctly set, idempotent re-run produces 0 new rows, `bar_gaps` populated if any are missing.
3. `pytest` runs cleanly including the DST-transition tests (`2026-03-08`, `2026-11-01`).
4. `pre-commit run --all-files` rejects a deliberate `datetime.now()` test fixture AND a deliberate fake API key string.
5. The `runs` table contains a row for the seed run with all 10 fields populated, including `adr_hash` matching `sha256(.planning/decisions/0001-data-provider.md)`.
6. `instruments.py` is the only file with hardcoded tick_value / point_value (grep check).
7. `pnpm --filter web build` succeeds and `pnpm --filter web tsc --noEmit` passes — JS toolchain works on Windows.
8. The 4 Protocol seams are defined and mypy validates the live `DataSource` implementations against the Protocol.
9. EventBus has a passing publish-subscribe-FIFO test.

## Sources

### Primary (HIGH confidence)

- [uv on PyPI](https://pypi.org/project/uv/) — 0.11.14 (May 12, 2026) [VERIFIED]
- [uv workspaces docs](https://docs.astral.sh/uv/concepts/projects/workspaces/) — workspace syntax + tool.uv.sources [VERIFIED]
- [uv init docs](https://docs.astral.sh/uv/concepts/projects/init/) — `--lib` flag, `src/` layout [VERIFIED]
- [uv sync docs](https://docs.astral.sh/uv/concepts/projects/sync/) — editable installs + `dependency-groups` PEP 735 [VERIFIED]
- [Next.js 16 installation docs](https://nextjs.org/docs/app/getting-started/installation) — current 16.2.6 May 13, 2026; Node 20.9+; create-next-app defaults to Tailwind+TS+App Router [VERIFIED]
- [Pydantic on PyPI](https://pypi.org/project/pydantic/) — 2.13.4 (May 6, 2026) [VERIFIED]
- [structlog on PyPI](https://pypi.org/project/structlog/) — 25.5.0 (Oct 27, 2025), Python 3.8+ [VERIFIED]
- [pandas_market_calendars 5.3.2 (Apr 5, 2026)](https://pypi.org/project/pandas-market-calendars/) [VERIFIED]
- [pandas_market_calendars usage docs](https://pandas-market-calendars.readthedocs.io/en/latest/usage.html) — CME_Equity + date_range() + UTC output [VERIFIED]
- [pandas_market_calendars CME class source](https://github.com/rsheftel/pandas_market_calendars/blob/master/pandas_market_calendars/calendars/cme.py) — confirmed CME_Equity covers 23-hour Globex session 5pm-4pm Chicago with 3:15-3:30pm Chicago break, **not** 9:30-16:00 ET cash session [VERIFIED]
- [pandas-ta-classic on PyPI](https://pypi.org/project/pandas-ta-classic/) — 0.5.44 (Apr 30, 2026); Python 3.10-3.14 [VERIFIED]
- [DuckDB INSERT docs](https://duckdb.org/docs/current/sql/statements/insert) — INSERT OR REPLACE + composite PK + ON CONFLICT DO UPDATE [VERIFIED]
- [DuckDB Hive partitioning docs](https://duckdb.org/docs/lts/data/partitioning/partitioned_writes) — PARTITION_BY + OVERWRITE_OR_IGNORE [VERIFIED]
- [uuid6 on PyPI](https://pypi.org/project/uuid6/) — 2025.0.1 (Jul 4, 2025), provides `uuid7()` [VERIFIED]
- [gitleaks pre-commit integration](https://github.com/gitleaks/gitleaks) — rev v8.24.2 [VERIFIED]
- [pre-commit.com framework docs](https://pre-commit.com/) — local hooks, cross-platform (Win/Mac/Linux) [VERIFIED]
- [lightweight-charts on npm](https://www.npmjs.com/package/lightweight-charts) — 5.2.0 [VERIFIED]
- `.planning/decisions/0001-data-provider.md` — locked DataSource ADR [READ verbatim]
- `.planning/phases/01-foundation-data-in/01-CONTEXT.md` — all D-01..D-04 locks + Claude's Discretion areas [READ verbatim]
- `.planning/phases/00-provider-validation-spike/00-{01,02,03}-SUMMARY.md` — Phase 0 operational findings [READ verbatim]
- `.planning/research/spike-0/spy-bar-budget.md` — 9s pacing + Free tier budget [READ verbatim]
- `CLAUDE.md` — version matrix + "What NOT to Use" + Project Constraints [READ verbatim]

### Secondary (MEDIUM confidence, cross-verified)

- [DuckDB Issue #14133](https://github.com/duckdb/duckdb/issues/14133) — `INSERT OR REPLACE` silent fail in transactions on PK tables [VERIFIED — cross-checked with #20743]
- [DuckDB Issue #20743](https://github.com/duckdb/duckdb/issues/20743) — `INSERT OR REPLACE` silent fail on certain databases; workaround is `INSERT ... ON CONFLICT DO UPDATE` [VERIFIED]
- [Python typing docs runtime_checkable](https://docs.python.org/3/library/typing.html) — `@runtime_checkable` slow isinstance + no signature validation [VERIFIED]
- [Python logging.handlers docs](https://docs.python.org/3/library/logging.handlers.html) — WatchedFileHandler unsafe on Windows [VERIFIED]
- [Tailwind 4 vs 3 stability blog roundup, 2026](https://devtoolbox.dedyn.io/blog/tailwind-css-v4-complete-guide) — v3 still safer choice for new projects in 2026 [MEDIUM — community guidance, not single official source]
- [structlog ProcessorFormatter + RotatingFileHandler patterns](https://www.structlog.org/en/stable/standard-library.html) — JSONRenderer + AsyncBoundLogger pattern [VERIFIED]
- [broadcaster on PyPI](https://pypi.org/project/broadcaster/) — alpha status; multi-backend [VERIFIED] — rejected for in-process Phase 1 use

### Tertiary (LOW confidence)

- None — every load-bearing claim has at least one primary or secondary verified source.

## Metadata

**Confidence breakdown:**

- **Standard stack:** HIGH — every version verified against PyPI / npm on 2026-05-14.
- **Architecture (Protocols + EventBus + DuckDB upsert + RTH filter pattern):** HIGH — patterns either come from CONTEXT.md locks or are verified against the relevant library's official docs/source.
- **Pitfalls:** HIGH on the operational ones (Windows cp1252, DuckDB INSERT OR REPLACE, mcp stderr) — all from Phase 0 evidence or upstream issues; MEDIUM on assumption A1 (DuckDB ON CONFLICT works fine in transactions; if also buggy fallback is documented).
- **Plan structure:** HIGH — module ownership is clean per CONTEXT.md D-03; the 6-plan / 3-wave split derives from file-overlap analysis.
- **Open Question O-1 (Tailwind 3 vs 4):** MEDIUM — recommend v3 based on 2026 community guidance; flagged for user confirmation.

**Research date:** 2026-05-14
**Valid until:** 2026-06-13 (30 days; Phase 1 ships well within this window so no re-verification needed before plan execution)
