# Requirements: ES Futures Trading System

**Defined:** 2026-05-14
**Core Value:** Trust the numbers — every reported backtest result is reproducible, leakage-free, and survives walk-forward, because every downstream decision compounds on top of it.

## v1 Requirements

Requirements for initial release. Each maps to roadmap phases. REQ-IDs use the 7-module taxonomy from research/FEATURES.md plus a Foundation category.

### Foundation & Reproducibility

- [ ] **FND-01**: Project scaffolded as a `uv` workspace monorepo with `packages/{trading-core, api, tv-bridge}` Python packages and `apps/web/` Next.js app; `uv.lock` committed before any backtest is run
- [ ] **FND-02**: `pyproject.toml` pins exact dependencies: Python 3.11–3.12, `vectorbt==1.0.0`, `pandas>=2.2,<3.0`, FastAPI, Pydantic v2, DuckDB, structlog, httpx, pytest, hypothesis, respx, freezegun
- [ ] **FND-03**: Pydantic Settings loader merges `.env` (secrets, gitignored) + `config/*.yaml` (system / risk / strategy params); `.env.example` committed
- [ ] **FND-04**: `gitleaks` pre-commit hook blocks any API key / .env content from entering git history
- [ ] **FND-05**: Repo-wide UTC discipline: every timestamp stored as tz-aware UTC; pre-commit lint forbids `datetime.now()` and `datetime.utcnow()` without explicit timezone
- [ ] **FND-06**: `instruments.py` single-source-of-truth registry exposes `tick_value`, `point_value`, `tick_size`, `session_open_et`, `session_close_et` for ES, MES, SPY (proxy); every dollar-denominated calc reads from it (no magic numbers)
- [ ] **FND-07**: `EventBus` (in-process asyncio pub/sub) with typed topics: `bars`, `signals`, `risk_decisions`, `fills`, `positions`, `equity`; deterministic event ordering enforced
- [ ] **FND-08**: Every run logs `git_sha / data_hash / param_hash / seed` to a `runs` table; reproducibility CI test asserts same input → bitwise-identical equity curve
- [ ] **FND-09**: `structlog` JSON logging with correlation IDs threaded through every async boundary
- [ ] **FND-10**: Provider-validation ADR committed to `.planning/decisions/` documenting (a) Twelve Data's ES coverage as of the ADR date, (b) the chosen v1 primary feed (TradingView MCP) and rationale, (c) the eventual futures-aware swap candidate (Databento / Polygon Futures / IB)

### Market Data Ingestion (MD)

- [ ] **MD-01**: `DataSource` protocol defines `fetch_bars(symbol, tf, start, end) -> DataFrame[Bar]` and `subscribe_bars(symbol, tf) -> AsyncIterator[Bar]`; all readers code against the protocol, never an implementation
- [ ] **MD-02**: `TradingViewDataSource` implementation pulls bars via TradingView MCP `data_get_ohlcv` (live polling + replay-driven historical); reconnects transparently when TV restarts
- [ ] **MD-03**: `TwelveDataSource` implementation (secondary) pulls 1m / 5m / 15m bars from Twelve Data REST for SPY (and any other Twelve-Data-supported proxy); used for headless CI runs and cross-vendor reconciliation
- [ ] **MD-04**: Bars persisted to DuckDB + Hive-partitioned Parquet (`symbol=/year=/month=`) with idempotent upsert keyed on `(symbol, tf, ts_utc)`; single-writer convention enforced (FastAPI process holds the only writer connection)
- [ ] **MD-05**: RTH session filter applies the **CME equity-index calendar** (`pandas_market_calendars` `CME_Equity`, NOT NYSE) including half-days and exchange holidays
- [ ] **MD-06**: Bar timestamps documented as **open-time** (matching TradingView and Twelve Data convention); helper functions enforce next-bar reference everywhere downstream
- [ ] **MD-07**: Bar-gap detector flags missing bars within RTH and writes them to a `bar_gaps` table; UI surfaces gaps before any backtest is run on the affected window
- [ ] **MD-08**: Continuous-contract rollover-seam detector flags 3rd-Friday-of-Mar/Jun/Sep/Dec boundary bars; strategies receive a `rollover_seam: bool` field and ORB masks them out
- [ ] **MD-09**: CLI command `seed_bars.py --symbol <SYM> --tf <TF> --from <DATE> --to <DATE>` backfills history through the configured `DataSource`
- [ ] **MD-10**: Daily reconciliation pass compares same-window TradingView bars vs Twelve Data SPY-proxy bars (when both are available); divergences > 0.05% on price or > 5% on volume raise an alert in the audit log

