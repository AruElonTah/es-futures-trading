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

import { useEffect, useRef } from 'react'
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

  useEffect(() => {
    if (!containerRef.current) return

    const chart: IChartApi = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height: containerRef.current.clientHeight,
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

    // Convert BarRow to lightweight-charts data format (Unix seconds UTC)
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

    // ORB price lines
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

    // Trade stop/target price lines and entry markers
    // v5 markers plugin — import createSeriesMarkers from 'lightweight-charts' (D-09)
    // CRITICAL: pass markers directly to the constructor (v5 API, 03-RESEARCH.md Pitfall 2).
    // The v4 series markers API was removed in v5.2.0 — never call it on a series object.
    const entryMarkers: SeriesMarker<Time>[] = []

    for (const trade of trades) {
      // Entry marker
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

      // Stop price line (nullable)
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

      // Target price line (nullable)
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

    // createSeriesMarkers(series, initialMarkers) — v5 named import (03-RESEARCH.md Pitfall 2)
    // Passing markers directly to constructor is the complete v5 pattern
    createSeriesMarkers(candleSeries, entryMarkers)

    // Fit content on initial render
    chart.timeScale().fitContent()

    // ResizeObserver for responsive sizing
    const resizeObserver = new ResizeObserver(() => {
      if (containerRef.current) {
        chart.applyOptions({
          width: containerRef.current.clientWidth,
          height: containerRef.current.clientHeight,
        })
      }
    })
    if (containerRef.current) {
      resizeObserver.observe(containerRef.current)
    }

    return () => {
      resizeObserver.disconnect()
      chart.remove()
    }
  }, [bars, orbHigh, orbLow, trades])

  return (
    <div
      ref={containerRef}
      style={{ width: '100%', height: '100%' }}
    />
  )
}
