"""Strategies API routes — Phase 7 Plan 02.

UI-07 strategy controls panel endpoints:
  GET  /strategies               — list all registered strategies with params + enabled state
  PUT  /strategies/{id}/params   — update strategy YAML params; publish TOPIC_STRATEGY_RELOAD
  POST /strategies/{id}/toggle   — toggle strategy enabled/disabled state
  POST /backtests/run            — accept a background backtest job (202 + run_id)

Security:
  T-07-02-01: strategy_id validated against ^[a-z0-9_-]+$ BEFORE any filesystem path construction
  T-07-02-02: Pydantic ORBConfigUpdate validates param values before yaml.dump()
  Path.resolve() + relative_to() guard applied to all yaml_path constructions
"""

from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path
from typing import Annotated

import yaml
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, field_validator

from api.deps import get_bus, get_store
from trading_core.events.models import TOPIC_STRATEGY_RELOAD
from trading_core.logging import get_logger
from trading_core.storage.duckdb_store import DuckDBStore
from trading_core.storage.runs import new_run_id

router = APIRouter()
_log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Path-traversal guard (T-07-02-01)
# ---------------------------------------------------------------------------

_STRATEGY_ID_RE = re.compile(r'^[a-z0-9_-]+$')  # security: T-07-02-01 path guard


# ---------------------------------------------------------------------------
# Repo root helper (same pattern as app.py and backtests.py — WR-001)
# ---------------------------------------------------------------------------

def _find_repo_root(start: Path) -> Path:
    """Walk upward from *start* to the outermost directory containing pyproject.toml."""
    found: Path | None = None
    for candidate in [start, *start.parents]:
        if (candidate / "pyproject.toml").exists():
            found = candidate
    if found is None:
        raise RuntimeError(f"Could not locate repo root from {start}")
    return found


# ---------------------------------------------------------------------------
# Pydantic update model (T-07-02-02: validate before YAML write)
# ---------------------------------------------------------------------------

class ORBConfigUpdate(BaseModel):
    """Editable subset of ORBConfig params for PUT /strategies/{id}/params.

    All fields are optional — only non-None values are merged into the YAML.
    Validators reject non-positive values to prevent invalid strategy configs.
    """

    opening_range_minutes: int | None = None
    atr_stop_mult: float | None = None
    r_target: float | None = None

    @field_validator('opening_range_minutes')
    @classmethod
    def opening_range_minutes_positive(cls, v: int | None) -> int | None:
        if v is not None and v <= 0:
            raise ValueError('opening_range_minutes must be positive (> 0)')
        return v

    @field_validator('atr_stop_mult')
    @classmethod
    def atr_stop_mult_positive(cls, v: float | None) -> float | None:
        if v is not None and v <= 0:
            raise ValueError('atr_stop_mult must be positive (> 0)')
        return v

    @field_validator('r_target')
    @classmethod
    def r_target_positive(cls, v: float | None) -> float | None:
        if v is not None and v <= 0:
            raise ValueError('r_target must be positive (> 0)')
        return v


# ---------------------------------------------------------------------------
# Background backtest stub task (wired to full BacktestEngine in Phase 8)
# ---------------------------------------------------------------------------

async def _run_backtest_task(run_id: str, app_state: object) -> None:
    """Stub background task — sleeps 2s then marks the run complete.

    Real BacktestEngine wiring is a separate concern (Phase 8).
    """
    import asyncio as _asyncio
    await _asyncio.sleep(2)
    store: DuckDBStore = getattr(app_state, "store", None)
    if store is not None:
        try:
            store._conn.execute(
                "UPDATE backtests SET status = 'complete' WHERE run_id = ?",
                [run_id],
            )
            _log.info("backtest.stub_complete", run_id=run_id)
        except Exception as exc:
            _log.error("backtest.stub_error", run_id=run_id, error=str(exc))


# ---------------------------------------------------------------------------
# GET /strategies
# ---------------------------------------------------------------------------

@router.get("/strategies")
async def get_strategies(request: Request) -> list[dict]:
    """List all registered strategies with current params and enabled state.

    Reads all *.yaml files from config/strategies/, merges with per-strategy
    enabled state from DuckDB engine_state table.

    Returns:
        List of dicts with strategy_id, name, params, enabled fields.
    """
    store: DuckDBStore = get_store(request)
    _repo_root = _find_repo_root(Path(__file__).resolve())
    strategies_dir = _repo_root / "config" / "strategies"

    result: list[dict] = []
    for yaml_path in sorted(strategies_dir.glob("*.yaml")):
        with yaml_path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        strategy_id = data.get("strategy_id", yaml_path.stem)
        enabled = store.get_strategy_enabled(strategy_id)
        result.append({
            "strategy_id": strategy_id,
            "name": data.get("name", strategy_id),
            "params": data.get("params", {}),
            "enabled": enabled,
        })

    _log.info("strategies.listed", count=len(result))
    return result


# ---------------------------------------------------------------------------
# PUT /strategies/{strategy_id}/params
# ---------------------------------------------------------------------------

