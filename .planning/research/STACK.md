# Stack Research — ES Futures Trading System

**Domain:** Intraday futures backtest + paper-trading system with Bloomberg-style web UI
**Researched:** 2026-05-14
**Overall confidence:** HIGH on locked-in choices and Python/JS ecosystems; **MEDIUM** on Twelve Data ES coverage (see Open Questions — major caveat).

---

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

---

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

Picked over `requests` (no async — would force a second client for the WebSocket fan-out path) and `aiohttp` (async-only — can't reuse it in CLI/notebook code; we need both surfaces for backtest scripts and the live FastAPI app).

### Data frames: pandas 2.2.x + polars 1.x (selective)

| Library | Version | Role |
|---------|---------|------|
| **pandas** | **2.2.x** (NOT 3.0) | Primary bar/trade DataFrame. vectorbt's API surface is pandas. Pin to `>=2.2,<3.0`. |
| **polars** | 1.x | Reach for only on hot paths: large Parquet scans, multi-symbol resampling, optimization fold preparation. Use `.to_pandas()` at the vectorbt boundary. |

pandas 3.0 (Jan 21, 2026) introduces Copy-on-Write semantics and `str` dtype default. Real breaking changes. Adopt after vectorbt 1.x has verified compatibility in a point release — currently risky.

### Technical indicators: pandas-ta-classic + hand-roll

| Library | Version | When |
|---------|---------|------|
| **pandas-ta-classic** (the maintained fork of pandas-ta) | latest | EMA, ADR, daily ATR, common helpers. The original `pandas-ta` is effectively abandoned; the `-classic` fork is the active continuation. |
| **TA-Lib** | 0.4.x via `ta-lib-python` | OPTIONAL. Only if you need C-speed batch indicators (you won't at 1m–15m intraday on a single instrument). Adds a native build dep — Windows install via prebuilt wheel only. |
| **Hand-rolled** | — | **ATR (Wilder's), session VWAP, ORB high/low** — these are 20-line functions, easier to unit-test against known fixtures, and avoid the surprise of upstream definition changes. Critical for "trust the numbers." |

NOT picking `talipp` despite incremental O(1) updates — vectorbt is vectorized batch, so streaming-style incremental indicators add architectural friction. Reach for talipp only if a future live-trade path materializes.

### Market calendars: pandas_market_calendars

| Library | Version | Why |
|---------|---------|-----|
| **pandas_market_calendars** | 5.x (Mar 3, 2026 PDF doc date) | Provides NYSE *and* CME calendars (with holiday and DST-correct logic). Use `mcal.get_calendar("CME_Equity")` or `"NYSE"` and `.schedule()` to enforce RTH (9:30–16:00 ET). Solves the "is today a half-day before Thanksgiving?" class of bugs that *will* otherwise corrupt the equity curve. |

### Logging: structlog

| Library | Version | Why |
|---------|---------|-----|
| **structlog** | latest | Processor pipeline → JSON output. Critical for the audit log requirement (every signal/decision/fill needs structured, queryable records). Faster than loguru (~25% on JSON), and the processor model is the right fit for PII-free, redacted, contextvar-aware async logs. |

Loguru is the tempting alternative for ergonomics but the *audit log forensic replay* requirement leans on structured pipeline composition (correlation IDs across `Signal → Risk → Executor → Fill`) which structlog does better.

---

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

**Use the vanilla library directly inside a `useEffect`-mounted React component** — do NOT pull in a React wrapper. The two major wrappers (`lightweight-charts-react-wrapper` and `lightweight-charts-react-components`) are *years* behind v5, will fight React 19, and lock you out of the v5 series API (panes, `addSeries`, etc.). The official docs example for React is ~40 lines and is the correct pattern. This is one of those cases where "the wrapper saves time" is a lie — it costs more time than it saves.

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

---

## Data + Storage

### DuckDB + Parquet (locked)

| Tech | Version | Pattern |
|------|---------|---------|
| **DuckDB** | 1.x latest | Embedded OLAP, zero-ops, columnar. Reads/writes Parquet natively. Native `TIMESTAMPTZ` (TIMESTAMP WITH TIME ZONE) for our RTH-aware bars. |
| **Parquet (via pyarrow)** | pyarrow 17.x+ | On-disk persistence. Hive-partitioned by `symbol=/year=/month=` — that partition scheme survived peer review across multiple DuckDB time-series writeups and is the right granularity for ES at 1m for ~10 years. |

**Idioms locked in by research:**

1. **Storage timezone:** Store bars in **UTC** as `TIMESTAMPTZ`, convert to `America/New_York` at read time inside the session-filter layer. Don't store local time — DST will silently shift bars twice a year. (See PITFALLS.md.)
2. **Partition by `symbol=X/year=Y/month=M/`** — coarser (year-only) wastes scan time, finer (day-level) creates thousands of tiny Parquet files that DuckDB hates.
3. **Upserts:** DuckDB has no native UPSERT on partitioned Parquet. Pattern is: read partition → merge in DataFrame → rewrite partition. Idempotent. Use a `bar_hash` column to detect provider revisions.
4. **Row groups:** target ~100k rows per row group — DuckDB's zonemaps + filter pushdown kick in here.
5. **Compaction job:** weekly task that rewrites the current month's Parquet into a single file (instead of N append shards).

### Market data provider: Twelve Data (LOCKED — but see caveat)

| Tech | Version | Caveat |
|------|---------|--------|
| **twelvedata** (official Python client) | latest | Wrapped behind `DataSource` interface so it can be swapped without strategy/backtest changes |

**CRITICAL CAVEAT — read this carefully:**

Twelve Data's published asset catalog (verified across `twelvedata.com/market-data`, `twelvedata.com/exchanges`, and the official Python client README on 2026-05-14) lists **Stocks, Forex, ETFs, Crypto, Commodities, and Indices**. **CME equity index futures (ES, MES) are NOT documented as supported.** Their "Indices" surface was "coming soon" on the public Indices page as of May 2026.

**Practical implication for v1:**

- **Use `SPY` (SPDR S&P 500 ETF, NYSE Arca) as the working symbol** while building the pipeline. SPY trades 9:30–16:00 ET (matches our RTH constraint exactly), has 1m bars on Twelve Data, and tracks SPX/ES tick-for-tick at 0.1× scale. Strategy logic ported to ES later is mechanical (multiply by 10, swap tick value).
- The `DataSource` interface is the right abstraction precisely because of this — when a user upgrades to a futures-aware provider (Databento, Polygon Futures, or IB historical), only the adapter changes. The strategy/backtest/risk layer doesn't know the symbol's real exchange.
- **Validate against Twelve Data support before relying on it for ES.** Concretely: hit `GET https://api.twelvedata.com/stocks?symbol=ES` and `/commodities?symbol=ES` and inspect. If their catalog has added ES since this research, great. If not, run on SPY and treat ES as a "swap provider" phase.

Confidence on the Twelve Data ES claim: **LOW** that ES is directly available; **HIGH** that SPY works as a proxy.

Recommended candidates for the inevitable provider swap (out of scope for v1 but worth knowing):
- **Databento** — gold standard for CME futures, $125 free credits, usage-based pricing
- **Polygon.io** — does NOT have futures (verified May 2026)
- **Alpaca** — does NOT have futures
- **IBKR historical via `ib_async`** — free if you have an IB account, but live broker out of scope per project constraints

---

## Backtest / Optimize

### VectorBT 1.0.0 (OSS, locked)

| Aspect | Detail |
|--------|--------|
| **Version** | **vectorbt 1.0.0** released Apr 22, 2026 on PyPI |
| **Python** | requires `>=3.10`, supports 3.10–3.13 |
| **License** | Apache 2.0 (free, no PRO needed for ORB v1) |

**Free vs PRO feature delta (relevant subset):**

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

**ORB-specific pattern that works on OSS:**

The right OSS pattern for ORB:
1. Compute the opening-range high/low per session in pandas (group by session date).
2. Generate `entries`, `exits`, and use `sl_stop`/`tp_stop` (in price terms, e.g., `0.5 * ATR`) on `Portfolio.from_signals`.
3. For the walk-forward analysis, use `vbt.Splitter` to chop the bar DataFrame into IS/OOS windows, run `Portfolio.from_signals` per fold with the grid of params, and aggregate Sharpe/expectancy/PF.

**Upgrade to PRO only if** you hit one of these:
- Need per-bar custom logic that can't be expressed in vectorized signals (rare for ORB — possible for trailing stops with custom rules).
- Need built-in optuna / genetic optimization (out of scope per project constraints — we're grid-only).
- Need their built-in walk-forward objective ranking.

For the v1 ORB scope, OSS 1.0.0 is sufficient.

### Optimization tooling

| Layer | Choice |
|-------|--------|
| **Grid generator** | `itertools.product` over typed parameter spaces (`OpeningRangeMinutes`, `StopATRMult`, `TargetRMult`). Yields a list of dicts → vectorbt MultiIndex param input. |
| **Walk-forward splitter** | `vbt.Splitter.from_n_rolling` for fixed-window IS/OOS rolling, or hand-rolled date splits via `pandas_market_calendars` if calendar-aware folds matter. |
| **Persistence** | Each fold's (param, IS metrics, OOS metrics, equity curve) row → DuckDB table `optimization_runs`. Equity curves as Parquet blobs or compact arrays. |
| **Leaderboard** | DuckDB SQL — `SELECT * FROM optimization_runs ORDER BY oos_sharpe DESC` is the answer. Don't over-engineer. |

---

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

**Critical test fixtures:**
- A canonical "synthetic ORB day" fixture: a bar series where the breakout happens at a known time and the trade outcome is hand-computed. Every refactor must keep this test green or trust is gone.
- A "Daylight Saving Time" fixture: bars across the spring-forward and fall-back days, asserting the session filter still produces 390 minutes of 1m bars.

---

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

Both are first-class. The system reflects state to both: when the operator clicks a trade in the in-app blotter, the FastAPI backend pushes that date/time to TradingView via MCP, drawing the entry/stop/target on their TV chart.

---

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

---

## Installation

```bash
# 1) Install uv (Windows PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# 2) Create project + sync deps (run from repo root)
uv init --python 3.12
uv add fastapi==0.136.* "uvicorn[standard]==0.32.*" "pydantic==2.13.*" httpx duckdb pyarrow pandas==2.2.* polars pandas-ta-classic pandas_market_calendars structlog vectorbt==1.0.0 twelvedata
uv add --dev pytest pytest-asyncio hypothesis pytest-cov respx freezegun ruff mypy

# 3) Frontend (assumes pnpm 9.x installed via corepack)
pnpm create next-app@latest apps/web --typescript --app --turbopack --no-tailwind  # use Tailwind only if you want; dense terminal style works either way
cd apps/web
pnpm add lightweight-charts@^5.2.0 @tanstack/react-query@^5 zustand react-plotly.js plotly.js
pnpm add -D typescript @types/react @types/react-dom @types/plotly.js
```

---

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

---

## Open Questions

These are unresolved after this research pass and should be answered before or during Phase 1 (data ingestion):

1. **Does Twelve Data actually serve ES (E-mini S&P 500) futures bars?** Public docs say no (Stocks/Forex/ETF/Crypto/Commodities/Indices-coming-soon only). **Action:** in Phase 1, hit `/stocks?symbol=ES`, `/commodities?symbol=ES`, `/indices?symbol=SPX` and document the answer. If ES is absent (likely), confirm SPY as the v1 working symbol and document the eventual provider swap as Phase-N work.

2. **What's the exact Twelve Data 1m intraday rate limit on the chosen tier?** Free tier is ~8 req/min, ~800/day. We need to know whether a full historical backfill of 2 years of 1m SPY (~196,000 bars across pagination) fits within day-budget or requires Starter tier ($).

3. **VectorBT 1.0.0 + pandas 2.2 + numpy version compatibility on Windows.** Verify with `uv pip compile` *before* committing the lockfile; numba's numpy ceilings have historically been the silent killer.

4. **TradingView MCP authentication / re-attach behavior across PowerShell sessions.** The 78 tools assume an attached desktop session. Need a Phase 0 smoke test that confirms the FastAPI process can reliably issue MCP calls and recover when the TV desktop client restarts.

5. **DuckDB on Windows with large Parquet partitions** — there have been historical issues with Parquet writes on Windows filesystems (file locking, atomic rename). Verify with a 1 GB synthetic write test before locking the storage layer.

6. **Does VectorBT 1.0.0 actually support `sl_stop`/`tp_stop` at the level of intrabar fidelity we need for an ATR-based ORB?** The OSS docs are thin on the *exact* fill semantics when stop and target are both inside the same bar. Smoke-test with hand-computed expected trades before declaring the backtest "trustable."

---

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

---
*Stack research for: intraday ES futures backtest + paper-trading system with Bloomberg-Terminal-style web UI*
*Researched: 2026-05-14*
