# Phase 7: Bloomberg-Density UI Polish — Research

**Researched:** 2026-05-20
**Domain:** Next.js 16.2 multi-pane terminal layout, WebSocket reconnect, lightweight-charts v5 histogram, FastAPI strategy API
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- D-01: `/dashboard` becomes the 4-pane terminal (existing 2-pane replaced entirely)
- D-02: `/dashboard/blotter` retired with Next.js `redirects()` in `next.config.ts`; `apps/web/app/dashboard/blotter/` deleted
- D-03 (Claude): Default layout — Left 60% chart; Right 40% split [30% blotter / 40% history / 30% controls]
- D-04: `EquityCurve` merged into Trade History pane (trade rows + equity chart below)
- D-05: Each pane gets 28px title bar; `AuthorTVAlertButton` moves to BLOTTER title bar rightSlot
- D-06: Layout corruption → silent fallback to defaults (no user-visible error)
- D-07: `react-resizable-panels` for drag/resize
- D-08: `localStorage` key `es-terminal-layout`; stores size percentages JSON array
- D-09: Resize handles always visible; 4px divider `#222222` → `#3a3a3a` on hover
- D-10: Trade History pulls from last backtest run; no new API endpoint (uses existing `/backtests`, `/backtests/{id}/trades`, `/backtests/{id}/equity`)
- D-11: DD overlay = `HistogramSeries` on equity chart; bars below zero using `drawdown` field; color `rgba(239,68,68,0.5)`
- D-12: `focusedBarTs: string|null` Zustand atom; trade row click → `setFocusedBarTs(entry_ts_utc)` → `Chart.tsx` watches + calls `chart.timeScale().scrollToPosition()`
- D-13 (Claude): Fees = `slippage_ticks × tick_value × size` derived client-side; `tick_value = point_value / 4`
- D-14: Hot-reload via API writes YAML + `TOPIC_STRATEGY_RELOAD` EventBus event; engine subscribes and swaps in-memory Strategy without restart
- D-15: `POST /backtests/run` returns immediately with `{run_id}`; UI polls `GET /backtests/{run_id}` every 2s; `invalidateQueries(['backtests'])` on completion
- D-16: Server-side Pydantic 422 only (no client-side HTML5 min/max); show `detail` inline
- D-17: New routes — `GET /strategies`, `PUT /strategies/{id}/params`, `POST /strategies/{id}/toggle`, `POST /backtests/run`
- D-18 (Claude): Exponential backoff with jitter — `min(2^attempt × 1000ms, 30000ms) + Math.random() × 1000ms`
- D-19 (Claude): Monotonic `seq` field per WS message; `lastSeq` tracked; gap → `invalidateQueries` resync
- D-20 (Claude): Snapshot resync via existing endpoints: `GET /positions`, `GET /backtests`, trades, equity — no new endpoints
- D-21 (Claude): Playwright test in `apps/web/e2e/`; simulates 30s disconnect; `pnpm test:e2e` script

### Claude's Discretion
- D-03, D-13, D-18, D-19, D-20, D-21 — all Claude's discretion items have been resolved per CONTEXT.md