@router.put("/strategies/{strategy_id}/params")
async def put_strategy_params(
    strategy_id: str,
    body: ORBConfigUpdate,
    request: Request,
) -> dict:
    """Update strategy YAML params and publish TOPIC_STRATEGY_RELOAD.

    Security (T-07-02-01): strategy_id validated against ^[a-z0-9_-]+$ BEFORE
    any filesystem path construction. Path.resolve() + relative_to() guard applied.

    Security (T-07-02-02): Pydantic ORBConfigUpdate validates all fields before
    yaml.dump(); only model_dump() output is written to YAML, never raw request body.

    Args:
        strategy_id: Strategy YAML stem (e.g. 'orb').
        body: ORBConfigUpdate with optional fields to merge.

    Returns:
        Dict with strategy_id and updated params.

    Raises:
        HTTPException(400): if strategy_id fails regex validation.
        HTTPException(403): if resolved path escapes config/strategies/ directory.
        HTTPException(404): if strategy YAML does not exist.
        HTTPException(422): automatic on Pydantic validation failure.
    """
    # T-07-02-01: regex guard FIRST, before any path construction
    if not _STRATEGY_ID_RE.match(strategy_id):
        raise HTTPException(status_code=400, detail="invalid strategy_id")

    _repo_root = _find_repo_root(Path(__file__).resolve())
    strategies_root = (_repo_root / "config" / "strategies").resolve()
    yaml_path = (strategies_root / f"{strategy_id}.yaml").resolve()

    # Path escape guard (T-07-02-01 defense-in-depth)
    try:
        yaml_path.relative_to(strategies_root)
    except ValueError:
        raise HTTPException(status_code=403, detail="forbidden strategy path")

    if not yaml_path.exists():
        raise HTTPException(status_code=404, detail=f"strategy '{strategy_id}' not found")

    # Read current YAML
    with yaml_path.open(encoding="utf-8") as f:
        current = yaml.safe_load(f) or {}

    # Merge non-None fields from body into current params (T-07-02-02: use model_dump)
    update_dict = body.model_dump(exclude_none=True)
    if "params" not in current:
        current["params"] = {}
    current["params"].update(update_dict)

    # Write YAML back atomically (WR-03: write to tmp then os.replace to avoid
    # partial-write corruption visible to concurrent GET /strategies requests).
    tmp_path = yaml_path.with_suffix('.yaml.tmp')
    with tmp_path.open("w", encoding="utf-8") as f:
        yaml.dump(current, f, default_flow_style=False)
    os.replace(tmp_path, yaml_path)

    # Publish TOPIC_STRATEGY_RELOAD (D-14)
    bus = get_bus(request)
    await bus.publish(
        TOPIC_STRATEGY_RELOAD,
        {
            "type": "strategy_reload",
            "payload": {"strategy_id": strategy_id, "params": current["params"]},
        },
    )

    _log.info("strategy.params_updated", strategy_id=strategy_id, params=current["params"])
    return {"strategy_id": strategy_id, "params": current["params"]}


# ---------------------------------------------------------------------------
# POST /strategies/{strategy_id}/toggle
# ---------------------------------------------------------------------------

@router.post("/strategies/{strategy_id}/toggle")
async def post_strategy_toggle(
    strategy_id: str,
    request: Request,
) -> dict:
    """Toggle strategy enabled/disabled state.

    Reads current enabled state from DuckDB, flips it, writes the new state
    back, publishes a bus event.

    Args:
        strategy_id: Strategy identifier (e.g. 'orb').

    Returns:
        Dict with strategy_id and new enabled boolean.

    Raises:
        HTTPException(400): if strategy_id fails regex validation.
    """
    if not _STRATEGY_ID_RE.match(strategy_id):
        raise HTTPException(status_code=400, detail="invalid strategy_id")

    store: DuckDBStore = get_store(request)
    bus = get_bus(request)

    # Read current state and flip
    current_enabled = store.get_strategy_enabled(strategy_id)
    new_enabled = not current_enabled

    # Persist new state
    store.write_strategy_enabled(strategy_id, new_enabled)

    # Publish bus event for engine to react
    await bus.publish(
        TOPIC_STRATEGY_RELOAD,
        {
            "type": "strategy_toggled",
            "payload": {"strategy_id": strategy_id, "enabled": new_enabled},
        },
    )

    _log.info("strategy.toggled", strategy_id=strategy_id, enabled=new_enabled)
    return {"strategy_id": strategy_id, "enabled": new_enabled}


# ---------------------------------------------------------------------------
# POST /backtests/run — background backtest job (D-15)
# ---------------------------------------------------------------------------

@router.post("/backtests/run", status_code=202)
async def post_run_backtest(request: Request) -> dict:
    """Accept a background backtest job and return run_id immediately.

    Inserts a pending row into backtests table, starts the background task,
    returns the run_id so the UI can poll GET /backtests/{run_id}.

    Returns:
        Dict with run_id (HTTP 202 Accepted).
    """
    run_id = new_run_id()
    store: DuckDBStore = get_store(request)

    # Mark pending immediately so UI can begin polling (D-15)
    store.write_pending_backtest(run_id)

    # Non-blocking background task (tv.py asyncio.create_task pattern)
    asyncio.create_task(
        _run_backtest_task(run_id, request.app.state),
        name=f"backtest_{run_id}",
    )

    _log.info("backtest.started", run_id=run_id)
    return {"run_id": run_id}
