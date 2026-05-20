---
phase: 06-tradingview-mcp-bridge
verified: 2026-05-19T22:00:00Z
status: human_needed
score: 4/5 must-haves verified
overrides_applied: 0
human_verification:
  - test: "POST /tv/focus visibly drives TradingView Desktop chart"
    expected: "TV Desktop chart switches to CME_MINI:ES1! 1m and scrolls to 2024-06-12 within 3s"
    why_human: "Requires live TV Desktop session. HTTP 202 response is automated-verified; visual chart jump is not testable without a live chart surface."
  - test: "Entry arrow + stop line + target line + ORB box appear within 2s of a Signal"
    expected: "4 shapes appear on TV Desktop chart within 2s of bus Signal publication"
    why_human: "Requires live TV Desktop. Unit tests prove the MCP payloads are constructed and the call sequence fires; visual appearance requires a live chart. NOTE: the ORB box currently uses stub values (0.1% above/below entry price, 15 min before signal) — not the actual day's opening range H/L. SC-2 asks for 'ORB rectangle for the day's opening range' but the implementation draws a geometrically-approximate placeholder."
  - test: "Author TV Alert button creates alert visible in TV Desktop alerts panel"
    expected: "Button click POSTs to /tv/alerts, toast shows tv_alert_id, TV Desktop alerts panel shows new alert"
    why_human: "Requires live TV Desktop. POST /tv/alerts unit test (test_create_delete_alert) is automated-verified; round-trip confirmation in TV Desktop UI requires human."
  - test: "TV crash isolation: degradation banner appears and pipeline continues on forced TV Desktop kill"
    expected: "Pipeline emits no skipped signals, degradation banner surfaces in Next.js UI, bridge reconnects after TV restart"
    why_human: "The automated integration test (test_pipeline_continues_when_tv_killed) proves zero signal pipeline skips and bridge._session becomes None. However the UI degradation banner appearance and the auto-reconnect after restart require a live combined system observation."
---

# Phase 6: TradingView MCP Bridge Verification Report

**Phase Goal:** Every signal and fill auto-renders on the user's live TradingView Desktop chart, the chart can be driven from the Next.js date-picker, TV replay sessions can feed the backtester through the same DataSource protocol, and a daily TV/Twelve-Data reconciliation surfaces any > 0.05% divergence.
**Verified:** 2026-05-19T22:00:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | TVBridge spawns MCP stdio subprocess, maintains long-lived ClientSession, auto-restarts on disconnect; TV failure does not skip signals | ✓ VERIFIED | `bridge.py` supervisor loop with capped exponential backoff [1,2,4,8,16,30]s; `_safe_draw_signal` catches all exceptions; `test_pipeline_continues_when_tv_killed` (integration test) confirms 10/10 signals processed with 0 skips when bridge raises ConnectionError mid-stream (3.49s run) |
| 2 | ORB Signal triggers 4 draw_shape MCP calls + 4 tv_overlays rows; 201st shape refused with audit row; nightly cleanup removes shapes > 5 trading days | ✓ VERIFIED | `bridge.py:_safe_draw_signal` semaphore + cap check at line 351; `test_draw_on_signal` and `test_cap_enforcement` pass; `cleanup.py:nightly_cleanup` with `_trading_days_ago` CME_Equity calendar; `test_nightly_cleanup` + `test_nightly_cleanup_tolerates_mcp_failure` pass. WARNING: ORB box uses stub high/low (0.1% above/below entry), not actual session H/L — partial implementation |
| 3 | POST /tv/focus calls chart_set_symbol + chart_set_timeframe + chart_scroll_to_date in order; returns 202 in <200ms; invalid symbol returns 422 | ✓ VERIFIED | `routes/tv.py:tv_focus` uses `asyncio.create_task(bridge.focus(...))` and returns immediately; `bridge.py:focus()` calls tools in documented order (chart_set_symbol → chart_set_timeframe → chart_scroll_to_date); `test_focus_call_sequence` asserts 3 calls in exact order with mocked session; `test_tv_focus` covers 202 happy path + 422 invalid symbol + 422 invalid date + 503 no bridge |
| 4 | TVReplayDataSource implements DataSource protocol; run_backtest.py --data-source tv-replay routes through it | ✓ VERIFIED | `replay.py` class TVReplayDataSource with `name="tradingview_replay"`, `async fetch_bars`, `async subscribe_bars`; per-call stdio_client; `test_replay_source_protocol` + `test_fetch_bars` + `test_fetch_bars_empty` + `test_fetch_bars_disconnect` all pass; `scripts/run_backtest.py` has `--data-source {duckdb,tv-replay}` argparse flag |
| 5 | Daily reconciliation at 16:10 ET compares TV SPY vs Twelve Data SPY; divergence > 0.05% price or > 5% volume → audit_log reconciliation_alert row; Author TV Alert button POSTs to /tv/alerts and persists alert_id | ✓ VERIFIED | `reconciliation.py` with PRICE_DIVERGENCE_THRESHOLD=0.0005 and VOLUME_DIVERGENCE_THRESHOLD=0.05; no ES_SPY_BASIS_RATIO (confirmed: grep returns 2 hits which are comment-only); `test_price_divergence` and `test_audit_log_write` pass; `AuthorTVAlertButton.tsx` is wired in `blotter/page.tsx` with fetch to `/tv/alerts` and toast; `test_create_delete_alert` passes |

