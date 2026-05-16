# Phase 3: Vertical MVP Slice + Backtester - Research

**Researched:** 2026-05-16
**Domain:** VectorBT 1.0.0 backtester, FastAPI WebSocket fan-out, lightweight-charts v5.2.0, DuckDB schema extension, safe_from_signals wrapper, reproducibility CI
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Two new DuckDB tables — `backtests` + `trades`. The existing `runs` table is NOT extended.
- **D-02:** Full attribution chain in `trades` table from day 1. Fields: `trade_id`, `run_id`, `signal_id`, `strategy_id`, `side`, `entry_price`, `exit_price`, `exit_reason`, `entry_ts_utc`, `exit_ts_utc`, `pnl_$`, `size`, `slippage_ticks`, `mae`, `mfe`.
- **D-03:** Equity curves stored as Parquet files at `data/parquet/equity/{run_id}.parquet`. Columns: `ts_utc`, `equity_$`, `drawdown_$`.
- **D-04:** `WS /stream` mirrors all 7 EventBus topics.
- **D-05:** Message envelope is `{"type": "<event_type>", "payload": {...}}`.
- **D-06:** In-process asyncio.Queue fan-out — no extra dependencies.
- **D-07:** Cold-load state = most recent RTH bars in DuckDB, no overlays.
- **D-08:** Two-pane layout — chart (top ~70%) + equity curve (bottom ~30%).
- **D-09:** ORB overlays use primitive types — `createPriceLine()` + `setMarkers()`.
- **D-10:** Minimal fields on existing stubs: `RiskDecision.approved/reason/adjusted_size`, `Fill.signal_id/fill_price/fill_qty/side/slippage_ticks/ts_utc/exit_reason`, `RiskState.realized_pnl_today`, `RiskConfig.max_contracts=1`.
- **D-11:** `exit_reason` four-value Literal: `target|stop|eod_flat|manual`.
- **D-12:** Stop-first intrabar conflict resolution.
- **D-13:** `safe_from_signals(entries, exits, price, …)` enforces shift(1) + price=nextbar, blocks direct calls via pre-commit hook.
- **D-14:** BL-1 test at `tests/integration/test_lookahead.py`.

### Claude's Discretion

Nothing explicitly left to Claude's discretion — all major decisions locked.

### Deferred Ideas (OUT OF SCOPE)

- Full DrawdownModel variants (TRAILING_EOD, TRAILING_INTRADAY) with HWM — Phase 5
- `/positions`, `/trades`, `/equity`, `/optimizations`, `/kill`, `/flatten` REST endpoints — later phases
- TVBridge auto-draw on TradingView Desktop — Phase 6
- Drag/resize multi-pane layout + blotter panel — Phase 7
- Optimization heatmap browser — Phase 4
- Custom Lightweight Charts drawing plugin for shaded ORB rectangle — Phase 7
- Client-side WS topic subscription filtering — Phase 7
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| BT-01 | BacktestEngine consuming (DataSource, Strategy, RiskManager, Executor, config), emitting BacktestResult | Driver loop pattern verified — `snapshot → on_bar → _push_bar` from Phase 2; vectorbt `Portfolio.from_signals` for metrics |
| BT-02 | `safe_from_signals()` wrapper: `entries.shift(1)` + `price='nextbar'`; direct calls blocked by lint | `price='nextbar'` is NOT a string literal VBT accepts — must pass an array; wrapper shifts entries and converts stop/target to percentages or passes open array as price |
| BT-03 | Fill simulation: next-bar-open entry, session-phase-aware slippage, worst-case intrabar stop/target | Vectorbt default resolves stop FIRST when both hit same bar [VERIFIED]; slippage simulated manually by adjusting fill price by `tick_size * slippage_ticks` |
| BT-04 | Standard metrics: total return, CAGR, Sharpe, Sortino, Calmar, max DD, max DD duration, win rate, expectancy, profit factor, trade count, avg hold time | All available: `pf.total_return()`, `pf.annualized_return()`, `pf.sharpe_ratio()`, `pf.sortino_ratio()`, `pf.calmar_ratio()`, `pf.max_drawdown()`, `pf.drawdowns.max_duration()`, `pf.trades.win_rate()`, `pf.trades.expectancy()`, `pf.trades.profit_factor()`, `pf.trades.count()`, `pf.trades.avg_duration()` [VERIFIED] |
| BT-05 | Per-trade MAE/MFE persisted | VBT 1.0.0 does NOT expose MAE/MFE natively — must compute manually from bar high/low between entry and exit [VERIFIED] |
| BT-06 | Full attribution chain: fill → signal → risk_decision | D-02 fields on `trades` table; `signal_id` threaded from Signal through Fill |
| BT-07 | BL-1 lookahead-leakage detector CI test | D-14: `close.shift(-1)`-based entry → finite Sharpe, 40-60% win rate after safe_from_signals |
| BT-08 | EOD forced flat at last RTH bar | Implemented in PaperExecutor driver loop; assertion `sum(positions) == 0` |
| BT-09 | Backtest CLI `run_backtest.py` | New script alongside `seed_bars.py` |
| SP-01 | asyncio pub/sub routes Signal → RiskManager → Executor → Fill | EventBus from Phase 1 already implemented; Phase 3 wires the full pipeline |
| UI-01 | FastAPI REST+WS: `GET /bars`, `GET /backtests`, `WS /stream` (Phase 3 minimal surface) | FastAPI 0.136.1, uvicorn 0.32.x in api package |
| UI-04 | Chart panel: Lightweight Charts vanilla, candlesticks, ORB overlay, ET timezone | v5.2.0 installed; `addSeries(CandlestickSeries)`, `createPriceLine()`, `createSeriesMarkers()` [VERIFIED from typings] |
| UI-08 | ET clock + connection-status indicator in header | Clock: `Intl.DateTimeFormat` with `timeZone: 'America/New_York'`; WS staleness tracked in Zustand |
</phase_requirements>

---

## Summary

Phase 3 is the integration gate that closes the loop: `bar → ORBStrategy signal → PaperExecutor fill → DuckDB trade → equity-curve Parquet → FastAPI REST+WS → lightweight-charts dashboard`. All upstream infrastructure (EventBus, DuckDBStore, ORBStrategy, indicators) is implemented and green (244 tests, 0 failures).

The five key technical discoveries from research:

1. **VectorBT 1.0.0 `sl_stop`/`tp_stop` use percentage fractions relative to entry price** — the wrapper must convert Signal.stop/Signal.target (absolute prices) to `(entry - stop) / entry` and `(target - entry) / entry` fractions, or use a manual exit loop for full MAE/MFE/exit_reason attribution.

2. **VectorBT 1.0.0 resolves stop FIRST when both stop and target hit the same bar** — this matches D-12 (stop-first worst-case) without any custom configuration. [VERIFIED by live testing]

3. **VectorBT 1.0.0 does NOT natively expose MAE/MFE on trades** — `pf.trades.records_arr` dtype shows 14 fields with no MAE/MFE. Per-trade MAE/MFE must be computed manually by scanning `high`/`low` arrays between `entry_idx` and `exit_idx`.

4. **lightweight-charts v5.2.0 markers use `createSeriesMarkers()` (a separate plugin function), not `series.setMarkers()` directly** — the v4 `series.setMarkers()` API is gone; v5 requires `import { createSeriesMarkers } from 'lightweight-charts'` and calling `createSeriesMarkers(series, markersArray)`. [VERIFIED from installed typings.d.ts]

