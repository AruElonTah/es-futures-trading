---
phase: 06-tradingview-mcp-bridge
plan: "04"
subsystem: tv-bridge
tags: [tv-bridge, cleanup, frontend, integration-test, checkpoint]
completed: "2026-05-19T20:55:54Z"
duration_minutes: 65

dependency_graph:
  requires: [06-01, 06-02, 06-03]
  provides: [nightly-overlay-cleanup, tv-failure-isolation-test, author-tv-alert-ui]
  affects: [api-lifespan, blotter-page, audit-log, tv-overlays]

tech_stack:
  added:
    - NightlyCleanupScheduler: EodScheduler wrapper firing at 03:00 ET daily
    - nightly_cleanup coroutine: pandas_market_calendars CME_Equity calendar for 5-trading-day retention
    - AuthorTVAlertButton: Next.js 'use client' React component, native fetch + useState toast
  patterns:
    - EodScheduler wrapping pattern (same as ReconciliationScheduler in Plan 03)
    - asyncio.wait_for(timeout=10.0) for test deadline enforcement without pytest-timeout
    - Best-effort MCP call with cleanup_partial audit row on failure

key_files:
  created:
    - packages/tv-bridge/src/tv_bridge/cleanup.py
    - apps/web/components/AuthorTVAlertButton.tsx
  modified:
    - packages/tv-bridge/src/tv_bridge/__init__.py
    - packages/tv-bridge/tests/test_overlay_registry.py
    - packages/tv-bridge/tests/integration/test_tv_failure_isolation.py
    - packages/api/src/api/app.py
    - apps/web/app/dashboard/blotter/page.tsx

decisions:
  - "NightlyCleanupScheduler wraps EodScheduler(close_time_et=03:00, lead_seconds=0) — same pattern as ReconciliationScheduler; no calendar-aware fire check needed since flatten-on-non-trading-day is harmless"
  - "BLOCKER 5 fix: asyncio.wait_for(pipeline_complete.wait(), timeout=10.0) enforces 10s deadline inside test body; pytest-timeout NOT added to project deps (not in CLAUDE.md testing stack)"
  - "AuthorTVAlertButton uses hardcoded ORB defaults in Phase 6; TODO(Phase 7 UI-07) markers added in both component and blotter page for traceability when live strategy registry is wired"
  - "Task 3 checkpoint auto-approved: workflow.auto_advance=true; Step 5 (TV crash isolation) proven by test_pipeline_continues_when_tv_killed integration test"

metrics:
  tasks_completed: 3
  tasks_total: 3
  commits: 2
  files_created: 2
  files_modified: 5
---

# Phase 6 Plan 04: Nightly Cleanup + Failure Isolation Test + AuthorTVAlertButton Summary

Nightly overlay cleanup scheduler (03:00 ET, 5-trading-day retention via CME_Equity calendar), end-to-end TV failure isolation integration test proving zero pipeline skips under forced disconnect, and AuthorTVAlertButton frontend component closing Phase 6's TV-07 requirement.

## Tasks Completed

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| 1 | nightly_cleanup + NightlyCleanupScheduler + lifespan wiring + integration test | fb3038c | cleanup.py (new), __init__.py, test_overlay_registry.py, test_tv_failure_isolation.py, app.py |
| 2 | AuthorTVAlertButton frontend component + blotter integration | c7e2da8 | AuthorTVAlertButton.tsx (new), blotter/page.tsx |
| 3 | Human-verify checkpoint | auto-approved | 06-04-CHECKPOINT-NOTES.md |

## What Was Built

### Task 1: Nightly Overlay Cleanup

`packages/tv-bridge/src/tv_bridge/cleanup.py`:
- `nightly_cleanup(bridge, store, today, retention_trading_days=5)` async coroutine
- `_trading_days_ago(today, n)` uses `pandas_market_calendars.get_calendar("CME_Equity")` to correctly skip weekends and US market holidays; conservative fallback for edge-case dates
- Per expired overlay: calls `bridge.call_tool("draw_remove_one", {"entity_id": shape_id})` best-effort; if it returns None, writes `cleanup_partial` audit row with shape_id (T-06-04-06 repudiation mitigation)
- Always calls `store.mark_tv_overlay_deleted(overlay_id=overlay_id)` regardless of MCP outcome
- Summary `cleanup_completed` audit row with removed count and cutoff date

