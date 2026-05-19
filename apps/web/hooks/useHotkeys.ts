'use client'

/**
 * useHotkeys — single hotkey registry + keyboard event hook (UI-09).
 *
 * Registry is the single source of truth for the HelpOverlay table.
 * Collision detection runs at module load (throws at startup, not runtime) — T-05-05-04.
 *
 * Keys: F → flatten, K → kill, P → pause, ? → help overlay
 * Guard: F/K/P are blocked inside INPUT/TEXTAREA/SELECT elements.
 * Re-entrant guard: dialogOpen flag prevents stacking confirmation dialogs.
 */

import { useEffect } from 'react'

export interface HotkeyEntry {
  key: string         // single character, e.g. 'f', 'k', 'p', '?'
  description: string
}

/**
 * Canonical hotkey registry — single source of truth for the HelpOverlay.
 * The key strings are lowercase; the listener normalises e.key via toLowerCase().
 */
export const HOTKEY_REGISTRY: HotkeyEntry[] = [
  { key: 'f', description: 'Flatten all open positions' },
  { key: 'k', description: 'Kill switch — halt signal processing' },
  { key: 'p', description: 'Pause / resume active strategy' },
  { key: '?', description: 'Show this help overlay' },
]

// Collision detection at module load — throws at startup (T-05-05-04).
const _keys = HOTKEY_REGISTRY.map((e) => e.key)
if (new Set(_keys).size !== _keys.length) {
  throw new Error(`Hotkey collision detected in HOTKEY_REGISTRY: ${_keys.join(', ')}`)
}

interface HotkeyHandlers {
  onFlatten: () => void
  onKill: () => void
  onPause: () => void
  onHelp: () => void
}

/**
 * Mount global keydown listener for the blotter hotkeys.
 *
 * @param handlers  - Callback functions for each hotkey action.
 * @param dialogOpen - True when any confirmation dialog is already open;
 *                     prevents re-entrant F/K/P activations (T-05-05-02).
 */
export function useHotkeys({
  onFlatten,
  onKill,
  onPause,
  onHelp,
  dialogOpen = false,
}: HotkeyHandlers & { dialogOpen?: boolean }) {
  useEffect(() => {
    function handler(e: KeyboardEvent) {
      const active = document.activeElement
      const inInput =
        active?.tagName === 'INPUT' ||
        active?.tagName === 'TEXTAREA' ||
        active?.tagName === 'SELECT'

      const key = e.key.toLowerCase()

      // '?' is allowed inside inputs (help overlay is always accessible)
      if (key === '?') {
        onHelp()
        return
      }

      // F, K, P are blocked inside form inputs
      if (inInput) return

      // Re-entrant guard — if a dialog is open, ignore conflicting hotkeys
      if (dialogOpen && (key === 'f' || key === 'k' || key === 'p')) return

      if (key === 'f') {
        onFlatten()
        return
      }
      if (key === 'k') {
        onKill()
        return
      }
      if (key === 'p') {
        onPause()
        return
      }
    }

    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onFlatten, onKill, onPause, onHelp, dialogOpen])
}
