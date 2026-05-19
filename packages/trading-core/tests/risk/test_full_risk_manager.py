"""TDD test suite for FullRiskManager — Phase 5 Plan 02.

Tests: RM-01..RM-08 + kill-switch gate (D-10) + _positions dict management.

Run with:
    uv run pytest packages/trading-core/tests/risk/test_full_risk_manager.py -x -v \
        --import-mode=importlib

RED phase: all tests import FullRiskManager which does not yet exist → CollectError
or ImportError. That is the expected RED failure mode for a brand-new module.
"""
from __future__ import annotations

import asyncio
from decimal import Decimal
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

import pytest

from trading_core.instruments import get as get_instrument
from trading_core.risk.models import DrawdownModel, RiskConfig, RiskDecision, RiskState
from trading_core.strategy.models import Signal

# --- SUT imports (will fail until GREEN) ---
from trading_core.risk.full_risk_manager import FullRiskManager, size_for_stop


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_signal(
    *,
    strategy_id: str = "orb_v1",
    side: str = "long",
    entry: Decimal = Decimal("4200.00"),
    stop: Decimal = Decimal("4195.00"),   # 5 points below entry
    target: Decimal = Decimal("4210.00"),
    size_hint: Decimal = Decimal("1"),
) -> Signal:
    """Factory for minimal valid Signal objects."""
    return Signal(
        strategy_id=strategy_id,
        strategy_version="1.0",
        ts_utc=datetime(2026, 5, 18, 14, 30, 0, tzinfo=timezone.utc),
        side=side,
        entry=entry,
        stop=stop,
        target=target,
        size_hint=size_hint,
    )


def _make_config(
    *,
    max_contracts: int = 10,  # high cap so sizing math is unclamped in most tests
    account_equity: Decimal = Decimal("50000"),
    max_risk_per_trade_pct: Decimal = Decimal("0.02"),  # 2% = $1000 risk at $50k
    daily_dd_limit: Decimal = Decimal("2000"),
    drawdown_model: DrawdownModel = DrawdownModel.TRAILING_INTRADAY,
) -> RiskConfig:
    return RiskConfig(
        max_contracts=max_contracts,
        account_equity=account_equity,
        max_risk_per_trade_pct=max_risk_per_trade_pct,
        daily_dd_limit=daily_dd_limit,
        drawdown_model=drawdown_model,
    )


def _make_state(
    *,
    realized_pnl_today: Decimal = Decimal("0"),
    open_exposure_dollars: Decimal = Decimal("0"),
) -> RiskState:
    return RiskState(
        realized_pnl_today=realized_pnl_today,
        open_exposure_dollars=open_exposure_dollars,
    )


MES = get_instrument("MES")
ES = get_instrument("ES")


# ---------------------------------------------------------------------------
# RM-01: size_for_stop pure function
# ---------------------------------------------------------------------------

class TestSizeForStop:
    """RM-01 — ATR-based sizing formula (pure function)."""

    def test_size_for_stop_mes(self) -> None:
        """Canonical proof: floor(1000 / (5 * 5.00)) = 40."""
        result = size_for_stop(
            risk_dollars=Decimal("1000"),
            stop_ticks=Decimal("5"),
            instrument=MES,
        )
        assert result == 40, f"Expected 40, got {result}"

    def test_size_for_stop_es(self) -> None:
        """Canonical proof: floor(1000 / (5 * 50.00)) = 4."""
        result = size_for_stop(
            risk_dollars=Decimal("1000"),
            stop_ticks=Decimal("5"),
            instrument=ES,
        )
        assert result == 4, f"Expected 4, got {result}"

    def test_size_for_stop_returns_int(self) -> None:
        result = size_for_stop(
            risk_dollars=Decimal("1000"),
            stop_ticks=Decimal("5"),
            instrument=MES,
        )
        assert isinstance(result, int)

    def test_size_for_stop_floors_fractional(self) -> None:
        """floor(1001 / 25) = floor(40.04) = 40."""
        result = size_for_stop(
            risk_dollars=Decimal("1001"),
            stop_ticks=Decimal("5"),
            instrument=MES,
        )
        assert result == 40

    def test_size_for_stop_single_contract(self) -> None:
        """floor(500 / (5 * 50)) = floor(2) = 2."""
        result = size_for_stop(
            risk_dollars=Decimal("500"),
            stop_ticks=Decimal("5"),
            instrument=ES,
        )
        assert result == 2


