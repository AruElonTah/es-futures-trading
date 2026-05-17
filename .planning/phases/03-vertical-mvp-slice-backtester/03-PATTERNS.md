# Phase 3: Vertical MVP Slice + Backtester - Pattern Map

**Mapped:** 2026-05-16
**Files analyzed:** 23 new/modified files
**Analogs found:** 22 / 23

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `packages/trading-core/src/trading_core/backtest/engine.py` | service | batch | `packages/trading-core/src/trading_core/strategy/orb.py` + `scripts/seed_bars.py` | role-match |
| `packages/trading-core/src/trading_core/backtest/safe_signals.py` | utility | transform | `scripts/hooks/no_naive_tz.py` (guard pattern) | partial |
| `packages/trading-core/src/trading_core/execution/paper.py` | service | request-response | `packages/trading-core/src/trading_core/strategy/orb.py` (stateful class) | role-match |
| `packages/trading-core/src/trading_core/execution/models.py` | model | — | `packages/trading-core/src/trading_core/strategy/models.py` | exact |
| `packages/trading-core/src/trading_core/risk/pass_through.py` | service | request-response | `packages/trading-core/src/trading_core/risk/protocols.py` | exact |
| `packages/trading-core/src/trading_core/risk/models.py` | model | — | `packages/trading-core/src/trading_core/strategy/models.py` | exact |
| `packages/trading-core/src/trading_core/storage/duckdb_store.py` | storage | CRUD | self (extend existing) | exact |
| `packages/trading-core/tests/test_backtest_engine.py` | test | batch | `packages/trading-core/tests/test_orb_strategy.py` | exact |
| `packages/trading-core/tests/test_paper_executor.py` | test | request-response | `packages/trading-core/tests/test_duckdb_store.py` | role-match |
| `packages/trading-core/tests/test_safe_signals.py` | test | transform | `packages/trading-core/tests/test_orb_strategy.py` | role-match |
| `packages/trading-core/tests/integration/test_lookahead.py` | test | batch | `packages/trading-core/tests/integration/test_indicator_leakage.py` | exact |
| `packages/trading-core/tests/integration/test_reproducibility.py` | test | batch | `packages/trading-core/tests/integration/test_seed_bars_e2e.py` | role-match |
| `packages/api/src/api/routes/bars.py` | route | request-response | `packages/api/src/api/app.py` | role-match |
| `packages/api/src/api/routes/backtests.py` | route | request-response | `packages/api/src/api/app.py` | role-match |
| `packages/api/src/api/ws.py` | service | event-driven | `packages/trading-core/src/trading_core/events/bus.py` | partial |
| `packages/api/tests/test_routes.py` | test | request-response | `packages/api/tests/test_health.py` | exact |
| `packages/api/tests/test_ws_stream.py` | test | event-driven | `packages/trading-core/tests/test_event_bus.py` | role-match |
| `apps/web/app/dashboard/page.tsx` | component | request-response | `apps/web/app/page.tsx` + `apps/web/app/layout.tsx` | role-match |
| `apps/web/components/Chart.tsx` | component | event-driven | `apps/web/app/page.tsx` (stub only) | no analog (use RESEARCH.md) |
| `apps/web/components/EquityCurve.tsx` | component | event-driven | `apps/web/app/page.tsx` (stub only) | no analog (use RESEARCH.md) |
| `apps/web/hooks/useWebSocket.ts` | hook | event-driven | — | no analog (use RESEARCH.md) |
| `apps/web/hooks/useBars.ts` | hook | request-response | — | no analog (use RESEARCH.md) |
| `scripts/run_backtest.py` | script | batch | `scripts/seed_bars.py` | exact |
| `.pre-commit-config.yaml` | config | — | self (extend existing) + `scripts/hooks/no_naive_tz.py` | exact |

---

## Pattern Assignments

### `packages/trading-core/src/trading_core/backtest/engine.py` (service, batch)

**Analogs:** `packages/trading-core/src/trading_core/strategy/orb.py` (driver loop) + `scripts/seed_bars.py` (async pipeline)

**Imports pattern** — copy from `scripts/seed_bars.py` lines 39-78:
```python
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from trading_core.data.models import Bar
from trading_core.events import EventBus
from trading_core.events.models import TOPIC_FILLS, TOPIC_SIGNALS
from trading_core.instruments import get as get_instrument
from trading_core.logging import get_logger
from trading_core.storage.duckdb_store import DuckDBStore
from trading_core.storage.runs import new_run_id, param_hash, data_hash, git_sha, adr_hash
from trading_core.strategy.models import Signal, StrategyContext
from trading_core.strategy.orb import ORBStrategy
```

**Driver loop pattern** — copy from `packages/trading-core/tests/test_orb_strategy.py` lines 22-47:
```python
# The canonical look-ahead-safe driver loop:
#   1. Snapshot indicator state BEFORE the current bar (prior-bar context)
#   2. Call on_bar with current bar + prior-bar context
#   3. Push bar to indicators AFTER on_bar
for bar in bars:
    ctx = StrategyContext(
        rollover_seam=bar.rollover_seam,
        warmup_complete=strategy.is_warm(),
        bar_index=strategy._bar_count,
        ts_utc=bar.ts_utc,
        atr=strategy._atr.current,      # prior-bar ATR snapshot
        session_vwap=strategy._vwap.current,
        ema=strategy._ema.current,
        adr=None,
    )
    signal = strategy.on_bar(bar, ctx)
    strategy._push_bar(bar)             # push AFTER on_bar
```

