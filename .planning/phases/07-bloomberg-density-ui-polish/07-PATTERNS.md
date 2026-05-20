# Phase 7: Bloomberg-Density UI Polish - Pattern Map

**Mapped:** 2026-05-20
**Files analyzed:** 20 (12 new + 8 modified)
**Analogs found:** 20 / 20

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `apps/web/app/dashboard/page.tsx` (REPLACED) | component | request-response | `apps/web/app/dashboard/page.tsx` (itself, v2 replaces v1) | exact |
| `apps/web/components/BlotterPane.tsx` (new) | component | request-response | `apps/web/app/dashboard/blotter/page.tsx` | exact |
| `apps/web/components/TradeHistoryPane.tsx` (new) | component | request-response | `apps/web/components/EquityCurve.tsx` + `apps/web/app/dashboard/blotter/page.tsx` (table section) | exact |
| `apps/web/components/StrategyControlsPane.tsx` (new) | component | request-response | `apps/web/app/dashboard/blotter/page.tsx` (controls row) | role-match |
| `apps/web/components/PaneContainer.tsx` (new) | component | — | `apps/web/app/dashboard/blotter/page.tsx` (header section, lines 526–572) | role-match |
| `apps/web/components/HelpOverlay.tsx` (extracted) | component | — | `apps/web/app/dashboard/blotter/page.tsx` (lines 304–401) | exact |
| `apps/web/components/ConfirmationDialog.tsx` (extracted) | component | — | `apps/web/app/dashboard/blotter/page.tsx` (lines 128–298) | exact |
| `apps/web/e2e/playwright.config.ts` (new) | config | — | `apps/web/vitest.config.ts` | role-match |
| `apps/web/e2e/ws-reconnect.spec.ts` (new) | test | event-driven | no direct analog | no-analog |
| `packages/api/src/api/routes/strategies.py` (new) | route | request-response | `packages/api/src/api/routes/risk.py` | exact |
| `apps/web/next.config.ts` (add redirect) | config | — | `apps/web/next.config.ts` (itself) | exact |
| `apps/web/hooks/useStream.ts` (modify) | hook | event-driven | `apps/web/hooks/useStream.ts` (itself) | exact |
| `apps/web/store/ws.ts` (modify) | store | — | `apps/web/store/ws.ts` (itself) | exact |
| `apps/web/hooks/useBacktests.ts` (modify) | hook | request-response | `apps/web/hooks/useBacktests.ts` (itself) | exact |
| `apps/web/lib/api.ts` (modify) | utility | — | `apps/web/lib/api.ts` (itself) | exact |
| `apps/web/components/Chart.tsx` (modify) | component | request-response | `apps/web/components/Chart.tsx` (itself) | exact |
| `apps/web/components/EquityCurve.tsx` (modify) | component | request-response | `apps/web/components/EquityCurve.tsx` (itself) | exact |
| `apps/web/hooks/useHotkeys.ts` (modify) | hook | event-driven | `apps/web/hooks/useHotkeys.ts` (itself) | exact |
| `packages/api/src/api/app.py` (modify) | config | event-driven | `packages/api/src/api/app.py` (itself) | exact |
| `packages/api/src/api/routes/backtests.py` (modify) | route | CRUD | `packages/api/src/api/routes/backtests.py` (itself) | exact |
| `packages/trading-core/src/trading_core/events/models.py` (modify) | model | — | `packages/trading-core/src/trading_core/events/models.py` (itself) | exact |
| `packages/trading-core/src/trading_core/strategy/registry.py` (modify) | service | — | `packages/trading-core/src/trading_core/strategy/registry.py` (itself) | exact |
| `config/strategies/orb.yaml` (modify) | config | — | `config/strategies/orb.yaml` (itself) | exact |

---

## Pattern Assignments

### `apps/web/app/dashboard/page.tsx` (component, request-response) — REPLACED

**Analog:** `apps/web/app/dashboard/page.tsx` (current 2-pane version, lines 1–215)

**Imports pattern** (lines 1–31 of current file — keep, extend):
```typescript
'use client'

import { useMemo } from 'react'
import { useStream } from '@/hooks/useStream'
import { useBars } from '@/hooks/useBars'
import { useBacktests, useEquityCurve, useEquityTrades } from '@/hooks/useBacktests'
import Chart from '@/components/Chart'
import ETClock from '@/components/ETClock'
import ConnectionStatus from '@/components/ConnectionStatus'
import DegradationBanner from '@/components/DegradationBanner'
```
Phase 7 adds:
```typescript
import { Panel, PanelGroup, PanelResizeHandle } from 'react-resizable-panels'
import PaneContainer from '@/components/PaneContainer'
import BlotterPane from '@/components/BlotterPane'
import TradeHistoryPane from '@/components/TradeHistoryPane'
import StrategyControlsPane from '@/components/StrategyControlsPane'
```

**localStorage persistence pattern** (from CONTEXT.md D-06/D-08, no direct analog — use this shape):
```typescript
const LAYOUT_KEY = 'es-terminal-layout'
const DEFAULT_H_SIZES = [60, 40]
const DEFAULT_V_SIZES = [30, 40, 30]

function loadSizes(key: string, fallback: number[]): number[] {
  try {
    const raw = localStorage.getItem(key)
    if (raw) return JSON.parse(raw) as number[]
  } catch { /* D-06: silent fallback — no error shown */ }
  return fallback
}
```

