# Roadmap: ES Futures Trading System

**Defined:** 2026-05-14
**Granularity:** standard
**Mode:** Vertical MVP (per-phase)
**Coverage:** 74/74 v1 requirements mapped (REQUIREMENTS.md header says 75, actual REQ-IDs total 74 — flagged below)

## Overview

A 9-phase plan (Phase 0 + Phases 1–8) that builds a single-operator intraday ES futures backtest + paper-trading system around the load-bearing invariant **"trust the numbers"**. Phase 0 is a short validation spike that resolves the data-vendor unknown before any strategy work begins. Phases 1–2 lay the foundation: scaffolding, repo-wide UTC/RTH discipline, the four load-bearing `Protocol` seams (`DataSource`, `Strategy`, `RiskManager`, `Executor`), and the indicator + ORB strategy code. **Phase 3 is the integration gate** — it closes the visible loop (bar → ORB signal → paper fill → chart marker on the Next.js panel) and introduces the BL-1 lookahead-leakage detector and the bitwise-identical equity-curve reproducibility test. Phases 4–8 are incremental depth on top of the proven slice: optimization with walk-forward (gated by ADR), the full risk manager with prop-firm-correct drawdown variants and HWM persistence, the TradingView MCP bridge, the Bloomberg-density UI polish, and operational hardening with the Replay command and a reproducibility CI gate.

## Phases

**Phase Numbering:**
- Integer phases (0, 1, 2, …): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

- [x] **Phase 0: Provider Validation Spike** - Lock the v1 primary data feed via ADR; smoke-test TradingView MCP and Twelve Data coverage before any strategy work begins (completed 2026-05-14)
- [x] **Phase 1: Foundation + Data In** - uv workspace scaffold, repo-wide UTC/RTH discipline, `instruments.py` SoT, `DataSource` protocol with TV-primary + Twelve-Data-secondary implementations, DuckDB+Parquet storage with gap/rollover detection, `seed_bars.py` CLI, reproducibility scaffolding (completed 2026-05-15)
- [x] **Phase 2: Strategy Engine + Indicators** - `Strategy` protocol, `StrategyContext`, look-ahead-safe indicators (ATR Wilder / VWAP / EMA / ADR), `ORBStrategy` reference implementation, YAML strategy registration (completed 2026-05-16)

**Plans:** 2/2 plans complete

Plans:
- [x] 02-01-PLAN.md — Signal + StrategyContext models + look-ahead-safe indicators ATR/VWAP/EMA/ADR (Wave 1)
- [x] 02-02-PLAN.md — ORBStrategy + YAML config + StrategyRegistry + acceptance tests (Wave 2)
- [ ] **Phase 3: Vertical MVP Slice + Backtester** - Integration gate: one day of bars → ORB → paper fill → chart marker; VectorBT `safe_from_signals` wrapper, BL-1 lookahead detector, EOD flatten, reproducibility CI smoke test, FastAPI REST+WS, Lightweight Charts panel
- [ ] **Phase 4: Optimization Grid + Walk-Forward** - Grid expansion, `ProcessPoolExecutor` workers, walk-forward IS/OOS with pre-run ADR gate, true-holdout guard, OOS-ranked leaderboard, 2-param heatmap
- [ ] **Phase 5: Risk Manager + Full Audit + Controls** - ATR-based sizing on `instruments.py`, `DrawdownModel` enum (STATIC / TRAILING_EOD / TRAILING_INTRADAY) tracked side-by-side with HWM persistence, daily-DD circuit breaker, wall-clock EOD flatten, audit log surviving `kill -9`, separate kill switch + flatten hotkeys, blotter panel
- [ ] **Phase 6: TradingView MCP Bridge** - `TVBridge` supervisor + stdio MCP client, auto-draw ORB box + signal arrows + stop/target lines, overlay registry with 200-shape cap, `TVReplayDataSource`, `POST /tv/focus`, daily TV↔Twelve-Data reconciliation, alert authoring
- [ ] **Phase 7: Bloomberg-Density UI Polish** - Multi-pane Next.js dark/dense layout, WebSocket reconnect with sequence numbers and snapshot resync, trade history + equity curve panel, strategy controls with hot-reload, full hotkey registry
- [ ] **Phase 8: Operational Hardening + Reproducibility CI** - `Replay` command with byte-identical audit-log assertion, expanded reproducibility CI on Windows, cross-platform path/encoding tests, backup/retention policy