### Strategy Engine (STR)

- [ ] **STR-01**: `Strategy` protocol defines `on_bar(bar, ctx) -> Signal | None` and `warmup_bars() -> int`; same code path runs in backtest and live (load-bearing invariant)
- [ ] **STR-02**: `StrategyContext` exposes indicator snapshots (`atr_14`, `vwap`, `ema_20`, `adr_20`), current session-open-range high/low, position state, and the rollover-seam flag for the current bar
- [ ] **STR-03**: Indicators (ATR Wilder, VWAP, EMA, ADR) are computed without look-ahead — `snapshot_at(t)` only references bars `≤ t`; higher-timeframe features always `.shift(1)` after resample
- [ ] **STR-04**: `ORBStrategy` reference implementation accepts config-driven `opening_range_minutes` (default 15), `atr_stop_mult`, `r_target`, `max_entries_per_day`, `latest_entry_time`, `range_to_atr_min`, `bar_close_confirmation` flag
- [ ] **STR-05**: Every emitted `Signal` carries strategy ID + version + bar timestamp + side (LONG/SHORT) + proposed entry + proposed stop + proposed target + size hint
- [ ] **STR-06**: Strategy registration: `strategies/orb.yaml` describes the strategy + param defaults; UI lists registered strategies by reading this dir

### Backtesting Module (BT)

- [ ] **BT-01**: `BacktestEngine` consumes `(DataSource, Strategy, RiskManager, Executor, config)` and emits `BacktestResult{trades, equity_curve, metrics, attribution_ledger}`; same `Strategy.on_bar` is driven by a `SyntheticClock` over historical bars
- [ ] **BT-02**: `safe_from_signals()` wrapper around `vbt.Portfolio.from_signals` mandates `entries.shift(1)` and `price='nextbar'`; direct calls to `from_signals` blocked by a `noqa`-style lint check
- [ ] **BT-03**: Fill simulation: next-bar-open entry + configurable tick slippage (1 tick default, session-phase-aware adjustment of ≥1.5 ticks during the 9:30 open window) + per-side commission + worst-case intrabar stop/target resolution when both touch
- [ ] **BT-04**: Standard metrics: total return, CAGR, Sharpe, Sortino, Calmar, max drawdown, max drawdown duration, win rate, expectancy ($/trade), profit factor, trade count, average hold time
- [ ] **BT-05**: Per-trade MAE / MFE persisted alongside trade ledger
- [ ] **BT-06**: Full attribution chain persisted: every fill row references the signal row that produced it and the risk-decision row that approved it
- [ ] **BT-07**: **Lookahead-leakage detector**: a CI assertion test constructs a deliberately-leaking strategy (`close.shift(-1)` based) and asserts the `safe_from_signals()` wrapper neutralizes it (Sharpe stays finite, win rate ~50%); test must run on every PR
- [ ] **BT-08**: EOD forced flat: at `session_close - 60s` wall-clock (live) or last RTH bar (backtest), any open position is closed at next-bar-open; assertion `sum(positions) == 0` after EOD
- [ ] **BT-09**: Backtest CLI: `run_backtest.py --strategy orb --symbol SPY --tf 1m --from 2024-01-01 --to 2026-04-30 --config <yaml>` produces a `BacktestResult` row in DuckDB + equity-curve Parquet

### Parameter Optimization (OPT)