**NightlyCleanupScheduler:**
- Wraps `EodScheduler(on_flatten=on_cleanup, close_time_et="03:00", lead_seconds=0)` — same pattern as `ReconciliationScheduler`
- Fires at 03:00 ET daily (off-hours; TV Desktop typically not in active use)

**FastAPI lifespan wiring** (`packages/api/src/api/app.py`):
- Async callback `_do_cleanup()` calls `nightly_cleanup(bridge=app.state.tv_bridge, store=app.state.store)`
- `app.state.cleanup_task = asyncio.create_task(_cleanup_scheduler.run(), name="nightly_cleanup_scheduler")`
- Shutdown: `app.state.cleanup_task.cancel()` → `await cleanup_task` → `except CancelledError: pass` (before recon_task in reverse startup order)

**Tests added to `test_overlay_registry.py`:**
- `test_nightly_cleanup`: 5 rows spanning today/today-3d/today-7d/today-10d/today-30d; verifies 3 expired rows cleaned (deleted_at set), 2 recent rows untouched, mock_bridge.call_tool called once per expired row with `draw_remove_one`, cleanup_completed audit row written
- `test_nightly_cleanup_tolerates_mcp_failure`: 2 rows aged 30 days; bridge.call_tool returns None; both rows still marked deleted; 2 cleanup_partial audit rows written

**Integration test `test_tv_failure_isolation.py`:**
- Real EventBus + in-memory DuckDBStore
- MockRiskManager records Signal.received_count + writes `risk_decision` audit_log rows
- TVBridge with injected mock session that raises `ConnectionError` after 3 successful call_tool calls
- Signal producer publishes 10 Signals at 50ms intervals on TOPIC_SIGNALS
- `asyncio.wait_for(pipeline_complete.wait(), timeout=10.0)` enforces 10s deadline (BLOCKER 5 fix — no pytest-timeout dependency)
- Asserts: `received_count == 10` (zero skipped), `audit_log WHERE topic='risk_decision' >= 10`
- Test completes in ~6.6s; bridge's `_safe_draw_signal` silently absorbs the MCP crashes via its own try/except

### Task 2: AuthorTVAlertButton

`apps/web/components/AuthorTVAlertButton.tsx`:
- First line `'use client'` (Next.js client component boundary)
- `AuthorTVAlertButtonProps`: `{ strategyId: string, condition: string, message: string }`
- Renders a `<button>` + optional toast `<span>`; auto-dismisses toast after 6000ms
- POSTs to `${API_BASE}/tv/alerts` with JSON body; handles HTTP errors + network errors gracefully
- XSS mitigations: React JSX escaping (default) + `errText.slice(0, 120)` / `String(e).slice(0, 120)` caps (T-06-04-03)
- Accessibility: `aria-label="Author TradingView alert for current strategy"` + `role="status"` on toast span
- TODO(Phase 7 UI-07) JSDoc comment above component — traceability marker for live strategy registry wiring

**Blotter page integration** (`apps/web/app/dashboard/blotter/page.tsx`):
- Import: `import AuthorTVAlertButton from '@/components/AuthorTVAlertButton'`
- Button placed in header inside `<div className="flex items-center gap-3">` alongside `<ConnectionStatus />`
- Phase 6 hardcoded props: `strategyId="orb"`, `condition="ORB long entry threshold"`, `message="ORB strategy alert"`
- Inline JSX comment: `{/* TODO(Phase 7 UI-07): replace hardcoded condition/message with live strategy registry values */}`
- TypeScript build clean: zero new errors (24 pre-existing in useStream.test.ts unrelated to this plan)
- Next.js production build (`pnpm build`): `✓ Compiled successfully in 27.6s`

### Task 3: Human-Verify Checkpoint (Auto-Approved)

Checkpoint auto-approved per `workflow.auto_advance=true` configuration. Step 5 (TV crash isolation) is PASS by the integration test. Steps 1-4 require operator manual verification against live TV Desktop.

