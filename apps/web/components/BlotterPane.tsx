'use client'

/**
 * BlotterPane — positions table + F/K/P controls as a resizable pane component.
 *
 * Migrated from apps/web/app/dashboard/blotter/page.tsx (Phase 5).
 * This is NOT a full page — it's a pane body rendered inside PaneContainer.
 *
 * Key differences from the blotter page:
 *  - Does NOT call useStream() — the parent dashboard page does this once.
 *  - Does NOT render a header/nav bar — PaneContainer provides the title bar.
 *  - Reads positions and engineState from useWsStore (cross-pane Zustand state).
 *  - EngineStateBadge + AuthorTVAlertButton are passed to PaneContainer via rightSlot
 *    in dashboard/page.tsx (D-05).
 *
 * Color tokens: 05-UI-SPEC.md / 07-UI-SPEC.md
 */

import { useState, useEffect, useCallback } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useHotkeys } from '@/hooks/useHotkeys'
import { useWsStore, type Position } from '@/store/ws'
import ConfirmationDialog from '@/components/ConfirmationDialog'
import HelpOverlay from '@/components/HelpOverlay'
import { API_BASE } from '@/lib/api'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface PositionsResponse {
  positions: Position[]
  engine_state: 'running' | 'paused' | 'killed'
}

// ---------------------------------------------------------------------------
// Time-in-position formatter
// ---------------------------------------------------------------------------