- [ ] **OPT-01**: Grid expansion from `optspace.yaml` (typed parameter ranges with step / list / range syntax)
- [ ] **OPT-02**: `ProcessPoolExecutor` worker harness: workers open DuckDB read-only, write per-worker Parquet shards, orchestrator aggregates into `opt_runs` / `opt_results` in a single-process pass
- [ ] **OPT-03**: Walk-forward analysis with configurable IS/OOS window split (anchored or rolling), step size, and warmup placement
- [ ] **OPT-04**: **Pre-run ADR gate**: every optimization run requires a committed ADR file in `.planning/decisions/` declaring IS/OOS split, parameter grid, objective function, seed; ADR hash logged on every `opt_run` row
- [ ] **OPT-05**: Per-fold persistence: each fold's equity curve, metrics, and selected best-IS params written to `opt_results` with full hashes (`git_sha / data_hash / param_grid_hash / seed`)
- [ ] **OPT-06**: Coarse-grid-first protocol enforced: ranges narrower than 5 points per axis require a documented coarser run first (audit-log warning otherwise)
- [ ] **OPT-07**: OOS Sharpe is the **default ranking metric**; leaderboard sorts by OOS, never IS; an IS/OOS edge-ratio column flags overfit candidates (ratio > 2 = red flag)
- [ ] **OPT-08**: "True holdout" guard: the most-recent 6 months of bars refuses to be queried by the optimization API until an explicit `--burn-holdout` flag is passed; flag use is rate-limited (max 3 burns per quarter, tracked in a `holdout_burns` table)
- [ ] **OPT-09**: 2-parameter heatmap export (any pair of grid axes) viewable in the UI

### Signal Pipeline (SP)

- [ ] **SP-01**: asyncio pub/sub bus routes `Signal → RiskManager → Executor → Fill` with deterministic event ordering; signal queue is single-threaded to eliminate race between signal and risk-state read
- [ ] **SP-02**: `RiskManager.check(signal, state)` is the **only** path from signal to fill; backdoors forbidden by lint; audit log captures every risk decision (approve / reject + reason code)
- [ ] **SP-03**: Audit log: every event (bar tick, signal, risk decision, fill, position update, equity update, kill switch, flatten command) persisted synchronously to DuckDB **and** mirrored to a daily CSV; survives `kill -9` (no buffered writes)
- [ ] **SP-04**: `Replay` command: re-feeds bars from DuckDB through the full pipeline; assertion that re-played audit log is byte-identical to the original
- [ ] **SP-05**: **Kill switch** halts all signal processing immediately (no new entries, existing positions held); **separate** `Flatten` command closes all open positions at next-bar-open; both have different hotkeys, different buttons, and different confirmations
- [ ] **SP-06**: Sequence numbers on every WebSocket message + `state_version` field; client detects gaps and requests a snapshot resync

### Risk Manager (RM)

- [ ] **RM-01**: ATR-based position sizing: `contracts = floor(risk_$ / (stop_ticks × tick_value))` using `instruments.py` values; unit tests `size(1000, 5, MES) == 40` and `size(1000, 5, ES) == 4`
- [ ] **RM-02**: `DrawdownModel` enum: `STATIC`, `TRAILING_EOD`, `TRAILING_INTRADAY`; default `TRAILING_INTRADAY` (Apex-style); risk manager tracks **all three side-by-side** and writes each to `risk_state` so misconfiguration is visible
- [ ] **RM-03**: Pre-trade `worst_case_loss` check: signal's stop distance × tick value × proposed size must not push the chosen DD model past its floor; rejection with `reason='dd_floor_violation'`
- [ ] **RM-04**: Daily-DD circuit breaker (default $2000) halts new entries when realized + unrealized PnL drops past the threshold; existing positions kept (kill-switch behavior, not flatten)
- [ ] **RM-05**: HWM persisted to DuckDB on every update; engine refuses to start without today's HWM row (computed from yesterday's close + any pre-market equity delta)
- [ ] **RM-06**: Max contracts cap (default 2 MES) enforced per signal regardless of sizing math
- [ ] **RM-07**: EOD flatten-all is a **wall-clock scheduler** (not bar-driven) firing at `session_close - 60s`; same logic enforced in backtester via synthetic clock
- [ ] **RM-08**: Per-strategy concurrency cap: only one active position per strategy ID at a time (multi-strategy comes in v2)

