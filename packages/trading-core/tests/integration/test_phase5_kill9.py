"""Phase 5 integration tests — kill-9 HWM survival + DrawdownModel per-variant.

ROADMAP cross-phase guardrail: "Phase 5 must not exit without the
HWM-survives-kill-9 integration test green."

Tests:
1. test_hwm_survives_kill9 — Subprocess writes risk_state + audit_log rows
   then is killed (proc.kill() = TerminateProcess on Windows). Verifies rows
   committed to DuckDB before kill survive after process death. Also verifies
   HWM can be restored via load_hwm_from_db() on a fresh manager.

2. test_static_hwm_never_decreases — STATIC model: HWM stays at starting
   value even when equity dips below it.

3. test_trailing_eod_hwm_only_updates_at_close — TRAILING_EOD: HWM only
   ratchets via update_eod_hwm(), not during check().

4. test_trailing_intraday_hwm_updates_on_every_tick — TRAILING_INTRADAY: HWM
   advances to track equity highs on every check() call.

Run with:
    uv run pytest packages/trading-core/tests/integration/test_phase5_kill9.py \
        -x -v --import-mode=importlib

Note: The kill-9 test uses proc.kill() which maps to TerminateProcess on
Windows (the platform this project runs on) — equivalent to SIGKILL on POSIX.
"""
from __future__ import annotations

import asyncio
import sys
import time
from decimal import Decimal
from datetime import datetime, timezone
from pathlib import Path

import pytest

from trading_core.risk.models import DrawdownModel, RiskConfig, RiskState
from trading_core.risk.full_risk_manager import FullRiskManager
from trading_core.storage.duckdb_store import DuckDBStore
from trading_core.storage.runs import new_run_id

# Absolute path to the trading-core src directory.
# This file is at: packages/trading-core/tests/integration/test_phase5_kill9.py
# 3 levels up = packages/trading-core/ ; then + 'src' = packages/trading-core/src
_TRADING_CORE_SRC = str(Path(__file__).parent.parent.parent / "src")


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------