# ---------------------------------------------------------------------------
# RM-06: max_contracts cap
# ---------------------------------------------------------------------------

class TestMaxContractsCap:
    """RM-06 — cap applied in FullRiskManager.check(), not inside size_for_stop."""

    def test_max_contracts_cap_clamps_result(self) -> None:
        """With max_contracts=2 and huge risk_$, result must be capped to 2."""
        cfg = _make_config(max_contracts=2, account_equity=Decimal("5000000"))
        rm = FullRiskManager(config=cfg, symbol="MES")
        signal = _make_signal(entry=Decimal("4200"), stop=Decimal("4199"))  # 1-point stop
        state = _make_state()
        decision = asyncio.get_event_loop().run_until_complete(rm.check(signal, state))
        assert decision.approved is True
        assert decision.adjusted_size <= 2


# ---------------------------------------------------------------------------
# RM-02: all three DrawdownModel variants tracked side-by-side
# ---------------------------------------------------------------------------

class TestDrawdownModelVariants:
    """RM-02 — STATIC / TRAILING_EOD / TRAILING_INTRADAY all pass per-variant tests."""

    def test_drawdown_model_static_approves_valid_signal(self) -> None:
        cfg = _make_config(drawdown_model=DrawdownModel.STATIC)
        rm = FullRiskManager(config=cfg, symbol="MES")
        signal = _make_signal()
        state = _make_state()
        decision = asyncio.get_event_loop().run_until_complete(rm.check(signal, state))
        assert decision.approved is True

    def test_drawdown_model_trailing_eod_approves_valid_signal(self) -> None:
        cfg = _make_config(drawdown_model=DrawdownModel.TRAILING_EOD)
        rm = FullRiskManager(config=cfg, symbol="MES")
        signal = _make_signal()
        state = _make_state()
        decision = asyncio.get_event_loop().run_until_complete(rm.check(signal, state))
        assert decision.approved is True

    def test_drawdown_model_trailing_intraday_approves_valid_signal(self) -> None:
        cfg = _make_config(drawdown_model=DrawdownModel.TRAILING_INTRADAY)
        rm = FullRiskManager(config=cfg, symbol="MES")
        signal = _make_signal()
        state = _make_state()
        decision = asyncio.get_event_loop().run_until_complete(rm.check(signal, state))
        assert decision.approved is True

    def test_hwm_static_never_decreases(self) -> None:
        """STATIC HWM should not update even when equity rises intraday."""
        cfg = _make_config(drawdown_model=DrawdownModel.STATIC)
        rm = FullRiskManager(config=cfg, symbol="MES")
        initial_hwm = rm._hwm_static
        signal = _make_signal()
        # Simulate equity gain via positive open_exposure
        state = _make_state(open_exposure_dollars=Decimal("500"))
        asyncio.get_event_loop().run_until_complete(rm.check(signal, state))
        # STATIC hwm must remain at account_equity (never ratchets intraday)
        assert rm._hwm_static == initial_hwm

    def test_hwm_trailing_intraday_updates_on_check(self) -> None:
        """TRAILING_INTRADAY HWM should ratchet up when current equity exceeds prior HWM."""
        cfg = _make_config(drawdown_model=DrawdownModel.TRAILING_INTRADAY)
        rm = FullRiskManager(config=cfg, symbol="MES")
        initial_hwm = rm._hwm_trailing_intraday
        signal = _make_signal()
        # Simulate realized gains — current_equity = 50000 + 1000 = 51000
        state = _make_state(realized_pnl_today=Decimal("1000"))
        asyncio.get_event_loop().run_until_complete(rm.check(signal, state))
        # After check, HWM should have risen to reflect the gain
        assert rm._hwm_trailing_intraday > initial_hwm


# ---------------------------------------------------------------------------
# RM-03: worst_case_loss check → dd_floor_violation
# ---------------------------------------------------------------------------

