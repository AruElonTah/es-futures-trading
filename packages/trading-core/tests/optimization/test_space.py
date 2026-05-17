"""Tests for OptSpace Pydantic model — OPT-01, OPT-06.

Verifies:
- 125 combos from 5x5x5 coarse ORB grid
- param_grid_hash is stable across two loads of the same YAML
- axis with < 5 values raises ValueError at parse time (OPT-06)
- unknown param name raises ValueError (T-04-01-01)
"""
from __future__ import annotations

from pathlib import Path

import pytest

from trading_core.optimization.space import OptSpace, ParamAxis


# Path to the coarse ORB optspace YAML shipped with the project
_ORB_YAML = Path("config/strategies/orb.optspace.yaml")


def test_combo_count() -> None:
    """125 combos from 5x5x5 grid."""
    space = OptSpace.load(_ORB_YAML)
    combos = space.combos()
    assert len(combos) == 125, f"Expected 125 combos, got {len(combos)}"


def test_combo_keys() -> None:
    """Each combo dict has all three ORB param keys."""
    space = OptSpace.load(_ORB_YAML)
    combo = space.combos()[0]
    assert "opening_range_minutes" in combo
    assert "atr_stop_mult" in combo
    assert "r_target" in combo


def test_hash_stable() -> None:
    """Same YAML loaded twice produces the same param_grid_hash."""
    hash1 = OptSpace.load(_ORB_YAML).param_grid_hash()
    hash2 = OptSpace.load(_ORB_YAML).param_grid_hash()
    assert hash1 == hash2, "param_grid_hash must be deterministic"
    assert len(hash1) == 64, "Should be 64-char SHA256 hex"


def test_axis_too_narrow() -> None:
    """Axis with 4 values raises ValueError at parse time (OPT-06)."""
    with pytest.raises(ValueError, match="minimum 5"):
        OptSpace(
            strategy="orb",
            params={
                "opening_range_minutes": ParamAxis(type="list", values=[5, 10, 15, 20]),
                "atr_stop_mult": ParamAxis(type="list", values=[1.0, 1.5, 2.0, 2.5, 3.0]),
                "r_target": ParamAxis(type="list", values=[1.5, 2.0, 2.5, 3.0, 3.5]),
            },
        )


def test_unknown_param_name() -> None:
    """Nonexistent ORBConfig field name raises ValueError (T-04-01-01)."""
    with pytest.raises(ValueError, match="Unknown param"):
        OptSpace(
            strategy="orb",
            params={
                "nonexistent_param": ParamAxis(type="list", values=[1, 2, 3, 4, 5]),
                "atr_stop_mult": ParamAxis(type="list", values=[1.0, 1.5, 2.0, 2.5, 3.0]),
                "r_target": ParamAxis(type="list", values=[1.5, 2.0, 2.5, 3.0, 3.5]),
            },
        )


def test_strategy_field() -> None:
    """Loaded YAML has strategy = 'orb'."""
    space = OptSpace.load(_ORB_YAML)
    assert space.strategy == "orb"
