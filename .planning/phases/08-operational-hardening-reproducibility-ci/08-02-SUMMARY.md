---
phase: 08-operational-hardening-reproducibility-ci
plan: "02"
subsystem: ci
tags: [ci, github-actions, windows, pytest, vitest, reproducibility]
dependency_graph:
  requires: ["08-01"]
  provides: ["windows-ci-workflow"]
  affects: [".github/workflows/ci.yml"]
tech_stack:
  added: ["github-actions", "astral-sh/setup-uv@v5", "pnpm/action-setup@v3"]
  patterns: ["windows-latest runner", "path-with-space checkout", "utf-8-env-enforcement"]
key_files:
  created:
    - .github/workflows/ci.yml
  modified: []
decisions:
  - "D-07: Two windows-latest jobs (python-tests + frontend-tests) — no Linux/macOS per OP-4"
  - "D-08: checkout path: 'Day Trading' exercises path-with-space on CI runner matching local dev"
  - "D-09: PYTHONUTF8=1 and PYTHONIOENCODING=utf-8 on python-tests job enforces UTF-8 throughout"
  - "Supply-chain: all actions pinned to major-version tags (actions/@v4, astral-sh/@v5, pnpm/@v3)"
metrics:
  duration: "5m"
  completed: "2026-05-20"
  tasks_completed: 1
  files_created: 1
  files_modified: 0
---

# Phase 08 Plan 02: Windows CI Workflow Summary

**One-liner:** GitHub Actions CI with two `windows-latest` jobs (uv+pytest and pnpm+vitest) checking out into a path-with-space with UTF-8 env vars enforced.

## Objective

Deliver the Windows CI workflow (ROADMAP Phase 8 success criterion 2): a `.github/workflows/ci.yml` with `python-tests` and `frontend-tests` jobs running on `windows-latest`, checking out to `path: "Day Trading"` to exercise the path-with-space constraint, and running the full pytest and vitest suites on every push/PR to master/main.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Create .github/workflows/ci.yml | see below | .github/workflows/ci.yml |

## Implementation Details

### `.github/workflows/ci.yml`

Two-job GitHub Actions workflow:

**`python-tests` job:**
- `runs-on: windows-latest`
- `env: PYTHONUTF8: "1"` and `PYTHONIOENCODING: "utf-8"` (D-09)
- `defaults.run.working-directory: "Day Trading"` and `defaults.run.shell: pwsh`
- Steps: `actions/checkout@v4` with `path: "Day Trading"` (D-08) → `astral-sh/setup-uv@v5` → `uv sync` → `uv run pytest --tb=short -q`

**`frontend-tests` job:**
- `runs-on: windows-latest`
- `defaults.run.working-directory: "Day Trading"` and `defaults.run.shell: pwsh`
- Steps: `actions/checkout@v4` with `path: "Day Trading"` → `pnpm/action-setup@v3` with `version: 9` → `pnpm install` → `pnpm --filter web exec vitest run`

All third-party actions pinned to major-version tags from official namespaces (T-08-05 supply-chain mitigation). No `@main` or fork refs. No secrets used (T-08-06 satisfied by design).

## Acceptance Criteria Verification

- [x] `.github/workflows/ci.yml` parses as valid YAML
- [x] Two jobs, both `runs-on: windows-latest`
- [x] `path: "Day Trading"` on both checkout steps (D-08)
- [x] `PYTHONUTF8` and `PYTHONIOENCODING` env vars on python-tests job (D-09)
- [x] `uv sync` and `uv run pytest --tb=short -q` in python-tests
- [x] `pnpm --filter web exec vitest run` in frontend-tests
- [x] Triggers on push and pull_request to master and main
- [x] All actions version-pinned (`@v4` / `@v5` / `@v3`), none reference `@main`

## Deviations from Plan

None — plan executed exactly as written. The canonical `.github/workflows/ci.yml` structure from `08-PATTERNS.md` was used verbatim. Job-level `defaults.run.shell: pwsh` is used (matching the plan action description) while individual `run:` steps inherit it rather than specifying shell per-step (equivalent result, cleaner YAML).

## Threat Surface Scan

| Flag | File | Description |
|------|------|-------------|
| T-08-05 mitigated | .github/workflows/ci.yml | All third-party actions pinned to major-version tags from official namespaces |
| T-08-07 accepted | .github/workflows/ci.yml | Triggers limited to push/pull_request on master/main; no pull_request_target or workflow_run |

No new threat surface beyond what was enumerated in the plan's threat model.

## Known Stubs

None — the CI workflow is complete and directly executable by GitHub Actions.

## Self-Check

- [x] `.github/workflows/ci.yml` exists and contains expected content (verified via Read tool)
- [x] Two jobs present: `python-tests` and `frontend-tests`
- [x] Both jobs use `windows-latest`
- [x] `path: "Day Trading"` checkout present in both jobs
- [x] UTF-8 env vars present in python-tests
- [x] Supply-chain pins verified: `@v4`, `@v5`, `@v3` — no `@main`

## Self-Check: PASSED