**PanelGroup layout pattern** (from RESEARCH.md §Pattern 1):
```typescript
return (
  <div style={{ display: 'flex', flexDirection: 'column', height: '100vh',
                backgroundColor: '#000000', color: '#d1d4dc', overflow: 'hidden' }}>
    <DegradationBanner />
    {/* 48px header — same structure as current page.tsx lines 128–197 */}
    <header style={{ height: '48px', flexShrink: 0, ... }}>...</header>

    {/* Terminal body — fills remaining height */}
    <PanelGroup
      direction="horizontal"
      onLayout={(sizes) => localStorage.setItem(`${LAYOUT_KEY}-h`, JSON.stringify(sizes))}
      style={{ flex: 1, overflow: 'hidden' }}
    >
      <Panel defaultSize={60} style={{ minWidth: '400px' }}>
        <PaneContainer label="CHART">
          <Chart bars={stableBars} orbHigh={orbHigh} orbLow={orbLow} trades={stableTrades} />
        </PaneContainer>
      </Panel>
      <PanelResizeHandle style={{ width: '4px', backgroundColor: '#222222', cursor: 'col-resize' }} />
      <Panel defaultSize={40}>
        <PanelGroup direction="vertical" onLayout={(sizes) => localStorage.setItem(`${LAYOUT_KEY}-v`, JSON.stringify(sizes))}>
          <Panel defaultSize={30} style={{ minHeight: '120px' }}>
            <PaneContainer label="BLOTTER"><BlotterPane /></PaneContainer>
          </Panel>
          <PanelResizeHandle style={{ height: '4px', backgroundColor: '#222222', cursor: 'row-resize' }} />
          <Panel defaultSize={40} style={{ minHeight: '150px' }}>
            <PaneContainer label="HISTORY"><TradeHistoryPane runId={latestRunId} /></PaneContainer>
          </Panel>
          <PanelResizeHandle style={{ height: '4px', backgroundColor: '#222222', cursor: 'row-resize' }} />
          <Panel defaultSize={30} style={{ minHeight: '100px' }}>
            <PaneContainer label="CONTROLS"><StrategyControlsPane /></PaneContainer>
          </Panel>
        </PanelGroup>
      </Panel>
    </PanelGroup>
  </div>
)
```

**ORB computation to migrate** (current page.tsx lines 33–82 — move into a separate `utils/computeORB.ts` or keep inline):
The `computeORB` function is pure (no side effects). Move to `apps/web/lib/computeORB.ts` so BlotterPane and Chart can share it without prop drilling.

---

### `apps/web/components/PaneContainer.tsx` (component, —) — NEW

**Analog:** `apps/web/app/dashboard/blotter/page.tsx` — header section (lines 526–572)

**Full component pattern** (copy header structure, reduce to 28px, add title + optional right slot):
```typescript
'use client'

interface PaneContainerProps {
  label: string                       // 'CHART' | 'BLOTTER' | 'HISTORY' | 'CONTROLS'
  rightSlot?: React.ReactNode         // e.g. AuthorTVAlertButton + engine badge
  children: React.ReactNode
}

export default function PaneContainer({ label, rightSlot, children }: PaneContainerProps) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%',
                  backgroundColor: '#000000', overflow: 'hidden' }}>
      {/* 28px title bar — D-05 */}
      <div style={{
        height: '28px',
        flexShrink: 0,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '0 8px',
        borderBottom: '1px solid #222222',
        backgroundColor: '#0a0a0a',
      }}>
        <span style={{ fontSize: '11px', fontFamily: 'monospace',
                       color: '#888888', letterSpacing: '0.08em' }}>
          {label}
        </span>
        {rightSlot && <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>{rightSlot}</div>}
      </div>
      {/* Content fills remaining height */}
      <div style={{ flex: 1, overflow: 'hidden', minHeight: 0 }}>
        {children}
      </div>
    </div>
  )
}
```

**Color reference** (from blotter/page.tsx lines 526–572):
- Title bar background: `#0a0a0a` (slightly lighter than `#000000` to distinguish from content)
- Border: `#222222`
- Label text: `#888888` (muted), 11px monospace
- Hover on resize handle: `#3a3a3a` — applied via CSS or inline `onMouseEnter`/`onMouseLeave`

---

### `apps/web/components/BlotterPane.tsx` (component, request-response) — NEW

**Analog:** `apps/web/app/dashboard/blotter/page.tsx` (lines 407–905, the full `BlotterPage` component)

**Imports pattern** (lines 16–25 of blotter/page.tsx — copy verbatim, strip `Link`):
```typescript
'use client'

import { useState, useEffect, useRef, useCallback } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useStream } from '@/hooks/useStream'
import { useHotkeys, HOTKEY_REGISTRY } from '@/hooks/useHotkeys'
import { useWsStore } from '@/store/ws'
import AuthorTVAlertButton from '@/components/AuthorTVAlertButton'
import ConfirmationDialog from '@/components/ConfirmationDialog'   // extracted
import HelpOverlay from '@/components/HelpOverlay'                  // extracted
import { API_BASE } from '@/lib/api'
```

**Core state + query pattern** (blotter/page.tsx lines 412–446):
```typescript
// useStream() is called in the parent dashboard; BlotterPane does NOT call it again.
// Use Zustand only for cross-pane state.
const engineState = useWsStore((s) => s.engineState)
const positions = useWsStore((s) => s.positions)   // Phase 7: positions now in Zustand

// 1s polling fallback for when WS is disconnected
const { isError } = useQuery<PositionsResponse>({
  queryKey: ['positions'],
  queryFn: () => fetch(`${API_BASE}/positions`).then((r) => r.json()),
  refetchInterval: 1000,
})
```

**Action handler pattern** (blotter/page.tsx lines 449–511 — stable useCallback refs):
```typescript
const handleFlatten = useCallback(() => { if (!killOpen) setFlattenOpen(true) }, [killOpen])
const handleKill    = useCallback(() => { if (!flattenOpen) setKillOpen(true) }, [flattenOpen])
const handlePause   = useCallback(async () => {
  const res = await fetch(`${API_BASE}/pause`, { method: 'POST' })
  if (res.ok) setEngineState((await res.json()).state)
}, [setEngineState])
```

