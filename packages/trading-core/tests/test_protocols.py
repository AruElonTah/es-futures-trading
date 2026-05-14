"""Protocol seam shape tests (MD-01).

Plan 01-02 / Task 2.

These tests verify structural attributes (method names, exceptions) rather than
runtime conformance — we deliberately do NOT use `@runtime_checkable` on the
four Protocols (see 01-RESEARCH.md §Anti-Patterns line 948 and §Pattern 1):
- @runtime_checkable's isinstance() check is slow.
- It only validates method *presence*, not signatures / return types.
- mypy + pyright catch real conformance failures at static-analysis time.

So these tests are deliberately attribute-presence checks. The real Protocol
conformance is verified by Plan 04's `uv run mypy` over the TwelveDataSource
implementation.
"""

from __future__ import annotations

import inspect
from typing import Final

from trading_core.data.protocols import (
    DataSource,
    DataSourceError,
    DataSourceUnavailable,
    GapDetected,
    RateLimited,
)
from trading_core.events import (
    TOPIC_BARS,
    TOPIC_DEGRADED_STATE,
    TOPIC_EQUITY,
    TOPIC_FILLS,
    TOPIC_POSITIONS,
    TOPIC_RISK_DECISIONS,
    TOPIC_SIGNALS,
    BarReceived,
    DegradedStateEvent,
)
from trading_core.execution.protocols import Executor
from trading_core.risk.protocols import RiskManager
from trading_core.strategy.protocols import Strategy


class TestDataSourceProtocolShape:
    def test_datasource_protocol_structural_match(self):
        """A class with the documented attributes is a structural DataSource."""

        # Any class with the right attributes satisfies the Protocol structurally.
        # We don't isinstance-check (no @runtime_checkable); we attribute-check.
        assert hasattr(DataSource, "fetch_bars")
        assert hasattr(DataSource, "subscribe_bars")

    def test_datasource_fetch_bars_is_async(self):
        # Protocol method bodies are `...` — but `inspect.iscoroutinefunction`
        # on the function object resolves the `async def` mark.
        assert inspect.iscoroutinefunction(DataSource.fetch_bars)

    def test_datasource_subscribe_bars_is_async(self):
        assert inspect.iscoroutinefunction(DataSource.subscribe_bars)


class TestDataSourceExceptionHierarchy:
    def test_subclasses(self):
        assert issubclass(DataSourceUnavailable, DataSourceError)
        assert issubclass(RateLimited, DataSourceError)
        assert issubclass(GapDetected, DataSourceError)

    def test_datasource_error_is_exception(self):
        assert issubclass(DataSourceError, Exception)


class TestStrategyProtocolShape:
    def test_has_warmup_bars(self):
        assert hasattr(Strategy, "warmup_bars")

    def test_has_on_bar(self):
        assert hasattr(Strategy, "on_bar")


class TestRiskManagerProtocolShape:
    def test_has_check(self):
        assert hasattr(RiskManager, "check")

    def test_check_is_async(self):
        assert inspect.iscoroutinefunction(RiskManager.check)


class TestExecutorProtocolShape:
    def test_has_fill(self):
        assert hasattr(Executor, "fill")

    def test_fill_is_async(self):
        assert inspect.iscoroutinefunction(Executor.fill)


class TestNoRuntimeCheckable:
    """Anti-pattern guard — the four Protocols MUST NOT be @runtime_checkable."""

    def test_datasource_not_runtime_checkable(self):
        # @runtime_checkable sets _is_runtime_protocol = True on the Protocol class.
        assert getattr(DataSource, "_is_runtime_protocol", False) is False

    def test_strategy_not_runtime_checkable(self):
        assert getattr(Strategy, "_is_runtime_protocol", False) is False

    def test_riskmanager_not_runtime_checkable(self):
        assert getattr(RiskManager, "_is_runtime_protocol", False) is False

    def test_executor_not_runtime_checkable(self):
        assert getattr(Executor, "_is_runtime_protocol", False) is False


