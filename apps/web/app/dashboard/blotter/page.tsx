'use client'

/**
 * /dashboard/blotter — Phase 5 blotter sub-route (UI-05, UI-09).
 *
 * Positions table with live WS mark-price updates + engine state badge.
 * F/K/P hotkeys with confirmation dialogs + ? help overlay.
 *
 * Color tokens and component specs from 05-UI-SPEC.md.
 * unreal_pnl uses position.point_value from GET /positions (FND-06: no magic numbers).
 *
 * Docs consulted:
 *  - apps/web/node_modules/next/dist/docs/01-app/03-api-reference/01-directives/use-client.md
 */

import { useState, useEffect, useRef, useCallback } from 'react'
import Link from 'next/link'
import { useQuery } from '@tanstack/react-query'
import { useStream } from '@/hooks/useStream'
import { useHotkeys, HOTKEY_REGISTRY } from '@/hooks/useHotkeys'
import { useWsStore } from '@/store/ws'
import ETClock from '@/components/ETClock'
import ConnectionStatus from '@/components/ConnectionStatus'
import AuthorTVAlertButton from '@/components/AuthorTVAlertButton'
import { API_BASE } from '@/lib/api'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface Position {
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

interface PositionsResponse {
  positions: Position[]
  engine_state: 'running' | 'paused' | 'killed'
}

// ---------------------------------------------------------------------------
// Engine State Badge (inline component)
// ---------------------------------------------------------------------------

const ENGINE_STATE_COLORS: Record<'running' | 'paused' | 'killed', string> = {
  running: '#4ade80',
  paused: '#eab308',
  killed: '#ef4444',
}

const ENGINE_STATE_LABELS: Record<'running' | 'paused' | 'killed', string> = {
  running: 'RUNNING',
  paused: 'PAUSED',
  killed: 'KILLED',
}

function EngineStateBadge({ state }: { state: 'running' | 'paused' | 'killed' }) {
  const color = ENGINE_STATE_COLORS[state] ?? '#888888'
  const label = ENGINE_STATE_LABELS[state] ?? state.toUpperCase()
  return (
    <span
      style={{
        fontSize: '11px',
        fontFamily: 'monospace',
        padding: '2px 8px',
        borderRadius: '2px',
        border: `1px solid ${color}`,
        color,
        backgroundColor: 'transparent',
      }}
    >
      {label}
    </span>
  )
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
// Confirmation dialogs
// ---------------------------------------------------------------------------

interface ConfirmDialogProps {
  open: boolean
  onClose: () => void
  onConfirm: () => void
  title: string
  titleColor: string
  description: string
  warning: string
  inputLabel: string
  confirmString: string
  confirmButtonText: string
  dismissButtonText: string
  confirmBorderColor: string
  inputErrorBorderColor: string
}

function ConfirmationDialog({
  open,
  onClose,
  onConfirm,
  title,
  titleColor,
  description,
  warning,
  inputLabel,
  confirmString,
  confirmButtonText,
  dismissButtonText,
  confirmBorderColor,
  inputErrorBorderColor,
}: ConfirmDialogProps) {
  const [value, setValue] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)
  const titleId = `dialog-title-${title.replace(/\s+/g, '-').toLowerCase()}`

  // Reset input and auto-focus on open
  useEffect(() => {
    if (open) {
      setValue('')
      // Small timeout ensures DOM is rendered before focus
      setTimeout(() => inputRef.current?.focus(), 0)
    }
  }, [open])

  // Escape closes dialog
  useEffect(() => {
    if (!open) return
    function handler(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
      if (e.key === 'Enter' && value === confirmString) onConfirm()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [open, value, confirmString, onClose, onConfirm])

  if (!open) return null

  const isConfirmable = value === confirmString
  const hasError = value.length > 0 && !isConfirmable
  const inputBorderColor = hasError ? inputErrorBorderColor : '#333333'

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        backgroundColor: 'rgba(0,0,0,0.75)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 9999,
      }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        style={{
          backgroundColor: '#111111',
          border: '1px solid #333333',
          borderRadius: '4px',
          padding: '24px',
          maxWidth: '480px',
          width: '100%',
          fontFamily: 'monospace',
        }}
      >
        {/* Title */}
        <div
          id={titleId}
          style={{
            fontSize: '14px',
            fontWeight: 'bold',
            color: titleColor,
            marginBottom: '16px',
          }}
        >
          {title}
        </div>

        {/* Description */}
        <div style={{ fontSize: '12px', color: '#888888', marginBottom: '16px' }}>
          {description}
        </div>

        {/* Warning */}
        <div style={{ fontSize: '12px', color: '#f87171', marginBottom: '16px' }}>
          {warning}
        </div>

        {/* Input label */}
        <div style={{ fontSize: '11px', color: '#888888', marginBottom: '8px' }}>
          {inputLabel}
        </div>

        {/* Input */}
        <input
          ref={inputRef}
          type="text"
          autoFocus
          value={value}
          onChange={(e) => setValue(e.target.value)}
          style={{
            fontSize: '12px',
            fontFamily: 'monospace',
            backgroundColor: '#000000',
            border: `1px solid ${inputBorderColor}`,
            borderRadius: '4px',
            color: '#d1d4dc',
            padding: '8px 12px',
            width: '100%',
            boxSizing: 'border-box',
            outline: 'none',
          }}
        />

        {/* Button row */}
        <div
          style={{
            display: 'flex',
            justifyContent: 'flex-end',
            gap: '8px',
            marginTop: '16px',
          }}
        >
          <button
            onClick={onClose}
            tabIndex={0}
            style={{
              border: '1px solid #444444',
              color: '#888888',
              backgroundColor: 'transparent',
              fontSize: '12px',
              fontFamily: 'monospace',
              padding: '4px 12px',
              borderRadius: '4px',
              cursor: 'pointer',
            }}
          >
            {dismissButtonText}
          </button>
          <button
            onClick={isConfirmable ? onConfirm : undefined}
            disabled={!isConfirmable}
            aria-disabled={!isConfirmable}
            tabIndex={0}
            style={{
              border: isConfirmable
                ? `1px solid ${confirmBorderColor}`
                : '1px solid #444444',
              color: isConfirmable ? confirmBorderColor : '#555555',
              backgroundColor: 'transparent',
              fontSize: '12px',
              fontFamily: 'monospace',
              padding: '4px 12px',
              borderRadius: '4px',
              cursor: isConfirmable ? 'pointer' : 'not-allowed',
            }}
          >
            {confirmButtonText}
          </button>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Help Overlay
// ---------------------------------------------------------------------------

function HelpOverlay({ open, onClose }: { open: boolean; onClose: () => void }) {
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

// ---------------------------------------------------------------------------
// Main Blotter Page
// ---------------------------------------------------------------------------

export default function BlotterPage() {
  // Mount WS subscription for live price updates and engine state
  useStream()

  const engineState = useWsStore((s) => s.engineState)

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

  // TanStack Query — GET /positions (1s polling fallback for when WS disconnected)
  const {
    data: positionsData,
    isError,
  } = useQuery<PositionsResponse>({
    queryKey: ['positions'],
    queryFn: () => fetch(`${API_BASE}/positions`).then((r) => r.json()),
    refetchInterval: 1000,
  })

  // Sync engine state from the REST response on initial load
  const setEngineState = useWsStore((s) => s.setEngineState)
  useEffect(() => {
    if (positionsData?.engine_state) {
      setEngineState(positionsData.engine_state)
    }
  }, [positionsData?.engine_state, setEngineState])

  const positions: Position[] = positionsData?.positions ?? []

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
        // WR-02: surface non-2xx response so the operator knows the request failed.
        const errText = await res.text().catch(() => '')
        const msg = `Flatten failed: ${res.status} ${errText.slice(0, 120)}`
        setFlattenError(msg)
        console.error(msg)
      }
    } catch (e) {
      // Network error — backend may still have received the request.
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
        height: '100vh',
        backgroundColor: '#000000',
        color: '#d1d4dc',
        overflow: 'hidden',
      }}
    >
      {/* Header */}
      <header
        style={{
          height: '48px',
          flexShrink: 0,
          display: 'flex',
          alignItems: 'center',
          gap: '16px',
          padding: '0 16px',
          borderBottom: '1px solid #222222',
        }}
      >
        {/* Back link */}
        <Link
          href="/dashboard"
          style={{ color: '#888888', textDecoration: 'none', fontSize: '12px' }}
        >
          ← Dashboard
        </Link>

        {/* Spacer pushing title to center */}
        <div style={{ flex: 1 }} />

        {/* Title */}
        <span
          className="font-mono font-bold"
          style={{ fontSize: '14px', color: '#d1d4dc' }}
        >
          BLOTTER
        </span>

        {/* Spacer pushing right-side controls to the right */}
        <div style={{ flex: 1 }} />

        {/* Engine state badge */}
        <EngineStateBadge state={engineState} />

        <ETClock />
        <div className="flex items-center gap-3">
          {/* TODO(Phase 7 UI-07): replace hardcoded condition/message with live strategy registry values */}
          <AuthorTVAlertButton
            strategyId="orb"
            condition="ORB long entry threshold"
            message="ORB strategy alert"
          />
          <ConnectionStatus />
        </div>
      </header>

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

      {/* Positions table */}
      <div style={{ flex: 1, overflow: 'auto', minHeight: 0 }}>
        {isError ? (
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
              <tr
                style={{
                  borderBottom: '1px solid #222222',
                }}
              >
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
              {positions.map((pos, idx) => {
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

      {/* Controls row */}
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
          onClick={handlePause}
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
        onConfirm={handleFlattenConfirm}
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
        onConfirm={handleKillConfirm}
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