Checkpoint notes: `.planning/phases/06-tradingview-mcp-bridge/06-04-CHECKPOINT-NOTES.md`

## Phase 6 Traceability Matrix

| REQ-ID | Description | Plan | Implementing Test(s) |
|--------|-------------|------|---------------------|
| TV-01 | TVBridge: supervised long-lived MCP session with reconnect | 02 | test_reconnect, test_pipeline_continues_when_tv_killed |
| TV-02 | draw_shape orchestration: entry_arrow, stop_line, target_line, orb_box; tv_overlays rows | 02, 04 | test_draw_on_signal, test_write_overlay, test_cap_enforcement, test_nightly_cleanup |
| TV-03 | Nightly overlay cleanup: mark deleted_at + best-effort draw_remove_one | 04 | test_nightly_cleanup, test_nightly_cleanup_tolerates_mcp_failure |
| TV-04 | TVReplayDataSource: DataSource protocol + replay_start/step/stop | 03 | test_replay_source_protocol, test_fetch_bars |
| TV-05 | POST /tv/focus: fire-and-forget chart navigation with symbol allowlist | 02 | test_tv_focus |
| TV-06 | TV failure isolation: pipeline continues without skipping signals on TV crash | 02, 04 | test_draw_timeout_nonblocking, test_pipeline_continues_when_tv_killed |
| TV-07 | Author TV Alert: POST /tv/alerts endpoint + AuthorTVAlertButton UI | 02, 04 | test_create_delete_alert, AuthorTVAlertButton.tsx |
| MD-10 | Daily SPY cross-vendor reconciliation: TV vs Twelve Data price/volume divergence | 03 | test_price_divergence, test_audit_log_write |

## Deviations from Plan

None — plan executed exactly as written. All acceptance criteria satisfied:
- `cleanup.py` created with `nightly_cleanup` + `NightlyCleanupScheduler` + `DEFAULT_RETENTION_TRADING_DAYS = 5` + `draw_remove_one` call
- `__init__.py` updated with `from .cleanup import ...`
- `app.state.cleanup_task` appears in both create and cancel in `app.py`
- `test_nightly_cleanup` and `test_nightly_cleanup_tolerates_mcp_failure` pass
- `test_pipeline_continues_when_tv_killed` passes in < 10s (observed: 6.6s)
- `pytest.mark.timeout` NOT used; `asyncio.wait_for` IS used (BLOCKER 5 fix confirmed)
- `pytest-timeout` NOT added to pyproject.toml
- `AuthorTVAlertButton.tsx` with `'use client'`, fetch to `/tv/alerts`, `export default function AuthorTVAlertButton`
- `aria-label` on button, `role="status"` on toast
- TODO(Phase 7 UI-07) markers in both files
- `pnpm build` succeeds

## Threat Surface Scan

No new network endpoints, auth paths, or schema changes introduced in this plan beyond what was specified in the PLAN.md threat model:
- T-06-04-01: draw_remove_one calls bounded by bridge.call_tool 12s timeout; off-hours 03:00 ET schedule
- T-06-04-02: cleanup audit payload contains only overlay_id, shape_id, counts — no price/strategy data
- T-06-04-03: React JSX escaping + slice(0,120) on all toast strings
- T-06-04-04: API layer enforces Pydantic max_length; frontend props are defense in depth
- T-06-04-05: test_pipeline_continues_when_tv_killed proves the isolation contract
- T-06-04-06: cleanup_partial audit rows written per failed draw_remove_one; cleanup_completed summary row always written

## Self-Check: PASSED

Files exist:
- packages/tv-bridge/src/tv_bridge/cleanup.py: FOUND
- apps/web/components/AuthorTVAlertButton.tsx: FOUND
- packages/api/src/api/app.py: FOUND (modified with cleanup_task wiring)
- .planning/phases/06-tradingview-mcp-bridge/06-04-CHECKPOINT-NOTES.md: FOUND

Commits exist:
- fb3038c: feat(06-04): nightly_cleanup + NightlyCleanupScheduler + lifespan wiring + integration test
- c7e2da8: feat(06-04): AuthorTVAlertButton component + blotter page integration (TV-07)
