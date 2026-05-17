"""Optimization subpackage — grid search + walk-forward (Phase 4).

Exports:
    OptSpace: Pydantic model for parameter space definition.
    ParamAxis: Pydantic model for a single optimization axis.
    get_fold_boundaries: Rolling walk-forward fold generator.
"""

from trading_core.optimization.space import OptSpace, ParamAxis
from trading_core.optimization.splitter import get_fold_boundaries

__all__ = ["OptSpace", "ParamAxis", "get_fold_boundaries"]
