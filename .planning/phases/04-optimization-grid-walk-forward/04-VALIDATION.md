---
phase: 4
slug: optimization-grid-walk-forward
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-05-17
---

# Phase 4 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x (existing) |
| **Config file** | `pyproject.toml` (`[tool.pytest.ini_options]`) |
| **Quick run command** | `uv run pytest packages/trading-core/tests/ -x -q` |
| **Full suite command** | `uv run pytest packages/trading-core/tests/ packages/api/tests/ -q` |
| **Estimated runtime** | ~30 seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest packages/trading-core/tests/ -x -q`
- **After every plan wave:** Run full suite
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 4-01-01 | 01 | 1 | OPT-01 | — | N/A | unit | `uv run pytest packages/trading-core/tests/test_optspace.py -x -q` | ❌ W0 | ⬜ pending |
| 4-01-02 | 01 | 1 | OPT-04 | — | ADR gate refuses run without committed ADR | unit | `uv run pytest packages/trading-core/tests/test_opt_adr_gate.py -x -q` | ❌ W0 | ⬜ pending |
| 4-01-03 | 01 | 1 | OPT-06 | — | Coarse-grid-first refuses narrow axes | unit | `uv run pytest packages/trading-core/tests/test_optspace.py::test_coarse_grid_first -x -q` | ❌ W0 | ⬜ pending |
| 4-02-01 | 02 | 2 | OPT-03 | — | N/A | unit | `uv run pytest packages/trading-core/tests/test_splitter.py -x -q` | ❌ W0 | ⬜ pending |
| 4-02-02 | 02 | 2 | OPT-02 | — | Worker opens DuckDB read-only only | unit | `uv run pytest packages/trading-core/tests/test_opt_worker.py -x -q` | ❌ W0 | ⬜ pending |
| 4-02-03 | 02 | 2 | OPT-05 | — | Per-fold hashes written correctly | unit | `uv run pytest packages/trading-core/tests/test_opt_worker.py::test_fold_hashes -x -q` | ❌ W0 | ⬜ pending |
| 4-03-01 | 03 | 2 | OPT-08 | — | Holdout guard refuses query without flag | unit | `uv run pytest packages/trading-core/tests/test_holdout_guard.py -x -q` | ❌ W0 | ⬜ pending |
| 4-03-02 | 03 | 2 | OPT-08 | — | 4th burn in quarter refused | unit | `uv run pytest packages/trading-core/tests/test_holdout_guard.py::test_quota -x -q` | ❌ W0 | ⬜ pending |
| 4-04-01 | 04 | 3 | OPT-07 | — | Leaderboard sorted by OOS Sharpe | unit | `uv run pytest packages/api/tests/test_opt_routes.py -x -q` | ❌ W0 | ⬜ pending |
| 4-04-02 | 04 | 3 | OPT-09 | — | Heatmap endpoint returns 2D grid | unit | `uv run pytest packages/api/tests/test_opt_routes.py::test_heatmap -x -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `packages/trading-core/tests/optimization/test_space.py` — stubs for OPT-01, OPT-06 (OptSpace parser + coarse-grid-first check)
- [ ] `packages/trading-core/tests/optimization/test_holdout.py` — stubs for OPT-04, OPT-08 (ADR gate + holdout quota)
- [ ] `packages/trading-core/tests/optimization/test_splitter.py` — stubs for OPT-03 (rolling splitter fold generation)
- [ ] `packages/trading-core/tests/optimization/test_worker.py` — stubs for OPT-02, OPT-05 (worker harness + shard output)
- [ ] `packages/trading-core/tests/integration/test_run_opt.py` — stubs for OPT-04, OPT-05 (CLI ADR gate + per-fold persistence)
- [ ] `packages/api/tests/test_optimizations.py` — stubs for OPT-07, OPT-09 (leaderboard + heatmap routes)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| 125-combo full grid run completes end-to-end | OPT-02 | Requires live DuckDB + bars data; ProcessPoolExecutor can't run in pytest without multiprocessing guard | Run `uv run python scripts/run_opt.py --space config/strategies/orb.optspace.yaml --symbol SPY --tf 1m --from 2023-01-01 --to 2024-06-01`; verify `opt_runs` row exists with status=complete and 125 `opt_results` rows |
| /optimizations page renders leaderboard + heatmap | OPT-09 | Next.js frontend visual verification | Start `uvicorn` + `next dev`, navigate to `localhost:3000/optimizations`, confirm table sorted by OOS Sharpe, select two axes and render heatmap |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
