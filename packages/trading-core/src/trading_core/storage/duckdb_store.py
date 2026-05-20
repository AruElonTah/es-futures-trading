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

import csv
import threading
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import duckdb
import pandas as pd


class _LockedConn:
    """Thread-safe proxy for a DuckDB connection.

    FastAPI runs synchronous route handlers in a thread-pool executor, so
    multiple requests can call _conn.execute() concurrently on the same
    Connection object. DuckDB connections are not thread-safe; concurrent
    execute() calls on a single Connection return corrupt or empty results.
    This wrapper serializes all execute/executemany calls with a Lock so the
    singleton DuckDBStore used by the FastAPI lifespan is safe under load.
    """

    def __init__(self, conn: duckdb.DuckDBPyConnection) -> None:
        self._conn = conn
        self._lock = threading.Lock()

    def execute(self, *args: Any, **kwargs: Any) -> Any:
        with self._lock:
            return self._conn.execute(*args, **kwargs)

    def executemany(self, *args: Any, **kwargs: Any) -> Any:
        with self._lock:
            return self._conn.executemany(*args, **kwargs)

    def close(self) -> None:
        self._conn.close()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)


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

# Phase 4: Optimization grid + walk-forward SQL constants (D-13).

WRITE_OPT_RUN_SQL = """
INSERT INTO opt_runs (run_id, strategy_id, adr_hash, param_grid_hash,
    is_window_months, oos_window_months, step_months, seed,
    fold_count, completed_combos, total_combos, status)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
"""

WRITE_OPT_RESULT_SQL = """
INSERT INTO opt_results (result_id, run_id, fold_idx, param_hash,
    opening_range_minutes, atr_stop_mult, r_target,
    is_sharpe, oos_sharpe, is_return, oos_return, edge_ratio,
    equity_curve_path, git_sha, data_hash, seed)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
"""

WRITE_HOLDOUT_BURN_SQL = """
INSERT INTO holdout_burns (burn_id, run_id, quarter)
VALUES (?, ?, ?);
"""

CHECK_HOLDOUT_QUOTA_SQL = """
SELECT COUNT(*) FROM holdout_burns WHERE quarter = ?;
"""

# Phase 5: Risk state, audit log, and engine state SQL (D-06/D-07/D-09/D-10/D-11).
# All three tables are append-only (uuid7 PKs; no upsert needed).

WRITE_RISK_STATE_SQL = """
INSERT INTO risk_state (
    id, ts_utc, date, session_id,
    equity_dollars, realized_pnl_dollars, open_exposure_dollars,
    hwm_static, floor_static,
    hwm_trailing_eod, floor_trailing_eod,
    hwm_trailing_intraday, floor_trailing_intraday
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
"""

WRITE_AUDIT_EVENT_SQL = """
INSERT INTO audit_log (event_id, ts_utc, topic, entity_id, reason_code, payload_json)
VALUES (?, ?, ?, ?, ?, ?);
"""

GET_LAST_RISK_STATE_SQL = """
SELECT * FROM risk_state WHERE date = ? ORDER BY ts_utc DESC LIMIT 1;
"""

WRITE_ENGINE_STATE_SQL = """
INSERT INTO engine_state (id, session_id, ts_utc, state)
VALUES (?, ?, now(), ?);
"""

GET_ENGINE_STATE_SQL = """
SELECT state FROM engine_state ORDER BY ts_utc DESC LIMIT 1;
"""

# Phase 6: TV overlay + alert SQL constants (TV-02, TV-07).
# All new DuckDBStore methods use parameterized ? binding — no f-string SQL
# construction — enforcing T-06-01-04 (no SQL injection via caller-supplied strings).

WRITE_TV_OVERLAY_SQL = """
INSERT INTO tv_overlays (overlay_id, strategy_id, signal_id, shape_kind, shape_id, trading_date)
VALUES (?, ?, ?, ?, ?, ?);
"""

WRITE_TV_ALERT_SQL = """
INSERT INTO tv_alerts (alert_id, strategy_id, tv_alert_id, condition)
VALUES (?, ?, ?, ?);
"""

MARK_TV_ALERT_DELETED_SQL = """
UPDATE tv_alerts SET deleted_at = now() WHERE alert_id = ?;
"""

COUNT_ACTIVE_OVERLAYS_SQL = """
SELECT COUNT(*) FROM tv_overlays WHERE deleted_at IS NULL;
"""

