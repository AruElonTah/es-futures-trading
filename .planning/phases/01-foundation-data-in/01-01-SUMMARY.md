---
phase: 01-foundation-data-in
plan: 01
subsystem: foundation
tags: [scaffold, uv-workspace, pnpm-workspace, nextjs, tailwind-v3, toolchain]
requires:
  - Windows 11 + PowerShell + Node.js >= 20
  - Internet access (uv installer, PyPI, npm registry)
provides:
  - es-futures-trading uv workspace with 3 members (trading-core, es-api, tv-bridge) all editable-installed
  - es-futures-monorepo pnpm workspace with apps/web (Next.js 16.2 + React 19 + Tailwind v3)
  - data/{duckdb,parquet,logs/audit}/ runtime tree with .gitkeep markers
  - config/system.yaml placeholder for Plan 01-05 Pydantic Settings wiring
  - Reproducible toolchain: uv 0.11.14, Python 3.12.13, pnpm 9.15.0, Node 25.9.0
affects:
  - .gitignore (extended with .venv/, data globs, !data/**/.gitkeep negation)
  - Every downstream Phase 1 plan (01-02 onward) can now run `uv sync` and `pnpm install` from clean clone
tech-stack:
  added:
    python: ["uv 0.11.14", "Python 3.12.13", "pytest 8.4.2", "pytest-asyncio 0.24.0", "hypothesis 6.152.7", "respx 0.23.1", "freezegun 1.5.5", "mypy 2.1.0", "vectorbt 1.0.0", "pandas 2.3.3", "pyarrow 17.x", "duckdb 1.5.2", "pydantic 2.13.4", "pydantic-settings 2.14.1", "httpx 0.27.2", "structlog 25.5.0", "concurrent-log-handler", "pandas-market-calendars 5.x", "uuid6 2025.0.1", "rich 15.0.0", "mcp 1.x"]
    js: ["pnpm 9.15.0", "next 16.2.6", "react 19.2.4", "typescript 5.9.3", "tailwindcss 3.4.19", "postcss 8.5.14", "autoprefixer 10.5.0", "lightweight-charts 5.2.0", "@tanstack/react-query 5", "zustand 5"]
  patterns:
    - "uv workspace via [tool.uv.workspace] members + [tool.uv.sources] workspace=true cross-references"
    - "pytest --import-mode=importlib (avoids cross-package basename collision)"
    - "Tailwind v3 pin (downgrade-after-init pattern; v4 was create-next-app default)"
key-files:
  created:
    - pyproject.toml (root uv workspace + dev deps + pytest config)
    - uv.lock (committed; 138 packages, platform-resolution-complete)
    - packages/trading-core/{pyproject.toml, src/trading_core/__init__.py, tests/conftest.py, tests/test_import.py}
    - packages/api/{pyproject.toml, src/api/__init__.py, tests/conftest.py, tests/test_import.py}
    - packages/tv-bridge/{pyproject.toml, src/tv_bridge/__init__.py, tests/conftest.py, tests/test_import.py}
    - package.json (root JS workspace)
    - pnpm-workspace.yaml
    - pnpm-lock.yaml (committed)
    - apps/web/* (Next.js stub: app/page.tsx, app/layout.tsx, app/globals.css, tailwind.config.ts, postcss.config.mjs, README.md)
    - data/duckdb/.gitkeep, data/parquet/.gitkeep, data/logs/audit/.gitkeep
    - config/system.yaml
  modified:
    - .gitignore (added .venv/, __pycache__, *.pyc, data globs with !data/**/.gitkeep negation, node_modules/, apps/web/.next/, apps/web/out/, .pnpm-store/)
