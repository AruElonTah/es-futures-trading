# ES Futures Trading System

## What This Is

A modular Python trading system for E-mini S&P 500 (ES) futures focused on intraday (1m–15m) strategies during the cash session, paired with a Bloomberg-Terminal-style web UI for chart visualization, position tracking, P&L analysis, and strategy control. It runs in **paper / backtest-only** mode — no live capital — but is designed cleanly enough that a real broker adapter could be slotted in later.

Built for a single operator who wants to research, backtest, optimize, and observe intraday ES strategies (starting with Opening Range Breakout) inside one local tool that uses the **TradingView Desktop chart (via TradingView MCP) as both the live data source and the visualization surface**. Twelve Data and other vendors remain pluggable behind a `DataSource` abstraction for headless backfills and reconciliation, but TV MCP is the v1 primary feed.

## Core Value

**Trust the numbers.** When the system says a strategy made X dollars in backtest with Y drawdown at Z parameters, that result must be reproducible, leakage-free, and survive walk-forward — because every decision (param tuning, deployment, capital allocation) compounds on top of it.

## Requirements

### Validated

<!-- Shipped and confirmed valuable. -->

(None yet — ship to validate)

### Active

<!-- Current scope. Building toward these. -->

**Market Data Ingestion**
- [ ] Pull ES (continuous front-month) 1m / 5m / 15m bars via TradingView MCP `data_get_ohlcv` (primary v1 feed) — handles both live polling and historical replay-window pulls
- [ ] Provider-agnostic `DataSource` protocol with at least two implementations: `TradingViewDataSource` (primary) and `TwelveDataSource` (secondary / SPY-proxy / reconciliation / headless backfill)
- [ ] Persist bars to DuckDB + Parquet with idempotent upserts keyed on `(symbol, tf, ts_utc)` and gap detection
- [ ] RTH-only session filtering (9:30–16:00 ET, CME equity-index calendar, NOT NYSE) with correct DST handling
- [ ] Daily TradingView ↔ Twelve Data reconciliation pass (when Twelve Data session is provisioned) — flag bars where price differs > 0.05%

**Strategy Engine**
- [ ] Strategy base class with `on_bar(bar) -> Signal | None` event interface
- [ ] Opening Range Breakout (ORB) reference strategy: configurable opening-range minutes, ATR-based stop, R-multiple target
- [ ] Pluggable indicator layer (ATR, VWAP, EMA, ADR) usable by any strategy
- [ ] Signal object carries side, entry, stop, target, size hint, timestamp, and strategy ID

**Backtesting Module**
- [ ] VectorBT-backed engine that consumes bars + strategy + risk config, emits trades and an equity curve
- [ ] Honest fill simulation: next-bar entry, slippage in ticks, commission per contract (round-turn)
- [ ] Standard metrics: total return, Sharpe, Sortino, max drawdown, win rate, expectancy, profit factor
- [ ] Trade ledger persisted to DuckDB with full attribution (signal → fill → exit reason)

**Parameter Optimization**
- [ ] Grid search across declared parameter spaces
- [ ] Walk-forward analysis with configurable IS/OOS window split
- [ ] Optimization runs stored to DuckDB with full parameter set, metrics, and equity curves per fold
- [ ] Heatmap export for any 2-param slice; ranked leaderboard for OOS performance

**Signal Pipeline**
- [ ] In-process pub/sub bus (asyncio) routing `Signal` → risk-checked → paper executor
- [ ] Paper executor that fills against the next live bar or last quote, persists positions / fills
- [ ] Audit log of every signal, decision, and fill (CSV + DuckDB) for forensic replay

**Risk Manager**
- [ ] Prop-firm-style defaults: $50k account, max 2% risk per trade, $2k daily-drawdown circuit breaker
- [ ] ATR-based position sizing (contracts = floor(risk_$ / (stop_ticks × tick_value)))
- [ ] Pre-trade checks: max contracts, daily-loss-hit, per-strategy concurrency cap
- [ ] Post-trade state: realized PnL, open exposure, equity high-water mark

