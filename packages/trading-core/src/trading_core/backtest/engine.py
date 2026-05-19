"""BacktestEngine — hybrid driver loop + VBT metrics pass (Phase 3 Plan 03).

Architectural decision (D-02/D-03/D-12/BT-01..BT-09):
    Hybrid: the driver loop produces per-trade attribution (D-02) + MAE/MFE (BT-05)
    + exit_reason (D-11); VBT computes portfolio-level metrics (BT-04). VBT is
    called via safe_from_signals ONLY (D-13).

Driver loop order (Phase 2 canonical — MUST NOT CHANGE):
    1. snapshot ctx from prior-bar indicator state
    2. signal = strategy.on_bar(bar, ctx)
    3. strategy._push_bar(bar)   ← AFTER on_bar (lookahead guard)

Reproducibility:
    write_equity_parquet uses compression='none', use_dictionary=False,
    write_statistics=False — byte-stable across runs (FND-08).

DoS accept (T-03-03-05):
    Multi-year backtests may cause memory blowup (all bars in RAM). Phase 3
    scope is single-day / short-window backtests. Multi-year scaling is Phase 4's
    concern (workers + Parquet shards).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from trading_core.backtest.safe_signals import safe_from_signals
from trading_core.data.models import Bar
from trading_core.events.models import TOPIC_AUDIT, TOPIC_FILLS, TOPIC_RISK_DECISIONS
from trading_core.execution.paper import PaperExecutor
from trading_core.instruments import get as get_instrument
from trading_core.logging import get_logger
from trading_core.risk.models import DrawdownModel, RiskConfig, RiskState
from trading_core.risk.pass_through import PassThroughRiskManager
from trading_core.storage.runs import new_run_id
from trading_core.strategy.models import StrategyContext

_log = get_logger(__name__)


@dataclass
class BacktestResult:
    """Immutable result from BacktestEngine.run().

    Attributes:
        trades:    List of D-02 trade dicts (per-trade attribution chain).
        metrics:   BT-04 portfolio-level metrics dict (12 scalars + max_dd_duration_bars).
        equity_df: Per-bar equity/drawdown DataFrame (ts_utc, equity_$, drawdown_$).
    """

    trades: list
    metrics: dict
    equity_df: pd.DataFrame


def _or_none(x) -> float | None:
    """Coerce NaN/inf floats to None for DuckDB-safe storage."""
    if x is None:
        return None
    if isinstance(x, float) and not math.isfinite(x):
        return None
    return float(x)


def write_equity_parquet(equity_df: pd.DataFrame, path: Path) -> None:
    """Write equity_df to Parquet with byte-stable flags (FND-08).

    Byte-stable flags (locked in Phase 1 runs.py):
        compression='none', use_dictionary=False, write_statistics=False

    Args:
        equity_df: DataFrame with ts_utc, equity_$, drawdown_$ columns.
        path:      Target Parquet file path.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pandas(equity_df.reset_index(drop=True), preserve_index=False)
    pq.write_table(
        table,
        str(path),
        compression="none",
        use_dictionary=False,
        write_statistics=False,
    )


