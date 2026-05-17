"""DuckDB connection + schema loader + ON CONFLICT upserts + Parquet partitioning.

Implements MD-04 (DuckDB + Hive-partitioned Parquet idempotent upsert).

Why ON CONFLICT (symbol, timeframe, ts_utc) DO UPDATE SET col = EXCLUDED.col?
    DuckDB issues #14133 and #20743 documented that the upsert shortcut form
    (which CONTEXT.md mentions verbatim) silently fails to update existing
    rows in some transaction/file scenarios on PK tables. The semantically
    equivalent and footgun-free form is the explicit ON CONFLICT clause —
    this module uses it exclusively. See 01-RESEARCH.md §Pitfall 2.

Single-writer convention:
    Only the FastAPI process (Phase 3) and the ``seed_bars.py`` CLI (Plan 05)
    instantiate ``DuckDBStore``. There is no code-level enforcement — the
    constraint is documented here and in ``storage/__init__.py``.

The class is usable as a context manager so callers can write::

    with DuckDBStore(path) as store:
        store.ensure_schema()
        store.upsert_bars(df, provider="twelve_data")
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

# Schema file lives alongside this module. Read verbatim by ensure_schema.
_SCHEMA_PATH = Path(__file__).parent / "schema.sql"

# Upsert SQL — Pitfall 2 workaround. Explicit ON CONFLICT clause used in
# place of the documented-equivalent upsert shortcut form. See 01-RESEARCH.md
# Pattern 6 lines 754-767.
# Note: DuckDB 1.x's binder treats bare ``CURRENT_TIMESTAMP`` inside the
# DO UPDATE SET right-hand side as a column reference (not the SQL keyword),
# producing ``Binder Error: Table "bars" does not have a column named
# "CURRENT_TIMESTAMP"``. We use the function form ``now()`` instead — both
# return the current UTC timestamp on a TIMESTAMPTZ column, but ``now()``
# is unambiguous to the binder.
UPSERT_BAR_SQL = """
INSERT INTO bars (symbol, timeframe, ts_utc, open, high, low, close, volume,
                  rollover_seam, provider)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (symbol, timeframe, ts_utc) DO UPDATE SET
    open = EXCLUDED.open,
    high = EXCLUDED.high,
    low = EXCLUDED.low,
    close = EXCLUDED.close,
    volume = EXCLUDED.volume,
    rollover_seam = EXCLUDED.rollover_seam,
    provider = EXCLUDED.provider,
    ingested_at = now();
"""

UPSERT_GAP_SQL = """
INSERT INTO bar_gaps (symbol, timeframe, ts_utc, provider, run_id)
VALUES (?, ?, ?, ?, ?)
ON CONFLICT (symbol, timeframe, ts_utc) DO UPDATE SET
    provider = EXCLUDED.provider,
    run_id = EXCLUDED.run_id,
    detected_at = now();
"""

WRITE_RUN_SQL = """
INSERT INTO runs (run_id, git_sha, data_hash, param_hash, seed, adr_hash,
                  started_at, finished_at, status, notes)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
"""

# D-01: Backtest metrics persistence (Phase 3 Plan 01).
# All 20 columns; no ON CONFLICT — run_id (uuid7) is unique per run.
WRITE_BACKTEST_SQL = """
INSERT INTO backtests (run_id, strategy_id, symbol, timeframe, from_ts, to_ts,
    param_hash, equity_curve_path, total_return, cagr, sharpe, sortino, calmar,
    max_dd, max_dd_duration_bars, win_rate, expectancy, profit_factor,
    trade_count, avg_hold_bars)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
"""

# D-02: Per-trade attribution persistence (Phase 3 Plan 01).
# 15 base D-02 fields + stop_price + target_price (nullable).
# No ON CONFLICT — trade_id (uuid7) is unique per trade.
WRITE_TRADE_SQL = """
INSERT INTO trades (trade_id, run_id, signal_id, strategy_id, side, entry_price,
    exit_price, exit_reason, entry_ts_utc, exit_ts_utc, pnl, size,
    slippage_ticks, mae, mfe, stop_price, target_price)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