**Positions table pattern** (blotter/page.tsx lines 641–789 — copy column set, PnL math):
- Columns: Symbol | Side | Qty | Avg Fill | Mark | Unreal P&L | Stop Dist $ | Stop Dist ticks | Target Dist | Time In
- PnL color: `pnl > 0 ? '#4ade80' : pnl < 0 ? '#f87171' : '#888888'`
- Side color: `pos.side === 'long' ? '#4ade80' : '#f87171'`
- Row height: `36px`, background `#111111`, border-bottom `#1a1a2e`
- `className="tabular-nums"` on all numeric cells

**Controls row pattern** (blotter/page.tsx lines 793–865 — copy button styles):
```typescript
// Flatten button
style={{ border: '1px solid #ef4444', color: '#ef4444', backgroundColor: 'transparent',
         fontSize: '12px', fontFamily: 'monospace', padding: '4px 12px',
         borderRadius: '4px', cursor: 'pointer' }}

// Kill button
style={{ border: '1px solid #dc2626', color: '#dc2626', ... }}

// Pause button — state-conditional styling
style={{
  border: engineState === 'paused' ? '1px solid #eab308' : '1px solid #444444',
  color: engineState === 'paused' ? '#eab308' : '#888888', ...
}}
```

**Title bar right slot** (from CONTEXT.md §Specific Ideas): Pass to PaneContainer's `rightSlot` prop:
```typescript
<PaneContainer
  label="BLOTTER"
  rightSlot={
    <>
      <EngineStateBadge state={engineState} />
      <AuthorTVAlertButton strategyId="orb" condition="ORB long entry" message="ORB alert" />
    </>
  }
>
```

---

### `apps/web/components/ConfirmationDialog.tsx` (extracted component) — NEW

**Analog:** `apps/web/app/dashboard/blotter/page.tsx` lines 128–298

Extract verbatim — this is already a clean reusable component. The only change is promoting it from an inline function to a named export in its own file.

**Full interface** (lines 112–126):
```typescript
interface ConfirmDialogProps {
  open: boolean; onClose: () => void; onConfirm: () => void
  title: string; titleColor: string; description: string; warning: string
  inputLabel: string; confirmString: string; confirmButtonText: string
  dismissButtonText: string; confirmBorderColor: string; inputErrorBorderColor: string
}
```
Key patterns to preserve:
- `useEffect` for auto-focus + Escape/Enter keyboard handling (lines 147–165)
- Backdrop click closes: `onClick={(e) => { if (e.target === e.currentTarget) onClose() }}` (line 184)
- Confirm button disabled when `value !== confirmString` (lines 274–294)
- Input border turns error color when `value.length > 0 && !isConfirmable` (line 171)

---

### `apps/web/components/HelpOverlay.tsx` (extracted component) — NEW

**Analog:** `apps/web/app/dashboard/blotter/page.tsx` lines 304–401

Extract verbatim. Props: `{ open: boolean; onClose: () => void }`.