**Logging pattern** — copy from `scripts/seed_bars.py` lines 154-174:
```python
log = get_logger(__name__)
run_id = new_run_id()
started_at = datetime.now(tz=timezone.utc)
log = log.bind(run_id=run_id, symbol=args.symbol, tf=args.tf)
log.info("backtest.start", provider=..., from_ts=..., to_ts=...)
```

**Try/finally audit-chain pattern** — copy from `scripts/seed_bars.py` lines 232-263:
```python
try:
    # ... main work ...
except Exception as exc:  # noqa: BLE001 — finally block guarantees runs row
    status = "failed"
    notes = f"{type(exc).__name__}: {exc}"
    log.exception("backtest.failed", error_type=type(exc).__name__)
finally:
    # ALWAYS write the runs row — even on failure
    try:
        finished_at = datetime.now(tz=timezone.utc)
        store.write_run(
            run_id=run_id,
            git_sha=git_sha(),
            data_hash=data_hash(df) if df is not None else "",
            param_hash=param_hash(args_dict),
            seed=seed,
            adr_hash=adr_hash(_REPO_ROOT / ".planning" / "decisions" / "0001-data-provider.md"),
            started_at=started_at,
            finished_at=finished_at,
            status=status,
            notes=notes,
        )
    except Exception:  # noqa: BLE001
        log.exception("runs.write_run.failed")
    finally:
        store.close()
```

**Equity curve Parquet write** — byte-stable flags from `packages/trading-core/src/trading_core/storage/runs.py` lines 116-131:
```python
# Same flags as data_hash Parquet write — ensures byte-stability for reproducibility CI
import pyarrow as pa
import pyarrow.parquet as pq

table = pa.Table.from_pandas(equity_df.reset_index(drop=True), preserve_index=False)
pq.write_table(
    table,
    str(equity_path),
    compression="none",
    use_dictionary=False,
    write_statistics=False,
)
```

---

### `packages/trading-core/src/trading_core/backtest/safe_signals.py` (utility, transform)

**Analog:** `scripts/hooks/no_naive_tz.py` (guard/validator pattern) + RESEARCH.md §safe_from_signals Wrapper Pattern

**Guard pattern** — copy from `scripts/hooks/no_naive_tz.py` lines 38-96 (raise-on-violation style):
```python
# Guard: reject disallowed inputs immediately with a clear ValueError
if isinstance(price, str):
    raise ValueError(
        "safe_from_signals: price must be an array of fill prices, not a string. "
        "Pass the next-bar open prices as a pd.Series. "
        "Passing price='nextbar' crashes Numba JIT."
    )
```

**pandas FutureWarning suppression** — verified pattern from RESEARCH.md §Pitfall 3:
```python
# pandas 2.2.x FutureWarning: Downcasting object dtype arrays on .fillna
# Fix: append .infer_objects(copy=False) after every .fillna(False) on shifted bool Series
shifted_entries = entries.shift(1).fillna(False).infer_objects(copy=False)
shifted_exits   = exits.shift(1).fillna(False).infer_objects(copy=False)
```

**Module-level docstring** — copy style from `packages/trading-core/src/trading_core/storage/duckdb_store.py` lines 1-22 (explains WHY, cites RESEARCH.md section):
```python
"""safe_from_signals — lookahead-safe wrapper around vbt.Portfolio.from_signals.

Enforces:
  1. entries and exits are shifted by 1 (next-bar execution) — D-13
  2. price is a concrete array, never the string 'nextbar' (crashes Numba JIT)

See 03-RESEARCH.md §safe_from_signals Wrapper Pattern + §Pitfall 1.

Direct calls to vbt.Portfolio.from_signals() are blocked by the
no-direct-vbt-from-signals pre-commit hook; this module is explicitly
excluded from that hook.
"""
```

---

### `packages/trading-core/src/trading_core/execution/paper.py` (service, request-response)

**Analog:** `packages/trading-core/src/trading_core/strategy/orb.py` (stateful class with session-phase logic)

**Module imports** — adapt from `packages/trading-core/src/trading_core/strategy/orb.py` lines 34-46:
```python
from __future__ import annotations

from datetime import time as dt_time
from decimal import Decimal
from zoneinfo import ZoneInfo

from trading_core.data.models import Bar
from trading_core.execution.models import Fill
from trading_core.instruments import get as get_instrument
from trading_core.logging import get_logger
from trading_core.risk.models import RiskDecision
from trading_core.strategy.models import Signal

_ET = ZoneInfo("America/New_York")   # same pattern as orb.py line 46
```

**Session-phase logic** — adapt from `packages/trading-core/src/trading_core/strategy/orb.py` lines 150-158 (ET date handling):
```python
# Session-phase-aware slippage — adapt the ET date-change pattern from ORBStrategy
_OPEN_WINDOW_START = dt_time(9, 30)
_OPEN_WINDOW_END   = dt_time(9, 45)

def _slippage_ticks(bar_ts_utc, symbol: str) -> int:
    et_time = bar_ts_utc.astimezone(_ET).time()
    if _OPEN_WINDOW_START <= et_time < _OPEN_WINDOW_END:
        return 2   # >= 1.5 ticks adverse during 9:30-9:45 open window (FR-1 pitfall)
    return 1       # off-peak default (1 tick; off-peak spec: 0.5 ticks rounds to 1)
```

**Decimal arithmetic** — copy constraint from `packages/trading-core/src/trading_core/strategy/orb.py` lines 190-211:
```python
# All price math uses Decimal — never float.
# Conversion back from float boundary: Decimal(str(round(x, 4)))
instrument = get_instrument(symbol)
adj = instrument.tick_size * Decimal(str(slippage_ticks))
fill_price = entry_price + adj  # for long; - adj for short
```