**Web App (Bloomberg-Terminal-style UI)**
- [ ] FastAPI backend with REST + WebSocket endpoints feeding bars, positions, trades, equity, optimization runs
- [ ] React/Next.js frontend, dark dense layout, monospace typography, configurable multi-pane grid
- [ ] Live chart panel: ES candles, ORB box overlay, signal markers, active stop/target lines (TradingView Lightweight Charts)
- [ ] Order blotter panel: open positions with avg price, unrealized P&L, distance to stop
- [ ] Trade history panel: closed trades table + running equity curve + daily/cumulative stats
- [ ] Strategy controls panel: toggle strategy on/off, edit ORB params live, kick off backtests, view optimization heatmaps

**TradingView MCP Integration (primary data source + visualization surface)**
- [ ] Long-lived supervised MCP stdio client (`TVBridge`) that owns the connection, auto-restarts on disconnect, and exposes a typed Python wrapper over the relevant tools
- [ ] `TradingViewDataSource` implementation: live polling via `quote_get` + periodic `data_get_ohlcv` for the active timeframe; historical pulls via `replay_start` / `chart_scroll_to_date` + `data_get_ohlcv`
- [ ] Bidirectional chart sync: when system focuses a date / symbol, push state to TradingView via MCP (`chart_set_symbol`, `chart_set_timeframe`, `chart_scroll_to_date`)
- [ ] Draw ORB range box, entries, stops, and targets onto the live TV chart via `draw_shape` — overlay registry + daily cleanup + 200-shape cap
- [ ] Replay-driven backtests: TV replay session feeds bars through the same `Strategy.on_bar()` path as historical files, so the user can eyeball the strategy on the same data the engine is consuming
- [ ] Create TradingView alerts on active strategy thresholds via `alert_create` as a secondary user-facing signal surface

### Out of Scope

<!-- Explicit boundaries. Includes reasoning to prevent re-adding. -->

- **Live broker execution (IB / Tradovate / NinjaTrader live)** — explicit user decision; paper-only for v1. Re-evaluate after a strategy survives walk-forward and at least 4 weeks of forward paper testing.
- **Multi-asset support (equities, FX, crypto)** — ES-only keeps fill assumptions, session logic, and risk math correct. Adding asset classes inflates scope without serving the core thesis.
- **Tick / sub-minute data and HFT-grade latency** — intraday-only (1m–15m). Microstructure modeling and Databento/Polygon WS streams are unnecessary at this resolution.
- **Multi-account / multi-user** — single operator, single local install. No auth, no roles.
- **Cloud deployment / multi-tenant SaaS** — local-only desktop-web app. Bundling for cloud removes the simplicity that makes this fast to iterate on.
- **ML / RL strategy types in v1** — start with deterministic, parameterized strategies (ORB) so the backtest/optimization plumbing is validated against known-good math first.
- **Globex / 23-hour session handling** — RTH only for v1. Overnight gaps, rollovers, and low-liquidity zones add complexity without changing the core ORB thesis.
- **Genetic / Bayesian optimization** — grid + walk-forward only. Faster optimizers can come once we have a baseline objective worth optimizing harder.

## Context

