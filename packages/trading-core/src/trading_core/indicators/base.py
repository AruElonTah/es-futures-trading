"""Look-ahead-safe indicator base class (Plan 02-01).

Contract:
    push(bar) appends bar to _bars, calls _compute_current(), appends result
    to _values. After N pushes, len(_values) == len(_bars) == N.

    snapshot_at(t) returns _values[t-1] — the value computed from bars[0:t-1]
    inclusive (t bars total). This equals the indicator recomputed from scratch
    on bars[:t]. No future bar data can bleed in because _values[t-1] was
    stored when only bars[0:t-1] existed.

    snapshot_at(0) always returns None (no bars = no value).

    current == snapshot_at(len(_bars)) == _values[-1].
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal

from trading_core.data.models import Bar


class IndicatorBase(ABC):
    """Abstract base for all look-ahead-safe indicators."""

    def __init__(self) -> None:
        self._bars: list[Bar] = []
        self._values: list[Decimal | None] = []

    def push(self, bar: Bar) -> None:
        """Append bar, compute new value, store in _values."""
        self._bars.append(bar)
        result = self._compute_current()
        self._values.append(result)

    def snapshot_at(self, t: int) -> Decimal | None:
        """Value computed from bars[0:t] (t bars, indices 0..t-1).

        Returns None for t == 0 or t > len pushed.
        """
        if t == 0:
            return None
        if t > len(self._values):
            return None
        return self._values[t - 1]

    @property
    def current(self) -> Decimal | None:
        """Most recently computed value."""
        return self._values[-1] if self._values else None

    @property
    def is_warm(self) -> bool:
        return self.current is not None

    @abstractmethod
    def _compute_current(self) -> Decimal | None:
        """Compute value from self._bars (all bars including the just-pushed one)."""

    @abstractmethod
    def warmup_bars(self) -> int:
        """Minimum number of bars needed for a non-None value."""