**Score:** 4/5 truths verified (Truth 2 has a partial-implementation note on ORB box coordinates; all tests pass but the ORB box visual geometry uses stub values rather than real session H/L)

### Deferred Items

None.

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `packages/trading-core/src/trading_core/storage/schema.sql` | tv_overlays + tv_alerts DDL | ✓ VERIFIED | Lines 189-213: both CREATE TABLE IF NOT EXISTS blocks present with correct column lists |
| `packages/trading-core/src/trading_core/storage/duckdb_store.py` | 7 TV writer methods | ✓ VERIFIED | `write_tv_overlay`, `write_tv_alert`, `mark_tv_alert_deleted`, `mark_tv_overlay_deleted`, `count_active_overlays`, `get_tv_alert_tv_id`, `list_overlays_older_than` all present and tested |
| `packages/tv-bridge/src/tv_bridge/bridge.py` | Full TVBridge supervisor + bus subscribers + draw orchestration | ✓ VERIFIED | 661 lines; supervisor loop, _subscribe_signals, _subscribe_fills, _safe_draw_signal, _draw_entry_arrow, _draw_stop_line, _draw_target_line, _draw_orb_box_if_new, focus, create_alert, delete_alert all implemented |
| `packages/tv-bridge/src/tv_bridge/shapes.py` | 4 pure-function payload builders | ✓ VERIFIED | entry_arrow_args, stop_line_args, target_line_args, orb_box_args; text[:64] cap enforced |
| `packages/api/src/api/routes/tv.py` | POST /tv/focus + /tv/alerts + DELETE /tv/alerts/{id} + GET /tv/status | ✓ VERIFIED | All 4 routes present with correct status codes (202, 201, 200, 200); symbol allowlist validator; date ISO validator |
| `packages/tv-bridge/src/tv_bridge/replay.py` | TVReplayDataSource implementing DataSource protocol | ✓ VERIFIED | Per-call stdio_client; fetch_bars + subscribe_bars; replay_stop in finally |
| `packages/tv-bridge/src/tv_bridge/reconciliation.py` | run_reconciliation + ReconciliationScheduler | ✓ VERIFIED | SPY-vs-SPY direct comparison; no ES_SPY_BASIS_RATIO assignment; EodScheduler wrapper at 16:10 ET |
| `packages/tv-bridge/src/tv_bridge/cleanup.py` | nightly_cleanup + NightlyCleanupScheduler | ✓ VERIFIED | CME_Equity calendar via pandas_market_calendars; 03:00 ET fire time; draw_remove_one best-effort |
| `apps/web/components/AuthorTVAlertButton.tsx` | React client component POSTing to /tv/alerts | ✓ VERIFIED | 'use client' first line; fetch to `${API_BASE}/tv/alerts`; aria-label + role="status"; TODO(Phase 7 UI-07) markers |
| `packages/api/src/api/app.py` | Lifespan wires TVBridge + ReconciliationScheduler + NightlyCleanupScheduler | ✓ VERIFIED | Lines 175-247 confirm TVBridge.start/stop, recon_task, cleanup_task all wired |
| `.planning/phases/06-tradingview-mcp-bridge/06-04-CHECKPOINT-NOTES.md` | Human-verify checkpoint with Steps 1-5 PASS | PARTIAL | File exists. Step 5 (TV crash isolation) is PASS via integration test. Steps 1-4 (visual TV Desktop verification) are AUTO-APPROVED, not human-verified. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `FastAPI lifespan()` | `TVBridge.start()` then `app.state.tv_bridge = bridge` | asyncio.create_task supervisor + bus-subscriber tasks | ✓ WIRED | `app.py` line 180-181: `await _tv_bridge_ref.start(); app.state.tv_bridge = _tv_bridge_ref` |
| `EventBus TOPIC_SIGNALS` | `TVBridge._safe_draw_signal -> draw_shape -> tv_overlays row` | subscriber loop + asyncio.create_task per event | ✓ WIRED | `bridge.py:_subscribe_signals` creates task per event; `_safe_draw_signal` calls `_record_overlay` on success |
| `POST /tv/focus` | `TVBridge.focus(symbol, date, timeframe)` | asyncio.create_task; HTTP 202 returns immediately | ✓ WIRED | `routes/tv.py` line 115: `asyncio.create_task(bridge.focus(...))` |
| `POST /tv/alerts` | `TVBridge.create_alert -> alert_create MCP -> DuckDBStore.write_tv_alert` | await on MCP call, then DB write | ✓ WIRED | `routes/tv.py` lines 143-154: `tv_alert_id = await bridge.create_alert(...); store.write_tv_alert(...)` |
| `FastAPI lifespan` | `ReconciliationScheduler.run()` as `app.state.recon_task` | asyncio.create_task at 16:10 ET daily | ✓ WIRED | `app.py` line 207: `app.state.recon_task = asyncio.create_task(_recon_scheduler.run())` |
| `FastAPI lifespan` | `NightlyCleanupScheduler.run()` as `app.state.cleanup_task` | asyncio.create_task at 03:00 ET daily | ✓ WIRED | `app.py` line 221: `app.state.cleanup_task = asyncio.create_task(_cleanup_scheduler.run())` |
| `AuthorTVAlertButton onClick` | `POST /tv/alerts` | fetch(`${API_BASE}/tv/alerts`, {method:'POST'}) | ✓ WIRED | `AuthorTVAlertButton.tsx` line 22: fetch to `${API_BASE}/tv/alerts` |
| `scripts/run_backtest.py CLI` | `TVReplayDataSource.fetch_bars` | argparse --data-source tv-replay branch | ✓ WIRED | `run_backtest.py` line 217: `if args.data_source == "tv-replay":` instantiates TVReplayDataSource |
| `DuckDBStore.ensure_schema()` | `schema.sql tv_overlays/tv_alerts DDL` | file read at module-init time | ✓ WIRED | schema.sql lines 189-213 contain both CREATE TABLE IF NOT EXISTS blocks |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|--------------|--------|--------------------|--------|
| `bridge.py:_safe_draw_signal` | `signal.entry`, `signal.stop`, `signal.target` | EventBus TOPIC_SIGNALS subscription | Yes — real Signal objects from strategy pipeline | ✓ FLOWING |
| `routes/tv.py:create_alert` | `tv_alert_id` | `bridge.create_alert()` MCP call | Real MCP response (mocked in tests, live in production) | ✓ FLOWING (mocked in test) |
| `AuthorTVAlertButton.tsx` | `data.tv_alert_id` | `POST /tv/alerts` response | Real API response | ✓ FLOWING |
| `bridge.py:_draw_orb_box_if_new` | `orb_high`, `orb_low` | STUB: `float(signal.entry) * 1.001/0.999` | Placeholder, not actual session H/L | ⚠ STATIC — stub values, not real ORB range |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| `from tv_bridge import TVBridge, TVReplayDataSource, run_reconciliation, ReconciliationScheduler, NightlyCleanupScheduler, nightly_cleanup` | `uv run python -c "from tv_bridge import ..."` | All imports OK | ✓ PASS |
| `uv run python scripts/run_backtest.py --help` shows --data-source flag | `uv run python scripts/run_backtest.py --help \| grep -c -- '--data-source'` | 2 | ✓ PASS |
| 94 Phase 6 tests pass (tv-bridge + api + storage + protocols) | `uv run pytest packages/tv-bridge/ packages/api/ packages/trading-core/tests/storage/ packages/trading-core/tests/test_protocols.py -q` | 94 passed in 22.32s | ✓ PASS |
| Integration test runs in <10s | `uv run pytest packages/tv-bridge/tests/integration/ -v` | 1 passed in 3.49s | ✓ PASS |
| entity_id_field resolved (not TODO) | `grep "entity_id_field:" 06-RESEARCH.md \| grep -v TODO` | `entity_id_field: entity_id` | ✓ PASS |
| No ES_SPY_BASIS_RATIO assignment | `grep -c "ES_SPY_BASIS_RATIO" reconciliation.py` | 2 (comment lines only, no assignment) | ✓ PASS |
| pnpm build | Verified by Plan 04 SUMMARY: "Compiled successfully in 27.6s" | Not re-run (TV route additions were Plan 02) | ? SKIP — no Node.js in test environment |

