#!/usr/bin/env python3
"""Backfill RTH bars to DuckDB + Parquet via the configured DataSource (MD-09).

Composes the Phase 1 storage / data / calendars / runs surfaces into a
single idempotent CLI:

    python scripts/seed_bars.py --symbol SPY --tf 1m \\
        --from 2024-01-02 --to 2024-01-03 [--provider {twelvedata,tradingview}]

Pipeline:
    fetch_bars  (selected DataSource adapter)
        -> RthFilter.filter   (strip ETH bars)
        -> RolloverDetector.annotate    (flag 3rd-Friday seams)
        -> DuckDBStore.upsert_bars
        -> RthFilter.find_gaps_as_dataframe
        -> DuckDBStore.upsert_gaps
        -> DuckDBStore.write_run   (always — finally block; audit chain)

Idempotency:
    Re-running the same command produces zero NET new rows (Pitfall 2
    ON CONFLICT path) and identical data_hash. Two runs rows are written
    (one per invocation) — the audit chain is per-invocation, the data
    is per-bar.

Exit-code mapping (decided in this plan — documented under SUMMARY.md):
    0 — status='ok' (all bars loaded, zero gaps)
    1 — status='failed' (adapter raised an exception; runs row still written)
    2 — status='partial' (bars loaded but len(gaps) > 0)

Pitfall 5 — Windows piped-stdout cp1252 trap: reconfigure stdout/stderr to
UTF-8 at script entry BEFORE any import that may log. setup_logging() does
this again in case the script is imported (test path), but the script entry
also does it eagerly so even unhandled exceptions print without crashing.

Plan 01-05 Task 2.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable

# Defensive: reconfigure stdout/stderr to UTF-8 BEFORE any module-level import
# that might write to them. Phase 0 lesson — Pitfall 5.
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Make sure `packages/trading-core/src` is on sys.path when invoked outside
# the uv `run` shim (e.g., from an editable install in a CI image).
# In a standard `uv run python scripts/seed_bars.py ...` invocation this is
# already true — but keep the guard so direct `python scripts/seed_bars.py`
# also works from the repo root.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "packages" / "trading-core" / "src"
if _SRC.exists() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import pandas as pd

from trading_core.calendars.rth import RolloverDetector, RthFilter
from trading_core.config import Settings
from trading_core.data.tradingview import TradingViewDataSource
from trading_core.data.twelvedata import TwelveDataSource
from trading_core.events import EventBus
from trading_core.logging import get_logger, setup_logging
from trading_core.storage.duckdb_store import DuckDBStore
from trading_core.storage.runs import (
    adr_hash,
    data_hash,
    git_sha,
    new_run_id,
    param_hash,
)


# Provider registry — maps the --provider CLI flag to the adapter class.
# Both adapters take a Settings instance; TradingViewDataSource additionally
# requires an EventBus for DegradedStateEvent publishing (Plan 04 contract).
PROVIDERS: dict[str, str] = {
    "twelvedata": "twelvedata",
    "tradingview": "tradingview",
}


def _construct_source(
    provider: str, settings: Settings, bus: EventBus
) -> object:
    """Construct the DataSource adapter for the requested provider name."""
    if provider == "twelvedata":
        return TwelveDataSource(settings)
    if provider == "tradingview":
        return TradingViewDataSource(settings, bus=bus)
    raise ValueError(
        f"unknown provider {provider!r}; choices: {sorted(PROVIDERS)}"
    )


def _set_ts_index(df: pd.DataFrame) -> pd.DataFrame:
    """Return df with `ts_utc` promoted from column to a tz-aware DatetimeIndex.

    RthFilter.filter requires a tz-aware DatetimeIndex; the adapter returns a
    flat DataFrame with `ts_utc` as a regular column. This helper bridges
    the two shapes without mutating the input.
    """
    if "ts_utc" not in df.columns:
        # Already indexed (e.g., adapter returned an indexed shape).
        return df
    out = df.copy()
    # Cast to UTC pandas Timestamps (idempotent if already UTC).
    out["ts_utc"] = pd.to_datetime(out["ts_utc"], utc=True)
    return out.set_index("ts_utc")


def _reset_ts_column(df: pd.DataFrame) -> pd.DataFrame:
    """Inverse of _set_ts_index — push the DatetimeIndex back to a column."""
    if df.index.name == "ts_utc":
        return df.reset_index()
    return df


async def main(args: argparse.Namespace) -> int:
    """Async pipeline entry — invoked by `__main__` via asyncio.run.

    Returns:
        Exit code: 0 ok, 1 failed, 2 partial.
    """
    settings = Settings()

    # Allow a --duckdb-path override (used by tests scoped to tmp_path so
    # they never touch the operator's real database).
    duckdb_path: Path = getattr(args, "duckdb_path", None) or settings.duckdb_path

    setup_logging(settings.audit_log_dir)

    # T-01-04-01 mitigation extension: httpx's stdlib logger emits the raw
    # request URL at INFO level — bypassing TwelveDataSource._redact_url and
    # writing the literal `apikey=<value>` to the audit log. Suppress to
    # WARNING so only real failures surface; the adapter's own structlog
    # lines (already redacted) remain the audit chain. Plan 01-05 deviation
    # Rule 2 (missing critical — audit-chain hygiene). httpcore is httpx's
    # transport; same exposure.
    import logging as _stdlib_logging

    _stdlib_logging.getLogger("httpx").setLevel(_stdlib_logging.WARNING)
    _stdlib_logging.getLogger("httpcore").setLevel(_stdlib_logging.WARNING)

    log = get_logger(__name__)

    run_id = new_run_id()
    started_at = datetime.now(tz=timezone.utc)
    log = log.bind(
        run_id=run_id,
        symbol=args.symbol,
        tf=args.tf,
    )

    provider_name = args.provider or settings.default_provider
    bus = EventBus()
    source = _construct_source(provider_name, settings, bus)
    rth = RthFilter()
    rollover = RolloverDetector()
    store = DuckDBStore(duckdb_path)
    store.ensure_schema()

    log.info(
        "backfill.start",
        provider=provider_name,
        frm=args.frm.isoformat(),
        to=args.to.isoformat(),
    )

    status = "ok"
    notes = ""
    df: pd.DataFrame | None = None
    gaps_df: pd.DataFrame | None = None

    try:
        df_raw = await source.fetch_bars(  # type: ignore[attr-defined]
            args.symbol, args.tf, args.frm, args.to
        )
        log.info("fetch_bars.done", rows=len(df_raw))

        # RthFilter expects a tz-aware DatetimeIndex.
        df_indexed = _set_ts_index(df_raw)
        df_rth = rth.filter(df_indexed, symbol=args.symbol)
        log.info(
            "rth.filter",
            input_rows=len(df_indexed),
            output_rows=len(df_rth),
        )

        # Push ts_utc back to a column for RolloverDetector + DuckDBStore
        # (annotate handles both shapes; upsert_bars expects a column).
        df = _reset_ts_column(df_rth)
        df = rollover.annotate(df)

        # provider column must be present for upsert_bars to compose the SQL
        # row tuples. The adapter already injects it, but defend in depth.
        if "provider" not in df.columns:
            df["provider"] = source.name  # type: ignore[attr-defined]

        store.upsert_bars(df, provider=provider_name)

        gaps_df = rth.find_gaps_as_dataframe(
            df_rth, args.symbol, args.tf, args.frm, args.to
        )
        store.upsert_gaps(gaps_df, provider=provider_name, run_id=run_id)

        gap_count = len(gaps_df)
        if gap_count > 0:
            status = "partial"
            notes = f"backfilled {len(df)} bars; {gap_count} gaps in RTH window"
            log.warning("backfill.partial", bar_count=len(df), gap_count=gap_count)
        else:
            notes = f"backfilled {len(df)} bars; 0 gaps"
            log.info("backfill.ok", bar_count=len(df))

        # Close the adapter if it owns a long-lived client (TwelveDataSource
        # uses a one-shot client by default; TradingViewDataSource is
        # per-call; defensive aclose() call).
        aclose: Callable[[], Awaitable[None]] | None = getattr(
            source, "aclose", None
        )
        if aclose is not None:
            await aclose()

    except Exception as exc:  # noqa: BLE001 — finally block guarantees runs row
        status = "failed"
        notes = f"{type(exc).__name__}: {exc}"
        log.exception("backfill.failed", error_type=type(exc).__name__)
        df = None
    finally:
        # ALWAYS write the runs row — even on failure. Audit-chain invariant
        # (FND-08 + T-01-05-04 threat mitigation). Use try/except to make
        # this step infallible — if the runs-write itself fails we still
        # need to return a meaningful exit code.
        try:
            finished_at = datetime.now(tz=timezone.utc)
            # Build a JSON-safe args dict for param_hash; argparse Namespace
            # vars() may contain Path / datetime which runs.param_hash will
            # serialize with default=str.
            args_dict = {k: v for k, v in vars(args).items()}
            store.write_run(
                run_id=run_id,
                git_sha=git_sha(),
                data_hash=data_hash(df) if df is not None and len(df) > 0 else "",
                param_hash=param_hash(args_dict),
                seed=args.seed,
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

    if status == "ok":
        return 0
    if status == "partial":
        return 2
    return 1


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
        prog="seed_bars",
        description=(
            "Backfill RTH bars to DuckDB + Parquet through the configured "
            "DataSource. Idempotent; writes a runs row on every exit (audit "
            "chain). Exit codes: 0 ok, 1 failed, 2 partial."
        ),
    )
    p.add_argument(
        "--symbol",
        required=True,
        choices=["ES", "MES", "SPY"],
        help="Instrument symbol (Phase 1 set: ES / MES / SPY).",
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
        "--provider",
        choices=sorted(PROVIDERS),
        default=None,
        help="DataSource adapter. Default: Settings.default_provider.",
    )
    p.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Run seed for the audit row (FND-08; default 42).",
    )
    p.add_argument(
        "--duckdb-path",
        dest="duckdb_path",
        type=Path,
        default=None,
        help="Override Settings.duckdb_path (default: data/duckdb/trading.duckdb).",
    )
    return p


if __name__ == "__main__":
    parser = _build_parser()
    parsed_args = parser.parse_args()
    sys.exit(asyncio.run(main(parsed_args)))
