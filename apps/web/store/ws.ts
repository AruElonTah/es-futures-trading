'use client'

/**
 * Zustand store for WebSocket connection state.
 *
 * Tracks:
 *  - connected: whether the WS is currently connected
 *  - lastBarAt:  Date.now() timestamp of the most recent bars event
 *  - degraded:   payload from a degraded_state WS event (or null)
 *
 * Connection-status color logic (D-08):
 *  - green:  connected AND lastBarAt <= 10s ago
 *  - yellow: connected AND lastBarAt > 10s ago
 *  - red:    disconnected OR lastBarAt > 30s ago OR lastBarAt is null
 */

import { create } from 'zustand'

export interface DegradedState {
  source: string
  reason: string
}

export interface WsState {
  connected: boolean
  lastBarAt: number | null
  degraded: DegradedState | null
  engineState: 'running' | 'paused' | 'killed'
  positions: Position[]
  focusedBarTs: string | null
  lastSeq: number | null
}

export interface Position {
  strategy_id: string
  symbol: string
  side: 'long' | 'short'
  qty: number
  avg_fill: number
  mark: number
  stop: number
  target: number
  entry_ts_utc: string
  point_value: number
}

export interface WsActions {
  setConnected: (v: boolean) => void
  setLastBarAt: (ts: number) => void
  setDegraded: (value: DegradedState) => void
  clearDegraded: () => void
  setEngineState: (s: 'running' | 'paused' | 'killed') => void
  setPositions: (p: Position[]) => void
  setFocusedBarTs: (ts: string | null) => void
  setLastSeq: (seq: number) => void
}

export type WsStore = WsState & WsActions

export const useWsStore = create<WsStore>()((set) => ({
  connected: false,
  lastBarAt: null,
  degraded: null,
  engineState: 'running',
  positions: [],
  focusedBarTs: null,
  lastSeq: null,

  setConnected: (v: boolean) => set({ connected: v }),
  setLastBarAt: (ts: number) => set({ lastBarAt: ts }),
  setDegraded: (value: DegradedState) => set({ degraded: value }),
  clearDegraded: () => set({ degraded: null }),
  setEngineState: (s: 'running' | 'paused' | 'killed') => set({ engineState: s }),
  setPositions: (p: Position[]) => set({ positions: p }),
  setFocusedBarTs: (ts: string | null) => set({ focusedBarTs: ts }),
  setLastSeq: (seq: number) => set({ lastSeq: seq }),
}))

/**
 * Compute the WS connection-status color from store state.
 *
 * Called every second by ConnectionStatus to reflect wall-clock staleness.
 *
 * @param state  Current WsStore state snapshot
 * @returns 'green' | 'yellow' | 'red'
 */
export function selectStatusColor(
  state: Pick<WsState, 'connected' | 'lastBarAt'>
): 'green' | 'yellow' | 'red' {
  if (!state.connected) return 'red'
  if (state.lastBarAt == null) return 'green'   // connected but no live bars yet
  const age = Date.now() - state.lastBarAt
  if (age > 30_000) return 'red'
  if (age > 10_000) return 'yellow'
  return 'green'
}