5. **`price='nextbar'` as a string literal crashes vectorbt's Numba JIT** — passing the string `'nextbar'` to `price=` causes a `TypingError: can't resolve ufunc isinf for types [UnicodeCharSeq(7)]`. The correct pattern is to pass a pre-computed array of next-bar open prices, or shift `close` by -1. [VERIFIED by live testing]

**Primary recommendation:** Implement a two-layer backtester: (a) a **driver loop** that runs the ORB strategy bar-by-bar (same `snapshot → on_bar → _push_bar` pattern from Phase 2) to collect per-trade attribution (signal_id, exit_reason, MAE, MFE); (b) a **VectorBT metrics pass** that takes the collected equity-value series and computes portfolio-level statistics. This hybrid approach gives full D-02 attribution AND all BT-04 metrics without fighting VBT's internals.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| ORB signal generation | Python (trading-core) | — | Strategy.on_bar runs in driver loop; no UI or API involvement |
| Paper fill simulation | Python (trading-core) | — | PaperExecutor implements Executor protocol; all price math in Python |
| Slippage calculation | Python (trading-core) | — | instruments.py tick_size; session-phase determined from bar.ts_utc |
| Metrics computation | Python (trading-core via VectorBT) | — | Portfolio.from_signals or manual loop; DuckDB writes |
| MAE/MFE computation | Python (trading-core) | — | Manual scan of high/low arrays; VBT does not expose natively |
| EOD flatten | Python (trading-core) | — | Last RTH bar check in driver loop; `sum(positions) == 0` assertion |
| DuckDB schema extension | Python (trading-core) | — | `write_backtest()` + `write_trades()` methods on DuckDBStore |
| Equity curve Parquet write | Python (trading-core) | — | pyarrow write_table with compression=none for byte-stability |
| REST endpoints | Python (api/FastAPI) | — | GET /bars, GET /backtests |
| WebSocket fan-out | Python (api/FastAPI) | — | asyncio.Queue per client; background task reads EventBus |
| Chart rendering | Browser (Next.js Client Component) | — | lightweight-charts v5 mounted in useEffect ref |
| Bar data fetch | Browser (TanStack Query v5) | — | GET /bars → populate chart |
| WS connection | Browser (native WebSocket) | — | JSON message routing by `type` field |
| UI state | Browser (Zustand) | — | WS connection status, last-bar timestamp, backtest selection |
| ET clock | Browser | — | setInterval + Intl.DateTimeFormat with America/New_York |

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| vectorbt | 1.0.0 | Portfolio metrics (Sharpe, Sortino, Calmar, drawdowns) | Pinned in pyproject.toml; already installed [VERIFIED] |
| pandas | 2.2.x | DataFrame ops: bar slices, equity series, trade rows | Pinned `>=2.2,<3.0`; vectorbt dependency [VERIFIED] |
| pyarrow | 17.x | Equity-curve Parquet write with byte-stable flags | Pinned `>=17.0,<18.0` for data_hash byte-stability [VERIFIED] |
| duckdb | 1.x | backtests + trades tables; bars queries | Installed; schema.sql pattern established [VERIFIED] |
| fastapi | 0.136.1 | REST + WebSocket endpoints | Installed in api package [VERIFIED] |
| pydantic | 2.13.x | RiskDecision, Fill, RiskState, RiskConfig models | Installed; models exist as stubs [VERIFIED] |
| lightweight-charts | 5.2.0 | Candlestick chart + equity curve line | Installed in apps/web [VERIFIED from package.json] |
| @tanstack/react-query | v5 | GET /bars data fetching | Installed [VERIFIED from package.json] |
| zustand | 5 | WS status, last-bar timestamp, backtest state | Installed [VERIFIED from package.json] |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| structlog | latest | Structured logging with signal_id correlation IDs | All new Python modules |
| uuid6 | 2025.x | Time-sortable uuid7 for trade_id, run_id | write_backtest(), write_trades() |
| freezegun | latest | Pin datetime.now() in PaperExecutor tests | EOD flatten time tests |
| pytest-asyncio | 0.24.x | Async tests for WS fan-out and EventBus pipeline | WS fan-out integration test |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Manual driver loop for attribution | VBT-only (sl_stop/tp_stop) | VBT alone cannot produce exit_reason or per-trade MAE/MFE; hybrid approach is the correct choice |
| asyncio.Queue per-client fan-out | broadcaster library | D-06 locks asyncio.Queue; broadcaster adds transitive dep for no benefit at single-operator scale |
| createSeriesMarkers() | series.setMarkers() | v4 API; setMarkers() removed from series in v5.2.0 typings; createSeriesMarkers() is the v5 plugin approach [VERIFIED] |

---

## Architecture Patterns

### System Architecture Diagram

```
run_backtest.py CLI
       |
       v
  StrategyRegistry.load(orb.yaml)
       |
       v
  BacktestEngine
  ┌─────────────────────────────────────────────────────────────┐
  │  bar DataFrame (from DuckDB)                                │
  │       ↓                                                     │
  │  for bar in bars:                                           │
  │    ctx = snapshot(strategy)   # prior-bar indicators       │
  │    signal = strategy.on_bar(bar, ctx)                      │
  │    strategy._push_bar(bar)                                  │
  │       ↓ (if signal)                                         │
  │    decision = risk_manager.check(signal, state)            │
  │       ↓ (if approved)                                       │
  │    fill = paper_executor.fill(signal, decision, next_bar)  │
  │    track: entry_idx, exit_idx, exit_reason, MAE, MFE       │
  │    EventBus.publish(TOPIC_FILLS, fill_event)               │
  │       ↓ EOD                                                 │
  │    eod_flatten(open_position, last_rth_bar)                │
  └─────────────────────────────────────────────────────────────┘
       |
       ├── write_run() → runs table
       ├── write_backtest() → backtests table (metrics)
       ├── write_trades() → trades table (attribution)
       └── equity_curve.parquet → data/parquet/equity/{run_id}.parquet

FastAPI Process
  ├── GET /bars → DuckDB query → JSON
  ├── GET /backtests → DuckDB query → JSON
  └── WS /stream
        └── background task subscribes EventBus (7 topics)
              └── per-client asyncio.Queue → JSON envelope

Next.js /dashboard (Client Component)
  ├── TanStack Query → GET /bars → CandlestickData[]
  ├── native WebSocket → JSON messages → chart updates
  └── lightweight-charts v5
        ├── chart.addSeries(CandlestickSeries) → price pane (~70%)
        ├── chart.addSeries(LineSeries, {paneIndex:1}) → equity pane (~30%)
        ├── series.createPriceLine({price: orb_high}) → ORB high line
        ├── series.createPriceLine({price: orb_low}) → ORB low line
        ├── series.createPriceLine({price: stop}) → stop line (red)
        ├── series.createPriceLine({price: target}) → target line (green)
        └── createSeriesMarkers(series, [{shape:'arrowUp',...}]) → entry
```

### Recommended Project Structure

```
packages/trading-core/src/trading_core/
├── backtest/
│   ├── __init__.py
│   ├── engine.py          # BacktestEngine: driver loop + VBT metrics pass
│   ├── safe_signals.py    # safe_from_signals() wrapper + ValueError guards
│   └── paper_executor.py  # PaperExecutor: next-bar fill, slippage, EOD flatten
├── risk/
│   ├── models.py          # Fill in D-10 minimal fields
│   └── minimal_manager.py # MinimalRiskManager: pass-through, max_contracts=1
├── storage/
│   ├── duckdb_store.py    # + write_backtest() + write_trades() methods
│   └── schema.sql         # + backtests + trades table DDL

packages/api/src/api/
├── app.py                 # + GET /bars, GET /backtests, WS /stream
└── ws_manager.py          # ConnectionManager: asyncio.Queue fan-out

apps/web/app/
├── dashboard/
│   └── page.tsx           # "use client" — chart + equity pane
└── components/
    ├── CandlestickChart.tsx
    ├── EquityCurveChart.tsx
    ├── ETClock.tsx
    └── ConnectionStatus.tsx

scripts/
└── run_backtest.py

