# Backup and Retention Policy

ES Futures Trading System — Operational Runbook

---

## Purpose

The DuckDB store (`data/duckdb/trading.duckdb`) and the Parquet bar history (`data/parquet/`) are the irreplaceable research assets that underpin the project's core value: **trust the numbers**. Every reported backtest result, every equity curve, every trade attribution trace lives in these files. Loss of this data means loss of research continuity.

This document covers:
- What files are backed up and where
- How to run and schedule `scripts/backup.ps1`
- Retention windows for each data category
- How to restore from a backup
- Encrypted-at-rest recommendations

---

## File Inventory

| Path | Description | Backup handled |
|------|-------------|----------------|
| `data/duckdb/trading.duckdb` | Live DuckDB store — bar history, trade ledger, optimization runs, audit events | Yes — daily snapshot |
| `data/parquet/` | Hive-partitioned Parquet bar history (`symbol=/year=/month=`) — the raw bar archive | No — indefinite retention in place; see Retention Policy |
| `data/logs/audit/{date}.csv` | Daily audit-log CSV mirror — one file per session day | Yes — copied on the same day |
| `data/backups/{date}/` | Snapshot destination — created by `backup.ps1` daily | N/A — is the backup |

---

## Backup Script

### What `scripts/backup.ps1` does

`scripts/backup.ps1` performs three operations:

1. **DuckDB snapshot** — copies `data/duckdb/trading.duckdb` to `data/backups/{date}/trading.duckdb`. If the source DB is absent (e.g., on a fresh clone before any data ingestion), a `Write-Warning` is emitted and the copy is skipped rather than throwing an error.
2. **Audit-log CSV copy** — copies `data/logs/audit/{date}.csv` to `data/backups/{date}/audit_{date}.csv`, guarded by `Test-Path` so days with no session generate no error.
3. **Retention cleanup** — removes backup directories under `data/backups/` whose `CreationTime` is older than `RetentionDays` days (default: 90).

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `-DataRoot` | `string` | `<repo root>\data` | Absolute or relative path to the data directory. Must contain `duckdb\` and `logs\audit\` subdirectories. |
| `-RetentionDays` | `int` | `90` | Number of days to retain backup directories before pruning. |

### Manual run

```powershell
# From the repo root — uses defaults (data\ relative to scripts\)
powershell -File scripts\backup.ps1

# With explicit data root (useful for testing against a temp directory)
powershell -File scripts\backup.ps1 -DataRoot C:\path\to\data

# Custom retention window (30 days)
powershell -File scripts\backup.ps1 -RetentionDays 30
```

### Windows Task Scheduler setup

Schedule `backup.ps1` to run daily at **16:10 ET** (after the 16:00 ET RTH close) so the snapshot captures the completed session's audit log and DuckDB state.

**Option A — `schtasks` command line (run as Administrator):**

```powershell
schtasks /Create `
  /TN "ES Trading System - Daily Backup" `
  /TR "powershell -NoProfile -File `"C:\Users\Admin\Desktop\Day Trading\scripts\backup.ps1`"" `
  /SC DAILY `
  /ST 16:10 `
  /RU SYSTEM `
  /F
```

**Option B — Task Scheduler UI:**

1. Open **Task Scheduler** (search in Start menu).
2. Click **Create Basic Task** in the right panel.
3. Name: `ES Trading System - Daily Backup`; click Next.
4. Trigger: **Daily**; start time **4:10 PM**; click Next.
5. Action: **Start a program**; Program: `powershell`; Arguments: `-NoProfile -File "C:\Users\Admin\Desktop\Day Trading\scripts\backup.ps1"`; click Next.
6. Check **Open the Properties dialog...** on Finish; in General tab, select **Run whether user is logged on or not**; click OK.

---

## Retention Policy

| Data category | Retention | Rationale |
|---------------|-----------|-----------|
| `data/backups/{date}/trading.duckdb` | **90 days** (rolling) | Covers a full quarter of session history; `backup.ps1` auto-prunes directories older than `RetentionDays`. |
| `data/backups/{date}/audit_{date}.csv` | **90 days** (rolling) | Mirrors the DuckDB snapshot window; audit log is redundant once the DuckDB snapshot covers the same period. |
| `data/parquet/` (bar history) | **Indefinite** | The full bar archive is the core research asset. It is never auto-deleted. Disk usage grows at roughly 50–100 MB/year for ES 1m bars; a modern laptop handles 10+ years without issue. |
| `data/logs/audit/{date}.csv` (live log) | Not managed by `backup.ps1` | Raw audit CSVs in the live log directory are not pruned by the backup script. Manage these manually or add a separate cleanup task if disk pressure arises. |

---

## Restore Procedure

To restore from a backup snapshot:

1. **Stop the FastAPI process.** DuckDB enforces a single-writer convention — the API server must not hold the database file open during restore.

   ```powershell
   # If running via uv:
   # Ctrl-C in the terminal, or find and kill the process:
   Get-Process python | Stop-Process -Force
   ```

2. **Identify the backup to restore.** List available snapshots:

   ```powershell
   Get-ChildItem data\backups -Directory | Sort-Object Name
   ```

3. **Copy the snapshot back to the live location:**

   ```powershell
   # Replace 2026-05-15 with the desired date
   Copy-Item -Path "data\backups\2026-05-15\trading.duckdb" `
             -Destination "data\duckdb\trading.duckdb" `
             -Force
   ```

4. **Restart the API server:**

   ```powershell
   uv run uvicorn api:app --reload
   ```

5. **Verify.** Open the web UI and confirm that bar history and trade records load correctly for the expected date range.

> **Note:** Restoring from a DuckDB snapshot rolls back trade ledger and optimization run history to the snapshot date. Parquet bar files are unaffected — they are never modified by the DuckDB restore.

---

## Encryption

### Encrypted at rest — BitLocker recommendation

The backup files in `data/backups/` inherit the encryption posture of the drive they reside on. The recommended approach is **BitLocker drive encryption** on the volume hosting the `data/` directory:

- Windows 11 Home/Pro ships BitLocker (or Device Encryption on Home). Enable it in **Settings > Privacy & security > Device encryption**.
- Once the drive is BitLocker-encrypted, all files under `data/` — including backups — are encrypted at rest with no additional tooling required.
- This satisfies the encrypted-at-rest recommendation at the OS level.

### What `backup.ps1` does NOT do

`backup.ps1` does **not** bundle 7-zip AES encryption or any application-level encryption of the snapshot files. The ROADMAP Phase 8 notes this as an option, not a requirement. Adding 7-zip encryption would require:

- Installing 7-zip and adding it to PATH
- Managing and securing an encryption passphrase
- Additional restore complexity (decrypt before copy)

For a single-operator local machine protected by BitLocker, this additional layer provides minimal security benefit. If the machine is shared or the data directory is synced to a cloud drive without client-side encryption, consider adding `7z a -mhe=on -p<passphrase>` to the backup step.
