# Phase 7: Bloomberg-Density UI Polish - Context

**Gathered:** 2026-05-20
**Status:** Ready for planning

<domain>
## Phase Boundary

Rebuild the `/dashboard` route into a full 4-pane Bloomberg-density terminal: draggable/resizable panes (chart, blotter, trade history+equity, strategy controls), WebSocket reconnect with exponential backoff + sequence-number gap detection + snapshot resync, Trade History panel showing last backtest's closed trades + cumulative-DD equity curve, and a Strategy Controls panel that lists registered strategies, toggles them, live-edits ORB params with hot-reload via EventBus, and kicks off background backtests.

**In scope:**
- Replace `/dashboard` 2-pane layout with 4-pane drag/resize terminal using `react-resizable-panels`
- Retire `/dashboard/blotter` as a separate page; redirect it to `/dashboard`; blotter becomes a pane
- Merge `EquityCurve` component into the Trade History pane
- `useStream` hook: add exponential backoff with jitter + sequence-number tracking + REST snapshot resync on reconnect (SP-06)
- Playwright integration test for WS reconnect / gap-detect / resync (SC#2)
- Trade History pane: closed-trade table from last backtest + cumulative-DD histogram overlay on equity curve
- `focusedBarTs` Zustand atom: clicking a trade row scrolls the chart to the entry bar
- Strategy Controls pane: list strategies from `config/strategies/*.yaml`, toggle on/off, live-edit ORB params (Pydantic 422 validation returned inline), hot-reload engine via TOPIC_STRATEGY_RELOAD on EventBus
- Background backtest job: `POST /backtests/run` → run_id, UI polls until complete, result shown in Trade History + optimization browser
- New API routes: `GET /strategies`, `PUT /strategies/{id}/params`, `POST /strategies/{id}/toggle`, `POST /backtests/run`
- 2-param heatmap from Phase 4 browsable in the Strategy Controls pane

**Out of scope:**
- `Ctrl+K` command palette — deferred to v2 per ROADMAP notes
- Mobile / responsive layout — desktop widths only per ROADMAP SC#1
- Live session paper fills in Trade History — deferred; panel shows last backtest only
- Multiple simultaneous backtest jobs — single background job at a time
- File watcher / watchdog library — hot-reload via EventBus bus event (no extra dep)

</domain>

<decisions>
## Implementation Decisions

### Dashboard Layout Model

- **D-01: `/dashboard` becomes the 4-pane terminal.** The existing 2-pane layout (chart 70% / equity 30%) is replaced entirely. This is the primary URL for the full trading terminal.

- **D-02: `/dashboard/blotter` is retired with a Next.js redirect.** `apps/web/next.config.ts` gets a `redirects()` entry mapping `/dashboard/blotter` → `/dashboard`. The `apps/web/app/dashboard/blotter/` directory is deleted.

- **D-03 (Claude): Default pane layout.**
  - Left column (~60% width, full height): chart pane
  - Right column (~40% width), three stacked panels:
    - Top (~30%): blotter pane
    - Middle (~40%): trade history + equity curve pane
    - Bottom (~30%): strategy controls pane
  This mirrors the Bloomberg mental model: primary data surface dominant left, action surfaces stacked right.

- **D-04: Equity curve merged into Trade History pane.** The existing `EquityCurve` component moves inside the Trade History pane (trade rows table on top, equity curve chart below). The standalone `EquityCurve` bottom pane from the old dashboard is removed.

- **D-05: Each pane gets a compact 28px title bar.** Title bars show the pane label (CHART / BLOTTER / HISTORY / CONTROLS) in the same monospace dark style. The `AuthorTVAlertButton` moves from the retired blotter page header into the BLOTTER pane title bar. The global header retains: system title, ET clock, connection status, engine state badge.

- **D-06: Layout corruption → fall back to default silently.** If `localStorage.getItem('es-terminal-layout')` is missing or invalid JSON, apply the default layout without showing an error.

### Pane Library

- **D-07: `react-resizable-panels` for drag/resize.** ~12kB, actively maintained, great TypeScript support, built-in `onLayout` callback for localStorage persistence. Works in Next.js App Router. No hand-rolled pointer-event code needed.

- **D-08: localStorage key: `es-terminal-layout`.** Stores panel size percentages as a JSON array (the native `onLayout` payload).

- **D-09: Resize handles always visible.** 4px divider using `#222222` background, brightening to `#3a3a3a` on hover. Permanent affordance — Bloomberg-style dense UI doesn't hide its chrome.

### Trade History Data Source

- **D-10: Trade History panel pulls from the last backtest run only.** Uses existing endpoints: `GET /backtests` (for `latestRunId`), `GET /backtests/{run_id}/trades` (closed-trade rows), `GET /backtests/{run_id}/equity` (equity + drawdown points). No new API endpoint needed.

- **D-11: Equity curve DD overlay: cumulative DD histogram bars below zero.** Uses the existing `drawdown` field on `EquityPoint`. Rendered as a Histogram series in lightweight-charts below the equity line — the same pane, same time axis. No separate chart needed.

- **D-12: Click-to-scroll via Zustand `focusedBarTs` atom.** Add `focusedBarTs: string | null` + `setFocusedBarTs(ts: string | null) => void` to the Zustand `WsStore`. A trade row click calls `setFocusedBarTs(trade.entry_ts_utc)`. The Chart pane's `useEffect` watches `focusedBarTs` and calls `chart.timeScale().scrollToPosition()` when it changes.

- **D-13 (Claude): Fees = `slippage_ticks × tick_value × size`, derived client-side.** No schema migration. The `TradeRow` type already has `slippage_ticks` and `size`; `point_value` is available from `instruments.py` via `GET /positions`. For the trade history table, `tick_value` is derived as `point_value / 4` (1 point = 4 ticks for ES/MES). Column label: "Slippage $".

### Strategy Controls Hot-Reload

- **D-14: Hot-reload via API writes YAML + TOPIC_STRATEGY_RELOAD EventBus event.** `PUT /strategies/{id}/params` writes the updated params to `config/strategies/{id}.yaml` (Pydantic-validated), then publishes `TOPIC_STRATEGY_RELOAD` with `{strategy_id, params}` on the EventBus. The engine subscribes to this topic and swaps the in-memory `Strategy` instance without restart. No `watchdog` dependency added.

- **D-15: "Run Backtest with current params" is a background job.** `POST /backtests/run` returns immediately with `{run_id}`. The UI polls `GET /backtests/{run_id}` every 2s until `status != "pending"`. On completion, Trade History pane reloads (via TanStack Query `invalidateQueries`) and the optimization browser is updated.

- **D-16: Param validation: server-side Pydantic 422 only.** Per ROADMAP Phase 7 notes: "invalid params return a 422 with the validator message, not a silent fail." The Strategy Controls UI shows the 422 `detail` message inline below the field. No client-side HTML5 min/max constraints — single source of truth in the Pydantic model.

- **D-17: New API routes for Strategy Controls:**
  - `GET /strategies` — returns list of all registered strategies with current params and on/off state (reads `config/strategies/*.yaml` + `engine_state` table)
  - `PUT /strategies/{id}/params` — validates params (Pydantic 422 on error), writes YAML, publishes `TOPIC_STRATEGY_RELOAD`
  - `POST /strategies/{id}/toggle` — toggles on/off state, writes to `engine_state` table, publishes bus event
  - `POST /backtests/run` — kicks off `BacktestEngine.run()` in a `asyncio.create_task`, returns `{run_id}` immediately

### WebSocket Reconnect (Claude's Discretion — not discussed, based on ROADMAP SP-06)

- **D-18 (Claude): Exponential backoff with jitter.** `useStream` replaces the bare `new WebSocket(...)` with a reconnect loop: delay = `min(2^attempt × 1000ms, 30_000ms) + Math.random() × 1000ms`. Cap at 30s (matches TVBridge's pattern from Phase 6). On `ws.onclose`, schedule next attempt.

- **D-19 (Claude): Sequence numbers on server-side WS messages.** Each message published via the FastAPI `WS /stream` fan-out gets a monotonic `seq` field appended (integer, per-connection counter). The `useStream` hook tracks `lastSeq`. On reconnect, if the server's first message `seq > lastSeq + 1`, the client detects a gap and calls the REST snapshot endpoints before resuming normal processing.

- **D-20 (Claude): Snapshot resync endpoints on gap detection:** `GET /positions` (already exists), `GET /backtests` + `GET /backtests/{run_id}/trades` + `GET /backtests/{run_id}/equity` (already exist). TanStack Query's `invalidateQueries` triggers a fresh fetch. No new snapshot endpoints needed.

- **D-21 (Claude): Playwright test in `apps/web/e2e/`.** Test simulates: connect WS → pause mock WS server for 30s (drops connection) → reconnect → assert dashboard shows no permanent stale data. Uses `@playwright/test` added to devDependencies. Test runs via `pnpm test:e2e` in `apps/web/`.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase Goal + Requirements

- `.planning/ROADMAP.md` §"Phase 7: Bloomberg-Density UI Polish" — Goal, 5 success criteria (pane drag/resize + localStorage, WS reconnect + Playwright test, Trade History + equity curve + click-to-scroll, Strategy Controls + hot-reload + backtest button + heatmap, hotkey help overlay + collision detection), requirements (UI-02, UI-03, UI-06, UI-07, SP-06), Notes (vanilla LW-Charts; hot-reload via Pydantic 422; Ctrl+K deferred to v2).
- `.planning/ROADMAP.md` §"Cross-Phase Guardrails" — four Protocol seams (Strategy is the one Phase 7 touches for hot-reload); Reproducibility CI must stay green; TV failure mode (Phase 6 wired).
- `.planning/REQUIREMENTS.md` — UI-02, UI-03, UI-06, UI-07, SP-06 full requirement specs.
- `CLAUDE.md` — Stack constraints (Next.js 16.2, React 19, lightweight-charts 5.2.0 vanilla NO wrapper, react-resizable-panels OK to add, Zustand 5.x, TanStack Query v5, FastAPI 0.136.1, Pydantic v2).

### Prior Phase Decisions Feeding Phase 7

- `.planning/phases/05-risk-manager-full-audit-controls/05-CONTEXT.md` — D-10 (engine_state DuckDB table + asyncio.Event); D-11 (kill/flatten/pause flows); confirms blotter page was deferred to Phase 7 for layout integration; TOPIC_ENGINE_STATE already on EventBus.
- `.planning/phases/05-risk-manager-full-audit-controls/05-UI-SPEC.md` — Blotter color tokens (green #4ade80, yellow #eab308, red #ef4444), engine state badge colors, pane styling spec. MUST follow these tokens in the integrated blotter pane.

### Existing Code — Key Frontend Files

- `apps/web/app/dashboard/page.tsx` — Current 2-pane dashboard (REPLACED by Phase 7). Shows inline-style patterns and ORB computation logic to preserve/migrate.
- `apps/web/app/dashboard/blotter/page.tsx` — Blotter page (RETIRED, redirect to /dashboard). Contains the full blotter implementation: positions table, F/K/P dialogs, HelpOverlay — migrate into the blotter pane component.
- `apps/web/store/ws.ts` — Zustand WsStore. Phase 7 adds `focusedBarTs: string | null` + `setFocusedBarTs`. Also adds `lastSeq: number` for WS sequence tracking.
- `apps/web/hooks/useStream.ts` — WS hook (Phase 7 adds exponential backoff + jitter + sequence tracking + resync trigger).
- `apps/web/hooks/useHotkeys.ts` — `HOTKEY_REGISTRY` + collision detection already implemented. Phase 7 extends the registry (add any new hotkeys here; collision throws at startup).
- `apps/web/components/Chart.tsx` — Lightweight Charts vanilla mount. Phase 7 adds a `useEffect` watching `focusedBarTs` to call `chart.timeScale().scrollToPosition()`.
- `apps/web/components/EquityCurve.tsx` — Existing equity curve component (migrated into Trade History pane; add DD histogram series).
- `apps/web/lib/api.ts` — `BarRow`, `BacktestRow`, `EquityPoint`, `TradeRow` types. Phase 7 adds `StrategyInfo` type for `GET /strategies` response.
- `apps/web/hooks/useBacktests.ts` — TanStack Query hooks for backtests/equity/trades. Phase 7 adds `useStrategies()` and `useStrategyRun()` hooks.

### Existing Code — Key Backend Files

- `packages/api/src/api/routes/risk.py` — `GET /positions`, `POST /kill`, `POST /flatten`, `POST /pause` patterns. Phase 7 adds `packages/api/src/api/routes/strategies.py` following the same pattern.
- `packages/api/src/api/routes/backtests.py` — Existing backtest query routes. Phase 7 adds `POST /backtests/run` to this file or the new strategies file.
- `packages/api/src/api/app.py` — FastAPI lifespan with EventBus, DuckDBStore, TVBridge, RiskManager on `app.state`. Phase 7 wires `TOPIC_STRATEGY_RELOAD` subscriber on the engine side.
- `packages/trading-core/src/trading_core/events/models.py` — Topic constants (TOPIC_FILLS, TOPIC_SIGNALS, TOPIC_ENGINE_STATE, etc.). Phase 7 adds `TOPIC_STRATEGY_RELOAD`.
- `packages/trading-core/src/trading_core/events/bus.py` — `EventBus` publish/subscribe pattern. Phase 7 engine subscribes to `TOPIC_STRATEGY_RELOAD`.
- `config/strategies/orb.yaml` — Strategy YAML that `PUT /strategies/orb/params` writes. Pydantic model validates before write.
- `packages/trading-core/src/trading_core/strategy/registry.py` — `StrategyRegistry` that `GET /strategies` reads and `POST .../toggle` mutates.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets

- `EquityCurve` component (`apps/web/components/EquityCurve.tsx`): already mounts a lightweight-charts `LineSeries`. Phase 7 adds a `HistogramSeries` on the same chart for the DD overlay. The component receives `EquityPoint[]` which already has a `drawdown` field.
- `useHotkeys` + `HOTKEY_REGISTRY` (`apps/web/hooks/useHotkeys.ts`): collision detection + `useEffect` listener already implemented. Phase 7 only extends the registry array and potentially the handler dispatch.
- `HelpOverlay` + `ConfirmationDialog` components in `apps/web/app/dashboard/blotter/page.tsx`: these are inline components that need to be extracted into `apps/web/components/` so they're shared between the new blotter pane and any other pane that needs dialogs.
- `DegradationBanner` (`apps/web/components/DegradationBanner.tsx`): already implemented in Phase 3, stays in the global header.
- `useStream` (`apps/web/hooks/useStream.ts`): already handles bars, degraded_state, engine_state_changed, positions. The TODO(Phase 7) comment at line 72 marks where fills/equity/signals routing will go.
- TanStack Query hooks (`apps/web/hooks/useBacktests.ts`, `useBars.ts`): established `useQuery` + `refetchInterval` pattern; Phase 7 follows the same for `useStrategies()` and `useStrategyRun()`.

### Established Patterns

- **Inline styles only, no Tailwind for layout.** The dashboard page uses `style={{ ... }}` throughout; only monospace class names via Tailwind (`font-mono`, `tabular-nums`). Maintain this pattern in new pane components.
- **Dark color palette.** Background: `#000000`. Surface: `#111111`. Borders: `#222222`. Text: `#d1d4dc`. Muted: `#888888`. Link/accent: `#4a90d9`. These are consistent across all Phase 3–6 UI components.
- **`'use client'` directive on all interactive components.** Next.js App Router; every pane component needs `'use client'`.
- **No prop-drilling across pane boundaries.** Use Zustand (`useWsStore`) for cross-pane state (engine state, positions, focusedBarTs, lastSeq).
- **`asyncio.create_task` for non-blocking FastAPI responses.** Established in Phase 6 (`POST /tv/focus` pattern). Phase 7's `POST /backtests/run` follows the same: `asyncio.create_task(run_engine(...))`, return `{run_id}` immediately.
- **`gsd-sdk` / `uv run pytest`** test patterns: `pytest --import-mode=importlib`, no `tests/__init__.py`.

### Integration Points

- `react-resizable-panels`: wrap the entire terminal layout in `<PanelGroup direction="horizontal">`. Left = chart `<Panel>`. Right = `<PanelGroup direction="vertical">` with three `<Panel>` children. `onLayout` callback saves to `localStorage['es-terminal-layout']`.
- Chart `focusedBarTs` watcher: in `apps/web/components/Chart.tsx`, add a second `useEffect` that watches `useWsStore(s => s.focusedBarTs)`. When non-null, call `chart.timeScale().scrollToPosition(targetIndex, false)` then call `setFocusedBarTs(null)` to reset.
- `TOPIC_STRATEGY_RELOAD` subscriber in the engine: `BacktestEngine` (or a new `StrategyReloadHandler`) subscribes via `bus.subscribe(TOPIC_STRATEGY_RELOAD, handler)`. Handler calls `registry.reload(strategy_id, new_params)` which replaces the in-memory `Strategy` instance.
- WS sequence numbers: FastAPI `WS /stream` fan-out at `packages/api/src/api/routes/stream.py` (or wherever the WS endpoint lives) wraps each outgoing message as `{seq: next_seq(), ...original_payload}`.

</code_context>

<specifics>
## Specific Ideas

- **Blotter pane title bar layout:** `[BLOTTER] [engine-state-badge] ← left aligned` | `[AuthorTVAlertButton] [ET clock] → right aligned`. Same 28px height as other pane title bars. Matches the style from `05-UI-SPEC.md`.
- **Strategy Controls edit form:** For ORB params, render each YAML key as a labeled input field (label from the Pydantic field name, value from current YAML). On `PUT /strategies/orb/params` 422, display the Pydantic `detail` error string in red below the relevant field. A "Save & Hot-reload" button triggers the PUT.
- **Backtest progress indicator:** While `POST /backtests/run` is polling, show a spinner/progress row in the Trade History pane where the new result will appear. On completion, `invalidateQueries(['backtests'])` to refresh.
- **Pane min sizes:** Chart pane min width = 400px; blotter min height = 120px; trade history min height = 150px; strategy controls min height = 100px. These prevent the user from collapsing a pane to zero.
- **ORB box stub fix (from Phase 6 verification warning):** Phase 6 left the ORB box drawing with stub H/L values (`signal.entry * 1.001/0.999`). While Phase 7 is frontend-focused, if the planner identifies a clean path to wire real session `orb_high/orb_low` from the `Signal` object into `_draw_orb_box_if_new` without scope creep, it should be included as a bonus fix. If not, defer explicitly.

</specifics>

<deferred>
## Deferred Ideas

- **`Ctrl+K` command palette** — deferred to v2 per ROADMAP Phase 7 notes. Do not implement.
- **Live session paper fills in Trade History** — Trade History panel shows last backtest only in v1. Live session fills can be added in v2 when there's a `GET /trades/session` endpoint.
- **Multiple simultaneous backtest jobs** — single background job at a time. Queue management is v2.
- **Mobile / responsive layout** — desktop widths only per ROADMAP SC#1.
- **Soft DD threshold warnings (80% of daily limit)** — deferred from Phase 5 as V2-UI-06.
- **Multi-strategy concurrency cap UI** — per-strategy capital silos are v2 (V2-MS-01).

</deferred>

---

*Phase: 07-bloomberg-density-ui-polish*
*Context gathered: 2026-05-20*
