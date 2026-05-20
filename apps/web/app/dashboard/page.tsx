'use client'

/**
 * /dashboard — Phase 7 4-pane terminal layout (UI-01 + UI-04 + UI-08 + D-03/D-06).
 *
 * Replaces the 2-pane layout with a resizable 4-pane terminal:
 *   - Left (60%): CHART pane — candlestick chart with ORB overlay
 *   - Right (40%) / Top (30%): BLOTTER pane — placeholder (Plan 07-03)
 *   - Right (40%) / Mid (40%): HISTORY pane — placeholder (Plan 07-03)
 *   - Right (40%) / Bot (30%): CONTROLS pane — placeholder (Plan 07-04)
 *
 * Layout persistence via localStorage (D-06): try/catch JSON.parse with
 * silent fallback to defaults.
 *
 * Blotter nav link removed (blotter is now a pane, not a route per Phase 7).
 * Run Backtest button removed from header (moves to StrategyControlsPane in Plan 07-04).
 *
 * Docs consulted:
 *  - apps/web/node_modules/next/dist/docs/01-app/03-api-reference/01-directives/use-client.md
 */

import { useMemo } from 'react'
import Link from 'next/link'
import { Panel, PanelGroup, PanelResizeHandle } from 'react-resizable-panels'
import { useStream } from '@/hooks/useStream'
import { useBars } from '@/hooks/useBars'
import { useBacktests, useEquityCurve, useEquityTrades } from '@/hooks/useBacktests'
import Chart from '@/components/Chart'
import ETClock from '@/components/ETClock'
import ConnectionStatus from '@/components/ConnectionStatus'
import DegradationBanner from '@/components/DegradationBanner'
import PaneContainer from '@/components/PaneContainer'
import type { BarRow } from '@/lib/api'

// ---------------------------------------------------------------------------
// Layout constants (D-03, D-06)
// ---------------------------------------------------------------------------

const LAYOUT_KEY_H = 'es-terminal-layout-h'
const LAYOUT_KEY_V = 'es-terminal-layout-v'
const DEFAULT_H_SIZES = [60, 40]
const DEFAULT_V_SIZES = [30, 40, 30]

/** Read persisted layout sizes from localStorage with silent fallback (D-06). */
function loadSizes(key: string, fallback: number[]): number[] {
  try {
    const raw = localStorage.getItem(key)
    if (raw) return JSON.parse(raw) as number[]
  } catch { /* D-06: silent fallback — no error shown */ }
  return fallback
}

// ---------------------------------------------------------------------------
// ORB computation (pure function — no side effects)
// ---------------------------------------------------------------------------

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

  const etFormatter = new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/New_York',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })

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

// ---------------------------------------------------------------------------
// Dashboard page — 4-pane TerminalLayout shell
// ---------------------------------------------------------------------------

