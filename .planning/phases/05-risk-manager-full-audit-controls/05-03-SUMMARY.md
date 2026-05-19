---
phase: "05"
plan: "03"
subsystem: backtest-engine-audit-wiring
tags: [backtest, audit, event-bus, risk-state, topic-routing]
dependency_graph:
  requires:
    - DrawdownModel enum from trading_core.risk.models (05-01)
    - RiskState Phase 5 fields — realized_pnl_today, equity_high_water, open_exposure_dollars (05-01)
    - TOPIC_AUDIT, TOPIC_ENGINE_STATE, TOPIC_FILLS, TOPIC_RISK_DECISIONS from events/models.py (05-01)
    - Fill.fill_id UUID7 field from execution/models.py (05-01)
    - FullRiskManager.record_position_open/closed methods (05-02)
    - EventBus.publish(topic, payload) routing (Phase 1)
  provides:
    - BacktestEngine.run() with optional bus=None parameter
    - Populated RiskState (not bare defaults) on every risk_manager.check() call
    - TOPIC_AUDIT events published at risk_decision/entry_fill/exit_fill when bus is set
    - hasattr-guarded record_position_open/record_position_closed calls in driver loop
    - EventBus.publish_engine_state(state) helper on TOPIC_ENGINE_STATE
    - TOPIC_AUDIT and TOPIC_ENGINE_STATE re-exported from events/__init__.py
  affects:
    - Phase 5 plans 04-05 (API routes, blotter, EOD flatten) consume the bus wiring
    - Integration tests that pass bus to BacktestEngine will receive live audit events
tech_stack:
  added: []
  patterns:
    - bus=None sentinel pattern — bus.publish() only called when bus is not None
    - getattr chain for _config.drawdown_model with DrawdownModel.TRAILING_INTRADAY default
    - hasattr guard for record_position_open/closed — backward compat with PassThroughRiskManager
    - async def test methods with await — pytest-asyncio asyncio_mode=auto pattern (replaces deprecated asyncio.get_event_loop().run_until_complete)
key_files:
  created: []
  modified:
    - packages/trading-core/src/trading_core/backtest/engine.py
    - packages/trading-core/src/trading_core/events/bus.py
    - packages/trading-core/src/trading_core/events/__init__.py
    - packages/trading-core/tests/risk/test_full_risk_manager.py
decisions:
  - "bus=None sentinel chosen over always-required EventBus — existing unit tests pass None and are not burdened with bus setup"
  - "TOPIC_AUDIT publish is notification-only; DuckDB writes are owned exclusively by FullRiskManager.check() (synchronous, kill-9 safe)"
  - "EventBus.publish() uses defaultdict — no allowlist needed; TOPIC_AUDIT and TOPIC_ENGINE_STATE route automatically"
  - "publish_engine_state() added as method on EventBus (not standalone) for discoverability and consistent ts_utc injection"
  - "asyncio_mode=auto means test classes with async methods work without @pytest.mark.asyncio — converted 24 sync tests using deprecated run_until_complete()"
metrics:
  duration: "~18m"
  completed_date: "2026-05-18"
  tasks_completed: 2
  files_changed: 4
---

# Phase 05 Plan 03: Backtest Engine Audit Wiring Summary

**One-liner:** BacktestEngine driver loop wired to publish TOPIC_AUDIT events at risk_decision/fill points with populated RiskState, plus EventBus.publish_engine_state() helper added for WS envelope delivery.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Populate RiskState + emit TOPIC_AUDIT events in BacktestEngine driver loop | 5af9a28 | engine.py, execution/models.py, test_full_risk_manager.py |
| 2 | Verify EventBus TOPIC_AUDIT/TOPIC_ENGINE_STATE routing + publish_engine_state helper | c6b1159 | events/bus.py, events/__init__.py |

## What Was Built

### Task 1 — BacktestEngine Audit Wiring

**RiskState population (CHANGE 1):**

Before every `risk_manager.check()` call, the driver loop now builds a populated `RiskState` from its own tracking variables rather than using bare defaults:

```python
_dm = getattr(getattr(risk_manager, '_config', None), 'drawdown_model',
              DrawdownModel.TRAILING_INTRADAY)
state = RiskState(
    realized_pnl_today=Decimal(str(realized_equity - init_cash)),
    equity_high_water=Decimal(str(realized_equity)),
    open_exposure_dollars=Decimal("0"),
    drawdown_model=_dm,
)
```

`realized_equity` accumulates all closed-trade PnL; `open_exposure_dollars=0` is correct because the gate above (`open_position is None`) ensures no position is open at signal time. `equity_high_water` uses `realized_equity` — the HWM within check() will ratchet it further for TRAILING_INTRADAY.

**bus=None parameter (CHANGE 2):**

`BacktestEngine.run()` now accepts `bus=None`. When a bus is provided, TOPIC_AUDIT events are published at three points:
- After `risk_manager.check()`: `{topic: TOPIC_RISK_DECISIONS, entity_id: signal.signal_id, reason_code: decision.reason, payload_json: ...}`
- After `executor.fill_entry()`: `{topic: TOPIC_FILLS, entity_id: entry_fill.fill_id, reason_code: "entry_fill", payload_json: ...}`
- After `executor.fill_exit()`: `{topic: TOPIC_FILLS, entity_id: exit_fill.fill_id, reason_code: exit_reason, payload_json: ...}`