def _make_config(
    *,
    account_equity: Decimal = Decimal("50000"),
    daily_dd_limit: Decimal = Decimal("2000"),
    drawdown_model: DrawdownModel = DrawdownModel.TRAILING_INTRADAY,
    max_contracts: int = 2,
) -> RiskConfig:
    return RiskConfig(
        account_equity=account_equity,
        max_risk_per_trade_pct=Decimal("0.01"),
        daily_dd_limit=daily_dd_limit,
        drawdown_model=drawdown_model,
        max_contracts=max_contracts,
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


# ---------------------------------------------------------------------------
# Test 1: kill-9 HWM survival
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_hwm_survives_kill9(tmp_path):
    """Audit log and risk_state rows committed before kill survive process death.

    The subprocess:
      1. Opens a DuckDBStore at a known temp path.
      2. Calls write_risk_state() with a known equity_dollars value.
      3. Calls write_audit_event() with a known event_id.
      4. Is killed via proc.kill() (TerminateProcess on Windows).

    After the subprocess is killed, this test:
      1. Opens the same DuckDB file on a fresh connection.
      2. Asserts risk_state row exists with the expected equity_dollars.
      3. Asserts audit_log row exists with the expected event_id.
      4. Creates a fresh FullRiskManager and calls load_hwm_from_db() using the
         date that was written — asserts loaded HWM matches the written value.
    """
    db_path = tmp_path / "test_kill9.duckdb"
    known_equity = "51234.56"
    known_event_id = new_run_id()

    # Write the subprocess script as a Python file
    script_path = tmp_path / "kill9_writer.py"

    # Build the script content with exact string interpolation (no f-string
    # trickery with nested braces; use separate variables for clarity)
    db_path_repr = repr(str(db_path))
    src_path_repr = repr(_TRADING_CORE_SRC)
    event_id_repr = repr(known_event_id)
    equity_repr = repr(known_equity)

    script_lines = [
        "import sys",
        "import os",
        "import time",
        "from pathlib import Path",
        "from datetime import datetime, timezone",
        "from decimal import Decimal",
        "",
        f"sys.path.insert(0, {src_path_repr})",
        "",
        "from trading_core.storage.duckdb_store import DuckDBStore",
        "from trading_core.storage.runs import new_run_id",
        "",
        f"db_path = Path({db_path_repr})",
        "store = DuckDBStore(db_path)",
        "store.ensure_schema()",
        "",
        "# Write a risk_state row with a known equity value",
        "store.write_risk_state({",
        "    'id': new_run_id(),",
        "    'ts_utc': datetime(2026, 5, 18, 20, 0, 0, tzinfo=timezone.utc),",
        "    'date': '2026-05-18',",
        "    'session_id': new_run_id(),",
        f"    'equity_dollars': Decimal({equity_repr}),",
        "    'realized_pnl_dollars': Decimal('1234.56'),",
        "    'open_exposure_dollars': Decimal('0'),",
        f"    'hwm_static': Decimal({equity_repr}),",
        "    'floor_static': Decimal('49234.56'),",
        f"    'hwm_trailing_eod': Decimal({equity_repr}),",
        "    'floor_trailing_eod': Decimal('49234.56'),",
        f"    'hwm_trailing_intraday': Decimal({equity_repr}),",
        "    'floor_trailing_intraday': Decimal('49234.56'),",
        "})",
        "",
        "# Write an audit_log row with a known event_id",
        "store.write_audit_event(",
        f"    event_id={event_id_repr},",
        "    ts_utc=datetime(2026, 5, 18, 20, 0, 0, tzinfo=timezone.utc),",
        "    topic='risk_decisions',",
        "    entity_id='test-entity',",
        "    reason_code='approved',",
        '    payload_json=\'{"test": "kill9"}\',',
        ")",
        "",
        "# Sleep briefly so the parent can kill us at a predictable point",
        "time.sleep(10)",
    ]

    script_path.write_text("\n".join(script_lines), encoding="utf-8")

    import subprocess

    proc = subprocess.Popen(
        [sys.executable, str(script_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Wait for the subprocess to finish its writes (0.5s is sufficient for
    # synchronous DuckDB inserts) then kill it while it sleeps.
    time.sleep(1.5)
    proc.kill()
    proc.wait(timeout=5)

    # Allow OS to release any file handles
    time.sleep(0.2)

    # --- Verify durability ---
    # Open a fresh DuckDB connection (simulating recovery after restart)
    import duckdb
    conn = duckdb.connect(str(db_path))

    # 1. risk_state row must exist with the committed equity value
    result = conn.execute(
        "SELECT equity_dollars FROM risk_state WHERE date = '2026-05-18' LIMIT 1"
    ).fetchone()
    assert result is not None, (
        f"risk_state row for 2026-05-18 not found after kill. DB: {db_path}"
    )
    recovered_equity = float(result[0])
    expected_equity = float(known_equity)
    assert abs(recovered_equity - expected_equity) < 0.01, (
        f"HWM equity mismatch: expected {expected_equity}, got {recovered_equity}"
    )

    # 2. audit_log row must exist with the known event_id
    audit_result = conn.execute(
        "SELECT event_id FROM audit_log WHERE event_id = ?",
        [known_event_id],
    ).fetchone()
    assert audit_result is not None, (
        f"audit_log row with event_id={known_event_id} not found after kill."
    )

    conn.close()

    # 3. Verify HWM can be restored via FullRiskManager.load_hwm_from_db()
    store2 = DuckDBStore(db_path)
    config = _make_config(account_equity=Decimal("50000"))
    rm = FullRiskManager(config=config, store=store2)

    # load_hwm_from_db uses "yesterday's date" to find the HWM row.
    # We wrote the row with date '2026-05-18' so pass that same date.
    rm.load_hwm_from_db("2026-05-18", store2)

    # All three HWM values should be restored from the committed row
    assert rm._hwm_static == Decimal(known_equity), (
        f"hwm_static mismatch after recovery: expected {known_equity}, got {rm._hwm_static}"
    )
    assert rm._hwm_trailing_eod == Decimal(known_equity), (
        f"hwm_trailing_eod mismatch after recovery: expected {known_equity}, got {rm._hwm_trailing_eod}"
    )
    assert rm._hwm_trailing_intraday == Decimal(known_equity), (
        f"hwm_trailing_intraday mismatch after recovery: expected {known_equity}, got {rm._hwm_trailing_intraday}"
    )


# ---------------------------------------------------------------------------
# Test 2: STATIC HWM never decreases
# ---------------------------------------------------------------------------

def test_static_hwm_never_decreases():
    """STATIC model: HWM is fixed at account_equity; never rises or falls.

    Even when equity rises due to profits (which would ratchet TRAILING_INTRADAY),
    _hwm_static stays at the original account_equity value.
    Even when equity dips (losses), _hwm_static does not decrease.
    """
    account_equity = Decimal("50000")
    config = _make_config(
        account_equity=account_equity,
        drawdown_model=DrawdownModel.STATIC,
        max_contracts=10,
    )
    rm = FullRiskManager(config=config, store=None)

    initial_hwm = rm._hwm_static
    assert initial_hwm == account_equity, (
        f"Initial hwm_static should be account_equity={account_equity}"
    )

    from trading_core.strategy.models import Signal

    async def run_checks():
        # Check with profitable state (equity > HWM)
        profit_state = _make_state(
            realized_pnl_today=Decimal("1500"),
            open_exposure_dollars=Decimal("0"),
        )
        signal = Signal(
            strategy_id="test_static_profit",
            strategy_version="1.0",
            ts_utc=datetime(2026, 5, 18, 14, 30, 0, tzinfo=timezone.utc),
            side="long",
            entry=Decimal("4200.00"),
            stop=Decimal("4195.00"),
            target=Decimal("4220.00"),
            size_hint=Decimal("1"),
        )
        await rm.check(signal, profit_state)

        # Check with loss state (equity < HWM)
        loss_state = _make_state(
            realized_pnl_today=Decimal("-500"),
            open_exposure_dollars=Decimal("0"),
        )
        signal2 = Signal(
            strategy_id="test_static_loss",
            strategy_version="1.0",
            ts_utc=datetime(2026, 5, 18, 14, 31, 0, tzinfo=timezone.utc),
            side="long",
            entry=Decimal("4200.00"),
            stop=Decimal("4195.00"),
            target=Decimal("4220.00"),
            size_hint=Decimal("1"),
        )
        await rm.check(signal2, loss_state)

    asyncio.run(run_checks())

    # STATIC HWM must not have changed in either direction
    assert rm._hwm_static == initial_hwm, (
        f"STATIC HWM changed! Expected {initial_hwm}, got {rm._hwm_static}. "
        f"STATIC model must never update _hwm_static intraday."
    )


# ---------------------------------------------------------------------------
# Test 3: TRAILING_EOD HWM only updates at close
# ---------------------------------------------------------------------------

def test_trailing_eod_hwm_only_updates_at_close():
    """TRAILING_EOD: HWM does NOT update during check(); only via update_eod_hwm().

    Intraday check() calls (even with equity > HWM) must NOT ratchet the
    TRAILING_EOD HWM. Only update_eod_hwm() ratchets it.
    """
    account_equity = Decimal("50000")
    config = _make_config(
        account_equity=account_equity,
        drawdown_model=DrawdownModel.TRAILING_EOD,
        max_contracts=10,
    )
    rm = FullRiskManager(config=config, store=None)

    initial_hwm = rm._hwm_trailing_eod
    assert initial_hwm == account_equity

    from trading_core.strategy.models import Signal

    async def run_check_with_profit():
        profit_state = _make_state(
            realized_pnl_today=Decimal("1000"),  # equity = 51000 > 50000
            open_exposure_dollars=Decimal("0"),
        )
        signal = Signal(
            strategy_id="test_eod",
            strategy_version="1.0",
            ts_utc=datetime(2026, 5, 18, 14, 30, 0, tzinfo=timezone.utc),
            side="long",
            entry=Decimal("4200.00"),
            stop=Decimal("4195.00"),
            target=Decimal("4220.00"),
            size_hint=Decimal("1"),
        )
        await rm.check(signal, profit_state)

    asyncio.run(run_check_with_profit())

    # TRAILING_EOD HWM must NOT have ratcheted during check()
    assert rm._hwm_trailing_eod == initial_hwm, (
        f"TRAILING_EOD HWM updated during check()! "
        f"Expected {initial_hwm}, got {rm._hwm_trailing_eod}. "
        f"TRAILING_EOD must only ratchet via update_eod_hwm()."
    )

    # Now call update_eod_hwm() with a higher equity — HWM should ratchet
    eod_equity = Decimal("51500")
    rm.update_eod_hwm(eod_equity)

    assert rm._hwm_trailing_eod == eod_equity, (
        f"TRAILING_EOD HWM did not ratchet after update_eod_hwm(). "
        f"Expected {eod_equity}, got {rm._hwm_trailing_eod}."
    )

    # Another update_eod_hwm() with a LOWER value — HWM must NOT decrease
    rm.update_eod_hwm(Decimal("50000"))
    assert rm._hwm_trailing_eod == eod_equity, (
        f"TRAILING_EOD HWM decreased on lower equity! "
        f"Expected {eod_equity}, got {rm._hwm_trailing_eod}."
    )


# ---------------------------------------------------------------------------
# Test 4: TRAILING_INTRADAY HWM updates on every tick
# ---------------------------------------------------------------------------

def test_trailing_intraday_hwm_updates_on_every_tick():
    """TRAILING_INTRADAY: HWM advances to track equity highs on every check() call.

    When current_equity > _hwm_trailing_intraday, check() ratchets the HWM.
    HWM does NOT decrease when equity falls back.
    """
    account_equity = Decimal("50000")
    config = _make_config(
        account_equity=account_equity,
        drawdown_model=DrawdownModel.TRAILING_INTRADAY,
        max_contracts=10,
    )
    rm = FullRiskManager(config=config, store=None)

    assert rm._hwm_trailing_intraday == account_equity

    from trading_core.strategy.models import Signal

    async def run_checks():
        # Check 1: equity $51,000 — HWM should ratchet to 51000
        profit_state_1 = _make_state(
            realized_pnl_today=Decimal("1000"),
            open_exposure_dollars=Decimal("0"),
        )
        signal_1 = Signal(
            strategy_id="intraday_test_1",
            strategy_version="1.0",
            ts_utc=datetime(2026, 5, 18, 14, 30, 0, tzinfo=timezone.utc),
            side="long",
            entry=Decimal("4200.00"),
            stop=Decimal("4195.00"),
            target=Decimal("4220.00"),
            size_hint=Decimal("1"),
        )
        await rm.check(signal_1, profit_state_1)
        hwm_after_first = rm._hwm_trailing_intraday
        assert hwm_after_first == Decimal("51000"), (
            f"TRAILING_INTRADAY did not ratchet to 51000. Got {hwm_after_first}."
        )

        # Check 2: equity $52,000 — HWM should ratchet to 52000
        profit_state_2 = _make_state(
            realized_pnl_today=Decimal("2000"),
            open_exposure_dollars=Decimal("0"),
        )
        # Different strategy_id to avoid concurrency cap
        signal_2 = Signal(
            strategy_id="intraday_test_2",
            strategy_version="1.0",
            ts_utc=datetime(2026, 5, 18, 14, 31, 0, tzinfo=timezone.utc),
            side="long",
            entry=Decimal("4200.00"),
            stop=Decimal("4195.00"),
            target=Decimal("4220.00"),
            size_hint=Decimal("1"),
        )
        await rm.check(signal_2, profit_state_2)
        hwm_after_second = rm._hwm_trailing_intraday
        assert hwm_after_second == Decimal("52000"), (
            f"TRAILING_INTRADAY did not ratchet to 52000. Got {hwm_after_second}."
        )

        # Check 3: equity $50,000 (back to starting point) — HWM must NOT decrease
        flat_state = _make_state(
            realized_pnl_today=Decimal("0"),
            open_exposure_dollars=Decimal("0"),
        )
        signal_3 = Signal(
            strategy_id="intraday_test_3",
            strategy_version="1.0",
            ts_utc=datetime(2026, 5, 18, 14, 32, 0, tzinfo=timezone.utc),
            side="long",
            entry=Decimal("4200.00"),
            stop=Decimal("4195.00"),
            target=Decimal("4220.00"),
            size_hint=Decimal("1"),
        )
        await rm.check(signal_3, flat_state)
        hwm_after_flat = rm._hwm_trailing_intraday
        assert hwm_after_flat == Decimal("52000"), (
            f"TRAILING_INTRADAY HWM decreased! Expected 52000, got {hwm_after_flat}."
        )

    asyncio.run(run_checks())
