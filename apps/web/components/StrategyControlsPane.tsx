'use client'

/**
 * StrategyControlsPane — 4th pane of the 4-pane terminal layout (Plan 07-04).
 *
 * Renders:
 *   1. Strategy list from GET /strategies with toggle buttons and status badges
 *   2. Param edit form (expandable per strategy) with PUT /strategies/{id}/params
 *      - 422 inline errors displayed below fields per D-16
 *      - Save & Hot-reload button with transient confirmation per UI-SPEC
 *   3. Run Backtest button calling POST /backtests/run with polling via useStrategyRun
 *   4. OPTIMIZATION HEATMAP accordion (collapsed by default)
 *
 * Security: No HTML5 min/max on inputs — server-side Pydantic is sole validator (D-16 / T-07-04-01).
 * Double-submit: Run Backtest button disabled while isRunning (T-07-04-02).
 */

import { useState, useCallback, useEffect, useRef } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useStrategies, useStrategyRun } from '@/hooks/useBacktests'
import { API_BASE } from '@/lib/api'
import type { StrategyInfo } from '@/lib/api'

// ---------------------------------------------------------------------------
// FieldError: per-field inline 422 error display
// ---------------------------------------------------------------------------

interface FieldErrorProps {
  message: string | null
}

function FieldError({ message }: FieldErrorProps) {
  if (!message) return null
  return (
    <div
      style={{
        fontSize: '11px',
        color: '#f87171',
        fontFamily: 'monospace',
        marginTop: '4px',
      }}
    >
      {message}
    </div>
  )
}

// ---------------------------------------------------------------------------
// ParamForm: inline param edit form for a single strategy
// ---------------------------------------------------------------------------

const FIELD_LABELS: Record<string, string> = {
  opening_range_minutes: 'Opening Range (min)',
  atr_stop_mult: 'ATR Stop Mult',
  r_target: 'R Target',
  atr_period: 'ATR Period',
  ema_period: 'EMA Period',
  min_range_ticks: 'Min Range Ticks',
}

interface ParamFormProps {
  strategy: StrategyInfo
  onClose: () => void
}

