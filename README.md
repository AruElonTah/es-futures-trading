# ES Futures Trading System

A modular Python + TypeScript trading system for E-mini S&P 500 (ES) futures. Focused on intraday strategies during the cash session (RTH 9:30–16:00 ET), with a Bloomberg-style terminal UI for chart visualization, position tracking, P&L analysis, and strategy control.

**Paper / backtest-only** — no live order routing. Designed so a real broker adapter can be slotted in later.

---

## What It Does

- **Opening Range Breakout (ORB)** strategy with ATR-based stop and R-multiple target
- **Walk-forward backtesting** via VectorBT — reproducible, leakage-free equity curves
- **Bloomberg-density 4-pane terminal** — Chart · Blotter · Trade History · Strategy Controls
- **TradingView Desktop integration** via MCP — chart control, drawing, replay, and live data
- **Real-time WebSocket feed** with monotonic sequence numbers and auto-reconnect
- **DuckDB + Parquet** local storage — zero-ops, columnar, fast grid-search queries
- **Strategy hot-reload** — edit `orb.yaml` params and reload the engine without restart

---

## Stack

| Layer | Tech |
|-------|------|
| Language | Python 3.12 + TypeScript 5 |
| Package manager | uv (Python) · pnpm 9 (JS) |
| Web framework | FastAPI 0.136 + uvicorn |
| Frontend | Next.js 16.2 · React 19 · Tailwind CSS |
| Charting | lightweight-charts v5.2 (vanilla) |
| State | TanStack Query v5 · Zustand |
| Backtest engine | VectorBT 1.0.0 |
| Storage | DuckDB 1.x + Parquet (pyarrow) |
| Indicators | pandas-ta-classic + hand-rolled ATR/VWAP/ORB |
| Calendars | pandas_market_calendars (CME/NYSE RTH) |
| Logging | structlog → JSON audit log |
| Testing | pytest · pytest-asyncio · hypothesis · Playwright |
| TV integration | TradingView MCP (78 tools) |

---

## Project Structure

```
.
├── apps/
│   └── web/                  # Next.js terminal UI
│       ├── app/dashboard/    # 4-pane Bloomberg layout
│       ├── components/       # Chart, Blotter, TradeHistory, StrategyControls, …
│       ├── hooks/            # useStream, useBacktests, useBars, useHotkeys
│       └── e2e/              # Playwright WebSocket reconnect tests
├── packages/
│   ├── trading-core/         # Python core — strategy, risk, storage, backtest
│   │   └── src/trading_core/
│   │       ├── strategy/     # ORBStrategy, StrategyRegistry
│   │       ├── risk/         # RiskManager, position sizing, drawdown guard
│   │       ├── storage/      # DuckDBStore, schema, Parquet ingest
│   │       ├── backtest/     # VectorBT engine, walk-forward splitter
│   │       └── events/       # EventBus, typed topic models
│   ├── api/                  # FastAPI app — REST + WebSocket
│   │   └── src/api/
│   │       ├── routes/       # /backtests, /strategies, /tv, /risk
│   │       └── ws.py         # ConnectionManager with seq-numbered fan-out
│   └── tv-bridge/            # TradingView MCP bridge (data source + chart control)
├── config/
│   └── strategies/orb.yaml   # Live-editable ORB parameters
└── data/                     # DuckDB files + Parquet bars (gitignored)
```

---

## Getting Started

### Prerequisites

- Python 3.11+ (3.12 recommended)
- [uv](https://github.com/astral-sh/uv) — `pip install uv`
- Node.js 18.18+ and pnpm 9 — `corepack enable && corepack prepare pnpm@9.15.0 --activate`
- TradingView Desktop (for live data via MCP)

### Install

```powershell
# Python deps (from repo root)
uv sync

# JS deps
pnpm install
```

### Run

```powershell
# API (from repo root)
uv run uvicorn api:app --reload --port 8000

# Frontend (separate terminal)
pnpm dev
```

Open **http://localhost:3000/dashboard** for the terminal UI.

### Test

```powershell
# Python (536 tests)
uv run pytest

# Frontend unit tests (22 tests)
pnpm --filter web exec vitest run

# E2E (requires live servers on :8000 and :3000)
pnpm --filter web test:e2e
```

---

## Architecture Notes

- **Trust the numbers** — every backtest result is reproducible, leakage-free, and survives walk-forward. All decisions compound on top of this.
- **EventBus** — typed async pub/sub (`trading_core.events`) connecting strategy signals → risk decisions → fills → WebSocket fan-out.
- **RTH enforcement** — every bar ingested and every backtest window is gated to 9:30–16:00 ET via `pandas_market_calendars`. ETH bars are discarded at ingest.
- **DuckDB as the source of truth** — bars, trades, positions, optimization runs, engine state, and audit log all live in DuckDB. Parquet for long-term bar storage.
- **TradingView MCP** — Python is the brain; the TV chart is the visualization and ground-truth replay surface. The backend drives chart state (symbol, timeframe, drawn ORB zones) via MCP tool calls.

---

## Configuration

Strategy parameters live in `config/strategies/orb.yaml` and can be edited live:

```yaml
name: opening_range_breakout
strategy_id: orb-v1
params:
  opening_range_minutes: 15
  atr_period: 14
  atr_stop_mult: 1.5
  r_target: 2.0
  ema_period: 20
  min_range_ticks: 2
```

Use the **Strategy Controls** pane in the UI (or `PUT /api/strategies/orb-v1/params`) to update params and hot-reload the engine without restarting.

---

## License

Private research project. Not financial advice.