class TestDDFloorViolation:
    """RM-03 — worst-case loss breaches active DD floor → rejected."""

    def test_dd_floor_violation_rejected(self) -> None:
        """Signal rejected when worst_case_loss > remaining buffer."""
        # Account: $50k, DD limit $2k → floor = $48k
        # Current equity = $48,001 (very close to floor)
        # Signal: entry=4200, stop=4195 (5 pts), size would be ~40 MES
        # worst_case = 5 * 5.00 * 40 = $1000 → current_equity - wc = 47001 < 48000 floor
        cfg = _make_config(
            max_contracts=40,
            account_equity=Decimal("50000"),
            daily_dd_limit=Decimal("2000"),
            drawdown_model=DrawdownModel.STATIC,
        )
        rm = FullRiskManager(config=cfg, symbol="MES")
        signal = _make_signal(entry=Decimal("4200"), stop=Decimal("4195"))
        # realized loss brings equity close to floor
        state = _make_state(realized_pnl_today=Decimal("-1999"))
        decision = asyncio.get_event_loop().run_until_complete(rm.check(signal, state))
        assert decision.approved is False
        assert decision.reason == "dd_floor_violation"
        assert decision.adjusted_size == 0

    def test_dd_floor_not_violated_when_safe(self) -> None:
        """Signal approved when worst_case_loss stays well within remaining buffer."""
        cfg = _make_config(
            max_contracts=1,
            account_equity=Decimal("50000"),
            daily_dd_limit=Decimal("2000"),
            drawdown_model=DrawdownModel.STATIC,
        )
        rm = FullRiskManager(config=cfg, symbol="MES")
        signal = _make_signal(entry=Decimal("4200"), stop=Decimal("4195"))
        state = _make_state(realized_pnl_today=Decimal("0"))
        decision = asyncio.get_event_loop().run_until_complete(rm.check(signal, state))
        assert decision.approved is True


# ---------------------------------------------------------------------------
# RM-04: daily-DD circuit breaker
# ---------------------------------------------------------------------------

class TestDailyDDBreaker:
    """RM-04 — realized + unrealized PnL at/below -daily_dd_limit → rejected."""

    def test_daily_dd_breaker_rejected(self) -> None:
        """Signal rejected when combined PnL ≤ -daily_dd_limit."""
        cfg = _make_config(daily_dd_limit=Decimal("2000"))
        rm = FullRiskManager(config=cfg, symbol="MES")
        signal = _make_signal()
        state = _make_state(
            realized_pnl_today=Decimal("-1500"),
            open_exposure_dollars=Decimal("-500"),
        )
        decision = asyncio.get_event_loop().run_until_complete(rm.check(signal, state))
        assert decision.approved is False
        assert decision.reason == "daily_dd_breaker"
        assert decision.adjusted_size == 0

    def test_daily_dd_breaker_at_exact_limit(self) -> None:
        """At exactly -daily_dd_limit, also rejected (RM-04 says <= not <)."""
        cfg = _make_config(daily_dd_limit=Decimal("2000"))
        rm = FullRiskManager(config=cfg, symbol="MES")
        signal = _make_signal()
        state = _make_state(
            realized_pnl_today=Decimal("-2000"),
            open_exposure_dollars=Decimal("0"),
        )
        decision = asyncio.get_event_loop().run_until_complete(rm.check(signal, state))
        assert decision.approved is False
        assert decision.reason == "daily_dd_breaker"

    def test_daily_dd_not_tripped_when_within_limit(self) -> None:
        """Signal approved when PnL is above -daily_dd_limit.

        RM-04 circuit breaker triggers at combined_pnl <= -daily_dd_limit.
        With realized_pnl = -1900 and open_exposure = 0, combined_pnl = -1900
        which is > -2000 so RM-04 does NOT trip.

        RM-03 (worst_case_loss) also passes: equity=48100, floor=48000,
        worst_case (1 MES contract, 5-pt stop) = 5*5*1 = $25.
        48100 - 25 = 48075 > 48000 → approved.
        """
        cfg = _make_config(daily_dd_limit=Decimal("2000"), max_contracts=1)
        rm = FullRiskManager(config=cfg, symbol="MES")
        signal = _make_signal()
        state = _make_state(realized_pnl_today=Decimal("-1900"))
        decision = asyncio.get_event_loop().run_until_complete(rm.check(signal, state))
        assert decision.approved is True