export default function DashboardPage() {
  // Mount WS subscription (side-effect only — no return value needed)
  useStream()

  // Fetch bars data
  const { data: bars } = useBars('SPY', '1m', 390)

  // Fetch most-recent backtest
  const { data: backtests } = useBacktests()
  const latestRunId = backtests?.[0]?.run_id ?? null

  // Fetch equity curve + trades for most-recent backtest
  // (equityPoints unused in Plan 07-02 shell — wired to TradeHistoryPane in Plan 07-03)
  useEquityCurve(latestRunId)
  const { data: trades } = useEquityTrades(latestRunId)

  // Stable empty-array fallbacks — prevent new [] refs on every render while
  // queries are loading, which would cause Chart's effect to destroy/recreate
  // the canvas on every parent re-render.
  const stableBars = useMemo(() => bars ?? [], [bars])
  const stableTrades = useMemo(() => trades ?? [], [trades])

  // Derive ORB overlay client-side from bars
  const { orbHigh, orbLow } = useMemo(
    () => computeORB(stableBars),
    [stableBars]
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

      {/* Global header — 48px, unchanged from Phase 3 except: Blotter link removed, Run Backtest removed */}
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

        {/* Flex spacer — pushes nav links to the right */}
        <div style={{ flex: 1 }} />

        <Link
          href="/optimizations"
          style={{
            color: '#4a90d9',
            textDecoration: 'none',
            fontSize: '12px',
            fontFamily: 'monospace',
            padding: '4px 12px',
            border: '1px solid #2a5a8a',
            borderRadius: '4px',
          }}
        >
          Optimizations
        </Link>
      </header>

      {/* Terminal body — fills remaining height after header */}
      <PanelGroup
        direction="horizontal"
        onLayout={(sizes: number[]) =>
          localStorage.setItem(LAYOUT_KEY_H, JSON.stringify(sizes))
        }
        style={{ flex: 1, overflow: 'hidden' }}
      >
        {/* Left column: CHART pane (60% default) */}
        <Panel
          defaultSize={loadSizes(LAYOUT_KEY_H, DEFAULT_H_SIZES)[0]}
          style={{ minWidth: '400px' }}
        >
          <PaneContainer label="CHART">
            <Chart
              bars={stableBars}
              orbHigh={orbHigh}
              orbLow={orbLow}
              trades={stableTrades}
            />
          </PaneContainer>
        </Panel>

        <PanelResizeHandle
          style={{
            width: '4px',
            backgroundColor: '#222222',
            cursor: 'col-resize',
            flexShrink: 0,
          }}
          aria-label="Resize chart and side panels"
        />

        {/* Right column: BLOTTER / HISTORY / CONTROLS (40% default) */}
        <Panel defaultSize={loadSizes(LAYOUT_KEY_H, DEFAULT_H_SIZES)[1]}>
          <PanelGroup
            direction="vertical"
            onLayout={(sizes: number[]) =>
              localStorage.setItem(LAYOUT_KEY_V, JSON.stringify(sizes))
            }
          >
            {/* BLOTTER pane — placeholder until Plan 07-03 */}
            <Panel
              defaultSize={loadSizes(LAYOUT_KEY_V, DEFAULT_V_SIZES)[0]}
              style={{ minHeight: '120px' }}
            >
              <PaneContainer label="BLOTTER">
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    height: '100%',
                    backgroundColor: '#111111',
                    color: '#888888',
                    fontSize: '12px',
                    fontFamily: 'monospace',
                  }}
                >
                  Coming in Plan 07-03
                </div>
              </PaneContainer>
            </Panel>

            <PanelResizeHandle
              style={{
                height: '4px',
                backgroundColor: '#222222',
                cursor: 'row-resize',
                flexShrink: 0,
              }}
              aria-label="Resize blotter and history panels"
            />

            {/* HISTORY pane — placeholder until Plan 07-03 */}
            <Panel
              defaultSize={loadSizes(LAYOUT_KEY_V, DEFAULT_V_SIZES)[1]}
              style={{ minHeight: '152px' }}
            >
              <PaneContainer label="HISTORY">
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    height: '100%',
                    backgroundColor: '#111111',
                    color: '#888888',
                    fontSize: '12px',
                    fontFamily: 'monospace',
                  }}
                >
                  Coming in Plan 07-03
                </div>
              </PaneContainer>
            </Panel>

            <PanelResizeHandle
              style={{
                height: '4px',
                backgroundColor: '#222222',
                cursor: 'row-resize',
                flexShrink: 0,
              }}
              aria-label="Resize history and controls panels"
            />

            {/* CONTROLS pane — placeholder until Plan 07-04 */}
            <Panel
              defaultSize={loadSizes(LAYOUT_KEY_V, DEFAULT_V_SIZES)[2]}
              style={{ minHeight: '100px' }}
            >
              <PaneContainer label="CONTROLS">
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    height: '100%',
                    backgroundColor: '#111111',
                    color: '#888888',
                    fontSize: '12px',
                    fontFamily: 'monospace',
                  }}
                >
                  Coming in Plan 07-03
                </div>
              </PaneContainer>
            </Panel>
          </PanelGroup>
        </Panel>
      </PanelGroup>
    </div>
  )
}
