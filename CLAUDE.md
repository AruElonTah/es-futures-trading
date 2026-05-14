<!-- GSD:project-start source:PROJECT.md -->
## Project

**ES Futures Trading System**

A modular Python trading system for E-mini S&P 500 (ES) futures focused on intraday (1m–15m) strategies during the cash session, paired with a Bloomberg-Terminal-style web UI for chart visualization, position tracking, P&L analysis, and strategy control. It runs in **paper / backtest-only** mode — no live capital — but is designed cleanly enough that a real broker adapter could be slotted in later.

Built for a single operator who wants to research, backtest, optimize, and observe intraday ES strategies (starting with Opening Range Breakout) inside one local tool that uses the **TradingView Desktop chart (via TradingView MCP) as both the live data source and the visualization surface**. Twelve Data and other vendors remain pluggable behind a `DataSource` abstraction for headless backfills and reconciliation, but TV MCP is the v1 primary feed.

**Core Value:** **Trust the numbers.** When the system says a strategy made X dollars in backtest with Y drawdown at Z parameters, that result must be reproducible, leakage-free, and survive walk-forward — because every decision (param tuning, deployment, capital allocation) compounds on top of it.

### Constraints

- **Tech stack — Python 3.11+**: required by VectorBT, FastAPI async features, and modern type hints. Lock minimum version in `pyproject.toml`.
- **Tech stack — VectorBT (free tier acceptable)**: backtest engine. PRO is optional — start free.
- **Tech stack — TradingView MCP as primary data feed**: live polling + replay-driven historical via `data_get_ohlcv`. Requires TradingView Desktop running and the `tradingview-mcp-jackson` server reachable as a stdio subprocess. Twelve Data REST remains as a secondary `DataSource` for headless / CI / reconciliation use.
- **Storage — DuckDB + Parquet local files only**: zero-ops, columnar, fast pandas/VBT integration. No Postgres / Timescale until proven necessary.
- **UI — FastAPI + Next.js (TypeScript) + TradingView Lightweight Charts**: required for true Bloomberg-style density and real-time WebSocket feeds.
- **Session — RTH (9:30–16:00 ET) only**: data ingestion, backtest windows, and execution gating all enforce this. ETH bars discarded at ingest.
- **Platform — Windows / PowerShell** primary, with Bash fallback: setup scripts use cross-platform commands (Python, Node, npm/pnpm). Avoid bash-only shell scripts in onboarding.
- **Compliance — paper only**: no broker API keys, no order-routing surfaces, no fills against live markets. Removes the bulk of operational/security work for v1.
<!-- GSD:project-end -->

<!-- GSD:stack-start source:research/STACK.md -->
## Technology Stack