### Web App / UI (UI)

- [ ] **UI-01**: FastAPI backend exposes REST + WebSocket endpoints: `GET /bars`, `GET /positions`, `GET /trades`, `GET /equity`, `GET /backtests`, `GET /optimizations`, `POST /backtests`, `POST /optimizations`, `POST /kill`, `POST /flatten`, `WS /stream`
- [ ] **UI-02**: WebSocket reconnect with exponential backoff + jitter; client maintains sequence cursor; gap detection triggers REST snapshot resync
- [ ] **UI-03**: Next.js 16.2 + React 19 + TypeScript + dark monospace theme; multi-pane configurable grid layout (drag/resize panes); responsive only for desktop widths (no mobile breakpoint)
- [ ] **UI-04**: **Chart panel**: TradingView Lightweight Charts (vanilla, mounted inside React `useEffect` — no wrapper); ES/SPY candles + ORB box overlay + signal markers (entry arrow + stop line + target line); `timeFormatter` + `tickMarkFormatter` configured to `America/New_York` (no browser-TZ drift)
- [ ] **UI-05**: **Order blotter panel**: live table of open positions with avg fill price, current price, unrealized P&L, distance to stop (in $ and ticks), distance to target, time since entry
- [ ] **UI-06**: **Trade history + equity curve panel**: closed-trades table (with side, entry, exit, gross PnL, fees, MAE, MFE, hold time, exit reason) + running equity curve overlayed with daily/cumulative-DD bars
- [ ] **UI-07**: **Strategy controls + parameter panel**: toggle each registered strategy on/off (writes to `engine_state`), live-edit ORB params (writes to `orb.yaml` via API + hot-reload), button to fire a backtest with current params, optimization results browser with 2-param heatmap viewer
- [ ] **UI-08**: ET clock always visible in the header; connection-status indicator (TV MCP / data feed / WebSocket) prominent with color-coded staleness ("last updated" timer turns yellow > 10s, red > 30s)
- [ ] **UI-09**: Hotkeys: `F` = flatten all (with confirmation), `K` = kill switch (with confirmation), `P` = pause active strategy, `?` = show shortcuts overlay; all hotkeys live in a single registry surfaced in the help overlay

### TradingView MCP Integration (TV)

- [ ] **TV-01**: `TVBridge` supervisor process: spawns `tradingview-mcp-jackson` as a stdio subprocess, maintains a long-lived `ClientSession`, auto-restarts on disconnect, exposes typed Python wrappers over the MCP tool surface
- [ ] **TV-02**: `TVBridge` subscribes to `signals` and `fills` topics on the bus; for each event it draws onto the live TV chart via `draw_shape` (entry arrow, stop line, target line, ORB box at session open)
- [ ] **TV-03**: Overlay registry table tracks every drawing by `(strategy_id, signal_id, shape_id)`; nightly cleanup removes shapes older than configurable retention (default 5 trading days) and enforces a 200-shape cap
- [ ] **TV-04**: `TVReplayDataSource`: starts a TV replay session at a chosen date, steps bars, exposes them through the `DataSource` protocol so the same `Strategy.on_bar()` consumes them and the user can eyeball the strategy on the exact bars the engine sees
- [ ] **TV-05**: REST endpoint `POST /tv/focus {symbol, date}` calls `chart_set_symbol` + `chart_set_timeframe` + `chart_scroll_to_date` so the UI date-picker drives the live TV chart
- [ ] **TV-06**: TV failure is non-blocking for the trading core when TV is not the active data source: MCP errors are logged to the audit log but never propagate up the pipeline; when TV **is** the active `DataSource`, a degradation banner surfaces in the UI and the engine refuses to emit signals until reconnection
- [ ] **TV-07**: UI button "Author TradingView Alert" calls `alert_create` for the active strategy's threshold condition; alert IDs persisted so they can be deleted on strategy toggle-off