## Phase Details

### Phase 0: Provider Validation Spike
**Goal:** Resolve the data-vendor unknown so Phase 1 can commit a `DataSource` implementation without rework.
**Mode:** mvp
**Depends on:** Nothing (first phase)
**Success Criteria**:
1. `.planning/decisions/0001-data-provider.md` ADR is committed and documents: (a) verified Twelve Data ES coverage as of the ADR date (negative result expected), (b) TradingView MCP confirmed as the v1 primary feed with rationale, (c) the eventual futures-aware swap candidate (Databento / Polygon Futures / IB historical) named with cost/coverage notes.
2. A PowerShell smoke-test script spawns the `tradingview-mcp-jackson` server, completes `chart_set_symbol`, pulls `data_get_ohlcv` for ES 1m for the previous RTH session, and recovers cleanly after a deliberate TV restart — full transcript stored under `.planning/research/spike-0/`.
3. A Twelve Data smoke call against `/stocks?symbol=ES`, `/commodities?symbol=ES`, and `/etf?symbol=SPY` documents response shapes, rate-limit headers, and the per-day-budget estimate for a 2-year SPY 1m backfill (~196k bars).

**Requirements**:
- FND-10

**Notes**:
- This is a research / decision phase, not implementation. Deliverable is an ADR + smoke artifacts, no production code.
- Output unblocks Phase 1's `DataSource` choice and the v1 working symbol.
- All Phase 4+ optimization runs reference this ADR by hash via `runs.adr_hash`.

**Plans:** 3/3 plans complete

Plans:
- [x] 00-01-PLAN.md — Twelve Data probe + SPY 1m backfill rate-limit budget (parallel with Plan 2)
- [x] 00-02-PLAN.md — TradingView MCP happy-path smoke + restart-cycle resilience test (parallel with Plan 1)
- [x] 00-03-PLAN.md — Vendor comparison + MADR ADR authoring (closes Phase 0; depends on Plans 1 and 2)

---

### Phase 1: Foundation + Data In
**Goal:** A scaffolded monorepo with repo-wide UTC/RTH discipline can backfill RTH-only ES/SPY bars from the configured `DataSource` into DuckDB + Parquet with idempotent upserts, gap detection, and rollover-seam flags.
**Mode:** mvp
**Depends on:** Phase 0
**Success Criteria**:
1. `uv sync` from a clean clone produces a working `.venv` with `vectorbt==1.0.0`, `pandas>=2.2,<3.0`, FastAPI, Pydantic v2, DuckDB, structlog, httpx, pytest, hypothesis, respx, freezegun pinned in `uv.lock`; `packages/{trading-core,api,tv-bridge}` and `apps/web/` are importable workspace members.
2. Running `python scripts/seed_bars.py --symbol SPY --tf 1m --from 2024-01-01 --to 2024-02-01` (or `--symbol ES --tf 1m` against the TV `DataSource`) produces a DuckDB `bars` table where: every row is tz-aware UTC, no ETH bars are present, the CME equity-index calendar's half-days are honored, idempotent re-run of the same command produces zero new rows, the `bar_gaps` table is populated for any missing intra-RTH bars, and the `rollover_seam` boolean column is `True` on the 3rd-Friday-of-Mar/Jun/Sep/Dec boundary bars.
3. `pytest` runs cleanly on the DST-transition test cases `2026-03-08` and `2026-11-01`, and the pre-commit hook rejects a deliberate `datetime.now()` (no tz) and a deliberate fake API key with `gitleaks`.
4. Every CLI / engine run inserts a row into the `runs` table containing `git_sha`, `data_hash`, `param_hash`, `seed`, and the ADR hash from Phase 0; `instruments.py` is the only file with hardcoded tick_value / point_value / session times and is consumed by all dollar-denominated calcs.

