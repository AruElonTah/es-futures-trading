"""Tests for Phase 3 D-10 minimal fields on Fill, RiskDecision, RiskState, RiskConfig.

Covers:
  - Fill: all seven fields, Literal guards, AwareDatetime + UTC validator, frozen, extra forbid
  - RiskDecision: three required fields, no defaults
  - RiskState: realized_pnl_today default Decimal("0")
  - RiskConfig: max_contracts default 1

Phase 3 plan 03-01.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError


# ---- Fill tests ----------------------------------------------------------

def _utc_dt():
    """Helper: 2024-01-02 14:30 UTC as timezone-aware datetime."""
    return datetime.datetime(2024, 1, 2, 14, 30, tzinfo=datetime.timezone.utc)


def _ny_dt():
    """Helper: 2024-01-02 09:30 America/New_York (offset -05:00)."""
    from zoneinfo import ZoneInfo
    return datetime.datetime(2024, 1, 2, 9, 30, tzinfo=ZoneInfo("America/New_York"))


class TestFillConstruction:
    def test_valid_fill_succeeds(self):
        from trading_core.execution.models import Fill

        f = Fill(
            signal_id="s1",
            fill_price=Decimal("471.50"),
            fill_qty=1,
            side="long",
            slippage_ticks=1,
            ts_utc=_utc_dt(),
            exit_reason="target",
        )
        assert f.signal_id == "s1"
        assert f.fill_price == Decimal("471.50")
        assert f.fill_qty == 1
        assert f.side == "long"
        assert f.slippage_ticks == 1
        assert f.exit_reason == "target"

    def test_valid_fill_short_side(self):
        from trading_core.execution.models import Fill

        f = Fill(
            signal_id="s2",
            fill_price=Decimal("471.50"),
            fill_qty=2,
            side="short",
            slippage_ticks=0,
            ts_utc=_utc_dt(),
            exit_reason="stop",
        )
        assert f.side == "short"

    def test_valid_fill_all_exit_reasons(self):
        from trading_core.execution.models import Fill

        for reason in ("target", "stop", "eod_flat", "manual"):
            f = Fill(
                signal_id="s3",
                fill_price=Decimal("471.50"),
                fill_qty=1,
                side="long",
                slippage_ticks=0,
                ts_utc=_utc_dt(),
                exit_reason=reason,
            )
            assert f.exit_reason == reason


class TestFillValidation:
    def test_invalid_side_raises(self):
        from trading_core.execution.models import Fill

        with pytest.raises(ValidationError):
            Fill(
                signal_id="s1",
                fill_price=Decimal("471.50"),
                fill_qty=1,
                side="diagonal",
                slippage_ticks=0,
                ts_utc=_utc_dt(),
                exit_reason="target",
            )

    def test_invalid_exit_reason_raises(self):
        from trading_core.execution.models import Fill

        with pytest.raises(ValidationError):
            Fill(
                signal_id="s1",
                fill_price=Decimal("471.50"),
                fill_qty=1,
                side="long",
                slippage_ticks=0,
                ts_utc=_utc_dt(),
                exit_reason="liquidated",
            )

    def test_naive_ts_utc_raises(self):
        from trading_core.execution.models import Fill

        with pytest.raises(ValidationError):
            Fill(
                signal_id="s1",
                fill_price=Decimal("471.50"),
                fill_qty=1,
                side="long",
                slippage_ticks=0,
                ts_utc=datetime.datetime(2024, 1, 2, 14, 30),  # naive
                exit_reason="target",
            )

    def test_non_utc_offset_ts_utc_raises(self):
        from trading_core.execution.models import Fill

        with pytest.raises(ValidationError):
            Fill(
                signal_id="s1",
                fill_price=Decimal("471.50"),
                fill_qty=1,
                side="long",
                slippage_ticks=0,
                ts_utc=_ny_dt(),  # America/New_York offset, not UTC
                exit_reason="target",
            )

    def test_zero_fill_price_raises(self):
        from trading_core.execution.models import Fill

        with pytest.raises(ValidationError):
            Fill(
                signal_id="s1",
                fill_price=Decimal("0"),
                fill_qty=1,
                side="long",
                slippage_ticks=0,
                ts_utc=_utc_dt(),
                exit_reason="target",
            )

    def test_zero_fill_qty_raises(self):
        from trading_core.execution.models import Fill

        with pytest.raises(ValidationError):
            Fill(
                signal_id="s1",
                fill_price=Decimal("471.50"),
                fill_qty=0,
                side="long",
                slippage_ticks=0,
                ts_utc=_utc_dt(),
                exit_reason="target",
            )

    def test_fill_is_frozen(self):
        from trading_core.execution.models import Fill

        f = Fill(
            signal_id="s1",
            fill_price=Decimal("471.50"),
            fill_qty=1,
            side="long",
            slippage_ticks=0,
            ts_utc=_utc_dt(),
            exit_reason="target",
        )
        with pytest.raises((ValidationError, TypeError)):
            f.fill_price = Decimal("999.99")  # type: ignore[misc]

    def test_fill_rejects_extra_fields(self):
        from trading_core.execution.models import Fill

        with pytest.raises(ValidationError):
            Fill(
                signal_id="s1",
                fill_price=Decimal("471.50"),
                fill_qty=1,
                side="long",
                slippage_ticks=0,
                ts_utc=_utc_dt(),
                exit_reason="target",
                commission_usd=1.25,  # not a declared field
            )


# ---- RiskDecision tests --------------------------------------------------

class TestRiskDecision:
    def test_valid_risk_decision_succeeds(self):
        from trading_core.risk.models import RiskDecision

        rd = RiskDecision(approved=True, reason="pass_through", adjusted_size=1)
        assert rd.approved is True
        assert rd.reason == "pass_through"
        assert rd.adjusted_size == 1

    def test_risk_decision_approved_false(self):
        from trading_core.risk.models import RiskDecision

        rd = RiskDecision(approved=False, reason="daily_dd_hit", adjusted_size=0)
        assert rd.approved is False

    def test_risk_decision_missing_required_field_raises(self):
        from trading_core.risk.models import RiskDecision

        with pytest.raises(ValidationError):
            RiskDecision(approved=True, reason="pass_through")  # missing adjusted_size


# ---- RiskState tests -----------------------------------------------------

class TestRiskState:
    def test_default_realized_pnl_today(self):
        from trading_core.risk.models import RiskState

        rs = RiskState()
        assert rs.realized_pnl_today == Decimal("0")

    def test_custom_realized_pnl_today(self):
        from trading_core.risk.models import RiskState

        rs = RiskState(realized_pnl_today=Decimal("123.45"))
        assert rs.realized_pnl_today == Decimal("123.45")


# ---- RiskConfig tests ----------------------------------------------------

class TestRiskConfig:
    def test_default_max_contracts(self):
        from trading_core.risk.models import RiskConfig

        rc = RiskConfig()
        assert rc.max_contracts == 1

    def test_custom_max_contracts(self):
        from trading_core.risk.models import RiskConfig

        rc = RiskConfig(max_contracts=2)
        assert rc.max_contracts == 2

    def test_risk_config_rejects_extra_fields(self):
        from trading_core.risk.models import RiskConfig

        # Phase 3 used `daily_dd_limit` as the "extra field" sentinel, but Phase 5
        # legitimately adds that field. Use a genuinely unknown field instead.
        with pytest.raises(ValidationError):
            RiskConfig(max_contracts=1, unknown_phase3_field=500)  # type: ignore[call-arg]
