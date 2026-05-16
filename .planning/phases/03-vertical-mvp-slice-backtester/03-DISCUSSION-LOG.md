# Phase 3: Vertical MVP Slice + Backtester - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-16
**Phase:** 03-vertical-mvp-slice-backtester
**Areas discussed:** BacktestResult + trade ledger schema, WebSocket stream design, Dashboard first-load state + layout, Risk + Fill model concreteness

---

## BacktestResult + Trade Ledger Schema

### DuckDB persistence structure

| Option | Description | Selected |
|--------|-------------|----------|
| `backtests` + `trades` tables | New tables: backtests holds metadata + metrics + equity_curve_path; trades holds per-trade rows | ✓ |
| Extend `runs` table | Add metric columns to existing runs — conflates seed runs with backtest runs | |
| Single fat table with JSONB trades | One backtests table with JSON blob for trades — awkward DuckDB JSON querying | |

**User's choice:** `backtests` + `trades` tables

### Per-trade fields

| Option | Description | Selected |
|--------|-------------|----------|
| Full attribution chain | signal_id, run_id, strategy_id, side, entry/exit price, exit_reason, timestamps, pnl, size, slippage_ticks, mae, mfe | ✓ |
| Minimal trade record | run_id, side, entry/exit price, pnl, exit_reason — skip MAE/MFE | |
| You decide | Planner picks from metrics requirements | |

**User's choice:** Full attribution chain from day 1

### Equity curve location

| Option | Description | Selected |
|--------|-------------|----------|
| Parquet file, path in `backtests.equity_curve_path` | data/parquet/equity/{run_id}.parquet — enables bitwise byte-compare | ✓ |
| DuckDB `equity_curves` table | In-DB equity rows — DuckDB binary is non-deterministic, breaks reproducibility CI | |
| You decide | Planner picks | |

**User's choice:** Parquet file

---

## WebSocket Stream Design

### Event set

| Option | Description | Selected |
|--------|-------------|----------|
| Full event-bus mirror | All 7 bus topics: bar_received, signal_emitted, risk_decision, fill_executed, position_update, equity_update, degraded_state | ✓ |
| Bars + signals only | Enough for chart + markers, but breaks degraded-state banner (UI-08) | |
| Bars only | Minimal — degraded-state needs WS not polling | |

**User's choice:** Full event-bus mirror

### Message envelope

| Option | Description | Selected |
|--------|-------------|----------|
| `{"type": "bar_received", "payload": {...}}` | Discriminated union, type string = snake_case event name | ✓ |
| `{"topic": "bars", "data": {...}}` | Use EventBus topic string directly | |
| You decide | Planner picks envelope | |

**User's choice:** `{type, payload}` envelope

### Fan-out mechanism

| Option | Description | Selected |
|--------|-------------|----------|
| In-process asyncio.Queue per client | Uses existing EventBus, no extra deps, clean disconnect handling | ✓ |
| `broadcaster` library (0.3.x) | CLAUDE.md-listed option but alpha-quality; overkill for single-operator | |
| You decide | Planner picks | |

**User's choice:** In-process asyncio.Queue

---

## Dashboard First-Load State + Layout

### Cold-load state

| Option | Description | Selected |
|--------|-------------|----------|
| Most recent RTH bars + Run Backtest button | Chart shows real bars from DuckDB; ORB overlays absent until backtest runs | ✓ |
| Empty state with Run Backtest CTA | Blank chart + centered button — lifeless for a terminal | |
| Last backtest auto-loaded | Query DuckDB on load; show backtest if exists, otherwise bars | |

**User's choice:** Most recent bars on cold load

### Layout pane count

| Option | Description | Selected |
|--------|-------------|----------|
| Two-pane: chart (~70%) + equity curve (~30%) | Satisfies ROADMAP SC#5; both update via WS | ✓ |
| Single full-screen chart | Violates ROADMAP success criterion #5 | |
| Three-pane with blotter stub | No blotter data in Phase 3 — wasted real estate | |

**User's choice:** Two-pane layout

### ORB overlay drawing approach

| Option | Description | Selected |
|--------|-------------|----------|
| Primitive series types: price lines + markers | ORB high/low = price lines; entry = series marker; stop/target = colored price lines. No custom plugins. | ✓ |
| Custom drawing plugin | True shaded rectangle — adds ~200 lines TypeScript. Phase 7 material. | |
| You decide | Planner picks from lightweight-charts v5 API | |

**User's choice:** Primitive price lines + markers

---

## Risk + Fill Model Concreteness

### Model fields strategy

| Option | Description | Selected |
|--------|-------------|----------|
| Fill in minimal fields on existing stubs | Add minimum required fields to RiskDecision/Fill/RiskState/RiskConfig — Phase 5 adds more on top | ✓ |
| Phase-3-specific internal types | PaperExecutor uses own dataclasses; Protocol stubs stay empty until Phase 5 | |
| You decide | Planner decides based on paper executor needs | |

**User's choice:** Fill in minimal fields directly on existing Phase-1 stubs

### exit_reason values

| Option | Description | Selected |
|--------|-------------|----------|
| Four-value: target \| stop \| eod_flat \| manual | Reserve 'manual' now to avoid Phase 5 schema migration | ✓ |
| Three-value: target \| stop \| eod_flat | Skip manual — Phase 5 must migrate later | |
| You decide | Planner picks | |

**User's choice:** Four-value Literal including 'manual'

### Intrabar stop+target resolution

| Option | Description | Selected |
|--------|-------------|----------|
| Stop first (worst-case) | Conservative — never credit winner when bar touched both levels. ROADMAP spec. | ✓ |
| Target first | Optimistic — inflates equity curve. Contradicts ROADMAP. | |
| Flag ambiguous bars | Too complex for Phase 3 | |

**User's choice:** Stop first (confirmed the ROADMAP-specified behavior)

---

## Claude's Discretion

- **Off-peak slippage default**: ROADMAP specifies ≥1.5 ticks adverse during 9:30–9:45 ET. Planner decides the off-peak default (0.5 ticks is reasonable).
- **`safe_from_signals` lint rule mechanism**: ROADMAP says "noqa-style lint" — planner decides exact implementation (pre-commit grep hook is the established pattern in this project).
- **Phase 3 JS tests**: Not required per ROADMAP. Planner may add basic React Testing Library coverage for the dashboard if deemed valuable.

## Deferred Ideas

- Full DrawdownModel variants with HWM persistence → Phase 5
- `/positions`, `/trades`, `/equity`, `/optimizations`, `/kill`, `/flatten` endpoints → Phase 5+
- TVBridge auto-draw on TradingView Desktop → Phase 6
- Drag/resize multi-pane layout + blotter panel → Phase 7
- Optimization heatmap browser → Phase 4
- Custom Lightweight Charts drawing plugin for shaded ORB rectangle → Phase 7
- WS topic subscription filtering → Phase 7