**Requirements**:
- FND-01, FND-02, FND-03, FND-04, FND-05, FND-06, FND-07, FND-08, FND-09
- MD-01, MD-02, MD-03, MD-04, MD-05, MD-06, MD-07, MD-08, MD-09

**Notes**:
- The four `Protocol` seams (`DataSource`, `Strategy`, `RiskManager`, `Executor`) are *defined* here even if only `DataSource` has live implementations. No "backtest-specific shortcut" may bypass them in later phases.
- `EventBus` (asyncio in-process) is delivered here so Phase 3 can wire bars → strategy → risk → executor without re-plumbing.
- FND-08's CI reproducibility test is *introduced* in Phase 3 (it needs an equity curve to compare); the `runs` table infrastructure ships here.
- MD-10 (TV↔Twelve-Data daily reconciliation) requires the TV bridge and lives in Phase 6, not here.
- When TV is the active `DataSource` and MCP is disconnected, the data layer surfaces the degraded state via the bus; the actual UI banner ships in Phase 3 (UI-08).

**Plans:** 6/6 plans complete

Plans:
- [x] 01-01-PLAN.md — Workspace scaffold + uv/pnpm install + Next.js stub (Wave 1)
- [x] 01-02-PLAN.md — Domain models + 4 Protocols + Settings + structlog (Wave 2)
- [x] 01-03-PLAN.md — Calendars (RTH/rollover/gap) + EventBus + DST fixtures (Wave 2)
- [x] 01-04-PLAN.md — Storage (DuckDB + Parquet + runs) + Twelve Data + TradingView adapters (Wave 2)
- [x] 01-05-PLAN.md — seed_bars.py CLI + pre-commit hooks (no-naive-tz + gitleaks) (Wave 3)
- [x] 01-06-PLAN.md — FastAPI shell + apps/web finalize + Phase 1 acceptance smoke (Wave 4)

---

### Phase 2: Strategy Engine + Indicators
**Goal:** A `Strategy` running through the protocol API can compute look-ahead-safe indicators, observe the current bar's `StrategyContext` (including the rollover-seam flag), and emit fully-stamped `Signal` objects — with the reference ORB strategy completely config-driven.
**Mode:** mvp
**Depends on:** Phase 1
**Success Criteria**:
1. A unit test loads a known SPY 1m fixture for a single RTH day, instantiates `ORBStrategy` from `config/strategies/orb.yaml` (with `opening_range_minutes=15, atr_stop_mult=1.5, r_target=2.0`), drives `on_bar` over the day's bars, and produces zero signals during the opening range, at most one breakout signal afterward, and the signal carries strategy ID + version + bar timestamp + side + entry + stop + target + size hint.
2. An indicator-leakage assertion test computes `ATR_14.snapshot_at(t)` and verifies it equals `ATR_14` recomputed from bars `[0..t-1]` only; the same test passes for VWAP, EMA, and ADR — any `.shift(1)` regression fails the test.
3. `ORBStrategy.on_bar` returns `None` on bars where `ctx.rollover_seam=True`, verified by feeding a fixture that contains a 3rd-Friday-of-Mar boundary into the strategy.
4. The UI's strategy registry (read in Phase 7 from `config/strategies/`) sees the ORB strategy and reads its param defaults purely from the YAML — no Python-side hardcoded fallback.

**Requirements**:
- STR-01, STR-02, STR-03, STR-04, STR-05, STR-06

**Notes**:
- This phase is pure compute — no bus, no fills, no UI integration yet. That happens in Phase 3.
- HTF features (any feature derived from a higher timeframe) must `.shift(1)` after resample (BL-3 prevention).
- `Strategy.on_bar` here is the same code path the backtester drives in Phase 3 and the live engine drives later — this is the load-bearing invariant from Critical Finding #3.

---

