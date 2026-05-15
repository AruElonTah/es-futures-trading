---
phase: 01-foundation-data-in
plan: 06
subsystem: closure-fastapi-shell-and-acceptance-smoke
tags: [fastapi-shell, health-endpoint, apps-web-finalize, phase-1-closure, acceptance-smoke, roadmap-update]
requires:
  - Plan 01-01 (uv workspace + apps/web stub + packages/api scaffold with fastapi+uvicorn deps)
  - Plan 01-02 (trading_core.config.Settings — imported by FastAPI shell to prove import graph)
  - Plan 01-05 (pre-commit hooks installed; gate every commit in this plan)
provides:
  - packages/api/src/api/app.py — FastAPI shell with GET /health (Phase 3 expands)
  - packages/api/src/api/__init__.py — re-exports `app` so `uvicorn api:app` works
  - packages/api/tests/test_health.py — 4 TestClient tests covering /health body, FastAPI typecheck, only-/health guard (T-01-06-01), and Settings import (FND-01)
  - apps/web/README.md — finalized with explicit pnpm dev/build/tsc commands + Phase 3 Lightweight Charts roadmap note
  - .planning/ROADMAP.md — Phase 1 marked complete (6/6 plans, 2026-05-15)
  - .planning/STATE.md — Phase 1 closed; Current Position + Progress + Performance metrics + 4 new Plan 01-06 decisions
  - Phase 1 acceptance smoke: `uv sync --all-packages && uv run pytest -q && pnpm --filter web build && pnpm --filter web exec tsc --noEmit && uv run pre-commit run --all-files` → all five exit 0
affects:
  - Phase 1 ROADMAP success criterion #1 (uv sync + workspace importable + pinned deps) — now provable end-to-end via TestClient
  - Phase 1 ROADMAP success criterion #4 (apps/web builds + tsc clean) — proven; 19s build, 0 type errors
  - Phase 3 inherits a working FastAPI shell with the trading-core import graph proven; expansion to /bars, /backtests, WS /stream is purely additive
tech-stack:
  added:
    python: []  # no new deps; fastapi+uvicorn+testclient already pinned by Plan 01-01
    js: []  # no new deps; README-only change
  patterns:
    - "FastAPI shell: module-level app = FastAPI(title=..., version='0.1.0') + module-level Settings() instantiation + single @app.get('/health') endpoint — codifies the Phase 1 contract that test_only_health_endpoint_registered guards against accidental expansion"
    - "TestClient(app) for in-process integration testing — no port binding, no uvicorn lifecycle to manage; Phase 3 will keep this pattern when adding /bars + /backtests"
    - "api/__init__.py re-export pattern: `from api.app import app` enables `uvicorn api:app` shorthand BUT causes `import api.app` to resolve to the FastAPI instance at the package namespace (Python's `from X import Y` semantics rebind X.Y). Tests inspecting the underlying module grab it via `sys.modules['api.app']`."
