---
phase: 06-tradingview-mcp-bridge
plan: 01
subsystem: database
tags: [tv-bridge, mcp, duckdb, schema, asyncio, test-scaffolding]

# Dependency graph
requires:
  - phase: 05-risk-engine
    provides: DuckDBStore base class, audit_log/engine_state schema patterns, EventBus

provides:
  - tv_overlays and tv_alerts DuckDB tables (schema.sql DDL)
  - DuckDBStore TV writer methods (write_tv_overlay, write_tv_alert, mark_tv_alert_deleted, mark_tv_overlay_deleted, count_active_overlays, get_tv_alert_tv_id, list_overlays_older_than)
  - TVBridge class skeleton (constructor, start, stop, call_tool, _supervisor_loop stub) importable from tv_bridge package
  - Wave 0 test scaffolding for all Phase 6 task IDs (6 new test files)
  - draw_shape entity_id field name resolved and documented in 06-RESEARCH.md

affects: [06-02-plan, 06-03-plan, 06-04-plan]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - TVBridge constructor injection (store, bus, settings) — no subprocess spawn at init
    - Keyword-only DuckDBStore TV methods with parameterized ? binding (T-06-01-04)
    - asyncio.Future() stub in _supervisor_loop — holds context manager alive without blocking
    - Strict-xfail Wave 0 stubs — Plan 02/03/04 flip them green

key-files:
  created:
    - packages/trading-core/tests/storage/test_schema.py
    - packages/trading-core/tests/storage/test_duckdb_store.py
    - packages/tv-bridge/src/tv_bridge/bridge.py
    - packages/tv-bridge/tests/test_bridge.py
    - packages/tv-bridge/tests/test_overlay_registry.py
    - packages/tv-bridge/tests/test_replay_source.py
    - packages/tv-bridge/tests/test_reconciliation.py
    - packages/tv-bridge/tests/integration/__init__.py
    - packages/tv-bridge/tests/integration/test_tv_failure_isolation.py
    - packages/api/tests/test_tv_routes.py
    - .planning/research/spike-6/draw_shape_response.json
  modified:
    - packages/trading-core/src/trading_core/storage/schema.sql
    - packages/trading-core/src/trading_core/storage/duckdb_store.py
    - packages/tv-bridge/src/tv_bridge/__init__.py
    - packages/tv-bridge/tests/conftest.py
    - .planning/phases/06-tradingview-mcp-bridge/06-RESEARCH.md

key-decisions:
  - "draw_shape entity_id field confirmed as 'entity_id' from core/drawing.js line 34 (source-read fallback — live call not needed)"
  - "TVBridge _supervisor_loop uses asyncio.Future() stub in Wave 1 — no subprocess spawn until Plan 02"
  - "Strict xfail (strict=True) on all Wave 0 stubs — Plan 02/03/04 must flip them, cannot accidentally pass"
  - "Deleted tests/test_import.py — test_bridge_importable in test_bridge.py is a strict superset"

patterns-established:
  - "Pattern 1: TVBridge constructor injection — store/bus/settings injected; bridge never opens its own DuckDB connection"
  - "Pattern 2: Wave 0 xfail scaffolding — every Phase 6 task ID in VALIDATION.md gets a stub test file before production logic"
  - "Pattern 3: DuckDB TV writer methods — keyword-only, parameterized ? binding, module-level SQL constant"

requirements-completed: [TV-01, TV-02, TV-07]

# Metrics
duration: 10min
completed: 2026-05-19
---

# Phase 6 Plan 01: TradingView MCP Bridge Foundation Summary

**DuckDB tv_overlays + tv_alerts schema, 7 new DuckDBStore TV writer methods, importable TVBridge skeleton with asyncio supervisor stub, and 6 Wave 0 test files covering all Phase 6 task IDs from VALIDATION.md**

## Performance

- **Duration:** ~10 min
- **Started:** 2026-05-19T18:04:51Z
- **Completed:** 2026-05-19T18:14:17Z
- **Tasks:** 3
- **Files modified:** 15

## Accomplishments

- Added tv_overlays and tv_alerts CREATE TABLE IF NOT EXISTS blocks to schema.sql following established Phase 5 DDL conventions (TIMESTAMPTZ, uuid7 PK, deleted_at nullable for soft-delete)
- Added 7 keyword-only DuckDBStore methods using parameterized ? binding (T-06-01-04): write_tv_overlay, write_tv_alert, mark_tv_alert_deleted, mark_tv_overlay_deleted, count_active_overlays, get_tv_alert_tv_id, list_overlays_older_than
- Created TVBridge class skeleton: constructor (pure attribute setup, no subprocess), call_tool (safe: no session → None), _supervisor_loop (stub: asyncio.Future), start/stop lifecycle
- Resolved draw_shape entity_id field name from MCP server source (core/drawing.js line 34): confirmed `entity_id` — unblocks Plan 02
- Created 6 Wave 0 test files with strict-xfail stubs covering all 14 Phase 6 task IDs in VALIDATION.md

## DuckDBStore Methods Added