### Phase 3: Vertical MVP Slice + Backtester
**Goal:** The user can run a one-command CLI backtest **and** load a Next.js page that shows ES/SPY candles with the ORB box overlay, the entry/stop/target markers for the day's signals, and the equity curve from the backtest — proving the architecture closes end-to-end.
**Mode:** mvp
**Depends on:** Phase 2
**Success Criteria**:
1. `python scripts/run_backtest.py --strategy orb --symbol SPY --tf 1m --from 2024-01-01 --to 2024-03-31 --config config/strategies/orb.yaml` produces a `BacktestResult` row in DuckDB containing trades, an equity-curve Parquet path, and standard metrics (total return, CAGR, Sharpe, Sortino, Calmar, max DD, max DD duration, win rate, expectancy, profit factor, trade count, average hold time) plus per-trade MAE/MFE.
2. **BL-1 lookahead-detector CI gate**: the test `tests/integration/test_lookahead.py` constructs a deliberately-leaking ORB variant (`close.shift(-1)`-based entry), routes it through `safe_from_signals()`, asserts the resulting Sharpe is finite (not infinite) and the win rate sits in the 40–60% band; the test runs in the PR CI workflow and is required to pass for merge.
3. **Reproducibility CI smoke test**: running the same `run_backtest.py` invocation twice with the same `git_sha + data_hash + param_hash + seed` produces a bitwise-identical equity-curve Parquet (byte-compare passes), and the test runs in CI.
4. **EOD-flat assertion**: at the last RTH bar of any backtest day, `sum(positions) == 0` after the EOD flatten step; intrabar stop-and-target-both-hit resolves worst-case (stop first); attribution chain (`fill_id → signal_id → risk_decision_id`) is unbroken in the DuckDB trade ledger.
5. With `uvicorn` running, the Next.js dev server at `localhost:3000` loads `/dashboard`, calls `GET /bars` for SPY 1m for the backtest window, renders Lightweight Charts with the `America/New_York` `timeFormatter` + `tickMarkFormatter`, overlays the ORB box for one trading day, drops the entry arrow + stop line + target line for at least one ORB signal, and shows the ET clock + connection-status indicator in the header (yellow if last bar > 10s, red > 30s); when TV is the active `DataSource` and MCP disconnects, a degradation banner appears and the engine stops emitting signals until reconnect.

**Requirements**:
- BT-01, BT-02, BT-03, BT-04, BT-05, BT-06, BT-07, BT-08, BT-09
- SP-01
- UI-01, UI-04, UI-08

**Notes**:
- **This phase is the integration gate.** It must not exit until criteria 2 (BL-1) and criteria 3 (reproducibility) are green in CI.
- `safe_from_signals()` mandates `entries.shift(1)` and `price='nextbar'`; direct `vbt.Portfolio.from_signals` calls are blocked by a `noqa`-style lint.
- Session-phase-aware slippage: ≥1.5 ticks adverse during the 9:30–9:45 ET window (FR-1 pitfall).
- This phase delivers the minimum `RiskManager` (pass-through, fixed 1 MES) and the minimum `PaperExecutor` (next-bar fill, slippage, EOD flat). The full Risk Manager ships in Phase 5; the `Protocol` seam is honored here so Phase 5 is a drop-in swap.
- UI-01 here is the **minimal surface**: `/bars`, `/backtests`, `WS /stream`. The full endpoint set (`/positions`, `/trades`, `/equity`, `/optimizations`, `/kill`, `/flatten`) is completed in later phases when their respective subsystems land.

**Plans:** 5 plans

Plans:
- [x] 03-01-PLAN.md — D-10 minimal model fields + DuckDB backtests/trades tables + no-direct-vbt pre-commit hook + Wave 0 test stubs (Wave 1)
- [x] 03-02-PLAN.md — safe_from_signals wrapper + PassThroughRiskManager + PaperExecutor (slippage, intrabar stop-first, EOD flatten) (Wave 2)
- [ ] 03-03-PLAN.md — BacktestEngine (driver loop + VBT metrics + MAE/MFE) + run_backtest.py CLI + BL-1 lookahead + reproducibility integration tests (Wave 3)
- [ ] 03-04-PLAN.md — FastAPI GET /bars + GET /backtests + WS /stream (7-topic asyncio.Queue fan-out) + CORS regression update (Wave 4)
- [ ] 03-05-PLAN.md — Next.js /dashboard (two-pane chart + equity, ORB overlay, ET clock, connection-status, degradation banner) + GET /backtests/{run_id}/equity (Wave 5, includes human-verify checkpoint)

