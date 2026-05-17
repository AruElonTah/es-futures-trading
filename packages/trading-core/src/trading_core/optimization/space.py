"""OptSpace — parameter space model for grid optimization (OPT-01, OPT-06).

Parses and validates an ``optspace.yaml`` file into a typed Pydantic model.
The model enforces:
    - Every axis has >= 5 values (OPT-06, enforced at parse time)
    - Every param name exists in the strategy config (T-04-01-01)
    - combos() returns itertools.product of all axis values as list[dict]
    - param_grid_hash() returns a stable SHA256 hex of the full param grid

Usage::

    space = OptSpace.load("config/strategies/orb.optspace.yaml")
    print(len(space.combos()))   # 125 for the 5x5x5 coarse ORB grid
    print(space.param_grid_hash())  # 64-char SHA256 hex
"""

from __future__ import annotations

import dataclasses
import itertools
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, model_validator

from trading_core.storage.runs import param_hash


class ParamAxis(BaseModel):
    """A single optimization axis defined as an explicit list of values.

    Attributes:
        type: Always ``"list"`` (D-02 format; ``range/step`` deferred to v2).
        values: Ordered list of parameter values to sweep over.
    """

    type: Literal["list"]
    values: list[float | int]


class OptSpace(BaseModel):
    """Parameter space model for grid optimization.

    Attributes:
        strategy: Strategy slug (e.g., ``"orb"``).
        params: Mapping from param name to its axis definition.
    """

    strategy: str
    params: dict[str, ParamAxis]

    @model_validator(mode="after")
    def validate_axes(self) -> "OptSpace":
        """Validate param names and axis sizes at parse time.

        Raises:
            ValueError: If any param name is not in ``ORBConfig`` fields
                (T-04-01-01), or any axis has fewer than 5 values (OPT-06).
        """
        # Inline import to avoid circular-import risk (A2).
        from trading_core.strategy.orb import ORBConfig  # noqa: PLC0415

        valid_names = {f.name for f in dataclasses.fields(ORBConfig)}

        for name, axis in self.params.items():
            # OPT-06: minimum 5 values per axis (coarse-grid-first enforcement)
            if len(axis.values) < 5:
                raise ValueError(
                    f"Axis '{name}' has {len(axis.values)} values — minimum 5 (OPT-06)"
                )
            # T-04-01-01: param name must exist in the strategy's config
            if name not in valid_names:
                raise ValueError(
                    f"Unknown param '{name}' — not in ORBConfig fields: {valid_names}"
                )
        return self

    def combos(self) -> list[dict]:
        """Return all parameter combinations as a list of dicts.

        Uses ``itertools.product`` over axis values in insertion order.
        The returned list has exactly ``product(len(axis.values))`` entries.

        Example::

            space.combos()[0]
            # {"opening_range_minutes": 5, "atr_stop_mult": 1.0, "r_target": 1.5}
        """
        keys = list(self.params.keys())
        value_lists = [self.params[k].values for k in keys]
        return [dict(zip(keys, combo)) for combo in itertools.product(*value_lists)]

    def param_grid_hash(self) -> str:
        """Return a stable SHA256 hex of the full parameter grid.

        Reuses ``param_hash()`` from ``trading_core.storage.runs`` — the same
        canonical-JSON function used for run reproducibility hashing (D-14).
        Calling this twice on the same ``OptSpace`` always returns the same
        64-char hex string.
        """
        return param_hash({k: v.values for k, v in self.params.items()})

    @classmethod
    def load(cls, path: "Path | str") -> "OptSpace":
        """Load and validate an ``optspace.yaml`` file.

        Args:
            path: Path to the YAML file (e.g.,
                ``"config/strategies/orb.optspace.yaml"``).

        Returns:
            Validated ``OptSpace`` instance.

        Raises:
            ValueError: If any axis fails OPT-06 or T-04-01-01 checks.
            FileNotFoundError: If ``path`` does not exist.
        """
        path = Path(path)
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return cls.model_validate(data)
