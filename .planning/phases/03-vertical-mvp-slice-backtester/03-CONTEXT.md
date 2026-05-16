# Phase 3: Vertical MVP Slice + Backtester - Context

**Gathered:** 2026-05-16
**Status:** Ready for planning

<domain>
## Phase Boundary

The user can run a one-command CLI backtest and load a Next.js `/dashboard` page that shows ES/SPY candles with the ORB box overlay, entry/stop/target markers, and the equity curve from the backtest — proving the architecture closes end-to-end for the first time.

**In scope:** `run_backtest.py` CLI; VectorBT `safe_from_signals` wrapper; BL-1 lookahead-detector CI gate; reproducibility CI smoke test (bitwise-identical equity-curve Parquet on same `git_sha + data_hash + param_hash + seed`); `BacktestResult` in DuckDB (`backtests` + `trades` tables); equity-curve Parquet files; minimal `RiskManager` (pass-through, fixed 1 MES) with minimal fields filled in; minimal `PaperExecutor` (next-bar fill, session-phase slippage, EOD flatten); FastAPI `GET /bars`, `GET /backtests`, `WS /stream`; Next.js `/dashboard` two-pane (chart + equity curve), ORB overlays, ET clock, connection-status indicator, degraded-state banner.

**Out of scope:** full risk manager with DrawdownModel variants (Phase 5); TVBridge / auto-draw on TV Desktop (Phase 6); drag/resize multi-pane layout (Phase 7); blotter panel (Phase 5); optimization grid (Phase 4); Phase 5 kill-switch / flatten controls.

</domain>

<decisions>
## Implementation Decisions

### BacktestResult + Trade Ledger Schema

- **D-01: Two new DuckDB tables — `backtests` + `trades`.** The existing `runs` table is NOT extended. `backtests` holds: `run_id` (FK to `runs`), `strategy_id`, `symbol`, `timeframe`, `from_ts`, `to_ts`, `param_hash`, `equity_curve_path` (text — relative path to Parquet), and all scalar metrics: `total_return`, `cagr`, `sharpe`, `sortino`, `calmar`, `max_dd`, `max_dd_duration_bars`, `win_rate`, `expectancy`, `profit_factor`, `trade_count`, `avg_hold_bars`. A `trades` table holds per-trade rows.

- **D-02: Full attribution chain in `trades` table from day 1.** Fields: `trade_id`, `run_id`, `signal_id`, `strategy_id`, `side`, `entry_price`, `exit_price`, `exit_reason` (target|stop|eod_flat|manual), `entry_ts_utc`, `exit_ts_utc`, `pnl_$`, `size`, `slippage_ticks`, `mae`, `mfe`. The `fill_id → signal_id → risk_decision_id` chain is unbroken from Phase 3 forward.

- **D-03: Equity curves stored as Parquet files, path in `backtests.equity_curve_path`.** Layout: `data/parquet/equity/{run_id}.parquet`. Columns: `ts_utc`, `equity_$`, `drawdown_$`. This enables the bitwise-identical byte-compare required by ROADMAP success criterion #3 (reproducibility CI). DuckDB binary files are non-deterministic across runs so an in-DB equity_curves table would not satisfy the byte-compare assertion.

### WebSocket Stream

- **D-04: `WS /stream` mirrors all 7 EventBus topics.** Events emitted: `bar_received`, `signal_emitted`, `risk_decision`, `fill_executed`, `position_update`, `equity_update`, `degraded_state`. No client-side topic filtering in Phase 3 — the client receives everything. Phase 7 adds subscription filtering if needed.

- **D-05: Message envelope is `{"type": "<event_type>", "payload": {...}}`.** The `type` field uses a snake_case event name (matching the EventBus topic constants). The `payload` is the serialized Pydantic model. Standard discriminated-union pattern — the JS client switches on `type`.

- **D-06: In-process asyncio.Queue fan-out — no extra dependencies.** A single background task subscribes to all EventBus topics and puts serialized messages onto a per-connected-client `asyncio.Queue`. The `EventBus` from Phase 1 (`events/bus.py`) is used directly. Client disconnect triggers queue cleanup. No `broadcaster` library.

### Dashboard Layout

- **D-07: Cold-load state = most recent RTH bars in DuckDB, no overlays.** On first open (no backtest run), `/dashboard` loads the most recent available RTH bars for SPY (or ES) from DuckDB into the chart. ORB overlays are absent. A "Run Backtest" button is visible in the header. The chart is not blank — it shows real bars.