---

### Phase 4: Optimization Grid + Walk-Forward
**Goal:** A user can launch a grid + walk-forward optimization run from a committed ADR, watch progress live, and inspect an OOS-ranked leaderboard plus 2-param heatmaps — with the most-recent 6 months of bars guarded against accidental burn.
**Mode:** mvp
**Depends on:** Phase 3
**Success Criteria**:
1. **Pre-run ADR gate**: `python scripts/run_opt.py --space config/strategies/orb.optspace.yaml` refuses to start unless an ADR file matching `.planning/decisions/opt-*.md` exists declaring IS/OOS split, parameter grid, objective function, and seed; the ADR's content hash is written to every `opt_runs` row and is recoverable forensically.
2. A coarse grid (3 axes, 5 points each = 125 configs) runs in a `ProcessPoolExecutor`, workers open DuckDB read-only and write per-worker Parquet shards, the orchestrator aggregates into `opt_runs` + `opt_results` in a single-process pass, and every fold persists its equity curve, metrics, and selected best-IS params with full hashes (`git_sha / data_hash / param_grid_hash / seed`).
3. **True-holdout guard**: an attempt to query bars from the most-recent 6 months without the `--burn-holdout` flag is refused; `--burn-holdout` increments a `holdout_burns` table row; a 4th burn within a quarter is refused with a quota error.
4. The UI's optimization browser ranks results by **OOS Sharpe** (never IS), shows an IS/OOS edge-ratio column with red flag for ratio > 2, and lets the user pick any 2 grid axes and render a heatmap of OOS Sharpe across them.
5. Ranges narrower than 5 points per axis emit an audit-log warning and require a documented coarser run to have been completed first (recorded as a precondition row in `opt_runs`).

**Requirements**:
- OPT-01, OPT-02, OPT-03, OPT-04, OPT-05, OPT-06, OPT-07, OPT-08, OPT-09

**Notes**:
- The pre-run ADR gate (OPT-04 / BL-4) is the single most important Phase 4 invariant. Without it, every optimization is meta-overfitting waiting to happen.
- Workers must only import `trading-core` (not `api` or `tv-bridge`) — Anti-Pattern 5 from ARCHITECTURE.md.
- Walk-forward warmup uses bars from *before* the IS window — never spans into OOS (BL-4).

---

### Phase 5: Risk Manager + Full Audit + Controls
**Goal:** Every signal flows through a single risk gate that sizes correctly on `instruments.py`, tracks all three drawdown models side-by-side with HWM persisted across restarts, honors the daily-DD circuit breaker, flattens at the wall-clock EOD, and is observable through the live blotter with separate kill-switch and flatten controls.
**Mode:** mvp
**Depends on:** Phase 3 (uses the pipeline from there; develops in parallel with Phase 4)
**Success Criteria**:
1. **Sizing unit tests pass**: `size(risk_$=1000, stop_ticks=5, instrument=MES) == 40` and `size(risk_$=1000, stop_ticks=5, instrument=ES) == 4`, both reading tick_value from `instruments.py` (no magic numbers); the max-contracts cap (default 2 MES) clamps the result regardless of the math.
2. **`DrawdownModel` enum gate**: per-variant unit tests pass for `STATIC`, `TRAILING_EOD`, and `TRAILING_INTRADAY`; the risk manager writes all three values to the `risk_state` table on every update; the engine **refuses to start** without today's HWM row computed from yesterday's close + any pre-market equity delta; killing the process with `kill -9` mid-session and restarting preserves HWM correctly (verified by integration test).
3. A signal whose `worst_case_loss = stop_ticks × tick_value × proposed_size` would push the chosen DD model past its floor is rejected with `reason='dd_floor_violation'` and logged to the audit log; the daily-DD circuit breaker (default $2000) halts new entries when realized+unrealized PnL trips it while keeping existing positions open.
4. **EOD wall-clock flatten** fires at `session_close - 60s` driven by an asyncio scheduler (not a bar event); the same logic is replayed in backtests via the `SyntheticClock`; the integration test `kill -9` 90s before close, restart, observe flatten still fires on time, and the assertion `sum(positions) == 0` holds after `session_close + 5s`.
5. The UI blotter at `/dashboard/blotter` shows every open position with avg fill, current price, unrealized P&L, distance-to-stop in $ and ticks, distance-to-target, and time-since-entry; `F` (flatten all) and `K` (kill switch) are different keys with different confirmation dialogs and different audit-log reason codes; the audit log survives `kill -9` (verified by killing the process during a fill and confirming the fill row exists in DuckDB after restart).

