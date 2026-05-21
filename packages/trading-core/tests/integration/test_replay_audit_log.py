"""Integration: SP-04 replay audit-log reproducibility CI.

Bar-by-bar replay through the live engine path (ORBStrategy -> FullRiskManager
-> PaperExecutor -> audit CSV) must produce a byte-identical audit-log CSV
compared to a committed golden fixture.

Requirements:
    SP-04 — replay.py re-feeds bars through the live engine path and writes an
             audit-log CSV that is byte-identical across runs on the same bars.

Three tests:
    1. test_replay_audit_log_byte_identical — engine-path unit test: runs the
       replay loop in-process and byte-compares to the golden fixture.
    2. test_audit_csv_is_utf8_no_bom — D-09: confirms UTF-8 encoding, no BOM.
    3. test_replay_cli_subprocess_matches_golden — subprocess CLI test: invokes
       scripts/replay.py as a subprocess and byte-compares its output CSV to the
       golden fixture (validates arg parsing, DuckDB query, output path composition).
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import sys
import time
from datetime import timezone
from decimal import Decimal
from pathlib import Path

import pytest

import yaml

from fixtures.orb_day import orb_day_bars
from trading_core.events.models import TOPIC_RISK_DECISIONS
from trading_core.execution.paper import PaperExecutor
from trading_core.risk.models import RiskConfig, RiskState
from trading_core.risk.full_risk_manager import FullRiskManager
from trading_core.storage.duckdb_store import DuckDBStore
from trading_core.storage.runs import new_run_id
from trading_core.strategy.models import StrategyContext
from trading_core.strategy.orb import ORBConfig, ORBStrategy

# ---- module-level constants ------------------------------------------------

# _REPO_ROOT: four levels up from this file (tests/integration/ -> tests/ -> trading-core/ -> packages/ -> repo)
_REPO_ROOT = Path(__file__).resolve().parents[4]
_GOLDEN_DIR = Path(__file__).parent.parent / "fixtures" / "golden_audit"
_GOLDEN_CSV = _GOLDEN_DIR / "2024-06-12.csv"

# Fixture date for the golden CSV
_FIXTURE_DATE = "2024-06-12"

# Audit CSV header — matches DuckDBStore._AUDIT_CSV_HEADER
_AUDIT_CSV_HEADER = ["event_id", "ts_utc", "topic", "entity_id", "reason_code", "payload_json"]

# Risk config — load from config/risk.yaml so in-process tests use the same
# config as the CLI (max_contracts, account_equity, etc. must match).
_RISK_CONFIG_PATH = _REPO_ROOT / "config" / "risk.yaml"


def _load_risk_config() -> RiskConfig:
    """Load RiskConfig from config/risk.yaml (same source as replay.py CLI)."""
    with _RISK_CONFIG_PATH.open("r", encoding="utf-8") as fh:
        return RiskConfig(**yaml.safe_load(fh))


# ---- helper: engine-path replay loop ---------------------------------------

def _run_replay_once(output_dir: Path) -> Path:
    """Run bar-by-bar engine-path replay over orb_day_bars('2024-06-12') into output_dir.

    Mirrors the replay loop in scripts/replay.py and scripts/gen_golden.py.
    Uses deterministic event_ids and entity_ids so the output CSV is
    byte-identical across runs (SP-04).

    Args:
        output_dir: Directory under which audit/{date}.csv is written.

    Returns:
        Path to the written audit CSV.
    """
    import csv as _csv  # noqa: PLC0415 — local import to avoid shadowing module-level

    bars = orb_day_bars(date_str=_FIXTURE_DATE)

    # Use an isolated DuckDB for in-process audit writes (avoids polluting the live store)
    replay_db = output_dir / "replay.duckdb"
    store = DuckDBStore(replay_db)
    store.ensure_schema()

    try:
        strategy = ORBStrategy(ORBConfig())
        risk_manager = FullRiskManager(config=_load_risk_config(), store=store, symbol="SPY")
        executor = PaperExecutor("SPY")

        audit_dir = output_dir / "audit"
        audit_dir.mkdir(parents=True, exist_ok=True)
        output_csv_path = audit_dir / f"{_FIXTURE_DATE}.csv"

        _counters = {"events": 0, "signals": 0}

        with output_csv_path.open("w", newline="", encoding="utf-8") as fh:
            writer = _csv.writer(fh)
            writer.writerow(_AUDIT_CSV_HEADER)

            def _write_event(ts_utc, topic, det_entity_id, reason_code, payload_json):
                det_event_id = f"replay-{_counters['events']:010d}"
                writer.writerow(
                    [det_event_id, ts_utc.isoformat(), topic, det_entity_id, reason_code, payload_json]
                )
                _counters["events"] += 1

            open_position = None
            risk_state = RiskState()

            async def _run():
                nonlocal open_position, risk_state

                for i, bar in enumerate(bars):
                    ctx = StrategyContext(
                        rollover_seam=bar.rollover_seam,
                        warmup_complete=strategy.is_warm(),
                        bar_index=strategy._bar_count,
                        ts_utc=bar.ts_utc,
                        atr=strategy._atr.current,
                        session_vwap=strategy._vwap.current,
                        ema=strategy._ema.current,
                        adr=None,
                    )

                    signal = strategy.on_bar(bar, ctx)
                    strategy._push_bar(bar)

                    # Check exit on open position
                    if open_position is not None:
                        exit_result = executor.check_exit(
                            side=open_position["side"],
                            entry_price=open_position["entry_price"],
                            stop=open_position["stop"],
                            target=open_position["target"],
                            bar=bar,
                            is_last_rth_bar=(i == len(bars) - 1),
                        )
                        if exit_result is not None:
                            exit_reason, exit_price = exit_result
                            exit_fill = await executor.fill_exit(
                                signal=open_position["entry_signal"],
                                exit_reason=exit_reason,
                                exit_price=exit_price,
                                exit_ts_utc=bar.ts_utc,
                                fill_qty=open_position["fill_qty"],
                            )

                            if open_position["side"] == "long":
                                pnl = (exit_fill.fill_price - open_position["entry_fill_price"]) * Decimal(open_position["fill_qty"])
                            else:
                                pnl = (open_position["entry_fill_price"] - exit_fill.fill_price) * Decimal(open_position["fill_qty"])

                            risk_state = RiskState(
                                realized_pnl_today=risk_state.realized_pnl_today + pnl,
                                open_exposure_dollars=Decimal("0"),
                                drawdown_model=risk_state.drawdown_model,
                            )

                            exit_payload = json.dumps({
                                "exit_reason": exit_reason,
                                "exit_price": str(exit_fill.fill_price),
                                "fill_qty": exit_fill.fill_qty,
                                "pnl": str(pnl),
                            })
                            store.write_audit_event(
                                event_id=new_run_id(),
                                ts_utc=bar.ts_utc,
                                topic="fills",
                                entity_id=open_position["entry_signal"].signal_id,
                                reason_code=exit_reason,
                                payload_json=exit_payload,
                            )
                            _write_event(
                                ts_utc=bar.ts_utc,
                                topic="fills",
                                det_entity_id=open_position["det_signal_id"],
                                reason_code=exit_reason,
                                payload_json=exit_payload,
                            )
                            risk_manager.record_position_closed(open_position["entry_signal"].strategy_id)
                            open_position = None

                    # Process new signal
                    if signal is not None and open_position is None:
                        decision = await risk_manager.check(signal, risk_state)

                        det_sig_id = f"signal-{_counters['signals']:06d}"

                        _write_event(
                            ts_utc=signal.ts_utc,
                            topic=TOPIC_RISK_DECISIONS,
                            det_entity_id=det_sig_id,
                            reason_code=decision.reason,
                            payload_json=decision.model_dump_json(),
                        )

                        if decision.approved:
                            next_bar_idx = i + 1
                            if next_bar_idx < len(bars):
                                next_bar = bars[next_bar_idx]
                                entry_fill = await executor.fill_entry(signal, decision, next_bar)

                                if signal.side == "long":
                                    open_exposure = (bar.close - entry_fill.fill_price) * Decimal(entry_fill.fill_qty)
                                else:
                                    open_exposure = (entry_fill.fill_price - bar.close) * Decimal(entry_fill.fill_qty)

                                risk_state = RiskState(
                                    realized_pnl_today=risk_state.realized_pnl_today,
                                    open_exposure_dollars=open_exposure,
                                    drawdown_model=risk_state.drawdown_model,
                                )

                                entry_payload = json.dumps({
                                    "fill_price": str(entry_fill.fill_price),
                                    "fill_qty": entry_fill.fill_qty,
                                    "side": entry_fill.side,
                                    "slippage_ticks": entry_fill.slippage_ticks,
                                })
                                store.write_audit_event(
                                    event_id=new_run_id(),
                                    ts_utc=next_bar.ts_utc,
                                    topic="fills",
                                    entity_id=signal.signal_id,
                                    reason_code="entry_fill",
                                    payload_json=entry_payload,
                                )
                                _write_event(
                                    ts_utc=next_bar.ts_utc,
                                    topic="fills",
                                    det_entity_id=det_sig_id,
                                    reason_code="entry_fill",
                                    payload_json=entry_payload,
                                )

                                risk_manager.record_position_open(
                                    signal.strategy_id,
                                    {
                                        "symbol": "SPY",
                                        "strategy_id": signal.strategy_id,
                                        "side": signal.side,
                                        "qty": entry_fill.fill_qty,
                                        "avg_fill": entry_fill.fill_price,
                                        "mark": next_bar.close,
                                        "stop": signal.stop,
                                        "target": signal.target,
                                        "entry_ts_utc": next_bar.ts_utc,
                                    },
                                )
                                open_position = {
                                    "side": signal.side,
                                    "entry_price": signal.entry,
                                    "entry_fill_price": entry_fill.fill_price,
                                    "stop": signal.stop,
                                    "target": signal.target,
                                    "fill_qty": entry_fill.fill_qty,
                                    "entry_signal": signal,
                                    "det_signal_id": det_sig_id,
                                }

                        _counters["signals"] += 1

            asyncio.run(_run())
            fh.flush()

    finally:
        store.close()

    return output_csv_path


# ---- tests -----------------------------------------------------------------

def test_replay_audit_log_byte_identical(tmp_path: Path, request):
    """SP-04: engine-path replay produces byte-identical audit-log CSV vs golden fixture.

    When --update-golden is supplied: regenerate the golden fixture and skip.
    Otherwise: assert byte-identical match.
    """
    if request.config.getoption("--update-golden", default=False):
        # Regenerate golden fixture instead of asserting
        _GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
        output = _run_replay_once(tmp_path)
        shutil.copy(output, _GOLDEN_CSV)
        pytest.skip("Golden fixture updated — re-run without --update-golden to assert.")
        return

    assert _GOLDEN_CSV.exists(), (
        f"Golden fixture missing: {_GOLDEN_CSV}. "
        "Run 'uv run python scripts/gen_golden.py' or "
        "'uv run pytest ... --update-golden' to generate it."
    )

    output = _run_replay_once(tmp_path)

    # Byte comparison — same approach as FND-08 equity-Parquet test
    assert output.read_bytes() == _GOLDEN_CSV.read_bytes(), (
        "Audit log CSV does not match golden fixture. "
        "If audit schema changed intentionally, regenerate with --update-golden."
    )


def test_audit_csv_is_utf8_no_bom(tmp_path: Path):
    """D-09: replay output CSV is UTF-8 encoded with no BOM.

    Ensures the csv.writer with encoding='utf-8' (no 'utf-8-sig') never
    prepends the 0xEF 0xBB 0xBF BOM sequence.
    """
    output = _run_replay_once(tmp_path)
    raw = output.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf"), (
        "Audit CSV must not have a UTF-8 BOM (D-09). "
        "Ensure the file is opened with encoding='utf-8', not 'utf-8-sig'."
    )
    # Full decode must succeed without errors
    output.read_text(encoding="utf-8")


def test_replay_cli_subprocess_matches_golden(tmp_path: Path):
    """SP-04 subprocess validation: scripts/replay.py CLI produces byte-identical output.

    This test validates the actual CLI end-to-end:
    - Arg parsing (--symbol, --tf, --from, --to, --duckdb-path, --output-dir)
    - DuckDB bars query (parameterized SELECT)
    - Output path composition ({output-dir}/audit/{date}.csv)
    - Byte-identical comparison to the committed golden fixture

    Pattern follows test_phase5_kill9.py subprocess invocation style.
    """
    assert _GOLDEN_CSV.exists(), (
        f"Golden fixture missing: {_GOLDEN_CSV}. "
        "Run 'uv run python scripts/gen_golden.py' or "
        "'uv run pytest ... --update-golden' first."
    )

    # Step 1: Populate a test DuckDB with orb_day_bars("2024-06-12") data.
    # Symbol must match the --symbol arg passed to replay.py below.
    test_db_path = tmp_path / "test.duckdb"
    bars = orb_day_bars(date_str=_FIXTURE_DATE)  # symbol defaults to "SPY"

    test_store = DuckDBStore(test_db_path)
    test_store.ensure_schema()
    # Write bars into the bars table via upsert_bars (the path replay.py's SELECT queries)
    import pandas as pd  # noqa: PLC0415
    import pandas as pd_  # noqa: PLC0415, F401 (needed for type)
    bar_records = [
        {
            "symbol": bar.symbol,
            "timeframe": bar.timeframe,
            "ts_utc": bar.ts_utc,
            "open": float(bar.open),
            "high": float(bar.high),
            "low": float(bar.low),
            "close": float(bar.close),
            "volume": bar.volume,
            "rollover_seam": bar.rollover_seam,
        }
        for bar in bars
    ]
    bars_df = pd.DataFrame(bar_records)
    test_store.upsert_bars(bars_df, provider="test")
    test_store.close()

    # Short sleep to guard Windows file-handle release before subprocess opens the DB
    # (pattern from test_phase5_kill9.py — guards against EBUSY on Windows)
    time.sleep(0.2)

    # Step 2: Invoke replay.py as a subprocess with --duckdb-path and --output-dir.
    # Use the same symbol the bars were written under (SPY).
    # --to is the day AFTER the fixture date (exclusive end of range) so all
    # bars on 2024-06-12 are included in the parameterized SELECT.
    output_dir = tmp_path / "output"
    result = subprocess.run(
        [
            sys.executable,
            "scripts/replay.py",
            "--from", _FIXTURE_DATE,
            "--to", "2024-06-13",
            "--symbol", "SPY",
            "--tf", "1m",
            "--duckdb-path", str(test_db_path),
            "--output-dir", str(output_dir),
        ],
        cwd=str(_REPO_ROOT),
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    # Confirm the CLI printed a valid JSON status line
    stdout_lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
    assert stdout_lines, f"replay.py produced no stdout. stderr:\n{result.stderr}"
    status_obj = json.loads(stdout_lines[-1])
    assert status_obj.get("status") == "ok", (
        f"replay.py exited with status != 'ok': {status_obj}"
    )

    # Step 3: Read the CLI's output CSV from {output-dir}/audit/{date}.csv
    cli_output_path = output_dir / "audit" / f"{_FIXTURE_DATE}.csv"
    assert cli_output_path.exists(), (
        f"replay.py did not create expected output CSV at {cli_output_path}. "
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )

    # Step 4: Byte comparison against the committed golden fixture
    assert cli_output_path.read_bytes() == _GOLDEN_CSV.read_bytes(), (
        "replay.py CLI output CSV does not match golden fixture. "
        "If audit schema changed intentionally, regenerate with --update-golden."
    )