### Probe Execution

No phase-declared probes in PLAN.md files. Phase 0 probes do not apply here.

| Probe | Command | Result | Status |
|-------|---------|--------|--------|
| N/A | — | — | SKIP — no probe-*.sh files declared for Phase 6 |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|------------|------------|-------------|--------|----------|
| TV-01 | 06-01, 06-02 | TVBridge supervisor: spawns subprocess, long-lived session, auto-restarts | ✓ SATISFIED | `bridge.py:_supervisor_loop` with capped backoff; `test_reconnect` passes; `test_pipeline_continues_when_tv_killed` passes; REQUIREMENTS.md checkbox is stale-unchecked (documentation only) |
| TV-02 | 06-02 | TVBridge subscribes to signals/fills; draws entry/stop/target/ORB box; tv_overlays tracked | ✓ SATISFIED (partial) | `_subscribe_signals` + `_safe_draw_signal` + 4 draw helpers; `test_draw_on_signal` passes; `test_cap_enforcement` passes. ORB box uses stub H/L values |
| TV-03 | 06-04 | Overlay registry with nightly cleanup (5 trading days) and 200-shape cap | ✓ SATISFIED | `cleanup.py:nightly_cleanup` with CME_Equity calendar; `count_active_overlays >= 200` cap in `_safe_draw_signal`; `test_nightly_cleanup` + `test_nightly_cleanup_tolerates_mcp_failure` pass |
| TV-04 | 06-03 | TVReplayDataSource implementing DataSource protocol | ✓ SATISFIED | `replay.py` conforms to protocol; `test_fetch_bars` + `test_replay_source_protocol` pass; REQUIREMENTS.md checkbox is stale-unchecked |
| TV-05 | 06-02 | POST /tv/focus calls 3 MCP tools in order | ✓ SATISFIED | `routes/tv.py:tv_focus` + `bridge.py:focus()`; `test_focus_call_sequence` proves ordered 3-call sequence; REQUIREMENTS.md checkbox is stale-unchecked |
| TV-06 | 06-02, 06-04 | TV failure non-blocking to trading pipeline | ✓ SATISFIED | `_safe_draw_signal` never re-raises; `test_pipeline_continues_when_tv_killed` (10/10 signals, 0 skipped) |
| TV-07 | 06-02, 06-04 | Author TV Alert button + POST /tv/alerts endpoint + alert_id persisted | ✓ SATISFIED | `AuthorTVAlertButton.tsx` in blotter; `routes/tv.py:create_alert` + `delete_alert`; `test_create_delete_alert` passes |
| MD-10 | 06-03 | Daily reconciliation: TV vs Twelve Data SPY bars; divergence > 0.05% price / > 5% vol → audit_log | ✓ SATISFIED | `reconciliation.py` with SPY-vs-SPY comparison; PRICE_DIVERGENCE_THRESHOLD=0.0005; VOLUME_DIVERGENCE_THRESHOLD=0.05; `test_price_divergence` + `test_audit_log_write` pass |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `packages/tv-bridge/src/tv_bridge/bridge.py` | 493-520 | ORB box drawn with stub H/L values (`signal.entry * 1.001/0.999`, 15-min placeholder timestamps). Comment says "Plan 04 will wire in real session_open_ts and orb_end_ts from strategy context" but Plan 04 SUMMARY says no deviations and all acceptance criteria satisfied — the stub was never resolved. | ⚠ WARNING | ORB box appears on the chart but does not represent the actual Opening Range. SC-2 requires "ORB rectangle for the day's opening range" — geometrically incorrect shapes satisfy the render test but not the visual requirement. No `TBD/FIXME/XXX` marker with issue reference. |
| `.planning/phases/06-tradingview-mcp-bridge/06-04-CHECKPOINT-NOTES.md` | All | Steps 1-4 marked AUTO-APPROVED instead of human-verified PASS. Plan 04 Task 3 acceptance criteria require "All of Steps 1-5 marked PASS". | ⚠ WARNING | Visual TV Desktop verification (drawing appearance, focus navigation, alert creation in TV UI) was skipped. These are SC-1, SC-2, SC-3 observability requirements from the ROADMAP. |

