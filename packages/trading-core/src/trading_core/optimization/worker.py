"""Optimization worker — module-level run_combo() function (Windows spawn-safe).

Phase 4 Plan 02 — OPT-02, D-06, D-07, D-08.

Architecture (D-06):
    Unit of work = one param-combo across all folds.
    Each worker receives: combo_dict, fold_boundaries[], db_path, run_id, symbol,
    timeframe, seed, shard_dir, param_hash_str.
    Worker loads bars from DuckDB read-only connection, runs BacktestEngine per
    fold (IS then OOS), writes per-fold equity Parquet shards, returns list of
    per-fold result dicts.

Windows spawn requirement (Pitfall 2 — RESEARCH.md):
    run_combo MUST be defined at module level (not inside __main__ or any closure).
    Windows uses spawn (not fork); child processes import this module fresh.
    The orchestrator imports via: from trading_core.optimization.worker import run_combo

Read-only DuckDB (Pitfall 3 / T-04-02-02):
    Workers open duckdb.connect(db_path, read_only=True) — cannot acquire write lock.
    DuckDBStore is NOT instantiated in workers (ensure_schema would fail on read_only).

Fold boundaries (Pitfall 4):
    Fold boundaries are ISO date strings (picklable across ProcessPoolExecutor on Windows).
    Workers parse them back with datetime.fromisoformat().

# D-07: workers import only trading-core (never api or tv_bridge)
"""

from __future__ import annotations

import asyncio
import dataclasses
import math
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path

import duckdb
import pandas as pd

from trading_core.backtest.engine import BacktestEngine, write_equity_parquet
from trading_core.data.models import Bar
from trading_core.execution.paper import PaperExecutor
from trading_core.risk.models import RiskConfig, RiskState
from trading_core.risk.pass_through import PassThroughRiskManager
from trading_core.storage.runs import new_run_id, git_sha as _git_sha, data_hash as _data_hash
from trading_core.strategy.orb import ORBConfig, ORBStrategy

# Module-level frozenset of ORBConfig field names (computed once at import time).
# Used to filter combo_dict keys before passing to ORBConfig(**...).
# D-07: This file must never import api, tv_bridge, or any module that imports them.
_ORBCONFIG_FIELDS: frozenset[str] = frozenset(
    f.name for f in dataclasses.fields(ORBConfig)
)


def _bars_from_df(df: pd.DataFrame, symbol: str, timeframe: str) -> list[Bar]:
    """Convert DuckDB query result DataFrame to list[Bar].

    Follows the same pattern as run_backtest.py lines 226-239.
    """
    bars: list[Bar] = []
    for row in df.itertuples(index=False):
        ts = row.ts_utc
        if hasattr(ts, "to_pydatetime"):
            ts = ts.to_pydatetime()
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        else:
            ts = ts.astimezone(timezone.utc)
        bars.append(
            Bar(
                symbol=str(row.symbol),
                timeframe=str(row.timeframe),
                ts_utc=ts,
                open=Decimal(str(row.open)),
                high=Decimal(str(row.high)),
                low=Decimal(str(row.low)),
                close=Decimal(str(row.close)),
                volume=int(row.volume),
                rollover_seam=bool(row.rollover_seam),
            )
        )
    return bars