**Intrabar stop/target conflict** — D-12 requires stop-first; implement in the check_exit helper:
```python
# D-12: stop-first conflict resolution (conservative/worst-case)
# When bar.low <= stop AND bar.high >= target in the same bar → exit_reason="stop"
if bar.low <= stop_price and bar.high >= target_price:
    return "stop"   # stop wins — conservative assumption
elif bar.low <= stop_price:
    return "stop"
elif bar.high >= target_price:
    return "target"
```

---

### `packages/trading-core/src/trading_core/execution/models.py` (model, extend stub)

**Analog:** `packages/trading-core/src/trading_core/strategy/models.py` (frozen Pydantic v2 with Decimal + AwareDatetime)

**Imports pattern** — copy from `packages/trading-core/src/trading_core/strategy/models.py` lines 14-21:
```python
from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator
```

**Frozen model with UTC validator** — copy from `packages/trading-core/src/trading_core/strategy/models.py` lines 23-43:
```python
class Fill(BaseModel):
    """Paper-executor fill record — D-10 minimal fields."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    signal_id: str
    fill_price: Decimal = Field(gt=Decimal("0"))
    fill_qty: int = Field(gt=0)
    side: Literal["long", "short"]
    slippage_ticks: int = Field(ge=0)
    ts_utc: AwareDatetime
    exit_reason: Literal["target", "stop", "eod_flat", "manual"]

    @field_validator("ts_utc")
    @classmethod
    def must_be_utc(cls, v):  # type: ignore[override]
        """Reject offsets != 0. AwareDatetime already rejects naive."""
        offset = v.utcoffset()
        if offset is None or offset.total_seconds() != 0:
            raise ValueError(
                f"ts_utc must be tz-aware UTC; got offset {offset}"
            )
        return v
```

---

### `packages/trading-core/src/trading_core/risk/models.py` (model, extend stub)

**Analog:** `packages/trading-core/src/trading_core/strategy/models.py` (Pydantic v2 ConfigDict pattern)

**Model pattern** — adapt from `packages/trading-core/src/trading_core/risk/models.py` (current stub, lines 14-32):
```python
# Extend existing stubs — D-10 minimal fields only; Phase 5 adds the rest.
# Keep model_config = ConfigDict(extra="forbid") on all three models.

class RiskConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_contracts: int = 1   # D-10: Phase 5 adds full risk params

class RiskState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    realized_pnl_today: Decimal = Decimal("0")  # D-10: Phase 5 adds HWM + open exposure

class RiskDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approved: bool             # D-10
    reason: str                # D-10
    adjusted_size: int         # D-10
```

---

### `packages/trading-core/src/trading_core/risk/pass_through.py` (service, request-response)

**Analog:** `packages/trading-core/src/trading_core/risk/protocols.py` (Protocol signature to implement against)

**Protocol to implement** — copy from `packages/trading-core/src/trading_core/risk/protocols.py` lines 17-21:
```python
class RiskManager(Protocol):
    async def check(self, signal: "Signal", state: "RiskState") -> "RiskDecision":
        ...
```

**Implementation pattern** — structurally matches the Protocol; similar async service shape:
```python
from __future__ import annotations

from trading_core.logging import get_logger
from trading_core.risk.models import RiskConfig, RiskDecision, RiskState
from trading_core.strategy.models import Signal

log = get_logger(__name__)


class PassThroughRiskManager:
    """Minimal pass-through RiskManager — always approves, size=1 (D-10/Phase 3).

    Structurally satisfies the RiskManager Protocol. Phase 5 adds prop-firm
    risk constraints (daily DD limit, max_contracts_per_strategy, HWM logic).
    """

    def __init__(self, config: RiskConfig) -> None:
        self._config = config

    async def check(self, signal: Signal, state: RiskState) -> RiskDecision:
        approved = True
        adjusted_size = min(int(signal.size_hint), self._config.max_contracts)
        log.debug(
            "risk.pass_through",
            signal_id=signal.signal_id,
            approved=approved,
            adjusted_size=adjusted_size,
        )
        return RiskDecision(
            approved=approved,
            reason="pass_through",
            adjusted_size=adjusted_size,
        )
```

---

### `packages/trading-core/src/trading_core/storage/duckdb_store.py` (storage, CRUD — extend)

**Analog:** self — existing `DuckDBStore` (extend with `write_backtest` + `write_trades`)

**SQL constant pattern** — copy from `packages/trading-core/src/trading_core/storage/duckdb_store.py` lines 69-73:
```python
# SQL constants at module top — same pattern as WRITE_RUN_SQL
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

**Method signature pattern** — copy from `packages/trading-core/src/trading_core/storage/duckdb_store.py` `write_run` lines 177-209:
```python
def write_backtest(
    self,
    *,
    run_id: str,
    strategy_id: str,
    symbol: str,
    timeframe: str,
    from_ts: datetime,
    to_ts: datetime,
    param_hash: str,
    equity_curve_path: str,
    total_return: float,
    cagr: float,
    sharpe: float,
    sortino: float,
    calmar: float,
    max_dd: float,
    max_dd_duration_bars: int,
    win_rate: float,
    expectancy: float,
    profit_factor: float,
    trade_count: int,
    avg_hold_bars: float,
) -> None:
    """Persist a single backtests row. No upsert — run_id (uuid7) is unique per run."""
    self._conn.execute(
        WRITE_BACKTEST_SQL,
        [run_id, strategy_id, symbol, timeframe, from_ts, to_ts,
         param_hash, equity_curve_path, total_return, cagr, sharpe, sortino, calmar,
         max_dd, max_dd_duration_bars, win_rate, expectancy, profit_factor,
         trade_count, avg_hold_bars],
    )