- **D-08: Two-pane layout — chart (top ~70%) + equity curve (bottom ~30%).** Chart pane: Lightweight Charts v5 candlestick series with ORB overlays and signal markers. Equity curve pane: Lightweight Charts v5 line series showing `equity_$` vs time for the most recent backtest (if one exists). Both panes update in real-time via `WS /stream`. Phase 7 adds drag/resize; Phase 3 uses fixed percentage heights.

- **D-09: ORB overlays use Lightweight Charts v5 primitive types — no custom plugins.** ORB box high/low = two `ISeriesApi.createPriceLine()` calls scoped to the opening-range window. Entry arrow = `series.setMarkers()` with an up/down arrow shape. Stop line = price line (red). Target line = price line (green). Phase 7 may upgrade to a custom drawing plugin for a true shaded rectangle.

### Risk + Fill Model Concreteness

- **D-10: Fill in the Phase-3 minimal fields directly on the existing stubs.** The `RiskDecision`, `Fill`, `RiskState`, and `RiskConfig` models in `risk/models.py` and `execution/models.py` receive the minimum fields Phase 3 needs. Phase 5 adds the remaining fields on top — no model churn or wholesale replacement.
  - `RiskDecision`: `approved: bool`, `reason: str`, `adjusted_size: int`
  - `Fill`: `signal_id: str`, `fill_price: Decimal`, `fill_qty: int`, `side: Literal["long","short"]`, `slippage_ticks: int`, `ts_utc: AwareDatetime`, `exit_reason: Literal["target","stop","eod_flat","manual"]`
  - `RiskState`: `realized_pnl_today: Decimal` (Phase 5 adds HWM + open exposure)
  - `RiskConfig`: `max_contracts: int = 1` (Phase 5 adds full risk params)

- **D-11: `exit_reason` is a four-value Literal: `target | stop | eod_flat | manual`.** `manual` is reserved for Phase 5's kill-switch/flatten — reserved now to avoid a schema migration later.

- **D-12: Intrabar stop+target conflict resolves stop-first (worst-case).** When both stop and target are touched within the same bar, the paper executor records `exit_reason="stop"`. This is the conservative assumption — never credit a winner when the bar touched both levels. Locked per ROADMAP spec.

### safe_from_signals Wrapper + BL-1

- **D-13: `safe_from_signals(entries, exits, price, …)` wrapper applies `entries.shift(1)` internally and forces `price="nextbar"`.** Any caller that passes pre-shifted entries or tries to override `price` gets a `ValueError`. Direct `vbt.Portfolio.from_signals(…)` is blocked by a pre-commit grep hook that rejects any file calling it outside of `safe_from_signals` itself. This is the ROADMAP-specified enforcement mechanism.

- **D-14: BL-1 lookahead detector test lives at `tests/integration/test_lookahead.py`.** Test constructs a deliberately-leaking ORB variant (`close.shift(-1)`-based entry), routes it through `safe_from_signals()`, asserts the resulting Sharpe is finite (not `inf`) and win rate is in the 40–60% band. This test is required to pass in CI for any PR merge.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Architecture + Phase Goal

- `.planning/ROADMAP.md` §"Phase 3: Vertical MVP Slice + Backtester" — Goal, 5 success criteria (BL-1 gate, reproducibility CI, EOD-flat assertion, UI requirements), requirements mapping (BT-01..09, SP-01, UI-01/04/08), Notes (safe_from_signals enforcement, slippage spec, minimal RiskManager + PaperExecutor spec, minimal UI-01 surface).
- `.planning/ROADMAP.md` §"Cross-Phase Guardrails" — BL-1 lookahead detector gate, reproducibility CI, EOD wall-clock flatten, TV MCP failure mode, four Protocol seams — all must remain unviolated.
- `CLAUDE.md` — Stack versions (VectorBT 1.0.0, FastAPI 0.136.1, Next.js 16.2, lightweight-charts 5.2.0, pandas 2.2.x), "What NOT to Use" table.
- `.planning/PROJECT.md` — Core value ("trust the numbers"), tech-stack picks, constraints.
- `.planning/REQUIREMENTS.md` — BT-01..09, SP-01, UI-01, UI-04, UI-08 requirement specs.

