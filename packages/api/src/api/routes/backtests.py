"""GET /backtests route — UI-01 minimal surface.

Returns all rows from the ``backtests`` table ordered ``created_at DESC``
(most-recent run first). D-01 persistence layer: BacktestEngine.run() writes
rows via DuckDBStore.write_backtest(); this endpoint exposes them to the
dashboard equity-curve pane.

No query parameters in Phase 3 — Phase 7 may add symbol/strategy filters.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from api.deps import get_store
from trading_core.logging import get_logger
from trading_core.storage.duckdb_store import DuckDBStore

router = APIRouter()
log = get_logger(__name__)

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
