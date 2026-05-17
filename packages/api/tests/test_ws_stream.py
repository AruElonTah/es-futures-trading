"""Wave 0 placeholder for FastAPI WebSocket stream tests — SP-01, D-04, D-05.

Requirements:
  SP-01 — asyncio pub/sub routes Signal → RiskManager → Executor → Fill via EventBus.
  D-04 — WS /stream mirrors all 7 EventBus topics: bar_received, signal_emitted,
          risk_decision, fill_executed, position_update, equity_update, degraded_state.
  D-05 — Message envelope is {"type": "<event_type>", "payload": {...}}.
          'type' uses snake_case event name (matching EventBus topic constants).
          'payload' is the serialized Pydantic model.

Analog: packages/trading-core/tests/test_event_bus.py (async test + EventBus pattern)

This file is a Wave 0 stub. Wave 4 Plan 04 implements WS /stream and the
ConnectionManager and fills in the real WebSocket integration tests.
"""

import pytest


@pytest.mark.xfail(reason="Wave 4 Plan 04 — not yet implemented", strict=True)
def test_placeholder_until_wave_4():
    raise NotImplementedError