decisions:
  - "Dropped per-package tests/__init__.py — pytest's default rootdir collection treats sibling tests/ dirs with shared basenames (e.g. test_import.py) as colliding `tests.conftest` plugin registrations on Windows. Combined with --import-mode=importlib, rootless test dirs are the modern pytest convention and unblock collection. D-04's `pytest_plugins` re-export mechanism still works through trading_core.tests.conftest because importlib mode imports tests by file path, not package name."
  - "Used `npm install -g pnpm@9.15.0` fallback because corepack is not present on the operator's Node 25.9 install (expected per assumption A8). pnpm 9.15.0 is on PATH at C:\\Users\\Admin\\AppData\\Roaming\\npm\\pnpm.cmd."
  - "Tailwind v3 pin honored despite create-next-app emitting v4 by default in 2026 (see 01-RESEARCH.md O-1). Downgrade path: pnpm remove tailwindcss @tailwindcss/postcss → pnpm add -D tailwindcss@^3.4 postcss autoprefixer → pnpm exec tailwindcss init -p → hand-write tailwind.config.ts + postcss.config.mjs in v3 syntax."
  - "Stripped next/font/google Geist from layout.tsx — pulls fonts at build time (requires network) and bloats the Phase 1 stub. Plain HTML+Tailwind font-mono classes are sufficient for the placeholder."
metrics:
  duration: "~12 minutes (toolchain install + scaffold + 3 commits)"
  completed_date: "2026-05-14"
---

# Phase 01 Plan 01: Foundation Scaffold Summary

`uv` + `pnpm` toolchains bootstrapped on Windows, three-package Python workspace + Next.js 16.2 / Tailwind v3 / React 19 monorepo authored, full acceptance smoke (`uv sync && uv run pytest -q && pnpm install && pnpm --filter web build && pnpm --filter web exec tsc --noEmit`) green from a clean state.

## Toolchain Versions Installed

| Tool | Version | Source |
| --- | --- | --- |
| uv | 0.11.14 | `irm https://astral.sh/uv/install.ps1 \| iex` |
| Python | 3.12.13 | `uv python install 3.12` (uv-managed CPython) |
| Node.js | 25.9.0 | pre-existing |
| pnpm | 9.15.0 | `npm install -g pnpm@9.15.0` (corepack fallback per assumption A8) |

## FND-02 Evidence — `uv.lock` vectorbt pin

```
2160: name = "vectorbt"
2161: version = "1.0.0"
2162: source = { registry = "https://pypi.org/simple" }
```

Other FND-02-mandated pins resolved by `uv.lock` (all within their pyproject specifiers):

| Package | Resolved version | Constraint |
| --- | --- | --- |
| vectorbt | 1.0.0 | `==1.0.0` |
| pandas | 2.3.3 | `>=2.2,<3.0` |
| pydantic | 2.13.4 | `>=2.13,<3.0` |
| fastapi | 0.136.1 | `>=0.136,<0.137` |
| duckdb | 1.5.2 | `>=1.0,<2.0` |
| structlog | 25.5.0 | `>=25.0` |
| httpx | 0.27.2 | `>=0.27,<0.28` |
| pyarrow | 17.x | `>=17.0,<18.0` (data_hash byte-stability per Pattern 7) |
| pytest | 8.4.2 | `>=8.0,<9.0` |
| hypothesis | 6.152.7 | `>=6.150,<7.0` |
| respx | 0.23.1 | latest |
| freezegun | 1.5.5 | latest |

## Windows Path-with-Space Behavior

The repo path `C:\Users\Admin\Desktop\Day Trading` contains a space. Observed during execution:

- **uv:** zero quoting issues. `uv sync`, `uv run pytest`, and editable installs of all three workspace members all worked when invoked via absolute path `C:\Users\Admin\.local\bin\uv.exe` from a `cd "/c/Users/Admin/Desktop/Day Trading"` shell. uv.lock encodes the path as `file:///C:/Users/Admin/Desktop/Day%20Trading/packages/...` (URL-encoded space) without any operator intervention.
- **pnpm:** zero quoting issues for `install`, `--filter web build`, `--filter web exec tsc --noEmit`. The earlier `pnpm create next-app apps/web ...` initially failed with *"The application path is not writable"* — but that was because the `apps/` parent directory did not exist yet, not a space-related quoting issue. After `mkdir -p apps`, `pnpm create next-app web ...` from inside `apps/` succeeded on the first try.
- **git:** zero issues with the per-task commits; line-ending CRLF warnings are cosmetic.