# ---------------------------------------------------------------------------
# D-10: asyncio.Event kill-switch gate
# ---------------------------------------------------------------------------

class TestKillSwitch:
    """D-10 — asyncio.Event kill-switch checked FIRST in check()."""

    def test_kill_switch_rejects_signal(self) -> None:
        """After set_killed('killed'), check() returns approved=False, reason='kill_switch_active'."""
        cfg = _make_config()
        rm = FullRiskManager(config=cfg, symbol="MES")
        rm.set_killed("killed")
        signal = _make_signal()
        state = _make_state()
        decision = asyncio.get_event_loop().run_until_complete(rm.check(signal, state))
        assert decision.approved is False
        assert decision.reason == "kill_switch_active"
        assert decision.adjusted_size == 0

    def test_kill_switch_clears_on_running(self) -> None:
        """set_killed('killed') then set_killed('running') → check() proceeds normally."""
        cfg = _make_config(max_contracts=1)
        rm = FullRiskManager(config=cfg, symbol="MES")
        rm.set_killed("killed")
        rm.set_killed("running")
        signal = _make_signal()
        state = _make_state()
        decision = asyncio.get_event_loop().run_until_complete(rm.check(signal, state))
        assert decision.approved is True

    def test_kill_switch_clears_on_paused(self) -> None:
        """set_killed('paused') clears the kill event (paused does not block new entries in same way)."""
        cfg = _make_config(max_contracts=1)
        rm = FullRiskManager(config=cfg, symbol="MES")
        rm.set_killed("killed")
        rm.set_killed("paused")
        assert not rm._kill_event.is_set()

    def test_kill_switch_unknown_state_ignored(self) -> None:
        """Unknown state is ignored (no exception, no state change)."""
        cfg = _make_config()
        rm = FullRiskManager(config=cfg, symbol="MES")
        rm.set_killed("unknown_state")  # Should not raise
        assert not rm._kill_event.is_set()

    def test_kill_switch_bootstrap_from_db(self) -> None:
        """mock store.get_engine_state() returning 'killed' → after load_kill_state_from_db, check() rejects."""
        cfg = _make_config()
        rm = FullRiskManager(config=cfg, symbol="MES")
        mock_store = MagicMock()
        mock_store.get_engine_state.return_value = "killed"
        rm.load_kill_state_from_db(mock_store)
        assert rm._kill_event.is_set()
        signal = _make_signal()
        state = _make_state()
        decision = asyncio.get_event_loop().run_until_complete(rm.check(signal, state))
        assert decision.approved is False
        assert decision.reason == "kill_switch_active"

    def test_kill_switch_bootstrap_running_does_not_set(self) -> None:
        """Bootstrap with 'running' does not set the kill event."""
        cfg = _make_config()
        rm = FullRiskManager(config=cfg, symbol="MES")
        mock_store = MagicMock()
        mock_store.get_engine_state.return_value = "running"
        rm.load_kill_state_from_db(mock_store)
        assert not rm._kill_event.is_set()


# ---------------------------------------------------------------------------
# RM-08: per-strategy concurrency cap
# ---------------------------------------------------------------------------

