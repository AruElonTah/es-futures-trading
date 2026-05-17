"""Tests for PassThroughRiskManager — BT-03 / D-10.

PassThroughRiskManager always approves and clamps adjusted_size to
RiskConfig.max_contracts. Phase 5 replaces it with prop-firm-style checks.

This file replaces the Wave 0 xfail stub (if any); new for Plan 02.
"""

from __future__ import annotations

from decimal import Decimal
from datetime import datetime, timezone

import pytest

from trading_core.risk.models import RiskConfig, RiskState
from trading_core.risk.pass_through import PassThroughRiskManager
from trading_core.strategy.models import Signal


def _make_signal(size_hint: Decimal = Decimal("1")) -> Signal:
    """Build a minimal valid Signal for testing."""
    return Signal(
        strategy_id="orb-v1",
        strategy_version="1.0",
        ts_utc=datetime(2024, 1, 2, 14, 30, tzinfo=timezone.utc),
        side="long",
        entry=Decimal("471.00"),
        stop=Decimal("470.00"),
        target=Decimal("473.00"),
        size_hint=size_hint,
    )


class TestPassThroughAlwaysApproves:
    def test_approved_is_true(self):
        """check() always returns approved=True."""
        manager = PassThroughRiskManager(config=RiskConfig(max_contracts=1))
        signal = _make_signal()
        state = RiskState()
        # asyncio_mode = "auto" in pyproject.toml — tests are auto-awaited

    async def test_approved_is_true_async(self):
        """check() is awaitable and returns approved=True."""
        manager = PassThroughRiskManager(config=RiskConfig(max_contracts=1))
        signal = _make_signal()
        state = RiskState()
        decision = await manager.check(signal, state)
        assert decision.approved is True

    async def test_reason_is_pass_through(self):
        """check() returns reason='pass_through'."""
        manager = PassThroughRiskManager(config=RiskConfig(max_contracts=1))
        signal = _make_signal()
        state = RiskState()
        decision = await manager.check(signal, state)
        assert decision.reason == "pass_through"


class TestPassThroughSizeClamping:
    async def test_size_hint_5_clamped_to_1_with_max_1(self):
        """adjusted_size = min(5, 1) = 1 when max_contracts=1."""
        manager = PassThroughRiskManager(config=RiskConfig(max_contracts=1))
        signal = _make_signal(size_hint=Decimal("5"))
        state = RiskState()
        decision = await manager.check(signal, state)
        assert decision.adjusted_size == 1

    async def test_size_hint_2_with_max_3_gives_2(self):
        """adjusted_size = min(2, 3) = 2 when max_contracts=3."""
        manager = PassThroughRiskManager(config=RiskConfig(max_contracts=3))
        signal = _make_signal(size_hint=Decimal("2"))
        state = RiskState()
        decision = await manager.check(signal, state)
        assert decision.adjusted_size == 2

    async def test_approved_regardless_of_pnl_today(self):
        """approved=True even when realized_pnl_today is deeply negative (Phase 3 invariant)."""
        manager = PassThroughRiskManager(config=RiskConfig(max_contracts=1))
        signal = _make_signal()
        state = RiskState(realized_pnl_today=Decimal("-9999.99"))
        decision = await manager.check(signal, state)
        assert decision.approved is True

    async def test_check_is_awaitable(self):
        """check() satisfies the RiskManager Protocol (async def)."""
        import inspect
        manager = PassThroughRiskManager(config=RiskConfig(max_contracts=1))
        assert inspect.iscoroutinefunction(manager.check), (
            "PassThroughRiskManager.check must be async def to satisfy RiskManager Protocol"
        )