## Stack Summary
| Layer | Pick | Version (May 2026) | Confidence |
|-------|------|--------------------|------------|
| Language | Python | **3.11+** (target 3.12 for prod, 3.13 supported) | HIGH |
| Pkg/env manager | **uv** (Astral) | 0.11.x | HIGH |
| Dependency model | `pyproject.toml` + `uv.lock` | — | HIGH |
| HTTP client | **httpx** | 0.27.x+ | HIGH |
| Data frames | **pandas 2.2.x** primary, **polars 1.x** for hot paths | pandas 2.2.x (NOT 3.0 yet — see What NOT to Use) | HIGH |
| Indicators | **pandas-ta-classic** + hand-rolled ATR/VWAP | pandas-ta-classic latest | HIGH |
| Storage | **DuckDB + Parquet** | DuckDB 1.x | HIGH |
| Market calendars | **pandas_market_calendars** | 5.x (Mar 2026) | HIGH |
| Backtest engine | **vectorbt (OSS)** | **1.0.0** (released Apr 22, 2026) | HIGH |
| Web framework | **FastAPI** + **uvicorn** | FastAPI 0.136.1 (Apr 23, 2026), uvicorn 0.32.x | HIGH |
| Validation | **Pydantic v2** | 2.13.x (May 6, 2026) | HIGH |
| WebSocket fan-out | FastAPI native `WebSocket` + in-process `broadcaster` library | broadcaster 0.3.x | HIGH |
| Logging | **structlog** | latest | HIGH |
| Testing | **pytest** + **pytest-asyncio** + **hypothesis** | pytest 8.x, pytest-asyncio 0.24.x, hypothesis 6.152.x | HIGH |
| Frontend | **Next.js 16.2** (App Router) + **React 19** + **TypeScript 5.x** | Next.js 16.2 (Mar 18, 2026) | HIGH |
| Charting | **lightweight-charts** (vanilla; no React wrapper) | **5.2.0** | HIGH |
| Frontend state | **TanStack Query v5** + **Zustand** | TQ v5.x | HIGH |
| Monorepo | **pnpm workspaces** for JS side; Python lives in `apps/api/` with uv | pnpm 9.x | HIGH |
| Data provider | **Twelve Data REST** (locked by user) — wrapped behind `DataSource` interface | — | MEDIUM (see Open Questions) |
## Backend Python
### Core: Python 3.11+, uv, FastAPI, Pydantic v2
| Tech | Version | Why this, not the obvious alternative |
|------|---------|---------------------------------------|
| **Python 3.11+** (target 3.12) | 3.12 in dev, 3.11 minimum | 3.11 brings the asyncio speedups vectorbt and FastAPI both leverage; 3.12 adds free-threading prep and faster comprehensions. 3.13 is *supported* by all key libs but skip until ecosystem catches up further. Don't pin to 3.13 yet — pandas/numba/vectorbt wheels lag on every new minor. |
| **uv** (Astral) | 0.11.14 (May 12, 2026) | 10–100× faster than pip, 10× faster than Poetry on cold install. `uv.lock` is platform-resolution-complete (no re-resolve on a different OS — critical for "trust the numbers" backtest reproducibility). Single binary replaces pyenv + virtualenv + pip + pip-tools + most of Poetry. Community consensus in 2026 is uv. |
| **FastAPI** | 0.136.1 (Apr 23, 2026) | Async-first, OpenAPI auto-gen for the Next.js client, native WebSocket support, Pydantic v2 fully integrated. The only adult option in async Python web in 2026. Litestar is the credible alternative but smaller ecosystem and less TradingView/quant community familiarity. |
| **uvicorn[standard]** | 0.32.x | ASGI server. `[standard]` extra pulls `uvloop` (POSIX) + `httptools` for the perf win. On Windows uvloop is skipped automatically — fine, the asyncio default loop is adequate at our load. |
| **Pydantic v2** | 2.13.x | Schemas for Bar, Signal, Fill, RiskConfig. v2 is Rust-cored (10–50× faster validation than v1). Mandatory for FastAPI 0.136+ — v1 path is deprecated and being removed. |
### HTTP client: httpx
| Library | Version | Why |
|---------|---------|-----|
| **httpx** | 0.27.x | Sync + async with the same API (REPL exploration uses sync; production uses async). HTTP/2 support. Used by the OpenAI/Anthropic SDKs and FastAPI's own `TestClient`. Built-in retry/timeout primitives that requests lacks. |
### Data frames: pandas 2.2.x + polars 1.x (selective)
| Library | Version | Role |
|---------|---------|------|
| **pandas** | **2.2.x** (NOT 3.0) | Primary bar/trade DataFrame. vectorbt's API surface is pandas. Pin to `>=2.2,<3.0`. |
| **polars** | 1.x | Reach for only on hot paths: large Parquet scans, multi-symbol resampling, optimization fold preparation. Use `.to_pandas()` at the vectorbt boundary. |
### Technical indicators: pandas-ta-classic + hand-roll
| Library | Version | When |
|---------|---------|------|
| **pandas-ta-classic** (the maintained fork of pandas-ta) | latest | EMA, ADR, daily ATR, common helpers. The original `pandas-ta` is effectively abandoned; the `-classic` fork is the active continuation. |
| **TA-Lib** | 0.4.x via `ta-lib-python` | OPTIONAL. Only if you need C-speed batch indicators (you won't at 1m–15m intraday on a single instrument). Adds a native build dep — Windows install via prebuilt wheel only. |
| **Hand-rolled** | — | **ATR (Wilder's), session VWAP, ORB high/low** — these are 20-line functions, easier to unit-test against known fixtures, and avoid the surprise of upstream definition changes. Critical for "trust the numbers." |
### Market calendars: pandas_market_calendars
| Library | Version | Why |
|---------|---------|-----|
| **pandas_market_calendars** | 5.x (Mar 3, 2026 PDF doc date) | Provides NYSE *and* CME calendars (with holiday and DST-correct logic). Use `mcal.get_calendar("CME_Equity")` or `"NYSE"` and `.schedule()` to enforce RTH (9:30–16:00 ET). Solves the "is today a half-day before Thanksgiving?" class of bugs that *will* otherwise corrupt the equity curve. |
### Logging: structlog
| Library | Version | Why |
|---------|---------|-----|
| **structlog** | latest | Processor pipeline → JSON output. Critical for the audit log requirement (every signal/decision/fill needs structured, queryable records). Faster than loguru (~25% on JSON), and the processor model is the right fit for PII-free, redacted, contextvar-aware async logs. |
## Frontend
### Core: Next.js 16.2 + React 19 + TypeScript 5
| Tech | Version | Why |
|------|---------|-----|
| **Next.js** | **16.2** (Mar 18, 2026) | App Router stable, Turbopack default (Rust bundler, ~400% faster `next dev`), React 19 fully supported. For a *local-only* Bloomberg-style terminal we don't need SSR/PPR per se, but the data fetching primitives and TS DX are unmatched. |
| **React** | **19** (stable) | `use()`, `useFormStatus`, Suspense improvements, no need for memo gymnastics with React Compiler. |
| **TypeScript** | 5.x | Required. Don't ship JS in a trading app — runtime type confusion on a Bar timestamp = silent backtest corruption. |
| **pnpm** | 9.x | Workspaces, content-addressed `node_modules`, prevents phantom dependency hell. |
### Charts: lightweight-charts (vanilla, NOT a wrapper)
| Tech | Version | Why |
|------|---------|-----|
| **lightweight-charts** | **5.2.0** (Apr/May 2026) | Official TradingView library. ~50kB, canvas-rendered, supports our exact use case (candles + markers + lines + areas, real-time updates). Ships its own TypeScript declarations. |
### State + data: TanStack Query v5 + Zustand + native WebSocket
| Tech | Version | Role |
|------|---------|------|
| **@tanstack/react-query** | v5.x | REST data fetching (initial bar load, optimization results, trade history). Cache invalidation on WebSocket events. |
| **Zustand** | 5.x | Local UI state (active panel, selected strategy, draw-tool state). Smaller than Redux, no boilerplate, plays well with React 19. |
| **Native WebSocket** + small client wrapper | — | The "subscribe → update TQ cache via `setQueryData` / `invalidateQueries`" pattern is the documented community standard. Don't pull in socket.io (extra protocol layer, more deps, server complexity) — FastAPI's native WebSocket + JSON message envelopes is enough. |
### Optimization plots (heatmaps, equity curves)
| Tech | Notes |
|------|-------|
| **lightweight-charts** for OHLC + equity curve (line series) | Same lib, no extra dep |
| **Plotly.js** (`react-plotly.js`) for grid-search heatmaps | The de facto choice; vectorbt's own internal plotting is Plotly so we already get the contract |
## Data + Storage
### DuckDB + Parquet (locked)
| Tech | Version | Pattern |
|------|---------|---------|
| **DuckDB** | 1.x latest | Embedded OLAP, zero-ops, columnar. Reads/writes Parquet natively. Native `TIMESTAMPTZ` (TIMESTAMP WITH TIME ZONE) for our RTH-aware bars. |
| **Parquet (via pyarrow)** | pyarrow 17.x+ | On-disk persistence. Hive-partitioned by `symbol=/year=/month=` — that partition scheme survived peer review across multiple DuckDB time-series writeups and is the right granularity for ES at 1m for ~10 years. |
### Market data provider: Twelve Data (LOCKED — but see caveat)
| Tech | Version | Caveat |
|------|---------|--------|
| **twelvedata** (official Python client) | latest | Wrapped behind `DataSource` interface so it can be swapped without strategy/backtest changes |
- **Use `SPY` (SPDR S&P 500 ETF, NYSE Arca) as the working symbol** while building the pipeline. SPY trades 9:30–16:00 ET (matches our RTH constraint exactly), has 1m bars on Twelve Data, and tracks SPX/ES tick-for-tick at 0.1× scale. Strategy logic ported to ES later is mechanical (multiply by 10, swap tick value).
- The `DataSource` interface is the right abstraction precisely because of this — when a user upgrades to a futures-aware provider (Databento, Polygon Futures, or IB historical), only the adapter changes. The strategy/backtest/risk layer doesn't know the symbol's real exchange.
- **Validate against Twelve Data support before relying on it for ES.** Concretely: hit `GET https://api.twelvedata.com/stocks?symbol=ES` and `/commodities?symbol=ES` and inspect. If their catalog has added ES since this research, great. If not, run on SPY and treat ES as a "swap provider" phase.
- **Databento** — gold standard for CME futures, $125 free credits, usage-based pricing
- **Polygon.io** — does NOT have futures (verified May 2026)
- **Alpaca** — does NOT have futures
- **IBKR historical via `ib_async`** — free if you have an IB account, but live broker out of scope per project constraints
## Backtest / Optimize
### VectorBT 1.0.0 (OSS, locked)
| Aspect | Detail |
|--------|--------|
| **Version** | **vectorbt 1.0.0** released Apr 22, 2026 on PyPI |
| **Python** | requires `>=3.10`, supports 3.10–3.13 |
| **License** | Apache 2.0 (free, no PRO needed for ORB v1) |
| Capability | OSS (vectorbt) | PRO (vectorbtpro) |
|------------|----------------|-------------------|
| Vectorized signal-based backtests (`Portfolio.from_signals`) | YES | YES |
| Vectorized order-based backtests | YES | YES |
| Grid search via MultiIndex param sweep | YES | YES |
| Walk-forward via `Splitter` (manual fold loop) | YES (example notebook in repo) | YES (richer API) |
| Native intrabar SL/TP simulation | YES (`sl_stop`, `tp_stop` on `from_signals`) | YES (more granular) |
| **Numba JIT-compiled inner loop** | YES | YES |
| **Bring-your-own signal flexibility for ORB** | YES — generate entry/exit boolean arrays externally, pass into `Portfolio.from_signals` | YES, plus the new `from_signal_func_nb` patterns |
| Plotly visualizations | YES | YES |
| Active development / new features | Frozen-ish (1.0.0 is the OSS finalization) | Active, paid subscription |
| Documentation depth | Medium (vectorbt.dev) | Heavy (vectorbt.pro) |
- Need per-bar custom logic that can't be expressed in vectorized signals (rare for ORB — possible for trailing stops with custom rules).
- Need built-in optuna / genetic optimization (out of scope per project constraints — we're grid-only).
- Need their built-in walk-forward objective ranking.
### Optimization tooling
| Layer | Choice |
|-------|--------|
| **Grid generator** | `itertools.product` over typed parameter spaces (`OpeningRangeMinutes`, `StopATRMult`, `TargetRMult`). Yields a list of dicts → vectorbt MultiIndex param input. |
| **Walk-forward splitter** | `vbt.Splitter.from_n_rolling` for fixed-window IS/OOS rolling, or hand-rolled date splits via `pandas_market_calendars` if calendar-aware folds matter. |
| **Persistence** | Each fold's (param, IS metrics, OOS metrics, equity curve) row → DuckDB table `optimization_runs`. Equity curves as Parquet blobs or compact arrays. |
| **Leaderboard** | DuckDB SQL — `SELECT * FROM optimization_runs ORDER BY oos_sharpe DESC` is the answer. Don't over-engineer. |
## Observability / Testing
### Logging
- **structlog** with JSON output to stdout (FastAPI dev console) and rolling file under `data/logs/audit/{date}.jsonl`.
- Correlation ID per signal: `signal_id = uuid7()` (time-sortable) attached to every downstream record (risk decision, fill, position update). Forensic replay = `jq 'select(.signal_id == "...")'`.
### Metrics (lightweight)
- For v1 (local-only), **no Prometheus**. A `/metrics` endpoint exposing counters (signals/min, fills/min, daily PnL, distance-to-DD-breaker) as plain JSON, polled by a UI panel, is plenty.
- Add `prometheus-client` + Grafana only if observability becomes an actual bottleneck (it won't at one operator + one strategy).
### Testing
| Tool | Version | Role |
|------|---------|------|
| **pytest** | 8.x | Test runner. |
| **pytest-asyncio** | 0.24.x | Async tests for the bus / FastAPI WS routes. Use `asyncio_mode = "auto"` in `pyproject.toml`. |
| **hypothesis** | 6.152.x | Property-based tests for the risk math (`size_for_atr_stop`), session filter (no bar ever escapes RTH), and the order ledger invariants (sum of fills = position; daily DD never negative without a stop fill). |
| **pytest-cov** | latest | Coverage gates on `risk/`, `execution/`, `backtest/` (strategy layer can be lower). |
| **respx** | latest | httpx mock for the Twelve Data adapter tests. |
| **freezegun** | latest | Pin time in session/calendar tests. |
- A canonical "synthetic ORB day" fixture: a bar series where the breakout happens at a known time and the trade outcome is hand-computed. Every refactor must keep this test green or trust is gone.
- A "Daylight Saving Time" fixture: bars across the spring-forward and fall-back days, asserting the session filter still produces 390 minutes of 1m bars.
## TradingView Integration
### TradingView Desktop + TradingView MCP (locked, already running)
| Aspect | Detail |
|--------|--------|
| **MCP server location** | `C:\Users\Admin\tradingview-mcp-jackson\` (78 tools) — runtime already wired |
| **Surface** | Chart control (`chart_set_symbol`, `chart_set_timeframe`), drawing (`draw_shape` for ORB box / entries / stops / targets as horizontal_line, rectangle, trend_line), Pine console (`data_get_study_values`, `data_get_pine_*` for Pine output reads), replay (`replay_start` / `replay_step`), alerts (`alert_create`), screenshots, batch ops |
| **Symbol on TV side** | `CME_MINI:ES1!` for ES continuous front-month, `CME_MINI:MES1!` for MES — the TradingView native continuous-contract suffix |
| **Pattern** | Python is the brain. The TV chart is the visualization + ground-truth replay surface. Backend Python issues MCP calls to keep the chart in sync with whatever the operator is investigating (date, symbol, drawn ORB zone). |
| **Caveat** | MCP requires Pine indicators to be *visible* for `data_get_pine_*` reads to return — the system must add/manage them deliberately. |
### Lightweight Charts vs TradingView MCP chart — which is for what?
| Surface | Purpose |
|---------|---------|
| **Embedded Lightweight Charts (in Next.js panel)** | Fast, in-app candle visualization tied to our own backtest replay. Always available, no external dep. |
| **TradingView Desktop (driven via MCP)** | Operator's primary visual research surface. Lets them eyeball strategy behavior on the same charts they already trust, with all their indicators/drawings/Pine scripts loaded. |
## What NOT to Use
| Avoid | Why | Use Instead |
|-------|-----|-------------|
| **pandas 3.0** (released Jan 21, 2026) | Breaking changes (Copy-on-Write, `str` dtype default). vectorbt's 1.0.0 may or may not have caught up — verify before adopting. | **pandas 2.2.x** until vectorbt explicitly documents 3.0 support. |
| **Python 3.13** as minimum | Wheels for numba/numpy/pandas/vectorbt lag every minor release. | **Python 3.11 minimum, 3.12 target**. |
| **Poetry** | Dependency resolution is 10× slower than uv, lockfile is not platform-resolution-complete, two extra subcommands for every action. | **uv**. |
| **`requests`** | No async. You'll end up with a second client just for the FastAPI side. | **httpx** (sync + async one API). |
| **`aiohttp`** | Async-only. Doesn't compose with the notebook/CLI scripts you'll run for ad-hoc backtest exploration. | **httpx**. |
| **`pandas-ta`** (original) | Effectively unmaintained; depends on the original `pandas-ta` package which has bitrotted. | **`pandas-ta-classic`** (active fork), or hand-roll the ~6 indicators we actually need. |
| **TA-Lib** (as the default) | Native build dependency. On Windows requires prebuilt wheels — and pinning that toolchain in CI is its own problem. Overkill for 1m–15m intraday on a single instrument. | Hand-rolled ATR/VWAP; `pandas-ta-classic` for the rest. Reach for TA-Lib only if perf is proven to be a bottleneck. |
| **socket.io / python-socketio** | Adds a protocol layer over WebSocket, server-side state, extra deps. Designed for multi-worker fan-out with Redis pub/sub. We're single-process, single-operator. | **FastAPI native `WebSocket`** + an in-process broadcaster. |
| **lightweight-charts-react-wrapper / -react-components** | Both lag v5 by 2+ years. Will fight React 19. Lock you out of v5 series API (panes, `addSeries`, the new `IChartApi.addCustomSeries`). | **Vanilla `lightweight-charts` v5** inside a `useEffect`-mounted ref. The official tutorial is 40 lines. |
| **Redux / Redux Toolkit** | Overkill for a single-operator local app. Boilerplate per slice fights React 19's `use()`. | **Zustand** for local UI + **TanStack Query** for server state. |
| **socket.io** on the JS side | Same as Python side — protocol overhead for no scaling benefit. | Native `WebSocket` + a tiny client wrapper. |
| **Loguru** for primary logger | Lacks a true processor pipeline — harder to enforce structured fields for audit replay. ~25% slower JSON output than structlog. | **structlog**. Use Loguru only if you need its colorful stderr in REPL — and even then, route everything through structlog. |
| **Postgres / TimescaleDB** | Zero-ops requirement violated. DBA work, schema migrations, container management. Bars are immutable time series, not OLTP. | **DuckDB + Parquet** (locked). |
| **SQLite for time series** | Row-oriented, no columnar pushdown, no Parquet interop, slow on the multi-million-row scans grid search requires. | **DuckDB** (also embedded, also zero-ops, but columnar). |
| **`backtrader`, `zipline`, `backtesting.py`** | Event-loop backtests; ~100–1000× slower than vectorbt at grid search; smaller communities; zipline is unmaintained. | **vectorbt**. |
| **`talipp`** as primary indicator lib | Incremental O(1) updates only help live streams. vectorbt is batch-vectorized — the impedance mismatch costs more than it saves. | **pandas-ta-classic + hand-rolled**. |
| **`yfinance` as primary feed** | Free but unreliable, no SLA, no API key, scraping-based, no futures continuous contracts. Fine for one-off sanity checks; not for "trust the numbers." | **Twelve Data** (with the SPY-proxy caveat above). |
| **Genetic / Bayesian optimizers (optuna, hyperopt) in v1** | Explicit project constraint. Adds an optimizer's own bias and reduces interpretability before we have a baseline edge. | **Grid + walk-forward** only for v1. |
| **Conda / Anaconda** | Heavier than uv, slower env creation, mixes its own package channel with PyPI in ways that hurt reproducibility. | **uv** + PyPI. |
| **Docker for local dev** | Project is explicitly local-only single-operator. Containerization is overhead with zero v1 benefit. | Run uv + Node directly on Windows. Add Docker later if cloud deploy is reopened. |
## Installation
# 1) Install uv (Windows PowerShell)
# 2) Create project + sync deps (run from repo root)
# 3) Frontend (assumes pnpm 9.x installed via corepack)
## Version Compatibility Matrix
| Package A | Compatible With | Notes |
|-----------|-----------------|-------|
| `vectorbt==1.0.0` | `python>=3.10,<3.14`, `pandas>=2.0,<3.0`, `numpy<2.0 OR >=2.0 depending on build` | Pin pandas `<3.0` until vbt 1.x explicitly publishes 3.0 support |
| `fastapi==0.136.*` | `pydantic>=2.10`, `python>=3.10` | v1 pydantic path is removed-or-deprecating |
| `pydantic==2.13.*` | `python>=3.9,<3.15` | Rust-cored validator; orders of magnitude faster than v1 |
| `duckdb` (latest 1.x) | `pyarrow>=14`, `pandas` any modern, `polars>=1.0` | All three play nicely; DuckDB is the glue |
| `lightweight-charts@5.2.0` | `react>=18`, works fine with React 19 | Do NOT use any React wrapper package — see What NOT to Use |
| `next.js@16.2` | `react@19`, `node>=18.18` | App Router is the only path for new projects |
| `pandas_market_calendars` | `pandas>=2.0` | NYSE + CME calendars |
## Open Questions
## Sources
- [vectorbt on PyPI](https://pypi.org/project/vectorbt/) — version 1.0.0 confirmed (Apr 22, 2026) — HIGH
- [vectorbt repo + WalkForwardOptimization example](https://github.com/polakowo/vectorbt) — pattern confirmed — HIGH
- [FastAPI on PyPI](https://pypi.org/project/fastapi/) — version 0.136.1 (Apr 23, 2026) — HIGH
- [Pydantic v2.13 release](https://pypi.org/project/pydantic/) — May 6, 2026 — HIGH
- [uv on PyPI](https://pypi.org/project/uv/) — 0.11.14 (May 12, 2026) — HIGH
- [uv vs Poetry vs pip-tools (2026)](https://www.danilchenko.dev/posts/uv-vs-pip-vs-poetry/) — community consensus — MEDIUM
- [Next.js 16.2 release blog](https://nextjs.org/blog) — Mar 18, 2026 — HIGH
- [lightweight-charts on npm](https://www.npmjs.com/package/lightweight-charts) — v5.2.0 — HIGH
- [lightweight-charts React tutorial (official)](https://tradingview.github.io/lightweight-charts/tutorials/react/simple) — wrapper pattern — HIGH
- [pandas 3.0 release notes (Jan 21, 2026)](https://pandas.pydata.org/docs/whatsnew/v3.0.0.html) — breaking changes documented — HIGH
- [pandas_market_calendars docs (Mar 3, 2026)](https://pandas-market-calendars.readthedocs.io/en/latest/usage.html) — CME RTH support — HIGH
- [DuckDB partitioning guides (2026)](https://medium.com/@Quaxel/5-duckdb-partitioning-moves-that-make-time-reads-fly-de7f77a51d71) — partitioning pattern — MEDIUM
- [DuckDB TIMESTAMPTZ timezone guide](https://duckdb.org/docs/current/guides/sql_features/timestamps) — HIGH
- [HTTPX vs Requests vs AIOHTTP (2026 comparison)](https://decodo.com/blog/httpx-vs-requests-vs-aiohttp) — MEDIUM
- [FastAPI WebSocket scaling patterns (2026)](https://github.com/fastapi/fastapi/discussions/14807) — broadcast pattern — MEDIUM
- [structlog vs loguru (2026)](https://www.dash0.com/guides/python-logging-libraries) — MEDIUM
- [Twelve Data exchanges/market-data pages](https://twelvedata.com/exchanges) — futures NOT listed — HIGH (negative finding)
- [Twelve Data Python client README](https://github.com/twelvedata/twelvedata-python) — asset types: stocks/forex/crypto/etf/indices, no futures — HIGH (negative finding)
- [Twelve Data Indices page](https://twelvedata.com/indices) — "coming soon" as of May 2026 — HIGH
- [TanStack Query + WebSockets pattern (TkDodo)](https://tkdodo.eu/blog/using-web-sockets-with-react-query) — `setQueryData` + `invalidateQueries` — HIGH
- [pandas-ta-classic on PyPI](https://pypi.org/project/pandas-ta-classic/) — active fork — HIGH
- [talipp on PyPI](https://pypi.org/project/talipp/) — incremental indicators, evaluated and not chosen — HIGH
<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->
## Conventions

Conventions not yet established. Will populate as patterns emerge during development.
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->
## Architecture

Architecture not yet mapped. Follow existing patterns found in the codebase.
<!-- GSD:architecture-end -->

<!-- GSD:skills-start source:skills/ -->
## Project Skills

No project skills found. Add skills to any of: `.claude/skills/`, `.agents/skills/`, `.cursor/skills/`, `.github/skills/`, or `.codex/skills/` with a `SKILL.md` index file.
<!-- GSD:skills-end -->

<!-- GSD:workflow-start source:GSD defaults -->
## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:
- `/gsd-quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd-debug` for investigation and bug fixing
- `/gsd-execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->



<!-- GSD:profile-start -->
## Developer Profile

> Profile not yet configured. Run `/gsd-profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