class TestEventModels:
    def test_bar_received_constructible(self):
        from datetime import datetime, timezone
        from decimal import Decimal

        from trading_core.data import Bar

        bar = Bar(
            symbol="SPY",
            timeframe="1m",
            ts_utc=datetime(2024, 1, 2, 14, 30, tzinfo=timezone.utc),
            open=Decimal("470.0"),
            high=Decimal("470.5"),
            low=Decimal("469.9"),
            close=Decimal("470.2"),
            volume=12345,
        )
        evt = BarReceived(
            topic=TOPIC_BARS,
            emitted_at=datetime(2024, 1, 2, 14, 30, 5, tzinfo=timezone.utc),
            bar=bar,
        )
        assert evt.topic == "bars"
        assert evt.bar is bar

    def test_degraded_state_event_constructible(self):
        from datetime import datetime, timezone

        evt = DegradedStateEvent(
            topic=TOPIC_DEGRADED_STATE,
            emitted_at=datetime(2024, 1, 2, 14, 30, 5, tzinfo=timezone.utc),
            source="tradingview",
            reason="cdp disconnect",
        )
        assert evt.source == "tradingview"
        assert evt.reason == "cdp disconnect"


class TestTopicConstants:
    """The Final[str] topic constants are the bus's stable contract."""

    def test_topic_values(self):
        assert TOPIC_BARS == "bars"
        assert TOPIC_SIGNALS == "signals"
        assert TOPIC_RISK_DECISIONS == "risk_decisions"
        assert TOPIC_FILLS == "fills"
        assert TOPIC_POSITIONS == "positions"
        assert TOPIC_EQUITY == "equity"
        assert TOPIC_DEGRADED_STATE == "degraded_state"

    def test_topic_constants_are_strings(self):
        # `Final[str]` is a static annotation — runtime type is just `str`.
        for v in (
            TOPIC_BARS,
            TOPIC_SIGNALS,
            TOPIC_RISK_DECISIONS,
            TOPIC_FILLS,
            TOPIC_POSITIONS,
            TOPIC_EQUITY,
            TOPIC_DEGRADED_STATE,
        ):
            assert isinstance(v, str)


def test_final_str_annotation_present():
    """Sanity: the module-level Final[str] annotation is intact in events.models."""

    import trading_core.events.models as m

    anns = getattr(m, "__annotations__", {})
    # All seven topics must be annotated `Final[str]`.
    for name in (
        "TOPIC_BARS",
        "TOPIC_SIGNALS",
        "TOPIC_RISK_DECISIONS",
        "TOPIC_FILLS",
        "TOPIC_POSITIONS",
        "TOPIC_EQUITY",
        "TOPIC_DEGRADED_STATE",
    ):
        ann = anns.get(name)
        assert ann is not None, f"{name} missing module annotation"
        # The annotation is `Final[str]`; we check its string repr contains 'Final'.
        assert "Final" in str(ann), f"{name} annotation is {ann!r}, expected Final[str]"


# Pin the public re-export surface so downstream Plan 03 / 04 imports stay green.
_PUBLIC_SURFACE: Final[tuple[str, ...]] = (
    "Bar",
    "DataSource",
    "DataSourceError",
    "DataSourceUnavailable",
    "RateLimited",
    "GapDetected",
    "Strategy",
    "RiskManager",
    "Executor",
    "BarReceived",
    "DegradedStateEvent",
    "TOPIC_BARS",
    "TOPIC_SIGNALS",
    "TOPIC_RISK_DECISIONS",
    "TOPIC_FILLS",
    "TOPIC_POSITIONS",
    "TOPIC_EQUITY",
    "TOPIC_DEGRADED_STATE",
)


def test_public_surface_importable():
    """Smoke that every documented public name resolves through its package path."""

    # Re-import from data package
    from trading_core.data import Bar, DataSource  # noqa: F401
    from trading_core.data.protocols import (  # noqa: F401
        DataSourceError,
        DataSourceUnavailable,
        GapDetected,
        RateLimited,
    )
    from trading_core.events import (  # noqa: F401
        TOPIC_BARS,
        TOPIC_DEGRADED_STATE,
        TOPIC_EQUITY,
        TOPIC_FILLS,
        TOPIC_POSITIONS,
        TOPIC_RISK_DECISIONS,
        TOPIC_SIGNALS,
        BarReceived,
        DegradedStateEvent,
    )
    from trading_core.execution.protocols import Executor  # noqa: F401
    from trading_core.risk.protocols import RiskManager  # noqa: F401
    from trading_core.strategy.protocols import Strategy  # noqa: F401
