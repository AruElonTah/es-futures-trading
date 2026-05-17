"""PassThroughRiskManager — minimal pass-through RiskManager for Phase 3.

Structurally satisfies the RiskManager Protocol from risk/protocols.py.
Always approves signals; clamps adjusted_size to RiskConfig.max_contracts.

Phase 5 replaces this with the prop-firm-style RiskManager (daily DD limit,
max_contracts_per_strategy, equity high-water mark checks) — see T-03-02-05
for the accepted-risk rationale during Phase 3 (paper-only, single-operator).

D-10: RiskDecision returns approved=True, reason='pass_through',
      adjusted_size=min(int(signal.size_hint), config.max_contracts).

Do NOT add risk rejection logic here — this class is intentionally a stub.
All rejection logic belongs in the Phase 5 RiskManager implementation.
"""

from __future__ import annotations

from trading_core.logging import get_logger
from trading_core.risk.models import RiskConfig, RiskDecision, RiskState
from trading_core.strategy.models import Signal

log = get_logger(__name__)


class PassThroughRiskManager:
    """Minimal pass-through RiskManager — always approves, clamps size (D-10, Phase 3).

    Structurally satisfies the RiskManager Protocol. No inheritance.

    ACCEPTED RISK (T-03-02-05): This class never rejects a signal. Phase 3 is
    paper-only single-operator; no capital is at risk. Phase 5 adds:
      - Daily drawdown circuit breaker
      - Max contracts per strategy cap
      - Equity high-water mark tracking
      - Per-trade risk % cap
    """

    def __init__(self, config: RiskConfig) -> None:
        self._config = config

    async def check(self, signal: Signal, state: RiskState) -> RiskDecision:
        """Approve the signal and clamp size to max_contracts.

        Always returns approved=True regardless of state.realized_pnl_today.
        Phase 5 adds rejection logic against this seam.
        """
        adjusted_size = min(int(signal.size_hint), self._config.max_contracts)
        log.debug(
            "risk.pass_through",
            signal_id=signal.signal_id,
            approved=True,
            adjusted_size=adjusted_size,
            size_hint=str(signal.size_hint),
            max_contracts=self._config.max_contracts,
        )
        return RiskDecision(
            approved=True,
            reason="pass_through",
            adjusted_size=adjusted_size,
        )
