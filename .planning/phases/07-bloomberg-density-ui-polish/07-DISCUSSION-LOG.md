# Phase 7: Bloomberg-Density UI Polish - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-20
**Phase:** 07-bloomberg-density-ui-polish
**Areas discussed:** Dashboard layout model, Trade History data source, Pane library for drag/resize, Strategy Controls hot-reload

---

## Dashboard Layout Model

### Q1 — Route structure

| Option | Description | Selected |
|--------|-------------|----------|
| Replace /dashboard | Existing /dashboard becomes the 4-pane terminal; /dashboard/blotter retired | ✓ |
| New /terminal route | Build 4-pane layout at a new URL; keep /dashboard and /dashboard/blotter as-is | |
| Extend /dashboard only | Add panels below existing chart+equity; blotter stays separate | |

**User's choice:** Replace /dashboard
**Notes:** Clean approach — single URL for the full terminal.

---

### Q2 — Default pane arrangement

| Option | Description | Selected |
|--------|-------------|----------|
| 2×2 grid | Chart top-left, blotter top-right, trade history bottom-left, strategy controls bottom-right | |
| Left column full-height chart, 3 stacked right | Chart dominates left; 3 panels stack vertically on right | |
| Let Claude decide | Claude picks a Bloomberg-style default | ✓ |

**User's choice:** Let Claude decide
**Notes:** Claude chose: chart left ~60% full height, right column three stacked panels (blotter ~30%, trade history+equity ~40%, strategy controls ~30%).

---

### Q3 — Equity curve fate

| Option | Description | Selected |
|--------|-------------|----------|
| Merge into Trade History pane | EquityCurve component moves inside Trade History; standalone pane removed | ✓ |
| Keep as separate pane | Equity curve stays its own resizable pane alongside trade history | |
| Let Claude decide | — | |

**User's choice:** Merge into Trade History pane

---

### Q4 — Blotter header controls

| Option | Description | Selected |
|--------|-------------|----------|
| Pane title bar with AuthorTVAlert inline | 28px title bar per pane; AuthorTVAlertButton in blotter bar; ET clock + connection status + engine badge in global header | ✓ |
| Blotter pane has no header row | Global header has clock/status; blotter pane drops its own header | |
| Let Claude decide | — | |

**User's choice:** Pane title bar with AuthorTVAlert inline

---

### Q5 — Redirect from retired /dashboard/blotter

| Option | Description | Selected |
|--------|-------------|----------|
| Redirect to /dashboard | next.config.ts redirects entry; users land on new terminal | ✓ |
| Just delete the route | Single operator — no one else bookmarked it | |

**User's choice:** Yes — redirect

---

### Q6 — Corrupted/missing layout

| Option | Description | Selected |
|--------|-------------|----------|
| Fall back to default silently | Invalid JSON → use default layout, no error shown | ✓ |
| Show reset toast | Notify user of invalid layout and reset | |

**User's choice:** Fall back to default silently

---

## Pane Library for Drag/Resize

### Q1 — Library choice

| Option | Description | Selected |
|--------|-------------|----------|
| react-resizable-panels | ~12kB, maintained, built-in onLayout for localStorage, great TS | ✓ |
| Hand-rolled CSS flex + pointer events | No new dep; harder to implement 2D resizing | |

**User's choice:** react-resizable-panels

---

### Q2 — localStorage key

| Option | Description | Selected |
|--------|-------------|----------|
| es-terminal-layout | Short, project-specific | ✓ |
| dashboard-pane-layout | More descriptive | |
| Let Claude decide | — | |

**User's choice:** es-terminal-layout

---

### Q3 — Handle visibility

