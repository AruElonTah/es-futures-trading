'use client'

/**
 * /dashboard — Phase 3 minimal trading dashboard (UI-01 + UI-04 + UI-08).
 *
 * Two-pane layout (D-08):
 *  - Top ~70%: Candlestick chart with ORB box overlay + entry/stop/target markers
 *  - Bottom ~30%: Equity curve from most-recent backtest
 *
 * Header: title | ET clock | connection status | Run Backtest (disabled)
 * DegradationBanner: appears when degraded_state WS event received
 *
 * ORB box derived client-side from the first 15 1m bars after 09:30 ET.
 * Entry markers + stop/target priceLines from GET /backtests/{run_id}/trades.
 *
 * Docs consulted:
 *  - apps/web/node_modules/next/dist/docs/01-app/03-api-reference/01-directives/use-client.md
 *  - apps/web/node_modules/next/dist/docs/01-app/02-guides/index.md
 */

import { useMemo } from 'react'
import { useStream } from '@/hooks/useStream'
import { useBars } from '@/hooks/useBars'
import { useBacktests, useEquityCurve, useEquityTrades } from '@/hooks/useBacktests'
import Chart from '@/components/Chart'
import EquityCurve from '@/components/EquityCurve'
import ETClock from '@/components/ETClock'
import ConnectionStatus from '@/components/ConnectionStatus'
import DegradationBanner from '@/components/DegradationBanner'
import type { BarRow } from '@/lib/api'

/** Opening range window: first 15 bars after 09:30 ET */
const ORB_MINUTES = 15

/**
 * Derive ORB high/low from the bars array.
 * Identifies the first RTH session (09:30 ET = 14:30 UTC for EDT, 15:30 for EST).
 * Returns the high/low of the first ORB_MINUTES bars after session open.
 */
function computeORB(
  bars: BarRow[]
): { orbHigh: number | undefined; orbLow: number | undefined } {
  if (bars.length === 0) return { orbHigh: undefined, orbLow: undefined }

  // API returns DESC; sort ASC so session-start scan works correctly
  const sorted = [...bars].sort(
    (a, b) => new Date(a.ts_utc).getTime() - new Date(b.ts_utc).getTime()
  )

  // Find bars in the first 09:30-09:44 ET window (first ORB_MINUTES bars of RTH)
  // We identify session start by finding the first bar at 09:30 ET
  const etFormatter = new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/New_York',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })

  // Find the first 09:30 bar
  let sessionStartIdx = -1
  for (let i = 0; i < sorted.length; i++) {
    const ts = new Date(sorted[i].ts_utc)
    const formatted = etFormatter.format(ts)
    if (formatted === '09:30') {
      sessionStartIdx = i
      break
    }
  }

  if (sessionStartIdx === -1) {
    sessionStartIdx = 0
  }

  const orbBars = sorted.slice(sessionStartIdx, sessionStartIdx + ORB_MINUTES)
  if (orbBars.length === 0) return { orbHigh: undefined, orbLow: undefined }

  const orbHigh = Math.max(...orbBars.map((b) => b.high))
  const orbLow = Math.min(...orbBars.map((b) => b.low))

  return { orbHigh, orbLow }
}

export default function DashboardPage() {
  // Mount WS subscription (side-effect only — no return value needed)
  useStream()

  // Fetch bars data
  const { data: bars } = useBars('SPY', '1m', 390)

  // Fetch most-recent backtest
  const { data: backtests } = useBacktests()
  const latestRunId = backtests?.[0]?.run_id ?? null

  // Fetch equity curve + trades for most-recent backtest
  const { data: equityPoints } = useEquityCurve(latestRunId)
  const { data: trades } = useEquityTrades(latestRunId)

  // Derive ORB overlay client-side from bars
  const { orbHigh, orbLow } = useMemo(
    () => computeORB(bars ?? []),
    [bars]
  )

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100vh',
        backgroundColor: '#000000',
        color: '#d1d4dc',
        overflow: 'hidden',
      }}
    >
      {/* Degradation banner — renders nothing when degraded is null */}
      <DegradationBanner />

      {/* Header */}
      <header
        style={{
          height: '48px',
          flexShrink: 0,
          display: 'flex',
          alignItems: 'center',
          gap: '16px',
          padding: '0 16px',
          borderBottom: '1px solid #222222',
        }}
      >
        <span
          className="font-mono text-sm font-bold"
          style={{ color: '#d1d4dc' }}
        >
          ES Futures Trading System
        </span>

        <ETClock />
        <ConnectionStatus />

        <button
          disabled
          style={{
            marginLeft: 'auto',
            backgroundColor: 'transparent',
            border: '1px solid #444',
            color: '#666',
            cursor: 'not-allowed',
            padding: '4px 12px',
            borderRadius: '4px',
            fontSize: '12px',
            fontFamily: 'monospace',
          }}
          title="Phase 7 — not yet implemented"
        >
          Run Backtest
        </button>
      </header>

      {/* Chart pane — 70% of remaining height after header (D-08) */}
      <div style={{ flex: '7 1 0', overflow: 'hidden', minHeight: 0 }}>
        <Chart
          bars={bars ?? []}
          orbHigh={orbHigh}
          orbLow={orbLow}
          trades={trades ?? []}
        />
      </div>

      {/* Equity curve pane — 30% of remaining height after header (D-08) */}
      <div style={{ flex: '3 1 0', overflow: 'hidden', minHeight: 0 }}>
        <EquityCurve points={equityPoints ?? []} />
      </div>
    </div>
  )
}
