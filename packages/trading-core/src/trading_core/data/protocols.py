"""DataSource Protocol seam (MD-01) + adapter exception family.

NO runtime-checkable decorator — see 01-RESEARCH.md §Pattern 1 + Anti-Patterns.
Static type-checking (mypy / pyright) verifies conformance; runtime isinstance()
is slow AND only validates method *presence*, not signatures or return types.

Concrete adapters (Plan 04 TwelveDataSource, Phase 6 TradingViewDataSource) just
expose the same method names; mypy guarantees the signatures match.
"""

from __future__ import annotations

from datetime import datetime
from typing import AsyncIterator, Protocol

import pandas as pd

from .models import Bar


class DataSourceError(Exception):
    """Base for all DataSource adapter errors."""


class DataSourceUnavailable(DataSourceError):
    """Provider is reachable but reported a service-level failure."""


class RateLimited(DataSourceError):
    """Provider returned 429 / pacing-budget exhausted."""


class GapDetected(DataSourceError):
    """Provider returned bars but with internal gaps (caller decides recovery)."""


class DataSource(Protocol):
    """Async contract every bar provider implements.

    Inputs are tz-aware UTC datetimes. Outputs are pandas DataFrames whose rows
    match the `Bar` model (ts_utc = OPEN time, UTC).
    """

    name: str  # e.g., "twelve_data" / "tradingview_mcp" — recorded in runs.notes

    async def fetch_bars(
        self,
        symbol: str,
        timeframe: str,        # "1m" | "5m" | "15m"
        start: datetime,       # tz-aware UTC
        end: datetime,         # tz-aware UTC, exclusive
    ) -> pd.DataFrame:
        """Historical pull. DataFrame indexed by ts_utc with bar OPEN time.

        Raises: DataSourceUnavailable | RateLimited | GapDetected.
        """
        ...

    async def subscribe_bars(
        self,
        symbol: str,
        timeframe: str,
    ) -> AsyncIterator[Bar]:
        """Live polling. Yields completed bars as they close.

        Yields tz-aware UTC Bar instances. Polling implementations should sleep
        between yields based on timeframe. CDP/connection failures should be
        published as `DegradedStateEvent` on the bus rather than raised — the
        caller would otherwise have to catch and re-establish, which is the
        bridge's job (Phase 6).
        """
        ...