No `TBD`, `FIXME`, or `XXX` debt markers found in any files modified by Phase 6.

### Human Verification Required

#### 1. POST /tv/focus drives TradingView Desktop chart visually

**Test:** With TradingView Desktop running (CME_MINI:ES1! chart visible), start uvicorn, run:
`curl -X POST -H "Content-Type: application/json" -d '{"symbol":"ES","date":"2024-06-12"}' http://127.0.0.1:8000/tv/focus`

**Expected:**
- HTTP response `{"status":"accepted","symbol":"ES","date":"2024-06-12"}` arrives in < 500ms
- TV Desktop chart visibly switches to CME_MINI:ES1! 1m and scrolls to 2024-06-12 within 3s

**Why human:** Requires a live TV Desktop session. The HTTP 202 + asyncio.create_task pattern is unit-tested; the actual chart visual jump requires a running TradingView Desktop application.

#### 2. Drawing pipeline renders correct shapes on TV chart

**Test:** Publish a synthetic ORB Signal on the bus (or trigger via backtest). Observe TV Desktop.

**Expected:**
- Entry arrow (horizontal line, green for long) at entry price
- Stop line (dashed red) at stop price
- Target line (dashed blue) at target price
- ORB rectangle (yellow, covering actual 9:30-9:45 ET opening range bars)

