"""FastAPI dependency providers — singletons scoped to the app lifespan.

Import in route handlers via Depends():

    from api.deps import get_store, get_bus

    @router.get("/bars")
    async def get_bars(store: Annotated[DuckDBStore, Depends(get_store)]) -> list[dict]:
        ...

The lifespan in app.py instantiates DuckDBStore and EventBus on startup and
stores them on ``app.state``. Dependencies here simply retrieve them —
no connection creation happens inside the dependency function itself.
"""

from __future__ import annotations

from fastapi import Request
from trading_core.events import EventBus
from trading_core.storage.duckdb_store import DuckDBStore


def get_store(request: Request) -> DuckDBStore:
    """Return the DuckDBStore singleton from app.state (read-only on read endpoints)."""
    return request.app.state.store  # type: ignore[no-any-return]


def get_bus(request: Request) -> EventBus:
    """Return the EventBus singleton from app.state."""
    return request.app.state.bus  # type: ignore[no-any-return]