No `## Known Quirks` section is being added to 01-RESEARCH.md because no space-related quirks were observed.

## Tailwind v3 Downgrade

`pnpm create next-app@latest web --tailwind ...` emitted Tailwind 4.3.0 + `@tailwindcss/postcss` by default. Per the Plan + Open Question O-1, the downgrade was executed inline:

1. `pnpm remove tailwindcss @tailwindcss/postcss`
2. `pnpm add -D tailwindcss@^3.4 postcss autoprefixer` → resolved to `tailwindcss 3.4.19`
3. `pnpm exec tailwindcss init -p` (created `tailwind.config.js` + `postcss.config.js`)
4. Deleted the v3-generated `.js` configs; wrote `tailwind.config.ts` + `postcss.config.mjs` with v3 syntax (content = `app/**/*.{ts,tsx}`, plugins = `{ tailwindcss: {}, autoprefixer: {} }`)
5. Replaced the v4 `app/globals.css` (`@import "tailwindcss"` + `@theme inline {...}`) with v3 directives (`@tailwind base; @tailwind components; @tailwind utilities;`)
6. Stripped `next/font/google Geist` from `app/layout.tsx` (avoids build-time network dep on Windows)
7. Wrote the verbatim placeholder `app/page.tsx` from 01-RESEARCH.md lines 1349–1364

`apps/web/package.json` now declares `tailwindcss: "3.4"` and `pnpm --filter web build` exits 0 with `"ES Futures Trading System"` literal present in the prerendered HTML output (`apps/web/.next/server/app/index.html`).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Removed `tests/__init__.py` from each package's tests/ dir**
- **Found during:** Task 1 (running `uv run pytest -q`)
- **Issue:** With `tests/__init__.py` files present, pytest's default collection treats all three sibling `tests/` dirs as the same `tests` Python package, registering each `conftest.py` under the same `tests.conftest` plugin name → `ValueError: Plugin already registered under a different name`. Adding `--import-mode=importlib` alone is not sufficient because the `__init__.py` files force pytest into the package-based import path.
- **Fix:** Deleted the three `tests/__init__.py` files; kept the `--import-mode=importlib` setting in `[tool.pytest.ini_options]` for forward-safety. D-04's plan to share fixtures via `pytest_plugins` re-export still works under importlib mode because conftests are imported by file path, not Python package name.
- **Files modified:** Three deletions vs the plan's stated `files_modified` list — `packages/trading-core/tests/__init__.py`, `packages/api/tests/__init__.py`, `packages/tv-bridge/tests/__init__.py` are NOT present.
- **Commit:** 03ef06a

**2. [Rule 1 - Bug] Rewrote `.gitignore` data/parquet/ rule from directory-style to file-glob**
- **Found during:** Task 3 (running `git check-ignore -v` on `.gitkeep` files)
- **Issue:** The original rule `data/parquet/` excluded the entire directory, which means Git cannot re-include files inside it via the `!data/**/.gitkeep` negation — there is no way to re-include files inside an excluded directory.
- **Fix:** Changed `data/parquet/` → `data/parquet/**/*` so the negation can selectively re-include `.gitkeep`. Verified `data/parquet/symbol=SPY/test.parquet` is gitignored AND `data/parquet/.gitkeep` is staged.
- **Files modified:** `.gitignore`
- **Commit:** 2928f70

