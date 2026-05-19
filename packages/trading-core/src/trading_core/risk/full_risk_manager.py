"""FullRiskManager — Phase 5 Plan 02.

ATR-based position sizing + all three DrawdownModel variants tracked side-by-side
+ worst-case loss pre-trade check + daily-DD circuit breaker + per-strategy
concurrency cap + asyncio.Event-based kill-switch gate (D-10).

This class structurally satisfies the RiskManager Protocol — no inheritance.
Every check() result is written to DuckDB BEFORE the coroutine returns (SP-03
kill-9 guarantee, D-09).

Sizing formula (RM-01, locked by unit tests):
    size_for_stop(risk_$=1000, stop_ticks=5, MES) == 40
      Proof: floor(1000 / (5 * 5.00)) = floor(1000 / 25) = 40
    size_for_stop(risk_$=1000, stop_ticks=5, ES) == 4
      Proof: floor(1000 / (5 * 50.00)) = floor(1000 / 250) = 4

    "stop_ticks" in the function signature is actually stop distance in index
    points — the parameter name is kept for backward compatibility with the
    RM-01 specification. Uses instrument.point_value (NOT tick_value).

DrawdownModel variants (RM-02):
    STATIC: HWM fixed at session start (account_equity). Never changes intraday.
    TRAILING_EOD: HWM updates only at session close — call update_eod_hwm() to ratchet.
    TRAILING_INTRADAY: HWM updates on every check() call when current_equity > hwm.

All three HWM values are written to risk_state on every check() call (D-07).

Kill-switch (D-10):
    _kill_event: asyncio.Event — set_killed('killed') sets it; 'running'/'paused'
    clears it. check() reads is_set() BEFORE any other logic. On startup,
    load_kill_state_from_db() bootstraps the event from DuckDB engine_state.
"""

from __future__ import annotations

import asyncio
import math
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING

from trading_core.events.models import TOPIC_RISK_DECISIONS
from trading_core.instruments import Instrument
from trading_core.instruments import get as get_instrument
from trading_core.logging import get_logger
from trading_core.risk.models import (
    DrawdownModel,
    RiskConfig,
    RiskDecision,
    RiskState,
)
from trading_core.storage.runs import new_run_id
from trading_core.strategy.models import Signal

if TYPE_CHECKING:
    from trading_core.storage.duckdb_store import DuckDBStore


def size_for_stop(
    risk_dollars: Decimal,
    stop_ticks: Decimal,
    instrument: Instrument,
) -> int:
    """ATR-based position sizing — pure function (RM-01).

    Args:
        risk_dollars: Maximum dollar amount to risk on the trade.
        stop_ticks: Stop distance in index points (NOT tick count).
            For ES/MES, 1 index point = 4 ticks = 0.25 tick_size × 4.
            Named "stop_ticks" per the RM-01 spec; the math uses point_value.
        instrument: The Instrument from REGISTRY (provides point_value).

    Returns:
        Integer contract count (floor division; always >= 0).

    Examples:
        >>> from decimal import Decimal
        >>> from trading_core.instruments import get
        >>> size_for_stop(Decimal("1000"), Decimal("5"), get("MES"))
        40
        >>> size_for_stop(Decimal("1000"), Decimal("5"), get("ES"))
        4
    """
    return math.floor(risk_dollars / (stop_ticks * instrument.point_value))


