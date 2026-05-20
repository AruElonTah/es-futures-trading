'use client'

import { useEffect, useRef } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { WS_BASE } from '@/lib/api'
import { useWsStore, type Position } from '@/store/ws'

/**
 * Native WebSocket hook with exponential backoff reconnect (Phase 7 SP-06).
 *
 * Reconnect loop: delay = min(2^attempt * 1000ms, MAX_BACKOFF_MS) + random jitter
 * Gap detection: if incoming seq > lastSeq + 1, invalidate positions + backtests queries
 * Cleanup: stopped flag + clearTimeout + ws.close()
 *
 * Topics handled:
 *  - 'bars'                → setLastBarAt(Date.now())
 *  - 'degraded_state'      → setDegraded({source, reason})
 *  - 'engine_state_changed'→ setEngineState(state)
 *  - 'positions'           → setPositions(payload)
 *
 * Docs consulted:
 *  - apps/web/node_modules/next/dist/docs/01-app/03-api-reference/01-directives/use-client.md
 */

const MAX_BACKOFF_MS = 30_000

export function useStream() {
  const setConnected = useWsStore((s) => s.setConnected)
  const setLastBarAt = useWsStore((s) => s.setLastBarAt)
  const setDegraded = useWsStore((s) => s.setDegraded)
  const setEngineState = useWsStore((s) => s.setEngineState)
  const setPositions = useWsStore((s) => s.setPositions)
  const setLastSeq = useWsStore((s) => s.setLastSeq)

  const lastSeqRef = useRef<number | null>(null)
  const queryClient = useQueryClient()

  useEffect(() => {
    let attempt = 0
    let ws: WebSocket | null = null
    let timerId: ReturnType<typeof setTimeout> | null = null
    let stopped = false

    function connect() {
      ws = new WebSocket(`${WS_BASE}/stream`)

      ws.onopen = () => {
        setConnected(true)
        attempt = 0  // reset backoff on successful connection
      }

      ws.onclose = () => {
        setConnected(false)
        if (!stopped) {
          const delay =
            Math.min(Math.pow(2, attempt) * 1000, MAX_BACKOFF_MS) +
            Math.random() * 1000
          attempt++
          timerId = setTimeout(connect, delay)
        }
      }

      ws.onerror = () => {
        setConnected(false)
        // onclose will fire after onerror — reconnect handled there
      }

      ws.onmessage = (event: MessageEvent) => {
        // Narrow the catch to JSON parse errors only; handler errors surface normally (WR-002).
        let msg: { type: string; payload: Record<string, unknown>; seq?: number }
        try {
          msg = JSON.parse(event.data as string) as {
            type: string
            payload: Record<string, unknown>
            seq?: number
          }
        } catch {
          return  // Malformed JSON — skip
        }

        // Gap detection (D-19): if seq jumps, resync via TanStack Query (D-20)
        const incomingSeq = msg.seq ?? null
        if (
          incomingSeq !== null &&
          lastSeqRef.current !== null &&
          incomingSeq > lastSeqRef.current + 1
        ) {
          void queryClient.invalidateQueries({ queryKey: ['positions'] })
          void queryClient.invalidateQueries({ queryKey: ['backtests'] })
        }
        if (incomingSeq !== null) {
          lastSeqRef.current = incomingSeq
          setLastSeq(incomingSeq)
        }

        // Message routing outside the try block so real handler errors surface
        switch (msg.type) {
          case 'bars':
            setLastBarAt(Date.now())
            break
          case 'degraded_state':
            setDegraded({
              source: (msg.payload.source as string) ?? 'unknown',
              reason: (msg.payload.reason as string) ?? '',
            })
            break
          case 'engine_state_changed':
            setEngineState(msg.payload.state as 'running' | 'paused' | 'killed')
            break
          case 'positions': {
            // WR-05: payload may be a bare array or an object with a positions key.
            // The backend model serializes as {topic, emitted_at, positions: [...]}.
            const raw = msg.payload
            const arr = Array.isArray(raw)
              ? raw
              : (raw as Record<string, unknown>).positions
            if (Array.isArray(arr)) setPositions(arr as Position[])
            break
          }
          default:
            break
        }
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
