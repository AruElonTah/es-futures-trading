'use client'

/**
 * Candlestick chart component with ORB price lines and entry/stop/target markers.
 *
 * Uses lightweight-charts v5.2.0 vanilla API — no React wrapper.
 * Mounted inside a useEffect ref so cleanup (chart.remove()) prevents memory leaks.
 *
 * CRITICAL (D-09 / Pitfall 2): the v4 series markers API was removed in v5.2.0.
 * Use createSeriesMarkers(series, markers) — named import from 'lightweight-charts'.
 *
 * Docs consulted:
 *  - apps/web/node_modules/lightweight-charts/dist/typings.d.ts
 *  - .planning/phases/03-vertical-mvp-slice-backtester/03-RESEARCH.md §lightweight-charts v5.2.0
 */

import { useEffect, useRef, useState } from 'react'
import {
  createChart,
  createSeriesMarkers,
  CandlestickSeries,
  LineStyle,
  type IChartApi,
  type ISeriesApi,
  type SeriesMarker,
  type Time,
} from 'lightweight-charts'
import type { BarRow, TradeRow } from '@/lib/api'
import { useWsStore } from '@/store/ws'

/** ET time formatter — converts Unix seconds to America/New_York hh:mm display */
const etTimeFormatter = (unixSeconds: number): string =>
  new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/New_York',
    hour: '2-digit',
    minute: '2-digit',
    month: 'short',
    day: 'numeric',
    hour12: false,
  }).format(new Date(unixSeconds * 1000))

/** ET tick mark formatter — compact hh:mm for the time scale axis */
const etTickFormatter = (unixSeconds: number): string =>
  new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/New_York',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(new Date(unixSeconds * 1000))

export interface ChartProps {
  bars: BarRow[]
  orbHigh?: number
  orbLow?: number
  trades?: TradeRow[]
}

/**
 * Render a candlestick chart with optional ORB price lines and entry markers.
 *
 * - ORB high/low: yellow dashed price lines (orbHigh / orbLow props)
 * - Entry markers: green arrowUp for long, red arrowDown for short
 * - Stop price line: red dashed (from trade.stop_price)
 * - Target price line: green dashed (from trade.target_price)
 */
