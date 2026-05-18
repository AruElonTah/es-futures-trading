# Phase 5: Risk Manager + Full Audit + Controls - Context

**Gathered:** 2026-05-18
**Status:** Ready for planning

<domain>
## Phase Boundary

Every signal flows through a single risk gate that sizes correctly on `instruments.py`, tracks all three drawdown models side-by-side with HWM persisted across restarts, honors the daily-DD circuit breaker, flattens at the wall-clock EOD, and is observable through the live blotter with separate kill-switch and flatten controls. Audit log writes survive `kill -9`.

**In scope:** ATR-based position sizing (`FullRiskManager` replacing `PassThroughRiskManager`); `DrawdownModel` enum (STATIC / TRAILING_EOD / TRAILING_INTRADAY); `risk_state` DuckDB table tracking all 3 models side-by-side; HWM persistence across restarts; daily-DD circuit breaker ($2,000 default); wall-clock EOD flatten at `session_close - 60s` via asyncio scheduler; `SyntheticClock` hook in `BacktestEngine` for backtest EOD; audit log (DuckDB `audit_log` table + daily CSV mirror, synchronous writes, survives `kill -9`); `engine_state` table + kill-switch / flatten logic; `POST /kill` + `POST /flatten` API endpoints; `GET /positions` endpoint; blotter panel at `/dashboard/blotter`; hotkey registry (`F` flatten, `K` kill, `P` pause, `?` help overlay); `config/risk.yaml` (new file).

**Out of scope:** TVBridge / TV chart overlays (Phase 6); drag/resize multi-pane layout (Phase 7); WebSocket reconnect with sequence numbers (Phase 7); Trade History + Equity Curve panel (Phase 7); Strategy Controls hot-reload panel (Phase 7); multi-strategy concurrency (v2).

</domain>

<decisions>
## Implementation Decisions

### RiskConfig — New config/risk.yaml

- **D-01: `RiskConfig` lives in `config/risk.yaml` (new file).** Risk params are an operator-level concern, separate from strategy configs (e.g., `config/strategies/orb.yaml`). Loaded via the existing `pydantic-settings` loader pattern established in Phase 1.

- **D-02: `account_equity = $50,000` — static config value in `risk.yaml`.** Paper-only constraint means account equity is a fixed starting point for sizing math, not dynamically fetched from a broker. This keeps the sizing formula reproducible: changing the equity requires editing the config file deliberately.

- **D-03: `max_risk_per_trade_pct = 0.01` (1%).** At $50k: `risk_$ = $500/trade`. With 5-tick stop on MES (`tick_value = $1.25`): `floor(500 / 6.25) = 80 MES` → clamped to `max_contracts = 2`. Conservative, matches prop-firm norms.

- **D-04: ROADMAP-locked defaults in `risk.yaml`:** `daily_dd_limit = 2000` (USD), `max_contracts = 2` (MES units), `drawdown_model = TRAILING_INTRADAY` (Apex-style default). These may not be changed without updating the cross-phase guardrails in ROADMAP.md.

### Sizing Function

