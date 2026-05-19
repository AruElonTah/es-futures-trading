"""Shared pytest fixtures for tv-bridge tests (Phase 6).

Provides:
    - in_memory_store: DuckDBStore(":memory:") with ensure_schema() called
    - mock_bus: minimal EventBus stub that records published events (for tests
      that only need publish behavior — NOT subscribe)
    - real_bus: real EventBus for tests that use bus.subscribe()
    - mock_settings: real Settings() constructed from defaults
    - mock_mcp_session: AsyncMock simulating a live ClientSession
    - bridge: TVBridge(store, bus, settings) — constructed but NOT started
      Uses a real EventBus so start() can create subscriber tasks (Plan 02+).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from trading_core.config import Settings
from trading_core.events import EventBus
from trading_core.storage.duckdb_store import DuckDBStore
from tv_bridge import TVBridge


@pytest.fixture
def in_memory_store() -> DuckDBStore:
    """In-memory DuckDBStore with full schema applied."""
    store = DuckDBStore(":memory:")
    store.ensure_schema()
    yield store
    store.close()


class _MockBus:
    """Minimal EventBus stub that records published events.

    Only supports publish() — use the real EventBus (via real_bus fixture
    or EventBus() directly) for tests that need bus.subscribe().
    """

    def __init__(self) -> None:
        self.published_events: list[tuple[str, object]] = []

    async def publish(self, topic: str, event: object) -> None:
        self.published_events.append((topic, event))


@pytest.fixture
def mock_bus() -> _MockBus:
    """Minimal EventBus stub recording (topic, event) pairs.

    Note: does NOT support subscribe(). Use EventBus() directly in tests
    that need the subscriber pattern.
    """
    return _MockBus()


@pytest.fixture
def real_bus() -> EventBus:
    """Real EventBus for tests that need bus.subscribe() functionality."""
    return EventBus()


@pytest.fixture
def mock_settings() -> Settings:
    """Real Settings() constructed from defaults (no .env needed)."""
    return Settings()


@pytest.fixture
def mock_mcp_session() -> AsyncMock:
    """AsyncMock simulating a live MCP ClientSession.

    By default call_tool() returns an object with .content[0].text = '{}'.
    Override per-test: ``mock_mcp_session.call_tool.return_value = ...``.
    """
    session = AsyncMock()
    # Build a minimal result object with the .content[0].text structure
    content_item = MagicMock()
    content_item.text = "{}"
    result = MagicMock()
    result.content = [content_item]
    session.call_tool.return_value = result
    return session


@pytest.fixture
def bridge(in_memory_store: DuckDBStore, mock_settings: Settings) -> TVBridge:
    """TVBridge constructed but NOT started (no supervisor task, no subprocess).

    Uses a real EventBus so start() can create subscriber tasks (Plan 02+).
    Tests that need to observe published events should capture them via the
    real EventBus subscribe() pattern.
    """
    # Use a real EventBus so _subscribe_signals / _subscribe_fills tasks
    # don't crash when start() creates them (Plan 02 requirement).
    bus = EventBus()
    return TVBridge(store=in_memory_store, bus=bus, settings=mock_settings)
