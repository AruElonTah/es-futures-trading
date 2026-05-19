"""Phase 5 tests for DrawdownModel enum + RiskConfig/RiskState extensions.

Tests:
- DrawdownModel enum values and str coercion
- RiskConfig backward compat (default max_contracts=1 still works)
- RiskConfig with all Phase 5 fields validates correctly
- RiskState backward compat (default realized_pnl_today=Decimal("0") still works)
- RiskState with all Phase 5 fields validates correctly
- RiskConfig extra field raises ValidationError

Run with: uv run pytest packages/trading-core/tests/risk/test_models_phase5.py -x -q --import-mode=importlib
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from trading_core.risk.models import DrawdownModel, RiskConfig, RiskDecision, RiskState


class TestDrawdownModel:
    """DrawdownModel enum — string coercion + enum identity."""

    def test_static_value(self) -> None:
        assert DrawdownModel("STATIC") == DrawdownModel.STATIC

    def test_trailing_eod_value(self) -> None:
        assert DrawdownModel("TRAILING_EOD") == DrawdownModel.TRAILING_EOD

    def test_trailing_intraday_value(self) -> None:
        assert DrawdownModel("TRAILING_INTRADAY") == DrawdownModel.TRAILING_INTRADAY

    def test_str_coercion_returns_str(self) -> None:
        """DrawdownModel(str, Enum) should behave as a str."""
        dm = DrawdownModel.STATIC
        assert str(dm) == "STATIC"

    def test_invalid_value_raises(self) -> None:
        with pytest.raises(ValueError):
            DrawdownModel("INVALID_MODEL")


class TestRiskConfigBackwardCompat:
    """RiskConfig — Phase 3 backward compatibility."""

    def test_default_max_contracts(self) -> None:
        """RiskConfig() still works with no args — backward compat."""
        cfg = RiskConfig()
        assert cfg.max_contracts == 1

    def test_extra_field_raises_validation_error(self) -> None:
        """extra='forbid' preserved — unknown fields rejected."""
        with pytest.raises(ValidationError):
            RiskConfig(max_contracts=1, unknown_field="bad")  # type: ignore[call-arg]


class TestRiskConfigPhase5Fields:
    """RiskConfig — Phase 5 extended fields."""

    def test_full_phase5_config_validates(self) -> None:
        cfg = RiskConfig(
            max_contracts=2,
            account_equity=Decimal("50000"),
            max_risk_per_trade_pct=Decimal("0.01"),
            daily_dd_limit=Decimal("2000"),
            drawdown_model=DrawdownModel.TRAILING_INTRADAY,
        )
        assert cfg.max_contracts == 2
        assert cfg.account_equity == Decimal("50000")
        assert cfg.max_risk_per_trade_pct == Decimal("0.01")
        assert cfg.daily_dd_limit == Decimal("2000")
        assert cfg.drawdown_model == DrawdownModel.TRAILING_INTRADAY

    def test_account_equity_default(self) -> None:
        cfg = RiskConfig()
        assert cfg.account_equity == Decimal("50000")

    def test_max_risk_per_trade_pct_default(self) -> None:
        cfg = RiskConfig()
        assert cfg.max_risk_per_trade_pct == Decimal("0.01")

    def test_daily_dd_limit_default(self) -> None:
        cfg = RiskConfig()
        assert cfg.daily_dd_limit == Decimal("2000")

    def test_drawdown_model_default(self) -> None:
        cfg = RiskConfig()
        assert cfg.drawdown_model == DrawdownModel.TRAILING_INTRADAY

    def test_drawdown_model_str_coercion_from_yaml(self) -> None:
        """DrawdownModel field accepts plain string (YAML-loaded value)."""
        cfg = RiskConfig(drawdown_model="STATIC")  # type: ignore[arg-type]
        assert cfg.drawdown_model == DrawdownModel.STATIC


class TestRiskStateBackwardCompat:
    """RiskState — Phase 3 backward compatibility."""

    def test_default_realized_pnl_today(self) -> None:
        """RiskState() still works with no args — backward compat."""
        state = RiskState()
        assert state.realized_pnl_today == Decimal("0")


class TestRiskStatePhase5Fields:
    """RiskState — Phase 5 extended fields."""

    def test_full_phase5_state_validates(self) -> None:
        state = RiskState(
            realized_pnl_today=Decimal("0"),
            equity_high_water=Decimal("50000"),
            open_exposure_dollars=Decimal("0"),
            drawdown_model=DrawdownModel.TRAILING_INTRADAY,
        )
        assert state.equity_high_water == Decimal("50000")
        assert state.open_exposure_dollars == Decimal("0")
        assert state.drawdown_model == DrawdownModel.TRAILING_INTRADAY

    def test_equity_high_water_default(self) -> None:
        state = RiskState()
        assert state.equity_high_water == Decimal("0")

    def test_open_exposure_dollars_default(self) -> None:
        state = RiskState()
        assert state.open_exposure_dollars == Decimal("0")

    def test_drawdown_model_default(self) -> None:
        state = RiskState()
        assert state.drawdown_model == DrawdownModel.TRAILING_INTRADAY


class TestRiskDecisionUnchanged:
    """RiskDecision — unchanged from Phase 3, verify it still works."""

    def test_risk_decision_requires_all_fields(self) -> None:
        decision = RiskDecision(approved=True, reason="pass", adjusted_size=2)
        assert decision.approved is True
        assert decision.reason == "pass"
        assert decision.adjusted_size == 2

    def test_risk_decision_extra_field_raises(self) -> None:
        with pytest.raises(ValidationError):
            RiskDecision(approved=True, reason="pass", adjusted_size=2, extra="bad")  # type: ignore[call-arg]
