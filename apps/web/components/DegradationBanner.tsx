'use client'

/**
 * DegradationBanner — top banner shown when a degraded_state WS event arrives.
 *
 * Reads `degraded` from the Zustand WS store. Renders a yellow-orange banner
 * with: "Degraded: {source} — {reason}" and a "Dismiss" button.
 *
 * Hidden when degraded is null — no layout impact in normal operation (UI-08).
 */

import { useWsStore } from '@/store/ws'

export default function DegradationBanner() {
  const degraded = useWsStore((s) => s.degraded)
  const clearDegraded = useWsStore((s) => s.clearDegraded)

  if (degraded == null) return null

  return (
    <div
      style={{
        backgroundColor: '#92400e',
        borderBottom: '1px solid #d97706',
        padding: '6px 16px',
        display: 'flex',
        alignItems: 'center',
        gap: '12px',
        color: '#fef3c7',
        fontSize: '13px',
        fontFamily: 'monospace',
      }}
      role="alert"
    >
      <span>
        <strong>DEGRADED:</strong> {degraded.source} — {degraded.reason}
      </span>
      <button
        onClick={clearDegraded}
        style={{
          marginLeft: 'auto',
          background: 'transparent',
          border: '1px solid #d97706',
          color: '#fef3c7',
          cursor: 'pointer',
          padding: '2px 8px',
          borderRadius: '4px',
          fontSize: '12px',
          fontFamily: 'monospace',
        }}
      >
        Dismiss
      </button>
    </div>
  )
}