class TestConcurrencyCap:
    """RM-08 — 1 active position per strategy_id."""

    def test_concurrency_cap_rejected(self) -> None:
        """Second signal from same strategy_id while position is open → rejected."""
        cfg = _make_config(max_contracts=1)
        rm = FullRiskManager(config=cfg, symbol="MES")
        position_info = {
            "symbol": "MES",
            "strategy_id": "orb_v1",
            "side": "long",
            "qty": 1,
            "avg_fill": Decimal("4200"),
            "mark": Decimal("4201"),
            "stop": Decimal("4195"),
            "target": Decimal("4210"),
            "entry_ts_utc": datetime(2026, 5, 18, 14, 30, tzinfo=timezone.utc),
        }
        rm.record_position_open("orb_v1", position_info)
        signal = _make_signal(strategy_id="orb_v1")
        state = _make_state()
        decision = asyncio.get_event_loop().run_until_complete(rm.check(signal, state))
        assert decision.approved is False
        assert decision.reason == "concurrency_cap"
        assert decision.adjusted_size == 0

    def test_different_strategy_not_blocked(self) -> None:
        """Signal from different strategy_id is NOT blocked by another strategy's open position."""
        cfg = _make_config(max_contracts=1)
        rm = FullRiskManager(config=cfg, symbol="MES")
        position_info = {
            "symbol": "MES",
            "strategy_id": "orb_v1",
            "side": "long",
            "qty": 1,
            "avg_fill": Decimal("4200"),
            "mark": Decimal("4201"),
            "stop": Decimal("4195"),
            "target": Decimal("4210"),
            "entry_ts_utc": datetime(2026, 5, 18, 14, 30, tzinfo=timezone.utc),
        }
        rm.record_position_open("orb_v1", position_info)
        signal = _make_signal(strategy_id="orb_v2")  # different strategy
        state = _make_state()
        decision = asyncio.get_event_loop().run_until_complete(rm.check(signal, state))
        assert decision.approved is True

    def test_record_position_open_stores_metadata(self) -> None:
        """record_position_open stores full position info in _positions dict."""
        cfg = _make_config()
        rm = FullRiskManager(config=cfg, symbol="MES")
        position_info = {
            "symbol": "MES",
            "strategy_id": "orb_v1",
            "side": "long",
            "qty": 2,
            "avg_fill": Decimal("4200"),
            "mark": Decimal("4205"),
            "stop": Decimal("4195"),
            "target": Decimal("4215"),
            "entry_ts_utc": datetime(2026, 5, 18, 14, 30, tzinfo=timezone.utc),
        }
        rm.record_position_open("orb_v1", position_info)
        assert "orb_v1" in rm._positions
        assert rm._positions["orb_v1"] == position_info

    def test_concurrency_cap_uses_positions_dict(self) -> None:
        """Verify concurrency cap uses _positions dict keys (not other state)."""
        cfg = _make_config(max_contracts=1)
        rm = FullRiskManager(config=cfg, symbol="MES")
        # Open position via record_position_open
        rm.record_position_open("orb_v1", {
            "symbol": "MES", "strategy_id": "orb_v1", "side": "long", "qty": 1,
            "avg_fill": Decimal("4200"), "mark": Decimal("4201"),
            "stop": Decimal("4195"), "target": Decimal("4210"),
            "entry_ts_utc": datetime(2026, 5, 18, 14, 30, tzinfo=timezone.utc),
        })
        assert "orb_v1" in rm._positions
        signal = _make_signal(strategy_id="orb_v1")
        state = _make_state()
        decision = asyncio.get_event_loop().run_until_complete(rm.check(signal, state))
        assert decision.reason == "concurrency_cap"

    def test_record_position_closed_removes_entry(self) -> None:
        """record_position_closed removes the strategy_id from _positions."""
        cfg = _make_config()
        rm = FullRiskManager(config=cfg, symbol="MES")
        rm.record_position_open("orb_v1", {
            "symbol": "MES", "strategy_id": "orb_v1", "side": "long", "qty": 1,
            "avg_fill": Decimal("4200"), "mark": Decimal("4201"),
            "stop": Decimal("4195"), "target": Decimal("4210"),
            "entry_ts_utc": datetime(2026, 5, 18, 14, 30, tzinfo=timezone.utc),
        })
        rm.record_position_closed("orb_v1")
        assert "orb_v1" not in rm._positions
        assert rm._positions == {}

    def test_record_position_closed_noop_if_not_present(self) -> None:
        """record_position_closed is a no-op if strategy_id not in _positions."""
        cfg = _make_config()
        rm = FullRiskManager(config=cfg, symbol="MES")
        rm.record_position_closed("non_existent_strategy")  # Should not raise
        assert rm._positions == {}


# ---------------------------------------------------------------------------
# Happy path: approved signal
# ---------------------------------------------------------------------------

