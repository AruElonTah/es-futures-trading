'use client'

/**
 * TradeHistoryPane — trade history table + equity+DD chart as a pane component.
 *
 * Two-section layout:
 *   - Trade table (flex: 1, overflow: auto) — 9 columns per 07-UI-SPEC.md
 *   - Equity chart (height: 160px, flexShrink: 0) — LineSeries + HistogramSeries
 *
 * Trade row click: calls setFocusedBarTs(trade.entry_ts_utc) via Zustand (D-12).
 * Chart.tsx Effect 3 watches focusedBarTs and scrolls the candlestick chart.
 *
 * HistogramSeries used with color 'rgba(239, 68, 68, 0.5)', values negated (D-11).
 * Per-bar color set on each data point to satisfy lightweight-charts Pitfall 7.
 *
 * References:
 *   - apps/web/components/EquityCurve.tsx — chart lifecycle pattern (two-effect split)
 *   - 07-PATTERNS.md §TradeHistoryPane
 *   - 07-UI-SPEC.md §TradeHistoryPane
 *   - T-07-03-01: error states show generic message, no stack traces
 *   - T-07-03-03: chartRef.current = null before chart.remove() (Pitfall 2)
 */

import { useEffect, useRef } from 'react'
import {
  createChart,
  LineSeries,
  HistogramSeries,
  type IChartApi,
  type Time,
} from 'lightweight-charts'
import { useWsStore } from '@/store/ws'
import { useBacktests, useEquityCurve, useEquityTrades } from '@/hooks/useBacktests'
import type { EquityPoint, TradeRow } from '@/lib/api'

// ---------------------------------------------------------------------------
// ET time formatters (same pattern as EquityCurve.tsx)
// ---------------------------------------------------------------------------

const etTickFormatter = (unixSeconds: number): string =>
  new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/New_York',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(new Date(unixSeconds * 1000))

const etTimeFormatter = (unixSeconds: number): string =>
  new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/New_York',
    hour: '2-digit',
    minute: '2-digit',
    month: 'short',
    day: 'numeric',
    hour12: false,
  }).format(new Date(unixSeconds * 1000))

// ---------------------------------------------------------------------------
// Point value constant (D-13: hardcode 50 for ES; client doesn't call instruments.py)
// Slippage $ = slippage_ticks × (pointValue / 4) × size
// ---------------------------------------------------------------------------

const POINT_VALUE = 50 // ES futures: 1 point = $50

function computeSlippageDollars(
  slippage_ticks: number,
  size: number
): number {
  return slippage_ticks * (POINT_VALUE / 4) * size
}

// ---------------------------------------------------------------------------
// Hold time formatter: hold_bars * 60s → HH:MM
// ---------------------------------------------------------------------------