"""


class DuckDBStore:
    """Owns a DuckDB connection and the bar/run persistence surface.

    Inputs use stdlib datetime where possible (matching the Bar model
    convention) and pandas DataFrames at the bulk-insert boundary.
    """

    def __init__(self, db_path: Path) -> None:
        if not isinstance(db_path, Path):
            db_path = Path(db_path)
        self._db_path = db_path
        # Validate the parent directory eagerly. DuckDB itself will tolerate a
        # missing parent (it just fails at file open), but the caller deserves a
        # crisp signal *before* schema-loading time.
        if db_path.parent != Path() and not db_path.parent.exists():
            raise FileNotFoundError(
                f"DuckDBStore parent directory does not exist: {db_path.parent}"
            )
        self._conn: duckdb.DuckDBPyConnection = duckdb.connect(str(db_path))

    # ---- schema -----------------------------------------------------------

    def ensure_schema(self) -> None:
        """Read schema.sql verbatim and execute it.

        Idempotent — every CREATE statement is ``IF NOT EXISTS``.
        """
        sql = _SCHEMA_PATH.read_text(encoding="utf-8")
        self._conn.execute(sql)

    # ---- bars upsert ------------------------------------------------------

    def upsert_bars(self, df: pd.DataFrame, *, provider: str) -> int:
        """Idempotent INSERT-or-UPDATE into ``bars``.

        Args:
            df: DataFrame with columns (symbol, timeframe, ts_utc, open, high,
                low, close, volume, rollover_seam). The ``provider`` column is
                injected from the kwarg — callers should NOT pre-populate it.
            provider: provider name ("twelve_data" | "tradingview_mcp").

        Returns:
            Number of rows touched (the input row count).
        """
        if df is None or len(df) == 0:
            return 0
        rows: list[tuple[Any, ...]] = []
        for r in df.itertuples(index=False):
            d = r._asdict()
            ts = d["ts_utc"]
            if isinstance(ts, pd.Timestamp):
                ts = ts.to_pydatetime()
            rows.append(
                (
                    d["symbol"],
                    d["timeframe"],
                    ts,
                    float(d["open"]),
                    float(d["high"]),
                    float(d["low"]),
                    float(d["close"]),
                    int(d["volume"]),
                    bool(d.get("rollover_seam", False)),
                    provider,
                )
            )
        self._conn.executemany(UPSERT_BAR_SQL, rows)
        return len(rows)

    # ---- gaps upsert ------------------------------------------------------

    def upsert_gaps(
        self, gaps_df: pd.DataFrame, *, provider: str, run_id: str | None = None
    ) -> int:
        """Idempotent INSERT-or-UPDATE into ``bar_gaps``.

        Shape: ``[symbol, timeframe, ts_utc]`` — produced by
        :py:meth:`trading_core.calendars.rth.RthFilter.find_gaps_as_dataframe`.
        """
        if gaps_df is None or len(gaps_df) == 0:
            return 0
        rows: list[tuple[Any, ...]] = []
        for r in gaps_df.itertuples(index=False):
            d = r._asdict()
            ts = d["ts_utc"]
            if isinstance(ts, pd.Timestamp):
                ts = ts.to_pydatetime()
            rows.append(
                (
                    d["symbol"],
                    d["timeframe"],
                    ts,
                    provider,
                    run_id,
                )
            )
        self._conn.executemany(UPSERT_GAP_SQL, rows)
        return len(rows)

    # ---- runs row writer --------------------------------------------------

    def write_run(
        self,
        *,
        run_id: str,
        git_sha: str,
        data_hash: str,
        param_hash: str,
        seed: int,
        adr_hash: str,
        started_at: datetime,
        finished_at: datetime | None,
        status: str,
        notes: str = "",
    ) -> None:
        """Persist a single ``runs`` row.

        Run IDs are unique per CLI invocation (uuid7) — no upsert needed.
        """
        self._conn.execute(
            WRITE_RUN_SQL,
            [
                run_id,
                git_sha,
                data_hash,
                param_hash,
                int(seed),
                adr_hash,
                started_at,
                finished_at,
                status,
                notes,
            ],
        )

    # ---- backtest + trades writers ----------------------------------------

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
        """Persist a single ``backtests`` row.

        All keyword-only. Plain INSERT — run_id (uuid7) is unique per run;
        no upsert needed. Parameterized queries enforce T-03-01-01 (no SQL
        injection via caller-supplied strings).
        """
        self._conn.execute(
            WRITE_BACKTEST_SQL,
            [
                run_id,
                strategy_id,
                symbol,
                timeframe,
                from_ts,
                to_ts,
                param_hash,
                equity_curve_path,
                float(total_return),
                float(cagr),
                float(sharpe),
                float(sortino),
                float(calmar),
                float(max_dd),
                int(max_dd_duration_bars),
                float(win_rate),
                float(expectancy),
                float(profit_factor),
                int(trade_count),
                float(avg_hold_bars),
            ],
        )

    def write_trades(self, trades: list[dict]) -> int:
        """Persist a list of trade rows to the ``trades`` table.

        Args:
            trades: List of dicts with D-02 keys. ``stop_price`` and
                ``target_price`` are optional (use ``trade.get(...)`` for
                NULL-safe handling — non-ORB strategies omit them).

        Returns:
            Number of rows inserted. Zero when ``trades`` is empty.
        """
        if not trades:
            return 0
        rows: list[tuple[Any, ...]] = [
            (
                t["trade_id"],
                t["run_id"],
                t["signal_id"],
                t["strategy_id"],
                t["side"],
                float(t["entry_price"]),
                float(t["exit_price"]),
                t["exit_reason"],
                t["entry_ts_utc"],
                t["exit_ts_utc"],
                float(t["pnl"]),
                int(t["size"]),
                int(t["slippage_ticks"]),
                float(t["mae"]),
                float(t["mfe"]),
                float(t["stop_price"]) if t.get("stop_price") is not None else None,
                float(t["target_price"]) if t.get("target_price") is not None else None,
            )
            for t in trades
        ]
        self._conn.executemany(WRITE_TRADE_SQL, rows)
        return len(rows)

    # ---- Parquet partition write -----------------------------------------

    def write_parquet_partition(
        self,
        *,
        symbol: str,
        start_utc: datetime,
        end_utc: datetime,
        root: Path | str = Path("data/parquet/bars"),
    ) -> None:
        """Snapshot a (symbol, [start_utc, end_utc)) slice of ``bars`` to Parquet.

        Layout: Hive-partitioned by (symbol, year(ts_utc), month(ts_utc)).
        Uses ``OVERWRITE_OR_IGNORE`` (RESEARCH.md Pattern 6 line 779) so
        re-running deletes existing partition directories before writing —
        idempotent on the filesystem.
        """
        root = Path(root) if not isinstance(root, Path) else root
        root.parent.mkdir(parents=True, exist_ok=True)
        # NOTE 1: DuckDB cannot bind the TO target nor the PARTITION_BY
        # expressions via parameter substitution — ``?`` placeholders inside
        # the OPTIONS clause are not supported. The output directory path is
        # constructed from local code paths (never user input), so string
        # interpolation is safe.  ``root`` is also single-quote-escaped
        # defensively in case a future caller passes a path with an apostrophe.
        #
        # NOTE 2: PARTITION_BY only accepts column names (not function calls
        # like ``year(ts_utc)``) in DuckDB 1.x — the binder reports the
        # ``year(STRING_LITERAL)`` error when one is supplied. We project
        # synthetic ``year`` / ``month`` columns inside the SELECT instead.
        # On disk this produces the desired Hive layout symbol=/year=/month=.
        #
        # Forward-slash the target so DuckDB's path parser accepts it on
        # Windows (back-slashes are treated as escape characters by the SQL
        # tokenizer).
        target = str(root).replace("\\", "/").replace("'", "''")
        self._conn.execute(
            f"""
            COPY (
                SELECT *, year(ts_utc) AS year, month(ts_utc) AS month
                FROM bars
                WHERE symbol = ? AND ts_utc >= ? AND ts_utc < ?
            )
            TO '{target}'
            (FORMAT PARQUET,
             PARTITION_BY (symbol, year, month),
             OVERWRITE_OR_IGNORE)
            """,
            [symbol, start_utc, end_utc],
        )

    # ---- context manager + close -----------------------------------------

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass

    def __enter__(self) -> DuckDBStore:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