function ParamForm({ strategy, onClose }: ParamFormProps) {
  // Local form state seeded from strategy.params
  const [formValues, setFormValues] = useState<Record<string, string>>(
    () =>
      Object.fromEntries(
        Object.entries(strategy.params).map(([k, v]) => [k, String(v)])
      )
  )
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [globalError, setGlobalError] = useState<string | null>(null)
  const [saveSuccess, setSaveSuccess] = useState(false)
  const [isSaving, setIsSaving] = useState(false)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Cleanup transient timer on unmount
  useEffect(() => {
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [])

  const handleSave = useCallback(async () => {
    setIsSaving(true)
    setFieldErrors({})
    setGlobalError(null)
    setSaveSuccess(false)

    // Build param payload — try to parse numbers
    const payload: Record<string, number | string | boolean> = {}
    for (const [key, raw] of Object.entries(formValues)) {
      const num = Number(raw)
      payload[key] = raw.trim() === '' ? raw : isNaN(num) ? raw : num
    }

    try {
      const res = await fetch(`${API_BASE}/strategies/${strategy.strategy_id}/params`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })

      if (res.ok) {
        // Show transient "Params saved — engine reloading" for 2s (UI-SPEC)
        setSaveSuccess(true)
        timerRef.current = setTimeout(() => setSaveSuccess(false), 2000)
      } else if (res.status === 422) {
        const body = await res.json() as { detail?: string | Array<{ loc: string[]; msg: string }> }
        if (Array.isArray(body.detail)) {
          // Pydantic v2 returns an array of validation errors
          const errors: Record<string, string> = {}
          for (const err of body.detail) {
            const field = err.loc?.[err.loc.length - 1] ?? 'unknown'
            errors[String(field)] = err.msg
          }
          setFieldErrors(errors)
        } else if (typeof body.detail === 'string') {
          setGlobalError(body.detail)
        } else {
          setGlobalError('Validation failed. Check your values.')
        }
      } else {
        setGlobalError(`Failed to save params (HTTP ${res.status}). Is the API running?`)
      }
    } catch {
      setGlobalError('Failed to save params. Is the API running?')
    } finally {
      setIsSaving(false)
    }
  }, [strategy.strategy_id, formValues])

  return (
    <div
      style={{
        padding: '8px 12px 12px',
        borderTop: '1px solid #333333',
        backgroundColor: '#0a0a0a',
      }}
    >
      {/* Param fields */}
      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          gap: '8px',
          marginBottom: '12px',
        }}
      >
        {Object.entries(strategy.params).map(([key]) => {
          const fieldError = fieldErrors[key] ?? null
          return (
            <div key={key}>
              <label
                htmlFor={`param-${strategy.strategy_id}-${key}`}
                style={{
                  display: 'block',
                  fontSize: '11px',
                  color: '#888888',
                  fontFamily: 'monospace',
                  marginBottom: '4px',
                }}
              >
                {FIELD_LABELS[key] ?? key}
              </label>
              <input
                id={`param-${strategy.strategy_id}-${key}`}
                type="number"
                // NO min/max/step — server-side Pydantic is sole validator (D-16 / T-07-04-01)
                value={formValues[key] ?? ''}
                onChange={(e) =>
                  setFormValues((prev) => ({ ...prev, [key]: e.target.value }))
                }
                className="tabular-nums"
                style={{
                  backgroundColor: '#000000',
                  border: fieldError ? '1px solid #f87171' : '1px solid #333333',
                  borderRadius: '4px',
                  color: '#d1d4dc',
                  fontSize: '12px',
                  fontFamily: 'monospace',
                  padding: '4px 8px',
                  width: '64px',
                  outline: 'none',
                }}
              />
              <FieldError message={fieldError} />
            </div>
          )
        })}
      </div>

      {/* Global 422 error */}
      {globalError && (
        <div
          style={{
            fontSize: '11px',
            color: '#f87171',
            fontFamily: 'monospace',
            marginBottom: '8px',
          }}
        >
          {globalError}
        </div>
      )}

      {/* Transient success message */}
      {saveSuccess && (
        <div
          style={{
            fontSize: '11px',
            color: '#4ade80',
            fontFamily: 'monospace',
            marginBottom: '8px',
          }}
        >
          Params saved — engine reloading
        </div>
      )}

      {/* Action buttons */}
      <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', alignItems: 'center' }}>
        <button
          onClick={handleSave}
          disabled={isSaving}
          style={{
            border: '1px solid #2a5a8a',
            color: '#4a90d9',
            backgroundColor: 'transparent',
            fontSize: '12px',
            fontFamily: 'monospace',
            padding: '4px 12px',
            borderRadius: '4px',
            cursor: isSaving ? 'not-allowed' : 'pointer',
            opacity: isSaving ? 0.6 : 1,
          }}
        >
          Save &amp; Hot-reload
        </button>

        <button
          onClick={onClose}
          style={{
            border: '1px solid #333333',
            color: '#888888',
            backgroundColor: 'transparent',
            fontSize: '12px',
            fontFamily: 'monospace',
            padding: '4px 12px',
            borderRadius: '4px',
            cursor: 'pointer',
          }}
        >
          Close
        </button>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// StrategyRow: one row per strategy + optional expanded param form
// ---------------------------------------------------------------------------

interface StrategyRowProps {
  strategy: StrategyInfo
  isExpanded: boolean
  onToggleExpand: () => void
}

