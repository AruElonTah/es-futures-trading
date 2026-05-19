---
phase: 6
slug: tradingview-mcp-bridge
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-05-19
---

# Phase 6 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.4.2 + pytest-asyncio 0.24.0 |
| **Config file** | `pyproject.toml` — `[tool.pytest.ini_options]` asyncio_mode = "auto" |
| **Quick run command** | `uv run pytest packages/tv-bridge/tests/ -q` |
| **Full suite command** | `uv run pytest packages/tv-bridge/ packages/api/ packages/trading-core/ -q` |
| **Estimated runtime** | ~25 seconds (unit tests only; integration tests may require TV Desktop running) |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest packages/tv-bridge/tests/ -q`
- **After every plan wave:** Run `uv run pytest packages/tv-bridge/ packages/api/ packages/trading-core/ -q`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 06-01-01 | 01 | 1 | TV-01,TV-02 | T-06-01 | DuckDB DDL adds tv_overlays and tv_alerts tables | unit | `uv run pytest packages/trading-core/tests/storage/test_schema.py -k tv_overlays -x -q` | ❌ W0 | ⬜ pending |
| 06-01-02 | 01 | 1 | TV-02,TV-07 | — | DuckDBStore write_tv_overlay / write_tv_alert / mark_tv_alert_deleted methods present and write correct rows | unit | `uv run pytest packages/trading-core/tests/storage/test_duckdb_store.py -k tv_ -x -q` | ❌ W0 | ⬜ pending |
| 06-01-03 | 01 | 1 | TV-01 | — | TVBridge skeleton: __init__, start(), stop(), call_tool() importable from tv_bridge package | unit | `uv run pytest packages/tv-bridge/tests/test_bridge.py::test_bridge_importable -x -q` | ❌ W0 | ⬜ pending |
| 06-01-04 | 01 | 1 | TV-02 | A1 | draw_shape entity_id field name verified against live TV Desktop and recorded in RESEARCH.md | integration + structural | `grep "entity_id_field:" .planning/phases/06-tradingview-mcp-bridge/06-RESEARCH.md \| grep -v TODO` returns a non-empty line (BLOCKER 4 fix — structural proof the manual verification was completed) | ❌ W0 | ⬜ pending |
| 06-02-01 | 02 | 2 | TV-01 | — | TVBridge reconnects after session drop (simulated by cancelling mock session) | unit (mock MCP) | `uv run pytest packages/tv-bridge/tests/test_bridge.py::test_reconnect -x -q` | ❌ W0 | ⬜ pending |
| 06-02-02 | 02 | 2 | TV-06 | — | Bus dispatch not blocked when draw_shape times out; asyncio.create_task returns immediately | unit | `uv run pytest packages/tv-bridge/tests/test_bridge.py::test_draw_timeout_nonblocking -x -q` | ❌ W0 | ⬜ pending |
| 06-02-03 | 02 | 2 | TV-02 | — | draw_shape calls fired for entry_arrow + stop_line + target_line + orb_box after signal event | unit (mock MCP) | `uv run pytest packages/tv-bridge/tests/test_bridge.py::test_draw_on_signal -x -q` | ❌ W0 | ⬜ pending |
| 06-02-04 | 02 | 2 | TV-02 | DoS | 201st draw_shape call refused; tv_overlays cap enforced | unit | `uv run pytest packages/tv-bridge/tests/test_overlay_registry.py::test_cap_enforcement -x -q` | ❌ W0 | ⬜ pending |
| 06-02-05 | 02 | 2 | TV-02 | — | tv_overlays row written with correct (strategy_id, signal_id, shape_id) tuple | unit (in-memory DuckDB) | `uv run pytest packages/tv-bridge/tests/test_overlay_registry.py::test_write_overlay -x -q` | ❌ W0 | ⬜ pending |
| 06-02-06 | 02 | 2 | TV-05 | Tampering | POST /tv/focus returns 202 Accepted; symbol validated against allowlist | unit (TestClient) | `uv run pytest packages/api/tests/test_tv_routes.py::test_tv_focus -x -q` | ❌ W0 | ⬜ pending |
| 06-02-07 | 02 | 2 | TV-07 | — | POST /tv/alerts persists tv_alert_id to tv_alerts table; DELETE removes it | unit (TestClient + DuckDB) | `uv run pytest packages/api/tests/test_tv_routes.py::test_create_delete_alert -x -q` | ❌ W0 | ⬜ pending |
| 06-03-01 | 03 | 3 | TV-04 | — | TVReplayDataSource satisfies DataSource protocol (static type check + runtime protocol verification) | unit | `uv run pytest packages/trading-core/tests/test_protocols.py::test_replay_source_protocol -x -q` | ❌ W0 | ⬜ pending |
| 06-03-02 | 03 | 3 | TV-04 | — | TVReplayDataSource.fetch_bars returns DataFrame with correct Bar columns and RTH-only rows | unit (mock MCP) | `uv run pytest packages/tv-bridge/tests/test_replay_source.py::test_fetch_bars -x -q` | ❌ W0 | ⬜ pending |
| 06-03-03 | 03 | 3 | MD-10 | — | Reconciliation detects >0.05% price divergence between TV ES and Twelve Data SPY-proxy | unit (mock DataSources) | `uv run pytest packages/tv-bridge/tests/test_reconciliation.py::test_price_divergence -x -q` | ❌ W0 | ⬜ pending |
| 06-03-04 | 03 | 3 | MD-10 | — | Reconciliation writes audit_log row with topic='reconciliation_alert' on divergence | unit | `uv run pytest packages/tv-bridge/tests/test_reconciliation.py::test_audit_log_write -x -q` | ❌ W0 | ⬜ pending |
| 06-04-01 | 04 | 4 | TV-02 | — | Nightly cleanup removes tv_overlays rows older than 5 trading days | unit | `uv run pytest packages/tv-bridge/tests/test_overlay_registry.py::test_nightly_cleanup -x -q` | ❌ W0 | ⬜ pending |
| 06-04-02 | 04 | 4 | TV-01,TV-06 | — | Pipeline continues with no skipped signals when TV Desktop killed mid-session | integration | `uv run pytest packages/tv-bridge/tests/integration/test_tv_failure_isolation.py -x -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `packages/tv-bridge/tests/conftest.py` — shared fixtures: mock ClientSession, in-memory DuckDB, mock EventBus
- [ ] `packages/tv-bridge/tests/test_bridge.py` — stubs: test_bridge_importable, test_reconnect, test_draw_timeout_nonblocking, test_draw_on_signal
- [ ] `packages/tv-bridge/tests/test_overlay_registry.py` — stubs: test_write_overlay, test_cap_enforcement, test_nightly_cleanup
- [ ] `packages/tv-bridge/tests/test_replay_source.py` — stubs: test_fetch_bars
- [ ] `packages/tv-bridge/tests/test_reconciliation.py` — stubs: test_price_divergence, test_audit_log_write
- [ ] `packages/tv-bridge/tests/integration/test_tv_failure_isolation.py` — stub (marked skip until TV-01 and TV-06 complete)
- [ ] `packages/api/tests/test_tv_routes.py` — stubs: test_tv_focus, test_create_delete_alert
- [ ] `packages/trading-core/src/trading_core/storage/schema.sql` — ADD tv_overlays, tv_alerts DDL (Wave 1 plan task)
- [ ] draw_shape entity_id field name — verify via live TV Desktop call before Wave 2 (document in RESEARCH.md)

