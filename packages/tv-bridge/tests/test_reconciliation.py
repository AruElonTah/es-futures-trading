"""Tests for run_reconciliation + ReconciliationScheduler (Plan 03, Task 2).

Converted from xfail-strict stubs to real tests.
Task IDs: 06-03-03, 06-03-04
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock

import pandas as pd
import pytest

from trading_core.config import Settings


def _make_spy_df(rows: list[dict]) -> pd.DataFrame:
    """Build a SPY 1m bar DataFrame in the format returned by DataSource.fetch_bars."""
    return pd.DataFrame(rows)


@pytest.mark.asyncio
async def test_price_divergence(in_memory_store) -> None:
    """Reconciliation detects >0.05% price divergence between TV SPY and Twelve SPY."""
    from tv_bridge.reconciliation import run_reconciliation

    trading_date = date(2026, 5, 19)
    ts1 = datetime(2026, 5, 19, 14, 30, tzinfo=timezone.utc)

    # Below threshold: (549.90 - 549.85) / 549.85 = ~0.009% — NO alert
    tv_df_no_alert = _make_spy_df([{
        "symbol": "SPY", "timeframe": "1m", "ts_utc": ts1,
        "open": 549.80, "high": 550.00, "low": 549.70, "close": 549.90,
        "volume": 1_000_000, "provider": "tradingview_mcp",
    }])
    twelve_df_no_alert = _make_spy_df([{
        "symbol": "SPY", "timeframe": "1m", "ts_utc": ts1,
        "open": 549.75, "high": 549.95, "low": 549.65, "close": 549.85,
        "volume": 1_050_000, "provider": "twelve_data",
    }])

    mock_tv = AsyncMock()
    mock_tv.fetch_bars.return_value = tv_df_no_alert
    mock_twelve = AsyncMock()
    mock_twelve.fetch_bars.return_value = twelve_df_no_alert

    count_no_alert = await run_reconciliation(
        tv_source=mock_tv,
        twelve_source=mock_twelve,
        store=in_memory_store,
        trading_date=trading_date,
    )
    assert count_no_alert == 0

    # Above threshold: (549.90 - 548.50) / 548.50 = ~0.255% — ALERT
    twelve_df_alert = _make_spy_df([{
        "symbol": "SPY", "timeframe": "1m", "ts_utc": ts1,
        "open": 548.40, "high": 548.60, "low": 548.30, "close": 548.50,
        "volume": 1_050_000, "provider": "twelve_data",
    }])

    mock_tv2 = AsyncMock()
    mock_tv2.fetch_bars.return_value = tv_df_no_alert
    mock_twelve2 = AsyncMock()
    mock_twelve2.fetch_bars.return_value = twelve_df_alert

    count_alert = await run_reconciliation(
        tv_source=mock_tv2,
        twelve_source=mock_twelve2,
        store=in_memory_store,
        trading_date=trading_date,
    )
    assert count_alert == 1

    # Verify audit_log row exists
    rows = in_memory_store._conn.execute(
        "SELECT topic, reason_code FROM audit_log WHERE topic = 'reconciliation_alert'"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0][1] == "price_divergence"


@pytest.mark.asyncio
async def test_audit_log_write(in_memory_store) -> None:
    """Reconciliation writes audit_log row with correct fields for volume divergence."""
    from tv_bridge.reconciliation import run_reconciliation

    trading_date = date(2026, 5, 19)
    ts1 = datetime(2026, 5, 19, 14, 31, tzinfo=timezone.utc)

    # Same price, volume divergence > 5%: TV=1_000_000, Twelve=1_100_000 → 10%
    tv_df = _make_spy_df([{
        "symbol": "SPY", "timeframe": "1m", "ts_utc": ts1,
        "open": 549.80, "high": 550.00, "low": 549.70, "close": 549.90,
        "volume": 1_000_000, "provider": "tradingview_mcp",
    }])
    twelve_df = _make_spy_df([{
        "symbol": "SPY", "timeframe": "1m", "ts_utc": ts1,
        "open": 549.80, "high": 550.00, "low": 549.70, "close": 549.90,
        "volume": 1_100_000, "provider": "twelve_data",
    }])

    mock_tv = AsyncMock()
    mock_tv.fetch_bars.return_value = tv_df
    mock_twelve = AsyncMock()
    mock_twelve.fetch_bars.return_value = twelve_df

    count = await run_reconciliation(
        tv_source=mock_tv,
        twelve_source=mock_twelve,
        store=in_memory_store,
        trading_date=trading_date,
    )
    assert count == 1

    row = in_memory_store._conn.execute(
        "SELECT topic, reason_code, payload_json FROM audit_log WHERE topic = 'reconciliation_alert'"
    ).fetchone()
    assert row is not None
    assert row[0] == "reconciliation_alert"
    assert row[1] == "volume_divergence"

    payload = json.loads(row[2])
    assert "ts" in payload
    assert "price_pct" in payload
    assert "vol_pct" in payload


@pytest.mark.asyncio
async def test_skipped_when_no_api_key(in_memory_store) -> None:
    """Reconciliation skips and writes reconciliation_skipped when a source is None."""
    from tv_bridge.reconciliation import run_reconciliation

    trading_date = date(2026, 5, 19)

    # tv_source=None → should skip
    count = await run_reconciliation(
        tv_source=None,
        twelve_source=AsyncMock(),
        store=in_memory_store,
        trading_date=trading_date,
    )
    assert count == 0

    rows = in_memory_store._conn.execute(
        "SELECT topic, reason_code FROM audit_log WHERE topic = 'reconciliation_skipped'"
    ).fetchall()
    assert len(rows) == 1

    # twelve_source=None → should also skip (new audit row)
    count2 = await run_reconciliation(
        tv_source=AsyncMock(),
        twelve_source=None,
        store=in_memory_store,
        trading_date=trading_date,
    )
    assert count2 == 0

    rows2 = in_memory_store._conn.execute(
        "SELECT topic, reason_code FROM audit_log WHERE topic = 'reconciliation_skipped'"
    ).fetchall()
    assert len(rows2) == 2