**Requirements**:
- RM-01, RM-02, RM-03, RM-04, RM-05, RM-06, RM-07, RM-08
- SP-02, SP-03, SP-05
- UI-05, UI-09

**Notes**:
- **Phase 5 must not exit without the per-variant `DrawdownModel` tests green and the HWM-survives-restart integration test green.** This is non-negotiable per the cross-phase guardrails.
- `RiskManager.check(signal, state)` is the **only** path from signal to fill; lint blocks backdoors (SP-02).
- Per-strategy concurrency cap = 1 active position per strategy ID in v1 (RM-08); multi-strategy is v2.
- Audit-log writes are synchronous to DuckDB and mirrored to daily CSV — no buffered writes — so they survive `kill -9` (SP-03).

---

### Phase 6: TradingView MCP Bridge
**Goal:** Every signal and fill auto-renders on the user's live TradingView Desktop chart, the chart can be driven from the Next.js date-picker, TV replay sessions can feed the backtester through the same `DataSource` protocol, and a daily TV↔Twelve-Data reconciliation surfaces any > 0.05% divergence.
**Mode:** mvp
**Depends on:** Phase 5
**Success Criteria**:
1. `TVBridge` spawns the `tradingview-mcp-jackson` stdio subprocess, maintains a long-lived `ClientSession`, auto-restarts on disconnect, and exposes typed Python wrappers; killing TV Desktop while the engine is running causes the bridge to log the failure but the strategy/risk/executor pipeline continues running (the audit log shows no skipped signals).
2. When an ORB signal fires and is filled paper-side, the TV chart shows (within < 2s) an entry arrow at the fill bar, a horizontal stop line, a horizontal target line, and an ORB rectangle for the day's opening range; each drawing is registered in the `tv_overlays` table by `(strategy_id, signal_id, shape_id)`; a nightly cleanup removes shapes older than 5 trading days; a 201st shape on a single chart is refused with a clear error.
3. `POST /tv/focus {symbol: "ES", date: "2024-06-12"}` calls `chart_set_symbol` + `chart_set_timeframe` + `chart_scroll_to_date` and the TV Desktop chart visibly jumps to that date within 3s.
4. `TVReplayDataSource` satisfies the `DataSource` protocol; running `run_backtest.py --data-source tv-replay --start 2024-06-12` drives the same `Strategy.on_bar` path the historical-Parquet `DataSource` drives, and the resulting trade list cross-validates against the same-window run from `TwelveDataSource` / `TradingViewDataSource(historical)` within the documented divergence tolerance.
5. The daily reconciliation job compares TV `data_get_ohlcv` for ES vs Twelve Data SPY-proxy for the same RTH window; any bar with > 0.05% price divergence or > 5% volume divergence raises a row in `audit_log` with `topic='reconciliation_alert'` and surfaces in the UI; the "Author TradingView Alert" button calls `alert_create` for the active strategy's threshold and persists the alert ID so toggle-off deletes it.

**Requirements**:
- TV-01, TV-02, TV-03, TV-04, TV-05, TV-06, TV-07
- MD-10

**Notes**:
- TV is a **subscriber on the bus**, never a pipeline step — Anti-Pattern 4. The trading engine must not block on `await tv.draw_shape(...)`.
- TV failure mode: when TV is the active `DataSource` (set in Phase 1), the engine refuses to emit signals while MCP is disconnected and the UI shows the degradation banner; when TV is only the **output surface** (e.g. running on `TwelveDataSource`), MCP errors are logged but never propagated.

---