GET_TV_ALERT_TV_ID_SQL = """
SELECT tv_alert_id FROM tv_alerts WHERE alert_id = ?;
"""

LIST_OVERLAYS_OLDER_THAN_SQL = """
SELECT overlay_id, shape_id FROM tv_overlays WHERE deleted_at IS NULL AND trading_date < ?;
"""

# Audit CSV header — matches audit_log column order.
_AUDIT_CSV_HEADER = ["event_id", "ts_utc", "topic", "entity_id", "reason_code", "payload_json"]

# America/New_York timezone for trading-date derivation.
_ET = ZoneInfo("America/New_York")


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
        self._conn: _LockedConn = _LockedConn(duckdb.connect(str(db_path)))

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

    # ---- optimization run writers (Phase 4) --------------------------------

    def write_opt_run(
        self,
        *,
        run_id: str,
        strategy_id: str,
        adr_hash: str,
        param_grid_hash: str,
        is_window_months: int,
        oos_window_months: int,
        step_months: int,
        seed: int,
        fold_count: int = 0,
        completed_combos: int = 0,
        total_combos: int = 0,
        status: str,
    ) -> None:
        """Persist a single ``opt_runs`` row.

        Plain INSERT — run_id (uuid7) is unique per optimization run;
        no upsert needed.
        """
        self._conn.execute(
            WRITE_OPT_RUN_SQL,
            [
                run_id,
                strategy_id,
                adr_hash,
                param_grid_hash,
                int(is_window_months),
                int(oos_window_months),
                int(step_months),
                int(seed),
                int(fold_count),
                int(completed_combos),
                int(total_combos),
                status,
            ],
        )

    def write_opt_results(self, rows: list[dict]) -> int:
        """Persist a batch of ``opt_results`` rows.

        Args:
            rows: List of dicts with D-13 keys. ``is_sharpe``, ``oos_sharpe``,
                ``is_return``, ``oos_return``, ``edge_ratio``,
                ``equity_curve_path`` are nullable.

        Returns:
            Number of rows inserted. Zero when ``rows`` is empty.
        """
        if not rows:
            return 0
        tuples: list[tuple[Any, ...]] = [
            (
                r["result_id"],
                r["run_id"],
                int(r["fold_idx"]),
                r["param_hash"],
                int(r["opening_range_minutes"]),
                float(r["atr_stop_mult"]),
                float(r["r_target"]),
                float(r["is_sharpe"]) if r.get("is_sharpe") is not None else None,
                float(r["oos_sharpe"]) if r.get("oos_sharpe") is not None else None,
                float(r["is_return"]) if r.get("is_return") is not None else None,
                float(r["oos_return"]) if r.get("oos_return") is not None else None,
                float(r["edge_ratio"]) if r.get("edge_ratio") is not None else None,
                r.get("equity_curve_path"),
                r["git_sha"],
                r["data_hash"],
                int(r["seed"]),
            )
            for r in rows
        ]
        self._conn.executemany(WRITE_OPT_RESULT_SQL, tuples)
        return len(rows)

    def write_holdout_burn(
        self, *, burn_id: str, run_id: str, quarter: str
    ) -> None:
        """Persist a single ``holdout_burns`` row.

        The ``quarter`` string is computed in Python by the caller (e.g.,
        ``current_quarter_str()``) — it is never derived from user input,
        satisfying T-04-01-02 (tamper-resistant quarter string).
        """
        self._conn.execute(WRITE_HOLDOUT_BURN_SQL, [burn_id, run_id, quarter])

    def check_holdout_quota(self, quarter: str) -> bool:
        """Return True if a holdout burn is ALLOWED for ``quarter``.

        OPT-08: at most 3 burns per calendar quarter. Returns False when
        COUNT(*) >= 3 (the 4th burn is refused).
        """
        count: int = self._conn.execute(
            CHECK_HOLDOUT_QUOTA_SQL, [quarter]
        ).fetchone()[0]
        return count < 3

    def read_opt_results(self, run_id: str) -> list[dict]:
        """Return all ``opt_results`` rows for ``run_id``, sorted by OOS Sharpe DESC.

        Returns:
            List of dicts keyed by column name, ordered by
            ``oos_sharpe DESC NULLS LAST``.
        """
        cursor = self._conn.execute(
            "SELECT result_id, run_id, fold_idx, param_hash, "
            "opening_range_minutes, atr_stop_mult, r_target, "
            "is_sharpe, oos_sharpe, is_return, oos_return, edge_ratio, "
            "equity_curve_path, git_sha, data_hash, seed, created_at "
            "FROM opt_results WHERE run_id = ? "
            "ORDER BY oos_sharpe DESC NULLS LAST",
            [run_id],
        )
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    # ---- Phase 5: risk state, audit log, engine state -------------------

    def write_risk_state(self, row: dict) -> None:
        """Persist one append-only row to ``risk_state``.

        Args:
            row: Dict whose keys match the 13 ``risk_state`` column names
                (id, ts_utc, date, session_id, equity_dollars,
                realized_pnl_dollars, open_exposure_dollars, hwm_static,
                floor_static, hwm_trailing_eod, floor_trailing_eod,
                hwm_trailing_intraday, floor_trailing_intraday).

                Decimal values are converted to ``str`` to preserve precision
                (DuckDB 1.x does not accept Python Decimal objects directly).
        """
        self._conn.execute(
            WRITE_RISK_STATE_SQL,
            [
                str(row["id"]),
                row["ts_utc"],
                row["date"],
                str(row["session_id"]),
                str(row["equity_dollars"]),
                str(row["realized_pnl_dollars"]),
                str(row["open_exposure_dollars"]),
                str(row["hwm_static"]),
                str(row["floor_static"]),
                str(row["hwm_trailing_eod"]),
                str(row["floor_trailing_eod"]),
                str(row["hwm_trailing_intraday"]),
                str(row["floor_trailing_intraday"]),
            ],
        )

    def write_audit_event(
        self,
        *,
        event_id: str,
        ts_utc: datetime,
        topic: str,
        entity_id: str,
        reason_code: str,
        payload_json: str,
    ) -> None:
        """Persist one audit event to DuckDB + daily CSV mirror (SP-03 / D-09).

        Both writes are synchronous — DuckDB INSERT first, then CSV append +
        explicit flush(). The method blocks until both writes complete so that
        a ``kill -9`` immediately after the call leaves a committed record in
        at least one of the two stores.

        The CSV is co-located with the DuckDB file under
        ``{db_dir}/logs/audit/{YYYY-MM-DD}.csv`` (America/New_York date).
        """
        # 1. DuckDB INSERT (committed immediately; no buffering by design).
        self._conn.execute(
            WRITE_AUDIT_EVENT_SQL,
            [event_id, ts_utc, topic, entity_id, reason_code, payload_json],
        )

        # 2. CSV append — derive ET date for the filename.
        et_date = ts_utc.astimezone(_ET).date()
        csv_dir = Path(self._db_path) / ".." / "logs" / "audit"
        # Resolve relative components so mkdir works correctly.
        csv_dir = csv_dir.resolve()
        csv_dir.mkdir(parents=True, exist_ok=True)
        csv_path = csv_dir / f"{et_date}.csv"

        write_header = not csv_path.exists() or csv_path.stat().st_size == 0
        with csv_path.open("a", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            if write_header:
                writer.writerow(_AUDIT_CSV_HEADER)
            writer.writerow(
                [event_id, ts_utc.isoformat(), topic, entity_id, reason_code, payload_json]
            )
            fh.flush()

    def get_last_risk_state(self, date_str: str) -> dict | None:
        """Return the most-recent ``risk_state`` row for ``date_str``, or None.

        Args:
            date_str: Trading date as ``'YYYY-MM-DD'`` string (ET calendar).

        Returns:
            Dict keyed by column name, or None if no row exists for that date.
        """
        cursor = self._conn.execute(GET_LAST_RISK_STATE_SQL, [date_str])
        row = cursor.fetchone()
        if row is None:
            return None
        columns = [desc[0] for desc in cursor.description]
        return dict(zip(columns, row))

    def write_engine_state(self, session_id: str, state: str) -> None:
        """Append one row to ``engine_state`` (D-10/D-11).

        Args:
            session_id: Current session's run_id (UUID7).
            state: One of ``'running'``, ``'killed'``, ``'paused'``,
                ``'flatten_requested'``. Not validated here — the caller
                (FullRiskManager / API route) is responsible for passing a
                valid literal.
        """
        from trading_core.storage.runs import new_run_id  # lazy import; avoids cycle

        self._conn.execute(
            WRITE_ENGINE_STATE_SQL,
            [new_run_id(), session_id, state],
        )

    def get_engine_state(self) -> str:
        """Return the most-recent ``engine_state.state`` value, or ``'running'``.

        Returns ``'running'`` when the table is empty (safe startup default —
        the engine has never been killed, so it is implicitly running).
        """
        row = self._conn.execute(GET_ENGINE_STATE_SQL).fetchone()
        if row is None:
            return "running"
        return str(row[0])

    # ---- Phase 6: TV overlay + alert writers (TV-02, TV-07) ----------------

    def write_tv_overlay(
        self,
        *,
        overlay_id: str,
        strategy_id: str,
        signal_id: str,
        shape_kind: str,
        shape_id: str,
        trading_date: date,
    ) -> None:
        """Persist one TV overlay row to ``tv_overlays``.

        All parameters are keyword-only. Uses parameterized ``?`` binding
        (T-06-01-04 — no f-string SQL construction; all caller-supplied strings
        go through DuckDB parameter binding).
        """
        self._conn.execute(
            WRITE_TV_OVERLAY_SQL,
            [overlay_id, strategy_id, signal_id, shape_kind, shape_id, trading_date],
        )

    def write_tv_alert(
        self,
        *,
        alert_id: str,
        strategy_id: str,
        tv_alert_id: str,
        condition: str,
    ) -> None:
        """Persist one TV alert row to ``tv_alerts``."""
        self._conn.execute(
            WRITE_TV_ALERT_SQL,
            [alert_id, strategy_id, tv_alert_id, condition],
        )

    def mark_tv_alert_deleted(self, *, alert_id: str) -> None:
        """Set ``deleted_at = now()`` on the given ``tv_alerts`` row."""
        self._conn.execute(MARK_TV_ALERT_DELETED_SQL, [alert_id])

    def mark_tv_overlay_deleted(self, *, overlay_id: str) -> None:
        """Set ``deleted_at = now()`` on the given ``tv_overlays`` row.

        Used by Plan 04's nightly cleanup task to mark expired overlay rows
        without deleting them (preserves forensic history).
        """
        self._conn.execute(
            "UPDATE tv_overlays SET deleted_at = now() WHERE overlay_id = ?;",
            [overlay_id],
        )

    def count_active_overlays(self) -> int:
        """Return the count of tv_overlays rows where ``deleted_at IS NULL``."""
        row = self._conn.execute(COUNT_ACTIVE_OVERLAYS_SQL).fetchone()
        return int(row[0]) if row is not None else 0

    def get_tv_alert_tv_id(self, alert_id: str) -> str | None:
        """Return the ``tv_alert_id`` for the given ``alert_id``, or None.

        Returns the value even if ``deleted_at`` is set — the caller reads
        ``deleted_at`` separately if needed to distinguish active vs deleted.
        """
        row = self._conn.execute(GET_TV_ALERT_TV_ID_SQL, [alert_id]).fetchone()
        return str(row[0]) if row is not None else None

    def is_orb_box_drawn(self, session_date: date, strategy_id: str) -> bool:
        """Return True if an orb_box overlay already exists for this session + strategy.

        Checks tv_overlays for a non-deleted row with shape_kind='orb_box',
        trading_date matching session_date, and strategy_id matching the caller.
        Used by TVBridge._draw_orb_box_if_new to avoid duplicate ORB rectangles.
        """
        row = self._conn.execute(
            "SELECT 1 FROM tv_overlays WHERE shape_kind = 'orb_box' "
            "AND trading_date = ? AND strategy_id = ? AND deleted_at IS NULL",
            [session_date, strategy_id],
        ).fetchone()
        return row is not None

    def list_overlays_older_than(self, trading_date: date) -> list[tuple[str, str]]:
        """Return (overlay_id, shape_id) pairs for active overlays older than ``trading_date``.

        Used by Plan 04's nightly cleanup to enumerate shapes that need to
        be removed from the TV chart (deleted_at IS NULL AND trading_date < ?).
        """
        rows = self._conn.execute(
            LIST_OVERLAYS_OLDER_THAN_SQL, [trading_date]
        ).fetchall()
        return [(str(r[0]), str(r[1])) for r in rows]

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
