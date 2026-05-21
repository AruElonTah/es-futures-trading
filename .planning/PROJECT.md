# ES Futures Trading System

## What This Is

A modular Python trading system for E-mini S&P 500 (ES) futures focused on intraday (1m–15m) strategies during the cash session, paired with a Bloomberg-Terminal-style web UI for chart visualization, position tracking, P&L analysis, and strategy control. It runs in **paper / backtest-only** mode — no live capital — but is designed cleanly enough that a real broker adapter could be slotted in later.

Built for a single operator who wants to research, backtest, optimize, and observe intraday ES strategies (starting with Opening Range Breakout) inside one local tool that uses the **TradingView Desktop chart (via TradingView MCP) as both the live data source and the visualization surface**.

**v1.0 shipped 2026-05-21.** 9 phases, 45 plans, 288 commits, ~74k LOC (Python + TypeScript), 7 days.

## Core Value

**Trust the numbers.** When the system says a strategy made X dollars in backtest with Y drawdown at Z parameters, that result must be reproducible, leakage-free, and survive walk-forward — because every decision (param tuning, deployment, capital allocation) compounds on top of it.

**v1.0 validation:** BL-1 lookahead detector CI-green, byte-identical equity-curve reproducibility CI on Windows, ATR leakage-proof integration test, full attribution chain (signal → risk decision → fill) in DuckDB.

## Requirements

### Validated (v1.0)

All 74 v1 requirements shipped and verified. Key highlights:

- ✓ uv workspace monorepo + locked deps (FND-01/02) — v1.0
- ✓ UTC discipline + gitleaks pre-commit (FND-04/05) — v1.0
- ✓ instruments.py single-source-of-truth for all dollar math (FND-06) — v1.0
- ✓ EventBus asyncio pub/sub (FND-07) — v1.0
- ✓ git_sha / data_hash / param_hash reproducibility (FND-08) — v1.0
- ✓ TradingViewDataSource + TwelveDataSource behind DataSource protocol (MD-01/02/03) — v1.0
- ✓ DuckDB + Hive Parquet with RTH CME calendar + rollover-seam detection (MD-04/05/08) — v1.0
- ✓ Look-ahead-safe ATR/VWAP/EMA/ADR indicators (STR-03) — v1.0
- ✓ ORBStrategy config-driven + leakage-proof (STR-04) — v1.0
- ✓ VectorBT safe_from_signals + BL-1 CI gate (BT-01/02/07) — v1.0
- ✓ Honest fill simulation: next-bar, slippage, commissions, MAE/MFE (BT-03/05) — v1.0
- ✓ Grid + walk-forward optimization with ADR gate + true holdout guard (OPT-01..09) — v1.0
- ✓ FullRiskManager: 3 DrawdownModel variants, HWM, kill-9 durability (RM-01..08) — v1.0
- ✓ Audit log surviving kill -9 + byte-identical Replay CI (SP-03/04) — v1.0
- ✓ Kill switch + Flatten as separate hotkeys with separate confirmations (SP-05) — v1.0
- ✓ TVBridge supervised MCP: ORB box + signal overlays, overlay registry (TV-01..07) — v1.0
- ✓ Bloomberg-density 4-pane terminal: drag/resize, WS gap-detect, strategy hot-reload (UI-02/03/06/07) — v1.0

Full details: `.planning/milestones/v1.0-REQUIREMENTS.md`

### Active (v1.1 Candidates)

**Tech Debt (from v1.0 audit):**
- [ ] Wire POST /backtests/run to BacktestEngine — UI Run Backtest button currently a 2s stub
- [ ] Fix ORB box coords in TVBridge — use actual session H/L from StrategyContext, not entry ×1.001
- [ ] Fix silent UTC coercion in Bar storage (CR-04 from Phase 1 audit)
- [ ] Wire strategy hot-reload to live engine — PUT /strategies/params reloads config but running engine never sees it

**Feature Additions:**
- [ ] Live engine with real TOPIC_SIGNALS publisher (paper exec on live TV data feed)
- [ ] Phase 2 retroactive VERIFICATION.md
- [ ] REQUIREMENTS.md checkbox cleanup (all Phase 2–8 checkboxes currently stale)

### Out of Scope

