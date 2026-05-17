#!/usr/bin/env python3
"""Backtest CLI — runs ORBStrategy over DuckDB bars and persists results (BT-09, FND-08).

Pipeline:
    DuckDB bars query (--symbol --tf --from --to)
        -> StrategyRegistry.load(--config)
        -> BacktestEngine.run(run_id, bars, strategy, risk_manager, executor, seed)
        -> DuckDBStore.write_run + write_backtest + write_trades
        -> write_equity_parquet -> data/parquet/equity/{run_id}.parquet

Reproducibility (FND-08):
    Same --symbol --tf --from --to --config --seed on the same DuckDB data
    produces byte-identical equity-curve Parquet. The data_hash + param_hash +
    git_sha + seed are written to the runs row for forensic traceability.

Exit codes:
    0 — status='ok' (backtest ran and all writes succeeded)
    1 — status='failed' (exception; runs row still written with status='failed')

Threat mitigations:
    T-03-03-01: CLI args use argparse choices= for --symbol/--tf/--strategy;
                DuckDB query uses parameterized ? placeholders (no interpolation).
    T-03-03-02: driver loop uses the locked snapshot→on_bar→_push_bar order (BL-1 gate).
    T-03-03-03: write_equity_parquet uses byte-stable Parquet flags (FND-08).
    T-03-03-04: StrategyRegistry.load uses yaml.safe_load (locked in Phase 2).

Plan 03-03.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

# Defensive: reconfigure stdout/stderr to UTF-8 BEFORE any module-level import
# (Pitfall 5 — Windows piped-stdout cp1252 trap; mirrors seed_bars.py pattern).
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Make sure `packages/trading-core/src` is on sys.path when invoked outside
# the uv `run` shim (mirrors seed_bars.py pattern).
_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "packages" / "trading-core" / "src"
if _SRC.exists() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from trading_core.backtest.engine import BacktestEngine, write_equity_parquet
from trading_core.config import Settings
from trading_core.data.models import Bar
from trading_core.execution.paper import PaperExecutor
from trading_core.logging import get_logger, setup_logging
from trading_core.risk.models import RiskConfig
from trading_core.risk.pass_through import PassThroughRiskManager
from trading_core.storage.duckdb_store import DuckDBStore
from trading_core.storage.runs import adr_hash, data_hash, git_sha, new_run_id, param_hash
from trading_core.strategy.registry import StrategyRegistry


def _parse_iso_utc(s: str) -> datetime:
    """Parse an ISO 8601 date / datetime string as tz-aware UTC.

    Accepts:
        '2024-01-02'        -> 2024-01-02T00:00 UTC
        '2024-01-02T13:30'  -> 2024-01-02T13:30 UTC
    """
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="run_backtest",
        description=(
            "Run ORBStrategy backtest over DuckDB bars. "
            "Writes runs + backtests + trades rows and equity-curve Parquet. "
            "Exit codes: 0 ok, 1 failed."
        ),
    )
    p.add_argument(
        "--strategy",
        required=True,
        choices=["orb"],
        help="Strategy to run. Currently only 'orb' is supported (Phase 7 adds more).",
    )
    p.add_argument(
        "--symbol",
        required=True,
        choices=["ES", "MES", "SPY"],
        help="Instrument symbol. Parameterized in SQL (T-03-03-01).",
    )
    p.add_argument(
        "--tf",
        required=True,
        choices=["1m", "5m", "15m"],
        help="Bar timeframe.",
    )
    p.add_argument(
        "--from",
        dest="frm",
        type=_parse_iso_utc,
        required=True,
        help="ISO 8601 start (inclusive, UTC). Bare date interpreted as 00:00 UTC.",
    )
    p.add_argument(
        "--to",
        type=_parse_iso_utc,
        required=True,
        help="ISO 8601 end (exclusive, UTC). Bare date interpreted as 00:00 UTC.",
    )
    p.add_argument(
        "--config",
        type=Path,
        default=Path("config/strategies/orb.yaml"),
        help="Path to strategy YAML config (default: config/strategies/orb.yaml).",
    )
    p.add_argument(
        "--seed",
        type=int,
        default=42,
        help="RNG seed for VBT reproducibility (FND-08; default 42).",
    )
    p.add_argument(
        "--duckdb-path",
        dest="duckdb_path",
        type=Path,
        default=None,
        help="Override Settings.duckdb_path (default: data/duckdb/trading.duckdb).",
    )
    p.add_argument(
        "--equity-root",
        dest="equity_root",
        type=Path,
        default=Path("data/parquet/equity"),
        help="Root directory for equity-curve Parquet files (default: data/parquet/equity).",
    )
    p.add_argument(
        "--init-cash",
        dest="init_cash",
        type=float,
        default=10_000.0,
        help="Starting cash for the backtest (default: 10000.0).",
    )
    return p


async def main(args: argparse.Namespace) -> int:
    """Async backtest pipeline — invoked by __main__ via asyncio.run.

    Returns:
        Exit code: 0 ok, 1 failed.
    """
    settings = Settings()
    duckdb_path: Path = args.duckdb_path or settings.duckdb_path

    setup_logging(settings.audit_log_dir)

    log = get_logger(__name__)
    run_id = new_run_id()
    log = log.bind(
        run_id=run_id,
        symbol=args.symbol,
        tf=args.tf,
        strategy=args.strategy,
    )

    log.info(
        "backtest.start",
        from_ts=str(args.frm),
        to_ts=str(args.to),
        seed=args.seed,
        config=str(args.config),
    )

    # Build args_dict for param_hash (JSON-safe primitives only)
    args_dict = {
        "symbol": args.symbol,
        "tf": args.tf,
        "from": args.frm.isoformat(),
        "to": args.to.isoformat(),
        "config": str(args.config),
        "seed": args.seed,
        "init_cash": args.init_cash,
        "strategy": args.strategy,
    }

    started_at = datetime.now(tz=timezone.utc)
    finished_at: datetime | None = None
    status = "failed"
    notes = ""
    df = None
    store: DuckDBStore | None = None

    try:
        store = DuckDBStore(duckdb_path)
        store.ensure_schema()

        # Query bars (parameterized — T-03-03-01)
        df = store._conn.execute(
            """
            SELECT symbol, timeframe, ts_utc, open, high, low, close, volume,
                   rollover_seam, provider
            FROM bars
            WHERE symbol = ? AND timeframe = ? AND ts_utc >= ? AND ts_utc < ?
            ORDER BY ts_utc ASC
            """,
            [args.symbol, args.tf, args.frm, args.to],
        ).fetch_df()

        if df.empty:
            raise RuntimeError(
                f"No bars found for {args.symbol} {args.tf} in [{args.frm}, {args.to}). "
                "Run seed_bars.py first."
            )

        log.info("bars.loaded", row_count=len(df))

        # Reconstruct Bar objects from DataFrame rows
        bars: list[Bar] = [
            Bar(
                symbol=str(row.symbol),
                timeframe=str(row.timeframe),
                ts_utc=row.ts_utc.to_pydatetime().astimezone(timezone.utc) if hasattr(row.ts_utc, "to_pydatetime") else row.ts_utc,
                open=Decimal(str(row.open)),
                high=Decimal(str(row.high)),
                low=Decimal(str(row.low)),
                close=Decimal(str(row.close)),
                volume=int(row.volume),
                rollover_seam=bool(row.rollover_seam),
            )
            for row in df.itertuples(index=False)
        ]

        # Load strategy from YAML config
        strategy = StrategyRegistry.load(args.config)

        # Wire up risk manager + executor
        risk_manager = PassThroughRiskManager(RiskConfig())
        executor = PaperExecutor(args.symbol)

        # Run the backtest
        engine = BacktestEngine(symbol=args.symbol)
        result = await engine.run(
            run_id=run_id,
            bars=bars,
            strategy=strategy,
            risk_manager=risk_manager,
            executor=executor,
            seed=args.seed,
            init_cash=args.init_cash,
        )

        # Write equity-curve Parquet (byte-stable flags — FND-08)
        equity_path = args.equity_root / f"{run_id}.parquet"
        write_equity_parquet(result.equity_df, equity_path)
        log.info("equity_parquet.written", path=str(equity_path))

        # Write backtests row (explicit kwarg unpack — not ** to avoid metrics key mismatch)
        m = result.metrics
        store.write_backtest(
            run_id=run_id,
            strategy_id="orb-v1",
            symbol=args.symbol,
            timeframe=args.tf,
            from_ts=args.frm,
            to_ts=args.to,
            param_hash=param_hash(args_dict),
            equity_curve_path=str(equity_path.resolve().relative_to(_REPO_ROOT)),
            total_return=m["total_return"] if m["total_return"] is not None else 0.0,
            cagr=m["cagr"] if m["cagr"] is not None else 0.0,
            sharpe=m["sharpe"] if m["sharpe"] is not None else 0.0,
            sortino=m["sortino"] if m["sortino"] is not None else 0.0,
            calmar=m["calmar"] if m["calmar"] is not None else 0.0,
            max_dd=m["max_dd"] if m["max_dd"] is not None else 0.0,
            max_dd_duration_bars=m["max_dd_duration_bars"] if m["max_dd_duration_bars"] is not None else 0,
            win_rate=m["win_rate"] if m["win_rate"] is not None else 0.0,
            expectancy=m["expectancy"] if m["expectancy"] is not None else 0.0,
            profit_factor=m["profit_factor"] if m["profit_factor"] is not None else 0.0,
            trade_count=m["trade_count"],
            avg_hold_bars=m["avg_hold_bars"] if m["avg_hold_bars"] is not None else 0.0,
        )

        # Write trade rows
        store.write_trades(result.trades)

        status = "ok"
        output = {
            "run_id": run_id,
            "status": "ok",
            "trade_count": result.metrics["trade_count"],
            "total_return": result.metrics["total_return"],
        }
        print(json.dumps(output))
        log.info("backtest.complete", **output)
        return 0

    except Exception as exc:  # noqa: BLE001 — finally block guarantees runs row
        status = "failed"
        notes = f"{type(exc).__name__}: {exc}"
        log.exception("backtest.failed", error_type=type(exc).__name__)
        return 1

    finally:
        # ALWAYS write the runs row — even on failure (audit chain invariant)
        try:
            finished_at = datetime.now(tz=timezone.utc)
            if store is not None:
                store.write_run(
                    run_id=run_id,
                    git_sha=git_sha(),
                    data_hash=data_hash(df) if df is not None and not df.empty else "",
                    param_hash=param_hash(args_dict),
                    seed=int(args.seed),
                    adr_hash=adr_hash(
                        _REPO_ROOT / ".planning" / "decisions" / "0001-data-provider.md"
                    ),
                    started_at=started_at,
                    finished_at=finished_at,
                    status=status,
                    notes=notes,
                )
        except Exception:  # noqa: BLE001
            log.exception("runs.write_run.failed")
        finally:
            try:
                if store is not None:
                    store.close()
            except Exception:
                pass


if __name__ == "__main__":
    parser = _build_parser()
    parsed_args = parser.parse_args()
    sys.exit(asyncio.run(main(parsed_args)))