class TestApprovedSignal:
    """Full happy path — signal passes all checks → approved=True."""

    def test_approved_signal_returns_adjusted_size(self) -> None:
        """Approved signal returns RiskDecision with correct adjusted_size."""
        # risk_$ = 50000 * 0.02 = 1000
        # stop = 5 pts, MES → size_for_stop(1000, 5, MES) = 40
        # capped at max_contracts=40
        cfg = _make_config(max_contracts=40, max_risk_per_trade_pct=Decimal("0.02"))
        rm = FullRiskManager(config=cfg, symbol="MES")
        signal = _make_signal(entry=Decimal("4200"), stop=Decimal("4195"))  # 5-pt stop
        state = _make_state()
        decision = asyncio.get_event_loop().run_until_complete(rm.check(signal, state))
        assert decision.approved is True
        assert decision.reason == "approved"
        assert decision.adjusted_size == 40

    def test_approved_signal_respects_max_contracts_cap(self) -> None:
        """Approved signal is capped at max_contracts even when sizing math gives more."""
        cfg = _make_config(max_contracts=2, max_risk_per_trade_pct=Decimal("0.02"))
        rm = FullRiskManager(config=cfg, symbol="MES")
        signal = _make_signal(entry=Decimal("4200"), stop=Decimal("4195"))
        state = _make_state()
        decision = asyncio.get_event_loop().run_until_complete(rm.check(signal, state))
        assert decision.approved is True
        assert decision.adjusted_size == 2

    def test_approved_signal_returns_risk_decision_type(self) -> None:
        """check() return type is RiskDecision."""
        cfg = _make_config(max_contracts=1)
        rm = FullRiskManager(config=cfg, symbol="MES")
        signal = _make_signal()
        state = _make_state()
        decision = asyncio.get_event_loop().run_until_complete(rm.check(signal, state))
        assert isinstance(decision, RiskDecision)


# ---------------------------------------------------------------------------
# DuckDB persist order (SP-03)
# ---------------------------------------------------------------------------

class TestDuckDBPersistOrder:
    """SP-03 — DuckDB writes happen BEFORE check() returns."""

    def test_write_risk_state_called_before_return(self) -> None:
        """write_risk_state() is called for approved signals."""
        mock_store = MagicMock()
        cfg = _make_config(max_contracts=1)
        rm = FullRiskManager(config=cfg, store=mock_store, symbol="MES")
        signal = _make_signal()
        state = _make_state()
        asyncio.get_event_loop().run_until_complete(rm.check(signal, state))
        assert mock_store.write_risk_state.called

    def test_write_audit_event_called_before_return(self) -> None:
        """write_audit_event() is called for every check() result."""
        mock_store = MagicMock()
        cfg = _make_config(max_contracts=1)
        rm = FullRiskManager(config=cfg, store=mock_store, symbol="MES")
        signal = _make_signal()
        state = _make_state()
        asyncio.get_event_loop().run_until_complete(rm.check(signal, state))
        assert mock_store.write_audit_event.called

    def test_write_called_on_rejection_too(self) -> None:
        """DuckDB writes happen even when signal is rejected (daily_dd_breaker)."""
        mock_store = MagicMock()
        cfg = _make_config(daily_dd_limit=Decimal("2000"))
        rm = FullRiskManager(config=cfg, store=mock_store, symbol="MES")
        signal = _make_signal()
        state = _make_state(
            realized_pnl_today=Decimal("-2000"),
            open_exposure_dollars=Decimal("0"),
        )
        asyncio.get_event_loop().run_until_complete(rm.check(signal, state))
        assert mock_store.write_audit_event.called

    def test_write_not_called_when_store_is_none(self) -> None:
        """When store=None (unit test mode), no AttributeError raised."""
        cfg = _make_config(max_contracts=1)
        rm = FullRiskManager(config=cfg, store=None, symbol="MES")
        signal = _make_signal()
        state = _make_state()
        # Should not raise
        decision = asyncio.get_event_loop().run_until_complete(rm.check(signal, state))
        assert isinstance(decision, RiskDecision)


# ---------------------------------------------------------------------------
# __init__.py export check
# ---------------------------------------------------------------------------

class TestRiskPackageExports:
    """Verify FullRiskManager is exported from trading_core.risk."""

    def test_full_risk_manager_importable_from_risk_package(self) -> None:
        from trading_core.risk import FullRiskManager as FRM  # noqa: F401
        assert FRM is FullRiskManager
