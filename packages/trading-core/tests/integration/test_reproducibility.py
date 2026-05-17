"""Integration: FND-08 reproducibility CI.

Same git_sha + data_hash + param_hash + seed must produce bitwise-identical
equity-curve Parquet (ROADMAP success criterion #3 — reproducibility CI).

Requirements:
  BT-09 — Backtest CLI run_backtest.py produces runs + backtests + trades rows.
  FND-08 — Same inputs → bitwise-identical equity-curve Parquet.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from fixtures.orb_day import orb_day_bars
from trading_core.backtest.engine import BacktestEngine, write_equity_parquet
from trading_core.execution.paper import PaperExecutor
from trading_core.risk.models import RiskConfig
from trading_core.risk.pass_through import PassThroughRiskManager
from trading_core.strategy.orb import ORBConfig, ORBStrategy


def _run_engine_once(run_id: str) -> object:
    """Run BacktestEngine over orb_day_bars with fixed seed=42."""
    bars = orb_day_bars()
    engine = BacktestEngine(symbol="SPY")
    strategy = ORBStrategy(ORBConfig())
    risk_manager = PassThroughRiskManager(RiskConfig())
    executor = PaperExecutor("SPY")
    return asyncio.run(
        engine.run(
            run_id=run_id,
            bars=bars,
            strategy=strategy,
            risk_manager=risk_manager,
            executor=executor,
            seed=42,
            init_cash=10_000.0,
        )
    )


def test_reproducibility_same_inputs_bitwise_identical(tmp_path: Path):
    """FND-08: two engine runs with identical inputs produce byte-identical equity Parquet.

    Implementation choice (locked in plan): programmatic BacktestEngine invocation
    rather than subprocess CLI — faster, more deterministic on Windows path-with-space.

    The test focuses on whether the engine + Parquet write are byte-stable.
    CLI reproducibility is covered by run_backtest.py behavioral spec.
    """
    # Run 1 — use different run_id to confirm run_id does NOT affect equity bytes
    result1 = _run_engine_once(run_id="repro-run-001")
    path1 = tmp_path / "a.parquet"
    write_equity_parquet(result1.equity_df, path1)

    # Run 2 — fresh strategy/executor instances (same bars, same seed)
    result2 = _run_engine_once(run_id="repro-run-002")
    path2 = tmp_path / "b.parquet"
    write_equity_parquet(result2.equity_df, path2)

    # FND-08 assertion: bytes must be identical
    assert path1.read_bytes() == path2.read_bytes(), (
        "Equity curve is not bitwise-identical between two runs with identical inputs. "
        "Check pyarrow write flags (compression, use_dictionary, write_statistics) "
        "and that equity_per_bar computation is deterministic (no random elements "
        "outside VBT seed=42)."
    )


def test_engine_metrics_deterministic():
    """Two runs with identical inputs produce identical metrics dicts."""
    result1 = _run_engine_once(run_id="metrics-run-001")
    result2 = _run_engine_once(run_id="metrics-run-002")

    # Metrics should be equal (NaN->None coercion already applied in engine)
    # Compare key by key to give a clear failure message
    for key in result1.metrics:
        v1 = result1.metrics[key]
        v2 = result2.metrics[key]
        if v1 is None and v2 is None:
            continue
        if isinstance(v1, float) and isinstance(v2, float):
            assert abs(v1 - v2) < 1e-10, (
                f"metrics['{key}'] differs: run1={v1}, run2={v2}"
            )
        else:
            assert v1 == v2, (
                f"metrics['{key}'] differs: run1={v1!r}, run2={v2!r}"
            )


def test_equity_df_rows_match_bar_count():
    """Equity DataFrame has exactly len(bars) rows."""
    bars = orb_day_bars()
    result = _run_engine_once(run_id="row-count-run")
    assert len(result.equity_df) == len(bars)