Key patterns:
- `HOTKEY_REGISTRY` import — iterates entries to build the shortcut table (lines 355–385)
- Escape closes: `useEffect` + `window.addEventListener('keydown', ...)` (lines 305–313)
- Backdrop click closes: same `onClick` guard pattern (line 327)
- Z-index: `9998` (one below ConfirmationDialog's `9999`)

---

### `apps/web/components/TradeHistoryPane.tsx` (component, request-response) — NEW

**Analog 1 (chart):** `apps/web/components/EquityCurve.tsx` (lines 1–127) — equity chart lifecycle
**Analog 2 (table):** `apps/web/app/dashboard/blotter/page.tsx` (lines 641–789) — table row pattern

**Imports pattern** (extend EquityCurve.tsx lines 13–19):
```typescript
'use client'

import { useEffect, useRef, useState, useCallback } from 'react'
import {
  createChart, LineSeries, HistogramSeries,
  type IChartApi, type Time,
} from 'lightweight-charts'
import { useWsStore } from '@/store/ws'
import { useBacktests, useEquityCurve, useEquityTrades } from '@/hooks/useBacktests'
import type { EquityPoint, TradeRow } from '@/lib/api'
```

**Chart lifecycle pattern** (EquityCurve.tsx lines 49–119 — COPY, add HistogramSeries + chartRef):
```typescript
const containerRef = useRef<HTMLDivElement>(null)
const chartRef = useRef<IChartApi | null>(null)   // NEW: needed for resize guard

useEffect(() => {
  if (!containerRef.current || points.length === 0) return
  const container = containerRef.current
  const { width: rectW, height: rectH } = container.getBoundingClientRect()
  const chart: IChartApi = createChart(container, {
    width: rectW || container.clientWidth || 800,
    height: rectH || container.clientHeight || 200,
    layout: { background: { color: '#000000' }, textColor: '#d1d4dc' },
    localization: { timeFormatter: etTimeFormatter },
    timeScale: { tickMarkFormatter: etTickFormatter, timeVisible: true, secondsVisible: false },
    grid: { vertLines: { color: '#1a1a2e' }, horzLines: { color: '#1a1a2e' } },
  })
  chartRef.current = chart

  const startEquity = points[0]?.equity ?? 0

  // Equity line (keep #2962FF from EquityCurve.tsx line 82)
  const equitySeries = chart.addSeries(LineSeries, { color: '#2962FF', lineWidth: 2, title: 'PnL $' })

  // DD histogram — REPLACES the secondary LineSeries in EquityCurve.tsx (lines 88–93)
  const ddSeries = chart.addSeries(HistogramSeries, {
    color: 'rgba(239, 68, 68, 0.5)',   // #ef4444 at 50% per D-11
    priceScaleId: 'right',
    title: 'DD $',
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
      value: -Math.abs(p.drawdown),       // negative so bars render below zero
      color: 'rgba(239, 68, 68, 0.5)',    // per-bar color for Pitfall 7 guard
    }))
  )
  chart.timeScale().fitContent()

  const resizeObserver = new ResizeObserver((entries) => {
    const { width, height } = entries[0].contentRect
    if (width > 0 && height > 0) chart.applyOptions({ width, height })
  })
  resizeObserver.observe(container)

  return () => {
    resizeObserver.disconnect()
    chartRef.current = null
    chart.remove()
  }
}, [points])
```

**Trade table pattern** (from blotter/page.tsx lines 641–789, adapted for TradeRow columns):
- Column set: Side | Entry | Exit | Gross PnL | Slippage $ | MAE | MFE | Hold bars | Exit Reason
- Click row → `setFocusedBarTs(trade.entry_ts_utc)` (D-12)
- PnL color: same token `pnl > 0 ? '#4ade80' : pnl < 0 ? '#f87171' : '#888888'`
- Side color: `trade.side === 'long' ? '#4ade80' : '#f87171'`
- Slippage $ derivation (D-13): `trade.slippage_ticks * (pointValue / 4) * trade.size`

**focusedBarTs integration** (from RESEARCH.md §Code Examples):
```typescript
const setFocusedBarTs = useWsStore((s) => s.setFocusedBarTs)
// On trade row click:
onClick={() => setFocusedBarTs(trade.entry_ts_utc)}
// Cursor: pointer on rows
style={{ cursor: 'pointer', ... }}
```

---

### `apps/web/components/StrategyControlsPane.tsx` (component, request-response) — NEW

**Analog:** `apps/web/app/dashboard/blotter/page.tsx` — controls row (lines 793–865) for button patterns; `apps/web/hooks/useBacktests.ts` for TanStack Query pattern

**Imports pattern**:
```typescript
'use client'

import { useState, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useStrategies } from '@/hooks/useBacktests'   // added in Phase 7
import { API_BASE } from '@/lib/api'
import type { StrategyInfo } from '@/lib/api'
```

**Strategy list + form pattern** (no direct analog — follow blotter button style):
```typescript
// Each strategy rendered as a row:
// [toggle switch] [strategy name] [enabled badge] [Save & Hot-reload button]
// Below: one labeled input per param key from strategy.params

// Toggle button style (on/off, follows pause button pattern from blotter, line 847–860):
style={{
  border: strategy.enabled ? '1px solid #4ade80' : '1px solid #444444',
  color: strategy.enabled ? '#4ade80' : '#888888',
  backgroundColor: 'transparent',
  fontSize: '12px', fontFamily: 'monospace', padding: '4px 12px',
  borderRadius: '4px', cursor: 'pointer',
}}

// 422 error display (D-16) — inline below the field:
{fieldError && (
  <div style={{ fontSize: '11px', color: '#ef4444', marginTop: '4px', fontFamily: 'monospace' }}>
    {fieldError}
  </div>
)}
```

**Background backtest pattern** (from RESEARCH.md §Pattern 7):
```typescript
const queryClient = useQueryClient()
const [runId, setRunId] = useState<string | null>(null)
const { data: runStatus } = useStrategyRun(runId)   // polls every 2s while pending

const handleRunBacktest = useCallback(async () => {
  const res = await fetch(`${API_BASE}/backtests/run`, { method: 'POST' })
  if (res.ok) {
    const { run_id } = await res.json() as { run_id: string }
    setRunId(run_id)
  }
}, [])

// When run completes:
useEffect(() => {
  if (runStatus && (runStatus as BacktestRow & { status?: string }).status === 'complete') {
    queryClient.invalidateQueries({ queryKey: ['backtests'] })
    setRunId(null)
  }
}, [runStatus, queryClient])
```

---

### `apps/web/e2e/playwright.config.ts` (config) — NEW

**Analog:** `apps/web/vitest.config.ts` (pattern: TypeScript config file exporting a config object)

No direct Playwright analog in the codebase. Use standard Playwright scaffold:
```typescript
import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  use: {
    baseURL: 'http://localhost:3000',
    headless: true,
  },
  webServer: {
    command: 'pnpm dev',
    url: 'http://localhost:3000',
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
})
```

---

### `apps/web/e2e/ws-reconnect.spec.ts` (test, event-driven) — NEW

**No direct analog.** Follow Playwright test structure. Key behaviors to test per D-21:
1. Connect to `/dashboard`, verify WS connected (green `ConnectionStatus`)
2. Use `page.route()` or `page.routeWebSocket()` to intercept and abort the WS connection
3. Wait for reconnect (yellow/red `ConnectionStatus` → back to green)
4. Assert no permanently stale data (trade table count matches API, positions load)

---

### `packages/api/src/api/routes/strategies.py` (route, request-response) — NEW

**Analog:** `packages/api/src/api/routes/risk.py` (entire file) — exact structural match

**Imports pattern** (risk.py lines 21–37 — copy structure):
```python
from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated

import yaml
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, field_validator

from api.deps import get_bus, get_store
from trading_core.events.models import TOPIC_STRATEGY_RELOAD
from trading_core.logging import get_logger
from trading_core.storage.duckdb_store import DuckDBStore
from trading_core.storage.runs import new_run_id
from trading_core.strategy.orb import ORBConfig

router = APIRouter()
_log = get_logger(__name__)

# Path-traversal guard (from backtests.py _find_repo_root pattern, lines 28–46)
_STRATEGY_ID_RE = re.compile(r'^[a-z0-9_-]+$')  # security: T-07 path guard
```

**GET /strategies pattern** (follow risk.py GET /positions structure, lines 69–102):
```python
@router.get("/strategies")
async def get_strategies(request: Request) -> list[dict]:
    store: DuckDBStore = get_store(request)
    _repo_root = _find_repo_root(Path(__file__).resolve())
    strategies_dir = _repo_root / "config" / "strategies"
    result = []
    for yaml_path in sorted(strategies_dir.glob("*.yaml")):
        with yaml_path.open() as f:
            data = yaml.safe_load(f) or {}
        strategy_id = data.get("strategy_id", yaml_path.stem)
        # Per-strategy enabled state from engine_state table (D-17 / Phase 5 precedent)
        enabled = store.get_strategy_enabled(strategy_id)   # new DuckDBStore method
        result.append({
            "strategy_id": strategy_id,
            "name": data.get("name", strategy_id),
            "params": data.get("params", {}),
            "enabled": enabled,
        })
    _log.info("strategies.listed", count=len(result))
    return result
```

**PUT /strategies/{id}/params pattern** (follow risk.py POST /kill lines 110–156 for audit + EventBus):
```python
@router.put("/strategies/{strategy_id}/params")
async def put_strategy_params(
    strategy_id: str, body: ORBConfigUpdate, request: Request
) -> dict:
    # Security: path traversal guard (T-07)
    if not _STRATEGY_ID_RE.match(strategy_id):
        raise HTTPException(400, "invalid strategy_id")
    _repo_root = _find_repo_root(Path(__file__).resolve())
    yaml_path = (_repo_root / "config" / "strategies" / f"{strategy_id}.yaml").resolve()
    try:
        yaml_path.relative_to(_repo_root / "config" / "strategies")
    except ValueError:
        raise HTTPException(403, "forbidden strategy path")

    # Step 1: Pydantic validation already happened (body is ORBConfigUpdate — 422 on failure)
    # Step 2: Read current YAML, merge params
    with yaml_path.open() as f:
        current = yaml.safe_load(f) or {}
    current["params"] = body.model_dump(exclude_none=True)
    with yaml_path.open("w") as f:
        yaml.dump(current, f, default_flow_style=False)

    # Step 3: publish TOPIC_STRATEGY_RELOAD (D-14)
    bus = get_bus(request)
    await bus.publish(TOPIC_STRATEGY_RELOAD, {
        "type": "strategy_reload",
        "payload": {"strategy_id": strategy_id, "params": current["params"]},
    })
    _log.info("strategy.params_updated", strategy_id=strategy_id)
    return {"strategy_id": strategy_id, "params": current["params"]}
```

**POST /backtests/run pattern** (tv.py lines 101–120, asyncio.create_task precedent):
```python
@router.post("/backtests/run", status_code=202)
async def post_run_backtest(request: Request) -> dict:
    run_id = new_run_id()
    store = get_store(request)
    # Mark pending immediately (new status column in backtests table)
    store.write_pending_backtest(run_id)
    # Non-blocking (tv.py pattern, line 115)
    asyncio.create_task(
        _run_backtest_task(run_id, request.app.state),
        name=f"backtest_{run_id}",
    )
    _log.info("backtest.started", run_id=run_id)
    return {"run_id": run_id}
```

---

### `apps/web/next.config.ts` (config) — MODIFY

**Analog:** `apps/web/next.config.ts` (itself, lines 1–7)

**Current file** (lines 1–7):
```typescript
import type { NextConfig } from "next";
const nextConfig: NextConfig = { /* config options here */ };
export default nextConfig;
```

**Add redirects (Pitfall 6 guard — must be async function)**:
```typescript
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async redirects() {
    return [
      {
        source: '/dashboard/blotter',
        destination: '/dashboard',
        permanent: true,
      },
    ]
  },
}

export default nextConfig;
```

---

### `apps/web/hooks/useStream.ts` (hook, event-driven) — MODIFY

**Analog:** `apps/web/hooks/useStream.ts` (itself, lines 1–81)

**Current structure** (lines 19–80):
- Single `useEffect` with bare `new WebSocket(...)` (line 27)
- No reconnect logic
- `ws.onclose = () => setConnected(false)` (line 33)
- TODO comment at line 72 marks where Phase 7 routing goes

**Backoff reconnect additions** (replace useEffect body, from RESEARCH.md §Pattern 4):
```typescript
import { useEffect, useRef } from 'react'
import { useQueryClient } from '@tanstack/react-query'
// ... existing store imports ...

const MAX_BACKOFF_MS = 30_000

export function useStream() {
  const setConnected = useWsStore((s) => s.setConnected)
  const setLastBarAt  = useWsStore((s) => s.setLastBarAt)
  const setDegraded   = useWsStore((s) => s.setDegraded)
  const setEngineState = useWsStore((s) => s.setEngineState)
  const setPositions  = useWsStore((s) => s.setPositions)
  const setLastSeq    = useWsStore((s) => s.setLastSeq)    // new
  const lastSeqRef    = useRef<number | null>(null)
  const queryClient   = useQueryClient()

  useEffect(() => {
    let attempt = 0
    let ws: WebSocket | null = null
    let timerId: ReturnType<typeof setTimeout> | null = null
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
          timerId = setTimeout(connect, delay)
        }
      }
      ws.onerror = () => { setConnected(false) }
      ws.onmessage = (event: MessageEvent) => {
        let msg: { type: string; payload: Record<string, unknown>; seq?: number }
        try {
          msg = JSON.parse(event.data as string)
        } catch { return }

        // Gap detection (D-19)
        const incomingSeq = msg.seq ?? null
        if (incomingSeq !== null && lastSeqRef.current !== null
            && incomingSeq > lastSeqRef.current + 1) {
          // Gap detected — resync via TanStack Query (D-20)
          void queryClient.invalidateQueries({ queryKey: ['positions'] })
          void queryClient.invalidateQueries({ queryKey: ['backtests'] })
        }
        if (incomingSeq !== null) {
          lastSeqRef.current = incomingSeq
          setLastSeq(incomingSeq)
        }

        // Message routing (existing switch from lines 53–73 — keep all cases)
        switch (msg.type) { ... }
      }
    }

    connect()
    return () => {
      stopped = true
      if (timerId !== null) clearTimeout(timerId)
      ws?.close()
    }
  }, [setConnected, setLastBarAt, setDegraded, setEngineState, setPositions, setLastSeq, queryClient])
}
```

---

### `apps/web/store/ws.ts` (store) — MODIFY

**Analog:** `apps/web/store/ws.ts` (itself, lines 1–88)

**Current state interface** (lines 24–31):
```typescript
export interface WsState {
  connected: boolean; lastBarAt: number | null; degraded: DegradedState | null
  engineState: 'running' | 'paused' | 'killed'; positions: Position[]
}
```

**Add to WsState** (after `positions: Position[]`):
```typescript
focusedBarTs: string | null
lastSeq: number | null
```

**Add to WsActions** (after `setPositions`):
```typescript
setFocusedBarTs: (ts: string | null) => void
setLastSeq: (seq: number) => void
```

**Add to create() initializer** (after `positions: []`):
```typescript
focusedBarTs: null,
lastSeq: null,
setFocusedBarTs: (ts) => set({ focusedBarTs: ts }),
setLastSeq: (seq) => set({ lastSeq: seq }),
```

---

### `apps/web/hooks/useBacktests.ts` (hook, request-response) — MODIFY

**Analog:** `apps/web/hooks/useBacktests.ts` (itself, lines 1–65)

**Existing pattern** (lines 9–23 — copy structure for new hooks):
```typescript
export function useBacktests() {
  return useQuery<BacktestRow[]>({
    queryKey: ['backtests'],
    queryFn: async () => {
      const res = await fetch(`${API_BASE}/backtests`)
      if (!res.ok) throw new Error(`GET /backtests failed: ${res.status} ${res.statusText}`)
      return res.json() as Promise<BacktestRow[]>
    },
    staleTime: 30_000,
  })
}
```

**New hooks to add** (from RESEARCH.md §Code Examples):
```typescript
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
  return useQuery<BacktestRow & { status?: 'pending' | 'complete' | 'failed' }>({
    queryKey: ['backtest_run', runId],
    queryFn: async () => {
      const res = await fetch(`${API_BASE}/backtests/${runId}`)
      if (!res.ok) throw new Error(`GET /backtests/${runId} failed: ${res.status}`)
      return res.json()
    },
    enabled: runId != null,
    // Poll every 2s while pending; stop when complete (D-15)
    refetchInterval: (query) => {
      return query.state.data?.status === 'pending' ? 2000 : false
    },
    staleTime: 0,
  })
}
```

---

### `apps/web/lib/api.ts` (utility) — MODIFY

**Analog:** `apps/web/lib/api.ts` (itself, lines 58–76 — existing TradeRow type shape)

**Add StrategyInfo** (after `TradeRow`, from RESEARCH.md §Code Examples):
```typescript
/** Shape of a strategy from GET /strategies */
export interface StrategyInfo {
  strategy_id: string
  name: string
  params: Record<string, number | string | boolean>
  enabled: boolean
}
```

---

### `apps/web/components/Chart.tsx` (component, request-response) — MODIFY

**Analog:** `apps/web/components/Chart.tsx` (itself, lines 71–220)

**Add chartRef** (after `seriesRef` at line 72):
```typescript
const chartRef = useRef<IChartApi | null>(null)
```

**Store chart in Effect 1** (add after `seriesRef.current = candleSeries` at line 151):
```typescript
chartRef.current = chart
```

**Clear chartRef in cleanup** (add before `chart.remove()` at line 165):
```typescript
chartRef.current = null
```

**Add Effect 3 — focusedBarTs scroll** (insert as a third `useEffect` after Effect 2, lines 169–212):
```typescript
// Effect 3: chart scroll-to-trade — watches focusedBarTs Zustand atom (D-12)
const focusedBarTs  = useWsStore((s) => s.focusedBarTs)
const setFocusedBarTs = useWsStore((s) => s.setFocusedBarTs)

useEffect(() => {
  if (!focusedBarTs || !seriesRef.current || !chartRef.current) return
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
  setFocusedBarTs(null)  // reset after scroll (D-12)
}, [focusedBarTs, bars, setFocusedBarTs])
```

**New imports needed** (add to existing import block at line 17):
```typescript
import { useWsStore } from '@/store/ws'
```

---

### `apps/web/components/EquityCurve.tsx` (component) — MODIFY (migration to TradeHistoryPane)

**Analog:** `apps/web/components/EquityCurve.tsx` (itself, lines 1–127)

The standalone `EquityCurve` component is kept as-is for now (it may still be importable from other pages). The DD overlay pattern is applied in `TradeHistoryPane.tsx` using `HistogramSeries` instead of the current secondary `LineSeries` (lines 88–93 of EquityCurve.tsx).

If the component is to be merged (the dashboard no longer instantiates it directly), keep the file but rename to mark its legacy status, or leave it for the optimizations page.

---

### `apps/web/hooks/useHotkeys.ts` (hook, event-driven) — MODIFY

**Analog:** `apps/web/hooks/useHotkeys.ts` (itself, lines 25–97)

**Current registry** (lines 25–30):
```typescript
export const HOTKEY_REGISTRY: HotkeyEntry[] = [
  { key: 'f', description: 'Flatten all open positions' },
  { key: 'k', description: 'Kill switch — halt signal processing' },
  { key: 'p', description: 'Pause / resume active strategy' },
  { key: '?', description: 'Show this help overlay' },
]
```

Phase 7 adds new hotkeys to this array (no new key collisions allowed — the collision detector at lines 33–36 throws at startup if duplicates are found). The `HotkeyHandlers` interface and `useHotkeys` hook body must also be extended for each new key.

---

### `packages/api/src/api/app.py` (config, event-driven) — MODIFY

**Analog:** `packages/api/src/api/app.py` (itself, lines 86–229 lifespan block)

**Add strategies router import** (after `from api.routes import tv as tv_routes` at line 63):
```python
from api.routes import strategies as strategies_routes
```

**Register router** (after `app.include_router(tv_routes.router)` at line 308):
```python
app.include_router(strategies_routes.router)
```

**Add PUT to CORS allow_methods** (line 299 — add `"PUT"`):
```python
allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
```

**Add TOPIC_STRATEGY_RELOAD subscriber in lifespan** (after TVBridge startup, ~line 182):
```python
# Phase 7: TOPIC_STRATEGY_RELOAD subscriber — hot-reload engine strategy (D-14)
from trading_core.events.models import TOPIC_STRATEGY_RELOAD  # noqa: PLC0415
from trading_core.strategy.registry import StrategyRegistry  # noqa: PLC0415

async def _strategy_reload_handler() -> None:
    """Subscribe to TOPIC_STRATEGY_RELOAD and swap in-memory Strategy instance."""
    async with app.state.bus.subscribe(TOPIC_STRATEGY_RELOAD) as sub:
        async for event in sub:
            if isinstance(event, dict):
                payload = event.get("payload", event)
            else:
                payload = event
            strategy_id = payload.get("strategy_id", "")
            _log.info("strategy.hot_reload_received", strategy_id=strategy_id)
            _repo_root2 = _find_repo_root(Path(__file__).resolve())
            yaml_path = _repo_root2 / "config" / "strategies" / f"{strategy_id}.yaml"
            if yaml_path.exists():
                new_strategy = StrategyRegistry.load(yaml_path)
                # Store on app.state for engine to pick up
                if not hasattr(app.state, "strategies"):
                    app.state.strategies = {}
                app.state.strategies[strategy_id] = new_strategy
                _log.info("strategy.hot_reloaded", strategy_id=strategy_id)

app.state.strategy_reload_task = asyncio.create_task(
    _strategy_reload_handler(), name="strategy_reload_handler"
)
```

**Shutdown** (add before `app.state.fan_out_task.cancel()` ~line 256):
```python
app.state.strategy_reload_task.cancel()
try:
    await app.state.strategy_reload_task
except asyncio.CancelledError:
    pass
```

---

### `packages/api/src/api/routes/backtests.py` (route, CRUD) — MODIFY

**Analog:** `packages/api/src/api/routes/backtests.py` (itself, lines 83–118 for GET /backtests pattern)

**Add GET /backtests/{run_id}** (new endpoint, follows same DuckDB query pattern as `get_backtests`):
```python
@router.get("/backtests/{run_id}")
def get_backtest(
    run_id: str,
    store: Annotated[DuckDBStore, Depends(get_store)] = ...,
) -> dict:
    """Return a single backtest run row with status field."""
    row = store._conn.execute(
        "SELECT " + ", ".join(_COLUMNS) + ", status "
        "FROM backtests WHERE run_id = ?",
        [run_id],
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="backtest not found")
    # ... same col normalization as get_backtests lines 97–116 ...
    record = {}
    for col, val in zip(_COLUMNS + ["status"], row):
        ...  # normalize timestamps + floats
    return record
```

Note: The `backtests` table needs a new `status` column (`VARCHAR DEFAULT 'complete'`). `POST /backtests/run` inserts with `status='pending'`; the background task updates to `'complete'` or `'failed'`.

---

### `packages/trading-core/src/trading_core/events/models.py` (model) — MODIFY

**Analog:** `packages/trading-core/src/trading_core/events/models.py` (itself, lines 24–33)

**Add after TOPIC_ENGINE_STATE** (line 33):
```python
# Phase 7: Strategy hot-reload event (D-14 / UI-07).
TOPIC_STRATEGY_RELOAD: Final[str] = "strategy_reload"
```

---

### `packages/trading-core/src/trading_core/strategy/registry.py` (service) — MODIFY

**Analog:** `packages/trading-core/src/trading_core/strategy/registry.py` (itself, lines 39–84)

**Add `reload` static method** (after `list_strategies`, line 84):
```python
@staticmethod
def reload(strategy_id: str, strategies_dir: str | Path) -> ORBStrategy:
    """Reload a strategy from its YAML file (called on TOPIC_STRATEGY_RELOAD).

    Args:
        strategy_id: The strategy identifier (e.g. 'orb-v1' or YAML stem).
        strategies_dir: Directory containing *.yaml strategy configs.

    Returns:
        A fresh ORBStrategy instance from the current YAML state.

    Raises:
        FileNotFoundError: if no YAML with matching strategy_id is found.
    """
    d = Path(strategies_dir)
    # Try exact stem match first, then scan for strategy_id field match
    yaml_path = d / f"{strategy_id}.yaml"
    if not yaml_path.exists():
        for p in sorted(d.glob("*.yaml")):
            with p.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if data and data.get("strategy_id") == strategy_id:
                yaml_path = p
                break
    return StrategyRegistry.load(yaml_path)
```

---

### `config/strategies/orb.yaml` (config) — MODIFY (written by API)

**Analog:** `config/strategies/orb.yaml` (itself, lines 1–13)

This file is written by `PUT /strategies/orb/params`. The structure is preserved; only the `params:` block values change. The Pydantic model `ORBConfig` in `trading_core/strategy/orb.py` is the schema that validates before write.

Current params block (lines 7–13):
```yaml
params:
  opening_range_minutes: 15
  atr_period: 14
  atr_stop_mult: 1.5
  r_target: 2.0
  ema_period: 20
  min_range_ticks: 2
```

---

## Shared Patterns

### Dark Color Palette
**Source:** `apps/web/app/dashboard/blotter/page.tsx` (consistent across all Phase 3–6 files)
**Apply to:** All new pane components
```typescript
// Background hierarchy:
backgroundColor: '#000000'   // page root
backgroundColor: '#0a0a0a'   // title bars (28px)
backgroundColor: '#111111'   // table rows, dialog boxes

// Borders:
borderColor: '#222222'       // primary dividers
borderColor: '#333333'       // dialog inner borders
borderColor: '#1a1a2e'       // table row separators

// Text:
color: '#d1d4dc'             // primary text
color: '#888888'             // muted/secondary text
color: '#555555'             // placeholder/disabled

// Semantic colors (05-UI-SPEC.md):
color: '#4ade80'             // positive PnL, long, running engine
color: '#eab308'             // paused engine, warning
color: '#ef4444'             // negative PnL, killed engine
color: '#f87171'             // error text (lighter red)
color: '#dc2626'             // kill switch (darker red)
color: '#4a90d9'             // links, accent
```

### `'use client'` + Inline Styles Rule
**Source:** Every component in `apps/web/components/` and `apps/web/app/dashboard/`
**Apply to:** All new frontend files
- All interactive components start with `'use client'` as the first line
- Layout uses `style={{ ... }}` props (inline styles), not Tailwind CSS classes
- Typography utilities (`font-mono`, `tabular-nums`) use Tailwind className
- `fontFamily: 'monospace'` in inline styles for all data display text

### EventBus Pub/Sub (Server-Side)
**Source:** `packages/api/src/api/routes/risk.py` lines 148–152; `packages/api/src/api/ws.py` lines 87–108
**Apply to:** `strategies.py` all mutating routes
```python
# Publish pattern (risk.py lines 148–153):
await bus.publish(
    TOPIC_ENGINE_STATE,
    {"type": "engine_state_changed", "payload": {"state": new_state}},
)
# For strategy reload (Phase 7):
await bus.publish(
    TOPIC_STRATEGY_RELOAD,
    {"type": "strategy_reload", "payload": {"strategy_id": sid, "params": {...}}},
)
```
Note from ws.py lines 94–97: plain dicts are forwarded as-is; they must already have the `{type, payload}` envelope from the publish site.

### DuckDB Store + audit_log Pattern
**Source:** `packages/api/src/api/routes/risk.py` lines 125–155
**Apply to:** `strategies.py` mutating routes
```python
# Always write engine_state or a domain-specific state record before publishing
store.write_engine_state(session_id=sid, state=new_state)
# Then write audit record
store.write_audit_event(
    event_id=new_run_id(),
    ts_utc=now_utc,
    topic="engine_state",
    entity_id=sid,
    reason_code="reason_code_here",
    payload_json=json.dumps({...}),
)
# Then set asyncio.Event (if applicable)
# Then publish EventBus
```

### TanStack Query Hook Pattern
**Source:** `apps/web/hooks/useBacktests.ts` lines 9–23
**Apply to:** `useStrategies()` and `useStrategyRun()` in `useBacktests.ts`
```typescript
return useQuery<T[]>({
  queryKey: ['key'],
  queryFn: async () => {
    const res = await fetch(`${API_BASE}/endpoint`)
    if (!res.ok) throw new Error(`GET /endpoint failed: ${res.status} ${res.statusText}`)
    return res.json() as Promise<T[]>
  },
  staleTime: N,
})
```

### asyncio.create_task for Non-Blocking Routes
**Source:** `packages/api/src/api/routes/tv.py` lines 101–120
**Apply to:** `POST /backtests/run` in `strategies.py`
```python
asyncio.create_task(
    some_coroutine(arg1, arg2),
    name="descriptive_task_name",
)
return {"status": "accepted", ...}  # HTTP 202
```

### Path-Traversal Guard
**Source:** `packages/api/src/api/routes/backtests.py` lines 28–46, 148–166
**Apply to:** `PUT /strategies/{id}/params` in `strategies.py`
```python
# Validate ID format
if not re.match(r'^[a-z0-9_-]+$', strategy_id):
    raise HTTPException(400, "invalid strategy_id")
# Resolve and verify path stays within allowed root
yaml_path = (strategies_root / f"{strategy_id}.yaml").resolve()
try:
    yaml_path.relative_to(strategies_root.resolve())
except ValueError:
    raise HTTPException(403, "forbidden strategy path")
```

### Zustand Store Extension
**Source:** `apps/web/store/ws.ts` lines 24–68
**Apply to:** `focusedBarTs` and `lastSeq` additions
Pattern: extend `WsState` interface + `WsActions` interface + `create()` initializer in lockstep. Never add state without a corresponding setter action.

---

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `apps/web/e2e/ws-reconnect.spec.ts` | test | event-driven | No Playwright tests exist in the codebase; no WS-specific test precedent |

---

## Metadata

**Analog search scope:** `apps/web/`, `packages/api/src/api/`, `packages/trading-core/src/trading_core/`
**Files scanned:** 17 source files read directly
**Pattern extraction date:** 2026-05-20

**Critical implementation notes for planner:**
1. `useStream` must call `useQueryClient()` at the top level of the hook (it's a React hook) and store the result in a ref to use inside the `onmessage` callback (Pitfall 4).
2. `react-resizable-panels` `minSize` prop is in percentage points, not pixels. Use `style={{ minWidth: '400px' }}` on the panel content div instead (Pitfall 1).
3. Chart.tsx Effect 1, Effect 2, and the new Effect 3 must each be separate `useEffect` calls. Do not merge them — the two-effect split prevents `chart.remove()` on trades-query updates (Pitfall 2).
4. The `backtests` table needs a `status VARCHAR DEFAULT 'complete'` column added via `DuckDBStore.ensure_schema()` migration for `useStrategyRun` polling to work.
5. `HistogramSeries` color must be set both in `addSeries` options AND per data point (Pitfall 7).
6. The `ConfirmationDialog` and `HelpOverlay` components must be extracted to `apps/web/components/` BEFORE the `blotter/` directory is deleted.