### Deferred Ideas (OUT OF SCOPE)
- `Ctrl+K` command palette — v2
- Live session paper fills in Trade History — v2 (last backtest only in v1)
- Multiple simultaneous backtest jobs — v2 (single background job at a time)
- Mobile / responsive layout — desktop widths only (SC#1)
- Soft DD threshold warnings (80% of daily limit) — V2-UI-06
- Multi-strategy concurrency cap UI — V2-MS-01
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| UI-02 | WebSocket reconnect with exponential backoff + jitter; client maintains sequence cursor; gap detection triggers REST snapshot resync | D-18/D-19/D-20 + `useStream.ts` extension pattern; `ConnectionStatus` yellow/red handles UX feedback; `invalidateQueries` in TanStack Query v5 is the resync mechanism |
| UI-03 | Next.js 16.2 + React 19 + TypeScript + dark monospace theme; multi-pane configurable grid layout (drag/resize panes); responsive only for desktop widths | `react-resizable-panels` 2.1.9 or 4.11.1 (both support React 19); layout persistence via `onLayout` → `localStorage`; all styling patterns established in Phases 3–6 |
| UI-06 | Trade history + equity curve panel: closed-trades table with side/entry/exit/gross PnL/fees/MAE/MFE/hold time/exit reason + running equity curve overlayed with DD bars | `HistogramSeries` available in lightweight-charts v5.2.0 (verified); existing `EquityPoint.drawdown` field covers DD data; `TradeRow` has all required fields |
| UI-07 | Strategy controls + parameter panel: toggle on/off, live-edit ORB params with hot-reload, backtest button, optimization heatmap browser | `StrategyRegistry.list_strategies()` exists; new routes in `strategies.py` following `risk.py` pattern; `TOPIC_STRATEGY_RELOAD` constant to be added to `events/models.py` |
| SP-06 | Sequence numbers on every WebSocket message + `state_version` field; client detects gaps and requests snapshot resync | `ConnectionManager._subscribe_topic()` fan-out wraps messages — `seq` field injected there; `useStream.ts` tracks `lastSeq` in Zustand WsStore |
</phase_requirements>

---

## Summary

Phase 7 is a pure UI/API integration phase with no new data-processing logic. The work divides cleanly into five tracks: (1) layout restructuring using `react-resizable-panels`, (2) blotter migration from `/dashboard/blotter` page into a pane component, (3) Trade History pane with a DD histogram using lightweight-charts v5 `HistogramSeries`, (4) Strategy Controls pane with a new FastAPI `strategies.py` route module and `TOPIC_STRATEGY_RELOAD` EventBus wiring, and (5) `useStream` hardening with exponential backoff, sequence numbers, and a Playwright E2E test.

All design decisions are locked in CONTEXT.md (D-01 through D-21). The 07-UI-SPEC.md provides exact pixel values, color tokens, and copywriting for every surface. The existing codebase is in excellent shape: `useHotkeys`, `EquityCurve`, `HOTKEY_REGISTRY`, and all TanStack Query hooks are ready to extend. The `ConfirmationDialog` and `HelpOverlay` components inside `apps/web/app/dashboard/blotter/page.tsx` must be extracted to `apps/web/components/` as part of the blotter migration.

One version discrepancy requires a planner decision: the UI-SPEC specifies `react-resizable-panels ^2.x` but npm registry latest is `4.11.1`. Both v2.1.9 (last v2 release) and v4.11.1 fully support React 19 via the same peer dependency spec. The API surface (PanelGroup, Panel, PanelResizeHandle, `onLayout`) is the same in v2 and v4. The planner should use `react-resizable-panels@^2.1.9` to honor the UI-SPEC vetting decision, or use `^4.11.1` which is the current maintained release — see Standard Stack section.

**Primary recommendation:** Build in 5 plans: Wave 0 (install + stubs), Wave 1 (TerminalLayout + BlotterPane), Wave 2 (TradeHistoryPane + EquityCurve update), Wave 3 (Strategy Controls + backend routes + EventBus wiring), Wave 4 (useStream backoff + seq numbers + Playwright E2E).

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| 4-pane drag/resize layout | Browser / Client (Next.js) | — | Pure client-side layout; no server state involved |
| Layout persistence (localStorage) | Browser / Client | — | `onLayout` writes JSON array; read on mount |
| Blotter pane (positions, kill/flatten/pause) | Browser / Client + API / Backend | — | Client renders; backend owns kill/flatten/pause state via DuckDB |
| Trade History pane (closed trades table) | Browser / Client | API / Backend | Client fetches/renders; backend owns trade data via DuckDB |
| Equity curve + DD histogram | Browser / Client | — | Pure client rendering of data fetched from existing endpoints |
| Chart scroll-to-trade (`focusedBarTs`) | Browser / Client | — | Zustand atom + lightweight-charts `scrollToPosition` — pure client |
| Strategy Controls (list, toggle, param edit) | Browser / Client + API / Backend | Database / Storage | Client renders form; API validates + writes YAML + publishes EventBus |
| Strategy hot-reload (TOPIC_STRATEGY_RELOAD) | API / Backend (EventBus) | — | In-process asyncio pub/sub; engine subscribes, swaps Strategy instance |
| Background backtest job (POST /backtests/run) | API / Backend | — | `asyncio.create_task` in FastAPI; client polls; result in DuckDB |
| WS reconnect / backoff | Browser / Client | — | `useStream.ts` manages retry loop; server is stateless per connection |
| WS sequence numbers | API / Backend (ConnectionManager) | Browser / Client | Server appends `seq`; client detects gaps and triggers resync |
| Playwright E2E test | Dev tooling | — | `apps/web/e2e/`; `@playwright/test` devDep only |

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `react-resizable-panels` | **2.1.9** (last v2; see note) | 4-pane drag/resize terminal layout | D-07 locked; ~12kB; `onLayout` for persistence; TypeScript-first; authored by Brian Vaughn (ex-React core team) |
| `@playwright/test` | **1.60.0** | E2E WS reconnect test (D-21) | Official Microsoft Playwright; devDep only; `pnpm test:e2e` |
| `lightweight-charts` | **5.2.0** (already installed) | Add `HistogramSeries` for DD overlay | Already used; `HistogramSeries` verified exported from v5.2.0 |
| `@tanstack/react-query` | **v5.x** (already installed) | `invalidateQueries` for snapshot resync; `useQuery` with `refetchInterval` for polling | Already used; `invalidateQueries` is the documented resync pattern |
| `zustand` | **v5.x** (already installed) | Add `focusedBarTs` + `lastSeq` atoms to `WsStore` | Already used; extends existing store cleanly |

**Version note on react-resizable-panels:** The UI-SPEC vetting document (2026-05-20) approved `^2.x`. However, the npm registry `latest` tag is `4.11.1` as of research date. Both v2.1.9 and v4.11.1 declare identical peer dependency specs (`react: ^18.0.0 || ^19.0.0`) and expose the same PanelGroup/Panel/PanelResizeHandle/onLayout API. The UI-SPEC safety gate passed on v2; the planner should use `react-resizable-panels@2.1.9` unless there is a specific reason to upgrade to v4. [VERIFIED: npm registry — react-resizable-panels latest=4.11.1, v2.1.9 peerDeps verified React 19 compatible]

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `vitest` | **4.1.6** (already installed) | Unit tests for new hooks/stores | All new JS unit tests |
| `@testing-library/react` | **16.3.2** (already installed) | React component tests | Integration tests for pane components |
| FastAPI `APIRouter` | 0.136.1 (already installed) | New `strategies.py` route module | Pattern: follow `packages/api/src/api/routes/risk.py` |
| Pydantic v2 `BaseModel` | 2.13.4 (already installed) | Strategy params validation schema | `PUT /strategies/{id}/params` 422 on invalid params |
| PyYAML | (already installed via trading-core) | Read/write `config/strategies/orb.yaml` | Strategy params persistence |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `react-resizable-panels` | `react-split` / hand-rolled pointer events | `react-resizable-panels` has `onLayout`, TypeScript, active maintenance — locked per D-07 |
| `@playwright/test` for E2E | Cypress | Playwright is lighter, no Electron wrapper, first-class TS support — locked per D-21 |
| `HistogramSeries` for DD | Second `LineSeries` with negative values | `HistogramSeries` renders as bars below zero — matches the Bloomberg-style DD look specified in D-11 |

**Installation (new packages only):**
```bash
# From apps/web directory
pnpm add react-resizable-panels@2.1.9
pnpm add -D @playwright/test@1.60.0
npx playwright install chromium --with-deps
```

[VERIFIED: npm registry — both packages confirmed available at stated versions]

---

## Architecture Patterns

### System Architecture Diagram

```
Browser (Next.js App Router — 'use client')
  ┌─────────────────────────────────────────────────────────────────┐
  │  /dashboard (TerminalLayout — apps/web/app/dashboard/page.tsx)  │
  │                                                                  │
  │  useStream() ←──── WS /stream ──────► ConnectionManager        │
  │    (backoff+seq)                        (seq counter)           │
  │                                                                  │
  │  PanelGroup[horizontal]                                          │
  │  ├── Panel[Chart] ←── focusedBarTs (Zustand) ──► scrollToPos   │
  │  └── PanelGroup[vertical]                                        │
  │      ├── Panel[BlotterPane] ────────► GET /positions (TQ)       │
  │      │      └── kill/flatten/pause ──► POST /kill /flatten /pause│
  │      ├── Panel[TradeHistoryPane]                                 │
  │      │      ├── trade table ──────► GET /backtests/{id}/trades  │
  │      │      └── equity+DD chart ──► GET /backtests/{id}/equity  │
  │      └── Panel[StrategyControlsPane]                            │
  │             ├── strategy list ────► GET /strategies (TQ)        │
  │             ├── param form ───────► PUT /strategies/{id}/params │
  │             ├── toggle ──────────► POST /strategies/{id}/toggle │
  │             ├── run backtest ─────► POST /backtests/run         │
  │             └── heatmap ─────────► (existing Plotly component)  │
  └─────────────────────────────────────────────────────────────────┘

FastAPI (packages/api)
  ├── WS /stream  ConnectionManager.seq_counter++ wraps every message
  ├── GET /strategies  ← reads config/strategies/*.yaml + engine_state
  ├── PUT /strategies/{id}/params  ← validates Pydantic, writes YAML,
  │                                  publishes TOPIC_STRATEGY_RELOAD
  ├── POST /strategies/{id}/toggle ← writes engine_state table
  └── POST /backtests/run  ← asyncio.create_task(BacktestEngine.run())

EventBus (in-process asyncio pub/sub)
  └── TOPIC_STRATEGY_RELOAD ──► StrategyReloadHandler
         └── StrategyRegistry.reload(strategy_id, new_params)
               └── swaps in-memory Strategy instance
```

### Recommended Project Structure (new files only)

```
apps/web/
├── app/
│   └── dashboard/
│       └── page.tsx                    ← REPLACE 2-pane with TerminalLayout
├── components/
│   ├── PaneContainer.tsx               ← NEW: 28px title bar + content wrapper
│   ├── BlotterPane.tsx                 ← NEW: migrated from blotter/page.tsx
│   ├── TradeHistoryPane.tsx            ← NEW: closed-trades table + equity chart
│   ├── StrategyControlsPane.tsx        ← NEW: param form + toggle + backtest btn
│   ├── HelpOverlay.tsx                 ← EXTRACTED from blotter/page.tsx
│   └── ConfirmationDialog.tsx          ← EXTRACTED from blotter/page.tsx
├── hooks/
│   ├── useStream.ts                    ← MODIFY: add backoff + seq tracking
│   └── useBacktests.ts                 ← MODIFY: add useStrategies, useStrategyRun
├── store/
│   └── ws.ts                           ← MODIFY: add focusedBarTs, lastSeq, setFocusedBarTs, setLastSeq
├── lib/
│   └── api.ts                          ← MODIFY: add StrategyInfo type
└── e2e/
    ├── playwright.config.ts            ← NEW: Playwright config
    └── ws-reconnect.spec.ts            ← NEW: WS reconnect + gap-detect E2E test

packages/api/src/api/
├── routes/
│   └── strategies.py                   ← NEW: GET/PUT /strategies, POST /backtests/run
└── app.py                              ← MODIFY: add TOPIC_STRATEGY_RELOAD subscriber wiring

packages/trading-core/src/trading_core/
└── events/
    └── models.py                       ← MODIFY: add TOPIC_STRATEGY_RELOAD constant

config/
└── strategies/orb.yaml                 ← MODIFY: written by PUT /strategies/orb/params

# DELETED:
# apps/web/app/dashboard/blotter/       ← directory deleted, redirect in next.config.ts
```

### Pattern 1: react-resizable-panels Layout
**What:** Nest `PanelGroup` / `Panel` / `PanelResizeHandle` components; persist sizes via `onLayout`
**When to use:** Root terminal layout in `dashboard/page.tsx`

```typescript
// Source: CONTEXT.md D-07, 07-UI-SPEC.md §TerminalLayout
import { Panel, PanelGroup, PanelResizeHandle } from 'react-resizable-panels'

const LAYOUT_KEY = 'es-terminal-layout'
const DEFAULT_H = [60, 40]
const DEFAULT_V = [30, 40, 30]

function loadLayout(key: string, fallback: number[]): number[] {
  try {
    const saved = localStorage.getItem(key)
    if (saved) return JSON.parse(saved) as number[]
  } catch { /* D-06: silent fallback */ }
  return fallback
}

export default function DashboardPage() {
  // ...
  return (
    <PanelGroup
      direction="horizontal"
      onLayout={(sizes) => localStorage.setItem(LAYOUT_KEY, JSON.stringify(sizes))}
    >
      <Panel defaultSize={60} minSize={/* 400px as % */}>
        <PaneContainer label="CHART"><Chart ... /></PaneContainer>
      </Panel>
      <PanelResizeHandle
        style={{ width: '4px', backgroundColor: '#222222', cursor: 'col-resize' }}
        aria-label="Resize chart and side panels"
      />
      <Panel defaultSize={40}>
        <PanelGroup direction="vertical" onLayout={...}>
          <Panel defaultSize={30} minSize={...}><PaneContainer label="BLOTTER">...</PaneContainer></Panel>
          <PanelResizeHandle style={{ height: '4px', backgroundColor: '#222222' }} />
          <Panel defaultSize={40} minSize={...}><PaneContainer label="HISTORY">...</PaneContainer></Panel>
          <PanelResizeHandle style={{ height: '4px', backgroundColor: '#222222' }} />
          <Panel defaultSize={30} minSize={...}><PaneContainer label="CONTROLS">...</PaneContainer></Panel>
        </PanelGroup>
      </Panel>
    </PanelGroup>
  )
}
```

### Pattern 2: HistogramSeries for DD Overlay (lightweight-charts v5)
**What:** Add a `HistogramSeries` to the same chart instance as the equity `LineSeries`
**When to use:** `TradeHistoryPane`'s equity chart section

```typescript
// Source: lightweight-charts v5.2.0 verified exports (HistogramSeries is a named export)
import { createChart, LineSeries, HistogramSeries } from 'lightweight-charts'

// Inside useEffect:
const chart = createChart(container, { /* same options as EquityCurve.tsx */ })

const equitySeries = chart.addSeries(LineSeries, {
  color: '#4ade80',
  lineWidth: 1,
})
const ddSeries = chart.addSeries(HistogramSeries, {
  color: 'rgba(239, 68, 68, 0.5)',   // #ef4444 at 50% opacity per D-11
  priceScaleId: 'right',             // same scale as equity line
})

equitySeries.setData(
  points.map((p) => ({
    time: Math.floor(new Date(p.ts_utc).getTime() / 1000) as Time,
    value: p.equity - startEquity,
  }))
)
ddSeries.setData(
  points.map((p) => ({
    time: Math.floor(new Date(p.ts_utc).getTime() / 1000) as Time,
    value: -Math.abs(p.drawdown),   // negate so bars render below zero
  }))
)
```

### Pattern 3: WS Sequence Number (Server-Side)
**What:** Inject a monotonic `seq` counter into every outgoing WS message
**When to use:** `packages/api/src/api/ws.py` `ConnectionManager`

```python
# Source: existing ws.py fan-out logic + SP-06 requirement
class ConnectionManager:
    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._clients: set[asyncio.Queue] = set()
        self._seq: int = 0          # per-server monotonic counter

    async def _subscribe_topic(self, topic: str) -> None:
        async with self._bus.subscribe(topic) as sub:
            async for event in sub:
                self._seq += 1
                if isinstance(event, dict):
                    payload = dict(event)
                    payload['seq'] = self._seq
                    msg = json.dumps(payload)
                else:
                    msg = json.dumps({
                        'type': event.topic,
                        'seq': self._seq,
                        'payload': event.model_dump(mode='json'),
                    })
                for q in list(self._clients):
                    await q.put(msg)
```

### Pattern 4: WS Reconnect with Backoff + Gap Detection (Client-Side)
**What:** Replace bare `new WebSocket()` in `useStream.ts` with a retry loop
**When to use:** `apps/web/hooks/useStream.ts`

```typescript
// Source: D-18/D-19/D-20 decisions
const MAX_BACKOFF_MS = 30_000

useEffect(() => {
  let attempt = 0
  let ws: WebSocket | null = null
  let stopped = false

  function connect() {
    ws = new WebSocket(`${WS_BASE}/stream`)
    ws.onopen = () => { setConnected(true); attempt = 0 }
    ws.onclose = () => {
      setConnected(false)
      if (!stopped) {
        const delay = Math.min(Math.pow(2, attempt) * 1000, MAX_BACKOFF_MS)
                      + Math.random() * 1000
        attempt++
        setTimeout(connect, delay)
      }
    }
    ws.onerror = () => { setConnected(false) }
    ws.onmessage = (event) => {
      // ... parse msg ...
      // Gap detection (D-19)
      const incomingSeq = (msg as { seq?: number }).seq ?? null
      if (incomingSeq !== null && lastSeq !== null && incomingSeq > lastSeq + 1) {
        // Gap detected — trigger snapshot resync
        queryClient.invalidateQueries({ queryKey: ['positions'] })
        queryClient.invalidateQueries({ queryKey: ['backtests'] })
        // etc.
      }
      if (incomingSeq !== null) setLastSeq(incomingSeq)
      // ... rest of routing ...
    }
  }

  connect()
  return () => { stopped = true; ws?.close() }
}, [/* stable refs */])
```

### Pattern 5: Strategy Reload Handler (Backend)
**What:** Subscribe to `TOPIC_STRATEGY_RELOAD` on EventBus; swap in-memory Strategy
**When to use:** `packages/api/src/api/app.py` lifespan wiring

```python
# Source: existing EventBus subscribe pattern (see ws.py); D-14
TOPIC_STRATEGY_RELOAD: Final[str] = "strategy_reload"  # add to events/models.py

# In lifespan or a dedicated handler module:
async def _strategy_reload_handler(bus: EventBus, registry_holder: dict) -> None:
    async with bus.subscribe(TOPIC_STRATEGY_RELOAD) as sub:
        async for event in sub:
            strategy_id = event['strategy_id']
            params = event['params']
            # Reload strategy from YAML (which was just written by the API)
            strategy_yaml = _repo_root / "config" / "strategies" / f"{strategy_id}.yaml"
            new_strategy = StrategyRegistry.load(strategy_yaml)
            registry_holder[strategy_id] = new_strategy
            log.info("strategy.hot_reloaded", strategy_id=strategy_id)
```

### Pattern 6: FastAPI strategies.py Route (Follow risk.py Pattern)
**What:** New route module for strategy CRUD
**When to use:** `packages/api/src/api/routes/strategies.py`

```python
# Source: existing risk.py pattern; D-17
@router.get("/strategies")
async def get_strategies(request: Request) -> list[dict]:
    strategies_dir = _repo_root / "config" / "strategies"
    result = []
    for yaml_path in sorted(strategies_dir.glob("*.yaml")):
        with yaml_path.open() as f:
            data = yaml.safe_load(f)
        strategy_id = data.get("strategy_id", yaml_path.stem)
        engine_state = get_store(request).get_engine_state()  # or per-strategy toggle
        result.append({
            "strategy_id": strategy_id,
            "name": data.get("name", strategy_id),
            "params": data.get("params", {}),
            "enabled": engine_state not in ("killed",),  # simplified for v1
        })
    return result

@router.put("/strategies/{strategy_id}/params")
async def put_strategy_params(strategy_id: str, body: ORBConfigUpdate, request: Request) -> dict:
    # 1. Pydantic validates (422 on failure)
    # 2. Write YAML
    # 3. bus.publish(TOPIC_STRATEGY_RELOAD, {...})
    # 4. Return updated params
    ...
```

### Pattern 7: Background Backtest Job (asyncio.create_task)
**What:** `POST /backtests/run` creates a background task and returns `run_id` immediately
**When to use:** `packages/api/src/api/routes/strategies.py` or `backtests.py`

```python
# Source: Phase 6 POST /tv/focus pattern (asyncio.create_task established precedent); D-15
@router.post("/backtests/run")
async def post_run_backtest(request: Request) -> dict:
    run_id = new_run_id()
    # Mark as pending in DuckDB immediately
    store = get_store(request)
    store.write_pending_backtest(run_id)
    # Non-blocking — returns immediately
    asyncio.create_task(_run_backtest_task(run_id, request.app.state))
    return {"run_id": run_id}
```

### Anti-Patterns to Avoid

- **Do not re-use `apps/web/app/dashboard/blotter/page.tsx` in-place:** The page.tsx must be deleted (per D-02). `ConfirmationDialog` and `HelpOverlay` are extracted to `apps/web/components/` first, then the page is deleted.
- **Do not call `chart.remove()` on the equity chart when `focusedBarTs` changes:** The scroll-to effect must be a separate `useEffect` from the chart lifecycle effect (same pattern as Chart.tsx Effect 1 / Effect 2 split).
- **Do not use `useEffect` deps on `queryClient`:** TanStack Query v5 `queryClient` is stable — get it via `useQueryClient()` inside the component and pass calls to `invalidateQueries` from the WS reconnect handler via a ref or callback.
- **Do not use `PanelResizeHandle` without `style` prop for sizing:** react-resizable-panels v2/v4 `PanelResizeHandle` defaults to 0px — always set explicit width/height.
- **Do not write YAML directly from the browser:** `PUT /strategies/{id}/params` goes through the API, which validates with Pydantic first. The client sends JSON body; the API writes YAML.
- **Do not call `bus.subscribe(TOPIC_STRATEGY_RELOAD)` inside a FastAPI route handler:** Subscribe in the lifespan or a background task, not per-request.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Drag/resize pane layout | Custom pointer-event listeners | `react-resizable-panels` | Handle edge cases: min sizes, keyboard resize, touch, ARIA — 500+ lines avoided |
| localStorage layout persistence | Manual JSON serialization | `react-resizable-panels` `onLayout` callback | Already returns the serializable sizes array |
| WS backoff algorithm | Custom interval tree | Simple `Math.min(2^attempt × 1000, 30000)` formula | One line is correct and readable; no library needed |
| E2E WS disconnect test | Custom WebSocket mock server | `@playwright/test` + Next.js dev server + mock WS | Playwright has built-in `page.route()` + WS interception; full browser context tests real reconnect behavior |
| Pydantic 422 error display | Client-side form validation | `response.json().detail` from the 422 response | Server is the single source of truth per D-16; parsing `detail` is ~5 lines |
| DD histogram as custom canvas drawing | `<canvas>` + requestAnimationFrame | `lightweight-charts` `HistogramSeries` | Shares time axis, zoom, scroll with the equity line automatically |

**Key insight:** The main complexity in this phase is coordination (which component owns which state, how do panes communicate), not algorithmic. Lean on Zustand for cross-pane state (`focusedBarTs`, `lastSeq`, `engineState`), TanStack Query for server state, and never prop-drill across pane boundaries.

---

## Common Pitfalls

### Pitfall 1: react-resizable-panels minSize expressed in pixels vs percentage
**What goes wrong:** Setting `minSize={400}` (interpreted as 400% by the library — defaults to percentage, not pixels)
**Why it happens:** `minSize` prop takes a number in **percentage points** of the panel group, not pixels
**How to avoid:** Convert pixel minimums to percentages: `minSize={Math.round(400 / window.innerWidth * 100)}`. Or use the `style={{ minWidth: '400px' }}` prop on the Panel wrapper div (CSS constraint). Recommended: use CSS `minWidth`/`minHeight` on the panel content container since the panel itself uses flex.
**Warning signs:** A pane collapses below its intended minimum during resize

### Pitfall 2: chart.remove() called twice (double-effect cleanup)
**What goes wrong:** The `TradeHistoryPane` equity chart is inside a component that re-mounts; `chart.remove()` called on an already-removed chart throws
**Why it happens:** `useEffect` cleanup runs when the component unmounts AND when deps change; if `points` changes while the component is mounted, the effect re-runs
**How to avoid:** Follow the exact two-effect pattern from `Chart.tsx` — one effect for chart lifecycle, one for data updates. Store the chart instance in a `useRef` and guard all operations with `if (!chartRef.current) return`
**Warning signs:** `TypeError: Cannot read properties of null (reading 'setData')` in console

### Pitfall 3: `useStream` reconnect loop leaks WebSocket instances
**What goes wrong:** Each reconnect creates a new `WebSocket` instance but the cleanup function only closes the final one
**Why it happens:** Closure over the `ws` variable in the reconnect timer; if the component unmounts before the timer fires, the new connection is never cleaned up
**How to avoid:** Track all scheduled timers in refs; in the `useEffect` cleanup, set a `stopped` flag that prevents new connections and clears pending timers. The pattern: `let stopped = false; return () => { stopped = true; ws?.close(); clearTimeout(timerId) }`
**Warning signs:** Multiple simultaneous WS connections visible in browser DevTools Network tab

### Pitfall 4: `invalidateQueries` called without `queryClient` in scope
**What goes wrong:** `useStream.ts` calls `queryClient.invalidateQueries(...)` but the hook doesn't have access to the TanStack Query client
**Why it happens:** `useQueryClient()` is a React hook — can't be called in non-hook code paths
**How to avoid:** The `useStream` hook calls `useQueryClient()` at the top level (it's already a hook); store the result in a ref (`const queryClientRef = useRef(queryClient)`); use `queryClientRef.current.invalidateQueries(...)` inside callbacks and event handlers
**Warning signs:** React error: "Invalid hook call" or `queryClient is not defined`

### Pitfall 5: TOPIC_STRATEGY_RELOAD published as dict but handler expects Event model
**What goes wrong:** `bus.publish(TOPIC_STRATEGY_RELOAD, {...})` publishes a plain dict, but the subscriber tries to call `.model_dump()` on it
**Why it happens:** `TOPIC_ENGINE_STATE` (Phase 5) also publishes plain dicts — the `_subscribe_topic` in `ws.py` already handles this with the `isinstance(event, dict)` guard, but a custom handler may not
**How to avoid:** Follow the Phase 5 pattern: publish as a plain dict with `{"type": "strategy_reload", "payload": {"strategy_id": ..., "params": ...}}`; handler receives it as a dict and accesses keys directly
**Warning signs:** `AttributeError: 'dict' object has no attribute 'topic'`

### Pitfall 6: Next.js `redirects()` in `next.config.ts` requires async function
**What goes wrong:** Adding `redirects` as a sync function in `next.config.ts` causes Next.js 16.2 build warning or error
**Why it happens:** `redirects()` in Next.js config must return a Promise (async function) even though the content is static
**How to avoid:**
```typescript
// next.config.ts — correct pattern
const nextConfig: NextConfig = {
  async redirects() {
    return [
      { source: '/dashboard/blotter', destination: '/dashboard', permanent: true },
    ]
  },
}
```
**Warning signs:** Next.js build warning about non-async redirects function

### Pitfall 7: `HistogramSeries` color must be set per-data-point for opacity
**What goes wrong:** Setting `color: 'rgba(239, 68, 68, 0.5)'` in `addSeries` options may not work for all lightweight-charts v5 versions; some builds require per-bar color
**Why it happens:** `HistogramSeries` supports a per-data-point `color` field in v5; global options may be overridden by default bar color
**How to avoid:** Set color in both `addSeries` options AND per data point:
```typescript
ddSeries.setData(
  points.map((p) => ({
    time: ...,
    value: -Math.abs(p.drawdown),
    color: 'rgba(239, 68, 68, 0.5)',   // per-bar color
  }))
)
```
**Warning signs:** DD histogram renders in default blue/green instead of red

---

## Code Examples

### Adding `focusedBarTs` to WsStore
```typescript
// Source: apps/web/store/ws.ts — extend existing store pattern
export interface WsState {
  // ... existing fields ...
  focusedBarTs: string | null
  lastSeq: number | null
}

export interface WsActions {
  // ... existing actions ...
  setFocusedBarTs: (ts: string | null) => void
  setLastSeq: (seq: number) => void
}

// In create() initializer:
focusedBarTs: null,
lastSeq: null,
setFocusedBarTs: (ts) => set({ focusedBarTs: ts }),
setLastSeq: (seq) => set({ lastSeq: seq }),
```

### Chart.tsx — focusedBarTs scroll-to effect
```typescript
// Source: 07-CONTEXT.md D-12; Chart.tsx Effect 2 pattern
const focusedBarTs = useWsStore((s) => s.focusedBarTs)
const setFocusedBarTs = useWsStore((s) => s.setFocusedBarTs)

useEffect(() => {
  if (!focusedBarTs || !seriesRef.current || !chartRef.current) return

  // Find bar index in sorted bars
  const targetUnix = Math.floor(new Date(focusedBarTs).getTime() / 1000)
  const sorted = [...bars].sort(
    (a, b) => new Date(a.ts_utc).getTime() - new Date(b.ts_utc).getTime()
  )
  const idx = sorted.findIndex(
    (b) => Math.floor(new Date(b.ts_utc).getTime() / 1000) === targetUnix
  )
  if (idx >= 0) {
    chartRef.current.timeScale().scrollToPosition(idx - Math.floor(sorted.length * 0.3), false)
  }
  setFocusedBarTs(null)  // reset after scroll
}, [focusedBarTs, bars, setFocusedBarTs])
```

Note: `Chart.tsx` currently stores `seriesRef` but not `chartRef`. The chart lifecycle effect must be updated to also store the chart instance in a ref for the scroll effect to access it.

### Adding `StrategyInfo` type to api.ts
```typescript
// Source: D-17 GET /strategies response shape
export interface StrategyInfo {
  strategy_id: string
  name: string
  params: Record<string, number | string | boolean>
  enabled: boolean
}
```

### useStrategies TanStack Query hook
```typescript
// Source: useBacktests.ts pattern; D-17
export function useStrategies() {
  return useQuery<StrategyInfo[]>({
    queryKey: ['strategies'],
    queryFn: async () => {
      const res = await fetch(`${API_BASE}/strategies`)
      if (!res.ok) throw new Error(`GET /strategies failed: ${res.status}`)
      return res.json() as Promise<StrategyInfo[]>
    },
    staleTime: 10_000,
  })
}

export function useStrategyRun(runId: string | null) {
  return useQuery<BacktestRow>({
    queryKey: ['backtest_run', runId],
    queryFn: async () => {
      const res = await fetch(`${API_BASE}/backtests/${runId}`)
      if (!res.ok) throw new Error(`GET /backtests/${runId} failed: ${res.status}`)
      return res.json() as Promise<BacktestRow>
    },
    enabled: runId != null,
    refetchInterval: (data) => {
      // Poll every 2s while pending; stop when complete
      if (!data || (data as BacktestRow & { status?: string }).status === 'pending') return 2000
      return false
    },
    staleTime: 0,
  })
}
```

Note: `GET /backtests/{run_id}` currently only exists as part of equity/trades endpoints. `POST /backtests/run` needs to write a `status` field to the `backtests` table, and `GET /backtests/{run_id}` needs to return a row with a `status` field. The planner must account for this schema addition.

### CORS update for PUT method
```python
# Source: app.py — Phase 5 added POST; Phase 7 adds PUT for strategy params
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],  # PUT added
    allow_headers=["*"],
    allow_credentials=False,
)
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `EquityCurve` as separate bottom pane | Merged into `TradeHistoryPane` | Phase 7 | Removes the standalone bottom pane; adds DD histogram |
| `/dashboard/blotter` as a separate route | Blotter as a pane within `/dashboard` | Phase 7 | Retired route; redirect in `next.config.ts` |
| WS reconnects immediately on close (no backoff) | Exponential backoff with jitter, capped at 30s | Phase 7 | Prevents reconnect storms; SP-06 compliance |
| No sequence numbers on WS messages | Monotonic `seq` per message from server | Phase 7 | Gap detection enables snapshot resync |
| `StrategyRegistry` is read-only (load only) | `StrategyRegistry` supports hot-reload via EventBus | Phase 7 | Strategy params editable at runtime without restart |
| `BacktestEngine.run()` blocks the request | `asyncio.create_task` returns `run_id` immediately | Phase 7 | Non-blocking UI; background job pattern |

**Deprecated / removed in Phase 7:**
- `apps/web/app/dashboard/blotter/page.tsx`: deleted (migrated to `BlotterPane` component)
- The "Blotter" nav link in the global header: removed (blotter is now a pane, not a route)
- The "Run Backtest" disabled button in the global header: removed (moved to Strategy Controls pane)

---

## Open Questions

1. **`GET /backtests/{run_id}` endpoint missing for polling**
   - What we know: `POST /backtests/run` returns `{run_id}`. The `useStrategyRun()` hook polls `GET /backtests/{run_id}` every 2s.
   - What's unclear: The existing `backtests.py` routes serve `GET /backtests` (list) and `GET /backtests/{run_id}/equity` and `GET /backtests/{run_id}/trades` — but there is no `GET /backtests/{run_id}` (single row) endpoint. The `backtests` table also has no `status` column.
   - Recommendation: The planner must add `GET /backtests/{run_id}` returning the full `BacktestRow` + a `status: 'pending' | 'complete' | 'failed'` field, and add a `status` column to the `backtests` schema. `POST /backtests/run` inserts a row with `status='pending'`; the background task updates to `status='complete'` or `status='failed'` on finish.

2. **`StrategyRegistry.toggle` method does not exist**
   - What we know: `StrategyRegistry` has `load()` and `list_strategies()`. `POST /strategies/{id}/toggle` should write to `engine_state` table per D-17.
   - What's unclear: Whether toggle state should be stored in `engine_state` (per-session) or in a new `strategy_state` table (persistent across restarts).
   - Recommendation: Follow Phase 5 precedent — use the existing `engine_state` DuckDB table. `POST /strategies/{id}/toggle` writes a row with the new `enabled` state. The `GET /strategies` endpoint reads this table to determine per-strategy enabled state. This reuses existing infrastructure without new schema work.

3. **`BacktestEngine` is not accessible from the FastAPI lifespan without import refactoring**
   - What we know: `BacktestEngine` is in `trading_core`. The API lifespan imports it lazily (similar to `FullRiskManager`). The `POST /backtests/run` needs to run a full backtest in the background.
   - What's unclear: What parameters `BacktestEngine.run()` needs and whether they come from the request body or are derived from config/YAML.
   - Recommendation: `POST /backtests/run` accepts an optional body `{strategy_id: string, from_date?: string, to_date?: string}` with sensible defaults from `config/risk.yaml` and `config/strategies/{id}.yaml`. The planner should define the full request/response schema.

4. **`react-resizable-panels` v2 vs v4 — which to pin**
   - What we know: UI-SPEC specifies `^2.x`. npm latest is `4.11.1`. Both support React 19. API surface is identical for PanelGroup/Panel/PanelResizeHandle/onLayout.
   - What's unclear: Whether v4 introduced any breaking changes vs v2 for the specific APIs used here.
   - Recommendation: Pin to `react-resizable-panels@2.1.9` to honor the UI-SPEC safety gate decision. If the planner wants v4, re-run the safety gate review. The API is equivalent for Phase 7's usage.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Node.js | pnpm install, Next.js dev | ✓ | v25.9.0 | — |
| pnpm | package management | ✓ | 9.15.0 (inferred from Phase 1 install) | — |
| Python 3.12 (via uv) | FastAPI routes, pytest | ✓ | 3.12.13 | — |
| uv | Python package management | ✓ | 0.11.x | — |
| pytest 8.x | Python tests | ✓ | 8.4.2 | — |
| FastAPI 0.136.1 | API routes | ✓ | 0.136.1 | — |
| Pydantic 2.13.4 | Strategy params validation | ✓ | 2.13.4 | — |
| DuckDB 1.5.2 | Storage reads | ✓ | 1.5.2 | — |
| `react-resizable-panels` | Terminal layout | ✗ (not installed) | — | Must install |
| `@playwright/test` | E2E WS test | ✗ (not installed) | — | Must install; also needs `npx playwright install chromium` |
| Vitest (for JS unit tests) | Frontend unit tests | ✓ | 4.1.6 | — |

**Missing dependencies that must be installed (no fallback):**
- `react-resizable-panels@2.1.9` — required for layout (D-07)
- `@playwright/test@1.60.0` + `playwright install chromium` — required for E2E (D-21)

[VERIFIED: npm registry for both packages]

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Frontend unit framework | Vitest 4.1.6 (jsdom environment) |
| Frontend E2E framework | Playwright 1.60.0 (Chromium) |
| Python test framework | pytest 8.4.2 + pytest-asyncio 0.24.x |
| Vitest config | `apps/web/vitest.config.ts` (exists, `environment: 'jsdom'`) |
| Playwright config | `apps/web/e2e/playwright.config.ts` (Wave 0 gap — does not exist) |
| Quick run (frontend unit) | `pnpm --filter web test -- --run` |
| Quick run (python) | `uv run pytest packages/ -x -q` |
| E2E run | `pnpm --filter web test:e2e` |
| Full suite | `uv run pytest packages/ && pnpm --filter web test -- --run` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| UI-02 | WS reconnect with backoff + gap detect + resync | E2E | `pnpm --filter web test:e2e` | ❌ Wave 0 gap |
| UI-03 | 4-pane layout renders + localStorage save/restore | E2E or Vitest + jsdom | `pnpm --filter web test -- --run` | ❌ Wave 0 gap |
| UI-06 | Trade table renders trade rows; DD histogram below equity | Vitest unit | `pnpm --filter web test -- --run` | ❌ Wave 0 gap |
| UI-07 | Strategy Controls: GET /strategies returns list; PUT validates | pytest | `uv run pytest packages/api/tests/test_strategies.py -x` | ❌ Wave 0 gap |
| SP-06 | WS messages include `seq` field; client tracks `lastSeq` | pytest (server) + Vitest (client) | both | ❌ Wave 0 gap |

### Sampling Rate
- **Per task commit:** `pnpm --filter web test -- --run` (frontend unit) + `uv run pytest packages/ -x -q` (Python)
- **Per wave merge:** Full suite (both commands above) + manual browser verification of layout rendering
- **Phase gate:** All green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `apps/web/e2e/playwright.config.ts` — Playwright config pointing to `http://localhost:3000`
- [ ] `apps/web/e2e/ws-reconnect.spec.ts` — WS disconnect/reconnect/gap-detect E2E test (covers UI-02, SP-06)
- [ ] `apps/web/__tests__/TradeHistoryPane.test.ts` — renders trade rows + DD histogram series (covers UI-06)
- [ ] `packages/api/tests/test_strategies.py` — GET /strategies, PUT /strategies/orb/params 200 + 422 (covers UI-07)
- [ ] `apps/web/package.json` — add `"test:e2e": "playwright test"` script

---

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | Single-operator localhost; no auth in v1 |
| V3 Session Management | no | No sessions; WS is stateless per connection |
| V4 Access Control | no | localhost-only CORS (already enforced in `app.py`) |
| V5 Input Validation | yes | Pydantic v2 validates strategy params on `PUT /strategies/{id}/params`; 422 on invalid input |
| V6 Cryptography | no | No sensitive data in new routes |
| V7 Error Handling | yes | 422 detail must not leak internal stack traces; `HTTPException(status_code=422, detail=str(e))` is sufficient |

### Known Threat Patterns for This Phase

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Path traversal via `strategy_id` in YAML write | Tampering | Validate `strategy_id` matches `^[a-z0-9_-]+$` regex before constructing file path; use `Path.resolve()` + `relative_to()` guard (same pattern as `backtests.py` equity path guard) |
| YAML injection via params values | Tampering | Use Pydantic model for params validation before `yaml.dump()`; only write validated typed values, not raw user input |
| CORS expansion for PUT method | Spoofing | Add `PUT` to `allow_methods` — already scoped to `localhost:3000` only; no new risk beyond Phase 5's POST addition |
| localStorage layout poisoning | Tampering | `JSON.parse` in a try/catch with silent fallback (D-06); no code execution risk from malformed JSON |

**Key constraint from CLAUDE.md:** `allow_origins` in CORS is `["http://localhost:3000", "http://127.0.0.1:3000"]` — must not be widened to `*` in this phase.

---

## Project Constraints (from CLAUDE.md)

The following CLAUDE.md directives apply directly to Phase 7 implementation:

1. **`lightweight-charts 5.2.0` — vanilla, no React wrapper** — `useEffect`-mounted ref only; `HistogramSeries` added to same `createChart` instance
2. **`react-resizable-panels` is OK to add** (explicitly mentioned in CLAUDE.md)
3. **Inline styles only for layout; Tailwind only for typography utilities** (`font-mono`, `tabular-nums`) — maintain this pattern in all new pane components
4. **`'use client'` directive required** on all interactive components
5. **No prop-drilling across pane boundaries** — use `useWsStore` for cross-pane state
6. **`pandas>=2.2,<3.0`** — not directly relevant to Phase 7 (UI focus) but BacktestEngine still uses it
7. **No new Python dependencies** for hot-reload — `watchdog` explicitly forbidden per CONTEXT.md; use EventBus only
8. **`asyncio.create_task` for non-blocking FastAPI** — `POST /backtests/run` must follow this pattern
9. **No Postgres / Docker** — DuckDB only for all new storage
10. **Windows / PowerShell primary** — `next.config.ts` redirects and file paths must be Windows-compatible; avoid POSIX-specific path constructors in tests
11. **No socket.io** — native WebSocket + TanStack Query `invalidateQueries` only (already enforced; no new deps needed)
12. **No Redux / Redux Toolkit** — Zustand 5.x for UI state

---

## Assumptions Log

> All factual claims in this research were verified via tool calls or codebase inspection.

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `react-resizable-panels` v2 and v4 have identical PanelGroup/Panel/PanelResizeHandle/onLayout API surface | Standard Stack | Planner might choose v4 and encounter API changes in handles or onLayout callback shape |
| A2 | `GET /backtests/{run_id}` (single-row) endpoint does not currently exist | Open Questions | If it exists, the planner does not need to add it |
| A3 | `StrategyRegistry.reload()` method does not currently exist (only `load()` and `list_strategies()`) | Open Questions | If it exists, the backend integration is simpler |
| A4 | `npx playwright install chromium` is required on the target Windows machine (browsers not pre-installed) | Environment Availability | If Playwright browsers are already installed, this installation step is a no-op |

[A1: ASSUMED — npm exports metadata does not expose runtime API shape]
[A2: VERIFIED: searched `backtests.py` — no single-row GET endpoint exists]
[A3: VERIFIED: read `registry.py` — only `load()` and `list_strategies()` exist]
[A4: ASSUMED — standard Playwright setup requirement on Windows]

---

## Sources

### Primary (HIGH confidence)
- Codebase — `apps/web/app/dashboard/blotter/page.tsx` — full blotter implementation inspected; `ConfirmationDialog` and `HelpOverlay` are inline components to be extracted
- Codebase — `apps/web/components/EquityCurve.tsx` — existing equity curve; `LineSeries` pattern ready to extend with `HistogramSeries`
- Codebase — `apps/web/components/Chart.tsx` — two-effect pattern (lifecycle / overlay) documented; `seriesRef` pattern confirmed
- Codebase — `apps/web/hooks/useStream.ts` — bare `new WebSocket()` confirmed; TODO(Phase 7) comment at line 72 confirmed
- Codebase — `apps/web/store/ws.ts` — `focusedBarTs` + `lastSeq` absent (must be added)
- Codebase — `apps/web/hooks/useHotkeys.ts` — `HOTKEY_REGISTRY` collision detection confirmed; no new hotkeys needed
- Codebase — `packages/api/src/api/ws.py` — `ConnectionManager._subscribe_topic()` fan-out loop; `seq` counter not present (must be added)
- Codebase — `packages/api/src/api/routes/backtests.py` — no `GET /backtests/{run_id}` single-row endpoint; no `status` column
- Codebase — `packages/api/src/api/routes/risk.py` — route pattern template for new `strategies.py`
- Codebase — `packages/api/src/api/app.py` — lifespan pattern for adding `TOPIC_STRATEGY_RELOAD` subscriber
- Codebase — `packages/trading-core/src/trading_core/events/models.py` — `TOPIC_STRATEGY_RELOAD` absent (must be added)
- Codebase — `packages/trading-core/src/trading_core/strategy/registry.py` — `reload()` absent; `list_strategies()` and `load()` exist
- Codebase — `config/strategies/orb.yaml` — params structure confirmed for `ORBConfig` Pydantic model binding
- Codebase — `apps/web/package.json` — `react-resizable-panels` absent; `@playwright/test` absent; `vitest` present; `lightweight-charts 5.2.0` present
- Codebase — `apps/web/vitest.config.ts` — jsdom environment, `@` alias confirmed
- npm registry — `react-resizable-panels@2.1.9` version confirmed; peerDeps `react ^16||^17||^18||^19` verified [VERIFIED]
- npm registry — `react-resizable-panels@4.11.1` is `latest`; peerDeps `react ^18||^19` verified [VERIFIED]
- npm registry — `@playwright/test@1.60.0` is `latest` in 1.x line [VERIFIED]
- Node runtime — `require('lightweight-charts')` — `HistogramSeries` export confirmed at v5.2.0 [VERIFIED]
- Runtime — `uv run python` — FastAPI 0.136.1, Pydantic 2.13.4, DuckDB 1.5.2 confirmed [VERIFIED]

### Secondary (MEDIUM confidence)
- `07-CONTEXT.md` — All D-01 through D-21 decisions (pre-researched by discuss-phase agent)
- `07-UI-SPEC.md` — Approved design contract; all pixel values, colors, copy from this file

### Tertiary (LOW confidence)
- None

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all versions verified via npm registry and node runtime
- Architecture: HIGH — derived from direct codebase inspection; patterns are established
- Pitfalls: HIGH — sourced from direct code reading of existing implementations; pitfalls are projections of known patterns
- Backend routes: HIGH — `risk.py` pattern is directly replicable; gaps documented in Open Questions

**Research date:** 2026-05-20
**Valid until:** 2026-06-20 (packages stable; `react-resizable-panels` API unlikely to change at v2.1.9 pin)