**Important:** These bus publishes are notification-only for WebSocket delivery. DuckDB audit writes are owned exclusively by `FullRiskManager.check()` (synchronous, before returning — SP-03 kill-9 guarantee). No bus subscriber writes to DuckDB.

**record_position_open/closed (CHANGE 3):**

After entry fill success:
```python
if hasattr(risk_manager, 'record_position_open'):
    _position_info = {"symbol": self._symbol, "strategy_id": ..., "side": ..., ...}
    risk_manager.record_position_open(signal.strategy_id, _position_info)
```

After exit fill success:
```python
if hasattr(risk_manager, 'record_position_closed'):
    risk_manager.record_position_closed(sig.strategy_id)
```

The `hasattr` guard preserves backward compatibility with `PassThroughRiskManager` (which lacks these methods) while fully wiring `FullRiskManager`'s concurrency-cap tracking.

**Import additions (CHANGE 4):**
- `from trading_core.risk.models import DrawdownModel`
- `from trading_core.events.models import TOPIC_AUDIT, TOPIC_FILLS, TOPIC_RISK_DECISIONS`

`fill_id` was already present on the `Fill` model (added in 05-01 preparation), so no model changes were needed there.

### Task 2 — EventBus TOPIC_AUDIT and TOPIC_ENGINE_STATE

**EventBus routing confirmation:**

`EventBus.publish()` uses a `defaultdict(list)` keyed on topic strings. Any string topic auto-registers on `subscribe()` — no allowlist exists. TOPIC_AUDIT and TOPIC_ENGINE_STATE route correctly without any code change to the publish/subscribe core.

**publish_engine_state() helper:**

```python
async def publish_engine_state(self, state: str) -> None:
    await self.publish(
        TOPIC_ENGINE_STATE,
        {
            "type": "engine_state_changed",
            "payload": {
                "state": state,
                "ts_utc": datetime.now(tz=timezone.utc).isoformat(),
            },
        },
    )
```

Emits the WS envelope format expected by the blotter panel (Plan 05): `{type: engine_state_changed, payload: {state, ts_utc}}`. Callers use literals `'running' | 'killed' | 'paused' | 'flatten_requested'` matching the engine_state DuckDB table schema (D-11).

**events/__init__.py re-export:**

`TOPIC_AUDIT` and `TOPIC_ENGINE_STATE` added to the package-level `__all__` so downstream callers can do `from trading_core.events import TOPIC_AUDIT`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] 24 test methods in test_full_risk_manager.py used deprecated asyncio.get_event_loop().run_until_complete()**
- **Found during:** Task 1 full test suite run (pre-existing failure, not introduced by this plan)
- **Issue:** Python 3.12 raises `RuntimeError: There is no current event loop` when `asyncio.get_event_loop()` is called after pytest-asyncio has cleaned up the prior test's event loop. The failure was intermittent (passed in isolation, failed when run after other async test classes).
- **Fix:** Converted all 24 test methods that called `asyncio.get_event_loop().run_until_complete(rm.check(...))` to `async def` methods using `await rm.check(...)`. pytest-asyncio `asyncio_mode=auto` handles auto-awaiting without any decorator changes.
- **Files modified:** `packages/trading-core/tests/risk/test_full_risk_manager.py`
- **Commit:** 5af9a28

## Success Criteria Verification

- [x] BacktestEngine.run() accepts optional `bus=None` parameter
- [x] RiskState populated with realized P&L, equity_high_water, open_exposure_dollars, drawdown_model before each check() call
- [x] TOPIC_AUDIT events published at risk_decision/entry_fill/exit_fill when bus is not None
- [x] DuckDB audit writes owned exclusively by FullRiskManager.check() — no bus subscriber writes to DuckDB (notification-only per must_haves)
- [x] record_position_open/closed called with hasattr guard (backward compat with PassThroughRiskManager)
- [x] EventBus TOPIC_AUDIT routing verified: `TOPIC_AUDIT routing: OK`
- [x] EventBus TOPIC_ENGINE_STATE routing verified: `TOPIC_ENGINE_STATE routing + publish_engine_state: OK`
- [x] publish_engine_state() helper added to EventBus
- [x] All existing tests pass: 410 passed (non-integration suite)
- [x] is_last_rth_bar logic unchanged — EOD flatten in backtest confirmed operational

## Known Stubs

None. All wiring is fully implemented. The `bus` parameter is optional by design — callers without a live bus pass `None` and the engine operates identically to the pre-Phase-5 behavior.

## Threat Flags

None. No new network endpoints, auth paths, or file access patterns introduced. Threat mitigations applied:
- T-05-03-03 (RiskState tampering): mitigated — state built from driver loop's own `realized_equity` tracking variable; no external input
- T-05-03-04 (Bus subscriber writing duplicate DuckDB rows): mitigated — explicit code comment + documentation. Bus publish is notification-only; FullRiskManager.check() owns all DuckDB writes.

## Self-Check: PASSED

- engine.py FOUND with all 4 changes: bus=None param, populated RiskState, TOPIC_AUDIT publishes, hasattr-guarded record_position calls
- bus.py FOUND with publish_engine_state() method
- events/__init__.py FOUND with TOPIC_AUDIT and TOPIC_ENGINE_STATE in __all__
- test_full_risk_manager.py FOUND with 0 remaining asyncio.get_event_loop().run_until_complete() calls
- Commit 5af9a28 (Task 1): FOUND in git log
- Commit c6b1159 (Task 2): FOUND in git log
- 410 tests pass: Confirmed