### Phase 7: Bloomberg-Density UI Polish
**Goal:** The Next.js dashboard is a usable dense multi-pane terminal: drag/resize panes, dark monospace theme, trade history + equity curve panel, strategy controls with hot-reload, full hotkey registry, and a WebSocket client that gap-detects and snapshot-resyncs after disconnects.
**Mode:** mvp
**Depends on:** Phase 6
**Success Criteria**:
1. The dashboard loads at desktop widths only (no mobile), uses a dark monospace theme, lets the user drag and resize the chart / blotter / history / controls panes, and saves the layout to local storage so it persists across reloads.
2. Pulling the network cable on the dev box for 30 seconds and reconnecting: the WS client backs off with jitter, reconnects, detects the `state_version` / sequence-number gap, calls the REST snapshot endpoints, and the dashboard shows no permanent stale data — verified by a Playwright integration test.
3. The Trade History + Equity Curve panel renders closed-trade rows with side, entry, exit, gross P&L, fees, MAE, MFE, hold time, and exit reason; below it an equity-curve line overlayed with a daily/cumulative-DD bar chart; clicking a trade row scrolls the chart panel to the entry bar.
4. The Strategy Controls panel lists every registered strategy (read from `config/strategies/*.yaml`), exposes a toggle on/off (writes `engine_state` via API), live-edits ORB params (writes the YAML through the API and the engine hot-reloads without restart), and a "Run Backtest with current params" button kicks off a backtest and shows the result in the optimization-results browser; the 2-param heatmap from Phase 4 is browsable here.
5. The hotkey help overlay (`?`) lists every shortcut from a single registry (`F` flatten, `K` kill, `P` pause, `?` help — plus any added in Phase 5); a hotkey collision throws at startup, not at runtime.

**Requirements**:
- UI-02, UI-03, UI-06, UI-07
- SP-06

**Notes**:
- Lightweight Charts must be mounted inside React `useEffect` directly (vanilla, no wrapper) — already established in Phase 3; this phase scales the chart pane out into the full layout.
- Strategy hot-reload (UI-07) writes to YAML via the API with Pydantic validation on the way in; invalid params return a 422 with the validator message, not a silent fail.
- Command palette (`Ctrl+K`) is **deferred to v2** per cross-phase context — do not implement here.

---

