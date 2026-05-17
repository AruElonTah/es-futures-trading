'use client'

import { useQuery } from '@tanstack/react-query'
import { API_BASE, type BacktestRow, type EquityPoint, type TradeRow } from '@/lib/api'

/**
 * List all backtest runs (most-recent first).
 */
export function useBacktests() {
  return useQuery<BacktestRow[]>({
    queryKey: ['backtests'],
    queryFn: async () => {
      const res = await fetch(`${API_BASE}/backtests`)
      if (!res.ok) {
        throw new Error(
          `GET /backtests failed: ${res.status} ${res.statusText}`
        )
      }
      return res.json() as Promise<BacktestRow[]>
    },
    staleTime: 30_000,
  })
}

/**
 * Fetch the equity curve for a specific backtest run.
 * Only enabled when runId is non-null.
 */
export function useEquityCurve(runId: string | null) {
  return useQuery<EquityPoint[]>({
    queryKey: ['equity', runId],
    queryFn: async () => {
      const res = await fetch(`${API_BASE}/backtests/${runId}/equity`)
      if (!res.ok) {
        throw new Error(
          `GET /backtests/${runId}/equity failed: ${res.status} ${res.statusText}`
        )
      }
      return res.json() as Promise<EquityPoint[]>
    },
    enabled: runId != null,
    staleTime: 60_000,
  })
}

/**
 * Fetch trades for a specific backtest run.
 * Only enabled when runId is non-null.
 */
export function useEquityTrades(runId: string | null) {
  return useQuery<TradeRow[]>({
    queryKey: ['trades', runId],
    queryFn: async () => {
      const res = await fetch(`${API_BASE}/backtests/${runId}/trades`)
      if (!res.ok) {
        throw new Error(
          `GET /backtests/${runId}/trades failed: ${res.status} ${res.statusText}`
        )
      }
      return res.json() as Promise<TradeRow[]>
    },
    enabled: runId != null,
    staleTime: 60_000,
  })
}