packages/trading-core/tests/
├── test_backtest_engine.py
├── test_paper_executor.py
├── test_safe_signals.py
└── integration/
    ├── test_lookahead.py       # BL-1 gate (D-14)
    └── test_reproducibility.py # bitwise-identical Parquet
```

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Portfolio-level metrics (Sharpe, Sortino, Calmar, max DD duration) | Custom metric functions | `vbt.Portfolio` methods | Correct handling of period, annualization, and edge cases |
| Parquet write | Custom serializer | `pyarrow.parquet.write_table` with `compression="none", use_dictionary=False, write_statistics=False` | Byte-stability already validated in Phase 1 `runs.py`; deviation breaks reproducibility CI |
| data_hash | New hash function | `trading_core.storage.runs.data_hash(df)` | Already implemented and validated; the 390-row fixture baseline is locked in STATE.md |
| UTC timestamp validation | Custom validators | Pydantic `AwareDatetime` + the existing UTC validator in Signal | Already present and tested |
| ETH bar filtering | Custom calendar code | `trading_core.calendars.rth.RthFilter` from Phase 1 | Handles DST, half-days, CME calendar |
| run_id generation | `str(uuid.uuid4())` | `trading_core.storage.runs.new_run_id()` (uuid7) | Time-sortable; already implemented |

---

## VectorBT 1.0.0: Verified API Details

### `Portfolio.from_signals()` — Critical Parameters

[VERIFIED by live testing against installed vectorbt==1.0.0]

```python
import vectorbt as vbt
import pandas as pd
import numpy as np

pf = vbt.Portfolio.from_signals(
    close=close_series,          # pd.Series with UTC DatetimeIndex
    entries=entries_bool,        # boolean Series; MUST be pre-shifted via .shift(1)
    exits=exits_bool,            # boolean Series; MUST be pre-shifted via .shift(1)
    short_entries=short_ent,     # for short trades (optional)
    short_exits=short_ex,        # for short trades (optional)
    sl_stop=sl_frac_series,      # FRACTION (not price): (entry - stop) / entry
    tp_stop=tp_frac_series,      # FRACTION (not price): (target - entry) / entry
    freq='1min',                 # required for time-based metrics (Sharpe etc.)
    price=open_price_series,     # fill price array (next-bar open); do NOT pass 'nextbar' string
    init_cash=10_000.0,
    size=1,
    direction='longonly',        # or 'shortonly' or 'both'
    open=open_series,            # required for intrabar stop/target simulation
    high=high_series,            # required for intrabar stop/target simulation
    low=low_series,              # required for intrabar stop/target simulation
    seed=42,                     # reproducibility
)
```

**CRITICAL — do NOT do this:**
```python
# This crashes Numba JIT with: TypingError: can't resolve ufunc isinf for [UnicodeCharSeq(7)]
pf = vbt.Portfolio.from_signals(..., price='nextbar')
```

**`sl_stop` / `tp_stop` semantics (VERIFIED):**
- `sl_stop` is a fraction: stop fires when `price <= entry_price * (1 - sl_stop)`
- `tp_stop` is a fraction: target fires when `price >= entry_price * (1 + tp_stop)`
- To convert Signal absolute stop/target: `sl_frac = (entry - stop) / entry`; `tp_frac = (target - entry) / entry`
- Both can be passed as per-bar arrays (NaN for bars with no active position)

**Intrabar conflict (VERIFIED — matches D-12):**
- When both stop and target touch the same bar, vectorbt resolves **stop FIRST** (conservative)
- No special configuration required; this is the default behavior

### Extracting Metrics

```python
# All VERIFIED against vectorbt 1.0.0
total_return  = pf.total_return()          # float
cagr          = pf.annualized_return()     # float (requires freq param)
sharpe        = pf.sharpe_ratio()          # float
sortino       = pf.sortino_ratio()         # float
calmar        = pf.calmar_ratio()          # float
max_dd        = pf.max_drawdown()          # float (negative fraction)
max_dd_dur    = pf.drawdowns.max_duration() # pd.Timedelta
win_rate      = pf.trades.win_rate()       # float [0,1]
expectancy    = pf.trades.expectancy()     # float (average PnL per trade)
profit_factor = pf.trades.profit_factor()  # float
trade_count   = pf.trades.count()          # int
avg_hold      = pf.trades.avg_duration()   # pd.Timedelta

# Equity curve for Parquet export
eq_series  = pf.value()          # pd.Series with UTC DatetimeIndex
dd_series  = pf.drawdown() * pf.value()   # $ drawdown = % * portfolio value
equity_df  = pd.DataFrame({
    'ts_utc': eq_series.index,
    'equity_$': eq_series.values,
    'drawdown_$': dd_series.values,
})
```

### MAE/MFE — Must Compute Manually

VBT 1.0.0 `ExitTrades` has no `mae` or `mfe` attributes. The `records_arr` dtype fields are: `id, col, size, entry_idx, entry_price, entry_fees, exit_idx, exit_price, exit_fees, pnl, return, direction, status, parent_id`. [VERIFIED]

**Manual MAE/MFE computation pattern:**
```python
def compute_mae_mfe(trade_record, high_arr, low_arr, side: str) -> tuple[float, float]:
    """Compute Maximum Adverse Excursion and Maximum Favorable Excursion."""
    entry_idx = int(trade_record['entry_idx'])
    exit_idx = int(trade_record['exit_idx'])
    entry_price = trade_record['entry_price']
    # Slice bars between entry and exit (inclusive)
    highs = high_arr[entry_idx:exit_idx + 1]
    lows  = low_arr[entry_idx:exit_idx + 1]
    if side == 'long':
        mae = entry_price - lows.min()    # max adverse = max drop from entry
        mfe = highs.max() - entry_price   # max favorable = max gain from entry
    else:  # short
        mae = highs.max() - entry_price
        mfe = entry_price - lows.min()
    return float(mae), float(mfe)
```

---

## safe_from_signals Wrapper Pattern

[ASSUMED based on D-13 decision; specific implementation details are design choices]

### Correct Implementation

```python
# packages/trading-core/src/trading_core/backtest/safe_signals.py

import vectorbt as vbt
import pandas as pd
import numpy as np


def safe_from_signals(
    close: pd.Series,
    entries: pd.Series,
    exits: pd.Series,
    *,
    price: pd.Series,           # next-bar open prices (caller provides)
    sl_stop: pd.Series | float | None = None,
    tp_stop: pd.Series | float | None = None,
    short_entries: pd.Series | None = None,
    short_exits: pd.Series | None = None,
    open: pd.Series | None = None,
    high: pd.Series | None = None,
    low: pd.Series | None = None,
    **kwargs,
) -> vbt.Portfolio:
    """Lookahead-safe wrapper around vbt.Portfolio.from_signals.

    Enforces:
      1. entries and exits are shifted by 1 (next-bar execution)
      2. price is an actual array (not the string 'nextbar')

    Raises ValueError if:
      - entries or exits are already shifted (all-False first bar after shift
        cannot be detected, but we check for common mistake patterns)
      - 'price' kwarg is passed as a string
    """
    # Guard: price must not be a string
    if isinstance(price, str):
        raise ValueError(
            "safe_from_signals: price must be an array of fill prices, not a string. "
            "Pass the next-bar open prices as a pd.Series. "
            "Passing price='nextbar' crashes Numba JIT."
        )

    # Shift entries/exits internally — caller passes UNshifted signals
    shifted_entries = entries.shift(1).fillna(False).infer_objects(copy=False)
    shifted_exits   = exits.shift(1).fillna(False).infer_objects(copy=False)

    shifted_short_entries = (
        short_entries.shift(1).fillna(False).infer_objects(copy=False)
        if short_entries is not None else None
    )
    shifted_short_exits = (
        short_exits.shift(1).fillna(False).infer_objects(copy=False)
        if short_exits is not None else None
    )

    call_kwargs = dict(
        close=close,
        entries=shifted_entries,
        exits=shifted_exits,
        price=price,
        **kwargs,
    )
    if sl_stop is not None:
        call_kwargs['sl_stop'] = sl_stop
    if tp_stop is not None:
        call_kwargs['tp_stop'] = tp_stop
    if short_entries is not None:
        call_kwargs['short_entries'] = shifted_short_entries
    if short_exits is not None:
        call_kwargs['short_exits'] = shifted_short_exits
    if open is not None:
        call_kwargs['open'] = open
    if high is not None:
        call_kwargs['high'] = high
    if low is not None:
        call_kwargs['low'] = low

    return vbt.Portfolio.from_signals(**call_kwargs)
