'use client'

/**
 * Equity curve chart — standalone lightweight-charts v5 LineSeries component.
 *
 * Renders equity_$ over time as a blue line. A secondary light-red line shows
 * drawdown_$ for context.
 *
 * Same ET-aware time formatters as Chart.tsx.
 * Cleanup with chart.remove() prevents memory leaks.
 */

import { useEffect, useRef } from 'react'
import {
  createChart,
  LineSeries,
  type IChartApi,
  type Time,
} from 'lightweight-charts'
import type { EquityPoint } from '@/lib/api'

/** ET tick mark formatter — compact hh:mm for the time scale axis */
const etTickFormatter = (unixSeconds: number): string =>
  new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/New_York',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(new Date(unixSeconds * 1000))

/** ET time formatter for crosshair labels */
const etTimeFormatter = (unixSeconds: number): string =>
  new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/New_York',
    hour: '2-digit',
    minute: '2-digit',
    month: 'short',
    day: 'numeric',
    hour12: false,
  }).format(new Date(unixSeconds * 1000))

export interface EquityCurveProps {
  points: EquityPoint[]
}

export default function EquityCurve({ points }: EquityCurveProps) {
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!containerRef.current || points.length === 0) return

    const container = containerRef.current
    const { width: rectW, height: rectH } = container.getBoundingClientRect()
    const chart: IChartApi = createChart(container, {
      width: rectW || container.clientWidth || 800,
      height: rectH || container.clientHeight || 200,
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

    // Primary equity line (blue)
    const equitySeries = chart.addSeries(LineSeries, {
      color: '#2962FF',
      lineWidth: 2,
      title: 'Equity $',
    })

    // Secondary drawdown line (light red)
    const drawdownSeries = chart.addSeries(LineSeries, {
      color: '#ef535080',
      lineWidth: 1,
      title: 'Drawdown $',
    })

    equitySeries.setData(
      points.map((p) => ({
        time: Math.floor(new Date(p.ts_utc).getTime() / 1000) as Time,
        value: p.equity,
      }))
    )
    drawdownSeries.setData(
      points.map((p) => ({
        time: Math.floor(new Date(p.ts_utc).getTime() / 1000) as Time,
        value: p.drawdown,
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
      chart.remove()
    }
  }, [points])

  return (
    <div
      ref={containerRef}
      style={{ width: '100%', height: '100%' }}
    />
  )
}
