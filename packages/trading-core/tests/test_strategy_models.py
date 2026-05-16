"""Tests for Signal + StrategyContext Pydantic v2 models (Plan 02-01 Task 1)."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from trading_core.strategy.models import Signal, StrategyContext

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

UTC = timezone.utc
_TS = datetime(2024, 1, 2, 14, 30, tzinfo=UTC)  # 09:30 ET on 2024-01-02


def _signal(**kwargs):
    defaults = dict(
        strategy_id="orb-v1",
        strategy_version="1.0",
        ts_utc=_TS,
        side="long",
        entry=Decimal("471.25"),
        stop=Decimal("470.50"),
        target=Decimal("472.75"),
        size_hint=Decimal("1"),
    )
    defaults.update(kwargs)
    return Signal(**defaults)


def _ctx(**kwargs):
    defaults = dict(
        rollover_seam=False,
        warmup_complete=True,
        bar_index=15,
        ts_utc=_TS,
        atr=Decimal("0.75"),
        session_vwap=Decimal("470.80"),
        ema=Decimal("470.60"),
        adr=None,
    )
    defaults.update(kwargs)
    return StrategyContext(**defaults)


# ---------------------------------------------------------------------------
# Signal construction
# ---------------------------------------------------------------------------


def test_signal_constructs_successfully():
    s = _signal()
    assert s.strategy_id == "orb-v1"
    assert s.strategy_version == "1.0"
    assert s.side == "long"
    assert s.entry == Decimal("471.25")
    assert s.stop == Decimal("470.50")
    assert s.target == Decimal("472.75")
    assert s.size_hint == Decimal("1")
    assert isinstance(s.signal_id, str)
    assert len(s.signal_id) > 0


def test_signal_auto_generates_signal_id():
    s1 = _signal()
    s2 = _signal()
    assert s1.signal_id != s2.signal_id


def test_signal_accepts_explicit_signal_id():
    s = _signal(signal_id="custom-id-123")
    assert s.signal_id == "custom-id-123"


def test_signal_ts_utc_rejects_naive():
    naive = datetime(2024, 1, 2, 14, 30)  # no tzinfo
    with pytest.raises(ValidationError):
        _signal(ts_utc=naive)


def test_signal_ts_utc_rejects_non_utc():
    eastern = datetime(2024, 1, 2, 9, 30, tzinfo=timezone(timedelta(hours=-5)))
    with pytest.raises(ValidationError):
        _signal(ts_utc=eastern)


@pytest.mark.parametrize("side", ["long", "short"])
def test_signal_side_valid(side):
    s = _signal(side=side)
    assert s.side == side


def test_signal_side_rejects_invalid():
    with pytest.raises(ValidationError):
        _signal(side="buy")


@pytest.mark.parametrize("field", ["entry", "stop", "target", "size_hint"])
def test_signal_price_field_must_be_positive(field):
    with pytest.raises(ValidationError):
        _signal(**{field: Decimal("0")})
    with pytest.raises(ValidationError):
        _signal(**{field: Decimal("-1")})


def test_signal_is_frozen():
    s = _signal()
    with pytest.raises((ValidationError, TypeError)):
        s.side = "short"  # type: ignore[misc]


def test_signal_extra_fields_forbidden():
    with pytest.raises(ValidationError):
        Signal(
            strategy_id="orb-v1",
            strategy_version="1.0",
            ts_utc=_TS,
            side="long",
            entry=Decimal("471.25"),
            stop=Decimal("470.50"),
            target=Decimal("472.75"),
            size_hint=Decimal("1"),
            extra_field="x",
        )


# ---------------------------------------------------------------------------
# StrategyContext construction
# ---------------------------------------------------------------------------


def test_ctx_constructs_successfully():
    ctx = _ctx()
    assert ctx.rollover_seam is False
    assert ctx.warmup_complete is True
    assert ctx.bar_index == 15
    assert ctx.atr == Decimal("0.75")
    assert ctx.session_vwap == Decimal("470.80")
    assert ctx.ema == Decimal("470.60")
    assert ctx.adr is None


def test_ctx_all_indicators_none():
    ctx = _ctx(
        warmup_complete=False,
        atr=None,
        session_vwap=None,
        ema=None,
        adr=None,
    )
    assert ctx.atr is None
    assert ctx.session_vwap is None
    assert ctx.ema is None
    assert ctx.adr is None


def test_ctx_is_frozen():
    ctx = _ctx()
    with pytest.raises((ValidationError, TypeError)):
        ctx.warmup_complete = False  # type: ignore[misc]


def test_ctx_extra_fields_forbidden():
    with pytest.raises(ValidationError):
        StrategyContext(
            rollover_seam=False,
            warmup_complete=True,
            bar_index=0,
            ts_utc=_TS,
            extra_field="x",
        )