| Method | SQL Constant | Purpose |
|--------|-------------|---------|
| `write_tv_overlay(*, overlay_id, strategy_id, signal_id, shape_kind, shape_id, trading_date)` | `WRITE_TV_OVERLAY_SQL` | Insert one tv_overlays row |
| `write_tv_alert(*, alert_id, strategy_id, tv_alert_id, condition)` | `WRITE_TV_ALERT_SQL` | Insert one tv_alerts row |
| `mark_tv_alert_deleted(*, alert_id)` | `MARK_TV_ALERT_DELETED_SQL` | Set deleted_at on tv_alerts row |
| `mark_tv_overlay_deleted(*, overlay_id)` | (inline) | Set deleted_at on tv_overlays row |
| `count_active_overlays()` | `COUNT_ACTIVE_OVERLAYS_SQL` | Count tv_overlays WHERE deleted_at IS NULL |
| `get_tv_alert_tv_id(alert_id)` | `GET_TV_ALERT_TV_ID_SQL` | Return tv_alert_id for given alert_id |
| `list_overlays_older_than(trading_date)` | `LIST_OVERLAYS_OLDER_THAN_SQL` | Return (overlay_id, shape_id) for Plan 04 cleanup |

## TVBridge Surface Area

**Constructor:** `TVBridge(*, store: DuckDBStore, bus: EventBus, settings: Settings, mcp_server_path: Path | None = None)`
- Pure attribute setup — no subprocess spawn, no MCP connection
- Initializes `_session: ClientSession | None = None`, `_session_lock`, `_draw_semaphore(3)`, `_stderr_capture`, `_supervisor_task: None`

**Public methods:**
- `is_connected` property: `_session is not None`
- `async call_tool(tool, args) -> dict | None`: safe call — returns None if no session, on timeout, or exception
- `async start()`: spawns `_supervisor_loop()` as asyncio.Task
- `async stop()`: cancels supervisor task, clears session

**Module constants:** `_DEFAULT_MCP_SERVER_PATH`, `_SYMBOL_MAP`, `_SYMBOL_ALLOWLIST`, `_INIT_TIMEOUT_SECONDS`, `_TOOL_TIMEOUT_SECONDS`

**Wave 1 stubs (Plan 02 replaces):** `_supervisor_loop` body is `await asyncio.Future()` — no subprocess spawned.

## draw_shape entity_id Field Name

**Resolution method:** Source-read fallback (live TV call not required)  
**Source:** `C:\Users\Admin\tradingview-mcp-jackson\src\core\drawing.js` line 34  
**Code:** `return { success: true, shape, entity_id: result?.entity_id };`  
**Confirmed field name:** `entity_id`  
**Plan 02 binding:** `tv_overlays.shape_id = response["entity_id"]`  
**Open Question 1 status:** RESOLVED — Assumption A1 confirmed.

## Test File Inventory

| File | Tests | Type | Flip Plan |
|------|-------|------|-----------|
| `packages/trading-core/tests/storage/test_schema.py` | 2 | real (pass) | — |
| `packages/trading-core/tests/storage/test_duckdb_store.py` | 6 | real (pass) | — |
| `packages/tv-bridge/tests/test_bridge.py` | 3 real + 3 xfail | mixed | Plan 02 flips xfails |
| `packages/tv-bridge/tests/test_overlay_registry.py` | 3 xfail | strict-xfail | Plan 02 (×2) + Plan 04 (×1) |
| `packages/tv-bridge/tests/test_replay_source.py` | 1 xfail | strict-xfail | Plan 03 |
| `packages/tv-bridge/tests/test_reconciliation.py` | 2 xfail | strict-xfail | Plan 03 |
| `packages/tv-bridge/tests/integration/test_tv_failure_isolation.py` | 1 skip | skip | Plan 04 |
| `packages/api/tests/test_tv_routes.py` | 2 xfail | strict-xfail | Plan 02 |

**Total Wave 1 test result:** 11 real pass, 1 skip, 11 xfailed — 0 failures.

## Task Commits

1. **Task 1: Add tv_overlays + tv_alerts DDL and DuckDBStore writer methods** — `bc16521` (feat)
2. **Task 2: TVBridge class skeleton + tv_bridge package wiring** — `54c218a` (feat)
3. **Task 3: Wave 0 test scaffolding + draw_shape entity_id verification** — `4cd14b4` (feat)

## Deviations from Plan

### Minor: strict=True count in 4 files = 8 (plan said >= 9)

- **Found during:** Task 3 acceptance criterion verification
- **Issue:** Plan acceptance criterion says the count of `strict=True` across 4 specific files (test_overlay_registry.py, test_replay_source.py, test_reconciliation.py, test_tv_routes.py) should be >= 9, but the explicitly enumerated stubs from VALIDATION.md sum to 8 (3+1+2+2). The plan appears to have a counting error.
- **Resolution:** All 8 stubs in those 4 files have `strict=True` applied correctly. The spirit of the requirement is satisfied — every stub enforces its plan (Plan 02/03/04) must implement it. With test_bridge.py included the total is 11.
- **Impact:** None on functionality or correctness. All stubs are properly marked strict-xfail.

No other deviations — plan executed essentially as written.

## Issues Encountered

None — all tests passed on first run, no debugging iterations required.

## Next Phase Readiness

Plan 02 (Wave 2) can proceed immediately:
- `tv_overlays` and `tv_alerts` tables ready in DuckDB
- `DuckDBStore` writer methods available for Plan 02's overlay registry
- `TVBridge._supervisor_loop` stub ready to be replaced with full reconnect loop
- `_SYMBOL_ALLOWLIST` and `_SYMBOL_MAP` already declared in bridge.py
- `entity_id_field: entity_id` documented in 06-RESEARCH.md — no blocking ambiguity
- All Plan 02 test stubs exist as strict-xfail in test_bridge.py and test_overlay_registry.py

## Self-Check: PASSED

---
*Phase: 06-tradingview-mcp-bridge*
*Completed: 2026-05-19*