function StrategyRow({ strategy, isExpanded, onToggleExpand }: StrategyRowProps) {
  const queryClient = useQueryClient()
  const [optimisticEnabled, setOptimisticEnabled] = useState(strategy.enabled)
  const [toggleError, setToggleError] = useState<string | null>(null)
  const toggleTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Keep optimistic state in sync if query refetches
  useEffect(() => {
    setOptimisticEnabled(strategy.enabled)
  }, [strategy.enabled])

  useEffect(() => {
    return () => {
      if (toggleTimerRef.current) clearTimeout(toggleTimerRef.current)
    }
  }, [])

  const handleToggle = useCallback(async () => {
    const prevEnabled = optimisticEnabled
    // Optimistic update (Toggle Strategy Contract)
    setOptimisticEnabled(!prevEnabled)
    setToggleError(null)

    try {
      const res = await fetch(
        `${API_BASE}/strategies/${strategy.strategy_id}/toggle`,
        { method: 'POST' }
      )
      if (res.ok) {
        await queryClient.invalidateQueries({ queryKey: ['strategies'] })
      } else {
        // Revert on error
        setOptimisticEnabled(prevEnabled)
        setToggleError('Failed to toggle strategy. Is the API running?')
        toggleTimerRef.current = setTimeout(() => setToggleError(null), 3000)
      }
    } catch {
      setOptimisticEnabled(prevEnabled)
      setToggleError('Failed to toggle strategy. Is the API running?')
      toggleTimerRef.current = setTimeout(() => setToggleError(null), 3000)
    }
  }, [strategy.strategy_id, optimisticEnabled, queryClient])

  return (
    <div>
      {/* Strategy row (36px) */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          height: '36px',
          padding: '0 8px',
          gap: '8px',
          borderBottom: '1px solid #1a1a2e',
          cursor: 'pointer',
        }}
        onClick={onToggleExpand}
      >
        {/* Strategy ID */}
        <span
          style={{
            fontSize: '12px',
            fontFamily: 'monospace',
            color: '#d1d4dc',
            flex: 1,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
        >
          {strategy.strategy_id}
        </span>

        {/* Status badge */}
        <span
          style={{
            fontSize: '11px',
            fontFamily: 'monospace',
            padding: '2px 6px',
            borderRadius: '2px',
            border: `1px solid ${optimisticEnabled ? '#4ade80' : '#444444'}`,
            color: optimisticEnabled ? '#4ade80' : '#888888',
            backgroundColor: 'transparent',
            flexShrink: 0,
          }}
        >
          {optimisticEnabled ? 'ACTIVE' : 'OFF'}
        </span>

        {/* Toggle button */}
        <button
          onClick={(e) => {
            e.stopPropagation() // Don't expand/collapse row on toggle click
            void handleToggle()
          }}
          aria-pressed={optimisticEnabled}
          style={{
            border: `1px solid ${optimisticEnabled ? '#444444' : '#444444'}`,
            color: optimisticEnabled ? '#4ade80' : '#888888',
            backgroundColor: 'transparent',
            fontSize: '11px',
            fontFamily: 'monospace',
            padding: '2px 8px',
            borderRadius: '2px',
            cursor: 'pointer',
            flexShrink: 0,
          }}
        >
          {optimisticEnabled ? 'Disable Strategy' : 'Enable Strategy'}
        </button>

        {/* Expand indicator */}
        <span style={{ fontSize: '11px', color: '#888888', flexShrink: 0 }}>
          {isExpanded ? '▼' : '▶'}
        </span>
      </div>

      {/* Toggle error (3s transient) */}
      {toggleError && (
        <div
          style={{
            fontSize: '11px',
            color: '#f87171',
            fontFamily: 'monospace',
            padding: '4px 8px',
            backgroundColor: '#0a0a0a',
          }}
        >
          {toggleError}
        </div>
      )}

      {/* Expanded param form */}
      {isExpanded && (
        <ParamForm strategy={strategy} onClose={onToggleExpand} />
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// BacktestSection: Run Backtest button with polling
// ---------------------------------------------------------------------------

function BacktestSection() {
  const queryClient = useQueryClient()
  const [runId, setRunId] = useState<string | null>(null)
  const isRunning = runId !== null

  const { data: runStatus } = useStrategyRun(runId)

  // When run completes or fails: invalidate backtests query and clear runId (D-15)
  useEffect(() => {
    if (
      runStatus &&
      (runStatus.status === 'complete' || runStatus.status === 'failed')
    ) {
      void queryClient.invalidateQueries({ queryKey: ['backtests'] })
      setRunId(null)
    }
  }, [runStatus, queryClient])

  const handleRunBacktest = useCallback(async () => {
    if (isRunning) return // Guard double-submit (T-07-04-02)
    try {
      const res = await fetch(`${API_BASE}/backtests/run`, { method: 'POST' })
      if (res.ok) {
        const body = await res.json() as { run_id: string }
        setRunId(body.run_id)
      }
    } catch {
      // Silently ignore — UI stays idle
    }
  }, [isRunning])

  return (
    <div style={{ padding: '8px 8px 4px' }}>
      <button
        onClick={() => void handleRunBacktest()}
        disabled={isRunning}
        aria-disabled={isRunning}
        style={{
          border: isRunning ? '1px solid #333333' : '1px solid #444444',
          color: isRunning ? '#555555' : '#d1d4dc',
          backgroundColor: 'transparent',
          fontSize: '12px',
          fontFamily: 'monospace',
          padding: '4px 12px',
          borderRadius: '4px',
          cursor: isRunning ? 'not-allowed' : 'pointer',
        }}
      >
        {isRunning ? 'Running…' : 'Run Backtest'}
      </button>
    </div>
  )
}

// ---------------------------------------------------------------------------
// HeatmapAccordion: collapsed by default (D-spec)
// ---------------------------------------------------------------------------

function HeatmapAccordion() {
  const [open, setOpen] = useState(false)

  return (
    <div style={{ borderTop: '1px solid #222222', marginTop: '4px' }}>
      {/* Header row — 28px */}
      <div
        onClick={() => setOpen((prev) => !prev)}
        style={{
          display: 'flex',
          alignItems: 'center',
          height: '28px',
          padding: '0 8px',
          cursor: 'pointer',
          gap: '8px',
        }}
      >
        <span
          style={{
            fontSize: '11px',
            color: '#888888',
            fontFamily: 'monospace',
            letterSpacing: '0.05em',
            flex: 1,
          }}
        >
          OPTIMIZATION HEATMAP
        </span>
        <span style={{ fontSize: '11px', color: '#888888' }}>
          {open ? '▼' : '▶'}
        </span>
      </div>

      {/* Expanded content */}
      {open && (
        <div
          style={{
            padding: '8px',
            color: '#888888',
            fontSize: '12px',
            fontFamily: 'monospace',
          }}
        >
          Optimization heatmap — see{' '}
          <a
            href="/optimizations"
            style={{ color: '#4a90d9', textDecoration: 'none' }}
          >
            /optimizations
          </a>{' '}
          page
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// StrategyControlsPane — exported pane component
// ---------------------------------------------------------------------------

export default function StrategyControlsPane() {
  const { data: strategies, isError } = useStrategies()
  const [expandedId, setExpandedId] = useState<string | null>(null)

  const toggleExpand = useCallback((strategyId: string) => {
    setExpandedId((prev) => (prev === strategyId ? null : strategyId))
  }, [])

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        overflowY: 'auto',
        backgroundColor: '#000000',
      }}
    >
      {/* Error state */}
      {isError && (
        <div
          style={{
            padding: '12px 8px',
            color: '#f87171',
            fontSize: '12px',
            fontFamily: 'monospace',
          }}
        >
          Failed to load strategies. Is the API running?
        </div>
      )}

      {/* Empty state */}
      {!isError && strategies !== undefined && strategies.length === 0 && (
        <div
          style={{
            padding: '24px 8px',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            gap: '8px',
          }}
        >
          <div style={{ color: '#d1d4dc', fontSize: '12px', fontFamily: 'monospace' }}>
            No strategies found
          </div>
          <div style={{ color: '#888888', fontSize: '11px', fontFamily: 'monospace', textAlign: 'center' }}>
            Add a YAML file to config/strategies/ and restart the API.
          </div>
        </div>
      )}

      {/* Strategy list */}
      {!isError && strategies && strategies.length > 0 && (
        <div>
          {strategies.map((strategy) => (
            <StrategyRow
              key={strategy.strategy_id}
              strategy={strategy}
              isExpanded={expandedId === strategy.strategy_id}
              onToggleExpand={() => toggleExpand(strategy.strategy_id)}
            />
          ))}
        </div>
      )}

      {/* Run Backtest section (below strategy list) */}
      {!isError && (
        <BacktestSection />
      )}

      {/* Heatmap accordion (bottom of pane) */}
      <HeatmapAccordion />
    </div>
  )
}