**Why human:** Requires live TV Desktop. NOTE: the ORB box currently uses stub coordinates (0.1% above/below entry, 15 min window) rather than the actual session opening range high/low. The ROADMAP SC-2 specifies "ORB rectangle for the day's opening range" — the current implementation does NOT meet this letter of the spec. The verifier recommends the operator assess whether the stub ORB box is acceptable for Phase 6 or requires a gap-closure plan.

#### 3. Author TV Alert button round-trips to TV Desktop

**Test:** Open `http://localhost:3000/dashboard/blotter`, click "Author TV Alert".

**Expected:**
- Button shows "Authoring..." briefly
- Toast appears: "TV alert created: <tv_alert_id>"
- TV Desktop Alerts panel shows new alert
- DuckDB `tv_alerts` table has a row with matching `tv_alert_id`

**Why human:** Requires live TV Desktop to confirm the alert appears in the TV Alerts panel.

#### 4. TV crash isolation visible in the full system

**Test:** With uvicorn + Next.js running, forcibly kill TV Desktop. Observe:

**Expected:**
- FastAPI logs show `tv_bridge.reconnecting attempt=0 backoff=1` backoff sequence
- Next.js degradation banner appears (Phase 3's DegradationBanner wired to TOPIC_DEGRADED_STATE)
- Any running pipeline emits no skipped signals
- After TV Desktop restarts: `tv_bridge.connected` log within 30s, banner clears

**Why human:** The pipeline isolation is proven by `test_pipeline_continues_when_tv_killed` (automated). The degradation banner appearance and auto-reconnect visual confirmation require a live running system.

### Gaps Summary

No automated-test blockers found. All 94 Phase 6 tests pass. The phase goal is substantially achieved in code.

Two issues require human resolution:

1. **ORB box stub values (WARNING):** The ORB box drawn on the TV chart uses geometrically incorrect stub coordinates (`signal.entry * 1.001/0.999`, not actual session H/L). The unit tests pass because they only verify that `draw_shape` is called — they do not assert the payload represents the real opening range. ROADMAP SC-2 says "ORB rectangle for the day's opening range." The operator must decide if the stub is acceptable or if a gap-closure plan is needed before Phase 6 is signed off.

2. **Human-verify checkpoint not completed (WARNING):** Steps 1-4 of the Plan 04 checkpoint were AUTO-APPROVED rather than verified against a live TV Desktop session. The Plan 04 acceptance criteria require all 5 steps PASS with human confirmation. ROADMAP SC-1, SC-2, SC-3 are directly dependent on this verification. The operator must run these steps manually before the phase can be considered fully closed.

---

_Verified: 2026-05-19T22:00:00Z_
_Verifier: Claude (gsd-verifier)_
