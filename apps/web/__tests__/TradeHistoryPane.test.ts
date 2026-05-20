import { describe, it, expect } from 'vitest'

/**
 * TradeHistoryPane tests (Wave 0 RED stubs).
 *
 * These stubs fail intentionally. Plan 07-03 will implement the actual
 * TradeHistoryPane component and turn these GREEN.
 *
 * Requirements: UI-07 (Trade History panel), D-11 (DD histogram).
 */

describe('TradeHistoryPane', () => {
  it('renders trade rows from last backtest', () => {
    // TODO: implement in Plan 07-03
    // Verify the component renders a table row for each trade in the last backtest.
    // Uses GET /backtests (latestRunId) + GET /backtests/{run_id}/trades.
    expect(true).toBe(false) // RED stub — must fail until Plan 07-03 implements this
  })

  it('DD histogram series renders below zero', () => {
    // TODO: implement in Plan 07-03
    // Verify the cumulative drawdown histogram series is rendered as a HistogramSeries
    // below zero (drawdown values are negative) on the equity curve chart.
    // Uses drawdown field from GET /backtests/{run_id}/equity EquityPoint[].
    expect(true).toBe(false) // RED stub — must fail until Plan 07-03 implements this
  })
})