### Phase 8: Operational Hardening + Reproducibility CI
**Goal:** The system is reproducible across machines and time: a `Replay` command re-feeds historical bars through the full pipeline and byte-matches the original audit log; the reproducibility CI runs on Windows; backup and audit-log retention are documented.
**Mode:** mvp
**Depends on:** Phase 7
**Success Criteria**:
1. `python scripts/replay.py --from 2024-06-12 --to 2024-06-12` re-feeds bars from DuckDB through `DataSource → Strategy → RiskManager → Executor → audit_log` and asserts the replayed audit-log CSV is byte-identical to the original day's CSV; a test makes this an automated CI assertion against a checked-in golden audit log.
2. The Phase-3 reproducibility CI is expanded: it runs on **Windows** (matching the operator's dev environment, OP-4), exercises paths with spaces (the repo path contains a space), and asserts UTF-8 encoding throughout; the CI matrix passes for both a clean `uv sync` and a cached one.
3. A documented backup policy lives in the repo (e.g., `docs/operations/backup.md`) covering DuckDB snapshot cadence, Parquet partition retention, audit-log retention, and an encrypted-at-rest option; a `scripts/backup.ps1` script performs the snapshot and is runnable from PowerShell.

**Requirements**:
- SP-04

**Notes**:
- The single REQ-ID owned by this phase is SP-04 (Replay), but the phase delivers the **operational closure** the project needs to be trusted: cross-platform CI, the Windows path-with-space edge case, the encoding rule, and the explicit backup/retention policy.
- This phase is the right home for any OP-* pitfall fixes that emerged during phases 1–7 and need a dedicated landing place.
- After Phase 8, the v1 milestone is shippable: validated, reproducible, leakage-free, and survivable across walk-forward — i.e., the Core Value from PROJECT.md is achievable.

---

## Cross-Phase Guardrails

These are non-negotiable invariants that span phase boundaries. A phase that violates one cannot be marked complete.

- **BL-1 lookahead-leakage detector gate** — Phase 3 must not exit until the `tests/integration/test_lookahead.py` CI test is green: a deliberately-leaking ORB variant routed through `safe_from_signals()` must produce a finite Sharpe and a 40–60% win rate. This is the integration test that proves the backtester is honest.
- **`DrawdownModel` + HWM persistence gate** — Phase 5 must not exit until per-variant unit tests pass for all three `DrawdownModel` enum values **and** the HWM-survives-`kill -9` integration test passes. Trailing drawdown is the single biggest prop-firm correctness lever; tracking only one variant silently corrupts the risk model.
- **Walk-forward ADR-before-first-run gate** — Phase 4 must not allow any `run_opt.py` invocation without a committed ADR file in `.planning/decisions/` declaring IS/OOS split, parameter grid, objective function, and seed. The ADR hash is logged on every `opt_runs` row. This is what makes the OOS metric trustworthy.
- **Reproducibility CI** — A bitwise-identical equity-curve test is **introduced** in Phase 3 (same `git_sha + data_hash + param_hash + seed` → identical Parquet) and **expanded** in Phase 8 (cross-platform Windows CI, path-with-space, UTF-8). Every phase from 3 onward must keep this test green.
- **EOD wall-clock flatten** — Phase 5 owns the wall-clock scheduler (asyncio task at `session_close - 60s`), and Phase 3 owns the backtest equivalent (last RTH bar). Both must enforce `sum(positions) == 0` after EOD. No phase may introduce a path that bypasses this.
- **TV MCP failure mode** — When `TradingViewDataSource` is the active `DataSource` (configurable from Phase 1 onward), the engine **refuses to emit signals** while MCP is disconnected and the UI shows a degradation banner (introduced in Phase 3 UI-08, wired to the real TV bridge in Phase 6). When TV is only an output surface (not the data source), MCP errors are logged but never propagated up the pipeline.
- **The four `Protocol` seams** — `DataSource`, `Strategy`, `RiskManager`, `Executor` are defined in Phases 1–2 and may not be bypassed in any later phase. Any "backtest-specific shortcut" or "live-specific hack" that sidesteps one of them is technical debt that breaks the load-bearing "same code in backtest and live" invariant.

## Progress

**Execution Order:**
Phases execute in numeric order: 0 → 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8.

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 0. Provider Validation Spike | 3/3 | Complete   | 2026-05-14 |
| 1. Foundation + Data In | 6/6 | Complete   | 2026-05-15 |
| 2. Strategy Engine + Indicators | 2/2 | Complete   | 2026-05-16 |
| 3. Vertical MVP Slice + Backtester | 0/5 | Planned    | - |
| 4. Optimization Grid + Walk-Forward | 0/TBD | Not started | - |
| 5. Risk Manager + Full Audit + Controls | 0/TBD | Not started | - |
| 6. TradingView MCP Bridge | 0/TBD | Not started | - |
| 7. Bloomberg-Density UI Polish | 0/TBD | Not started | - |
| 8. Operational Hardening + Reproducibility CI | 0/TBD | Not started | - |

---

## Coverage Notes

- **74 of 74 REQ-IDs mapped** to exactly one phase. No orphans, no duplicates.
- **REQUIREMENTS.md header inconsistency:** the document states "v1 requirements: 75 total" but the actual REQ-ID enumeration yields 74 (FND-10 + MD-10 + STR-6 + BT-9 + OPT-9 + SP-6 + RM-8 + UI-9 + TV-7 = 74). Flagging here for fix in the requirements document; coverage is otherwise complete.
- FND-08 has cross-phase aspects: the `runs` table and hash logging infrastructure is owned by Phase 1 (primary phase); the CI assertion test is introduced in Phase 3 and expanded in Phase 8 — captured in Cross-Phase Guardrails above.
- MD-10 is owned by Phase 6 (not Phase 1) because daily TV↔Twelve-Data reconciliation requires the TV bridge to exist.

*Last updated: 2026-05-16 — Phase 3 planned (5 plans across 5 waves; backtester + FastAPI surface + Next.js dashboard).*