function formatTimeIn(entryTsUtc: string): string {
  const entryMs = new Date(entryTsUtc).getTime()
  const nowMs = Date.now()
  const diffSec = Math.max(0, Math.floor((nowMs - entryMs) / 1000))
  const h = Math.floor(diffSec / 3600)
  const m = Math.floor((diffSec % 3600) / 60)
  const s = diffSec % 60
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

// ---------------------------------------------------------------------------
// P&L formatter
// ---------------------------------------------------------------------------

function formatPnl(pnl: number): string {
  const sign = pnl >= 0 ? '+' : ''
  return `${sign}$${pnl.toFixed(2)}`
}

// ---------------------------------------------------------------------------
// BlotterPane
// ---------------------------------------------------------------------------

export default function BlotterPane() {
  // Read cross-pane state from Zustand (positions updated by useStream in parent)
  const engineState = useWsStore((s) => s.engineState)
  const wsPositions = useWsStore((s) => s.positions)
  const setEngineState = useWsStore((s) => s.setEngineState)

  // Dialog state
  const [flattenOpen, setFlattenOpen] = useState(false)
  const [killOpen, setKillOpen] = useState(false)
  const [helpOpen, setHelpOpen] = useState(false)
  // WR-02: surface flatten errors to the user
  const [flattenError, setFlattenError] = useState<string | null>(null)
  const dialogOpen = flattenOpen || killOpen

  // Time-in ticker — forces re-render every second to update HH:MM:SS
  const [, tick] = useState(0)
  useEffect(() => {
    const interval = setInterval(() => tick((n) => n + 1), 1000)
    return () => clearInterval(interval)
  }, [])

  // TanStack Query — GET /positions (1s polling fallback for when WS is disconnected)
  const { isError } = useQuery<PositionsResponse>({
    queryKey: ['positions'],
    queryFn: async () => {
      const res = await fetch(`${API_BASE}/positions`)
      if (!res.ok) throw new Error(`GET /positions failed: ${res.status}`)
      return res.json() as Promise<PositionsResponse>
    },
    refetchInterval: 1000,
  })

  // Use WS positions (live) — updated by useStream in parent dashboard
  const positions: Position[] = wsPositions

  // Hotkey handlers (stable references via useCallback)
  const handleFlatten = useCallback(() => {
    if (!killOpen) setFlattenOpen(true)
  }, [killOpen])

  const handleKill = useCallback(() => {
    if (!flattenOpen) setKillOpen(true)
  }, [flattenOpen])

  const handlePause = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/pause`, { method: 'POST' })
      if (res.ok) {
        const data = await res.json() as { state: 'running' | 'paused' | 'killed' }
        setEngineState(data.state)
      }
    } catch {
      // Network error — badge will update via WS event when recovered
    }
  }, [setEngineState])

  const handleHelp = useCallback(() => setHelpOpen((o) => !o), [])

  useHotkeys({
    onFlatten: handleFlatten,
    onKill: handleKill,
    onPause: handlePause,
    onHelp: handleHelp,
    dialogOpen,
  })

  // Flatten confirm action
  async function handleFlattenConfirm() {
    setFlattenOpen(false)
    setFlattenError(null)
    try {
      const res = await fetch(`${API_BASE}/flatten`, { method: 'POST' })
      if (!res.ok) {
        // WR-02: surface non-2xx response so the operator knows the request failed
        const errText = await res.text().catch(() => '')
        const msg = `Flatten failed: ${res.status} ${errText.slice(0, 120)}`
        setFlattenError(msg)
        console.error(msg)
      }
    } catch (e) {
      const msg = `Flatten network error: ${String(e).slice(0, 120)}`
      setFlattenError(msg)
      console.error(msg)
    }
  }

  // Kill confirm action
  async function handleKillConfirm() {
    setKillOpen(false)
    try {
      const res = await fetch(`${API_BASE}/kill`, { method: 'POST' })
      if (res.ok) {
        const data = await res.json() as { state: 'running' | 'paused' | 'killed' }
        setEngineState(data.state)
      }
    } catch {
      // Fire-and-forget; backend writes audit log
    }
  }

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        backgroundColor: '#000000',
        color: '#d1d4dc',
        overflow: 'hidden',
      }}
    >
      {/* WR-02: flatten error banner */}
      {flattenError && (
        <div
          role="alert"
          style={{
            padding: '6px 16px',
            backgroundColor: '#2d0000',
            borderBottom: '1px solid #ef4444',
            color: '#f87171',
            fontSize: '11px',
            fontFamily: 'monospace',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            flexShrink: 0,
          }}
        >
          <span>{flattenError}</span>
          <button
            onClick={() => setFlattenError(null)}
            style={{ background: 'none', border: 'none', color: '#f87171', cursor: 'pointer', fontSize: '11px' }}
          >
            dismiss
          </button>
        </div>
      )}

      {/* Positions table — flex: 1, overflow: auto (scrollable body) */}
      <div style={{ flex: 1, overflow: 'auto', minHeight: 0 }}>
        {isError ? (
          /* Error state per 07-UI-SPEC §Error States */
          <div
            style={{
              padding: '32px',
              color: '#f87171',
              fontSize: '12px',
              fontFamily: 'monospace',
            }}
          >
            Failed to load positions. Is the API running? Check uvicorn output.
          </div>
        ) : positions.length === 0 ? (
          /* Empty state per 07-UI-SPEC §Empty States */
          <div
            style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              height: '100%',
              padding: '32px',
              textAlign: 'center',
            }}
          >
            <div
              style={{
                fontSize: '14px',
                fontWeight: 'bold',
                color: '#d1d4dc',
                marginBottom: '8px',
                fontFamily: 'monospace',
              }}
            >
              No open positions
            </div>
            <div style={{ fontSize: '12px', color: '#888888', fontFamily: 'monospace' }}>
              Positions appear here when the engine fills an entry. Start a backtest to generate fills.
            </div>
          </div>
        ) : (
          <table
            style={{
              width: '100%',
              borderCollapse: 'collapse',
              fontFamily: 'monospace',
              fontSize: '12px',
            }}
          >
            <thead>
              <tr style={{ borderBottom: '1px solid #222222' }}>
                {[
                  'Symbol',
                  'Side',
                  'Qty',
                  'Avg Fill',
                  'Mark',
                  'Unreal P&L',
                  'Stop Dist $',
                  'Stop Dist ticks',
                  'Target Dist',
                  'Time In',
                ].map((col) => (
                  <th
                    key={col}
                    scope="col"
                    style={{
                      fontSize: '11px',
                      color: '#888888',
                      textTransform: 'uppercase',
                      letterSpacing: '0.05em',
                      fontWeight: 400,
                      textAlign: 'right',
                      padding: '8px',
                    }}
                  >
                    {col}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {positions.map((pos) => {
                // Unreal P&L — uses point_value from API (FND-06: no hardcoded constants)
                const pnl =
                  pos.side === 'long'
                    ? (pos.mark - pos.avg_fill) * pos.qty * pos.point_value
                    : (pos.avg_fill - pos.mark) * pos.qty * pos.point_value

                // Stop distance in dollars and ticks
                const stopDistDollars =
                  pos.side === 'long'
                    ? (pos.stop - pos.mark) * pos.qty * pos.point_value
                    : (pos.mark - pos.stop) * pos.qty * pos.point_value

                // Target distance in dollars
                const targetDist =
                  pos.side === 'long'
                    ? (pos.target - pos.mark) * pos.point_value
                    : (pos.mark - pos.target) * pos.point_value

                // Stop distance in ticks (1 point = 4 ticks for ES/MES)
                const stopDistTicks = Math.abs(pos.mark - pos.stop) * 4

                const pnlColor =
                  pnl > 0 ? '#4ade80' : pnl < 0 ? '#f87171' : '#888888'

                return (
                  <tr
                    key={`${pos.strategy_id}-${pos.symbol}-${pos.entry_ts_utc}`}
                    style={{
                      height: '36px',
                      backgroundColor: '#111111',
                      borderBottom: '1px solid #1a1a2e',
                    }}
                  >
                    <td style={{ padding: '0 8px', color: '#d1d4dc' }}>
                      {pos.symbol}
                    </td>
                    <td
                      style={{
                        padding: '0 8px',
                        color: pos.side === 'long' ? '#4ade80' : '#f87171',
                        textAlign: 'right',
                      }}
                    >
                      {pos.side.toUpperCase()}
                    </td>
                    <td
                      className="tabular-nums"
                      style={{ padding: '0 8px', color: '#d1d4dc', textAlign: 'right' }}
                    >
                      {pos.qty}
                    </td>
                    <td
                      className="tabular-nums"
                      style={{ padding: '0 8px', color: '#d1d4dc', textAlign: 'right' }}
                    >
                      {pos.avg_fill.toFixed(2)}
                    </td>
                    <td
                      className="tabular-nums"
                      style={{ padding: '0 8px', color: '#d1d4dc', textAlign: 'right' }}
                    >
                      {pos.mark.toFixed(2)}
                    </td>
                    <td
                      className="tabular-nums"
                      style={{
                        padding: '0 8px',
                        color: pnlColor,
                        textAlign: 'right',
                      }}
                    >
                      {formatPnl(pnl)}
                    </td>
                    <td
                      className="tabular-nums"
                      style={{ padding: '0 8px', color: '#f87171', textAlign: 'right' }}
                    >
                      {stopDistDollars.toFixed(2)}
                    </td>
                    <td
                      className="tabular-nums"
                      style={{ padding: '0 8px', color: '#888888', textAlign: 'right' }}
                    >
                      {stopDistTicks.toFixed(1)}
                    </td>
                    <td
                      className="tabular-nums"
                      style={{ padding: '0 8px', color: '#4ade80', textAlign: 'right' }}
                    >
                      {targetDist >= 0 ? '+' : ''}{targetDist.toFixed(2)}
                    </td>
                    <td
                      className="tabular-nums"
                      style={{ padding: '0 8px', color: '#888888', textAlign: 'right' }}
                    >
                      {formatTimeIn(pos.entry_ts_utc)}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>

      {/* Controls row — 48px, flexShrink 0, at bottom of pane */}
      <div
        style={{
          height: '48px',
          flexShrink: 0,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '0 16px',
          borderTop: '1px solid #222222',
          gap: '8px',
        }}
      >
        {/* Left: Flatten + Kill */}
        <div style={{ display: 'flex', gap: '8px' }}>
          <button
            onClick={handleFlatten}
            tabIndex={0}
            onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') handleFlatten() }}
            style={{
              border: '1px solid #ef4444',
              color: '#ef4444',
              backgroundColor: 'transparent',
              fontSize: '12px',
              fontFamily: 'monospace',
              padding: '4px 12px',
              borderRadius: '4px',
              cursor: 'pointer',
            }}
            title="F — Flatten All"
          >
            F — Flatten All
          </button>

          <button
            onClick={handleKill}
            tabIndex={0}
            onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') handleKill() }}
            style={{
              border: '1px solid #dc2626',
              color: '#dc2626',
              backgroundColor: 'transparent',
              fontSize: '12px',
              fontFamily: 'monospace',
              padding: '4px 12px',
              borderRadius: '4px',
              cursor: 'pointer',
            }}
            title="K — Kill Switch"
          >
            K — Kill Switch
          </button>
        </div>

        {/* Right: Pause */}
        <button
          onClick={() => void handlePause()}
          tabIndex={0}
          onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') void handlePause() }}
          style={{
            border: engineState === 'paused' ? '1px solid #eab308' : '1px solid #444444',
            color: engineState === 'paused' ? '#eab308' : '#888888',
            backgroundColor: 'transparent',
            fontSize: '12px',
            fontFamily: 'monospace',
            padding: '4px 12px',
            borderRadius: '4px',
            cursor: 'pointer',
          }}
          title="P — Pause / Resume"
        >
          P — {engineState === 'paused' ? 'Resume' : 'Pause'}
        </button>
      </div>

      {/* Flatten Confirmation Dialog */}
      <ConfirmationDialog
        open={flattenOpen}
        onClose={() => setFlattenOpen(false)}
        onConfirm={() => void handleFlattenConfirm()}
        title="FLATTEN ALL POSITIONS"
        titleColor="#d1d4dc"
        description={`Close all ${positions.length} open position${positions.length !== 1 ? 's' : ''} at next bar open.`}
        warning="This action cannot be undone."
        inputLabel="Type FLATTEN to confirm:"
        confirmString="FLATTEN"
        confirmButtonText="Confirm Flatten"
        dismissButtonText="Keep Positions"
        confirmBorderColor="#ef4444"
        inputErrorBorderColor="#ef4444"
      />

      {/* Kill Confirmation Dialog */}
      <ConfirmationDialog
        open={killOpen}
        onClose={() => setKillOpen(false)}
        onConfirm={() => void handleKillConfirm()}
        title="KILL SWITCH"
        titleColor="#dc2626"
        description="Halt all signal processing. Existing positions are held open."
        warning="No new entries will be accepted until manually re-enabled."
        inputLabel="Type KILL to confirm:"
        confirmString="KILL"
        confirmButtonText="Confirm Kill"
        dismissButtonText="Stay Running"
        confirmBorderColor="#dc2626"
        inputErrorBorderColor="#dc2626"
      />

      {/* Help Overlay */}
      <HelpOverlay open={helpOpen} onClose={() => setHelpOpen(false)} />
    </div>
  )
}