def _max_dd_duration_bars(pf, has_trades: bool) -> int:
    """Extract max drawdown duration in bars (minutes), returning 0 on NaN/error."""
    if not has_trades:
        return 0
    try:
        dur = pf.drawdowns.max_duration()
        # dur may be NaT (no drawdown) or a Timedelta
        import pandas as pd
        if pd.isna(dur) or dur is pd.NaT:
            return 0
        total_secs = dur.total_seconds()
        if not math.isfinite(total_secs):
            return 0
        return int(total_secs // 60)
    except Exception:
        return 0


class BacktestEngine:
    """Hybrid backtester: driver loop (D-02 attribution) + VBT pass (BT-04 metrics).

    Usage:
        engine = BacktestEngine(symbol="SPY")
        result = await engine.run(
            run_id="...",
            bars=bars,
            strategy=strategy,
            risk_manager=risk_manager,
            executor=executor,
            seed=42,
            init_cash=10_000.0,
        )
    """

    def __init__(self, *, symbol: str) -> None:
        self._symbol = symbol
        self._instrument = get_instrument(symbol)
        self._log = _log.bind(symbol=symbol)

    async def run(
        self,
        *,
        run_id: str,
        bars: list[Bar],
        strategy,
        risk_manager,
        executor: PaperExecutor,
        seed: int = 42,
        init_cash: float = 10_000.0,
        bus=None,
    ) -> BacktestResult:
        """Run a hybrid backtest over the given bar sequence.

        Phase 1 (driver loop): bar-by-bar signal generation, risk check, entry/exit
        fill simulation, MAE/MFE computation, per-trade attribution (D-02).

        Phase 2 (VBT pass): portfolio-level metrics (BT-04) via safe_from_signals.

        Args:
            run_id:       UUID7 run identifier (wired into trade dicts, BT-06).
            bars:         Ordered list of Bar objects (RTH session, 1m).
            strategy:     ORBStrategy instance (or any Strategy-protocol implementor).
            risk_manager: PassThroughRiskManager or equivalent.
            executor:     PaperExecutor or equivalent.
            seed:         RNG seed for VBT reproducibility (default 42).
            init_cash:    Starting cash (default 10_000.0).
            bus:          EventBus | None — when provided, TOPIC_AUDIT events are
                          published at signal/risk_decision/fill points for WS
                          notification. Bus subscribers MUST NOT write to DuckDB;
                          DuckDB writes are owned by FullRiskManager.check() only.

        Returns:
            BacktestResult with trades, metrics, equity_df.
        """
        if not bars:
            return BacktestResult(
                trades=[],
                metrics=self._zero_metrics(),
                equity_df=pd.DataFrame(columns=["ts_utc", "equity_$", "drawdown_$"]),
            )

        n = len(bars)
        point_value = self._instrument.point_value

        # Tracking arrays for VBT (Phase 2) and equity curve
        entries_bool: list[bool] = [False] * n
        exits_bool: list[bool] = [False] * n
        equity_per_bar: list[float] = [init_cash] * n

        # D-02 trade collection
        trades: list[dict] = []

        # Driver loop state
        open_position: dict | None = None
        realized_equity: float = init_cash  # accumulates closed-trade PnL (CR-002)

        self._log.info(
            "engine.run.start",
            run_id=run_id,
            bar_count=n,
            seed=seed,
            init_cash=init_cash,
        )

        # ----------------------------------------------------------------
        # PHASE 1: bar-by-bar driver loop
        #   Order: snapshot ctx → on_bar → _push_bar (lookahead-safe)
        # ----------------------------------------------------------------
        for i, bar in enumerate(bars):
            # Step 1: snapshot indicator state BEFORE current bar
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

            # Step 2: emit signal (strategy reads PRIOR-bar indicators via ctx)
            signal = strategy.on_bar(bar, ctx)

            # Step 3: push bar to indicators AFTER on_bar (lookahead guard)
            strategy._push_bar(bar)

            # Step 4: process entry signal
            if signal is not None and open_position is None and i + 1 < n:
                # Build RiskState from current driver-loop tracking variables (T-05-03-03).
                # realized_equity reflects all closed trades; no open position at signal time
                # (gate above ensures open_position is None), so open_exposure_dollars = 0.
                _dm = getattr(
                    getattr(risk_manager, '_config', None),
                    'drawdown_model',
                    DrawdownModel.TRAILING_INTRADAY,
                )
                state = RiskState(
                    realized_pnl_today=Decimal(str(realized_equity - init_cash)),
                    equity_high_water=Decimal(str(realized_equity)),
                    open_exposure_dollars=Decimal("0"),
                    drawdown_model=_dm,
                )
                decision = await risk_manager.check(signal, state)
                # Publish risk_decision audit event for WS notification (bus = notification-only).
                # DuckDB writes are owned by FullRiskManager.check() — no double-write here.
                if bus is not None:
                    await bus.publish(
                        TOPIC_AUDIT,
                        {
                            "topic": TOPIC_RISK_DECISIONS,
                            "entity_id": signal.signal_id,
                            "reason_code": decision.reason,
                            "payload_json": decision.model_dump_json(),
                        },
                    )
                if decision.approved:
                    next_bar = bars[i + 1]
                    entry_fill = await executor.fill_entry(signal, decision, next_bar)
                    # Publish entry fill audit event for WS notification.
                    if bus is not None:
                        await bus.publish(
                            TOPIC_AUDIT,
                            {
                                "topic": TOPIC_FILLS,
                                "entity_id": entry_fill.fill_id,
                                "reason_code": "entry_fill",
                                "payload_json": entry_fill.model_dump_json(),
                            },
                        )
                    # Notify FullRiskManager of new open position for concurrency tracking.
                    if hasattr(risk_manager, 'record_position_open'):
                        _position_info = {
                            "symbol": self._symbol,
                            "strategy_id": signal.strategy_id,
                            "side": signal.side,
                            "qty": decision.adjusted_size,
                            "avg_fill": float(entry_fill.fill_price),
                            "mark": float(entry_fill.fill_price),
                            "stop": float(signal.stop),
                            "target": float(signal.target),
                            "entry_ts_utc": (
                                entry_fill.ts_utc.isoformat()
                                if hasattr(entry_fill, 'ts_utc') else ""
                            ),
                        }
                        risk_manager.record_position_open(signal.strategy_id, _position_info)
                    open_position = {
                        "signal": signal,
                        "entry_fill": entry_fill,
                        "entry_idx": i + 1,
                        "fill_qty": decision.adjusted_size,
                    }
                    entries_bool[i] = True  # raw signal bar (safe_from_signals shifts internally)

            # Step 5: check exit on open position
            if open_position is not None:
                sig = open_position["signal"]
                ef = open_position["entry_fill"]
                entry_idx = open_position["entry_idx"]
                fill_qty = open_position["fill_qty"]

                # Do not check exit on the bar where the entry fires; the fill
                # executes at the OPEN of bars[entry_idx], so exit checks must
                # begin at entry_idx, not at the signal bar (entry_idx - 1).
                if i < entry_idx:          # signal bar: skip exit check entirely
                    continue

                is_last_rth_bar = (i == n - 1)
                exit_result = executor.check_exit(
                    side=sig.side,
                    entry_price=ef.fill_price,
                    stop=sig.stop,
                    target=sig.target,
                    bar=bar,
                    is_last_rth_bar=is_last_rth_bar,
                )

                if exit_result is not None:
                    exit_reason, exit_price = exit_result
                    exit_fill = await executor.fill_exit(
                        signal=sig,
                        exit_reason=exit_reason,
                        exit_price=exit_price,
                        exit_ts_utc=bar.ts_utc,
                        fill_qty=fill_qty,
                    )
                    # Publish exit fill audit event for WS notification.
                    if bus is not None:
                        await bus.publish(
                            TOPIC_AUDIT,
                            {
                                "topic": TOPIC_FILLS,
                                "entity_id": exit_fill.fill_id,
                                "reason_code": exit_reason,
                                "payload_json": exit_fill.model_dump_json(),
                            },
                        )
                    # Notify FullRiskManager that position is now closed.
                    if hasattr(risk_manager, 'record_position_closed'):
                        risk_manager.record_position_closed(sig.strategy_id)

                    # Compute MAE/MFE manually (Pitfall 6 — not in VBT 1.0.0 OSS)
                    mae, mfe = self._compute_mae_mfe(
                        bars=bars,
                        entry_idx=entry_idx,
                        exit_idx=i,
                        entry_price=ef.fill_price,
                        side=sig.side,
                    )

                    # Compute PnL
                    if sig.side == "long":
                        pnl = float((exit_price - ef.fill_price) * Decimal(fill_qty) * point_value)
                    else:
                        pnl = float((ef.fill_price - exit_price) * Decimal(fill_qty) * point_value)

                    # D-02 trade dict (17 fields)
                    trade_dict = {
                        "trade_id": new_run_id(),
                        "run_id": run_id,
                        "signal_id": sig.signal_id,       # BT-06: attribution chain
                        "strategy_id": sig.strategy_id,
                        "side": sig.side,
                        "entry_price": float(ef.fill_price),
                        "exit_price": float(exit_price),
                        "exit_reason": exit_reason,
                        "entry_ts_utc": ef.ts_utc,
                        "exit_ts_utc": bar.ts_utc,
                        "pnl": pnl,
                        "size": fill_qty,
                        "slippage_ticks": ef.slippage_ticks,
                        "mae": mae,
                        "mfe": mfe,
                        "stop_price": float(sig.stop),    # BT-06: enables UI stop priceLine
                        "target_price": float(sig.target), # BT-06: enables UI target priceLine
                    }
                    trades.append(trade_dict)

                    # Update equity_per_bar at exit bar with realized PnL
                    realized_equity += pnl
                    equity_per_bar[i] = realized_equity

                    exits_bool[i] = True
                    open_position = None
                else:
                    # Unrealized P&L update
                    if sig.side == "long":
                        unrealized = float(
                            (bar.close - ef.fill_price) * Decimal(fill_qty) * point_value
                        )
                    else:
                        unrealized = float(
                            (ef.fill_price - bar.close) * Decimal(fill_qty) * point_value
                        )
                    equity_per_bar[i] = realized_equity + unrealized
            else:
                # No open position — equity stays at previous value (or init_cash)
                if i > 0:
                    equity_per_bar[i] = equity_per_bar[i - 1]
                # else equity_per_bar[0] = init_cash (initialized above)

        # ----------------------------------------------------------------
        # PHASE 2: VBT metrics pass (BT-04)
        # ----------------------------------------------------------------
        timestamps = pd.DatetimeIndex([b.ts_utc for b in bars], tz="UTC")
        close_s = pd.Series([float(b.close) for b in bars], index=timestamps)
        open_s = pd.Series([float(b.open) for b in bars], index=timestamps)
        high_s = pd.Series([float(b.high) for b in bars], index=timestamps)
        low_s = pd.Series([float(b.low) for b in bars], index=timestamps)

        entries_s = pd.Series(entries_bool, index=timestamps)
        exits_s = pd.Series(exits_bool, index=timestamps)

        # Price = next-bar open (shift open by -1, final bar keeps itself)
        price_s = open_s.shift(-1).fillna(open_s)

        pf = safe_from_signals(
            close=close_s,
            entries=entries_s,
            exits=exits_s,
            price=price_s,
            freq="1min",
            init_cash=init_cash,
            size=1,
            direction="longonly",
            open=open_s,
            high=high_s,
            low=low_s,
            seed=seed,
        )

        has_trades = int(pf.trades.count()) > 0

        # Extract metrics (Pitfall 5: pf.drawdowns.max_duration() not pf.max_drawdown_duration())
        metrics = {
            "total_return": _or_none(float(pf.total_return())),
            "cagr": _or_none(float(pf.annualized_return())) if has_trades else None,
            "sharpe": _or_none(float(pf.sharpe_ratio())) if has_trades else None,
            "sortino": _or_none(float(pf.sortino_ratio())) if has_trades else None,
            "calmar": _or_none(float(pf.calmar_ratio())) if has_trades else None,
            "max_dd": _or_none(float(pf.max_drawdown())),
            "max_dd_duration_bars": _max_dd_duration_bars(pf, has_trades),
            "win_rate": _or_none(float(pf.trades.win_rate())) if has_trades else None,
            "expectancy": _or_none(float(pf.trades.expectancy())) if has_trades else None,
            "profit_factor": _or_none(float(pf.trades.profit_factor())) if has_trades else None,
            "trade_count": int(pf.trades.count()),
            "avg_hold_bars": (
                _or_none(float(pf.trades.avg_duration().total_seconds() // 60))
                if has_trades else 0
            ),
        }

        # ----------------------------------------------------------------
        # Build equity_df from driver-loop equity_per_bar
        # (driver loop equity is cleaner for attribution; VBT equity is
        # used for metrics but the per-bar values include approximation)
        # ----------------------------------------------------------------
        peak = [init_cash] * n
        for i in range(n):
            peak[i] = max(equity_per_bar[:i + 1])

        equity_df = pd.DataFrame({
            "ts_utc": [b.ts_utc for b in bars],
            "equity_$": equity_per_bar,
            "drawdown_$": [peak[i] - equity_per_bar[i] for i in range(n)],
        })

        self._log.info(
            "engine.run.complete",
            run_id=run_id,
            trade_count=len(trades),
            total_return=metrics.get("total_return"),
        )

        return BacktestResult(trades=trades, metrics=metrics, equity_df=equity_df)

    def _compute_mae_mfe(
        self,
        *,
        bars: list[Bar],
        entry_idx: int,
        exit_idx: int,
        entry_price: Decimal,
        side: str,
    ) -> tuple[float, float]:
        """Compute MAE/MFE manually (VBT 1.0.0 OSS does not expose these — Pitfall 6).

        Slices bars[entry_idx:exit_idx+1] to scan high/low range.

        For long:
            MAE = entry_price - min(low in range)  (max adverse = max drop from entry)
            MFE = max(high in range) - entry_price (max favorable = max gain from entry)
        For short:
            MAE = max(high in range) - entry_price
            MFE = entry_price - min(low in range)
        """
        if exit_idx < entry_idx:
            return 0.0, 0.0

        bar_slice = bars[entry_idx:exit_idx + 1]
        highs = [float(b.high) for b in bar_slice]
        lows = [float(b.low) for b in bar_slice]
        ep = float(entry_price)

        if side == "long":
            mae = ep - min(lows)
            mfe = max(highs) - ep
        else:
            mae = max(highs) - ep
            mfe = ep - min(lows)

        return max(0.0, mae), max(0.0, mfe)

    def _zero_metrics(self) -> dict:
        """Return a metrics dict with all keys at zero/None (used for empty bar list)."""
        return {
            "total_return": 0.0,
            "cagr": None,
            "sharpe": None,
            "sortino": None,
            "calmar": None,
            "max_dd": 0.0,
            "max_dd_duration_bars": 0,
            "win_rate": None,
            "expectancy": None,
            "profit_factor": None,
            "trade_count": 0,
            "avg_hold_bars": 0,
        }
