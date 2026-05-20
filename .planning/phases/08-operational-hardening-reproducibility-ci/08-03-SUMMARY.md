---
phase: 08-operational-hardening-reproducibility-ci
plan: "03"
subsystem: operations
tags: [backup, powershell, documentation, retention-policy, windows]
dependency_graph:
  requires: []
  provides:
    - docs/operations/backup.md
    - scripts/backup.ps1
  affects:
    - data/backups/
tech_stack:
  added: []
  patterns:
    - PowerShell 5.1-compatible Join-Path chaining (no 3-arg Join-Path)
    - Test-Path guard before Copy-Item (warn-not-throw for missing source)
    - Retention cleanup via Get-ChildItem | Where-Object CreationTime | Remove-Item -Recurse -Force
key_files:
  created:
    - scripts/backup.ps1
    - docs/operations/backup.md
    - docs/operations/ (new directory)
  modified: []
decisions:
  - "Use chained 2-arg Join-Path calls for PowerShell 5.1 compatibility (PS5.1 does not support 3+ positional args)"
  - "Null-conditional operator (?.) is PS7+ only — replaced with explicit if/else after Resolve-Path"
  - "DataRoot parameter IS the data directory itself (not the repo root) — default is <PSScriptRoot>\..\data"
metrics:
  duration: "~12 minutes"
  completed: "2026-05-20"
  tasks_completed: 2
  files_created: 2
---

# Phase 08 Plan 03: Backup Policy and Script Summary

**One-liner:** PowerShell 5.1-compatible daily DuckDB + audit-log snapshot script with 90-day rolling retention, paired with a complete operational runbook covering cadence, file inventory, restore steps, and BitLocker encryption recommendation.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Implement scripts/backup.ps1 | a70ba08 | scripts/backup.ps1 |
| 2 | Write docs/operations/backup.md policy document | 1d8a45d | docs/operations/backup.md |

## Verification Results

- `scripts/backup.ps1`: Parses cleanly under PowerShell AST parser (ps1-syntax-ok)
- `scripts/backup.ps1`: Functional test against temp DataRoot — creates `backups/{date}/trading.duckdb` and `backups/{date}/audit_{date}.csv` (PASS)
- `docs/operations/backup.md`: All six required headers present (Purpose, File Inventory, Backup Script, Retention Policy, Restore Procedure, Encryption)
- `docs/operations/backup.md`: Verify command prints `md-ok` (exit 0)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] PowerShell 5.1 incompatibility in backup.ps1**
- **Found during:** Task 1 functional test
- **Issue:** Two PS7+-only features used in initial draft: (1) null-conditional operator `?.Path` on `Resolve-Path` result; (2) 3-argument `Join-Path` for path construction (e.g., `Join-Path $DataRoot "backups" $date`). Both fail in Windows PowerShell 5.1 (the only PowerShell version present on this machine).
- **Fix:** Replaced `?.Path` with explicit `if ($resolved) { ... } else { ... }` pattern. Replaced all 3-argument `Join-Path` calls with chained 2-argument calls: `Join-Path (Join-Path $DataRoot "backups") $date`. Also corrected the default param to use `Join-Path $PSScriptRoot "..\data"` (single expression) instead of a 3-arg form.
- **Files modified:** scripts/backup.ps1
- **Commit:** a70ba08 (incorporated into task commit)

## Known Stubs

None — both files are fully implemented and functional.

## Threat Surface Scan

No new network endpoints, auth paths, or trust-boundary-crossing patterns introduced. `scripts/backup.ps1` operates entirely on the local filesystem under `-DataRoot`. Threat mitigations from the plan's threat model are implemented:

- **T-08-08 (path traversal):** All paths composed via `Join-Path` — no string concatenation, no arbitrary path injection.
- **T-08-09 (unintended delete):** Retention `Remove-Item` pipeline is scoped to `$DataRoot\backups` via `Get-ChildItem -Path $backupsRoot -Directory`; live `duckdb/` and `parquet/` directories are never in scope.
- **T-08-10 (info disclosure):** Documented in backup.md — BitLocker covers backup files at rest; no additional script-level encryption.

## Self-Check: PASSED

| Check | Result |
|-------|--------|
| scripts/backup.ps1 exists | FOUND |
| docs/operations/backup.md exists | FOUND |
| Commit a70ba08 exists | FOUND |
| Commit 1d8a45d exists | FOUND |
