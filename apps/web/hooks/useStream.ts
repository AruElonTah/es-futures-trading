'use client'

import { useEffect } from 'react'
import { WS_BASE } from '@/lib/api'
import { useWsStore } from '@/store/ws'

/**
 * Native WebSocket hook — mounts once on client, routes messages to Zustand.
 *
 * Topics handled in Phase 3:
 *  - 'bars'           → setLastBarAt(Date.now())
 *  - 'degraded_state' → setDegraded({source, reason})
 *
 * Other topics are ignored with a TODO comment for Phase 7.
 *
 * D-03-05-03: No exponential backoff in Phase 3 (single operator, single tab).
 * WS reconnect storm accepted — Phase 7 SP-06 adds backoff.
 */
export function useStream() {
  const setConnected = useWsStore((s) => s.setConnected)
  const setLastBarAt = useWsStore((s) => s.setLastBarAt)
  const setDegraded = useWsStore((s) => s.setDegraded)

  useEffect(() => {
    const ws = new WebSocket(`${WS_BASE}/stream`)

    ws.onopen = () => {
      setConnected(true)
    }

    ws.onclose = () => {
      setConnected(false)
    }

    ws.onerror = () => {
      setConnected(false)
    }

    ws.onmessage = (event: MessageEvent) => {
      // Narrow the catch to JSON parse errors only; handler errors surface normally (WR-002).
      let msg: { type: string; payload: Record<string, unknown> }
      try {
        msg = JSON.parse(event.data as string) as {
          type: string
          payload: Record<string, unknown>
        }
      } catch {
        return  // Malformed JSON — skip
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
        default:
          // TODO (Phase 7): route fills, positions, equity, signals to queryClient
          break
      }
    }

    return () => {
      ws.close()
    }
  }, [setConnected, setLastBarAt, setDegraded])
}
