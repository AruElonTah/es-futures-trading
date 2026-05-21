#!/usr/bin/env python3
"""Replay CLI — re-feeds historical bars bar-by-bar through the live engine path (SP-04).

Pipeline:
    DuckDB bars query (--symbol --tf --from --to, or --duckdb-path override)
        -> ORBStrategy.on_bar
        -> FullRiskManager.check
        -> PaperExecutor.fill_entry / check_exit / fill_exit
        -> DuckDBStore.write_audit_event (DuckDB + store CSV side-effect)
        -> --output-dir/audit/{date}.csv  (isolated replay output)

Purpose (SP-04):
    The replay command proves the live engine path is deterministic — the same
    bars always produce the same audit log. The output CSV is byte-identical
    across runs on the same bars + config.

Exit codes:
    0 — {"status":"ok","event_count":N} printed to stdout
    1 — {"status":"failed"} on exception

Threat mitigations:
    T-08-01: --symbol/--tf use argparse choices= whitelist; bars SELECT uses ?
             parameterized placeholders (no f-string interpolation).
    T-08-02: Output CSV path is composed under --output-dir with fixed
             audit/{date}.csv suffix; date comes from bar timestamp, not user text.
    T-08-03: yaml.safe_load only — never yaml.load with default loader.

Plan 08-01.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
import tempfile
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

# Defensive: reconfigure stdout/stderr to UTF-8 BEFORE any module-level import
# (Pitfall 5 — Windows piped-stdout cp1252 trap; mirrors run_backtest.py pattern).
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Make sure `packages/trading-core/src` is on sys.path when invoked outside
# the uv `run` shim (mirrors run_backtest.py pattern).
_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "packages" / "trading-core" / "src"
if _SRC.exists() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import yaml  # noqa: E402 (after sys.path bootstrap)

from trading_core.config import Settings  # noqa: E402
from trading_core.data.models import Bar  # noqa: E402
from trading_core.events.models import TOPIC_RISK_DECISIONS  # noqa: E402
from trading_core.execution.paper import PaperExecutor  # noqa: E402
from trading_core.logging import get_logger, setup_logging  # noqa: E402
from trading_core.risk.models import RiskConfig, RiskState  # noqa: E402
from trading_core.risk.full_risk_manager import FullRiskManager  # noqa: E402
from trading_core.storage.duckdb_store import DuckDBStore  # noqa: E402
from trading_core.storage.runs import new_run_id  # noqa: E402
from trading_core.strategy.models import StrategyContext  # noqa: E402
from trading_core.strategy.orb import ORBConfig, ORBStrategy  # noqa: E402

# Audit CSV header — matches DuckDBStore._AUDIT_CSV_HEADER column order.
_AUDIT_CSV_HEADER = ["event_id", "ts_utc", "topic", "entity_id", "reason_code", "payload_json"]


def _parse_iso_utc(s: str) -> datetime:
    """Parse an ISO 8601 date / datetime string as tz-aware UTC.

    Accepts:
        '2024-01-02'        -> 2024-01-02T00:00 UTC
        '2024-01-02T13:30'  -> 2024-01-02T13:30 UTC
    """
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="replay",
        description=(
            "Re-feed historical DuckDB bars bar-by-bar through the live engine path "
            "(ORBStrategy -> FullRiskManager -> PaperExecutor -> audit_log CSV). "
            "Produces a deterministic audit-log CSV for SP-04 reproducibility CI. "
            "Exit codes: 0 ok, 1 failed."
        ),
    )
    p.add_argument(
        "--symbol",
        choices=["ES", "MES", "SPY"],  # T-08-01: whitelist prevents injection
        default="ES",
        help="Instrument symbol (default: ES). Parameterized in SQL (T-08-01).",
    )
    p.add_argument(
        "--tf",
        choices=["1m", "5m", "15m"],
        default="1m",
        help="Bar timeframe (default: 1m).",
    )
    p.add_argument(
        "--from",
        dest="frm",
        type=_parse_iso_utc,
        required=True,
        help="ISO 8601 start (inclusive, UTC). Bare date interpreted as 00:00 UTC.",
    )
    p.add_argument(
        "--to",
        type=_parse_iso_utc,
        required=True,
        help="ISO 8601 end (exclusive, UTC). Bare date interpreted as 00:00 UTC.",
    )
    p.add_argument(
        "--output-dir",
        dest="output_dir",
        type=Path,
        default=None,
        help=(
            "Directory for replay audit-log CSV output (default: temp dir). "
            "CSV is written to {output-dir}/audit/{date}.csv (T-08-02: fixed suffix). "
            "Never writes to the live data/logs/audit/ directory (D-04)."
        ),
    )
    p.add_argument(
        "--risk-config",
        dest="risk_config",
        type=Path,
        default=Path("config/risk.yaml"),
        help="Path to risk YAML config (default: config/risk.yaml). Loaded via yaml.safe_load (T-08-03).",
    )
    p.add_argument(
        "--duckdb-path",
        dest="duckdb_path",
        type=Path,
        default=None,
        help=(
            "Override Settings.duckdb_path for bar reads. "
            "When supplied, replay reads bars from this DuckDB file instead of the live store. "
            "Lets CI tests point replay at an isolated test DuckDB (D-03)."
        ),
    )
    return p


async def main(args: argparse.Namespace) -> int:
    """Async replay pipeline — invoked by __main__ via asyncio.run.

    Returns:
        Exit code: 0 ok, 1 failed.
    """
    settings = Settings()

    # D-03: bars read from DuckDB (live or --duckdb-path override)
    duckdb_path: Path = args.duckdb_path if args.duckdb_path is not None else settings.duckdb_path

    setup_logging(settings.audit_log_dir)

    log = get_logger(__name__)
    log = log.bind(symbol=args.symbol, tf=args.tf)

    log.info("replay.start", from_ts=str(args.frm), to_ts=str(args.to))

    store: DuckDBStore | None = None
    _temp_dir = None

    try:
        store = DuckDBStore(duckdb_path)
        store.ensure_schema()

        # Query bars via public DuckDBStore method (WR-06: avoids private _conn access).
        # Parameterized binding enforced inside query_bars (T-08-01).
        df = store.query_bars(args.symbol, args.tf, args.frm, args.to)

        if df.empty:
            raise RuntimeError(
                f"No bars found for {args.symbol} {args.tf} in [{args.frm}, {args.to}). "
                "Use --duckdb-path to point at a populated DuckDB, or run seed_bars.py first."
            )

        log.info("replay.bars.loaded", row_count=len(df))

        # Reconstruct Bar objects — Decimal-only (never float) for OHLC (T-08-01 / RM-01)
        bars: list[Bar] = [
            Bar(
                symbol=str(row.symbol),
                timeframe=str(row.timeframe),
                ts_utc=(
                    row.ts_utc.to_pydatetime().astimezone(timezone.utc)
                    if hasattr(row.ts_utc, "to_pydatetime")
                    else row.ts_utc
                ),
                open=Decimal(str(row.open)),
                high=Decimal(str(row.high)),
                low=Decimal(str(row.low)),
                close=Decimal(str(row.close)),
                volume=int(row.volume),
                rollover_seam=bool(row.rollover_seam),
            )
            for row in df.itertuples(index=False)
        ]

        # T-08-03: yaml.safe_load only — never yaml.load with default loader
        with Path(args.risk_config).open("r", encoding="utf-8") as fh:
            risk_data = yaml.safe_load(fh)
        risk_config = RiskConfig(**risk_data)

        # Instantiate engine components (D-01)
        strategy = ORBStrategy(ORBConfig())
        risk_manager = FullRiskManager(config=risk_config, store=store, symbol=args.symbol)
        executor = PaperExecutor(args.symbol)

        # D-04: resolve output CSV path under --output-dir (T-08-02: fixed suffix)
        # Never writes into data/logs/audit/ — always isolated under --output-dir.
        if args.output_dir is not None:
            output_base = args.output_dir
        else:
            # Use a temp dir when --output-dir not supplied (D-04)
            _temp_dir = tempfile.mkdtemp(prefix="replay_")
            output_base = Path(_temp_dir)

        # Determine the date for the output CSV from the first bar's ET date
        from zoneinfo import ZoneInfo  # noqa: PLC0415
        _ET = ZoneInfo("America/New_York")
        first_et_date = bars[0].ts_utc.astimezone(_ET).date()
        audit_dir = output_base / "audit"
        audit_dir.mkdir(parents=True, exist_ok=True)
        output_csv_path = audit_dir / f"{first_et_date}.csv"

        # Open the output CSV for writing (UTF-8, no BOM — D-09)
        # Use newline="" so csv.writer controls line endings exactly.
        with output_csv_path.open("w", newline="", encoding="utf-8") as output_csv_fh:
            output_writer = csv.writer(output_csv_fh)
            output_writer.writerow(_AUDIT_CSV_HEADER)

            # Track open position state for PaperExecutor exit checking
            open_position: dict | None = None
            risk_state = RiskState()
            # event_count and signal_counter are ints mutated via nonlocal in closures
            _counters = {"events": 0, "signals": 0}

            def _write_output_event(
                ts_utc: datetime,
                topic: str,
                det_entity_id: str,
                reason_code: str,
                payload_json: str,
            ) -> None:
                """Write one audit event row to the isolated output CSV.

                event_id and entity_id are both deterministic so the output CSV
                is byte-identical across runs on the same bars (SP-04).

                Args:
                    det_entity_id: Deterministic entity identifier (caller is
                        responsible for not passing random UUIDs here).
                """
                # Deterministic event_id: counter-prefixed so same bars -> same CSV
                det_event_id = f"replay-{_counters['events']:010d}"
                output_writer.writerow(
                    [det_event_id, ts_utc.isoformat(), topic, det_entity_id, reason_code, payload_json]
                )
                _counters["events"] += 1

            # Bar-by-bar replay loop (BL-1 gate: snapshot → on_bar → _push_bar)
            for i, bar in enumerate(bars):
                # Build StrategyContext from PRIOR-bar indicator snapshots (look-ahead safe)
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

                # on_bar BEFORE _push_bar (BL-1 gate: snapshot-before-push)
                signal = strategy.on_bar(bar, ctx)
                strategy._push_bar(bar)  # push AFTER on_bar — look-ahead safety

                # Check exit on open position (before processing new signals)
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

                        # Compute realized PnL and update risk state
                        if open_position["side"] == "long":
                            pnl = (exit_fill.fill_price - open_position["entry_fill_price"]) * Decimal(open_position["fill_qty"])
                        else:
                            pnl = (open_position["entry_fill_price"] - exit_fill.fill_price) * Decimal(open_position["fill_qty"])

                        risk_state = RiskState(
                            realized_pnl_today=risk_state.realized_pnl_today + pnl,
                            open_exposure_dollars=Decimal("0"),
                            drawdown_model=risk_state.drawdown_model,
                        )

                        # Write exit audit event
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
                        _write_output_event(
                            ts_utc=bar.ts_utc,
                            topic="fills",
                            det_entity_id=open_position["det_signal_id"],
                            reason_code=exit_reason,
                            payload_json=exit_payload,
                        )

                        risk_manager.record_position_closed(open_position["entry_signal"].strategy_id)
                        open_position = None

                # Process new signal if one fired and no position is open
                if signal is not None and open_position is None:
                    # FullRiskManager.check writes audit event to DuckDB + store CSV internally
                    decision = await risk_manager.check(signal, risk_state)

                    # Use a deterministic signal identifier for the output CSV (SP-04)
                    # signal.signal_id is UUID4 (random) — we use a counter instead.
                    det_sig_id = f"signal-{_counters['signals']:06d}"

                    # Mirror the risk decision audit event to the output CSV
                    decision_payload = decision.model_dump_json()
                    _write_output_event(
                        ts_utc=signal.ts_utc,
                        topic=TOPIC_RISK_DECISIONS,
                        det_entity_id=det_sig_id,
                        reason_code=decision.reason,
                        payload_json=decision_payload,
                    )

                    if decision.approved:
                        # PaperExecutor fill_entry: fill on the NEXT bar's open
                        # For bar-by-bar replay, the "next bar" is the following bar.
                        next_bar_idx = i + 1
                        if next_bar_idx < len(bars):
                            next_bar = bars[next_bar_idx]
                            entry_fill = await executor.fill_entry(signal, decision, next_bar)

                            # Open exposure at fill time is zero: unrealized P&L
                            # starts accruing on subsequent bars, not at the instant
                            # of fill. (CR-02: bar.close was stale signal-bar price,
                            # not fill price — produced incorrect initial exposure.)
                            risk_state = RiskState(
                                realized_pnl_today=risk_state.realized_pnl_today,
                                open_exposure_dollars=Decimal("0"),
                                drawdown_model=risk_state.drawdown_model,
                            )

                            # Write entry fill audit event
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
                            _write_output_event(
                                ts_utc=next_bar.ts_utc,
                                topic="fills",
                                det_entity_id=det_sig_id,
                                reason_code="entry_fill",
                                payload_json=entry_payload,
                            )

                            risk_manager.record_position_open(
                                signal.strategy_id,
                                {
                                    "symbol": args.symbol,
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

        event_count = _counters["events"]
        log.info("replay.complete", event_count=event_count, output_csv=str(output_csv_path))
        print(json.dumps({"status": "ok", "event_count": event_count}))
        return 0

    except Exception as exc:  # noqa: BLE001
        log.exception("replay.failed", error_type=type(exc).__name__)
        print(json.dumps({"status": "failed", "error": str(exc)}))
        return 1

    finally:
        try:
            if store is not None:
                store.close()
        except Exception:  # noqa: BLE001
            pass


if __name__ == "__main__":
    parser = _build_parser()
    parsed_args = parser.parse_args()
    sys.exit(asyncio.run(main(parsed_args)))
