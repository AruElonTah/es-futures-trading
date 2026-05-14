"""Data-domain public surface: Bar model + DataSource Protocol.

Importing from `trading_core.data` resolves the Bar Pydantic model and the
DataSource Protocol seam (with the four DataSourceError-family exceptions).
Concrete DataSource implementations (TwelveDataSource, TradingViewDataSource)
land in Plan 04 and Phase 6 respectively.
"""

from __future__ import annotations

from .models import Bar
from .protocols import (
    DataSource,
    DataSourceError,
    DataSourceUnavailable,
    GapDetected,
    RateLimited,
)

__all__ = [
    "Bar",
    "DataSource",
    "DataSourceError",
    "DataSourceUnavailable",
    "GapDetected",
    "RateLimited",
]
