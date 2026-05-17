---
phase: 3
slug: vertical-mvp-slice-backtester
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-05-16
---

# Phase 3 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x + pytest-asyncio 0.24.x |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` (exists) |
| **Quick run command** | `uv run pytest packages/trading-core/tests/test_backtest_engine.py packages/trading-core/tests/test_paper_executor.py packages/trading-core/tests/test_safe_signals.py -x -q` |
| **Full suite command** | `uv run pytest -x -q` |
| **Estimated runtime** | ~45 seconds (full suite, 244 existing + ~50 new tests) |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest packages/trading-core/tests/test_backtest_engine.py packages/trading-core/tests/test_paper_executor.py packages/trading-core/tests/test_safe_signals.py -x -q`
- **After every plan wave:** Run `uv run pytest -x -q`
- **Before `/gsd-verify-work`:** Full suite green + BL-1 green + reproducibility CI green
- **Max feedback latency:** ~45 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 3-01-01 | 01 | 1 | BT-01 | — | N/A | unit | `pytest packages/trading-core/tests/test_backtest_engine.py -x` | ❌ Wave 0 | ⬜ pending |
| 3-01-02 | 01 | 1 | BT-02 | — | safe_from_signals rejects string price arg | unit | `pytest packages/trading-core/tests/test_safe_signals.py -x` | ❌ Wave 0 | ⬜ pending |
| 3-01-03 | 01 | 1 | BT-03 | T-fill | Next-bar fill + session-phase slippage | unit | `pytest packages/trading-core/tests/test_paper_executor.py -x` | ❌ Wave 0 | ⬜ pending |
| 3-01-04 | 01 | 1 | BT-04 | — | N/A | unit | `pytest packages/trading-core/tests/test_backtest_engine.py::test_metrics -x` | ❌ Wave 0 | ⬜ pending |
| 3-01-05 | 01 | 1 | BT-05 | — | N/A | unit | `pytest packages/trading-core/tests/test_backtest_engine.py::test_mae_mfe -x` | ❌ Wave 0 | ⬜ pending |
| 3-01-06 | 01 | 1 | BT-06 | — | N/A | unit | `pytest packages/trading-core/tests/test_backtest_engine.py::test_attribution -x` | ❌ Wave 0 | ⬜ pending |
| 3-02-01 | 02 | 1 | BT-07 | — | Leaking strategy → finite Sharpe + 40-60% win rate | integration | `pytest packages/trading-core/tests/integration/test_lookahead.py -x` | ❌ Wave 0 | ⬜ pending |
| 3-02-02 | 02 | 1 | BT-08 | — | N/A | unit | `pytest packages/trading-core/tests/test_paper_executor.py::test_eod_flatten -x` | ❌ Wave 0 | ⬜ pending |
| 3-02-03 | 02 | 1 | BT-09 | — | N/A | integration | `pytest packages/trading-core/tests/integration/test_reproducibility.py -x` | ❌ Wave 0 | ⬜ pending |
| 3-03-01 | 03 | 2 | SP-01 | — | N/A | integration | `pytest packages/api/tests/test_ws_stream.py -x` | ❌ Wave 0 | ⬜ pending |
| 3-04-01 | 04 | 2 | UI-01 | V5 | Pydantic validates /bars query params | integration | `pytest packages/api/tests/test_routes.py -x` | ❌ Wave 0 | ⬜ pending |
| 3-04-02 | 04 | 2 | UI-04 | — | N/A | manual/smoke | `localhost:3000/dashboard` loads | — | ⬜ pending |
| 3-04-03 | 04 | 2 | UI-08 | — | N/A | manual | ET clock + connection status visual inspection | — | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `packages/trading-core/tests/test_backtest_engine.py` — stubs for BT-01, BT-04, BT-05, BT-06
- [ ] `packages/trading-core/tests/test_paper_executor.py` — stubs for BT-03, BT-08
- [ ] `packages/trading-core/tests/test_safe_signals.py` — stubs for BT-02
- [ ] `packages/trading-core/tests/integration/test_lookahead.py` — BT-07 (BL-1 gate, D-14)
- [ ] `packages/trading-core/tests/integration/test_reproducibility.py` — BT-09 + FND-08
- [ ] `packages/api/tests/test_routes.py` — UI-01 (GET /bars, GET /backtests)
- [ ] `packages/api/tests/test_ws_stream.py` — SP-01 + D-04 (7 event types) + D-05 (envelope)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Dashboard renders with ORB overlays | UI-04 | Requires browser + running backend | Start uvicorn + next dev; load localhost:3000/dashboard; verify chart shows bars, ORB price lines, entry marker |
| ET clock + connection status indicator | UI-08 | Visual DOM state + timing-dependent | Observe header: clock shows NY time; disconnect backend; status turns yellow then red within 10s/30s |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 45s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
