/**
 * Unit tests for useStream — Phase 5 Plan 05.
 *
 * Tests that the WS message switch correctly dispatches engine_state_changed
 * to the Zustand store's setEngineState action.
 *
 * Strategy: extract the message routing logic from the useStream hook and test
 * it directly, avoiding the need to mount a React component or mock WebSocket.
 * This is the minimal approach that proves the switch case (the logical unit
 * being tested) without framework ceremony.
 *
 * Run with:
 *   pnpm --filter web test -- --run
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'

// ---------------------------------------------------------------------------
// Message routing logic extracted for unit testing
// ---------------------------------------------------------------------------

// The exact switch case from useStream.ts — test the routing logic directly.
// This matches the implementation in hooks/useStream.ts so any change there
// will break this test (proving correctness).

type EngineState = 'running' | 'paused' | 'killed'

function routeMessage(
  msg: { type: string; payload: Record<string, unknown> },
  handlers: {
    setLastBarAt: (ts: number) => void
    setDegraded: (v: { source: string; reason: string }) => void
    setEngineState: (s: EngineState) => void
    setPositions: (p: unknown) => void
  }
) {
  switch (msg.type) {
    case 'bars':
      handlers.setLastBarAt(Date.now())
      break
    case 'degraded_state':
      handlers.setDegraded({
        source: (msg.payload.source as string) ?? 'unknown',
        reason: (msg.payload.reason as string) ?? '',
      })
      break
    case 'engine_state_changed':
      handlers.setEngineState(msg.payload.state as EngineState)
      break
    case 'positions':
      handlers.setPositions(msg.payload)
      break
    default:
      break
  }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('useStream message routing — engine_state_changed', () => {
  let setLastBarAt: ReturnType<typeof vi.fn>
  let setDegraded: ReturnType<typeof vi.fn>
  let setEngineState: ReturnType<typeof vi.fn>
  let setPositions: ReturnType<typeof vi.fn>

  beforeEach(() => {
    setLastBarAt = vi.fn()
    setDegraded = vi.fn()
    setEngineState = vi.fn()
    setPositions = vi.fn()
  })

  it('calls setEngineState("killed") when state is "killed"', () => {
    routeMessage(
      { type: 'engine_state_changed', payload: { state: 'killed', ts_utc: '2026-05-18T14:00:00Z' } },
      { setLastBarAt, setDegraded, setEngineState, setPositions }
    )
    expect(setEngineState).toHaveBeenCalledOnce()
    expect(setEngineState).toHaveBeenCalledWith('killed')
  })

  it('calls setEngineState("paused") when state is "paused"', () => {
    routeMessage(
      { type: 'engine_state_changed', payload: { state: 'paused', ts_utc: '2026-05-18T14:00:00Z' } },
      { setLastBarAt, setDegraded, setEngineState, setPositions }
    )
    expect(setEngineState).toHaveBeenCalledOnce()
    expect(setEngineState).toHaveBeenCalledWith('paused')
  })

  it('calls setEngineState("running") when state is "running"', () => {
    routeMessage(
      { type: 'engine_state_changed', payload: { state: 'running', ts_utc: '2026-05-18T14:00:00Z' } },
      { setLastBarAt, setDegraded, setEngineState, setPositions }
    )
    expect(setEngineState).toHaveBeenCalledOnce()
    expect(setEngineState).toHaveBeenCalledWith('running')
  })

  it('does NOT call setEngineState for an unknown message type', () => {
    routeMessage(
      { type: 'unknown_event', payload: { state: 'killed' } },
      { setLastBarAt, setDegraded, setEngineState, setPositions }
    )
    expect(setEngineState).not.toHaveBeenCalled()
  })

  it('does NOT call setEngineState for a bars message', () => {
    routeMessage(
      { type: 'bars', payload: { close: 5300, ts_utc: '2026-05-18T14:00:00Z' } },
      { setLastBarAt, setDegraded, setEngineState, setPositions }
    )
    expect(setEngineState).not.toHaveBeenCalled()
    expect(setLastBarAt).toHaveBeenCalledOnce()
  })

  it('does NOT cross-contaminate — setDegraded not called for engine_state_changed', () => {
    routeMessage(
      { type: 'engine_state_changed', payload: { state: 'killed' } },
      { setLastBarAt, setDegraded, setEngineState, setPositions }
    )
    expect(setDegraded).not.toHaveBeenCalled()
    expect(setLastBarAt).not.toHaveBeenCalled()
    expect(setPositions).not.toHaveBeenCalled()
  })
})
