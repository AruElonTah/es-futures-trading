/**
 * API base URLs and shared type interfaces for the ES Futures Trading System.
 *
 * All REST calls target FastAPI on :8000; WebSocket stream on :8000 as well.
 * Environment variables allow override in CI or staging.
 */

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? 'http://localhost:8000'

export const WS_BASE =
  process.env.NEXT_PUBLIC_WS_BASE ?? 'ws://localhost:8000'

/** Shape of a bar row returned by GET /bars */
export interface BarRow {
  ts_utc: string
  open: number
  high: number
  low: number
  close: number
  volume: number
  rollover_seam: boolean
}

/** Shape of a backtest summary row from GET /backtests */
export interface BacktestRow {
  run_id: string
  strategy_id: string
  symbol: string
  timeframe: string
  from_ts: string
  to_ts: string
  param_hash: string
  equity_curve_path: string
  total_return: number | null
  cagr: number | null
  sharpe: number | null
  sortino: number | null
  calmar: number | null
  max_dd: number | null
  max_dd_duration_bars: number | null
  win_rate: number | null
  expectancy: number | null
  profit_factor: number | null
  trade_count: number | null
  avg_hold_bars: number | null
  created_at: string
}

/** Shape of an equity curve point from GET /backtests/{run_id}/equity */
export interface EquityPoint {
  ts_utc: string
  equity: number
  drawdown: number
}

/** Shape of a trade row from GET /backtests/{run_id}/trades */
export interface TradeRow {
  trade_id: string
  run_id: string
  signal_id: string
  strategy_id: string
  side: 'long' | 'short'
  entry_price: number
  exit_price: number
  exit_reason: 'target' | 'stop' | 'eod_flat' | 'manual'
  entry_ts_utc: string
  exit_ts_utc: string
  pnl: number
  size: number
  slippage_ticks: number
  mae: number
  mfe: number
  stop_price: number | null
  target_price: number | null
}