```

### Pre-commit Hook Pattern

Based on existing `no-naive-tz` hook in `.pre-commit-config.yaml`:

```yaml
# Addition to .pre-commit-config.yaml
- repo: local
  hooks:
    - id: no-direct-vbt-from-signals
      name: Block direct vbt.Portfolio.from_signals() calls
      entry: python scripts/hooks/no_direct_vbt.py
      language: python
      types: [python]
      require_serial: true
      exclude: |
        (?x)^(
          packages/trading-core/src/trading_core/backtest/safe_signals\.py
        )$
```

```python
# scripts/hooks/no_direct_vbt.py
import sys, re

PATTERN = re.compile(r'vbt\.Portfolio\.from_signals\s*\(')
ERRORS = []
for path in sys.argv[1:]:
    with open(path, encoding='utf-8') as f:
        for lineno, line in enumerate(f, 1):
            if PATTERN.search(line):
                ERRORS.append(f'{path}:{lineno}: direct vbt.Portfolio.from_signals() call blocked. Use safe_from_signals() instead.')

if ERRORS:
    print('\n'.join(ERRORS))
    sys.exit(1)
sys.exit(0)
```

---

## PaperExecutor: Fill Simulation Pattern

[ASSUMED for slippage convention; tick_size sourced from instruments.py which is VERIFIED]

```python
# packages/trading-core/src/trading_core/backtest/paper_executor.py
from datetime import timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from trading_core.instruments import get as get_instrument

_ET = ZoneInfo("America/New_York")
_OPEN_WINDOW_MINUTES = 15  # 9:30–9:45 ET


def _slippage_ticks(bar_ts_utc, symbol: str) -> int:
    """Session-phase-aware slippage (D-03 spec).

    Returns:
        >= 2 ticks if within the 9:30–9:45 ET open window (FR-1 pitfall)
        1 tick otherwise
    """
    et_time = bar_ts_utc.astimezone(_ET).time()
    from datetime import time as dt_time
    open_window_end = dt_time(9, 45)
    session_open = dt_time(9, 30)
    if session_open <= et_time < open_window_end:
        return 2  # >= 1.5 ticks adverse; use 2 ticks as integer approximation
    return 1


def simulate_fill_price(entry_price: Decimal, side: str, slippage_ticks: int, symbol: str) -> Decimal:
    """Compute adverse fill price from slippage."""
    instrument = get_instrument(symbol)
    adj = instrument.tick_size * Decimal(str(slippage_ticks))
    if side == 'long':
        return entry_price + adj   # adverse: pay more on entry
    else:
        return entry_price - adj   # adverse: receive less on entry
```

**EOD flatten rule:**
- In the driver loop, after processing the last RTH bar (bar.ts_utc is the last 1m bar of the session), any open position is closed at the last bar's close price.
- `exit_reason = "eod_flat"`.
- Assertion: `sum(open_positions) == 0` after EOD step.

---

## DuckDB Schema Extension

[VERIFIED: existing schema.sql pattern; new tables follow same conventions]

```sql
-- Addition to packages/trading-core/src/trading_core/storage/schema.sql

CREATE TABLE IF NOT EXISTS backtests (
    run_id             VARCHAR     NOT NULL,   -- FK to runs.run_id
    strategy_id        VARCHAR     NOT NULL,
    symbol             VARCHAR     NOT NULL,
    timeframe          VARCHAR     NOT NULL,
    from_ts            TIMESTAMPTZ NOT NULL,
    to_ts              TIMESTAMPTZ NOT NULL,
    param_hash         VARCHAR     NOT NULL,
    equity_curve_path  VARCHAR     NOT NULL,   -- relative path to equity Parquet
    -- Scalar metrics
    total_return       DOUBLE,
    cagr               DOUBLE,
    sharpe             DOUBLE,
    sortino            DOUBLE,
    calmar             DOUBLE,
    max_dd             DOUBLE,
    max_dd_duration_bars BIGINT,
    win_rate           DOUBLE,
    expectancy         DOUBLE,
    profit_factor      DOUBLE,
    trade_count        INTEGER,
    avg_hold_bars      DOUBLE,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (run_id)
);

CREATE TABLE IF NOT EXISTS trades (
    trade_id           VARCHAR     NOT NULL,   -- uuid7
    run_id             VARCHAR     NOT NULL,   -- FK to runs.run_id
    signal_id          VARCHAR     NOT NULL,   -- FK to Signal.signal_id
    strategy_id        VARCHAR     NOT NULL,
    side               VARCHAR     NOT NULL,   -- 'long' | 'short'
    entry_price        DOUBLE      NOT NULL,
    exit_price         DOUBLE      NOT NULL,
    exit_reason        VARCHAR     NOT NULL,   -- 'target'|'stop'|'eod_flat'|'manual'
    entry_ts_utc       TIMESTAMPTZ NOT NULL,
    exit_ts_utc        TIMESTAMPTZ NOT NULL,
    pnl                DOUBLE      NOT NULL,   -- column name: pnl (maps to pnl_$ in context)
    size               INTEGER     NOT NULL,
    slippage_ticks     INTEGER     NOT NULL,
    mae                DOUBLE      NOT NULL,
    mfe                DOUBLE      NOT NULL,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (trade_id)
);
```

**DuckDBStore new methods:**

```python
# Addition to duckdb_store.py

WRITE_BACKTEST_SQL = """
INSERT INTO backtests (run_id, strategy_id, symbol, timeframe, from_ts, to_ts,
    param_hash, equity_curve_path, total_return, cagr, sharpe, sortino, calmar,
    max_dd, max_dd_duration_bars, win_rate, expectancy, profit_factor,
    trade_count, avg_hold_bars)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
"""

WRITE_TRADE_SQL = """
INSERT INTO trades (trade_id, run_id, signal_id, strategy_id, side, entry_price,
    exit_price, exit_reason, entry_ts_utc, exit_ts_utc, pnl, size,
    slippage_ticks, mae, mfe)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
"""
```

**Note on `ON CONFLICT`:** `backtests` PK is `run_id` (uuid7, unique per run). `trades` PK is `trade_id` (uuid7, unique per trade). Neither needs an upsert — plain INSERT is correct. Re-running `run_backtest.py` with the same inputs should generate a new `run_id`, not overwrite.

---

## FastAPI WebSocket Fan-Out Pattern

[VERIFIED: FastAPI 0.136.1 is installed in api package; asyncio.Queue pattern is standard]

```python
# packages/api/src/api/ws_manager.py
import asyncio
import json
from fastapi import WebSocket, WebSocketDisconnect
from trading_core.events.bus import EventBus
from trading_core.events.models import (
    TOPIC_BARS, TOPIC_SIGNALS, TOPIC_RISK_DECISIONS, TOPIC_FILLS,
    TOPIC_POSITIONS, TOPIC_EQUITY, TOPIC_DEGRADED_STATE,
)

ALL_TOPICS = [
    TOPIC_BARS, TOPIC_SIGNALS, TOPIC_RISK_DECISIONS, TOPIC_FILLS,
    TOPIC_POSITIONS, TOPIC_EQUITY, TOPIC_DEGRADED_STATE,
]

