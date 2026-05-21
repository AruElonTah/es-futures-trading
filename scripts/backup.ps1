# backup.ps1 — Daily DuckDB + audit-log snapshot.
#
# Purpose: Snapshot the live DuckDB store and the current-day audit-log CSV into
#          a dated directory under data\backups\. Prunes backup directories older
#          than RetentionDays. Intended to run via Windows Task Scheduler at
#          16:10 ET daily after the RTH session closes.
#
# Usage:
#   pwsh -File scripts\backup.ps1
#   powershell -File scripts\backup.ps1
#   powershell -File scripts\backup.ps1 -DataRoot C:\path\to\data -RetentionDays 60
#
# Parameters:
#   -DataRoot      Path to the data directory (default: <repo root>\data).
#                  Must contain duckdb\, logs\audit\, and will receive backups\.
#   -RetentionDays Number of days to retain backup directories (default: 90).

param(
    [string]$DataRoot = (Join-Path $PSScriptRoot "..\data"),
    [int]$RetentionDays = 90
)

# Resolve to an absolute path so all Join-Path calls below are unambiguous.
$resolved = Resolve-Path $DataRoot -ErrorAction SilentlyContinue
if ($resolved) {
    $DataRoot = $resolved.Path
} else {
    # DataRoot doesn't exist yet (e.g., fresh repo) — create it so the script can proceed.
    New-Item -ItemType Directory -Path $DataRoot -Force | Out-Null
    $DataRoot = (Resolve-Path $DataRoot).Path
}

# ─── 1. Create dated backup directory ──────────────────────────────────────────
$date = Get-Date -Format "yyyy-MM-dd"
$backupDir = Join-Path (Join-Path $DataRoot "backups") $date
New-Item -ItemType Directory -Path $backupDir -Force | Out-Null

# ─── 2. DuckDB snapshot ────────────────────────────────────────────────────────
$srcDb = Join-Path (Join-Path $DataRoot "duckdb") "trading.duckdb"
if (Test-Path $srcDb) {
    $dstDb = Join-Path $backupDir "trading.duckdb"
    Copy-Item -Path $srcDb -Destination $dstDb -Force
} else {
    Write-Warning "DuckDB source not found, skipping DB snapshot: $srcDb"
}

# ─── 3. Audit-log CSV copy ─────────────────────────────────────────────────────
$auditDir = Join-Path (Join-Path $DataRoot "logs") "audit"
$srcCsv = Join-Path $auditDir "$date.csv"
if (Test-Path $srcCsv) {
    $dstCsv = Join-Path $backupDir "audit_$date.csv"
    Copy-Item -Path $srcCsv -Destination $dstCsv -Force
}

# ─── 4. Retention cleanup — remove backup dirs older than $RetentionDays ───────
# WR-02: Parse date from directory name (yyyy-MM-dd) rather than using
# CreationTime, which is unreliable after file copies/restores (e.g., xcopy,
# robocopy, or OneDrive restores reset CreationTime to "now"). The directory
# name is the authoritative backup date.
$backupsRoot = Join-Path $DataRoot "backups"
if (Test-Path $backupsRoot) {
    Get-ChildItem -Path $backupsRoot -Directory |
        Where-Object {
            $dirDate = $null
            if ([datetime]::TryParseExact($_.Name, "yyyy-MM-dd",
                    [System.Globalization.CultureInfo]::InvariantCulture,
                    [System.Globalization.DateTimeStyles]::None,
                    [ref]$dirDate)) {
                $dirDate -lt (Get-Date).Date.AddDays(-$RetentionDays)
            } else {
                $false  # leave unknown-named directories alone
            }
        } |
        Remove-Item -Recurse -Force
}

Write-Host "Backup complete: $backupDir"
