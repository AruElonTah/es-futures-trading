# ES Futures Trading System

## What This Is

A modular Python trading system for E-mini S&P 500 (ES) futures focused on intraday (1m–15m) strategies during the cash session, paired with a Bloomberg-Terminal-style web UI for chart visualization, position tracking, P&L analysis, and strategy control. It runs in **paper / backtest-only** mode — no live capital — but is designed cleanly enough that a real broker adapter could be slotted in later.

Built for a single operator who wants to research, backtest, optimize, and observe intraday ES strategies (starting with Opening Range Breakout) inside one local tool that integrates first-class with their existing TradingView Desktop chart via the TradingView MCP.

## Core Value

**Trust the numbers.** When the system says a strategy made X dollars in backtest with Y drawdown at Z parameters, that result must be reproducible, leakage-free, and survive walk-forward — because every decision (param tuning, deployment, capital allocation) compounds on top of it.

## Requirements

### Validated

<!-- Shipped and confirmed valuable. -->

(None yet — ship to validate)

### Active

<!-- Current scope. Building toward these. -->

**Market Data Ingestion**
- [ ] Pull historical ES (continuous front-month) 1m / 5m / 15m bars from Twelve Data REST API into local storage
- [ ] Provider-agnostic `DataSource` interface so Polygon / IB / TradingView (via MCP) can be swapped in later without touching strategy code
- [ ] Persist bars to DuckDB + Parquet with idempotent upserts and gap detection
- [ ] RTH-only session filtering (9:30–16:00 ET) with correct DST handling

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

**TradingView MCP Integration (first-class)**
- [ ] Bidirectional chart sync: when system focuses a date / symbol, push state to TradingView via MCP
- [ ] Draw ORB range box, entries, stops, and targets onto the live TV chart via `draw_shape`
- [ ] Optionally seed backtests from TV replay sessions (`replay_start`, `data_get_ohlcv`) to validate against the same data the user is eyeballing
- [ ] Create TradingView alerts on active strategy thresholds via `alert_create` as a secondary signal source

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

- **TradingView MCP runtime is already wired** at `C:\Users\Admin\tradingview-mcp-jackson\` with 78 tools (chart control, Pine, replay, drawings, alerts, data extraction). This is the chart and validation surface — Python is the brain.
- **Greenfield repo** at `C:\Users\Admin\Desktop\Day Trading` (just `git init`'d). No prior code, no prior planning artifacts.
- **Windows 11 / PowerShell** primary dev environment. Bash available, but tooling and scripts should not assume POSIX.
- **Operator profile**: single user, builds for self, wants Bloomberg-Terminal density (not consumer-friendly bubbles). Comfortable with code-level config, not UI-only tuning.
- **Prop-firm framing** for the risk model implies the eventual goal is funded-trader capital — even though execution stays paper for v1, risk math should mirror Apex / Topstep limits ($50k, ~$2k DD, 1–2 MES contracts).
- **MES vs ES**: math defaults assume MES (Micro E-mini, $5/point, 0.25 tick = $1.25) for prop-firm sizing. Strategy and data layers use ES front-month continuous for analysis; sizing converts to MES contracts at the risk layer.

## Constraints

- **Tech stack — Python 3.11+**: required by VectorBT, FastAPI async features, and modern type hints. Lock minimum version in `pyproject.toml`.
- **Tech stack — VectorBT (free tier acceptable)**: backtest engine. PRO is optional — start free.
- **Tech stack — Twelve Data primary feed**: REST only, no streaming required at 1m–15m resolution. API key + free/Starter tier sufficient for ES continuous.
- **Storage — DuckDB + Parquet local files only**: zero-ops, columnar, fast pandas/VBT integration. No Postgres / Timescale until proven necessary.
- **UI — FastAPI + Next.js (TypeScript) + TradingView Lightweight Charts**: required for true Bloomberg-style density and real-time WebSocket feeds.
- **Session — RTH (9:30–16:00 ET) only**: data ingestion, backtest windows, and execution gating all enforce this. ETH bars discarded at ingest.
- **Platform — Windows / PowerShell** primary, with Bash fallback: setup scripts use cross-platform commands (Python, Node, npm/pnpm). Avoid bash-only shell scripts in onboarding.
- **Compliance — paper only**: no broker API keys, no order-routing surfaces, no fills against live markets. Removes the bulk of operational/security work for v1.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Paper / backtest only for v1 | Validate the research loop and strategy thesis before risking capital or operating a live system | — Pending |
| Twelve Data as primary feed | Cheaper than Polygon for futures access, abstract behind `DataSource` so we can swap later | — Pending |
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