- **D-05 (Claude's discretion): Sizing function `size_for_stop(risk_dollars, stop_ticks, instrument)` is a pure function.** Takes `risk_$` as a direct parameter (not `account_equity × pct`) so it is independently unit-testable. The RM-01 unit tests (`size(1000, 5, MES) == 40` and `size(1000, 5, ES) == 4`) call it with `risk_dollars=1000` directly — no config dependency. The `FullRiskManager` computes `risk_dollars = account_equity × max_risk_per_trade_pct` before calling `size_for_stop`.

### risk_state DuckDB Table

- **D-06: Append-only `risk_state` table (one row per update, full audit trail).** Matches ROADMAP language "writes all three values to the `risk_state` table on every update". Each row is an immutable committed write — naturally survives `kill -9` since prior rows are already committed. Intraday history is preserved for forensic review.

- **D-07: `risk_state` schema — 12 key columns:**
  ```
  ts_utc           TIMESTAMPTZ   -- event timestamp (UTC)
  date             DATE          -- trading date (ET)
  session_id       VARCHAR       -- today's run_id (UUID7)
  equity_$         DECIMAL       -- current total equity
  realized_pnl_$   DECIMAL       -- today's realized PnL
  open_exposure_$  DECIMAL       -- current unrealized exposure
  hwm_static       DECIMAL       -- HWM for STATIC model (never decreases)
  floor_static     DECIMAL       -- DD floor for STATIC (hwm_static - daily_dd_limit)
  hwm_trailing_eod     DECIMAL   -- HWM for TRAILING_EOD (updates at session close)
  floor_trailing_eod   DECIMAL   -- DD floor for TRAILING_EOD
  hwm_trailing_intraday    DECIMAL  -- HWM for TRAILING_INTRADAY (real-time)
  floor_trailing_intraday  DECIMAL  -- DD floor for TRAILING_INTRADAY
  ```

### HWM Restart Bootstrap

- **D-08: On startup, query the last `risk_state` row WHERE `date = yesterday`.** Use `equity_$` from that row as today's starting HWM for all 3 DD models. Engine refuses to start if no row exists for yesterday — **Day-1 exception:** if `risk_state` table is empty, bootstrap all 3 HWMs from `account_equity` in `config/risk.yaml`. This matches ROADMAP SC#2: "engine refuses to start without today's HWM row computed from yesterday's close."

### Audit Log Architecture (Claude's Discretion)

- **D-09: New `audit_log` DuckDB table + daily CSV mirror at `data/logs/audit/{date}.csv`.** Every event (bar tick, signal, risk decision, fill, position update, equity update, kill switch, flatten command) is written synchronously: first a DuckDB `INSERT` (committed immediately, no buffering), then a CSV `append + flush()`. Both writes happen in the same synchronous path before the coroutine yields — no async buffering. This is the minimal mechanism that satisfies SP-03's "survives `kill -9`" requirement.

  Minimum `audit_log` schema:
  ```
  event_id     VARCHAR    -- UUID7
  ts_utc       TIMESTAMPTZ
  topic        VARCHAR    -- matches EventBus topic constants (e.g., 'fills', 'signals', 'risk_decisions')
  entity_id    VARCHAR    -- signal_id / fill_id / run_id (the primary entity for the event)
  reason_code  VARCHAR    -- 'dd_floor_violation', 'pass', 'kill_switch', 'flatten_all', etc.
  payload_json VARCHAR    -- serialized Pydantic model (JSON)
  ```

### Engine State + Kill/Flatten (Claude's Discretion)

- **D-10: Engine state lives in BOTH DuckDB (`engine_state` table) AND an in-memory `asyncio.Event`.** DuckDB provides persistence across restarts; the `asyncio.Event` provides fast in-process signaling (no DB query on each signal). On startup, the engine reads `engine_state` from DuckDB and sets the `asyncio.Event` accordingly. Kill-switch state survives restart.

- **D-11: `engine_state` table schema:** `(session_id, ts_utc, state)` where `state ∈ {running, killed, paused}`. On `POST /kill`, insert a new row with `state='killed'`, set the asyncio.Event, return `{"state": "killed", "positions_held": N}`. On `POST /flatten`, insert `state='flatten_requested'`, close all positions at next-bar-open, then insert `state='running'`.

- **D-12: `POST /kill` when no positions open** returns `{"state": "killed", "positions_held": 0}` — the kill switch still activates (halts new entries). `POST /flatten` when no positions open returns `{"positions_closed": 0}` — a no-op is valid.

### RiskState + RiskConfig Model Extensions

- **D-13: Extend `RiskState` (do NOT replace).** Add to existing stub per Phase 3 D-10 pattern: `equity_high_water: Decimal`, `open_exposure_$: Decimal`, `drawdown_model: DrawdownModel` (enum). Existing `realized_pnl_today` field is preserved.

- **D-14: Extend `RiskConfig` (do NOT replace).** Add to existing stub: `account_equity: Decimal`, `max_risk_per_trade_pct: Decimal`, `daily_dd_limit: Decimal`, `drawdown_model: DrawdownModel`. Existing `max_contracts: int = 1` is preserved (Phase 5 changes the default to `2`).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase Goal + Requirements

- `.planning/ROADMAP.md` §"Phase 5: Risk Manager + Full Audit + Controls" — Goal, 5 success criteria (sizing unit tests, DrawdownModel gate + HWM restart, worst_case_loss check + DD circuit breaker, EOD wall-clock flatten, blotter + kill/flatten hotkeys + audit log survival), requirements mapping (RM-01..08, SP-02, SP-03, SP-05, UI-05, UI-09), Notes (Phase 5 must not exit without DrawdownModel tests green + HWM-survives-kill-9 integration test green; `RiskManager.check` is the ONLY path from signal to fill; per-strategy concurrency cap = 1; audit writes synchronous).
- `.planning/ROADMAP.md` §"Cross-Phase Guardrails" — `DrawdownModel` + HWM persistence gate; EOD wall-clock flatten; four Protocol seams (`RiskManager` is the seam Phase 5 implements); Reproducibility CI must stay green.
- `.planning/REQUIREMENTS.md` — RM-01..RM-08, SP-02, SP-03, SP-05, UI-05, UI-09 full requirement specs.
- `CLAUDE.md` — Stack constraints (FastAPI 0.136.1, Pydantic v2, DuckDB 1.x, Next.js 16.2, lightweight-charts 5.2.0).

### Prior Phase Decisions Feeding Phase 5

- `.planning/phases/03-vertical-mvp-slice-backtester/03-CONTEXT.md` — D-10 (`RiskDecision`, `Fill`, `RiskState`, `RiskConfig` minimal stubs; Phase 5 EXTENDS, never replaces); D-11 (`exit_reason = "manual"` reserved for kill/flatten); D-12 (stop-first worst-case intrabar resolution, unchanged); D-13 (`safe_from_signals` enforcement, unchanged).
- `.planning/phases/03-vertical-mvp-slice-backtester/03-02-SUMMARY.md` — `BacktestEngine.run()` signature; `PaperExecutor` fill flow; `PassThroughRiskManager` interface being replaced.
- `.planning/phases/04-optimization-grid-walk-forward/04-CONTEXT.md` — DuckDB schema extensions pattern (D-13 `opt_runs`/`opt_results`); ProcessPoolExecutor pattern (workers import only `trading-core`) — Phase 5 follows same workspace boundary rules.

### Existing Code — Key Files for Phase 5

- `packages/trading-core/src/trading_core/risk/models.py` — `RiskConfig`, `RiskState`, `RiskDecision` stubs (Phase 5 extends these per D-13, D-14; do NOT replace the classes).
- `packages/trading-core/src/trading_core/risk/pass_through.py` — `PassThroughRiskManager` — the stub that `FullRiskManager` replaces. Keep it in place for test reference; `BacktestEngine` swaps in `FullRiskManager` via config.
- `packages/trading-core/src/trading_core/risk/protocols.py` — `RiskManager` Protocol seam. `FullRiskManager` satisfies it structurally (no inheritance).
- `packages/trading-core/src/trading_core/instruments.py` — `REGISTRY` with ES, MES, SPY `tick_value` / `tick_size` / `point_value`. Sizing math MUST use this; no magic numbers.
- `packages/trading-core/src/trading_core/execution/models.py` — `Fill` model with `exit_reason = "manual"` reserved for flatten.
- `packages/trading-core/src/trading_core/storage/duckdb_store.py` — `DuckDBStore` pattern for `ensure_schema()`, upsert/insert methods. Phase 5 adds `write_risk_state()`, `write_audit_event()`, `get_last_risk_state()`, `write_engine_state()`, `get_engine_state()`.
- `packages/trading-core/src/trading_core/events/bus.py` — `EventBus` + topic constants (`TOPIC_FILLS`, `TOPIC_SIGNALS`, `TOPIC_RISK_DECISIONS`, etc.). Phase 5 adds `TOPIC_AUDIT` and `TOPIC_ENGINE_STATE` events.
- `packages/api/src/api/app.py` — Existing FastAPI shell. Phase 5 adds `POST /kill`, `POST /flatten`, `GET /positions` routes.
- `apps/web/app/dashboard/page.tsx` — Existing `/dashboard`. Phase 5 adds a "Blotter" link in the header (does not restructure the dashboard panes — Phase 7 owns that).
- `apps/web/app/dashboard/` — Phase 5 adds `blotter/page.tsx` as a sub-route at `/dashboard/blotter`.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets

- `PassThroughRiskManager` (`risk/pass_through.py`): Shows the exact `check(signal, state) → RiskDecision` call signature. `FullRiskManager` implements the same interface structurally (no inheritance, per Protocol seam rules from Phase 1).
- `DuckDBStore` (`storage/duckdb_store.py`): `ensure_schema()` pattern for DDL; `write_run()` / `write_backtest()` patterns for the new `write_risk_state()` + `write_audit_event()` methods. Append-only insert pattern already established.
- `instruments.REGISTRY` (`instruments.py`): Direct dict lookup `instruments.get("MES")` gives `tick_value = Decimal("1.25")`, `tick_size = Decimal("0.25")`. Sizing math uses these.
- `EventBus` (`events/bus.py`): All topics (fills, signals, risk_decisions, etc.) are already subscribed by the WS fan-out. Phase 5 publishes `engine_state_changed` events that the blotter panel needs.
- `new_run_id()` (`storage/runs.py`): UUID7 generator — reuse for `event_id` in `audit_log` rows.
- `get_logger(__name__)` pattern: Used by `PassThroughRiskManager` for structured logging. `FullRiskManager` follows the same pattern.

### Established Patterns

- **Extend, don't replace models**: Phase 3 D-10 established that `RiskConfig`, `RiskState`, `RiskDecision`, `Fill` are extended across phases. `model_config = ConfigDict(extra="forbid")` will reject any stray fields — extend the class, don't add extra dict fields.
- **Decimal-only arithmetic** in all price/sizing paths. `floor(Decimal(risk_dollars) / (Decimal(stop_ticks) * instrument.tick_value))` — never use `int()` division directly.
- **UTC-only datetimes** in `risk_state` and `audit_log`. `date` column = ET trading date (derived from UTC timestamp using `America/New_York` zone), stored as `DATE`.
- **DuckDB single-writer**: `DuckDBStore` is the only writer. `FullRiskManager` calls `DuckDBStore` methods synchronously within the asyncio event loop (DuckDB writes are fast enough at intraday 1m bar rates to avoid a background thread).
- **`pytest --import-mode=importlib`**, no `tests/__init__.py` — all new test files follow this (Phase 1 Plan 1 decision).
- **Pre-commit hooks**: `no-direct-vbt-from-signals` already enforced. Phase 5 may add a `no-backdoor-signal-path` lint rule that blocks any `fill()` call not preceded by `risk_manager.check()`.

### Integration Points

- `packages/trading-core/src/trading_core/backtest/engine.py` — `BacktestEngine`: currently uses `PassThroughRiskManager`. Phase 5 changes it to accept a `RiskManager` (the Protocol type), defaulting to `FullRiskManager` when loaded from config. The `SyntheticClock` EOD flatten hook is added here.
- `packages/api/src/api/routes/` — Add `risk.py` route file with `POST /kill`, `POST /flatten`, `GET /positions`. Follow the `backtests.py` / `optimizations.py` pattern.
- `apps/web/app/dashboard/blotter/page.tsx` — New Next.js App Router sub-route. Fetches positions via `GET /positions` (TanStack Query, polls at 1s while WS is connected) + subscribes to `WS /stream` for live price updates from `bar_received` events.
- `config/risk.yaml` — New file. Loaded via `pydantic-settings` `YamlConfigSettingsSource` (same pattern as `system.yaml` from Phase 1 Plan 2).

</code_context>

<specifics>
## Specific Ideas

- **kill -9 integration test:** Kill the process mid-fill (using `subprocess.Popen` + `os.kill(pid, signal.SIGKILL)`), restart, assert: (a) the fill row exists in DuckDB `audit_log`, (b) `risk_state` HWM is correctly restored from the last committed row, (c) the engine does not start without the HWM bootstrap row (or uses `account_equity` for Day-1). This is the ROADMAP SC#2 cross-phase guardrail test — non-negotiable for phase exit.
- **`F` vs `K` confirmation dialogs:** `F` (flatten all) shows "Close all N open positions at next bar open?" — user must type "FLATTEN" to confirm. `K` (kill switch) shows "Halt all signal processing? Existing positions held." — user must type "KILL" to confirm. Different text strings = different audit-log `reason_code` values (`"flatten_all"` vs `"kill_switch"`).
- **Blotter live price:** The blotter panel subscribes to `WS /stream` and updates unrealized P&L on each `bar_received` event using the bar's `close` price as the mark price. No separate price feed needed — the existing WebSocket already delivers all bars.
- **`DrawdownModel` enum in config:** `risk.yaml` stores `drawdown_model: TRAILING_INTRADAY` as a string; `RiskConfig` loads it with `DrawdownModel(value)`. The `FullRiskManager` computes all 3 DD floors on every update regardless of which model is the "active" one — they're all written to `risk_state` for observability.
- **Sizing formula source of truth:** `contracts = floor(risk_dollars / (stop_ticks * tick_value))` where `tick_value = instruments.get(symbol).tick_value`. Cap: `min(contracts, config.max_contracts)`. This formula is locked by RM-01 and must match the unit test expectations exactly.

</specifics>

<deferred>
## Deferred Ideas

- **Drag/resize multi-pane layout** integrating the blotter into a unified dashboard — Phase 7.
- **WebSocket sequence numbers + snapshot resync** for the blotter — Phase 7 (SP-06).
- **Soft warnings at 80% of daily-DD threshold** — v2 (V2-UI-06).
- **Multi-strategy concurrency cap** (per-strategy capital silos) — v2 (V2-MS-01).
- **Engine state UI indicator** (beyond connection-status) showing kill/pause state — Phase 7 (part of the full hotkey registry overlay).

</deferred>

---

*Phase: 05-risk-manager-full-audit-controls*
*Context gathered: 2026-05-18*
