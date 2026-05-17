'use client'

import { useQuery } from '@tanstack/react-query'
import { API_BASE, type BarRow } from '@/lib/api'

/**
 * TanStack Query v5 hook for GET /bars.
 *
 * Returns the most recent RTH bars for the given symbol+timeframe.
 * staleTime of 60s avoids hammering the server on rapid re-renders.
 */
export function useBars(
  symbol: string,
  tf: string,
  limit = 390
) {
  return useQuery<BarRow[]>({
    queryKey: ['bars', symbol, tf, limit],
    queryFn: async () => {
      const res = await fetch(
        `${API_BASE}/bars?symbol=${symbol}&tf=${tf}&limit=${limit}`
      )
      if (!res.ok) {
        throw new Error(
          `GET /bars failed: ${res.status} ${res.statusText}`
        )
      }
      return res.json() as Promise<BarRow[]>
    },
    staleTime: 60_000,
  })
}
