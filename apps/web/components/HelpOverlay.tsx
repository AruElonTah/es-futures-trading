'use client'

/**
 * HelpOverlay — extracted from apps/web/app/dashboard/blotter/page.tsx (Phase 5).
 *
 * Keyboard shortcut reference overlay. Triggered by the '?' hotkey.
 * Z-index 9998 — one below ConfirmationDialog (9999) so dialogs always
 * appear on top when both are open simultaneously.
 *
 * Used by: BlotterPane (Phase 7), dashboard page hotkey handler.
 */

import { useEffect } from 'react'
import { HOTKEY_REGISTRY } from '@/hooks/useHotkeys'

interface HelpOverlayProps {
  open: boolean
  onClose: () => void
}

export default function HelpOverlay({ open, onClose }: HelpOverlayProps) {
  useEffect(() => {
    if (!open) return
    function handler(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [open, onClose])

  if (!open) return null

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        backgroundColor: 'rgba(0,0,0,0.85)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 9998,
      }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="help-overlay-title"
        style={{
          maxWidth: '400px',
          width: '100%',
          backgroundColor: '#111111',
          border: '1px solid #333333',
          borderRadius: '4px',
          padding: '24px',
          fontFamily: 'monospace',
        }}
      >
        <div
          id="help-overlay-title"
          style={{
            fontSize: '14px',
            fontWeight: 'bold',
            color: '#d1d4dc',
            marginBottom: '16px',
          }}
        >
          KEYBOARD SHORTCUTS
        </div>

        {HOTKEY_REGISTRY.map((entry, idx) => (
          <div
            key={entry.key}
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              padding: '8px 0',
              borderBottom:
                idx < HOTKEY_REGISTRY.length - 1 ? '1px solid #222222' : 'none',
            }}
          >
            <span
              style={{
                backgroundColor: '#222222',
                border: '1px solid #444444',
                color: '#d1d4dc',
                borderRadius: '2px',
                padding: '2px 8px',
                fontSize: '11px',
                minWidth: '28px',
                textAlign: 'center',
                display: 'inline-block',
              }}
            >
              {entry.key === '?' ? '?' : entry.key.toUpperCase()}
            </span>
            <span style={{ fontSize: '12px', color: '#888888' }}>
              {entry.description}
            </span>
          </div>
        ))}

        <div
          style={{
            fontSize: '11px',
            color: '#555555',
            marginTop: '16px',
            textAlign: 'center',
          }}
        >
          Press Esc to close
        </div>
      </div>
    </div>
  )
}