### Prior Phase Decisions Feeding Phase 3

- `.planning/phases/02-strategy-engine/02-02-SUMMARY.md` — ORBStrategy driver pattern (`snapshot → on_bar → _push_bar` order), `ORBConfig` fields, `StrategyRegistry` API, `orb_day_bars` fixture, ATR leakage integration test result. Phase 3 backtester uses this identical driver loop.
- `.planning/phases/02-strategy-engine/02-01-SUMMARY.md` — `Signal` + `StrategyContext` field inventory, indicator leakage proof test results, `orb_day_bars` fixture design (2024-01-02, bar[15] is breakout).
- `.planning/phases/01-foundation-data-in/01-CONTEXT.md` — Workspace shape decisions (D-01..D-04), `instruments.py` registry, `DuckDBStore` upsert pattern, EventBus design, pre-commit hook setup.

### Existing Code — Key Files for Phase 3

- `packages/trading-core/src/trading_core/events/bus.py` — `EventBus` (subscribe/publish async context manager); `events/models.py` — `BarReceived`, `DegradedStateEvent`, topic constants (`TOPIC_BARS`, `TOPIC_SIGNALS`, `TOPIC_FILLS`, etc.).
- `packages/trading-core/src/trading_core/storage/duckdb_store.py` — `DuckDBStore` class, `write_run()`, `upsert_bars()`, `write_parquet_partition()`. Phase 3 adds `write_backtest()` + `write_trade()` methods.
- `packages/trading-core/src/trading_core/strategy/orb.py` — `ORBStrategy`, `ORBConfig`. Phase 3 backtester drives this.
- `packages/trading-core/src/trading_core/strategy/registry.py` — `StrategyRegistry.from_yaml()`. Phase 3 CLI uses this to load the strategy.
- `packages/trading-core/src/trading_core/risk/protocols.py` — `RiskManager` Protocol signature (async `check(signal, state) → RiskDecision`).
- `packages/trading-core/src/trading_core/execution/protocols.py` — `Executor` Protocol signature (async `fill(signal, decision) → Fill`).
- `packages/trading-core/src/trading_core/risk/models.py` — `RiskDecision`, `RiskState`, `RiskConfig` stubs (Phase 3 fills in minimal fields per D-10).
- `packages/trading-core/src/trading_core/execution/models.py` — `Fill` stub (Phase 3 fills in minimal fields per D-10).
- `packages/trading-core/tests/fixtures/orb_day.py` — `orb_day_bars()` fixture (390 bars, 2024-01-02, bar[15] is breakout, SPY 1m). Reuse in backtester tests.
- `packages/api/src/api/app.py` — FastAPI shell (only `GET /health` in Phase 1; Phase 3 adds real routes).
- `apps/web/app/page.tsx` + `apps/web/app/layout.tsx` — Next.js stub with Tailwind. Phase 3 adds `/dashboard` route.

### VectorBT

- `https://vectorbt.dev` / vectorbt OSS 1.0.0 (PyPI) — `Portfolio.from_signals()` API. The `safe_from_signals` wrapper enforces `entries.shift(1)` + `price="nextbar"`. Key params: `sl_stop`, `tp_stop` for stop/target simulation; `freq` for metrics computation.

### Data Provider ADR

- `.planning/decisions/0001-data-provider.md` — TV MCP primary + Twelve Data SPY secondary. `adr_hash` must be written to every `runs` row (already enforced by `DuckDBStore.write_run()`).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets

- `EventBus` (`events/bus.py`): Async context manager pub/sub. Phase 3's WS fan-out subscribes to all 7 topics; the paper executor publishes to `TOPIC_FILLS`; the strategy driver publishes to `TOPIC_SIGNALS`.
- `DuckDBStore` (`storage/duckdb_store.py`): Context manager with `ensure_schema()`, `upsert_bars()`, `write_run()`, `write_parquet_partition()`. Phase 3 extends with `write_backtest()` + `write_trades()` methods. Follows the same ON CONFLICT upsert pattern already established.
- `orb_day_bars` fixture (`tests/fixtures/orb_day.py`): 390-bar SPY 1m day. Reuse directly in backtester acceptance tests and BL-1 CI test.
- `StrategyContext` + `Signal` models: Frozen Pydantic v2 with Decimal prices. The backtester driver loop follows the `snapshot → on_bar → _push_bar` pattern established in Phase 2.
- `instruments.py`: `Instrument` registry (ES, MES, SPY). `tick_value`, `point_value`, `tick_size` sourced from here for slippage calculation. Never hardcode.