function formatHoldTime(holdBars: number): string {
  const totalSeconds = holdBars * 60
  const h = Math.floor(totalSeconds / 3600)
  const m = Math.floor((totalSeconds % 3600) / 60)
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`
}

// ---------------------------------------------------------------------------
// Gross P&L formatter
// ---------------------------------------------------------------------------

function formatGrossPnl(pnl: number): string {
  const sign = pnl >= 0 ? '+' : ''
  return `${sign}$${pnl.toFixed(2)}`
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface TradeHistoryPaneProps {
  runId: string | null
}

// ---------------------------------------------------------------------------
// TradeHistoryPane component
// ---------------------------------------------------------------------------

export default function TradeHistoryPane({ runId }: TradeHistoryPaneProps) {
  // Zustand — focusedBarTs (D-12: click-to-scroll)
  const setFocusedBarTs = useWsStore((s) => s.setFocusedBarTs)
  const focusedBarTs = useWsStore((s) => s.focusedBarTs)

  // TanStack Query hooks
  const { data: backtests } = useBacktests()
  const effectiveRunId = runId ?? (backtests?.[0]?.run_id ?? null)

  const {
    data: trades,
    isLoading: tradesLoading,
    isError: tradesError,
  } = useEquityTrades(effectiveRunId)

  const {
    data: equityPoints,
    isLoading: equityLoading,
  } = useEquityCurve(effectiveRunId)

  // Chart refs (two-effect pattern per Pitfall 2 — never destroy chart on data update)
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)

  // ---------------------------------------------------------------------------
  // Effect 1: chart lifecycle — create once when equityPoints are available
  // ---------------------------------------------------------------------------

  useEffect(() => {
    const points = equityPoints ?? []
    if (!containerRef.current || points.length === 0) return

    const container = containerRef.current
    const { width: rectW, height: rectH } = container.getBoundingClientRect()
    const chart: IChartApi = createChart(container, {
      width: rectW || container.clientWidth || 600,
      height: rectH || container.clientHeight || 160,
      layout: {
        background: { color: '#000000' },
        textColor: '#d1d4dc',
      },
      localization: {
        timeFormatter: etTimeFormatter,
      },
      timeScale: {
        tickMarkFormatter: etTickFormatter,
        timeVisible: true,
        secondsVisible: false,
      },
      grid: {
        vertLines: { color: '#1a1a2e' },
        horzLines: { color: '#1a1a2e' },
      },
    })

    chartRef.current = chart

    const startEquity = points[0]?.equity ?? 0

    // Equity line (LineSeries) — color #4ade80 per 07-UI-SPEC §TradeHistoryPane
    const equitySeries = chart.addSeries(LineSeries, {
      color: '#4ade80',
      lineWidth: 1,
      title: 'PnL $',
    })

    // DD histogram (HistogramSeries) — values negated, per-bar color (D-11, Pitfall 7)
    const ddSeries = chart.addSeries(HistogramSeries, {
      color: 'rgba(239, 68, 68, 0.5)',
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
        value: -Math.abs(p.drawdown), // negative so bars render below zero (D-11)
        color: 'rgba(239, 68, 68, 0.5)', // per-bar color guard (Pitfall 7)
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
      chartRef.current = null // T-07-03-03: clear before remove (Pitfall 2)
      chart.remove()
    }
  }, [equityPoints])

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  // Resolve effective data
  const tradeList: TradeRow[] = trades ?? []
  const equityList: EquityPoint[] = equityPoints ?? []

  // Determine display state
  const hasRunId = effectiveRunId !== null
  const isLoadingData = tradesLoading || equityLoading

  // ---------------------------------------------------------------------------
  // Empty / error states
  // ---------------------------------------------------------------------------

  let tableContent: React.ReactNode

  if (tradesError) {
    // T-07-03-01: error state shows generic message, no stack traces
    tableContent = (
      <div
        style={{
          padding: '32px',
          color: '#f87171',
          fontSize: '12px',
          fontFamily: 'monospace',
        }}
      >
        Failed to load backtest history. Is the API running?
      </div>
    )
  } else if (!hasRunId) {
    // Empty state: no backtest run yet
    tableContent = (
      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          height: '100%',
          padding: '32px',
          textAlign: 'center',
        }}
      >
        <div
          style={{
            fontSize: '14px',
            fontWeight: 'bold',
            color: '#d1d4dc',
            marginBottom: '8px',
            fontFamily: 'monospace',
          }}
        >
          No backtest results
        </div>
        <div style={{ fontSize: '12px', color: '#888888', fontFamily: 'monospace' }}>
          Run a backtest from the Controls pane to see trade history here.
        </div>
      </div>
    )
  } else if (hasRunId && !isLoadingData && tradeList.length === 0) {
    // Empty state: backtest ran but zero trades
    tableContent = (
      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          height: '100%',
          padding: '32px',
          textAlign: 'center',
        }}
      >
        <div
          style={{
            fontSize: '14px',
            fontWeight: 'bold',
            color: '#d1d4dc',
            marginBottom: '8px',
            fontFamily: 'monospace',
          }}
        >
          No trades
        </div>
        <div style={{ fontSize: '12px', color: '#888888', fontFamily: 'monospace' }}>
          The last backtest produced no closed trades. Adjust strategy parameters and try again.
        </div>
      </div>
    )
  } else if (isLoadingData && tradeList.length === 0) {
    // Loading / backtest-running spinner state (D-15)
    tableContent = (
      <div
        role="status"
        aria-live="polite"
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
          padding: '12px 8px',
          color: '#eab308',
          fontSize: '12px',
          fontFamily: 'monospace',
        }}
      >
        <span
          style={{
            display: 'inline-block',
            animation: 'spin 1s linear infinite',
          }}
        >
          &#x21BB;
        </span>
        Running backtest&hellip;
      </div>
    )
  } else {
    // Trade table — 9 columns per 07-UI-SPEC.md
    tableContent = (
      <table
        style={{
          width: '100%',
          borderCollapse: 'collapse',
          fontFamily: 'monospace',
          fontSize: '12px',
        }}
      >
        <thead>
          <tr style={{ borderBottom: '1px solid #222222' }}>
            {['SIDE', 'ENTRY', 'EXIT', 'GROSS P&L', 'SLIPPAGE $', 'MAE', 'MFE', 'HOLD', 'REASON'].map((col) => (
              <th
                key={col}
                scope="col"
                style={{
                  fontSize: '11px',
                  color: '#888888',
                  textTransform: 'uppercase',
                  letterSpacing: '0.05em',
                  fontWeight: 400,
                  textAlign: 'right',
                  padding: '8px',
                }}
              >
                {col}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {tradeList.map((trade) => {
            const slippageDollars = computeSlippageDollars(trade.slippage_ticks, trade.size)
            const pnlColor = trade.pnl > 0 ? '#4ade80' : trade.pnl < 0 ? '#f87171' : '#888888'
            const sideColor = trade.side === 'long' ? '#4ade80' : '#f87171'
            const isFocused = focusedBarTs === trade.entry_ts_utc
            const holdBars = trade.exit_ts_utc && trade.entry_ts_utc
              ? Math.round(
                  (new Date(trade.exit_ts_utc).getTime() - new Date(trade.entry_ts_utc).getTime()) / 60000
                )
              : 0

            return (
              <tr
                key={trade.trade_id}
                role="button"
                tabIndex={0}
                onClick={() => setFocusedBarTs(trade.entry_ts_utc)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault()
                    setFocusedBarTs(trade.entry_ts_utc)
                  }
                }}
                style={{
                  height: '36px',
                  backgroundColor: isFocused ? '#1a1a2e' : '#111111',
                  borderBottom: '1px solid #1a1a2e',
                  border: isFocused ? '1px solid #4a90d9' : undefined,
                  cursor: 'pointer',
                }}
              >
                <td
                  style={{
                    padding: '0 8px',
                    color: sideColor,
                    textAlign: 'right',
                  }}
                >
                  {trade.side.toUpperCase()}
                </td>
                <td
                  className="tabular-nums"
                  style={{ padding: '0 8px', color: '#d1d4dc', textAlign: 'right' }}
                >
                  {trade.entry_price.toFixed(2)}
                </td>
                <td
                  className="tabular-nums"
                  style={{ padding: '0 8px', color: '#d1d4dc', textAlign: 'right' }}
                >
                  {trade.exit_price.toFixed(2)}
                </td>
                <td
                  className="tabular-nums"
                  style={{ padding: '0 8px', color: pnlColor, textAlign: 'right' }}
                >
                  {formatGrossPnl(trade.pnl)}
                </td>
                <td
                  className="tabular-nums"
                  style={{ padding: '0 8px', color: '#888888', textAlign: 'right' }}
                >
                  ${slippageDollars.toFixed(2)}
                </td>
                <td
                  className="tabular-nums"
                  style={{ padding: '0 8px', color: '#f87171', textAlign: 'right' }}
                >
                  ${Math.abs(trade.mae).toFixed(2)}
                </td>
                <td
                  className="tabular-nums"
                  style={{ padding: '0 8px', color: '#4ade80', textAlign: 'right' }}
                >
                  ${trade.mfe.toFixed(2)}
                </td>
                <td
                  className="tabular-nums"
                  style={{ padding: '0 8px', color: '#888888', textAlign: 'right' }}
                >
                  {formatHoldTime(holdBars)}
                </td>
                <td
                  style={{ padding: '0 8px', color: '#888888', textAlign: 'left' }}
                >
                  {trade.exit_reason}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    )
  }

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        backgroundColor: '#000000',
        color: '#d1d4dc',
        overflow: 'hidden',
      }}
    >
      {/* Trade table — flex: 1 1 0, overflow: auto */}
      <div style={{ flex: '1 1 0', overflow: 'auto', minHeight: 0 }}>
        {tableContent}
      </div>

      {/* Equity+DD chart — 160px fixed height (flexShrink: 0) */}
      <div
        ref={containerRef}
        aria-label="Equity curve and drawdown chart"
        style={{
          height: '160px',
          flexShrink: 0,
          backgroundColor: '#000000',
          borderTop: equityList.length > 0 ? '1px solid #222222' : 'none',
        }}
      />

      {/* CSS keyframe for spinner animation */}
      <style>{`
        @keyframes spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  )
}