## v2 Requirements

Deferred to future release. Acknowledged but not in current roadmap.

### Multi-Strategy / Multi-Symbol

- **V2-MS-01**: Multiple strategies running concurrently with per-strategy capital silos
- **V2-MS-02**: Per-strategy correlation cap to prevent over-concentration
- **V2-MS-03**: Multi-symbol watchlist (NQ, RTY, YM, GC) reusing the same engine

### Advanced Optimization

- **V2-OPT-01**: Optuna / Bayesian (TPE) hyperparameter search
- **V2-OPT-02**: Genetic / DEAP optimization
- **V2-OPT-03**: Monte Carlo trade-shuffle bootstrap bands on equity curve

### Live Execution

- **V2-LIVE-01**: Interactive Brokers `ib_insync` adapter (`Executor` impl) for live ES / MES
- **V2-LIVE-02**: NinjaTrader / Tradovate sim-broker adapter
- **V2-LIVE-03**: Pre-flight live-mode safety review checklist (separate from paper)

### Data Vendor Expansion

- **V2-DATA-01**: `DatabentoDataSource` for real ES front-month + continuous historical
- **V2-DATA-02**: `PolygonFuturesDataSource` for streaming ES quotes
- **V2-DATA-03**: Globex / 23-hour session support (overnight gaps, rollovers handled cleanly)

### Bloomberg-Density UI Polish

- **V2-UI-01**: Command palette (`Ctrl+K` / Bloomberg-style `/` slash commands)
- **V2-UI-02**: Forensic panel — click a trade, see the full audit chain rendered as a timeline
- **V2-UI-03**: Saved-layout system (multiple operator profiles)
- **V2-UI-04**: Replay scrubber synced across all panels
- **V2-UI-05**: Side-by-side backtest diff (compare two BacktestResults)
- **V2-UI-06**: Soft warnings at 80% of daily-DD / max-contracts thresholds (in-UI nudges)

### Strategy Library

- **V2-STR-01**: VWAP mean-reversion reference strategy
- **V2-STR-02**: EMA crossover + trend filter reference strategy
- **V2-STR-03**: Strategy plugin loader so external modules can register without code changes

## Out of Scope

Explicitly excluded. Documented to prevent scope creep and to surface anti-features from research/FEATURES.md.

| Feature | Reason |
|---------|--------|
| Live broker order entry from the UI | Paper-only for v1 (explicit user decision); too much operational/security work for the value at this stage |
| Tick-level fill simulation from 1m bars | Feels precise, is a lie — generates a false sense of fill quality at sub-minute granularity that the data does not actually support |
| Same-bar / current-bar-at-close fills | Pure look-ahead; backtests look great but are unactionable |
| Forward-fill or interpolated OHLC across gaps | Fabricates bars that ORB will trade off; gaps should be visible, not hidden |
| Risk-override / "I know what I'm doing" toggle | Eliminates the reason the risk manager exists |
| Combined "halt and flatten" mega-button | Conflates two very different intents — must be separate controls |
| Auto-restart of trading engine after kill | Kill switch requires human acknowledgement; auto-restart is how prop accounts die |
| Mid-bar `on_tick` strategy hook | Out of scope at 1m resolution; encourages look-ahead and tempts ML/HFT scope creep |
| Genetic / Bayesian optimization in v1 | Need a baseline grid + walk-forward result first; advanced optimizers can overfit faster than they can validate |
| External message broker (Redis / Kafka) | Single-operator localhost; in-process asyncio bus is sufficient |
| Cloud / multi-tenant SaaS deployment | Local-only desktop-web app; bundling for cloud removes the simplicity that makes this fast to iterate on |
| Multi-account / multi-user auth | Single operator; no auth surface; no role system |
| ML / RL strategy types in v1 | Deterministic parameterized strategies first so backtest + optimization plumbing is validated on known-good math |
| Globex / 23-hour session handling | RTH only for v1; overnight gaps + rollovers + low-liquidity zones add complexity without changing the core ORB thesis |
| Mobile responsive UI / light theme | Wrong target — operator wants Bloomberg-density on a desktop monitor |
| Polygon Futures tier as v1 primary | $199/mo premature without proven strategy edge; TV MCP gives free ES data sufficient for paper / research |
| Twelve Data as v1 primary feed for ES | Research verified Twelve Data does not cover CME equity-index futures; demoted to secondary `DataSource` for SPY-proxy and reconciliation |