def write_trades(self, trades: list[dict]) -> None:
    """Persist a list of trade rows. Plain INSERT — trade_id (uuid7) is unique."""
    rows = [
        (t["trade_id"], t["run_id"], t["signal_id"], t["strategy_id"],
         t["side"], float(t["entry_price"]), float(t["exit_price"]),
         t["exit_reason"], t["entry_ts_utc"], t["exit_ts_utc"],
         float(t["pnl"]), int(t["size"]), int(t["slippage_ticks"]),
         float(t["mae"]), float(t["mfe"]))
        for t in trades
    ]
    self._conn.executemany(WRITE_TRADE_SQL, rows)
```

---

### `packages/trading-core/tests/test_backtest_engine.py` (test, batch)

**Analog:** `packages/trading-core/tests/test_orb_strategy.py` (class-organized tests + fixture import)

**Test structure pattern** — copy from `packages/trading-core/tests/test_orb_strategy.py` lines 1-56:
```python
"""Tests for BacktestEngine — Phase 3 success criteria BT-01, BT-04, BT-05, BT-06.

Success criteria tested:
  BT-01: BacktestEngine runs driver loop + produces BacktestResult
  BT-04: Standard metrics computed correctly
  BT-05: Per-trade MAE/MFE correct against known bar fixture
  BT-06: Attribution chain: signal_id in Fill in trades table
"""

from __future__ import annotations

from decimal import Decimal
import pytest

# Import fixture directly — not as pytest fixture (--import-mode=importlib pattern)
from fixtures.orb_day import orb_day_bars as _orb_day_bars

from trading_core.backtest.engine import BacktestEngine
from trading_core.backtest.safe_signals import safe_from_signals
from trading_core.risk.models import RiskConfig, RiskState
from trading_core.risk.pass_through import PassThroughRiskManager
from trading_core.execution.paper import PaperExecutor
from trading_core.strategy.orb import ORBConfig, ORBStrategy


@pytest.fixture
def tmp_duckdb_path(tmp_path):
    return tmp_path / "test.duckdb"
```

**Test class organization** — copy pattern from `packages/trading-core/tests/test_duckdb_store.py` lines 78-136:
```python
class TestBacktestEngineDriverLoop:
    def test_produces_backtest_result(self):
        ...

class TestMetrics:
    def test_sharpe_is_finite(self):
        ...

class TestMAEMFE:
    def test_mae_mfe_correct_against_fixture(self):
        ...

class TestAttributionChain:
    def test_signal_id_in_fill_in_trade_row(self):
        ...
```

---

### `packages/trading-core/tests/test_paper_executor.py` (test, request-response)

**Analog:** `packages/trading-core/tests/test_duckdb_store.py` (tmp_path fixtures + assertion style)

**Fixture + test pattern** — copy from `packages/trading-core/tests/test_duckdb_store.py` lines 36-64:
```python
@pytest.fixture
def tmp_duckdb_path(tmp_path: Path) -> Path:
    return tmp_path / "test.duckdb"

# Use the orb_day_bars fixture for known fill scenarios
from fixtures.orb_day import orb_day_bars as _orb_day_bars

class TestPaperExecutorFill:
    def test_fill_price_is_next_bar_open_plus_slippage(self):
        bars = _orb_day_bars()
        # bar[15] is breakout bar; bar[16] is next-bar open for fill
        ...

class TestEODFlatten:
    def test_eod_flatten_sum_positions_is_zero(self):
        # Assert sum(positions) == 0 after last RTH bar — BT-08
        ...
```

---

### `packages/trading-core/tests/test_safe_signals.py` (test, transform)

**Analog:** `packages/trading-core/tests/test_orb_strategy.py` (unit test style, no class needed)

**Test pattern:**
```python
"""Tests for safe_from_signals wrapper — BT-02 success criteria."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from trading_core.backtest.safe_signals import safe_from_signals


def test_rejects_string_price():
    """safe_from_signals raises ValueError when price='nextbar' string is passed."""
    with pytest.raises(ValueError, match="price must be an array"):
        safe_from_signals(
            close=pd.Series([1.0]),
            entries=pd.Series([True]),
            exits=pd.Series([False]),
            price="nextbar",   # must be rejected
        )


def test_shift_is_applied_internally():
    """Entries are shifted by 1 internally — entry at bar N fills at bar N+1."""
    ...
```

---

### `packages/trading-core/tests/integration/test_lookahead.py` (test, batch)

**Analog:** `packages/trading-core/tests/integration/test_indicator_leakage.py` — exact template

**Structure pattern** — copy from `packages/trading-core/tests/integration/test_indicator_leakage.py` lines 1-28:
```python
"""Integration: BL-1 lookahead-leakage detector (D-14, ROADMAP cross-phase guardrail).

A deliberately-leaking ORB variant uses close.shift(-1) as the entry signal.
safe_from_signals applies shift(1) on top — neutralizing lookahead.
Assertions:
  1. Sharpe is finite (not inf) — lookahead is neutralized
  2. Win rate is in [0.35, 0.65] — performance is in random-walk territory

