# Integration Check - ES Futures Trading System v1

Date: 2026-05-21
Scope: All 9 phases (trading-core, api, tv-bridge, web)

## Summary

Check 1 EventBus signal->risk->fill: PARTIAL - Wired in BacktestEngine only; no live TOPIC_SIGNALS publisher
Check 2 ORBStrategy -> BacktestEngine: WIRED - BacktestEngine.run() calls strategy.on_bar() and _push_bar()
Check 3 TVBridge subscribes TOPIC_SIGNALS: WIRED - bridge.py subscribes; tasks started on app startup
Check 4 PUT /strategies params hot-reload: PARTIAL - Publishes TOPIC_STRATEGY_RELOAD; stored but not consumed
Check 5 DuckDB single-writer guard: PARTIAL - _LockedConn thread-safe; no process-level guard
Check 6 CI pytest across all packages: WIRED - ci.yml + pyproject.toml testpaths cover all three packages
Check 7 WS /stream mirrors EventBus: WIRED - ConnectionManager subscribes all 9 topics
Check 8 EodScheduler startup wiring: WIRED - Instantiated and asyncio.create_task in lifespan

## BLOCKER

POST /backtests/run does not call BacktestEngine
File: packages/api/src/api/routes/strategies.py lines 99-125
_run_backtest_task comment says BacktestEngine wiring is Phase 8 scope.
Sleeps 2 seconds then marks run complete with no trades or metrics written.
D-01 and D-15 are not satisfied end-to-end.

## Details

1. EventBus signal->risk->fill - PARTIAL
   BacktestEngine.run() engine.py line 238 calls risk_manager.check(signal, state).
   The chain signal->risk->fill IS wired for the backtest path.
   TOPIC_AUDIT events are published at risk_decision and fill points when bus is provided.
   Grep for publish.*TOPIC_SIGNALS in packages/trading-core/src and packages/api/src: zero results.
   TOPIC_SIGNALS only defined in events/models.py, re-exported in events/__init__.py,
   subscribed in api/ws.py (fan-out) and tv_bridge/bridge.py (draw).
   No live bar-polling or live strategy execution engine in the API process.
   TVBridge _subscribe_signals and WS TOPIC_SIGNALS fan-out receive no events in normal operation.

2. ORBStrategy -> BacktestEngine - WIRED
   engine.py lines 217-220: signal = strategy.on_bar(bar, ctx) then strategy._push_bar(bar).
   Correct lookahead-safe ordering preserved.
   StrategyRegistry.load() returns ORBStrategy used by tests and optimization worker.

3. TVBridge -> EventBus TOPIC_SIGNALS - WIRED
   bridge.py line 310: async with self._bus.subscribe(TOPIC_SIGNALS) as sub
   bridge.start() spawns _subscribe_signals as tv_bridge.sig_sub asyncio task.
   app.py lifespan calls await _tv_bridge_ref.start() at line 181.
   Fire-and-forget asyncio.create_task(_safe_draw_signal(event)) keeps bus dispatch non-blocking.

4. PUT /strategies params hot-reload - PARTIAL
   strategies.py line 229: publishes TOPIC_STRATEGY_RELOAD after writing YAML.
   app.py _strategy_reload_handler calls StrategyRegistry.load(yaml_path) directly (line 247)
   NOT StrategyRegistry.reload(strategy_id, strategies_dir).
   StrategyRegistry.reload() at registry.py lines 87-120 is never called - dead code.
   Reloaded strategy stored on app.state.strategies[strategy_id] (line 250).
   No live engine, route, or background task reads from app.state.strategies.

5. DuckDB single-writer guard - PARTIAL
   duckdb_store.py: No code-level enforcement; constraint is documented only.
   _LockedConn (lines 37-59): threading.Lock serializes concurrent FastAPI requests.
   No process-level lock prevents concurrent subprocess DuckDBStore instances.

6. Phase 8 CI - WIRED
   .github/workflows/ci.yml triggers on push/PR to master/main.
   Runs: uv run pytest --tb=short -q from repo root.
   pyproject.toml testpaths covers all three packages.
   Frontend job: pnpm --filter web exec vitest run.

7. WS /stream -> EventBus - WIRED
   ws.py ConnectionManager.start_background_fan_out() subscribes all 9 topics.
   app.py lifespan line 107: asyncio.create_task(manager.start_background_fan_out()).
   WS route (app.py line 351): drains per-client asyncio.Queue and sends JSON.
   useStream.ts handles bars, degraded_state, engine_state_changed, positions.

8. EodScheduler wiring - WIRED
   app.py lifespan lines 169-170: EodScheduler + asyncio.create_task.
   Task cancelled on shutdown (app.py line 288).
   Caveat: _eod_flatten writes audit record only - no actual flatten call.

## Warnings

WARNING 1 - Hot-reloaded strategy stored but not consumed
File: packages/api/src/api/app.py lines 247-250
app.state.strategies updated on TOPIC_STRATEGY_RELOAD but no consumer exists.
D-14 hot-reload has zero effect on any running strategy.

WARNING 2 - StrategyRegistry.reload() is dead code
File: packages/trading-core/src/trading_core/strategy/registry.py lines 87-120
Production handler calls StrategyRegistry.load() directly; .reload() never called.

WARNING 3 - No live TOPIC_SIGNALS publisher
Signal->risk->fill chain on EventBus only exists inside BacktestEngine.run().
No live bar polling or live strategy execution engine publishes to TOPIC_SIGNALS.

WARNING 4 - EOD flatten is a no-op stub
File: packages/api/src/api/app.py line 151
EodScheduler fires at EOD; callback writes audit record only. No positions flattened.

## Requirements Integration Map

D-01 backtest run listing: PARTIAL - POST /backtests/run is a stub; BacktestEngine not called
D-02 per-trade attribution: WIRED - BacktestEngine driver loop builds 17-field trade_dict
D-04/D-05/D-06 WS mirror: WIRED - All 9 topics with type/seq/payload envelope
D-10 kill switch: WIRED - POST /kill -> FullRiskManager.set_killed() -> asyncio.Event -> check(); DuckDB bootstrap confirmed
D-14 strategy hot-reload: PARTIAL - Stored on app.state.strategies but no live engine consumes it
D-15 background backtest job: PARTIAL - _run_backtest_task is a stub; BacktestEngine not called
RM-07 EOD scheduler: PARTIAL - Fires correctly; flatten callback is a no-op
TV-01 TVBridge supervised session: WIRED - Full backoff reconnect + subscriber tasks confirmed
SP-06 WS gap detection: WIRED - ConnectionManager _seq + useStream gap check both implemented

Self-contained requirements (no cross-phase wiring needed):
FND-01 Settings/config: api imports trading_core.config - verified
BT-04 VBT metrics: internal to BacktestEngine.run() VBT pass
RM-01 ATR sizing: FullRiskManager.size_for_stop() - unit-tested, called within check()