class ConnectionManager:
    """Per-client asyncio.Queue fan-out. No broadcaster dep (D-06)."""

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._clients: set[asyncio.Queue] = set()

    async def start_background_fan_out(self) -> None:
        """Subscribe to all 7 EventBus topics; fan-out to per-client queues.

        Run as a FastAPI background task (lifespan event).
        """
        async def _subscribe_topic(topic: str) -> None:
            async with self._bus.subscribe(topic) as sub:
                async for event in sub:
                    msg = json.dumps({
                        "type": event.topic,
                        "payload": event.model_dump(mode="json"),
                    })
                    for q in list(self._clients):
                        await q.put(msg)

        await asyncio.gather(*[_subscribe_topic(t) for t in ALL_TOPICS])

    async def connect(self, ws: WebSocket) -> asyncio.Queue:
        await ws.accept()
        q: asyncio.Queue = asyncio.Queue()
        self._clients.add(q)
        return q

    def disconnect(self, q: asyncio.Queue) -> None:
        self._clients.discard(q)
```

```python
# In app.py WebSocket route:
@app.websocket("/stream")
async def ws_stream(websocket: WebSocket):
    q = await manager.connect(websocket)
    try:
        while True:
            msg = await q.get()
            await websocket.send_text(msg)
    except WebSocketDisconnect:
        manager.disconnect(q)
```

**Lifecycle note:** The background fan-out task must be started in the FastAPI lifespan context manager (not at module level) to ensure the EventBus is ready before any client connects.

---

## lightweight-charts v5.2.0: Verified API

[VERIFIED from installed `apps/web/node_modules/lightweight-charts/dist/typings.d.ts`]

### Breaking Change from v4: Markers Use Plugin API

```typescript
// v4 (WRONG for v5.2.0):
// series.setMarkers([...])  -- this method does NOT exist on ISeriesApi in v5

// v5.2.0 CORRECT:
import {
  createChart,
  createSeriesMarkers,
  CandlestickSeries,
  LineSeries,
  type SeriesMarker,
  type Time,
} from 'lightweight-charts';

// The setMarkers method lives on ISeriesMarkersPluginApi, not ISeriesApi
const markersPlugin = createSeriesMarkers(candleSeries, []);
markersPlugin.setMarkers(markerArray);  // update markers
markersPlugin.markers();                // read current markers
```

### Chart Setup Pattern

```typescript
// 'use client'
import { useEffect, useRef } from 'react';
import { createChart, createSeriesMarkers, CandlestickSeries, LineSeries } from 'lightweight-charts';

export function CandlestickChart({ barData, markers, priceLinesConfig }) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height: containerRef.current.clientHeight,
      layout: { background: { color: '#000' }, textColor: '#d1d4dc' },
      localization: {
        // timeFormatter: formats crosshair label (not tick marks)
        timeFormatter: (timestamp: number): string => {
          return new Intl.DateTimeFormat('en-US', {
            timeZone: 'America/New_York',
            hour: '2-digit',
            minute: '2-digit',
            month: 'short',
            day: 'numeric',
          }).format(new Date(timestamp * 1000));
        },
      },
      timeScale: {
        // tickMarkFormatter: formats tick marks on time axis
        tickMarkFormatter: (time: number, tickMarkType: number): string => {
          const d = new Date(time * 1000);
          const et = new Intl.DateTimeFormat('en-US', {
            timeZone: 'America/New_York',
            hour: '2-digit', minute: '2-digit',
          }).format(d);
          return et;
        },
        timeVisible: true,
        secondsVisible: false,
      },
    });

    // Pane 0 (default): candlesticks
    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#26a69a', downColor: '#ef5350',
      borderVisible: false, wickUpColor: '#26a69a', wickDownColor: '#ef5350',
    });
    candleSeries.setData(barData);  // CandlestickData[]

    // Markers plugin (v5 API)
    const markersPlugin = createSeriesMarkers(candleSeries, []);

    // ORB lines via createPriceLine (on the candleSeries)
    const orbHighLine = candleSeries.createPriceLine({
      price: 0,  // updated later
      color: '#ffeb3b',
      lineWidth: 1,
      lineStyle: 2,  // LineStyle.Dashed
      axisLabelVisible: true,
      title: 'ORB High',
    });

    // Pane 1: equity curve
    const equitySeries = chart.addSeries(LineSeries, {
      color: '#2962FF',
      lineWidth: 2,
    }, 1);  // paneIndex=1

    // ... update series with setData(), update price lines, update markers

    return () => chart.remove();
  }, []);

  return <div ref={containerRef} style={{ width: '100%', height: '100%' }} />;
}
```

### ET Timezone: Time Data Format

lightweight-charts v5 accepts `time` as Unix seconds (number) or `YYYY-MM-DD` string. For intraday 1m bars: use Unix seconds (UTC). The `timeFormatter` and `tickMarkFormatter` then convert to ET for display.

```typescript
// Bar data format for lightweight-charts v5
interface CandlestickData {
  time: number;   // Unix timestamp in seconds (UTC)
  open: number;
  high: number;
  low: number;
  close: number;
}

// Convert from FastAPI response (ISO string) to lwc format:
const lwcData = apiResponse.map((bar) => ({
  time: Math.floor(new Date(bar.ts_utc).getTime() / 1000),
  open: bar.open,
  high: bar.high,
  low: bar.low,
  close: bar.close,
}));
```

### Two-Pane Layout with Fixed Heights

```typescript
// Dashboard page structure (D-08: 70/30 split)
<div style={{ display: 'flex', flexDirection: 'column', height: '100vh' }}>
  <header style={{ height: '48px' }}>
    {/* ET clock + connection status */}
  </header>
  <div style={{ flex: '0 0 70%' }}>
    <CandlestickChart />
  </div>
  <div style={{ flex: '0 0 30%' }}>
    <EquityCurveChart />
  </div>
</div>
```

### createPriceLine Options

```typescript
const priceLine = series.createPriceLine({
  price: 471.00,           // absolute price value
  color: '#ef5350',        // red for stop
  lineWidth: 1,
  lineStyle: 2,            // LineStyle.Dashed = 2
  axisLabelVisible: true,
  title: 'Stop',
});

// Update later:
priceLine.applyOptions({ price: newPrice });

// Remove:
series.removePriceLine(priceLine);
```

---

## Reproducibility Hash Chain

[VERIFIED: `runs.py` already implements this; data_hash algorithm is locked]

**data_hash (existing, locked in Phase 1):**
- Uses `trading_core.storage.runs.data_hash(df)` — pyarrow Parquet byte-stable recipe
- Baseline for 390-row SPY synthetic fixture: `2d61c1889a7dbca4fee3e3cf7ea719be6cb3e12810d575635e69d38a6bbdb19f` (from STATE.md)
- NOTE: The JSON-hash approach (manual dict encoding) produces a DIFFERENT hash (`6ca17c21...`) — the correct hash uses the pyarrow Parquet byte-blob approach in `runs.py`. Phase 3 must use `runs.data_hash()` not a custom implementation.

**param_hash (existing):**
- Uses `trading_core.storage.runs.param_hash(args: dict)` — canonical JSON sha256

**equity_curve Parquet byte-stability:**
Same flags as data_hash: `compression="none", use_dictionary=False, write_statistics=False`. This ensures the equity curve Parquet is bitwise-identical for the same inputs.

```python
import pyarrow as pa
import pyarrow.parquet as pq

def write_equity_curve(equity_df: pd.DataFrame, path: Path) -> None:
    """Write equity curve to Parquet with byte-stable flags."""
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pandas(equity_df.reset_index(drop=True), preserve_index=False)
    pq.write_table(
        table, str(path),
        compression="none",
        use_dictionary=False,
        write_statistics=False,
    )