This test is required to pass in CI for any PR merge (BL-1 gate).
"""

from __future__ import annotations

from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from fixtures.orb_day import orb_day_bars
from trading_core.backtest.safe_signals import safe_from_signals
```

**Driver loop for leakage test** — adapt from `packages/trading-core/tests/integration/test_indicator_leakage.py` lines 44-74 (same bar-by-bar loop with different assertion focus):
```python
def test_bl1_lookahead_neutralized_by_safe_from_signals():
    bars = orb_day_bars()
    # Build pandas Series from Bar list
    index = pd.DatetimeIndex([b.ts_utc for b in bars], tz="UTC")
    close = pd.Series([float(b.close) for b in bars], index=index)
    high  = pd.Series([float(b.high) for b in bars], index=index)
    low   = pd.Series([float(b.low) for b in bars], index=index)

    # Deliberately-leaking entry: close.shift(-1) looks one bar into the future
    leaking_entries = (close.shift(-1) > 471.00).fillna(False)

    pf = safe_from_signals(
        close=close,
        entries=leaking_entries,
        exits=pd.Series([False] * len(close), index=index),
        price=close.shift(-1).fillna(close),
        freq="1min",
        init_cash=10_000.0,
        size=1,
        direction="longonly",
        high=high,
        low=low,
    )

    sharpe = pf.sharpe_ratio()
    win_rate = pf.trades.win_rate() if pf.trades.count() > 0 else 0.5

    assert np.isfinite(sharpe), f"Sharpe is infinite ({sharpe}): lookahead not neutralized"
    assert 0.35 <= win_rate <= 0.65, (
        f"Win rate {win_rate:.2%} outside 35-65% band"
    )
```

---

### `packages/trading-core/tests/integration/test_reproducibility.py` (test, batch)

**Analog:** `packages/trading-core/tests/integration/test_indicator_leakage.py` (integration test with fixture)

**Reproducibility test pattern** — from RESEARCH.md §Reproducibility Hash Chain:
```python
"""Integration: FND-08 reproducibility CI.

