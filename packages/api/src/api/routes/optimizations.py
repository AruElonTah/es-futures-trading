"""GET /optimizations routes — Phase 4 Plan 03.

Endpoints:
  GET /optimizations                                        — list opt_runs ordered by created_at DESC
  GET /optimizations/{run_id}                               — single opt_run row; 404 if not found
  GET /optimizations/{run_id}/results                       — opt_results for run_id, sorted oos_sharpe DESC
  GET /optimizations/{run_id}/results/{result_id}/equity    — equity curve for one result row
  GET /optimizations/{run_id}/heatmap                       — 2D grid {x, y, z} for Plotly heatmap

Security (T-04-03-01):
  Heatmap axis params are validated against ALLOWED_AXES whitelist before any SQL
  construction. Both axis_x and axis_y must be in the whitelist; 422 is returned
  otherwise. Column names from the whitelist are safe to interpolate into SQL only
  AFTER this validation gate.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from api.deps import get_store
from trading_core.logging import get_logger
from trading_core.storage.duckdb_store import DuckDBStore

router = APIRouter()
log = get_logger(__name__)

# Path-traversal guard for the opt equity endpoint.
# Walk up to the outermost pyproject.toml (repo root), skipping inner package roots.
def _find_repo_root(start: Path) -> Path:
    found: Path | None = None
    for candidate in [start, *start.parents]:
        if (candidate / "pyproject.toml").exists():
            found = candidate
    if found is None:
        raise RuntimeError(f"Could not locate repo root from {start}")
    return found

_OPT_EQUITY_ROOT: Path = (
    _find_repo_root(Path(__file__).resolve()) / "data" / "parquet" / "opt"
).resolve()

# T-04-03-01: Axis whitelist — only these columns may appear in the heatmap GROUP BY.
# Column names are safe to interpolate into SQL after validation against this set.
ALLOWED_AXES: frozenset[str] = frozenset(
    {"opening_range_minutes", "atr_stop_mult", "r_target"}
)

# Columns returned from opt_runs in the list/single-run endpoints
_OPT_RUNS_COLUMNS = [
    "run_id",
    "strategy_id",
    "status",
    "total_combos",
    "completed_combos",
    "fold_count",
    "created_at",
]

_OPT_RUNS_SQL = (
    "SELECT run_id, strategy_id, status, total_combos, completed_combos, "
    "fold_count, created_at "
    "FROM opt_runs "
    "ORDER BY created_at DESC"
)

_OPT_RUN_BY_ID_SQL = (
    "SELECT run_id, strategy_id, status, total_combos, completed_combos, "
    "fold_count, created_at "
    "FROM opt_runs "
    "WHERE run_id = ?"
)

# Columns returned from opt_results in the /results endpoint
_OPT_RESULTS_COLUMNS = [
    "result_id",
    "run_id",
    "fold_idx",
    "param_hash",
    "opening_range_minutes",
    "atr_stop_mult",
    "r_target",
    "is_sharpe",
    "oos_sharpe",
    "is_return",
    "oos_return",
    "edge_ratio",
    "equity_curve_path",
    "git_sha",
    "data_hash",
    "seed",
    "created_at",
]


def _serialize_opt_run_row(row: tuple, columns: list[str]) -> dict:
    """Serialize a single opt_runs row tuple into a dict.

    Normalises created_at to ISO 8601 string.
    """
    record: dict = {}
    for col, val in zip(columns, row):
        if col == "created_at":
            if val is not None and hasattr(val, "isoformat"):
                record[col] = val.isoformat()
            elif val is not None:
                record[col] = str(val)
            else:
                record[col] = None
        elif col in ("total_combos", "completed_combos", "fold_count"):
            record[col] = int(val) if val is not None else None
        else:
            record[col] = val
    return record


def _serialize_opt_result_row(row: tuple, columns: list[str]) -> dict:
    """Serialize a single opt_results row tuple into a dict.

    Normalises floats and timestamps; edge_ratio and nullable metrics
    serialise as JSON null when None.
    """
    record: dict = {}
    for col, val in zip(columns, row):
        if col == "created_at":
            if val is not None and hasattr(val, "isoformat"):
                record[col] = val.isoformat()
            elif val is not None:
                record[col] = str(val)
            else:
                record[col] = None
        elif col == "opening_range_minutes":
            record[col] = int(val) if val is not None else None
        elif col == "fold_idx":
            record[col] = int(val) if val is not None else None
        elif col == "seed":
            record[col] = int(val) if val is not None else None
        elif col in (
            "atr_stop_mult", "r_target",
            "is_sharpe", "oos_sharpe", "is_return", "oos_return", "edge_ratio",
        ):
            # Nullable float metrics — serialise as null if None
            record[col] = float(val) if val is not None else None
        else:
            record[col] = val
    return record


@router.get("/optimizations")
def get_optimizations(
    store: Annotated[DuckDBStore, Depends(get_store)] = ...,  # type: ignore[assignment]
) -> list[dict]:
    """Return all optimization run summaries ordered most-recent first.

    Returns an empty list when no runs exist — HTTP 200 (empty is valid).
    """
    rows = store._conn.execute(_OPT_RUNS_SQL).fetchall()
    result: list[dict] = [_serialize_opt_run_row(row, _OPT_RUNS_COLUMNS) for row in rows]
    log.info("optimizations.listed", rowcount=len(result))
    return result


@router.get("/optimizations/{run_id}/results")
def get_opt_results(
    run_id: str,
    store: Annotated[DuckDBStore, Depends(get_store)] = ...,  # type: ignore[assignment]
) -> list[dict]:
    """Return per-param-combo result rows for a run, sorted by oos_sharpe DESC.

    Returns an empty list when run_id has no results — HTTP 200 (empty is valid).
    edge_ratio may be None (serialises as JSON null) for combos with oos_sharpe == 0.
    """
    # DuckDBStore.read_opt_results handles the query and column name mapping
    raw_rows = store.read_opt_results(run_id)
    log.info("opt_results.listed", run_id=run_id, rowcount=len(raw_rows))
    # read_opt_results returns list[dict] already — just normalise types
    result: list[dict] = []
    for row in raw_rows:
        record: dict = {}
        for col, val in row.items():
            if col == "created_at":
                if val is not None and hasattr(val, "isoformat"):
                    record[col] = val.isoformat()
                elif val is not None:
                    record[col] = str(val)
                else:
                    record[col] = None
            elif col == "opening_range_minutes":
                record[col] = int(val) if val is not None else None
            elif col in ("fold_idx", "seed"):
                record[col] = int(val) if val is not None else None
            elif col in (
                "atr_stop_mult", "r_target",
                "is_sharpe", "oos_sharpe", "is_return", "oos_return", "edge_ratio",
            ):
                record[col] = float(val) if val is not None else None
            else:
                record[col] = val
        result.append(record)
    return result


@router.get("/optimizations/{run_id}/heatmap")
def get_opt_heatmap(
    run_id: str,
    axis_x: str = Query(..., description="X-axis parameter name"),
    axis_y: str = Query(..., description="Y-axis parameter name"),
    store: Annotated[DuckDBStore, Depends(get_store)] = ...,  # type: ignore[assignment]
) -> dict:
    """Return a 2D grid {x, y, z} for Plotly heatmap rendering.

    Security (T-04-03-01): Both axis_x and axis_y are validated against
    ALLOWED_AXES before any SQL is constructed. Column names from the
    whitelist are safe to interpolate into the GROUP BY after this gate.

    Response shape:
      {
        "x": [sorted unique axis_x values],
        "y": [sorted unique axis_y values],
        "z": [[oos_sharpe, ...], ...]  # indexed [y_idx][x_idx]
      }

    Returns {"x": [], "y": [], "z": []} when no results exist for run_id.
    """
    # T-04-03-01: Whitelist validation — must happen before ANY SQL construction
    if axis_x not in ALLOWED_AXES:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Invalid axis '{axis_x}'. "
                f"Allowed: {sorted(ALLOWED_AXES)}"
            ),
        )
    if axis_y not in ALLOWED_AXES:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Invalid axis '{axis_y}'. "
                f"Allowed: {sorted(ALLOWED_AXES)}"
            ),
        )

    # Column names are safe to interpolate after whitelist validation above.
    # run_id uses parameterized binding (? placeholder).
    sql = (
        f"SELECT {axis_x}, {axis_y}, AVG(oos_sharpe) AS oos_sharpe "
        f"FROM opt_results "
        f"WHERE run_id = ? "
        f"GROUP BY {axis_x}, {axis_y} "
        f"ORDER BY {axis_y} ASC, {axis_x} ASC"
    )
    rows = store._conn.execute(sql, [run_id]).fetchall()

    if not rows:
        return {"x": [], "y": [], "z": []}

    # Build sorted unique axis value lists
    x_vals_raw = sorted({row[0] for row in rows})
    y_vals_raw = sorted({row[1] for row in rows})

    # Build lookup: (x_val, y_val) -> oos_sharpe
    lookup: dict[tuple, float | None] = {}
    for row in rows:
        x_val, y_val, sharpe = row
        lookup[(x_val, y_val)] = float(sharpe) if sharpe is not None else None

    # Construct 2D grid indexed [y_idx][x_idx]
    z: list[list[float | None]] = []
    for y_val in y_vals_raw:
        row_z: list[float | None] = []
        for x_val in x_vals_raw:
            row_z.append(lookup.get((x_val, y_val)))
        z.append(row_z)

    # Normalise axis values to JSON-serialisable types
    x_vals: list = [
        int(v) if isinstance(v, float) and v == int(v) else float(v) if isinstance(v, float) else v
        for v in x_vals_raw
    ]
    y_vals: list = [
        float(v) if isinstance(v, float) else v
        for v in y_vals_raw
    ]

    log.info(
        "heatmap.generated",
        run_id=run_id,
        axis_x=axis_x,
        axis_y=axis_y,
        x_count=len(x_vals),
        y_count=len(y_vals),
    )
    return {"x": x_vals, "y": y_vals, "z": z}


@router.get("/optimizations/{run_id}")
def get_optimization(
    run_id: str,
    store: Annotated[DuckDBStore, Depends(get_store)] = ...,  # type: ignore[assignment]
) -> dict:
    """Return a single opt_runs row by run_id.

    Error codes:
    - 404 ``optimization run not found`` — run_id not in opt_runs.

    Includes completed_combos and total_combos for progress polling
    (2s poll pattern from D-12 while status='running').
    """
    row = store._conn.execute(_OPT_RUN_BY_ID_SQL, [run_id]).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="optimization run not found")
    result = _serialize_opt_run_row(row, _OPT_RUNS_COLUMNS)
    log.info("optimization.fetched", run_id=run_id)
    return result


@router.get("/optimizations/{run_id}/results/{result_id}/equity")
def get_opt_result_equity(
    run_id: str,
    result_id: str,
    store: Annotated[DuckDBStore, Depends(get_store)] = ...,  # type: ignore[assignment]
) -> list[dict]:
    """Return the OOS equity curve for a single opt result row.

    Reads the Parquet file pointed to by equity_curve_path in opt_results
    and returns [{ts_utc, equity, drawdown}] ordered by ts_utc ASC.

    Error codes:
    - 404 result not found — result_id not in opt_results for this run_id
    - 404 equity curve not found — DB row exists but Parquet file is missing
    - 403 forbidden equity path — path traversal attempt detected
    """
    row = store._conn.execute(
        "SELECT equity_curve_path FROM opt_results WHERE result_id = ? AND run_id = ?",
        [result_id, run_id],
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="opt result not found")

    equity_curve_path: str | None = row[0]
    if not equity_curve_path:
        raise HTTPException(status_code=404, detail="equity curve not found")

    candidate = Path(equity_curve_path)
    if candidate.is_absolute():
        abs_path = candidate.resolve()
    else:
        repo_root = _find_repo_root(Path(__file__).resolve())
        abs_path = (repo_root / equity_curve_path).resolve()

    try:
        abs_path.relative_to(_OPT_EQUITY_ROOT)
    except ValueError:
        log.warning("opt_equity.path_traversal_blocked", result_id=result_id, path=equity_curve_path)
        raise HTTPException(status_code=403, detail="forbidden equity path")

    if not abs_path.exists():
        raise HTTPException(status_code=404, detail="equity curve not found")

    parquet_path_str = str(abs_path).replace("\\", "/")
    equity_rows = store._conn.execute(
        'SELECT ts_utc, "equity_$" AS equity, "drawdown_$" AS drawdown '
        "FROM read_parquet($1) ORDER BY ts_utc ASC",
        [parquet_path_str],
    ).fetchall()

    result: list[dict] = []
    for eq_row in equity_rows:
        ts_utc_val, equity_val, drawdown_val = eq_row
        ts_str = ts_utc_val.isoformat() if ts_utc_val is not None and hasattr(ts_utc_val, "isoformat") else str(ts_utc_val)
        result.append({
            "ts_utc": ts_str,
            "equity": float(equity_val) if equity_val is not None else None,
            "drawdown": float(drawdown_val) if drawdown_val is not None else None,
        })

    log.info("opt_equity.served", run_id=run_id, result_id=result_id, rowcount=len(result))
    return result