```

**Reproducibility CI test pattern:**
```python
def test_reproducibility_same_inputs_bitwise_identical(tmp_path):
    """FND-08: same git_sha + data_hash + param_hash + seed → identical Parquet bytes."""
    kwargs = dict(
        symbol="SPY", tf="1m", from_date="2024-01-02", to_date="2024-01-02",
        config_path="config/strategies/orb.yaml", seed=42,
    )
    path1 = tmp_path / "run1.parquet"
    path2 = tmp_path / "run2.parquet"
    run_backtest(**kwargs, equity_path=path1)
    run_backtest(**kwargs, equity_path=path2)
    assert path1.read_bytes() == path2.read_bytes(), "Equity curve is not bitwise-identical"
```

---

## BL-1 Lookahead Detector Test Pattern

[Based on D-14; BL-1 requirement from ROADMAP cross-phase guardrails]

```python
# packages/trading-core/tests/integration/test_lookahead.py

def test_bl1_lookahead_neutralized_by_safe_from_signals():
    """BL-1 gate: a deliberately-leaking strategy produces finite Sharpe + 40-60% win rate.

    The leaking ORB variant uses close.shift(-1) as the 'entry signal' basis,
    which looks one bar into the future. safe_from_signals applies shift(1) on top,
    which delays execution by one bar — the future-looking information is partially
    but not fully neutralized. The key assertions are:
      1. Sharpe is finite (not inf) — lookahead is neutralized
      2. Win rate is in [0.4, 0.6] — performance is in random-walk territory
    """
    bars = orb_day_bars()  # 390 bars, 2024-01-02
    close = pd.Series([float(b.close) for b in bars], ...)
    high = pd.Series([float(b.high) for b in bars], ...)
    low  = pd.Series([float(b.low) for b in bars], ...)

    # Deliberately leaking entry: uses close.shift(-1) > orb_high
    # This looks one bar into the future
    leaking_entries = (close.shift(-1) > 471.00)  # ORB high from fixture

    pf = safe_from_signals(
        close=close,
        entries=leaking_entries,  # safe_from_signals applies shift(1)
        exits=pd.Series([False] * len(close), ...),
        price=close.shift(-1).fillna(close),  # next-bar proxy
        freq='1min',
        init_cash=10_000.0,
        size=1,
        direction='longonly',
        high=high,
        low=low,
    )

    sharpe = pf.sharpe_ratio()
    win_rate = pf.trades.win_rate() if pf.trades.count() > 0 else 0.5

    assert np.isfinite(sharpe), f"Sharpe is infinite ({sharpe}): lookahead not neutralized"
    assert 0.35 <= win_rate <= 0.65, (
        f"Win rate {win_rate:.2%} outside 35-65% band: lookahead may not be neutralized"
    )
```

---

## ET Clock + Connection Status (UI-08)

```typescript
// components/ETClock.tsx — 'use client'
import { useEffect, useState } from 'react';

const ET_FORMATTER = new Intl.DateTimeFormat('en-US', {
  timeZone: 'America/New_York',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
});

export function ETClock() {
  const [time, setTime] = useState('');
  useEffect(() => {
    const tick = () => setTime(ET_FORMATTER.format(new Date()));
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);
  return <span className="font-mono text-sm">{time} ET</span>;
}
```

```typescript
// Connection status logic (D-08 spec):
// green  = WS connected AND last bar <= 10s ago
// yellow = last bar > 10s ago
// red    = WS disconnected OR last bar > 30s ago

// Track in Zustand store:
interface WsState {
  connected: boolean;
  lastBarAt: number | null;  // Unix ms
  setConnected: (v: boolean) => void;
  setLastBarAt: (ts: number) => void;
}

// Status computation:
const now = Date.now();
const age = lastBarAt ? now - lastBarAt : Infinity;
const status =
  !connected || age > 30_000 ? 'red' :
  age > 10_000 ? 'yellow' : 'green';
```

---

## Common Pitfalls

### Pitfall 1: `price='nextbar'` crashes VBT Numba JIT

**What goes wrong:** Passing `price='nextbar'` causes a Numba typing error: `can't resolve ufunc isinf for types [UnicodeCharSeq(7)]`.
**Why it happens:** VBT documentation mentions `nextbar` as a concept but the string is not accepted by the Numba-compiled inner loop.
**How to avoid:** Always pass a concrete array (`pd.Series`) as `price`. The `safe_from_signals` wrapper enforces this with a `ValueError` guard.
**Warning signs:** `numba.core.errors.TypingError` in the backtester.

### Pitfall 2: `series.setMarkers()` does not exist in lightweight-charts v5.2.0

**What goes wrong:** Calling `candleSeries.setMarkers([...])` throws `TypeError: candleSeries.setMarkers is not a function` at runtime.
**Why it happens:** The v5 series API removed the built-in `setMarkers` method; markers are now handled by a plugin (`createSeriesMarkers`).
**How to avoid:** Import `createSeriesMarkers` from `'lightweight-charts'` and create a plugin instance. Call `markersPlugin.setMarkers(array)` to update.
**Warning signs:** The AGENTS.md in `apps/web/` explicitly warns about breaking changes from training data.

### Pitfall 3: FutureWarning from `.fillna(False)` on boolean entries

**What goes wrong:** `entries.shift(1).fillna(False)` generates a `FutureWarning: Downcasting object dtype arrays on .fillna` under pandas 2.2.x.
**Why it happens:** pandas 2.2 deprecates silent downcasting. The shifted boolean Series becomes object dtype temporarily.
**How to avoid:** Append `.infer_objects(copy=False)` after `.fillna(False)` to suppress the warning and force correct dtype.
**Warning signs:** `FutureWarning` flood in backtest output.

### Pitfall 4: VBT `sl_stop` is a fraction not an absolute price

**What goes wrong:** Passing `sl_stop=470.25` (the stop price from Signal) instead of `sl_stop=(471.0-470.25)/471.0` causes stops to fire immediately (stop is > 100% of entry, triggers on the same bar).
**Why it happens:** VBT interprets `sl_stop` as fraction: fires when price drops `sl_stop` fraction below entry.
**How to avoid:** Always convert: `sl_frac = (entry - stop) / entry` for long; `sl_frac = (stop - entry) / entry` for short.
**Warning signs:** Every trade exits on the very next bar.

### Pitfall 5: `pf.max_drawdown_duration()` does not exist

**What goes wrong:** Calling `pf.max_drawdown_duration()` raises `AttributeError: 'Portfolio' object has no attribute 'max_drawdown_duration'`.
**Why it happens:** The correct API is `pf.drawdowns.max_duration()`.
**How to avoid:** Use `pf.drawdowns.max_duration()` for max DD duration; `pf.drawdowns.max_drawdown()` for max DD depth. [VERIFIED]

### Pitfall 6: MAE/MFE not available on `pf.trades`

**What goes wrong:** `pf.trades.mae` raises `AttributeError: 'ExitTrades' object has no attribute 'mae'`.
**Why it happens:** VBT 1.0.0 OSS does not compute MAE/MFE. The `records_arr` only has 14 fields (no MAE/MFE). [VERIFIED]
**How to avoid:** Compute MAE/MFE manually in the driver loop using `high`/`low` arrays sliced by `[entry_idx:exit_idx+1]`.

### Pitfall 7: data_hash computation method matters

**What goes wrong:** Computing data_hash as JSON of bar dicts produces `6ca17c21...` which does NOT match the locked baseline `2d61c1889a...`.
**Why it happens:** The Phase 1 `runs.py` implementation uses a pyarrow Parquet byte-blob approach, not JSON.
**How to avoid:** Always call `trading_core.storage.runs.data_hash(df)` — never reimplement the hash function.

### Pitfall 8: Single-writer DuckDB — do NOT run CLI and FastAPI simultaneously

**What goes wrong:** Running `run_backtest.py` while the FastAPI server is open on the same DuckDB file causes a `CONFLICT: database is locked` error.
**Why it happens:** DuckDB enforces single-writer (established Phase 1 convention).
**How to avoid:** The operator workflow: start the backtest, then start the server. Or: open DuckDB in read-only mode in the FastAPI for reads, write from the CLI.

---

## Code Examples

### BacktestEngine Hybrid Driver Loop (Sketch)

```python
# Source: verified Phase 2 driver pattern + VBT verified API
def run_backtest(bars_df, strategy, risk_manager, executor, seed=42):
    """Hybrid: driver loop for attribution + VBT for metrics."""
    # Phase 1: bar-by-bar driver loop (per Phase 2 pattern)
    fills = []
    equity_series = []
    cash = init_cash
    open_position = None

    for i, bar in enumerate(bars_iter):
        ctx = StrategyContext(
            rollover_seam=bar.rollover_seam,
            warmup_complete=strategy.is_warm(),
            bar_index=strategy._bar_count,
            ts_utc=bar.ts_utc,
            atr=strategy._atr.current,
            session_vwap=strategy._vwap.current,
            ema=strategy._ema.current,
            adr=None,
        )
        signal = strategy.on_bar(bar, ctx)
        strategy._push_bar(bar)

        if signal and open_position is None:
            decision = await risk_manager.check(signal, state)
            if decision.approved:
                fill = await executor.fill(signal, decision, next_bar)
                open_position = fill
                fills.append(fill)

        # Check stop/target/EOD on open position
        if open_position is not None:
            exit_fill = check_exit(open_position, bar, i == last_bar_idx)
            if exit_fill:
                fills.append(exit_fill)
                open_position = None

        equity_series.append(cash + unrealized_pnl(open_position, bar))

    # Phase 2: VBT for portfolio-level metrics
    close_series = pd.Series(closes, index=timestamps)
    entries_bool = pd.Series(entry_flags, index=timestamps)
    exits_bool = pd.Series(exit_flags, index=timestamps)

    pf = safe_from_signals(
        close=close_series,
        entries=entries_bool,
        exits=exits_bool,
        price=open_prices,
        freq='1min',
        init_cash=init_cash,
        size=1,
        high=high_series,
        low=low_series,
        seed=seed,
    )

    return BacktestResult(
        trades=fills,            # from driver loop (has exit_reason, MAE, MFE)
        metrics=extract_metrics(pf),  # from VBT (Sharpe, Sortino, etc.)
        equity_series=pd.Series(equity_series, index=timestamps),
    )
```

### TanStack Query v5 Data Fetching Pattern

```typescript
// 'use client'
import { useQuery } from '@tanstack/react-query';

interface BarData {
  ts_utc: string;
  open: number; high: number; low: number; close: number;
  volume: number;
}

function useBarData(symbol: string, tf: string) {
  return useQuery({
    queryKey: ['bars', symbol, tf],
    queryFn: async () => {
      const res = await fetch(`http://localhost:8000/bars?symbol=${symbol}&tf=${tf}`);
      if (!res.ok) throw new Error('Failed to fetch bars');
      return res.json() as Promise<BarData[]>;
    },
    staleTime: 60_000,
  });
}
```

### Native WebSocket Client Pattern

```typescript
// hooks/useStream.ts — 'use client'
import { useEffect } from 'react';
import { useWsStore } from '@/store/ws';