key-files:
  created:
    - packages/api/src/api/app.py (FastAPI shell, ~60 lines)
    - packages/api/tests/test_health.py (4 TestClient tests, ~90 lines)
    - .planning/phases/01-foundation-data-in/01-06-SUMMARY.md (this file)
  modified:
    - packages/api/src/api/__init__.py (re-export `app`)
    - packages/api/tests/conftest.py (documented pytest_plugins non-applicability under importlib mode)
    - apps/web/README.md (added dev commands + Phase 3 Lightweight Charts mention)
    - packages/trading-core/tests/integration/test_seed_bars_e2e.py (Rule 3 fix: subprocess[\"uv\",...] → [sys.executable, ...])
    - .planning/ROADMAP.md (Phase 1 [x] + 6/6 + completion date)
    - .planning/STATE.md (status block + Current Position + Performance metrics row + Decisions)
key-decisions:
  - "FastAPI shell ships ONLY /health in Phase 1 — Phase 3 owns the real UI-01 surface (/bars, /backtests, WS /stream, /positions, /trades, /equity, /optimizations, /kill, /flatten). Codified by the test_only_health_endpoint_registered guard which fails on any 2nd @app.<verb> decorator (T-01-06-01 mitigation). The PR-time review burden is one assert."
  - "FastAPI app + Settings instantiation lives at module top (no FastAPI Depends() yet). Rationale: Phase 1's only goal here is proving the import graph. Phase 3 will refactor to lifespan + DI when /bars actually needs to read TwelveDataSource. Doing this Phase 1 would be over-design before the integration shape is known."
  - "api/__init__.py re-exports `app` so `uvicorn api:app` works as shorthand for `uvicorn api.app:app`. Trade-off documented: `import api.app` at the package namespace returns the FastAPI instance rather than the submodule because of Python's `from X import Y` rebinding rule. Tests that need the underlying module grab it via `sys.modules['api.app']`. This is the cheaper trade than dropping the re-export — operators expect `uvicorn api:app` to work."
  - "pytest_plugins = ['trading_core.tests.conftest'] does NOT work under the project's --import-mode=importlib + no tests/__init__.py setup (Plan 01-01 decision #1) — trading_core.tests is not an importable Python package. The api tests do not currently need shared fixtures (TestClient is enough), so the conftest stays empty with a docstring explaining the constraint for Phase 3."
metrics:
  duration: "~28 minutes (3 tasks, single TDD cycle for Task 1, ROADMAP/STATE edits for Task 3)"
  completed_date: "2026-05-15"
  tests_added: 4  # all in packages/api/tests/test_health.py
  tests_passing: "195 / 195 in full repo suite (190 trading-core + 5 api: 4 health + 1 import); 1 skipped (gitleaks-binary-cache-empty case)"
  commits: 4  # 1 RED + 1 GREEN + 1 README + 1 ROADMAP/STATE
requirements_completed: [FND-01, FND-02]
---

# Phase 01 Plan 06: FastAPI Shell + Phase 1 Acceptance Smoke Summary

**The FastAPI shell at `packages/api/src/api/app.py` exposes `GET /health` and imports `trading_core.config.Settings` at module top — proving the workspace import graph (FND-01); the `apps/web` Next.js placeholder builds clean (19s) with `tsc --noEmit` exit 0; the full Phase 1 acceptance smoke (uv sync → pytest → pnpm build → pnpm tsc → pre-commit) is green end-to-end; ROADMAP + STATE flipped to Phase 1 complete. The Phase verifier can now run a single command sequence and prove every ROADMAP Phase 1 success criterion.**

## Performance

- **Duration:** ~28 minutes (3 tasks; Task 1 was TDD RED + GREEN, Tasks 2 + 3 were single-commit)
- **Started + Completed:** 2026-05-15
- **Files created:** 3 (1 app.py + 1 test_health.py + this SUMMARY)
- **Files modified:** 6 (1 __init__.py + 1 conftest.py + 1 README.md + 1 test_seed_bars_e2e.py + 1 ROADMAP + 1 STATE)
- **Tests added:** 4 (all in `packages/api/tests/test_health.py`)
- **Repo test count:** 190 trading-core + 1 api-import = 191 → **195 passing, 1 skipped** (+4 new health tests). The skipped test is `test_gitleaks_allowlist_suppresses_sentinel` which is conditionally-skipped when the gitleaks pre-commit binary cache is empty (it IS populated on this dev machine, but pytest collection runs the skip-decision before the populate).

## Phase 1 Cumulative Wall-Clock Duration

Sum across all 6 Phase 1 plans (per SUMMARY-reported durations):

| Plan | Duration | Tasks | Files |
| --- | --- | --- | --- |
| 01-01 | ~12 min | 3 | 33 |
| 01-02 | ~7 min 23s | 3 | 23 |
| 01-03 | ~38 min | 3 | 11 |
| 01-04 | ~62 min | 4 | 10 |
| 01-05 | ~110 min | 2 | 9 |
| 01-06 | ~28 min | 3 | 6 |
| **Total** | **~257 min ≈ 4h 17m** | **18** | **92** |

## Accomplishments

- **FastAPI shell landed.** `packages/api/src/api/app.py` (lines 1–61) defines `app = FastAPI(title="ES Futures Trading System API", version="0.1.0", description=...)`, imports `from trading_core.config import Settings` at module top, instantiates a module-level `_settings: Settings = Settings()`, and registers exactly one route: `@app.get("/health") def health() -> dict[str, str]: return {"status": "ok", "service": "es-api", "version": app.version}`. No other endpoints — Phase 3 owns `/bars`, `/backtests`, `WS /stream`, etc.
- **TestClient integration tests in place.** `packages/api/tests/test_health.py` (4 tests, all passing):
  1. `test_health_endpoint_returns_200_and_canonical_body` — `TestClient(app).get("/health")` returns `{"status": "ok", "service": "es-api", "version": "0.1.0"}` exactly.
  2. `test_app_is_a_fastapi_instance` — `type(app).__name__ == "FastAPI"`.
  3. `test_only_health_endpoint_registered` — T-01-06-01 mitigation: filters out FastAPI auto-routes (`/openapi.json`, `/docs`, `/docs/oauth2-redirect`, `/redoc`) and asserts the user routes are exactly `["/health"]`. Any future PR that adds an endpoint here in Phase 1 fails this test.
  4. `test_app_imports_trading_core_settings` — FND-01 proof: grabs the underlying module via `sys.modules["api.app"]` (because the package-level `import api.app` resolves to the FastAPI instance after the `__init__.py` re-export), then asserts both `_settings` and `Settings` are present in the module namespace.
- **api/__init__.py re-export.** `packages/api/src/api/__init__.py` now does `from api.app import app` so `uvicorn api:app` works at the command line as a shorthand for `uvicorn api.app:app`. The trade-off (the `from X import Y` rebinding makes `import api.app` resolve to the FastAPI instance) is documented in both the `__init__.py` docstring and the test that works around it.
- **apps/web stub finalized.** `apps/web/app/page.tsx` was already verbatim per D-01 from Plan 01-01 — no edits needed. `apps/web/README.md` was extended with explicit `pnpm --filter web dev/build` + `pnpm --filter web exec tsc --noEmit` dev commands, Windows build-duration guidance (30-60s typical; do NOT Ctrl-C mid-run), and a Phase 3 roadmap note mentioning the real `/dashboard` will mount **Lightweight Charts v5.2.0 vanilla inside a `useEffect` ref** per the PROJECT.md NOT-a-wrapper rule.
- **Full Phase 1 acceptance smoke is green.** Five commands, all exit 0:
  - `uv sync --all-packages` → installs all 3 workspace members editable + dev deps
  - `uv run pytest -q` → **195 passed, 1 skipped** in 63s (190 trading-core + 5 api)
  - `pnpm --filter web build` → exit 0 in 19s (Turbopack; 5 static pages prerendered)
  - `pnpm --filter web exec tsc --noEmit` → exit 0
  - `uv run pre-commit run --all-files` → exit 0 (both `Detect hardcoded secrets` + `Forbid datetime.now()/utcnow() without timezone` Passed)
- **ROADMAP + STATE flipped.** Phase 1 row in ROADMAP marked `[x]` with 2026-05-15 completion date; progress table shows 6/6 + Complete; plan 01-06 bullet checked. STATE.md status block reads "Phase 1 complete — FastAPI shell + apps/web finalized + full acceptance smoke green"; Current Position shows "Plan 6 of 6 complete" + 100% progress bar; 4 new Plan 01-06 decisions appended to Accumulated Context.

## Phase 1 REQ-ID Coverage Statement

All 18 Phase 1 REQ-IDs are addressed across the 6 plans. Mapping (per each plan's `requirements_completed` frontmatter):

| REQ-ID | Description | Implemented By |
| --- | --- | --- |
| FND-01 | uv workspace + 3 Python packages + apps/web importable | Plan 01-01 (scaffold) + **Plan 01-06** (FastAPI shell proves api → trading-core import graph) |
| FND-02 | `uv.lock` pins of vectorbt 1.0.0, pandas <3.0, FastAPI, Pydantic v2, DuckDB, structlog, httpx, pytest, hypothesis, respx, freezegun | Plan 01-01 (pyproject.toml + uv.lock committed); **Plan 01-06** verified the pins in the running test suite |
| FND-03 | Pydantic Settings + `.env` + `.env.example` + `config/*.yaml` merge | Plan 01-02 |
| FND-04 | gitleaks pre-commit hook | Plan 01-05 |
| FND-05 | UTC discipline + AST-based naive-datetime pre-commit hook | Plan 01-05 |
| FND-06 | `instruments.py` SoT with tick_value/point_value/tick_size/session_*_et | Plan 01-02 |
| FND-07 | `EventBus` (asyncio in-process pub/sub) with typed topics | Plan 01-03 |
| FND-08 | `runs` table with git_sha/data_hash/param_hash/seed/adr_hash (CI assertion lands Phase 3) | Plan 01-04 |
| FND-09 | structlog JSON + correlation IDs | Plan 01-02 |
| FND-10 | Provider-validation ADR | Phase 0 Plan 03 (pre-Phase-1) |
| MD-01 | `DataSource` Protocol | Plan 01-02 |
| MD-02 | `TradingViewDataSource` | Plan 01-04 |
| MD-03 | `TwelveDataSource` | Plan 01-04 |
| MD-04 | DuckDB + Hive-Parquet idempotent upsert; single-writer | Plan 01-04 |
| MD-05 | CME equity-index RTH filter | Plan 01-03 |
| MD-06 | Bar timestamps documented as open-time | Plan 01-02 (Bar model + docstring) |
| MD-07 | Bar-gap detector + `bar_gaps` table | Plan 01-03 (detector) + Plan 01-04 (table) |
| MD-08 | Rollover-seam detector (3rd-Friday-of-Mar/Jun/Sep/Dec) | Plan 01-03 |
| MD-09 | `seed_bars.py --symbol --tf --from --to` CLI | Plan 01-05 |
| MD-10 | Daily TV↔Twelve-Data reconciliation | **Deferred to Phase 6** per ROADMAP scope note (requires TV bridge) |

So 18 of 19 Phase 1 REQ-IDs are addressed in Phase 1 itself; MD-10 is explicitly deferred to Phase 6 per ROADMAP §"Phase 1 Notes" and is NOT a Phase 1 gap.

## FastAPI Startup Smoke Result

TestClient is the test-suite path (in-process; no uvicorn lifecycle). For local sanity the operator can run:

```powershell
uv run uvicorn api.app:app --host 127.0.0.1 --port 8000 --workers 1
# (separate shell)
curl http://127.0.0.1:8000/health
# {"status":"ok","service":"es-api","version":"0.1.0"}
```

The `__init__.py` re-export also makes the shorthand `uvicorn api:app` work. The README documents both forms.

## Final Acceptance Smoke — Verbatim Command Output

```
$ uv sync --all-packages
warning: The `tool.uv.dev-dependencies` field (used in `pyproject.toml`) is deprecated …
+ trading-core==0.1.0 (from file:///C:/Users/Admin/Desktop/Day%20Trading/packages/trading-core)
+ tv-bridge==0.1.0 (from file:///C:/Users/Admin/Desktop/Day%20Trading/packages/tv-bridge)
+ es-api  (already editable)
+ … (138 packages total)

$ uv run pytest -q
…
195 passed, 1 skipped in 63.38s (0:01:03)

$ pnpm --filter web build
> next build
▲ Next.js 16.2.6 (Turbopack)
  Creating an optimized production build ...
✓ Compiled successfully in 6.8s
  Running TypeScript ...
  Finished TypeScript in 5.5s ...
  Collecting page data using 5 workers ...
  Generating static pages using 5 workers (4/4) in 912ms
  Finalizing page optimization ...
Route (app)
┌ ○ /
└ ○ /_not-found
EXIT=0
BUILD_DURATION_SECONDS=19

$ pnpm --filter web exec tsc --noEmit
EXIT=0

$ uv run pre-commit run --all-files
Detect hardcoded secrets ........................................................ Passed
Forbid datetime.now() / datetime.utcnow() without timezone ...................... Passed
EXIT=0
```

## Done-Criteria Spot Checks

| Check | Result |
| --- | --- |
| `uv run pytest packages/api/tests/test_health.py -q` | 4 passed in 1.63s |
| `uv run python -c "from api.app import app; print(type(app).__name__)"` | prints `FastAPI` |
| `uv run python -c "from api.app import app; print([r.path for r in app.routes if hasattr(r, 'path')])"` | `['/openapi.json', '/docs', '/docs/oauth2-redirect', '/redoc', '/health']` |
| `grep -nE "from trading_core" packages/api/src/api/app.py` | 1 match (line 35: `from trading_core.config import Settings`) |
| `grep -cE "@app\.(get\|post\|put\|delete\|websocket)" packages/api/src/api/app.py` | **1** — T-01-06-01 invariant holds |
| `grep -n "ES Futures Trading System" apps/web/app/page.tsx` | line 6 (`<h1>ES Futures Trading System</h1>`) |
| `grep -nE "Tailwind\s*v?3" apps/web/README.md` | 3 matches (header + rationale + comment) |
| `grep -n "use client" apps/web/app/page.tsx` | 0 matches — server component |
| `grep -l "Phase 1: Foundation scaffold" apps/web/.next/server/app/*.html` | `apps/web/.next/server/app/index.html` |
| `grep -nE "01-0[1-6]-PLAN\.md" .planning/ROADMAP.md` | 6 matches (all 6 plans enumerated under Phase 1) |
| `pnpm --filter web build` | exit 0, 19s |
| `pnpm --filter web exec tsc --noEmit` | exit 0 |
| `uv run pre-commit run --all-files` | exit 0 |

## Decisions Made

See `key-decisions` frontmatter for the full set. Highlights:

1. **FastAPI shell ships ONLY /health.** Codified by `test_only_health_endpoint_registered` (T-01-06-01).
2. **Module-level FastAPI + Settings instantiation** — no Depends/lifespan yet; Phase 3 refactors when integration shape is known.
3. **`api/__init__.py` re-exports `app`** so `uvicorn api:app` works; trade-off documented (the `from X import Y` rebinding consequence on `import api.app`).
4. **`pytest_plugins` re-export doesn't work** under the project's `--import-mode=importlib` + no `tests/__init__.py` setup; api tests use TestClient directly and the conftest stays empty.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocker] `pytest_plugins = ["trading_core.tests.conftest"]` does not work under the project's import setup**

- **Found during:** Task 1 GREEN, first `uv run pytest packages/api/tests/test_health.py` run after adding the `pytest_plugins` line to `packages/api/tests/conftest.py` per the plan action's note that "Plan 02 Task 1 may have already done this; verify and update if not".
- **Issue:** Plan 01-01 decision #1 dropped all `tests/__init__.py` files (cross-package conftest registration collision under default rootdir collection). Under `--import-mode=importlib`, conftest discovery works by file path, but `pytest_plugins` strings are still passed through `importlib.import_module(...)` — which needs `trading_core.tests` to be an importable package. It is not. Result: `ImportError: No module named 'trading_core.tests'` during conftest load → test collection error.
- **Fix:** Removed the `pytest_plugins` line and documented the constraint with a comment. The api tests do not currently need shared trading-core fixtures (TestClient is self-contained). Phase 3, when it adds tests that need shared fixtures, can use the same `sys.path.insert` pattern already in `packages/trading-core/tests/conftest.py` line 25.
- **Files modified:** `packages/api/tests/conftest.py`
- **Commit:** `2eab29b` (Task 1 GREEN)

**2. [Rule 1 - Bug + Rule 3 - Blocker] `import api.app as app_module` resolves to the FastAPI instance, not the module**

- **Found during:** Task 1 GREEN, first run of `test_app_imports_trading_core_settings`.
- **Issue:** The test originally did `import api.app as app_module` and asserted `hasattr(app_module, "_settings")`. After adding `from api.app import app` to `packages/api/src/api/__init__.py` (per the plan action's "re-export so `uvicorn api:app` works"), Python's `from X import Y` semantics rebind `api.app` to the imported FastAPI instance at the package namespace level. So `import api.app` retrieves the FastAPI app, not the module. `hasattr(FastAPI_instance, "_settings")` is False.
- **Fix:** The test now imports `api` first (triggering the re-export) and then grabs the underlying module via `sys.modules["api.app"]`. This is the documented Python idiom for "the submodule the package re-exported a name from". Both halves of the assertion (`hasattr(submodule, "_settings")` + `hasattr(submodule, "Settings")`) pass.
- **Files modified:** `packages/api/tests/test_health.py`
- **Commit:** `2eab29b` (Task 1 GREEN)

**3. [Rule 3 - Blocker] Pre-existing `test_help_exits_zero_and_lists_flags` fails under the Phase 1 acceptance smoke**

- **Found during:** Task 1 verification — running `uv run pytest packages/trading-core -q` to confirm the full suite is still green after the api changes.
- **Issue:** Plan 01-05's subprocess test does `subprocess.run(["uv", "run", "python", scripts/seed_bars.py, "--help"], …)` with bare `"uv"` as argv[0]. On the operator's machine `uv.exe` lives at `C:\Users\Admin\.local\bin\uv.exe` but `uv` (without extension) is NOT on PATH under bash invocations (and even on PowerShell, `uv` is shadowed by Microsoft Store stubs). Result: `FileNotFoundError: [WinError 2] The system cannot find the file specified`. This is pre-existing — Plan 01-05 SUMMARY claimed 190 passed on the day the plan was authored, presumably from a shell where `uv` was on PATH. But under the Phase 1 acceptance smoke this test would block the `uv run pytest -q` exit-0 requirement.
- **Fix:** Replaced `["uv", "run", "python", str(_SEED_SCRIPT), "--help"]` with `[sys.executable, str(_SEED_SCRIPT), "--help"]`. The test is already executing inside `uv run pytest`, so the venv is active and `sys.executable` points to the right Python; the `uv run` indirection adds nothing and creates the PATH dependency. The test still proves the Pitfall-5 UTF-8 reconfigure works (because the spawned child is a real subprocess, just one whose Python interpreter is resolved without going through `uv`). Verified: test now passes in 20s.
- **Files modified:** `packages/trading-core/tests/integration/test_seed_bars_e2e.py`
- **Commit:** `2eab29b` (Task 1 GREEN — included alongside the Task 1 changes because without it the acceptance smoke at Task 3 would have failed)

### Known Deprecation Warnings (non-blocking)

- `tool.uv.dev-dependencies` deprecation continues (carried forward from Plan 01-01, 01-04, 01-05). Not addressed; a future cleanup pass can migrate to `[dependency-groups]`.

## Authentication Gates

None. The FastAPI shell has no authentication of any kind in Phase 1 — `/health` is intentionally unauthenticated (liveness checks should be cheap). Phase 5 + Phase 7 will add operator-level auth if/when the system exposes more sensitive surfaces. Paper-only constraint per PROJECT.md means no broker keys to protect in v1.

## Threat Model Disposition Confirmations

| Threat ID | Mitigation Implemented |
| --- | --- |
| T-01-06-01 (FastAPI shell exposing endpoints beyond /health) | `test_only_health_endpoint_registered` asserts the user-route set equals `["/health"]` — fails on any additional `@app.get/post/put/delete/websocket` decorator. Done-criterion `grep -cE "@app\\.(get\|post\|put\|delete\|websocket)" packages/api/src/api/app.py` returns **1**. |
| T-01-06-02 (/health leaking Settings values) | The `/health` handler returns only the three literal strings `status`, `service`, `version` — no Settings fields, no env-derived values. Verified by `test_health_endpoint_returns_200_and_canonical_body` which asserts the exact-body match. |
| T-01-06-03 (Acceptance smoke silenced by skipping pre-commit) | `uv run pre-commit run --all-files` is the 5th and final step of the documented smoke; `--no-verify` is forbidden by CLAUDE.md GSD workflow and not used in any commit in this plan. Every commit in this plan triggered the two installed hooks (gitleaks + no-naive-tz) and both passed. |
| T-01-06-04 (Background `pnpm build` consuming the operator's machine) | Build measured at 19 seconds on this dev machine — well within the threat-model "accept" budget (< 30s). |

## Self-Check: PASSED

**Files verified to exist:**

- FOUND: packages/api/src/api/app.py
- FOUND: packages/api/src/api/__init__.py (re-export)
- FOUND: packages/api/tests/test_health.py
- FOUND: packages/api/tests/conftest.py (empty with docstring)
- FOUND: apps/web/app/page.tsx (unchanged from Plan 01-01 — already matches D-01)
- FOUND: apps/web/README.md (updated)
- FOUND: .planning/ROADMAP.md (Phase 1 [x])
- FOUND: .planning/STATE.md (Phase 1 complete)

**Commits verified in git log:**

- FOUND: 1b783aa test(01-06): add RED test_health for FastAPI shell + /health
- FOUND: 2eab29b feat(01-06): add FastAPI shell with GET /health (FND-01 import-graph proof)
- FOUND: f7919d3 feat(01-06): finalize apps/web README with dev commands + Phase 3 roadmap
- FOUND: 61d544f docs(01-06): mark Phase 1 complete in ROADMAP + STATE (6/6 plans)

**Test gate verified:** `uv run pytest -q` → 195 passed, 1 skipped in 63s. Full acceptance smoke (5 commands) all exit 0.

## Next Phase Readiness

- **Phase 2 (Strategy Engine + Indicators)** inherits: trading_core.config.Settings (Plan 01-02), Bar + Signal + StrategyContext + 4 Protocols (Plan 01-02), structlog audit logging (Plan 01-02), RTH/rollover/gap calendars (Plan 01-03), EventBus (Plan 01-03), DuckDBStore + Parquet (Plan 01-04), seed_bars CLI for backfill (Plan 01-05), FastAPI app shell (this plan). Every load-bearing Phase 2 surface is already in place.
- **Phase 3 (Vertical MVP Slice + Backtester)** inherits the FastAPI shell at `api.app:app`. Adding the real surface (`/bars`, `/backtests`, `WS /stream`, `/positions`, `/trades`, `/equity`) is purely additive — no architectural refactor needed. Phase 3 will:
  - Replace the module-level `_settings = Settings()` with a FastAPI lifespan + `Depends()` injection (when /bars actually needs to read TwelveDataSource).
  - Replace the module-level `app = FastAPI(...)` with an app factory if Phase 3 introduces test isolation needs (TestClient still works either way).
  - Add a single import edit to `app.py`: `from .routes import bars, backtests, positions, …; app.include_router(bars.router); …` — Plan 01-06's shell is small enough to grep at PR time.
- **Reproducibility CI (Phase 3 + Phase 8)** consumes the `runs` table baseline locked by Plan 01-04. seed_bars idempotency is proven by Plan 01-05. The Phase 3 CI gate compares equity-curve Parquet bytes across two `run_backtest.py` runs — the inputs to that comparison are ready.
- **CLAUDE.md skill discovery for Phase 2:** none changed; the only new file is `.vscode/` (untracked, ignored per project pattern — not a Phase 1 deliverable).

---
*Phase: 01-foundation-data-in*
*Plan: 06*
*Completed: 2026-05-15*