*Existing infrastructure (pytest, pytest-asyncio, DuckDB in-memory fixtures from prior phases) covers all Phase 6 requirements — no new test framework installation needed.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Entry arrow + stop line + target line + ORB box appear on TV Desktop chart within 2s of paper fill | TV-02 | Requires running TV Desktop + live draw_shape call; visual confirmation | Run the engine, trigger a paper fill, observe TV Desktop chart |
| POST /tv/focus visually moves TV Desktop chart to the requested date within 15s | TV-05 | TV Desktop visual update cannot be asserted from Python | Call `POST /tv/focus {"symbol":"ES","date":"2024-06-12"}`, observe TV Desktop |
| ORB rectangle appears at correct 09:30–09:45 ET session-open position | TV-02 | Shape coordinates depend on TV chart timezone; visual confirmation needed | Verify rectangle bounds on the chart match the 15-minute opening range |
| "Author TV Alert" button sends alert_create and displays toast with tv_alert_id | TV-07 | Requires running Next.js dev server + browser interaction | Click button in browser; confirm toast shows; verify tv_alerts table in DuckDB |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies (06-01-04 now has a grep-based structural verify per BLOCKER 4 fix)
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 30s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved (revision pass — checker BLOCKERs 1-5 + WARNINGs 1-5 addressed 2026-05-19)
