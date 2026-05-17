"""GET /backtests route — UI-01 minimal surface.

Returns all rows from the ``backtests`` table ordered ``created_at DESC``
(most-recent run first). D-01 persistence layer: BacktestEngine.run() writes
rows via DuckDBStore.write_backtest(); this endpoint exposes them to the
dashboard equity-curve pane.

No query parameters in Phase 3 — Phase 7 may add symbol/strategy filters.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from api.deps import get_store
from trading_core.logging import get_logger
from trading_core.storage.duckdb_store import DuckDBStore

router = APIRouter()
log = get_logger(__name__)

# Path-traversal guard for the equity endpoint (T-03-05-01).
# Five parents up from packages/api/src/api/routes/backtests.py reaches the repo root:
# routes/ -> api/ -> src/ -> api(pkg)/ -> packages/ -> repo root
_EQUITY_ROOT: Path = (
    Path(__file__).resolve().parents[5] / "data" / "parquet" / "equity"
).resolve()
assert _EQUITY_ROOT.name == "equity", (
    f"_EQUITY_ROOT path math error — expected 'equity', got '{_EQUITY_ROOT.name}'"
)

_BACKTESTS_SQL = (
    "SELECT run_id, strategy_id, symbol, timeframe, from_ts, to_ts, param_hash, "
    "equity_curve_path, total_return, cagr, sharpe, sortino, calmar, max_dd, "
    "max_dd_duration_bars, win_rate, expectancy, profit_factor, trade_count, "
    "avg_hold_bars, created_at "
    "FROM backtests "
    "ORDER BY created_at DESC"
)

# Column names in SELECT order — used to build the response dict
_COLUMNS = [
    "run_id",
    "strategy_id",
    "symbol",
    "timeframe",
    "from_ts",
    "to_ts",
    "param_hash",
    "equity_curve_path",
    "total_return",
    "cagr",
    "sharpe",
    "sortino",
    "calmar",
    "max_dd",
    "max_dd_duration_bars",
    "win_rate",
    "expectancy",
    "profit_factor",
    "trade_count",
    "avg_hold_bars",
    "created_at",
]


@router.get("/backtests")
def get_backtests(
    store: Annotated[DuckDBStore, Depends(get_store)] = ...,  # type: ignore[assignment]
) -> list[dict]:
    """Return all backtest run summaries ordered most-recent first.

    Returns an empty list when no runs exist — HTTP 200 (empty is valid).
    ``None`` values for nullable metrics (e.g., sharpe when trade_count==0)
    serialise as JSON ``null`` via FastAPI's default json encoder.
    """
    rows = store._conn.execute(_BACKTESTS_SQL).fetchall()
    result: list[dict] = []
    for row in rows:
        record: dict = {}
        for col, val in zip(_COLUMNS, row):
            if col in ("from_ts", "to_ts", "created_at"):
                # Normalise TIMESTAMPTZ to ISO 8601 string
                if val is not None and hasattr(val, "isoformat"):
                    record[col] = val.isoformat()
                elif val is not None:
                    record[col] = str(val)
                else:
                    record[col] = None
            elif col in ("total_return", "cagr", "sharpe", "sortino", "calmar",
                         "max_dd", "win_rate", "expectancy", "profit_factor",
                         "avg_hold_bars"):
                # Float or None (nullable metrics)
                record[col] = float(val) if val is not None else None
            elif col in ("max_dd_duration_bars", "trade_count"):
                # Int or None
                record[col] = int(val) if val is not None else None
            else:
                record[col] = val
        result.append(record)
    log.info("backtests.listed", rowcount=len(result))
    return result


@router.get("/backtests/{run_id}/equity")
def get_backtest_equity(
    run_id: str,
    store: Annotated[DuckDBStore, Depends(get_store)] = ...,  # type: ignore[assignment]
) -> list[dict]:
    """Return the equity curve for a backtest run as JSON (T-03-05-01).

    Reads the Parquet file pointed to by ``equity_curve_path`` in the
    ``backtests`` row and returns ``[{ts_utc, equity, drawdown}, ...]``
    ordered by ts_utc ASC.

    Error codes:
    - 404 ``backtest not found`` — run_id not in ``backtests``.
    - 404 ``equity curve not found`` — DB row exists but Parquet file is gone.
    - 403 ``forbidden equity path`` — equity_curve_path escapes _EQUITY_ROOT
      (path traversal guard, T-03-05-01).
    """
    # Step 1: look up the equity_curve_path for this run_id
    row = store._conn.execute(
        "SELECT equity_curve_path FROM backtests WHERE run_id = ?",
        [run_id],
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="backtest not found")

    equity_curve_path: str = row[0]

    # Step 2: resolve path + path-traversal guard (T-03-05-01)
    # equity_curve_path may be absolute (from tests) or relative (from CLI).
    # Try to resolve it; if relative, it is relative to the repo root (4 parents up).
    candidate = Path(equity_curve_path)
    if candidate.is_absolute():
        abs_path = candidate.resolve()
    else:
        _repo_root = Path(__file__).resolve().parents[5]
        abs_path = (_repo_root / equity_curve_path).resolve()

    try:
        abs_path.relative_to(_EQUITY_ROOT)
    except ValueError:
        log.warning(
            "equity.path_traversal_blocked",
            run_id=run_id,
            equity_curve_path=equity_curve_path,
        )
        raise HTTPException(status_code=403, detail="forbidden equity path")

    # Step 3: check file existence
    if not abs_path.exists():
        raise HTTPException(status_code=404, detail="equity curve not found")

    # Step 4: read via DuckDB's native Parquet reader
    # Column aliases: equity_$ → equity, drawdown_$ → drawdown
    # Use parameterized $1 binding to prevent SQL injection via path (CR-003).
    parquet_path_str = str(abs_path).replace("\\", "/")
    equity_rows = store._conn.execute(
        'SELECT ts_utc, "equity_$" AS equity, "drawdown_$" AS drawdown '
        "FROM read_parquet($1) ORDER BY ts_utc ASC",
        [parquet_path_str],
    ).fetchall()

    result: list[dict] = []
    for eq_row in equity_rows:
        ts_utc_val, equity_val, drawdown_val = eq_row
        if ts_utc_val is not None and hasattr(ts_utc_val, "isoformat"):
            ts_str = ts_utc_val.isoformat()
        else:
            ts_str = str(ts_utc_val) if ts_utc_val is not None else None
        result.append({
            "ts_utc": ts_str,
            "equity": float(equity_val) if equity_val is not None else None,
            "drawdown": float(drawdown_val) if drawdown_val is not None else None,
        })

    log.info("equity.served", run_id=run_id, rowcount=len(result))
    return result


# Column names for trades query in SELECT order
_TRADES_COLUMNS = [
    "trade_id",
    "run_id",
    "signal_id",
    "strategy_id",
    "side",
    "entry_price",
    "exit_price",
    "exit_reason",
    "entry_ts_utc",
    "exit_ts_utc",
    "pnl",
    "size",
    "slippage_ticks",
    "mae",
    "mfe",
    "stop_price",
    "target_price",
]

_TRADES_SQL = (
    "SELECT trade_id, run_id, signal_id, strategy_id, side, entry_price, "
    "exit_price, exit_reason, entry_ts_utc, exit_ts_utc, pnl, size, "
    "slippage_ticks, mae, mfe, stop_price, target_price "
    "FROM trades WHERE run_id = ? ORDER BY entry_ts_utc ASC"
)


@router.get("/backtests/{run_id}/trades")
def get_backtest_trades(
    run_id: str,
    store: Annotated[DuckDBStore, Depends(get_store)] = ...,  # type: ignore[assignment]
) -> list[dict]:
    """Return per-trade rows for a backtest run ordered by entry_ts_utc ASC.

    Fields: trade_id, run_id, signal_id, strategy_id, side, entry_price,
    exit_price, exit_reason, entry_ts_utc, exit_ts_utc, pnl, size,
    slippage_ticks, mae, mfe, stop_price (nullable), target_price (nullable).

    Error codes:
    - 404 ``backtest not found`` — run_id not in ``backtests``.
    """
    # Check run exists
    count_row = store._conn.execute(
        "SELECT COUNT(*) FROM backtests WHERE run_id = ?",
        [run_id],
    ).fetchone()
    if count_row is None or count_row[0] == 0:
        raise HTTPException(status_code=404, detail="backtest not found")

    rows = store._conn.execute(_TRADES_SQL, [run_id]).fetchall()
    result: list[dict] = []
    for row in rows:
        record: dict = {}
        for col, val in zip(_TRADES_COLUMNS, row):
            if col in ("entry_ts_utc", "exit_ts_utc"):
                if val is not None and hasattr(val, "isoformat"):
                    record[col] = val.isoformat()
                elif val is not None:
                    record[col] = str(val)
                else:
                    record[col] = None
            elif col in ("entry_price", "exit_price", "pnl", "mae", "mfe"):
                record[col] = float(val) if val is not None else None
            elif col in ("stop_price", "target_price"):
                # Nullable — may be None for strategies that don't set stop/target
                record[col] = float(val) if val is not None else None
            elif col in ("size", "slippage_ticks"):
                record[col] = int(val) if val is not None else None
            else:
                record[col] = val
        result.append(record)

    log.info("trades.listed", run_id=run_id, rowcount=len(result))
    return result