Same git_sha + data_hash + param_hash + seed must produce bitwise-identical
equity-curve Parquet (ROADMAP success criterion #3).
"""

from __future__ import annotations

from pathlib import Path
import pytest

def test_reproducibility_same_inputs_bitwise_identical(tmp_path: Path):
    """Same CLI args → bitwise-identical equity-curve Parquet bytes."""
    # Run backtest twice with identical args
    kwargs = dict(
        symbol="SPY", tf="1m", from_date="2024-01-02", to_date="2024-01-02",
        config_path="config/strategies/orb.yaml", seed=42,
    )
    path1 = tmp_path / "run1.parquet"
    path2 = tmp_path / "run2.parquet"
    run_backtest(**kwargs, equity_path=path1)
    run_backtest(**kwargs, equity_path=path2)
    assert path1.read_bytes() == path2.read_bytes(), (
        "Equity curve is not bitwise-identical — pyarrow flags or seed mismatch"
    )
```

---

### `packages/api/src/api/routes/bars.py` (route, request-response)

**Analog:** `packages/api/src/api/app.py` (FastAPI route pattern)

**Route imports pattern** — adapt from `packages/api/src/api/app.py` lines 27-48:
```python
from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from trading_core.config import Settings
from trading_core.data.models import Bar
from trading_core.logging import get_logger
from trading_core.storage.duckdb_store import DuckDBStore

router = APIRouter()
log = get_logger(__name__)
```

**Route decorator + response pattern** — copy from `packages/api/src/api/app.py` lines 51-64:
```python
@router.get("/bars")
def get_bars(
    symbol: str = Query(..., description="Instrument symbol"),
    tf: str = Query("1m", description="Bar timeframe"),
    limit: int = Query(390, description="Maximum bars to return (default=390 = one RTH session)"),
) -> list[dict]:
    """Return the most recent RTH bars for the given symbol+timeframe.

    D-07: cold-load state = most recent RTH bars in DuckDB, no overlays.
    """
    ...
```

---

### `packages/api/src/api/routes/backtests.py` (route, request-response)

**Analog:** same as bars.py — `packages/api/src/api/app.py`

**Pattern:** Identical structure to `bars.py` above. Use `APIRouter` + `@router.get("/backtests")` returning `list[dict]` queried from DuckDB `backtests` table via `DuckDBStore._conn.execute(...)`.

---

### `packages/api/src/api/ws.py` (service, event-driven)

**Analog:** `packages/trading-core/src/trading_core/events/bus.py` (asyncio.Queue pattern) + RESEARCH.md §FastAPI WebSocket Fan-Out Pattern

**ConnectionManager class** — modeled on the EventBus concurrency pattern from `packages/trading-core/src/trading_core/events/bus.py` lines 54-101 (per-subscriber queue, context-manager registration, lock-guard):
```python
from __future__ import annotations

import asyncio
import json

from fastapi import WebSocket, WebSocketDisconnect

from trading_core.events.bus import EventBus
from trading_core.events.models import (
    TOPIC_BARS, TOPIC_SIGNALS, TOPIC_RISK_DECISIONS, TOPIC_FILLS,
    TOPIC_POSITIONS, TOPIC_EQUITY, TOPIC_DEGRADED_STATE,
)
from trading_core.logging import get_logger

ALL_TOPICS = [
    TOPIC_BARS, TOPIC_SIGNALS, TOPIC_RISK_DECISIONS, TOPIC_FILLS,
    TOPIC_POSITIONS, TOPIC_EQUITY, TOPIC_DEGRADED_STATE,
]

log = get_logger(__name__)


class ConnectionManager:
    """Per-client asyncio.Queue fan-out. No broadcaster dep (D-06)."""

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._clients: set[asyncio.Queue] = set()

    async def connect(self, ws: WebSocket) -> asyncio.Queue:
        await ws.accept()
        q: asyncio.Queue = asyncio.Queue()
        self._clients.add(q)
        return q

    def disconnect(self, q: asyncio.Queue) -> None:
        self._clients.discard(q)
```

**Background fan-out** — adapt from EventBus `subscribe` async context manager pattern (lines 83-101):
```python
    async def start_background_fan_out(self) -> None:
        async def _subscribe_topic(topic: str) -> None:
            async with self._bus.subscribe(topic) as sub:
                async for event in sub:
                    msg = json.dumps({
                        "type": event.topic,   # D-05: snake_case type field
                        "payload": event.model_dump(mode="json"),
                    })
                    for q in list(self._clients):
                        await q.put(msg)
        await asyncio.gather(*[_subscribe_topic(t) for t in ALL_TOPICS])
```

**WebSocket route pattern** — adapt from `packages/api/src/api/app.py` lines 51-64:
```python
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

---

### `packages/api/tests/test_routes.py` (test, request-response)

**Analog:** `packages/api/tests/test_health.py` — exact template

**TestClient pattern** — copy from `packages/api/tests/test_health.py` lines 15-30:
```python
from __future__ import annotations

import pytest

def test_get_bars_returns_200():
    from fastapi.testclient import TestClient
    from api.app import app

    client = TestClient(app)
    response = client.get("/bars?symbol=SPY&tf=1m&limit=10")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)

def test_get_backtests_returns_200():
    from fastapi.testclient import TestClient
    from api.app import app

    client = TestClient(app)
    response = client.get("/backtests")
    assert response.status_code == 200
```

---

### `packages/api/tests/test_ws_stream.py` (test, event-driven)

**Analog:** `packages/trading-core/tests/test_event_bus.py` (async test + EventBus subscription pattern)

**Async test pattern** — copy from `packages/trading-core/tests/test_event_bus.py` lines 64-86:
```python
# asyncio_mode = "auto" in pyproject.toml — no @pytest.mark.asyncio needed
async def test_ws_stream_receives_all_7_event_types():
    """D-04: WS /stream mirrors all 7 EventBus topics."""
    from fastapi.testclient import TestClient
    from api.app import app

    client = TestClient(app)
    with client.websocket_connect("/stream") as ws:
        # Publish to each of the 7 topics via EventBus
        # Assert envelope shape: {"type": "<topic>", "payload": {...}}
        msg = ws.receive_json()
        assert "type" in msg
        assert "payload" in msg
```

**EventBus publish pattern** — copy from `packages/trading-core/tests/test_event_bus.py` lines 78-86:
```python
# From test_event_bus.py: publish then await consumer
await asyncio.sleep(0.01)  # Give subscriber time to register
await bus.publish(TOPIC_BARS, event)
await asyncio.wait_for(consumer_task, timeout=1.0)
```

---

### `apps/web/app/dashboard/page.tsx` (component, request-response)

**Analog:** `apps/web/app/page.tsx` + `apps/web/app/layout.tsx`

**'use client' + layout pattern** — adapt from `apps/web/app/layout.tsx` lines 9-19 and `apps/web/app/page.tsx` lines 1-14:
```typescript
'use client'

import { Suspense } from 'react'
import { Chart } from '@/components/Chart'
import { EquityCurve } from '@/components/EquityCurve'
import { ETClock } from '@/components/ETClock'
import { ConnectionStatus } from '@/components/ConnectionStatus'

// D-08: Two-pane layout — chart (top ~70%) + equity curve (bottom ~30%)
export default function DashboardPage() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh' }}>
      <header style={{ height: '48px', display: 'flex', alignItems: 'center', gap: '16px', padding: '0 16px' }}>
        <span className="font-mono text-sm font-bold">ES Trading System</span>
        <ETClock />
        <ConnectionStatus />
        <button>Run Backtest</button>
      </header>
      <div style={{ flex: '0 0 70%' }}>
        <Chart />
      </div>
      <div style={{ flex: '0 0 30%' }}>
        <EquityCurve />
      </div>
    </div>
  )
}
```

**Tailwind class style** — copy from `apps/web/app/page.tsx` line 3 (`className="flex min-h-screen ... font-mono"`).

---

### `apps/web/components/Chart.tsx` (component, event-driven)

**No close analog in codebase.** Use RESEARCH.md §lightweight-charts v5.2.0: Verified API.

**Key verified facts from RESEARCH.md:**
- `createChart`, `CandlestickSeries`, `LineSeries`, `createSeriesMarkers` all imported from `'lightweight-charts'`
- Markers use `createSeriesMarkers(series, [])` — NOT `series.setMarkers()` (v4 API, removed in v5)
- Second pane via `chart.addSeries(LineSeries, opts, 1)` — third arg is `paneIndex`
- Price lines via `series.createPriceLine({price, color, lineWidth, lineStyle, axisLabelVisible, title})`
- Cleanup via `return () => chart.remove()` in useEffect

**Pattern from RESEARCH.md §Chart Setup Pattern:**
```typescript
'use client'
import { useEffect, useRef } from 'react'
import {
  createChart,
  createSeriesMarkers,
  CandlestickSeries,
  LineSeries,
  type SeriesMarker,
  type Time,
} from 'lightweight-charts'

export function Chart({ barData, markers, priceLinesConfig }) {
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!containerRef.current) return
    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height: containerRef.current.clientHeight,
      layout: { background: { color: '#000' }, textColor: '#d1d4dc' },
      localization: {
        timeFormatter: (timestamp: number): string =>
          new Intl.DateTimeFormat('en-US', {
            timeZone: 'America/New_York',
            hour: '2-digit', minute: '2-digit', month: 'short', day: 'numeric',
          }).format(new Date(timestamp * 1000)),
      },
      timeScale: { timeVisible: true, secondsVisible: false },
    })

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#26a69a', downColor: '#ef5350',
      borderVisible: false, wickUpColor: '#26a69a', wickDownColor: '#ef5350',
    })
    candleSeries.setData(barData)

    // v5 markers plugin — NOT series.setMarkers()
    const markersPlugin = createSeriesMarkers(candleSeries, [])

    return () => chart.remove()
  }, [])

  return <div ref={containerRef} style={{ width: '100%', height: '100%' }} />
}
```

---

### `apps/web/components/EquityCurve.tsx` (component, event-driven)

**No close analog in codebase.** Use RESEARCH.md §Chart Setup Pattern (LineSeries pattern).

**Pattern from RESEARCH.md (paneIndex=1 line series):**
```typescript
// Same useEffect pattern as Chart.tsx but with LineSeries in pane 0 (standalone component)
const equitySeries = chart.addSeries(LineSeries, {
  color: '#2962FF',
  lineWidth: 2,
})
// Data format: { time: number (Unix seconds UTC), value: number }
equitySeries.setData(equityData)
```

---

### `apps/web/hooks/useWebSocket.ts` (hook, event-driven)

**No close analog in codebase.** Use RESEARCH.md §Native WebSocket Client Pattern.

**Pattern from RESEARCH.md:**
```typescript
'use client'
import { useEffect } from 'react'

export function useWebSocket(url: string, onMessage: (msg: { type: string; payload: unknown }) => void) {
  useEffect(() => {
    const ws = new WebSocket(url)
    ws.onopen = () => { /* update Zustand connected=true */ }
    ws.onclose = () => { /* update Zustand connected=false */ }
    ws.onerror = () => { /* update Zustand connected=false */ }
    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data) as { type: string; payload: unknown }
      onMessage(msg)
    }
    return () => ws.close()
  }, [url])
}
```

---

### `apps/web/hooks/useBars.ts` (hook, request-response)

**No close analog in codebase.** Use RESEARCH.md §TanStack Query v5 Data Fetching Pattern.

**Pattern from RESEARCH.md:**
```typescript
'use client'
import { useQuery } from '@tanstack/react-query'

export function useBars(symbol: string, tf: string, limit = 390) {
  return useQuery({
    queryKey: ['bars', symbol, tf, limit],
    queryFn: async () => {
      const res = await fetch(`http://localhost:8000/bars?symbol=${symbol}&tf=${tf}&limit=${limit}`)
      if (!res.ok) throw new Error('Failed to fetch bars')
      return res.json()
    },
    staleTime: 60_000,
  })
}
```

---

### `scripts/run_backtest.py` (script, batch)

**Analog:** `scripts/seed_bars.py` — exact template

**All structural patterns copy directly:**

**Imports + sys.path guard** — copy from `scripts/seed_bars.py` lines 39-78:
```python
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

# Defensive: reconfigure stdout/stderr to UTF-8 BEFORE any module-level import
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "packages" / "trading-core" / "src"
if _SRC.exists() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
```

**argparse builder** — copy from `scripts/seed_bars.py` lines 285-338 (use same `--symbol`, `--tf`, `--from`/`--to`, `--seed`, `--duckdb-path`; add `--config` for YAML path):
```python
def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="run_backtest", description="...")
    p.add_argument("--symbol", required=True, choices=["ES", "MES", "SPY"])
    p.add_argument("--tf", required=True, choices=["1m", "5m", "15m"])
    p.add_argument("--from", dest="frm", type=_parse_iso_utc, required=True)
    p.add_argument("--to", type=_parse_iso_utc, required=True)
    p.add_argument("--config", type=Path, default=Path("config/strategies/orb.yaml"))
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--duckdb-path", dest="duckdb_path", type=Path, default=None)
    return p
```

**`if __name__ == "__main__"` pattern** — copy from `scripts/seed_bars.py` lines 341-344:
```python
if __name__ == "__main__":
    parser = _build_parser()
    parsed_args = parser.parse_args()
    sys.exit(asyncio.run(main(parsed_args)))
```

---

### `.pre-commit-config.yaml` (config — extend existing)

**Analog:** `.pre-commit-config.yaml` (existing) + `scripts/hooks/no_naive_tz.py` (hook script template)

**Hook addition pattern** — copy from `.pre-commit-config.yaml` lines 16-34 (local hook block):
```yaml
# Addition to existing repos: - repo: local block
    - id: no-direct-vbt-from-signals
      name: Block direct vbt.Portfolio.from_signals() calls
      entry: python scripts/hooks/no_direct_vbt.py
      language: python
      types: [python]
      require_serial: true
      # Exclude the wrapper file itself — it is the only legitimate call site
      exclude: |
        (?x)^(
          packages/trading-core/src/trading_core/backtest/safe_signals\.py
        )$
```

**Hook script structure** — copy from `scripts/hooks/no_naive_tz.py` lines 99-111 (CLI entry):
```python
# scripts/hooks/no_direct_vbt.py
import sys, re

PATTERN = re.compile(r'vbt\.Portfolio\.from_signals\s*\(')
ERRORS = []
for path in sys.argv[1:]:
    with open(path, encoding='utf-8') as f:
        for lineno, line in enumerate(f, 1):
            if PATTERN.search(line):
                ERRORS.append(
                    f'{path}:{lineno}: direct vbt.Portfolio.from_signals() '
                    f'call blocked. Use safe_from_signals() instead.'
                )
if ERRORS:
    print('\n'.join(ERRORS))
    sys.exit(1)
sys.exit(0)
```

Note: unlike `no_naive_tz.py` which uses AST parsing, the VBT hook uses regex (simpler, sufficient — the pattern is unambiguous in Python source).

---

## Shared Patterns

### Decimal-Only Price Arithmetic
**Source:** `packages/trading-core/src/trading_core/strategy/models.py` (Signal model) + `packages/trading-core/src/trading_core/strategy/orb.py` lines 190-211
**Apply to:** `execution/paper.py`, `backtest/engine.py`, all risk/model work
```python
# No float() in price paths. Convert to Decimal at the boundary:
atr_stop_mult = Decimal(str(self._config.atr_stop_mult))  # float config → Decimal
# Convert back from float/VBT boundary:
price = Decimal(str(round(float_val, 4)))
```

### UTC-Only Datetimes
**Source:** `packages/trading-core/src/trading_core/data/models.py` lines 47-55 + `packages/trading-core/src/trading_core/strategy/models.py` lines 42-49
**Apply to:** All new Pydantic models with datetime fields (`Fill`, `RiskDecision`, `RiskState`)
```python
@field_validator("ts_utc")
@classmethod
def must_be_utc(cls, v):
    offset = v.utcoffset()
    if offset is None or offset.total_seconds() != 0:
        raise ValueError(f"ts_utc must be tz-aware UTC; got offset {offset}")
    return v
```

### Structlog Correlation Logging
**Source:** `packages/trading-core/src/trading_core/logging.py` lines 132-135 + `scripts/seed_bars.py` lines 154-160
**Apply to:** `backtest/engine.py`, `execution/paper.py`, `risk/pass_through.py`, `api/ws.py`
```python
from trading_core.logging import get_logger
log = get_logger(__name__)
# Bind context at call-site:
log = log.bind(run_id=run_id, signal_id=signal.signal_id)
log.info("event.name", field=value)
```

### Pydantic v2 Frozen Model with extra='forbid'
**Source:** `packages/trading-core/src/trading_core/strategy/models.py` lines 27-31 + `packages/trading-core/src/trading_core/data/models.py` lines 35-36
**Apply to:** All new Pydantic models (`Fill`, `RiskDecision`, `RiskState`, `RiskConfig`)
```python
model_config = ConfigDict(frozen=True, extra="forbid")
# Use ConfigDict(extra="forbid") on non-frozen models too (DuckDBStore query responses)
```

### DuckDB Parameterized Queries
**Source:** `packages/trading-core/src/trading_core/storage/duckdb_store.py` lines 141-143 + 195-209
**Apply to:** `duckdb_store.py` new methods, `api/routes/bars.py`, `api/routes/backtests.py`
```python
# Always parameterized — never string-interpolated user input
self._conn.execute(SQL_CONSTANT, [param1, param2, ...])
self._conn.executemany(SQL_CONSTANT, list_of_tuples)
```

### pytest --import-mode=importlib Fixture Import
**Source:** `packages/trading-core/tests/test_orb_strategy.py` lines 54-55
**Apply to:** All new test files
```python
# Import fixture functions directly — NOT as pytest fixtures
# (--import-mode=importlib + no tests/__init__.py pattern)
from fixtures.orb_day import orb_day_bars as _orb_day_bars
```

### async test auto-mode
**Source:** `packages/trading-core/tests/test_event_bus.py` lines 1-11
**Apply to:** `test_ws_stream.py`, any async tests in `test_backtest_engine.py`
```python
# asyncio_mode = "auto" in pyproject.toml [tool.pytest.ini_options]
# No @pytest.mark.asyncio decorator needed — test coroutines are auto-awaited
async def test_something():
    ...
```

### 'use client' Client Component Pattern
**Source:** `apps/web/app/page.tsx` (React Server Component stub)
**Apply to:** `dashboard/page.tsx`, `Chart.tsx`, `EquityCurve.tsx`, all hooks
```typescript
'use client'  // required for useEffect, useState, useRef, WebSocket
```

---

## No Analog Found

Files with no close match in the codebase (use RESEARCH.md patterns instead):

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `apps/web/components/Chart.tsx` | component | event-driven | No lightweight-charts components exist yet; use RESEARCH.md §Chart Setup Pattern |
| `apps/web/components/EquityCurve.tsx` | component | event-driven | Same — no chart components exist |
| `apps/web/hooks/useWebSocket.ts` | hook | event-driven | No React hooks exist in codebase |
| `apps/web/hooks/useBars.ts` | hook | request-response | No TanStack Query hooks exist in codebase |

**Critical RESEARCH.md facts for these files (no analog):**
- `createSeriesMarkers(series, [])` — not `series.setMarkers()` (removed in v5)
- `chart.addSeries(LineSeries, opts, 1)` — third arg is paneIndex for second pane
- Time data is Unix seconds (UTC); display conversion via `Intl.DateTimeFormat` with `timeZone: 'America/New_York'`
- `useEffect` cleanup MUST call `chart.remove()` to prevent memory leaks

---

## Metadata

**Analog search scope:** `packages/trading-core/src/`, `packages/trading-core/tests/`, `packages/api/src/`, `packages/api/tests/`, `apps/web/app/`, `scripts/`
**Files scanned:** 35 Python files + 4 TypeScript files + 2 config files
**Pattern extraction date:** 2026-05-16
