'use client'

/**
 * ConnectionStatus — colored circle indicator for WS connection state.
 *
 * Color logic (D-08):
 *  - green:  connected AND lastBarAt <= 10s ago
 *  - yellow: connected AND lastBarAt > 10s ago (stale)
 *  - red:    disconnected OR lastBarAt > 30s ago OR lastBarAt is null
 *
 * Re-computes color on a 1Hz timer so staleness reflects wall-clock time.
 */

import { useState, useEffect } from 'react'
import { useWsStore, selectStatusColor } from '@/store/ws'

const COLOR_MAP: Record<'green' | 'yellow' | 'red', string> = {
  green: '#22c55e',
  yellow: '#eab308',
  red: '#ef4444',
}

const LABEL_MAP: Record<'green' | 'yellow' | 'red', string> = {
  green: 'LIVE',
  yellow: 'STALE',
  red: 'OFFLINE',
}

export default function ConnectionStatus() {
  const connected = useWsStore((s) => s.connected)
  const lastBarAt = useWsStore((s) => s.lastBarAt)

  // Force a re-render every second so wall-clock staleness is reflected
  const [, forceUpdate] = useState(0)
  useEffect(() => {
    const interval = setInterval(() => forceUpdate((n) => n + 1), 1000)
    return () => clearInterval(interval)
  }, [])

  const color = selectStatusColor({ connected, lastBarAt })
  const label = LABEL_MAP[color]

  let subLabel = ''
  if (color === 'yellow' && lastBarAt != null) {
    const ageSec = Math.floor((Date.now() - lastBarAt) / 1000)
    subLabel = ` ${ageSec}s`
  }

  return (
    <div
      className="flex items-center gap-1 font-mono text-xs"
      title={`WebSocket: ${connected ? 'connected' : 'disconnected'}`}
    >
      {/* Colored circle */}
      <span
        style={{
          display: 'inline-block',
          width: 10,
          height: 10,
          borderRadius: '50%',
          backgroundColor: COLOR_MAP[color],
          boxShadow: `0 0 4px ${COLOR_MAP[color]}`,
        }}
      />
      <span style={{ color: COLOR_MAP[color] }}>
        {label}{subLabel}
      </span>
    </div>
  )
}