| Option | Description | Selected |
|--------|-------------|----------|
| Visible always | 4px dark divider (#222), brightens on hover; permanent affordance | ✓ |
| Invisible until hover | Appears on cursor proximity; maximizes content area | |

**User's choice:** Visible always

---

## Trade History Data Source

### Q1 — What the panel shows

| Option | Description | Selected |
|--------|-------------|----------|
| Last backtest run only | GET /backtests/{id}/trades + GET /backtests/{id}/equity (already exist); no new endpoint | ✓ |
| Live session paper fills only | New GET /trades/session endpoint; equity from cumulative PnL | |
| Both with toggle | Toggle in pane title bar; double API surface + two equity curve implementations | |

**User's choice:** Last backtest run only

---

### Q2 — DD overlay representation

| Option | Description | Selected |
|--------|-------------|----------|
| Cumulative DD only | Histogram bars below zero using existing drawdown field on EquityPoint | ✓ |
| Both daily DD and cumulative DD | Two overlapping bar series; more info, visually complex | |
| Let Claude decide | — | |

**User's choice:** Cumulative DD only (histogram bars below zero)

---

### Q3 — Click-to-scroll signal flow

| Option | Description | Selected |
|--------|-------------|----------|
| Zustand shared state | focusedBarTs atom; trade row sets it; Chart pane useEffect scrolls | ✓ |
| Custom DOM event | window CustomEvent 'focusBar'; less type-safe | |
| React context | Wrap terminal in context exposing focusBar(); layer on top of Zustand | |

**User's choice:** Zustand shared state

---

### Q4 — Fees column

| Option | Description | Selected |
|--------|-------------|----------|
| Derive from slippage_ticks × tick_value client-side | No schema change; use existing TradeRow fields | |
| Add 'fees' column to DuckDB trades table | Schema migration; more explicit | |
| Let Claude decide | — | ✓ |

**User's choice:** Let Claude decide
**Notes:** Claude chose: derive `slippage_ticks × tick_value × size` client-side; column label "Slippage $". No schema migration.

---

## Strategy Controls Hot-Reload

### Q1 — Hot-reload mechanism

| Option | Description | Selected |
|--------|-------------|----------|
| API writes YAML + signals engine via EventBus | TOPIC_STRATEGY_RELOAD; engine swaps in-memory Strategy instance; no extra dep | ✓ |
| File watcher (watchdog) | API writes YAML only; engine polls for changes; adds Python dep + background thread | |
| DB-backed params only | Engine reads from strategy_params DuckDB table; no YAML involved | |

**User's choice:** API writes YAML + signals engine via EventBus

---

### Q2 — "Run Backtest" UX

| Option | Description | Selected |
|--------|-------------|----------|
| Background job with status polling | POST /backtests/run → run_id; UI polls every 2s; non-blocking | ✓ |
| Blocking request | POST waits until backtest completes; freezes request for 5-30s | |

**User's choice:** Background job with status polling

---

### Q3 — Param validation

| Option | Description | Selected |
|--------|-------------|----------|
| Server-side 422 only, surfaced in UI | Pydantic validates; UI shows 422 detail inline; per ROADMAP Phase 7 notes | ✓ |
| Client-side + server-side 422 fallback | HTML5 constraints + Pydantic; schema in two places | |

**User's choice:** Server-side 422 only, surfaced in UI

---

### Q4 — New API routes

| Option | Description | Selected |
|--------|-------------|----------|
| GET /strategies + PUT /strategies/{id}/params + POST /strategies/{id}/toggle + POST /backtests/run | Minimal surface matching existing route patterns | ✓ |
| Same + GET /strategies/{id}/params | Dedicated params-fetch endpoint | |

**User's choice:** GET /strategies + PUT /strategies/{id}/params + POST /strategies/{id}/toggle + POST /backtests/run

---

## Claude's Discretion

- **Default pane layout** (Q2 of Layout): chart left ~60% full height; right column three stacked panels (blotter, trade history+equity, strategy controls).
- **Fees column** (Q4 of Trade History): derived client-side as `slippage_ticks × tick_value × size`; column label "Slippage $".
- **WebSocket reconnect protocol** (not user-selected for discussion): exponential backoff + jitter matching TVBridge pattern (max 30s); sequence numbers on server-side messages; gap detection triggers `invalidateQueries` resync; Playwright test in `apps/web/e2e/`.

## Deferred Ideas

- `Ctrl+K` command palette → v2 (per ROADMAP Phase 7 notes)
- Live session paper fills in Trade History → v2
- Multiple simultaneous backtest jobs → v2
- Mobile / responsive layout → out of scope per ROADMAP SC#1
- Soft DD threshold warnings → v2 (V2-UI-06)
- Multi-strategy concurrency cap UI → v2 (V2-MS-01)
