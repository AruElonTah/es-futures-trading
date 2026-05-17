#!/usr/bin/env python3
"""Optimization CLI — grid + walk-forward optimization runner (OPT-02..OPT-08).

Pipeline:
    ADR gate (.planning/decisions/opt-*.md must exist and have required fields)
        -> Holdout guard (check if OOS touches last 6 months)
        -> OptSpace.load(--space) -> 125 combos
        -> get_fold_boundaries(bars, is_months, oos_months)
        -> ProcessPoolExecutor (max_workers=cpu_count-1) -> 125 futures (run_combo)
        -> Collect results -> write opt_runs + opt_results to DuckDB

Trust boundaries (PLAN.md threat model):
    T-04-02-01: Worker D-07 isolation — workers import only trading-core
    T-04-02-02: Workers use duckdb.connect(read_only=True) — cannot write main DB
    T-04-02-03: equity_curve_path served via API validates path.relative_to(OPT_ROOT)
    T-04-02-04: max_workers=cpu_count-1 (accept: single-operator localhost)

Exit codes:
    0 — complete (all workers succeeded, opt_runs row written with status='complete')
    1 — failed or gate refused (ADR gate, holdout quota, missing bars, worker error)

D-09: Pre-run ADR gate — reads .planning/decisions/opt-*.md glob.
D-10: Holdout guard — 6-month barrier, 3-burn quarterly quota.
D-03: Coarse-grid-first — OptSpace model_validator enforces >=5 values per axis.

Plan 04-02.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

# Defensive: reconfigure stdout/stderr to UTF-8 BEFORE any module-level import
# (Pitfall 5 — Windows piped-stdout cp1252 trap; mirrors run_backtest.py pattern).
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Make sure `packages/trading-core/src` is on sys.path when invoked outside
# the uv `run` shim (mirrors run_backtest.py pattern).
_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "packages" / "trading-core" / "src"
if _SRC.exists() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

# Allow tests to override the repo root for ADR gate lookup without running the script
# from the actual repo. Set GSD_OPT_REPO_ROOT env var to override _REPO_ROOT.
_OPT_REPO_ROOT = Path(os.environ.get("GSD_OPT_REPO_ROOT", str(_REPO_ROOT)))

from dateutil.relativedelta import relativedelta  # noqa: E402 — after sys.path setup

from trading_core.config import Settings  # noqa: E402
from trading_core.data.models import Bar  # noqa: E402
from trading_core.logging import get_logger, setup_logging  # noqa: E402
from trading_core.optimization.space import OptSpace  # noqa: E402
from trading_core.optimization.splitter import get_fold_boundaries  # noqa: E402
from trading_core.optimization.worker import run_combo  # noqa: E402
from trading_core.storage.duckdb_store import DuckDBStore  # noqa: E402
from trading_core.storage.runs import adr_hash, new_run_id, param_hash  # noqa: E402


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


def current_quarter_str() -> str:
    """Return the current calendar quarter as 'YYYYQn' (e.g., '2026Q2')."""
    now = datetime.now(tz=timezone.utc)
    q = (now.month - 1) // 3 + 1
    return f"{now.year}Q{q}"


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="run_opt",
        description=(
            "Grid + walk-forward optimization runner. "
            "Requires a committed opt-*.md ADR in .planning/decisions/ (D-09). "
            "Exit codes: 0 complete, 1 failed/refused."
        ),
    )
    p.add_argument(
        "--space",
        type=Path,
        required=True,
        help="Path to optspace.yaml (e.g., config/strategies/orb.optspace.yaml).",
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
        "--seed",
        type=int,
        default=42,
        help="RNG seed for reproducibility (FND-08; default 42).",
    )
    p.add_argument(
        "--is-months",
        dest="is_months",
        type=int,
        default=6,
        help="In-sample window in calendar months (default 6).",
    )
    p.add_argument(
        "--oos-months",
        dest="oos_months",
        type=int,
        default=1,
        help="Out-of-sample window in calendar months (default 1).",
    )
    p.add_argument(
        "--burn-holdout",
        dest="burn_holdout",
        action="store_true",
        help=(
            "Allow OOS window to touch the last 6 months (holdout). "
            "Counts against the 3-burn quarterly quota (OPT-08)."
        ),
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
    return p


def _check_adr_gate(repo_root: Path) -> str:
    """Check the ADR gate (D-09): .planning/decisions/opt-*.md must exist and be complete.

    Returns the adr_hash string on success.
    Prints error message to stderr and calls sys.exit(1) on failure.
    """
    decisions_dir = repo_root / ".planning" / "decisions"
    glob_results = list(decisions_dir.glob("opt-*.md")) if decisions_dir.exists() else []

    if not glob_results:
        print(
            "ERROR: No optimization ADR found. "
            "Copy .planning/decisions/opt-template.md to opt-NNNN-<slug>.md "
            "and fill in the required fields.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Read the first matching ADR and check required fields
    adr_path = sorted(glob_results)[0]
    adr_content = adr_path.read_text(encoding="utf-8")

    required_fields = ["is_oos_split", "optspace_path", "objective", "seed"]
    missing_fields = [f for f in required_fields if f"`{f}`" not in adr_content and f not in adr_content]

    if missing_fields:
        print(
            f"ERROR: Optimization ADR at '{adr_path}' is missing required fields: "
            f"{', '.join(missing_fields)}. "
            "Add these fields to your opt-*.md ADR before running.",
            file=sys.stderr,
        )
        sys.exit(1)

    return adr_hash(adr_path)


def _check_holdout_guard(
    *,
    to_dt: datetime,
    burn_holdout: bool,
    store: DuckDBStore,
    run_id: str,
) -> None:
    """Check the holdout guard (D-10).

    If the OOS --to date touches the last 6 months, requires --burn-holdout.
    If --burn-holdout is passed, checks the 3-burn quarterly quota.
    Prints error and calls sys.exit(1) on refusal.
    Writes a holdout_burns row if the burn is allowed.
    """
    holdout_start = datetime.now(tz=timezone.utc) - relativedelta(months=6)

    if to_dt > holdout_start:
        if not burn_holdout:
            print(
                "ERROR: OOS window touches holdout period (last 6 months). "
                "Pass --burn-holdout to proceed (quota: 3 per quarter).",
                file=sys.stderr,
            )
            sys.exit(1)

        # --burn-holdout passed — check quota
        quarter = current_quarter_str()
        if not store.check_holdout_quota(quarter):
            print(
                f"ERROR: Holdout burn quota exceeded (3 burns this quarter: {quarter}). "
                "Wait until next quarter or use data that doesn't touch the holdout period.",
                file=sys.stderr,
            )
            sys.exit(1)

        # Quota allows the burn — record it
        store.write_holdout_burn(burn_id=new_run_id(), run_id=run_id, quarter=quarter)


def main(args: argparse.Namespace) -> int:
    """Main optimization pipeline.

    Returns:
        Exit code: 0 complete, 1 failed.
    """
    # Determine repo root for ADR gate — use the env-var-overridable root.
    # In tests, set GSD_OPT_REPO_ROOT=tmp_path to point to a test directory.
    repo_root = _OPT_REPO_ROOT

    # --- ADR gate (D-09) ---
    adr_hash_str = _check_adr_gate(repo_root)

    settings = Settings()
    duckdb_path: Path = args.duckdb_path or settings.duckdb_path
    setup_logging(settings.audit_log_dir)

    log = get_logger(__name__)
    run_id = new_run_id()
    log = log.bind(run_id=run_id, symbol=args.symbol, tf=args.tf)

    log.info(
        "opt.start",
        space=str(args.space),
        from_ts=str(args.frm),
        to_ts=str(args.to),
        seed=args.seed,
        is_months=args.is_months,
        oos_months=args.oos_months,
    )

    store: DuckDBStore | None = None
    try:
        store = DuckDBStore(duckdb_path)
        store.ensure_schema()

        # --- Holdout guard (D-10) ---
        _check_holdout_guard(
            to_dt=args.to,
            burn_holdout=args.burn_holdout,
            store=store,
            run_id=run_id,
        )

        # --- Load OptSpace ---
        space = OptSpace.load(args.space)
        combo_list = space.combos()  # 125 dicts for the default 5x5x5 grid
        param_grid_hash_str = space.param_grid_hash()

        log.info("opt.space_loaded", combo_count=len(combo_list))

        # --- Load bars from DuckDB ---
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
            print(
                f"ERROR: No bars found for {args.symbol} {args.tf} "
                f"in [{args.frm}, {args.to}). Run seed_bars.py first.",
                file=sys.stderr,
            )
            return 1

        log.info("bars.loaded", row_count=len(df))

        # --- Generate fold boundaries ---
        fold_boundaries = get_fold_boundaries(
            df,
            is_months=args.is_months,
            oos_months=args.oos_months,
        )
        log.info("opt.folds_generated", fold_count=len(fold_boundaries))

        # --- Shard directory ---
        shard_dir = Path("data/parquet/opt") / run_id
        shard_dir.mkdir(parents=True, exist_ok=True)

        # --- Write initial opt_runs row with status='running' ---
        store.write_opt_run(
            run_id=run_id,
            strategy_id=space.strategy,
            adr_hash=adr_hash_str,
            param_grid_hash=param_grid_hash_str,
            is_window_months=args.is_months,
            oos_window_months=args.oos_months,
            step_months=1,
            seed=args.seed,
            fold_count=len(fold_boundaries),
            completed_combos=0,
            total_combos=len(combo_list),
            status="running",
        )

        # --- ProcessPoolExecutor dispatch (D-06) ---
        # max_workers = cpu_count - 1 (leaves one core for OS/orchestrator — T-04-02-04)
        max_workers = max(1, (os.cpu_count() or 2) - 1)
        log.info("opt.dispatch", max_workers=max_workers, total_combos=len(combo_list))

        all_rows: list[dict] = []

        with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as executor:
            future_to_combo = {
                executor.submit(
                    run_combo,
                    combo_dict=combo,
                    fold_boundaries=fold_boundaries,
                    db_path=str(duckdb_path),
                    run_id=run_id,
                    symbol=args.symbol,
                    timeframe=args.tf,
                    seed=args.seed,
                    shard_dir=str(shard_dir),
                    param_hash_str=param_hash(combo),
                ): combo
                for combo in combo_list
            }

            for future in concurrent.futures.as_completed(future_to_combo):
                combo = future_to_combo[future]
                try:
                    fold_results = future.result()
                    all_rows.extend(fold_results)
                    log.info(
                        "opt.combo.complete",
                        opening_range_minutes=combo.get("opening_range_minutes"),
                        atr_stop_mult=combo.get("atr_stop_mult"),
                        r_target=combo.get("r_target"),
                        fold_count=len(fold_results),
                    )
                except Exception as exc:
                    log.exception(
                        "opt.combo.failed",
                        combo=combo,
                        error_type=type(exc).__name__,
                    )
                    # Continue collecting other results; this combo is lost

        # --- Aggregate: add run_id and result_id to each row ---
        for row in all_rows:
            row["result_id"] = new_run_id()
            row["run_id"] = run_id

        # --- Write opt_results rows ---
        store.write_opt_results(all_rows)

        # --- Update opt_runs status to 'complete' ---
        store._conn.execute(
            "UPDATE opt_runs SET status='complete', completed_combos=? WHERE run_id=?",
            [len(combo_list), run_id],
        )

        output = {
            "run_id": run_id,
            "status": "complete",
            "total_combos": len(combo_list),
            "fold_count": len(fold_boundaries),
            "result_rows": len(all_rows),
        }
        print(json.dumps(output))
        log.info("opt.run.complete", **output)
        return 0

    except SystemExit:
        raise  # re-raise sys.exit() calls (ADR gate, holdout guard)

    except Exception as exc:
        log.exception("opt.run.failed", error_type=type(exc).__name__)
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)

        # Update opt_runs status to 'failed' if the row was written
        if store is not None:
            try:
                store._conn.execute(
                    "UPDATE opt_runs SET status='failed' WHERE run_id=? AND status='running'",
                    [run_id],
                )
            except Exception:
                pass

        return 1

    finally:
        if store is not None:
            try:
                store.close()
            except Exception:
                pass


if __name__ == "__main__":
    parser = _build_parser()
    parsed_args = parser.parse_args()
    sys.exit(main(parsed_args))