- **TradingView MCP runtime is already wired** at `C:\Users\Admin\tradingview-mcp-jackson\` with 78 tools (chart control, Pine, replay, drawings, alerts, data extraction). In this project TV MCP plays **three roles**: (1) primary market-data source (live + historical via replay), (2) visualization surface (drawings, alerts), (3) eventual reconciliation peer against external vendors (Twelve Data / Databento) once they're slotted in. The Python core remains the brain — TV is the data hose and the screen, not the decision-maker.
- **Critical research finding (verified 2026-05-14):** Twelve Data does **not** document support for ES futures (only Stocks / Forex / ETFs / Crypto / Commodities / Indices). This is why TradingView MCP is promoted to primary data source for v1. Twelve Data stays in scope as a secondary `DataSource` impl for SPY-proxy backfills, headless CI runs (when TV isn't available), and live cross-vendor reconciliation.
- **Greenfield repo** at `C:\Users\Admin\Desktop\Day Trading` (just `git init`'d). No prior code, no prior planning artifacts.
- **Windows 11 / PowerShell** primary dev environment. Bash available, but tooling and scripts should not assume POSIX.
- **Operator profile**: single user, builds for self, wants Bloomberg-Terminal density (not consumer-friendly bubbles). Comfortable with code-level config, not UI-only tuning.
- **Prop-firm framing** for the risk model implies the eventual goal is funded-trader capital — even though execution stays paper for v1, risk math should mirror Apex / Topstep limits ($50k, ~$2k DD, 1–2 MES contracts).
- **MES vs ES**: math defaults assume MES (Micro E-mini, $5/point, 0.25 tick = $1.25) for prop-firm sizing. Strategy and data layers use ES front-month continuous for analysis; sizing converts to MES contracts at the risk layer.

## Constraints

- **Tech stack — Python 3.11+**: required by VectorBT, FastAPI async features, and modern type hints. Lock minimum version in `pyproject.toml`.
- **Tech stack — VectorBT (free tier acceptable)**: backtest engine. PRO is optional — start free.
- **Tech stack — TradingView MCP as primary data feed**: live polling + replay-driven historical via `data_get_ohlcv`. Requires TradingView Desktop running and the `tradingview-mcp-jackson` server reachable as a stdio subprocess. Twelve Data REST remains as a secondary `DataSource` for headless / CI / reconciliation use.
- **Storage — DuckDB + Parquet local files only**: zero-ops, columnar, fast pandas/VBT integration. No Postgres / Timescale until proven necessary.
- **UI — FastAPI + Next.js (TypeScript) + TradingView Lightweight Charts**: required for true Bloomberg-style density and real-time WebSocket feeds.
- **Session — RTH (9:30–16:00 ET) only**: data ingestion, backtest windows, and execution gating all enforce this. ETH bars discarded at ingest.
- **Platform — Windows / PowerShell** primary, with Bash fallback: setup scripts use cross-platform commands (Python, Node, npm/pnpm). Avoid bash-only shell scripts in onboarding.
- **Compliance — paper only**: no broker API keys, no order-routing surfaces, no fills against live markets. Removes the bulk of operational/security work for v1.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Paper / backtest only for v1 | Validate the research loop and strategy thesis before risking capital or operating a live system | — Pending |
| TradingView MCP as primary data feed (Twelve Data demoted to secondary) | Research surfaced that Twelve Data does not cover ES futures. TV MCP gives real ES data for free, integrates with the chart we already use, and feeds replay-driven backtests against the same bars the user eyeballs. Tradeoff: TV Desktop must be running; headless / CI runs need the secondary Twelve Data (SPY-proxy) path. | — Pending |
| VectorBT as backtest engine | Vectorized speed for grid + walk-forward, native Plotly, good pandas integration | — Pending |
| Opening Range Breakout as seed strategy | Well-documented ES intraday edge, simple to parameterize, ideal smoke test for the full pipeline | — Pending |
| Grid search + walk-forward optimization | Honest baseline; resists overfitting better than naive grid; easy to interpret | — Pending |
| Prop-firm risk profile ($50k / 2%, $2k DD) | Matches Apex / Topstep funded-trader constraints — the path to capital | — Pending |
| DuckDB + Parquet for storage | Zero-ops, columnar, plays well with pandas/VBT, no DBA work | — Pending |
| FastAPI + Next.js + Lightweight Charts UI | Highest ceiling for Bloomberg-style density and WebSocket-driven live updates | — Pending |
| TradingView MCP as first-class peer (not optional) | Chart sync, replay-fed backtests, MCP-driven drawings/alerts — leverage what's already running | — Pending |
| RTH-only sessions for v1 | Avoid overnight gap / rollover complexity; cleaner data; ORB is an RTH pattern anyway | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-05-14 after initialization*