## Traceability

Populated during roadmap creation. Empty initially.

| Requirement | Phase | Status |
|-------------|-------|--------|
| FND-01 | TBD | Pending |
| FND-02 | TBD | Pending |
| FND-03 | TBD | Pending |
| FND-04 | TBD | Pending |
| FND-05 | TBD | Pending |
| FND-06 | TBD | Pending |
| FND-07 | TBD | Pending |
| FND-08 | TBD | Pending |
| FND-09 | TBD | Pending |
| FND-10 | TBD | Pending |
| MD-01 | TBD | Pending |
| MD-02 | TBD | Pending |
| MD-03 | TBD | Pending |
| MD-04 | TBD | Pending |
| MD-05 | TBD | Pending |
| MD-06 | TBD | Pending |
| MD-07 | TBD | Pending |
| MD-08 | TBD | Pending |
| MD-09 | TBD | Pending |
| MD-10 | TBD | Pending |
| STR-01 | TBD | Pending |
| STR-02 | TBD | Pending |
| STR-03 | TBD | Pending |
| STR-04 | TBD | Pending |
| STR-05 | TBD | Pending |
| STR-06 | TBD | Pending |
| BT-01 | TBD | Pending |
| BT-02 | TBD | Pending |
| BT-03 | TBD | Pending |
| BT-04 | TBD | Pending |
| BT-05 | TBD | Pending |
| BT-06 | TBD | Pending |
| BT-07 | TBD | Pending |
| BT-08 | TBD | Pending |
| BT-09 | TBD | Pending |
| OPT-01 | TBD | Pending |
| OPT-02 | TBD | Pending |
| OPT-03 | TBD | Pending |
| OPT-04 | TBD | Pending |
| OPT-05 | TBD | Pending |
| OPT-06 | TBD | Pending |
| OPT-07 | TBD | Pending |
| OPT-08 | TBD | Pending |
| OPT-09 | TBD | Pending |
| SP-01 | TBD | Pending |
| SP-02 | TBD | Pending |
| SP-03 | TBD | Pending |
| SP-04 | TBD | Pending |
| SP-05 | TBD | Pending |
| SP-06 | TBD | Pending |
| RM-01 | TBD | Pending |
| RM-02 | TBD | Pending |
| RM-03 | TBD | Pending |
| RM-04 | TBD | Pending |
| RM-05 | TBD | Pending |
| RM-06 | TBD | Pending |
| RM-07 | TBD | Pending |
| RM-08 | TBD | Pending |
| UI-01 | TBD | Pending |
| UI-02 | TBD | Pending |
| UI-03 | TBD | Pending |
| UI-04 | TBD | Pending |
| UI-05 | TBD | Pending |
| UI-06 | TBD | Pending |
| UI-07 | TBD | Pending |
| UI-08 | TBD | Pending |
| UI-09 | TBD | Pending |
| TV-01 | TBD | Pending |
| TV-02 | TBD | Pending |
| TV-03 | TBD | Pending |
| TV-04 | TBD | Pending |
| TV-05 | TBD | Pending |
| TV-06 | TBD | Pending |
| TV-07 | TBD | Pending |

**Coverage:**
- v1 requirements: 75 total
- Mapped to phases: 0 (populated by roadmapper)
- Unmapped: 75 ⚠️ (will resolve in ROADMAP.md)

---
*Requirements defined: 2026-05-14*
*Last updated: 2026-05-14 after initial definition*