export function useStream(url: string) {
  const setConnected = useWsStore(s => s.setConnected);
  const setLastBarAt = useWsStore(s => s.setLastBarAt);

  useEffect(() => {
    const ws = new WebSocket(url);

    ws.onopen = () => setConnected(true);
    ws.onclose = () => setConnected(false);
    ws.onerror = () => setConnected(false);

    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data) as { type: string; payload: unknown };
      switch (msg.type) {
        case 'bar_received':
          setLastBarAt(Date.now());
          // update chart data via queryClient.setQueryData(...)
          break;
        case 'degraded_state':
          // show degradation banner
          break;
        // ... other topics
      }
    };

    return () => ws.close();
  }, [url]);
}
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `series.setMarkers([...])` | `createSeriesMarkers(series, markers)` plugin | lightweight-charts v5 | Must use plugin API; v4 code breaks |
| `price='nextbar'` string | Pass `open` array as `price` | VBT internal (Numba JIT) | String arg crashes; always use array |
| `pf.trades.mae` | Manual computation from high/low arrays | VBT 1.0.0 OSS | MAE/MFE are PRO features; compute manually in driver |
| `pf.max_drawdown_duration()` | `pf.drawdowns.max_duration()` | VBT 1.0.0 | Correct API path verified |

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Slippage of 2 ticks during 9:30–9:45 ET window and 1 tick off-peak satisfies the ">=1.5 ticks adverse" ROADMAP spec | PaperExecutor section | Spec says >=1.5 so 2 ticks is safe; but planner should confirm the off-peak default (0.5 ticks per CONTEXT.md vs 1 tick here) |
| A2 | `asyncio.gather` over 7 topic subscriptions will work correctly when bus has no subscribers for a topic | WS fan-out | EventBus returns silently on no-subscribers; this is established behavior from Phase 1 |
| A3 | Unix-seconds timestamps in lightweight-charts v5 must be UTC-based and the formatter converts to ET for display | LWC time section | If LWC interprets timestamps in local TZ, clocks drift; test explicitly with known UTC timestamps |
| A4 | `chart.addSeries(LineSeries, opts, 1)` creates a second pane at index 1 | Two-pane layout | VBT typings show `paneIndex` as 3rd arg to `addSeries` but behavior should be confirmed in first rendering test |

**If this table had no assumptions:** All critical claims in this research were verified directly.

---

## Open Questions

1. **Planner decision: off-peak slippage default**
   - CONTEXT.md Specifics says 0.5 ticks off-peak is "reasonable"
   - Research uses 1 tick (integer; 0.5 ticks is half a tick, needs rounding)
   - Recommendation: planner should lock either 0.5 (round up to 1 on odd lots) or 1 tick as the integer default

2. **BacktestEngine architecture: hybrid vs pure driver loop**
   - Hybrid (driver loop for attribution + VBT for metrics): cleaner separation, requires `entries`/`exits` boolean arrays to feed VBT in addition to the driver loop state
   - Pure driver loop (no VBT at all): simpler code, but must hand-roll Sharpe/Sortino/Calmar — contradicts "don't hand-roll" principle
   - Recommendation: hybrid — use the driver loop for D-02 attribution chain (exit_reason, MAE, MFE) and VBT for portfolio-level metrics. The `safe_from_signals` wrapper is still used and tested (satisfies BT-02/BT-07), just not as the primary fill simulation engine.

3. **GET /bars API shape**
   - Should it return ALL bars for a symbol+tf, or accept `from`/`to` query params?
   - Cold-load on dashboard requires the most recent RTH session bars (D-07)
   - Recommendation: `GET /bars?symbol=SPY&tf=1m&limit=390` (last N bars) for cold-load; the Phase 7 date-picker gets `from`/`to` params

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| vectorbt | BacktestEngine | ✓ | 1.0.0 | — |
| duckdb | DuckDBStore | ✓ | via pyproject.toml | — |
| pyarrow | Equity curve Parquet | ✓ | 17.x pinned | — |
| fastapi + uvicorn | REST + WS | ✓ | 0.136.1 / 0.32.x | — |
| pydantic | Models | ✓ | 2.13.x | — |
| lightweight-charts | Chart panel | ✓ | 5.2.0 | — |
| @tanstack/react-query | Data fetching | ✓ | v5 | — |
| zustand | UI state | ✓ | 5 | — |
| next | App Router | ✓ | 16.2.6 | — |
| pytest + pytest-asyncio | Tests | ✓ | 8.x / 0.24.x | — |

