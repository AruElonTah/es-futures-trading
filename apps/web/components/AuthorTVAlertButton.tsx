'use client'

// TODO(Phase 7 UI-07): condition + message will be sourced from the live strategy registry; Phase 6 wires hardcoded ORB defaults from the call site.

import { useState } from 'react'
import { API_BASE } from '@/lib/api'

interface AuthorTVAlertButtonProps {
  strategyId: string
  condition: string
  message: string
}

export default function AuthorTVAlertButton({ strategyId, condition, message }: AuthorTVAlertButtonProps) {
  const [busy, setBusy] = useState(false)
  const [toast, setToast] = useState<string | null>(null)

  const onClick = async () => {
    setBusy(true)
    setToast(null)
    try {
      const res = await fetch(`${API_BASE}/tv/alerts`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ strategy_id: strategyId, condition, message }),
      })
      if (!res.ok) {
        const errText = await res.text()
        setToast(`Alert failed: ${res.status} ${errText.slice(0, 120)}`)
        return
      }
      const data: { alert_id: string; tv_alert_id: string } = await res.json()
      setToast(`TV alert created: ${data.tv_alert_id}`)
    } catch (e) {
      setToast(`Network error: ${String(e).slice(0, 120)}`)
    } finally {
      setBusy(false)
      // Auto-dismiss toast after 6s
      setTimeout(() => setToast(null), 6000)
    }
  }

  return (
    <div className="inline-flex items-center gap-2">
      <button
        type="button"
        onClick={onClick}
        disabled={busy}
        className="px-2 py-1 text-xs font-mono border border-gray-600 hover:bg-gray-800 disabled:opacity-50"
        aria-label="Author TradingView alert for current strategy"
      >
        {busy ? 'Authoring…' : 'Author TV Alert'}
      </button>
      {toast && (
        <span className="text-xs font-mono text-amber-300" role="status">{toast}</span>
      )}
    </div>
  )
}
