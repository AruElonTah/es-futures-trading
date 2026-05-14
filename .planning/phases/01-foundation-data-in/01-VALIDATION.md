---
phase: 01
slug: foundation-data-in
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-05-14
---

# Phase 01 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Sourced from `01-RESEARCH.md §Validation Architecture`. The planner MUST
> ensure every task in `01-XX-PLAN.md` has either an `<automated>` verify
> command in this table OR a Wave 0 dependency to install the missing infra.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x + pytest-asyncio 0.24.x + hypothesis 6.152.x + respx + freezegun + pytest-cov |
| **Config file** | per-package `pyproject.toml` `[tool.pytest.ini_options]` (`packages/<name>/pyproject.toml`) |
| **Quick run command** | `uv run pytest packages/trading-core/tests/<file>.py -q --tb=short` (or `-k <name>` for keyword) |
| **Full suite command** | `uv run pytest -q` from repo root (uv-workspace discovers all packages) |
| **Estimated runtime** | quick ~3–8 s per file · full ~20–30 s once Phase 1 ships (no broker/IO mocks beyond respx) |

---

## Sampling Rate

- **After every task commit:** Run the quick command scoped to the task's `tests/` file(s).
- **After every plan wave:** Run the full suite command from repo root.
- **Before `/gsd-verify-work`:** Full suite must be green AND `pnpm build` from `apps/web/` must succeed AND `pre-commit run --all-files` must exit 0.
- **Max feedback latency:** 30 s for quick, 60 s for full suite (Windows + Python 3.12; first run after `uv sync` will be slower due to bytecode compilation).

---

## Per-Task Verification Map

> Populated by the planner from `01-XX-PLAN.md`'s `<verify>` blocks. The matrix below is the **shape**; the planner fills concrete Task IDs / requirements / threat refs / commands.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 01-01-XX | 01 (scaffold) | A | FND-01, FND-02 | — | `uv sync` produces working `.venv` from clean clone; 3 packages importable | smoke | `uv run python -c "import trading_core, api, tv_bridge"` | ❌ W0 (uv install) | ⬜ pending |
| 01-02-XX | 02 (protocols + models) | B | FND-04 | — | 4 Protocols are `typing.Protocol` + `runtime_checkable`; Pydantic v2 models validate | unit | `uv run pytest packages/trading-core/tests/test_protocols.py -q` | ❌ W0 | ⬜ pending |
| 01-03-XX | 03 (calendars + bus) | B | MD-03, MD-04 | — | CME_Equity hybrid filter produces 9:30–16:00 ET window only; EventBus pub/sub roundtrip | unit | `uv run pytest packages/trading-core/tests/test_calendars.py packages/trading-core/tests/test_events.py -q` | ❌ W0 | ⬜ pending |
| 01-04-XX | 04 (storage + adapters) | B | MD-01, MD-02, MD-05, MD-06, MD-07, MD-08 | T-01-01 (API key leak) | DuckDB ON CONFLICT upsert idempotent; rollover_seam True on 3rd-Fri; bar_gaps populated; Twelve Data adapter redacts apikey | integration | `uv run pytest packages/trading-core/tests/test_storage.py packages/trading-core/tests/test_adapters_twelvedata.py -q` | ❌ W0 (respx + freezegun) | ⬜ pending |
| 01-05-XX | 05 (seed_bars + pre-commit) | C | MD-09, FND-03, FND-06, FND-07, FND-08, FND-09 | T-01-02 (gitleaks bypass), T-01-03 (no-naive-tz) | seed_bars CLI idempotent; pre-commit rejects `datetime.now()` w/o tz; gitleaks rejects fake key; runs writer captures full field set incl `adr_hash` | end-to-end | `uv run python scripts/seed_bars.py --symbol SPY --tf 1m --from 2024-01-01 --to 2024-01-08 --provider twelvedata` (twice; second run = zero new rows) | ❌ W0 | ⬜ pending |
| 01-06-XX | 06 (API shell + web + acceptance smoke) | C | FND-05 | — | FastAPI app importable; `apps/web/` `pnpm build` succeeds; `tsc --noEmit` passes | smoke | `uv run python -c "from api.main import app; print(type(app))"; pushd apps/web && pnpm build && popd` | ❌ W0 (pnpm install) | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

The planner MUST treat these as Wave 0 prerequisites BEFORE any of the verify commands above can run. Wave 0 is the first set of tasks in Plan 01-01 (Scaffold).

- [ ] **`uv` installed.** Per RESEARCH.md operational finding, `uv` is NOT on the operator's machine. PowerShell install: `irm https://astral.sh/uv/install.ps1 | iex`. Verify with `uv --version` (expect `0.11.x` or later).
- [ ] **`pnpm` installed.** Per RESEARCH.md operational finding, `pnpm` is NOT on the operator's machine. Use Corepack (Node already installed at `C:\Program Files\nodejs\`): `corepack enable && corepack prepare pnpm@9.15.0 --activate`. Verify with `pnpm --version`.
- [ ] **`packages/trading-core/tests/conftest.py`** with shared fixtures: `synthetic_orb_day`, `dst_spring_forward_2026_03_08`, `dst_fall_back_2026_11_01`, `twelvedata_respx_mock`, `tmp_duckdb_path`.
- [ ] **`packages/api/tests/conftest.py`** + **`packages/tv-bridge/tests/conftest.py`** declaring `pytest_plugins = ["trading_core.tests.conftest"]` for fixture re-export.
- [ ] **Root `pyproject.toml`** with `[tool.uv.workspace]` listing the 3 inner packages.
- [ ] **Root `package.json`** with `pnpm@9.15.0` in `packageManager` field and `workspaces: ["apps/*", "packages/*"]` (Node side).
- [ ] **`.pre-commit-config.yaml`** with the no-naive-tz hook (regex-based) and `zricethezav/gitleaks` hook configured to allow the `<TWELVEDATA_API_KEY>` redaction sentinel.
- [ ] **`.gitleaks.toml`** allowlist for the Phase 0 sentinel pattern.
- [ ] **`data/duckdb/`** + **`data/parquet/`** + **`data/logs/audit/`** directories scaffolded with `.gitkeep`; root `.gitignore` already excludes `.env`, `.venv-spike/`, `data/` (planner extends to confirm).

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| TV `DataSource` end-to-end against live TV Desktop | FND-10 (re-verification) | Requires TV Desktop running with CDP on port 9222 — non-reproducible in CI, depends on operator's TV subscription | Launch TV via `tv_launch`; run `uv run python -m trading_core.scripts.tv_smoke` (a tiny harness Phase 1 may ship for parity with Phase 0's `tv_mcp_smoke.py` but using the production `TVDataSource`); confirm bar count > 0 and chart restored. |
| Audit log rotation under sustained write pressure on Windows | FND-09 (audit log integrity) | Requires multi-hour run to trigger file lock contention; not feasible per-task | Phase 1 ships the structlog + `concurrent-log-handler` config; deferred load test happens in Phase 5 (when the order ledger generates real volume). |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify (intra-plan rule the planner must enforce)
- [ ] Wave 0 covers all MISSING references (`uv`, `pnpm`, `pytest`, `pre-commit`, fixtures, gitleaks config)
- [ ] No watch-mode flags (pytest must NOT run with `--looponfail`; tests must exit deterministically)
- [ ] Feedback latency < 30 s for the quick command
- [ ] `nyquist_compliant: true` set in frontmatter (the plan-checker flips this after verifying every PLAN.md task has a verify or W0 reference)

**Approval:** pending