export default function Chart({
  bars,
  orbHigh,
  orbLow,
  trades = [],
}: ChartProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const seriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null)
  // chartRef stored for Effect 3 (focusedBarTs scroll) — must not be in Effect 1 scope
  const chartRef = useRef<IChartApi | null>(null)
  // Incremented each time a chart is created so the overlay effect re-fires
  const [chartKey, setChartKey] = useState(0)

  // focusedBarTs Zustand atom (D-12: click-to-scroll from TradeHistoryPane)
  const focusedBarTs = useWsStore((s) => s.focusedBarTs)
  const setFocusedBarTs = useWsStore((s) => s.setFocusedBarTs)

  // Effect 1: chart lifecycle — only bars and ORB levels.
  // Trades are intentionally excluded so a late-arriving trades query does not
  // destroy and recreate the chart, which caused the second createChart() call
  // to read clientHeight=0 after chart.remove() cleared the inline container styles.
  useEffect(() => {
    if (!containerRef.current || bars.length === 0) return

    const container = containerRef.current
    const { width: rectW, height: rectH } = container.getBoundingClientRect()
    const chart: IChartApi = createChart(container, {
      width: rectW || container.clientWidth || 800,
      height: rectH || container.clientHeight || 400,
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

    const candleSeries: ISeriesApi<'Candlestick'> = chart.addSeries(
      CandlestickSeries,
      {
        upColor: '#26a69a',
        downColor: '#ef5350',
        borderVisible: false,
        wickUpColor: '#26a69a',
        wickDownColor: '#ef5350',
      }
    )

    // API returns DESC (most-recent first); lightweight-charts requires ASC
    const chartData = bars
      .map((bar) => ({
        time: Math.floor(new Date(bar.ts_utc).getTime() / 1000) as Time,
        open: bar.open,
        high: bar.high,
        low: bar.low,
        close: bar.close,
      }))
      .sort((a, b) => (a.time as number) - (b.time as number))
    candleSeries.setData(chartData)

    if (orbHigh != null) {
      candleSeries.createPriceLine({
        price: orbHigh,
        color: '#ffeb3b',
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: 'ORB High',
      })
    }
    if (orbLow != null) {
      candleSeries.createPriceLine({
        price: orbLow,
        color: '#ffeb3b',
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: 'ORB Low',
      })
    }

    chart.timeScale().fitContent()
    seriesRef.current = candleSeries
    chartRef.current = chart // Store for Effect 3 (focusedBarTs scroll)

    // Signal to Effect 2 that a new series is ready
    setChartKey((k) => k + 1)

    const resizeObserver = new ResizeObserver((entries) => {
      const { width, height } = entries[0].contentRect
      if (width > 0 && height > 0) chart.applyOptions({ width, height })
    })
    resizeObserver.observe(container)

    return () => {
      resizeObserver.disconnect()
      chartRef.current = null // Clear before remove (T-07-03-03 / Pitfall 2)
      seriesRef.current = null
      chart.remove()
    }
  }, [bars, orbHigh, orbLow])

  // Effect 2: trade overlays — applied imperatively without touching the chart lifecycle.
  // chartKey in deps re-triggers this effect after a new chart is created in Effect 1,
  // handling both orderings: trades-before-bars and trades-after-bars.
  useEffect(() => {
    const candleSeries = seriesRef.current
    if (!candleSeries || trades.length === 0) return

    // v5 markers plugin — createSeriesMarkers(series, initialMarkers) (D-09)
    const entryMarkers: SeriesMarker<Time>[] = []
    for (const trade of trades) {
      const entryTime = Math.floor(
        new Date(trade.entry_ts_utc).getTime() / 1000
      ) as Time
      entryMarkers.push({
        time: entryTime,
        position: trade.side === 'long' ? 'belowBar' : 'aboveBar',
        color: trade.side === 'long' ? '#26a69a' : '#ef5350',
        shape: trade.side === 'long' ? 'arrowUp' : 'arrowDown',
        text: 'Entry',
      })

      if (trade.stop_price != null) {
        candleSeries.createPriceLine({
          price: trade.stop_price,
          color: '#ef4444',
          lineWidth: 1,
          lineStyle: LineStyle.Dashed,
          axisLabelVisible: true,
          title: 'Stop',
        })
      }
      if (trade.target_price != null) {
        candleSeries.createPriceLine({
          price: trade.target_price,
          color: '#26a69a',
          lineWidth: 1,
          lineStyle: LineStyle.Dashed,
          axisLabelVisible: true,
          title: 'Target',
        })
      }
    }
    createSeriesMarkers(candleSeries, entryMarkers)
  }, [trades, chartKey])

  // Effect 3: chart scroll-to-trade — watches focusedBarTs Zustand atom (D-12).
  // Fires when a trade row in TradeHistoryPane is clicked.
  // Scrolls the candlestick chart to center the bar at the trade's entry timestamp.
  useEffect(() => {
    if (!focusedBarTs || !seriesRef.current || !chartRef.current) return

    const targetUnix = Math.floor(new Date(focusedBarTs).getTime() / 1000)

    // Sort bars ASC for index lookup (bars prop may be DESC from API)
    const sorted = [...bars].sort(
      (a, b) => new Date(a.ts_utc).getTime() - new Date(b.ts_utc).getTime()
    )

    const idx = sorted.findIndex(
      (b) => Math.floor(new Date(b.ts_utc).getTime() / 1000) === targetUnix
    )

    if (idx >= 0) {
      // Scroll so the target bar is ~30% from the left edge
      chartRef.current.timeScale().scrollToPosition(
        idx - Math.floor(sorted.length * 0.3),
        false
      )
    }

    // Reset after scroll so effect doesn't fire again (D-12)
    setFocusedBarTs(null)
  }, [focusedBarTs, bars, setFocusedBarTs])

  return (
    <div
      ref={containerRef}
      style={{ width: '100%', height: '100%' }}
    />
  )
}