### Established Patterns

- **Driver loop pattern** (locked in Phase 2): `ctx = snapshot indicators → signal = on_bar(bar, ctx) → _push_bar(bar)`. The backtester uses this exact loop over the bar DataFrame.
- **Decimal-only arithmetic** in all price paths. No `float()` except at pandas/VectorBT boundary; explicit `Decimal(str(round(x, 4)))` on conversion back.
- **UTC-only datetimes** everywhere; `America/New_York` for display only (Lightweight Charts `timeFormatter`).
- **Single-writer DuckDB** convention: only the FastAPI process and `run_backtest.py` instantiate `DuckDBStore`. No parallel writers.
- **Pre-commit hooks** already set up: no-naive-tz hook + gitleaks. Phase 3 adds the `no-direct-vbt-from-signals` grep hook.
- **`pytest --import-mode=importlib`** with no `tests/__init__.py` — established in Phase 1 Plan 1. All new test files follow this.

### Integration Points

- `packages/api/src/api/app.py`: Add `GET /bars`, `GET /backtests`, `WS /stream` routes. Import `DuckDBStore`, `EventBus` from `trading_core`.
- `apps/web/app/`: Add `/dashboard` App Router page. Use vanilla `lightweight-charts@5.2.0` in `useEffect`-mounted ref (no React wrapper). TanStack Query v5 already installed for REST data fetching. Zustand already installed for UI state. Native WebSocket client (no socket.io).
- `packages/trading-core/src/trading_core/risk/models.py` + `execution/models.py`: Fill in minimal fields per D-10. Existing tests must not break.
- `scripts/run_backtest.py`: New CLI script (alongside existing `scripts/seed_bars.py`). Uses `StrategyRegistry`, `DuckDBStore`, writes to `runs` + `backtests` + `trades` tables, exports equity curve Parquet.

</code_context>

<specifics>
## Specific Ideas

- **Slippage rule is session-phase-aware**: ≥1.5 ticks adverse during the 9:30–9:45 ET window (the "FR-1 pitfall" per ROADMAP notes). Outside that window the paper executor uses a tighter default (planner decides the off-peak default; 0.5 ticks is reasonable). `instruments.py` is the source for `tick_size`.
- **`safe_from_signals` pre-commit grep**: the hook rejects any line matching `vbt\.Portfolio\.from_signals\(` outside of `safe_from_signals` itself. Similar in spirit to the existing no-naive-tz hook — a shell grep with an explicit exception for the wrapper file path.
- **Reproducibility hash chain**: same `git_sha + data_hash + param_hash + seed` must produce a bitwise-identical equity-curve Parquet. The `data_hash` baseline for the 390-row SPY synthetic-day fixture is `2d61c1889a7dbca4fee3e3cf7ea719be6cb3e12810d575635e69d38a6bbdb19f` (from Phase 1 Plan 4 decision log in STATE.md).
- **ET clock + connection status in Next.js header**: Clock shows current wall-clock time in `America/New_York`. Connection-status indicator: green = WS connected + last bar ≤10s ago; yellow = last bar >10s; red = WS disconnected or last bar >30s. Degraded-state banner appears when a `degraded_state` WS event is received.

</specifics>

<deferred>
## Deferred Ideas

- **Full DrawdownModel variants** (TRAILING_EOD, TRAILING_INTRADAY) with HWM persistence — Phase 5.
- **`/positions`, `/trades`, `/equity`, `/optimizations`, `/kill`, `/flatten` REST endpoints** — later phases when their subsystems land (ROADMAP UI-01 note).
- **TVBridge auto-draw** on the live TradingView Desktop chart — Phase 6.
- **Drag/resize multi-pane layout** + blotter panel — Phase 7.
- **Optimization heatmap browser** — Phase 4.
- **Custom Lightweight Charts drawing plugin** for shaded ORB rectangle — Phase 7.
- **Client-side WS topic subscription filtering** — Phase 7.
- **JS test framework selection** — deferred in Phase 1; Phase 3 may introduce basic React Testing Library for the dashboard if the planner deems it valuable, but not required.

</deferred>

---

*Phase: 03-vertical-mvp-slice-backtester*
*Context gathered: 2026-05-16*