class FullRiskManager:
    """Prop-firm-style risk manager implementing the RiskManager Protocol.

    Structurally satisfies RiskManager (no inheritance needed — Protocol seam).

    Key behaviors:
        - Kill-switch gate (D-10): checked FIRST, before all other logic
        - Per-strategy concurrency cap (RM-08): 1 active position per strategy_id
        - Daily-DD circuit breaker (RM-04): halts new entries, does NOT close positions
        - Worst-case loss check (RM-03): pre-trade floor violation detection
        - ATR-based sizing (RM-01): size_for_stop() + max_contracts cap (RM-06)
        - All three DrawdownModel HWM values tracked on every check() (RM-02)
        - DuckDB writes BEFORE returning RiskDecision (SP-03 kill-9 guarantee)

    Thread safety:
        asyncio is single-threaded; _positions dict and _kill_event are safe.
        DuckDBStore uses its own internal lock for the DuckDB connection.
    """

    def __init__(
        self,
        *,
        config: RiskConfig,
        store: "DuckDBStore | None" = None,
        symbol: str = "MES",
    ) -> None:
        """Initialise FullRiskManager.

        Args:
            config: Risk parameters (account_equity, max_risk_per_trade_pct,
                daily_dd_limit, drawdown_model, max_contracts).
            store: DuckDBStore instance for audit persistence (None in unit tests).
            symbol: Instrument symbol to look up from REGISTRY (default "MES").
        """
        self._config = config
        self._store = store
        self._instrument = get_instrument(symbol)
        self._symbol = symbol

        # Per-strategy open positions — keyed by strategy_id.
        # Values are full position metadata dicts (RM-08 / blotter data).
        self._positions: dict[str, dict] = {}

        # asyncio.Event for D-10 kill-switch (fast in-process gate).
        # set() → signals are rejected; clear() → signals flow normally.
        self._kill_event: asyncio.Event = asyncio.Event()

        self._log = get_logger(__name__)

        # Session ID — UUIDv7, time-sortable. Written to every risk_state row
        # so intraday rows can be grouped by session.
        self._session_id: str = new_run_id()

        # In-memory HWM state — initialized from account_equity.
        # Override via load_hwm_from_db() on lifespan startup (D-08).
        self._hwm_static: Decimal = config.account_equity
        self._hwm_trailing_eod: Decimal = config.account_equity
        self._hwm_trailing_intraday: Decimal = config.account_equity

    # ------------------------------------------------------------------
    # Kill-switch control (D-10)
    # ------------------------------------------------------------------

    def set_killed(self, state: str) -> None:
        """Toggle the asyncio.Event kill-switch gate.

        Args:
            state: One of ``'killed'``, ``'running'``, ``'paused'``.
                'killed' → sets the event (check() will reject all signals).
                'running' or 'paused' → clears the event.
                Unknown states are logged as warnings and ignored.
        """
        if state == "killed":
            self._kill_event.set()
        elif state in ("running", "paused"):
            self._kill_event.clear()
        else:
            self._log.warning(
                "risk.kill_switch.unknown_state",
                state=state,
                valid_states=["killed", "running", "paused"],
            )

    def load_kill_state_from_db(self, store: "DuckDBStore") -> None:
        """Bootstrap asyncio.Event from the persisted engine_state (D-10 startup).

        Called by the FastAPI lifespan on startup so the in-memory event reflects
        the last known kill/paused/running state after a restart.

        Args:
            store: DuckDBStore instance to query (may differ from self._store
                when called during lifespan setup before the singleton is wired).
        """
        persisted_state = store.get_engine_state()
        self.set_killed(persisted_state)

    # ------------------------------------------------------------------
    # HWM bootstrap (D-08)
    # ------------------------------------------------------------------

    def load_hwm_from_db(self, date_str: str, store: "DuckDBStore") -> None:
        """Restore HWM from yesterday's last risk_state row (D-08).

        If no row found (Day-1 exception): use account_equity as starting HWM.

        Args:
            date_str: Yesterday's trading date as ``'YYYY-MM-DD'`` (ET calendar).
            store: DuckDBStore instance to query.
        """
        row = store.get_last_risk_state(date_str)
        if row is None:
            # Day-1: no prior row — bootstrap from account_equity
            self._hwm_static = self._config.account_equity
            self._hwm_trailing_eod = self._config.account_equity
            self._hwm_trailing_intraday = self._config.account_equity
        else:
            self._hwm_static = Decimal(str(row.get("hwm_static", self._config.account_equity)))
            self._hwm_trailing_eod = Decimal(str(row.get("hwm_trailing_eod", self._config.account_equity)))
            self._hwm_trailing_intraday = Decimal(str(row.get("hwm_trailing_intraday", self._config.account_equity)))

    # ------------------------------------------------------------------
    # EOD HWM ratchet (TRAILING_EOD model)
    # ------------------------------------------------------------------

    def update_eod_hwm(self, current_equity: Decimal) -> None:
        """Ratchet TRAILING_EOD HWM at session close.

        Called by the EOD flatten hook (Phase 5 Plan 03) when the wall-clock
        reaches session_close - 60s. Does NOT ratchet intraday.

        Args:
            current_equity: Total equity at session close.
        """
        if current_equity > self._hwm_trailing_eod:
            self._hwm_trailing_eod = current_equity

    # ------------------------------------------------------------------
    # Position tracking (RM-08)
    # ------------------------------------------------------------------

    def record_position_open(self, strategy_id: str, position_info: dict) -> None:
        """Record an open position for the concurrency gate (RM-08).

        Args:
            strategy_id: The strategy that opened the position.
            position_info: Full position metadata dict with keys:
                symbol, strategy_id, side, qty, avg_fill, mark, stop, target,
                entry_ts_utc. Used by GET /positions blotter endpoint.
        """
        self._positions[strategy_id] = position_info

    def record_position_closed(self, strategy_id: str) -> None:
        """Remove a closed position from the concurrency gate (RM-08).

        No-op if strategy_id is not in _positions (idempotent).

        Args:
            strategy_id: The strategy whose position closed.
        """
        self._positions.pop(strategy_id, None)

    # ------------------------------------------------------------------
    # Main risk gate (SP-02 — ONLY path from signal to fill approval)
    # ------------------------------------------------------------------

    async def check(self, signal: Signal, state: RiskState) -> RiskDecision:
        """Evaluate signal against all risk constraints.

        Check order (MUST be preserved for correctness):
            0. Kill-switch gate (D-10) — FIRST, before anything else
            1. Per-strategy concurrency cap (RM-08)
            2. Daily-DD circuit breaker (RM-04)
            3. Position sizing (RM-01 / RM-06)
            4. Worst-case loss check (RM-03)
            5. Persist to DuckDB (SP-03 — BEFORE returning)
            6. Return RiskDecision

        DuckDB writes happen for EVERY outcome (approved AND rejected).
        This is the kill-9 guarantee: a crash after this method returns has
        already committed the audit row.

        Args:
            signal: Trade signal from the strategy layer.
            state: Current risk state (realized PnL, open exposure).

        Returns:
            RiskDecision with approved, reason, adjusted_size.
        """
        now_utc = datetime.now(tz=timezone.utc)

        # --- 0. Kill-switch gate (D-10) — checked FIRST ---
        if self._kill_event.is_set():
            decision = RiskDecision(
                approved=False,
                reason="kill_switch_active",
                adjusted_size=0,
            )
            if self._store is not None:
                self._store.write_audit_event(
                    event_id=new_run_id(),
                    ts_utc=now_utc,
                    topic=TOPIC_RISK_DECISIONS,
                    entity_id=signal.signal_id,
                    reason_code="kill_switch_active",
                    payload_json=decision.model_dump_json(),
                )
            self._log.info(
                "risk.check.kill_switch_active",
                signal_id=signal.signal_id,
                strategy_id=signal.strategy_id,
            )
            return decision

        # --- 1. Compute current equity ---
        current_equity = (
            self._config.account_equity
            + state.realized_pnl_today
            + state.open_exposure_dollars
        )

        # --- 2. Update TRAILING_INTRADAY HWM (always ratchets to new highs) ---
        if current_equity > self._hwm_trailing_intraday:
            self._hwm_trailing_intraday = current_equity
        # NOTE: STATIC HWM never changes (initialized from account_equity).
        # NOTE: TRAILING_EOD HWM only changes via update_eod_hwm() at session close.

        # --- 3. Compute all three floors (written to DuckDB on every call) ---
        floor_static = self._hwm_static - self._config.daily_dd_limit
        floor_trailing_eod = self._hwm_trailing_eod - self._config.daily_dd_limit
        floor_trailing_intraday = self._hwm_trailing_intraday - self._config.daily_dd_limit

        # Active floor (used for RM-03 worst-case check)
        active_floor: Decimal
        if self._config.drawdown_model == DrawdownModel.STATIC:
            active_floor = floor_static
        elif self._config.drawdown_model == DrawdownModel.TRAILING_EOD:
            active_floor = floor_trailing_eod
        else:  # TRAILING_INTRADAY
            active_floor = floor_trailing_intraday

        # --- 4. Per-strategy concurrency cap (RM-08) ---
        if signal.strategy_id in self._positions:
            decision = RiskDecision(
                approved=False,
                reason="concurrency_cap",
                adjusted_size=0,
            )
            decision = self._persist_and_return(
                decision=decision,
                signal=signal,
                state=state,
                now_utc=now_utc,
                current_equity=current_equity,
                floor_static=floor_static,
                floor_trailing_eod=floor_trailing_eod,
                floor_trailing_intraday=floor_trailing_intraday,
            )
            return decision

        # --- 5. Daily-DD circuit breaker (RM-04) ---
        # Halts new entries when realized + unrealized PnL drops to -daily_dd_limit.
        # Existing positions are NOT closed (kill-switch behavior vs. flatten).
        combined_pnl = state.realized_pnl_today + state.open_exposure_dollars
        if combined_pnl <= -self._config.daily_dd_limit:
            decision = RiskDecision(
                approved=False,
                reason="daily_dd_breaker",
                adjusted_size=0,
            )
            decision = self._persist_and_return(
                decision=decision,
                signal=signal,
                state=state,
                now_utc=now_utc,
                current_equity=current_equity,
                floor_static=floor_static,
                floor_trailing_eod=floor_trailing_eod,
                floor_trailing_intraday=floor_trailing_intraday,
            )
            return decision

        # --- 6. Position sizing (RM-01 / RM-06) ---
        risk_dollars = self._config.account_equity * self._config.max_risk_per_trade_pct
        stop_distance_points = abs(signal.entry - signal.stop)
        # Guard: zero or negative stop distance is invalid
        if stop_distance_points <= Decimal("0"):
            decision = RiskDecision(
                approved=False,
                reason="invalid_stop_distance",
                adjusted_size=0,
            )
            decision = self._persist_and_return(
                decision=decision,
                signal=signal,
                state=state,
                now_utc=now_utc,
                current_equity=current_equity,
                floor_static=floor_static,
                floor_trailing_eod=floor_trailing_eod,
                floor_trailing_intraday=floor_trailing_intraday,
            )
            return decision

        raw_size = size_for_stop(risk_dollars, stop_distance_points, self._instrument)
        proposed_size = min(raw_size, self._config.max_contracts)

        # --- 7. Worst-case loss check (RM-03) ---
        # worst_case_loss = stop_distance_points * point_value * proposed_size
        worst_case_loss = stop_distance_points * self._instrument.point_value * Decimal(proposed_size)
        if current_equity - worst_case_loss < active_floor:
            decision = RiskDecision(
                approved=False,
                reason="dd_floor_violation",
                adjusted_size=0,
            )
            decision = self._persist_and_return(
                decision=decision,
                signal=signal,
                state=state,
                now_utc=now_utc,
                current_equity=current_equity,
                floor_static=floor_static,
                floor_trailing_eod=floor_trailing_eod,
                floor_trailing_intraday=floor_trailing_intraday,
            )
            return decision

        # --- 8. All checks passed — approved ---
        decision = RiskDecision(
            approved=True,
            reason="approved",
            adjusted_size=proposed_size,
        )
        decision = self._persist_and_return(
            decision=decision,
            signal=signal,
            state=state,
            now_utc=now_utc,
            current_equity=current_equity,
            floor_static=floor_static,
            floor_trailing_eod=floor_trailing_eod,
            floor_trailing_intraday=floor_trailing_intraday,
        )
        return decision

    # ------------------------------------------------------------------
    # Internal persistence helper (SP-03 kill-9 guarantee)
    # ------------------------------------------------------------------

    def _persist_and_return(
        self,
        *,
        decision: RiskDecision,
        signal: Signal,
        state: RiskState,
        now_utc: datetime,
        current_equity: Decimal,
        floor_static: Decimal,
        floor_trailing_eod: Decimal,
        floor_trailing_intraday: Decimal,
    ) -> RiskDecision:
        """Persist risk_state + audit_event BEFORE the caller returns (SP-03).

        Both writes are synchronous (DuckDB is fast enough at intraday 1m rates).
        write_risk_state() is called FIRST; write_audit_event() SECOND.

        When store is None (unit tests), the method is a no-op.
        """
        if self._store is None:
            return decision

        # --- write_risk_state() FIRST (SP-03 ordering) ---
        now_date = now_utc.date()
        self._store.write_risk_state({
            "id": new_run_id(),
            "ts_utc": now_utc,
            "date": now_date,
            "session_id": self._session_id,
            "equity_dollars": current_equity,
            "realized_pnl_dollars": state.realized_pnl_today,
            "open_exposure_dollars": state.open_exposure_dollars,
            "hwm_static": self._hwm_static,
            "floor_static": floor_static,
            "hwm_trailing_eod": self._hwm_trailing_eod,
            "floor_trailing_eod": floor_trailing_eod,
            "hwm_trailing_intraday": self._hwm_trailing_intraday,
            "floor_trailing_intraday": floor_trailing_intraday,
        })

        # --- write_audit_event() SECOND (SP-03 ordering) ---
        self._store.write_audit_event(
            event_id=new_run_id(),
            ts_utc=now_utc,
            topic=TOPIC_RISK_DECISIONS,
            entity_id=signal.signal_id,
            reason_code=decision.reason,
            payload_json=decision.model_dump_json(),
        )

        return decision
