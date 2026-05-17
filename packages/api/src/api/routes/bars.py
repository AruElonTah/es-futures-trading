"""GET /bars route — D-07 cold-load.

Returns the most-recent ``limit`` bars for (symbol, tf) from DuckDB,
ordered ts_utc ASC (oldest to newest within the returned window).

Security:
    - T-03-04-01: Pydantic Literal validators on symbol and tf reject any
      non-whitelisted value with HTTP 422 before any DB access.
    - T-03-04-02: Parameterized ``?`` placeholders prevent SQL injection even
      on the (rejected) edge case where a bad actor bypasses Pydantic.
    - T-03-04-03: ``Query(ge=1, le=10_000)`` caps response size; 10 000 1m
      bars ≈ 26 days ≈ 3–5 MB JSON maximum.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query

from api.deps import get_store
from trading_core.logging import get_logger
from trading_core.storage.duckdb_store import DuckDBStore

router = APIRouter()
log = get_logger(__name__)

# Parameterized SQL — ORDER BY DESC + LIMIT to get the most recent N bars;
# reversed to ASC in Python before returning. See D-07 cold-load semantics.
_BARS_SQL = (
    "SELECT symbol, timeframe, ts_utc, open, high, low, close, volume, rollover_seam "
    "FROM bars "
    "WHERE symbol = ? AND timeframe = ? "
    "ORDER BY ts_utc DESC "
    "LIMIT ?"
)


@router.get("/bars")
def get_bars(
    symbol: Annotated[Literal["ES", "MES", "SPY"], Query()],
    tf: Annotated[Literal["1m", "5m", "15m"], Query()] = "1m",
    limit: Annotated[int, Query(ge=1, le=10_000)] = 390,
    store: Annotated[DuckDBStore, Depends(get_store)] = ...,  # type: ignore[assignment]
) -> list[dict]:
    """Return the most-recent ``limit`` bars for (symbol, tf).

    D-07 cold-load: the chart fetches this on mount; ``limit`` defaults to 390
    (one RTH 1m session). Bars are returned oldest-first (ts_utc ASC) so the
    chart renders left-to-right chronologically.

    Returns an empty list when no bars exist — HTTP 200 (empty is valid).
    """
    rows = store._conn.execute(_BARS_SQL, [symbol, tf, limit]).fetchall()
    # Reverse DESC → ASC for chronological chart display
    rows = list(reversed(rows))
    result: list[dict] = []
    for row in rows:
        # row columns: symbol, timeframe, ts_utc, open, high, low, close, volume, rollover_seam
        ts_utc = row[2]
        # DuckDB may return a datetime-like object or pandas Timestamp; normalise to ISO string
        if hasattr(ts_utc, "isoformat"):
            ts_str = ts_utc.isoformat()
        else:
            ts_str = str(ts_utc)
        result.append(
            {
                "ts_utc": ts_str,
                "open": float(row[3]),
                "high": float(row[4]),
                "low": float(row[5]),
                "close": float(row[6]),
                "volume": int(row[7]),
                "rollover_seam": bool(row[8]),
            }
        )
    log.info("bars.fetched", symbol=symbol, tf=tf, limit=limit, rowcount=len(result))
    return result