**3. [Rule 3 - Blocker] `pnpm create next-app` initial failure on missing `apps/` parent**
- **Found during:** Task 2 (first `pnpm create next-app apps/web ...` invocation)
- **Issue:** create-next-app reported *"The application path is not writable, please check folder permissions and try again"* — actually meant the parent `apps/` directory did not exist.
- **Fix:** `mkdir -p apps && cd apps && pnpm create next-app web ...`. No retry loop, no quoting changes.
- **Files modified:** none (operator-side)
- **Commit:** N/A (fixed inline; final tree committed in 196e02c)

**4. [Rule 3 - Blocker] Stripped `next/font/google Geist` from generated `app/layout.tsx`**
- **Found during:** Task 2 (post-downgrade build verification)
- **Issue:** The create-next-app template pulls Geist + Geist Mono fonts via `next/font/google`, which fetches font files at build time over the network. For a Phase 1 placeholder this is unnecessary build-time fragility on Windows; the v3 globals.css no longer references the `--font-geist-*` CSS variables anyway.
- **Fix:** Removed Geist imports + variable usage; used plain `font-mono` Tailwind class on the page.
- **Files modified:** `apps/web/app/layout.tsx`, `apps/web/app/globals.css` (already rewritten for v3)
- **Commit:** 196e02c

**5. [Rule 2 - Missing critical] Used `uv sync --all-packages` instead of plain `uv sync`**
- **Found during:** Task 1 (post-`uv sync` import smoke test)
- **Issue:** Plain `uv sync` only installs the root project's deps; it does NOT editable-install workspace members by default. The `uv run python -c "import trading_core, api, tv_bridge"` smoke failed with `ModuleNotFoundError: No module named 'trading_core'`.
- **Fix:** Re-ran with `uv sync --all-packages` to install all three workspace members editable. The plan's acceptance step `uv run python -c "import trading_core, api, tv_bridge"` then passed. (`uv sync` in CI / fresh clones must also use `--all-packages`; documented here for downstream plans.)
- **Files modified:** none — uv.lock was already correct; this was a one-time install-path fix.
- **Commit:** N/A (lock was already in 03ef06a)

### Known Deprecation Warnings (non-blocking)

- `warning: The 'tool.uv.dev-dependencies' field (used in 'pyproject.toml') is deprecated and will be removed in a future release; use 'dependency-groups.dev' instead`. The RESEARCH.md skeleton uses the deprecated form; uv 0.11.14 still honors it. Plan 01-02+ can migrate to `[dependency-groups]` if they touch pyproject.toml.

## Authentication Gates

None — all installs hit public registries (astral.sh, PyPI, npm) with no auth required.

## Self-Check: PASSED

**Files verified to exist:**

- FOUND: pyproject.toml
- FOUND: uv.lock
- FOUND: packages/trading-core/pyproject.toml
- FOUND: packages/trading-core/src/trading_core/__init__.py
- FOUND: packages/trading-core/tests/test_import.py
- FOUND: packages/api/pyproject.toml
- FOUND: packages/api/src/api/__init__.py
- FOUND: packages/api/tests/test_import.py
- FOUND: packages/tv-bridge/pyproject.toml
- FOUND: packages/tv-bridge/src/tv_bridge/__init__.py
- FOUND: packages/tv-bridge/tests/test_import.py
- FOUND: package.json, pnpm-workspace.yaml, pnpm-lock.yaml
- FOUND: apps/web/package.json, apps/web/app/page.tsx, apps/web/app/layout.tsx, apps/web/app/globals.css
- FOUND: apps/web/tailwind.config.ts, apps/web/postcss.config.mjs, apps/web/README.md
- FOUND: data/duckdb/.gitkeep, data/parquet/.gitkeep, data/logs/audit/.gitkeep
- FOUND: config/system.yaml

**Commits verified in git log:**

- FOUND: 03ef06a feat(01-01): install uv + pnpm; scaffold uv workspace with 3 Python packages
- FOUND: 196e02c feat(01-01): initialize pnpm workspace + Next.js 16.2 stub on Tailwind v3
- FOUND: 2928f70 chore(01-01): scaffold data/ + config/ tree; full Phase 1 acceptance smoke passes
