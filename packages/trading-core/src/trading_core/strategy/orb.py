"""Opening Range Breakout (ORB) strategy — Plan 02-02.

ORBStrategy implements the Strategy protocol structurally (no inheritance required).
It reads its configuration from an ORBConfig dataclass, which is populated from
config/strategies/orb.yaml by StrategyRegistry.

Look-ahead safety:
    The strategy never reads its own indicator values inside on_bar. Instead, the
    driver (test or backtester) builds a StrategyContext from indicator snapshots
    BEFORE the current bar, passes it to on_bar, then calls _push_bar AFTER.

    The correct driver loop:
        for bar in bars:
            ctx = StrategyContext(
                rollover_seam=bar.rollover_seam,
                warmup_complete=strategy.is_warm(),
                bar_index=strategy._bar_count,
                ts_utc=bar.ts_utc,
                atr=strategy._atr.current,      # prior-bar ATR snapshot
                session_vwap=strategy._vwap.current,
                ema=strategy._ema.current,
                adr=None,
            )
            signal = strategy.on_bar(bar, ctx)
            strategy._push_bar(bar)             # push AFTER on_bar

Critical invariants:
    1. rollover_seam guard fires FIRST (before any state mutation)
    2. Session state resets on ET date change (idempotent)
    3. At most ONE signal per RTH session (_signal_fired flag)
    4. stop is computed from ctx.atr (prior-bar ATR), never current-bar ATR
    5. All params come from ORBConfig (no Python-side fallback defaults in logic)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from zoneinfo import ZoneInfo

from trading_core.data.models import Bar
from trading_core.indicators import ATRWilder, EMA, SessionVWAP
from trading_core.strategy.models import Signal, StrategyContext

_ET = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class ORBConfig:
    """Immutable configuration for ORBStrategy.

    All params map 1:1 to YAML keys under the `params:` block in
    config/strategies/orb.yaml. Frozen so accidental mutation raises.

    Phase 5 will add instrument tick_size here; for now min_range_ticks is
    stored but tick validation is deferred (see TODO in on_bar).
    """

    strategy_id: str = "orb-v1"
    strategy_version: str = "1.0"
    opening_range_minutes: int = 15
    atr_period: int = 14
    atr_stop_mult: float = 1.5
    r_target: float = 2.0
    ema_period: int = 20
    min_range_ticks: int = 2


class ORBStrategy:
    """Opening Range Breakout strategy.

    Structurally satisfies the Strategy protocol (name, version, warmup_bars,
    on_bar). Does NOT inherit from any base class — pure structural matching.

    Session state resets whenever the ET calendar date changes. This handles
    multi-day runs correctly without external session tracking.

    The strategy is stateful (indicators, ORB levels, signal flag). Instances
    should not be shared across concurrent backtest runs.
    """

    # Class-level defaults; version is overridden from config in __init__
    name: str = "opening_range_breakout"
    version: str = "1.0"

    def __init__(self, config: ORBConfig) -> None:
        self._config = config
        self.version = config.strategy_version

        # Internal indicators — receive bars via _push_bar (AFTER on_bar)
        self._atr = ATRWilder(config.atr_period)
        self._vwap = SessionVWAP()
        self._ema = EMA(config.ema_period)

        # Cumulative bar counter (bar_index in ctx)
        self._bar_count: int = 0

        # Session-level state — reset on each new ET date
        self._session_date: date | None = None
        self._orb_high: Decimal | None = None
        self._orb_low: Decimal | None = None
        self._orb_bars: int = 0
        self._signal_fired: bool = False

    # ------------------------------------------------------------------
    # Strategy protocol methods
    # ------------------------------------------------------------------

    def warmup_bars(self) -> int:
        """Minimum bars needed before signals can fire (delegates to ATRWilder)."""
        return self._atr.warmup_bars()

    def is_warm(self) -> bool:
        """True once ATRWilder has a non-None value (warmup_bars pushed)."""
        return self._atr.is_warm

    def _push_bar(self, bar: Bar) -> None:
        """Push bar to all internal indicators and increment bar counter.

        MUST be called by the driver AFTER on_bar, never inside it.
        This is the mechanism that enforces look-ahead safety.
        """
        self._atr.push(bar)
        self._vwap.push(bar)
        self._ema.push(bar)
        self._bar_count += 1

    def on_bar(self, bar: Bar, ctx: StrategyContext) -> Signal | None:
        """Consume one bar and optionally emit a Signal.

        Logic order (strictly enforced):
          1. rollover_seam guard — return None before ANY state mutation
          2. Session reset on ET date change
          3. warmup guard — return None if not warm
          4. ORB window — collect first opening_range_minutes bars
          5. one-signal guard — return None after first signal in session
          6. Long breakout check
          7. Short breakout check
          8. return None (no breakout)

        ctx.atr MUST be the ATR snapshot from BEFORE this bar (driver
        guarantees this by reading strategy._atr.current before _push_bar).
        """
        # --- Guard 1: rollover seam (FIRST — before any state mutation) ---
        if ctx.rollover_seam:
            return None

        # --- Step 2: session reset on ET date change ---
        et_date: date = bar.ts_utc.astimezone(_ET).date()
        if et_date != self._session_date:
            self._session_date = et_date
            self._orb_high = None
            self._orb_low = None
            self._orb_bars = 0
            self._signal_fired = False

        # --- Step 3+4: ORB window runs concurrently with warmup ---
        # Track ORB high/low unconditionally during the first opening_range_minutes
        # bars of each session. We must collect these even while the indicator
        # warmup is still in progress, because warmup_bars == opening_range_minutes
        # when atr_period == opening_range_minutes (both = 15 in the default config).
        # If we guarded on warmup first, ORB levels would never be populated.
        if self._orb_bars < self._config.opening_range_minutes:
            if self._orb_high is None or bar.high > self._orb_high:
                self._orb_high = bar.high
            if self._orb_low is None or bar.low < self._orb_low:
                self._orb_low = bar.low
            self._orb_bars += 1
            return None

        # --- Guard 3: warmup (after ORB window so indicators don't block ORB collection) ---
        if not ctx.warmup_complete:
            return None

        # --- Guard 5: one signal per session ---
        if self._signal_fired:
            return None

        # --- Guards 6+7: require ORB levels and ATR ---
        if self._orb_high is None or self._orb_low is None:
            return None
        if ctx.atr is None:
            return None

        # TODO (Phase 5): enforce min_range_ticks validation once instruments.py
        # tick_size is wired into ORBConfig. For now the field is stored but
        # tick width check is deferred to avoid hardcoding tick_size = 0.25.

        atr_stop_mult = Decimal(str(self._config.atr_stop_mult))
        r_target = Decimal(str(self._config.r_target))

        # --- Step 6: long breakout ---
        if bar.close > self._orb_high and bar.close > bar.open:
            entry = self._orb_high
            stop = entry - ctx.atr * atr_stop_mult
            if stop <= Decimal("0"):
                return None  # degenerate stop — skip
            risk = entry - stop
            target = entry + r_target * risk
            self._signal_fired = True
            return Signal(
                strategy_id=self._config.strategy_id,
                strategy_version=self._config.strategy_version,
                ts_utc=bar.ts_utc,
                side="long",
                entry=entry,
                stop=stop,
                target=target,
                size_hint=Decimal("1"),
            )

        # --- Step 7: short breakout ---
        if bar.close < self._orb_low and bar.close < bar.open:
            entry = self._orb_low
            stop = entry + ctx.atr * atr_stop_mult
            risk = stop - entry
            target = entry - r_target * risk
            if target <= Decimal("0"):
                return None  # degenerate target — skip
            self._signal_fired = True
            return Signal(
                strategy_id=self._config.strategy_id,
                strategy_version=self._config.strategy_version,
                ts_utc=bar.ts_utc,
                side="short",
                entry=entry,
                stop=stop,
                target=target,
                size_hint=Decimal("1"),
            )

        return None