- **Live broker execution** — paper-only for v1. Re-evaluate after 4+ weeks of forward paper testing with validated strategy.
- **Multi-asset support** — ES-only keeps fill assumptions, session logic, and risk math correct.
- **Tick / sub-minute data** — intraday-only (1m–15m). Microstructure modeling is out of scope.
- **Multi-account / multi-user** — single operator, single local install.
- **Cloud deployment** — local-only desktop-web app.
- **ML / RL strategy types** — start with deterministic ORB; validate plumbing before advanced strategies.
- **Globex / 23-hour session** — RTH only; overnight gaps and low-liquidity zones complicate ORB thesis.
- **Genetic / Bayesian optimization** — grid + walk-forward first.

## Context

- **v1.0 shipped** 2026-05-21. All 9 phases complete. 7-day build, 288 commits, ~74k LOC.
- **TradingView MCP runtime wired** at `C:\Users\Admin\tradingview-mcp-jackson\` (78 tools). Primary data source and visualization surface. ES continuous front-month (`CME_MINI:ES1!`) confirmed working.
- **Critical finding (2026-05-14):** Twelve Data does NOT cover ES futures. TV MCP is primary; Twelve Data stays as SPY-proxy secondary for CI/reconciliation.
- **Platform:** Windows 11 / PowerShell primary. GitHub Actions CI running on `windows-latest`.
- **Known limitations at v1.0:** Run Backtest UI button is a stub (CLI works); ORB box on TV chart uses stub coords; strategy hot-reload not propagated to live engine.
- **Prop-firm framing:** Risk model mirrors Apex/Topstep limits ($50k, ~$2k DD, 1–2 MES contracts).

## Constraints

- **Python 3.11+** (3.12 target) — locked by VectorBT + FastAPI async.
- **VectorBT 1.0.0 (OSS)** — backtest engine. PRO not needed for ORB v1.
- **TradingView MCP as primary data feed** — requires TV Desktop running.
- **DuckDB + Parquet local files only** — zero-ops. No Postgres/Timescale.
- **FastAPI + Next.js + Lightweight Charts** — required for Bloomberg-density UI.
- **RTH only (9:30–16:00 ET)** — ETH bars discarded at ingest.
- **Windows / PowerShell primary** — CI runs on windows-latest.
- **Paper only** — no broker API keys, no live order routing.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Paper / backtest only for v1 | Validate research loop before risking capital | ✓ Good — enabled fast iteration without operational overhead |
| TradingView MCP as primary feed | Twelve Data doesn't cover ES futures; TV gives real ES data free | ✓ Good — ES data works; TV Desktop must be running (documented constraint) |
| VectorBT as backtest engine | Vectorized speed for grid + walk-forward, native Plotly | ✓ Good — grid search performant; OSS 1.0.0 stable |
| ORB as seed strategy | Well-documented ES edge, simple to parameterize | ✓ Good — clean smoke test for the full pipeline |
| Grid + walk-forward optimization | Honest baseline, interpretable | ✓ Good — OOS Sharpe + IS/OOS edge ratio are informative |
| Prop-firm risk profile ($50k / 2%, $2k DD) | Matches Apex/Topstep constraints | ✓ Good — risk math correct for funded-trader path |
| DuckDB + Parquet for storage | Zero-ops, columnar, pandas/VBT integration | ✓ Good — no ops overhead; Hive partitioning works well |
| FastAPI + Next.js + Lightweight Charts | Bloomberg density + WebSocket live updates | ✓ Good — WS fan-out + drag-resize panes work well |
| TradingView MCP as first-class peer | Chart sync, replay-fed backtests, MCP drawings | ⚠ Partial — ORB box coords are stubs; hot-reload not wired to live engine |
| RTH-only sessions | Avoid overnight complexity; ORB is RTH pattern | ✓ Good — 390-bar 1m day is clean |
| Defer POST /backtests/run wiring to Phase 8 | Risk of scope expansion mid-Phase 7 | ⚠ Revisit — Phase 8 closed without resolving it; now first-priority v1.1 item |
| `_run_backtest_task` 2s stub | "Phase 8 concern" defer at Phase 7 execution | ⚠ Revisit — left a broken UI feature shipped in v1.0 |

## Evolution

This document evolves at milestone boundaries.

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-05-21 after v1.0 milestone*