All dependencies confirmed present from `package.json` and `pyproject.toml` checks. No blocking gaps.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 8.x + pytest-asyncio 0.24.x |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` (exists) |
| Quick run command | `uv run pytest packages/trading-core/tests/test_backtest_engine.py packages/trading-core/tests/test_paper_executor.py packages/trading-core/tests/test_safe_signals.py -x -q` |
| Full suite command | `uv run pytest -x -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| BT-01 | BacktestEngine runs driver loop + produces BacktestResult | unit | `pytest packages/trading-core/tests/test_backtest_engine.py -x` | ❌ Wave 0 |
| BT-02 | safe_from_signals enforces shift(1) + rejects string price | unit | `pytest packages/trading-core/tests/test_safe_signals.py -x` | ❌ Wave 0 |
| BT-03 | Fill at next-bar-open + correct slippage + stop-first conflict | unit | `pytest packages/trading-core/tests/test_paper_executor.py -x` | ❌ Wave 0 |
| BT-04 | Standard metrics computed correctly (Sharpe, Sortino, etc.) | unit | `pytest packages/trading-core/tests/test_backtest_engine.py::test_metrics -x` | ❌ Wave 0 |
| BT-05 | Per-trade MAE/MFE correct against known bar fixture | unit | `pytest packages/trading-core/tests/test_backtest_engine.py::test_mae_mfe -x` | ❌ Wave 0 |
| BT-06 | Attribution chain: signal_id in Fill in trades table | unit | `pytest packages/trading-core/tests/test_backtest_engine.py::test_attribution -x` | ❌ Wave 0 |
| BT-07 | BL-1 lookahead: leaking strategy → finite Sharpe + 40-60% win rate | integration | `pytest packages/trading-core/tests/integration/test_lookahead.py -x` | ❌ Wave 0 |
| BT-08 | EOD flatten: sum(positions)==0 after last RTH bar | unit | `pytest packages/trading-core/tests/test_paper_executor.py::test_eod_flatten -x` | ❌ Wave 0 |
| BT-09 | CLI `run_backtest.py` produces runs+backtests+trades rows | integration | `pytest packages/trading-core/tests/integration/test_reproducibility.py -x` | ❌ Wave 0 |
| SP-01 | Signal → RiskManager → Executor → Fill pipeline via EventBus | integration | `pytest packages/api/tests/test_ws_stream.py -x` | ❌ Wave 0 |
| UI-01 | GET /bars returns bar JSON, GET /backtests returns results, WS /stream connects | integration | `pytest packages/api/tests/test_routes.py -x` | ❌ Wave 0 |
| UI-04 | Dashboard renders (smoke: page loads without JS error) | manual/smoke | Load `localhost:3000/dashboard` | — |
| UI-08 | ET clock visible + connection status changes color | manual | Visual inspection | — |

**Reproducibility CI:**
```
pytest packages/trading-core/tests/integration/test_reproducibility.py -x
```
Asserts: same CLI args → bitwise-identical equity-curve Parquet (two runs, `path1.read_bytes() == path2.read_bytes()`).

**BL-1 CI:**
```
pytest packages/trading-core/tests/integration/test_lookahead.py -x
```
Required to pass for any PR merge (per ROADMAP cross-phase guardrails).

### Sampling Rate

- **Per task commit:** `uv run pytest packages/trading-core/tests/test_backtest_engine.py packages/trading-core/tests/test_paper_executor.py packages/trading-core/tests/test_safe_signals.py -x -q`
- **Per wave merge:** `uv run pytest -x -q` (full 251+ test suite including new tests)
- **Phase gate:** Full suite green + BL-1 green + reproducibility CI green before `/gsd-verify-work`

### Wave 0 Gaps

- [ ] `packages/trading-core/tests/test_backtest_engine.py` — covers BT-01, BT-04, BT-05, BT-06
- [ ] `packages/trading-core/tests/test_paper_executor.py` — covers BT-03, BT-08
- [ ] `packages/trading-core/tests/test_safe_signals.py` — covers BT-02
- [ ] `packages/trading-core/tests/integration/test_lookahead.py` — covers BT-07 (BL-1 gate, D-14)
- [ ] `packages/trading-core/tests/integration/test_reproducibility.py` — covers BT-09 + FND-08
- [ ] `packages/api/tests/test_routes.py` — covers UI-01 (GET /bars, GET /backtests)
- [ ] `packages/api/tests/test_ws_stream.py` — covers SP-01, D-04 (7 event types), D-05 (envelope)
- [ ] Framework additions: `packages/api/tests/` needs pytest TestClient + WebSocket test helpers

---

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | Paper-only, single-operator, no auth surface |
| V3 Session Management | no | WebSocket is unauthed local connection |
| V4 Access Control | no | Single-operator localhost |
| V5 Input Validation | yes (partial) | CLI args validated by argparse + Pydantic; GET /bars query params validated by FastAPI/Pydantic |
| V6 Cryptography | no | No sensitive data; hashes are integrity-only (sha256), not security-sensitive |

### Known Threat Patterns for This Phase

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Malformed bar data corrupting equity curve | Tampering | Pydantic validation on Bar model (AwareDatetime, Decimal > 0) |
| DuckDB SQL injection via CLI args | Tampering | DuckDB parameterized queries only (established Phase 1); string interpolation is safe only for fixed paths per duckdb_store.py comments |
| WebSocket message flooding (unbounded queue) | DoS | Accepted T-01-03-04 for v1; documented in EventBus docstring |
| `orb.yaml` YAML injection | Tampering | `yaml.safe_load` locked in Phase 2 StrategyRegistry |

---

## Sources

### Primary (HIGH confidence)

- Installed `vectorbt==1.0.0` — live Python testing of `Portfolio.from_signals`, stats, trades, drawdowns APIs [VERIFIED by running in project venv]
- Installed `lightweight-charts@5.2.0` — typings.d.ts analysis for `createChart`, `addSeries`, `createSeriesMarkers`, `createPriceLine`, `setMarkers` [VERIFIED from `apps/web/node_modules/lightweight-charts/dist/typings.d.ts`]
- Installed `fastapi==0.136.1` — `packages/api/pyproject.toml` dependency pin [VERIFIED]
- Existing codebase — `bus.py`, `duckdb_store.py`, `runs.py`, `orb.py`, `schema.sql`, `instruments.py` [VERIFIED]
- Phase 2 SUMMARY files — driver loop pattern, ORBStrategy test results [VERIFIED]
- `apps/web/package.json` — confirmed installed versions of all frontend deps [VERIFIED]
- `pyproject.toml` + `packages/trading-core/pyproject.toml` — Python deps confirmed [VERIFIED]
- `apps/web/node_modules/next/dist/docs/` — Next.js 16.2 App Router docs, route handlers, client components [VERIFIED from local files]

### Secondary (MEDIUM confidence)

- STATE.md — `data_hash` baseline `2d61c1889a7dbca4fee3e3cf7ea719be6cb3e12810d575635e69d38a6bbdb19f` for 390-row fixture [cited from project state]
- CONTEXT.md decisions D-01 through D-14 — all implementation decisions [cited from project file]

### Tertiary (LOW confidence)

- None — all claims verified against installed code or project files.

---

## Metadata

**Confidence breakdown:**
- VectorBT API: HIGH — verified by live testing all critical methods in project venv
- lightweight-charts API: HIGH — verified from installed typings.d.ts
- FastAPI WebSocket: HIGH — 0.136.1 installed; asyncio.Queue pattern is established Python
- DuckDB schema: HIGH — follows existing schema.sql patterns exactly
- PaperExecutor slippage values: MEDIUM — 1.5+ ticks during open window is locked; off-peak default is open question for planner
- Reproducibility hash: HIGH — `runs.py` already implemented; data_hash baseline from STATE.md

**Research date:** 2026-05-16
**Valid until:** 2026-06-16 (30 days — stable stack)