def _or_none_float(x) -> float | None:
    """Coerce NaN/inf floats to None for DuckDB-safe storage."""
    if x is None:
        return None
    try:
        f = float(x)
        if not math.isfinite(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


def run_combo(
    *,
    combo_dict: dict,
    fold_boundaries: list[dict],
    db_path: str,
    run_id: str,
    symbol: str,
    timeframe: str,
    seed: int,
    shard_dir: str,
    param_hash_str: str,
) -> list[dict]:
    """Worker function: run one param combo across all folds.

    Returns a list of per-fold result dicts (one per fold).

    This function MUST remain at module level for Windows ProcessPoolExecutor
    spawn pickling (Pitfall 2 / RESEARCH.md). Do NOT move it inside a class,
    __main__ block, or any closure.

    Args:
        combo_dict:      Parameter dict for one ORBConfig variant.
                         Keys must be valid ORBConfig field names.
        fold_boundaries: List of IS/OOS fold boundary dicts with ISO date strings.
                         Each dict: fold_idx, is_start, is_end, oos_start, oos_end.
        db_path:         String path to DuckDB file (read_only=True connection).
        run_id:          UUID7 string for the parent optimization run.
        symbol:          Instrument symbol (e.g., "SPY", "ES").
        timeframe:       Bar timeframe (e.g., "1m").
        seed:            RNG seed for BacktestEngine reproducibility.
        shard_dir:       String path to directory for equity curve Parquet shards.
        param_hash_str:  SHA256 hex of the sorted JSON combo_dict (for naming shards).

    Returns:
        List of result dicts, one per fold. Each dict contains:
            fold_idx, param_hash, opening_range_minutes, atr_stop_mult, r_target,
            is_sharpe, oos_sharpe, is_return, oos_return, edge_ratio,
            equity_curve_path (OOS parquet path as str), git_sha, data_hash, seed.
    """
    # D-07: workers import only trading-core (enforced above; comment here for clarity)
    conn = duckdb.connect(db_path, read_only=True)
    results: list[dict] = []

    try:
        for fold in fold_boundaries:
            fold_idx = int(fold["fold_idx"])
            is_start_str = fold["is_start"]
            is_end_str = fold["is_end"]
            oos_start_str = fold["oos_start"]
            oos_end_str = fold["oos_end"]

            # Parse ISO date strings back to datetime for DuckDB query
            is_start_dt = datetime.fromisoformat(is_start_str).replace(tzinfo=timezone.utc)
            oos_start_dt = datetime.fromisoformat(oos_start_str).replace(tzinfo=timezone.utc)
            # oos_end is inclusive (last day), so we need the day AFTER for exclusive upper bound
            oos_end_dt = datetime.fromisoformat(oos_end_str).replace(tzinfo=timezone.utc)
            oos_end_exclusive = oos_end_dt + timedelta(days=1)

            # Construct ORBConfig and strategy to determine warmup_bars count
            orb_kwargs = {k: v for k, v in combo_dict.items() if k in _ORBCONFIG_FIELDS}
            config = ORBConfig(**orb_kwargs)
            strategy = ORBStrategy(config)
            warmup_n = strategy.warmup_bars()

            # Compute warmup start: is_start minus buffer (1.5 × warmup_n minutes)
            # Use a conservative daily buffer: warmup_n minutes at 1.5× safety margin,
            # rounded up to whole days then padded by 5 extra trading days.
            # For ORBConfig.atr_period=14, warmup_bars()=14 → ~14 minutes, safely within 1 day.
            # Use a generous 30-day lookback to capture warmup_n bars regardless of holidays.
            warmup_buffer_days = max(1, (warmup_n * 2) // 390 + 5)  # at least 5 trading days
            warmup_start_dt = is_start_dt - timedelta(days=warmup_buffer_days)

            # Fetch all bars from warmup_start through oos_end_exclusive (single read)
            full_df = conn.execute(
                "SELECT symbol, timeframe, ts_utc, open, high, low, close, volume, "
                "rollover_seam "
                "FROM bars "
                "WHERE symbol = ? AND timeframe = ? AND ts_utc >= ? AND ts_utc < ? "
                "ORDER BY ts_utc ASC",
                [symbol, timeframe, warmup_start_dt, oos_end_exclusive],
            ).fetch_df()

            if full_df.empty:
                # No bars for this fold — append a zero-result and continue
                results.append(_zero_fold_result(
                    fold_idx=fold_idx,
                    param_hash_str=param_hash_str,
                    combo_dict=combo_dict,
                    seed=seed,
                ))
                continue

            # Build Bar list from full_df
            all_bars = _bars_from_df(full_df, symbol, timeframe)

            # Slice into warmup / IS / OOS by timestamp
            # is_start_dt corresponds to the start of the IS day (00:00 UTC),
            # so all bars with ts_utc >= is_start_dt are IS or OOS.
            warmup_bars_list = [b for b in all_bars if b.ts_utc < is_start_dt]
            is_bars_list = [b for b in all_bars if is_start_dt <= b.ts_utc < oos_start_dt]
            oos_bars_list = [b for b in all_bars if oos_start_dt <= b.ts_utc < oos_end_exclusive]

            # -------------------------------------------------------
            # IS backtest
            # -------------------------------------------------------
            # Build fresh strategy for IS pass; prime with warmup bars only (no on_bar)
            is_strategy = ORBStrategy(config)
            for wb in warmup_bars_list:
                is_strategy._push_bar(wb)

            is_engine = BacktestEngine(symbol=symbol)
            is_result = asyncio.run(
                is_engine.run(
                    run_id=new_run_id(),
                    bars=is_bars_list,
                    strategy=is_strategy,
                    risk_manager=PassThroughRiskManager(RiskConfig()),
                    executor=PaperExecutor(symbol),
                    seed=seed,
                    init_cash=10_000.0,
                )
            )

            # Write IS equity curve Parquet shard
            is_shard_path = (
                Path(shard_dir)
                / f"worker_{param_hash_str[:12]}_fold{fold_idx}_is.parquet"
            )
            write_equity_parquet(is_result.equity_df, is_shard_path)

            # -------------------------------------------------------
            # OOS backtest
            # -------------------------------------------------------
            # Build fresh strategy for OOS pass; prime with warmup + IS bars
            oos_strategy = ORBStrategy(config)
            for wb in warmup_bars_list:
                oos_strategy._push_bar(wb)
            for ib in is_bars_list:
                # Prime OOS strategy with IS bars (no on_bar — indicators only)
                oos_strategy._push_bar(ib)

            oos_engine = BacktestEngine(symbol=symbol)
            oos_result = asyncio.run(
                oos_engine.run(
                    run_id=new_run_id(),
                    bars=oos_bars_list,
                    strategy=oos_strategy,
                    risk_manager=PassThroughRiskManager(RiskConfig()),
                    executor=PaperExecutor(symbol),
                    seed=seed,
                    init_cash=10_000.0,
                )
            )

            # Write OOS equity curve Parquet shard
            oos_shard_path = (
                Path(shard_dir)
                / f"worker_{param_hash_str[:12]}_fold{fold_idx}_oos.parquet"
            )
            write_equity_parquet(oos_result.equity_df, oos_shard_path)

            # -------------------------------------------------------
            # Collect metrics
            # -------------------------------------------------------
            is_sharpe = _or_none_float(is_result.metrics.get("sharpe"))
            oos_sharpe = _or_none_float(oos_result.metrics.get("sharpe"))
            is_return = _or_none_float(is_result.metrics.get("total_return"))
            oos_return = _or_none_float(oos_result.metrics.get("total_return"))

            # Edge ratio: is_sharpe / oos_sharpe (Pitfall 8 — guard division by zero)
            edge_ratio: float | None = None
            if (
                is_sharpe is not None
                and oos_sharpe is not None
                and abs(oos_sharpe) > 1e-9
            ):
                edge_ratio = is_sharpe / oos_sharpe

            # data_hash of the full fold data (IS + OOS combined)
            # Add provider column if missing (workers fetch without it)
            hash_df = full_df.copy()
            if "provider" not in hash_df.columns:
                hash_df["provider"] = "worker"
            fold_data_hash = _data_hash(hash_df)

            results.append(
                {
                    "fold_idx": fold_idx,
                    "param_hash": param_hash_str,
                    "opening_range_minutes": combo_dict.get("opening_range_minutes"),
                    "atr_stop_mult": combo_dict.get("atr_stop_mult"),
                    "r_target": combo_dict.get("r_target"),
                    "is_sharpe": is_sharpe,
                    "oos_sharpe": oos_sharpe,
                    "is_return": is_return,
                    "oos_return": oos_return,
                    "edge_ratio": edge_ratio,
                    "equity_curve_path": str(oos_shard_path),
                    "git_sha": _git_sha(),
                    "data_hash": fold_data_hash,
                    "seed": seed,
                }
            )

    finally:
        conn.close()

    return results


def _zero_fold_result(
    *,
    fold_idx: int,
    param_hash_str: str,
    combo_dict: dict,
    seed: int,
) -> dict:
    """Return a zero-value result dict for a fold with no bars."""
    return {
        "fold_idx": fold_idx,
        "param_hash": param_hash_str,
        "opening_range_minutes": combo_dict.get("opening_range_minutes"),
        "atr_stop_mult": combo_dict.get("atr_stop_mult"),
        "r_target": combo_dict.get("r_target"),
        "is_sharpe": None,
        "oos_sharpe": None,
        "is_return": None,
        "oos_return": None,
        "edge_ratio": None,
        "equity_curve_path": None,
        "git_sha": _git_sha(),
        "data_hash": "",
        "seed": seed,
    }
