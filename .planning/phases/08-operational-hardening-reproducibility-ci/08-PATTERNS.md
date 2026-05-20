# Phase 8: Operational Hardening + Reproducibility CI - Pattern Map

**Mapped:** 2026-05-20
**Files analyzed:** 8 new/modified files
**Analogs found:** 7 / 8

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `scripts/replay.py` | utility/CLI | request-response (bar-by-bar pipeline) | `scripts/run_backtest.py` | exact |
| `packages/trading-core/tests/integration/test_replay_audit_log.py` | test | batch | `packages/trading-core/tests/integration/test_reproducibility.py` | exact |
| `packages/trading-core/tests/fixtures/golden_audit/2024-06-12.csv` | fixture | file-I/O | `packages/trading-core/tests/fixtures/orb_day.py` | partial (data fixture, diff format) |
| `scripts/gen_golden.py` | utility/CLI | file-I/O | `scripts/run_backtest.py` | role-match |
| `.github/workflows/ci.yml` | config | — | none in repo | no-analog |
| `docs/operations/backup.md` | config/doc | — | none in repo | no-analog |
| `scripts/backup.ps1` | utility/script | file-I/O | none in repo | no-analog |
| `packages/trading-core/tests/conftest.py` (modify) | config | — | `packages/trading-core/tests/conftest.py` | self |

---

## Pattern Assignments

### `scripts/replay.py` (utility/CLI, request-response)

**Analog:** `scripts/run_backtest.py`

**Imports pattern** (`scripts/run_backtest.py` lines 31–63):
```python
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

# Defensive: reconfigure stdout/stderr to UTF-8 BEFORE any module-level import
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Make sure `packages/trading-core/src` is on sys.path when invoked outside the uv shim
_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "packages" / "trading-core" / "src"
if _SRC.exists() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from trading_core.config import Settings
from trading_core.execution.paper import PaperExecutor
from trading_core.logging import get_logger, setup_logging
from trading_core.risk.models import RiskConfig
from trading_core.risk.full_risk_manager import FullRiskManager
from trading_core.storage.duckdb_store import DuckDBStore
from trading_core.strategy.orb import ORBConfig, ORBStrategy
from trading_core.strategy.models import StrategyContext
```

**Argparse / choices= security pattern** (`scripts/run_backtest.py` lines 78–163):
```python
def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="replay",
        description="...",
    )
    p.add_argument(
        "--symbol",
        required=True,
        choices=["ES", "MES", "SPY"],    # T-03-03-01: whitelist prevents injection
        help="Instrument symbol.",
    )
    p.add_argument(
        "--tf",
        required=True,
        choices=["1m", "5m", "15m"],
        help="Bar timeframe.",
    )
    p.add_argument(
        "--from",
        dest="frm",
        type=_parse_iso_utc,
        required=True,
        help="ISO 8601 start (inclusive, UTC).",
    )
    p.add_argument(
        "--to",
        type=_parse_iso_utc,
        required=True,
        help="ISO 8601 end (exclusive, UTC).",
    )
    p.add_argument(
        "--output-dir",
        dest="output_dir",
        type=Path,
        default=None,
        help="Directory for replay audit-log CSV output (default: temp dir).",
    )
    p.add_argument(
        "--risk-config",
        dest="risk_config",
        type=Path,
        default=Path("config/risk.yaml"),
        help="Path to risk YAML config (default: config/risk.yaml).",
    )
    p.add_argument(
        "--duckdb-path",
        dest="duckdb_path",
        type=Path,
        default=None,
        help="Override Settings.duckdb_path.",
    )
    return p
```

**Core async pipeline pattern** (`scripts/run_backtest.py` lines 166–386):
```python
async def main(args: argparse.Namespace) -> int:
    settings = Settings()
    duckdb_path: Path = args.duckdb_path or settings.duckdb_path

    setup_logging(settings.audit_log_dir)

    log = get_logger(__name__)
    log = log.bind(symbol=args.symbol, tf=args.tf)

    log.info("replay.start", from_ts=str(args.frm), to_ts=str(args.to))

    try:
        store = DuckDBStore(duckdb_path)
        store.ensure_schema()

        # Query bars with parameterized SQL (T-03-03-01)
        df = store._conn.execute(
            """
            SELECT symbol, timeframe, ts_utc, open, high, low, close, volume,
                   rollover_seam, provider
            FROM bars
            WHERE symbol = ? AND timeframe = ? AND ts_utc >= ? AND ts_utc < ?
            ORDER BY ts_utc ASC
            """,
            [args.symbol, args.tf, args.frm, args.to],
        ).fetch_df()

        if df.empty:
            raise RuntimeError(f"No bars found for ...")

        bars = [Bar(...) for row in df.itertuples(index=False)]  # Decimal(str(row.open))

        # Instantiate engine components
        strategy = ORBStrategy(ORBConfig())
        # risk_manager = FullRiskManager(config=RiskConfig(**yaml_data), store=store)
        executor = PaperExecutor(args.symbol)

        # Bar-by-bar replay loop (snapshot→on_bar→_push_bar order per BL-1 gate)
        for bar in bars:
            ctx = StrategyContext(...)
            signal = strategy.on_bar(bar, ctx)
            strategy._push_bar(bar)
            if signal:
                decision = await risk_manager.check(signal, risk_state)
                if decision.approved:
                    # PaperExecutor.fill_entry / check_exit / fill_exit
                    # store.write_audit_event(...)

        print(json.dumps({"status": "ok", "event_count": ...}))
        return 0

    except Exception as exc:
        log.exception("replay.failed", error_type=type(exc).__name__)
        return 1

    finally:
        try:
            if store is not None:
                store.close()
        except Exception:
            pass
```

**Exit-code / `__main__` pattern** (`scripts/run_backtest.py` lines 389–392):
```python
if __name__ == "__main__":
    parser = _build_parser()
    parsed_args = parser.parse_args()
    sys.exit(asyncio.run(main(parsed_args)))
```

**RiskConfig YAML loading** — use `yaml.safe_load` (same as `StrategyRegistry.load`, `packages/trading-core/src/trading_core/strategy/registry.py` lines 54–56):
```python
import yaml

with Path(args.risk_config).open("r", encoding="utf-8") as f:
    risk_data = yaml.safe_load(f)
config = RiskConfig(**risk_data)
```

---

### `packages/trading-core/tests/integration/test_replay_audit_log.py` (test, batch)

**Analog:** `packages/trading-core/tests/integration/test_reproducibility.py`

**Imports pattern** (lines 1–23):
```python
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from fixtures.orb_day import orb_day_bars
from trading_core.execution.paper import PaperExecutor
from trading_core.risk.models import RiskConfig
from trading_core.risk.full_risk_manager import FullRiskManager
from trading_core.storage.duckdb_store import DuckDBStore
from trading_core.strategy.orb import ORBConfig, ORBStrategy
```

**Golden-fixture comparison pattern** (modeled on `test_reproducibility.py` lines 46–71):
```python
_GOLDEN_DIR = Path(__file__).parent.parent / "fixtures" / "golden_audit"
_GOLDEN_CSV = _GOLDEN_DIR / "2024-06-12.csv"


def _run_replay_once(output_dir: Path) -> Path:
    """Run bar-by-bar replay over orb_day_bars(date_str='2024-06-12') into output_dir.

    Returns path to the written audit CSV.
    """
    bars = orb_day_bars(date_str="2024-06-12")
    store = DuckDBStore(output_dir / "test.duckdb")
    store.ensure_schema()
    strategy = ORBStrategy(ORBConfig())
    risk_manager = FullRiskManager(config=RiskConfig(), store=store)
    executor = PaperExecutor("SPY")
    # ... bar-by-bar loop calling store.write_audit_event() ...
    return output_dir / "audit" / "2024-06-12.csv"


def test_replay_audit_log_byte_identical(tmp_path: Path, request):
    """SP-04: replay produces byte-identical audit-log CSV against golden fixture."""
    if request.config.getoption("--update-golden", default=False):
        # Regenerate golden fixture instead of asserting
        _GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
        output = _run_replay_once(tmp_path)
        import shutil
        shutil.copy(output, _GOLDEN_CSV)
        pytest.skip("Golden fixture updated — re-run without --update-golden to assert.")
        return

    assert _GOLDEN_CSV.exists(), (
        f"Golden fixture missing: {_GOLDEN_CSV}. "
        "Run with --update-golden to generate it."
    )
    output = _run_replay_once(tmp_path)

    # Byte comparison — same as FND-08 equity-Parquet approach
    assert output.read_bytes() == _GOLDEN_CSV.read_bytes(), (
        "Audit log CSV does not match golden fixture. "
        "If audit schema changed intentionally, regenerate with --update-golden."
    )
```

**UTF-8 encoding assertion** (additional test):
```python
def test_audit_csv_is_utf8_no_bom(tmp_path: Path):
    """D-09: audit CSV written by replay is UTF-8 without BOM."""
    output = _run_replay_once(tmp_path)
    raw = output.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf"), "CSV must not have UTF-8 BOM."
    # Decode must succeed without errors
    output.read_text(encoding="utf-8")
```

**Subprocess subprocess pattern for `write_audit_event` kill-9 survival** (`test_phase5_kill9.py` lines 86–177) — re-use for any subprocess-based CI tests:
```python
import subprocess
import sys
import time

proc = subprocess.Popen(
    [sys.executable, str(script_path)],
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
)
time.sleep(1.5)
proc.kill()
proc.wait(timeout=5)
time.sleep(0.2)  # OS file-handle release
```

---

### `packages/trading-core/tests/fixtures/golden_audit/2024-06-12.csv` (fixture, file-I/O)

**Analog:** `packages/trading-core/tests/fixtures/orb_day.py` (data-fixture role; CSV format is different)

**CSV schema** (from `duckdb_store.py` line 217):
```
event_id,ts_utc,topic,entity_id,reason_code,payload_json
```

**Generation pattern** — `scripts/gen_golden.py` writes this file by running the replay loop over `orb_day_bars(date_str="2024-06-12")`. The CSV must be:
- UTF-8 encoded, no BOM
- Written by `csv.writer` with `newline=""` (Python default line endings) — matching `DuckDBStore.write_audit_event` exactly (lines 702–708 of `duckdb_store.py`)
- Committed to the repo; never regenerated automatically except via `--update-golden`

---

### `scripts/gen_golden.py` (utility/CLI, file-I/O)

**Analog:** `scripts/run_backtest.py` (same CLI skeleton, simpler pipeline)

**Pattern:** Minimal CLI — runs replay once, writes to `packages/trading-core/tests/fixtures/golden_audit/2024-06-12.csv`. No argparse required (hard-coded fixture date). Uses same UTF-8 reconfigure header and `_REPO_ROOT`/`_SRC` path setup as all other scripts.

**Imports and structure** (`scripts/run_backtest.py` lines 31–51):
```python
#!/usr/bin/env python3
"""Generate golden audit-log CSV fixture for test_replay_audit_log.py.

Usage:
    uv run python scripts/gen_golden.py

Writes: packages/trading-core/tests/fixtures/golden_audit/2024-06-12.csv
"""
from __future__ import annotations
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "packages" / "trading-core" / "src"
if _SRC.exists() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
```

---

### `packages/trading-core/tests/conftest.py` (modification — add `--update-golden`)

**Analog:** `packages/trading-core/tests/conftest.py` (self — modify existing file)

**Existing pattern** (lines 1–86 of `conftest.py`) — `sys.path` prepend + pytest fixtures. The `--update-golden` flag follows standard pytest custom option registration:

```python
# Add at the top of conftest.py, before the existing fixture definitions:

def pytest_addoption(parser):
    """Register --update-golden flag for regenerating golden audit-log fixtures."""
    parser.addoption(
        "--update-golden",
        action="store_true",
        default=False,
        help=(
            "Regenerate golden audit-log CSV fixture instead of asserting against it. "
            "Run: uv run pytest packages/trading-core/tests/integration/"
            "test_replay_audit_log.py --update-golden"
        ),
    )
```

**Usage in test** (`request.config.getoption("--update-golden", default=False)`) — matches pytest standard pattern; `default=False` ensures the flag is optional and CI never accidentally regenerates.

---

### `.github/workflows/ci.yml` (config, no-analog)

**No analog in codebase.** Use CONTEXT.md D-07/D-08/D-09 decisions directly.

**Canonical structure from CONTEXT.md:**
```yaml
name: CI

on:
  push:
    branches: [master, main]
  pull_request:
    branches: [master, main]

jobs:
  python-tests:
    runs-on: windows-latest
    env:
      PYTHONUTF8: "1"
      PYTHONIOENCODING: "utf-8"
    defaults:
      run:
        working-directory: "Day Trading"   # matches path: option on checkout
    steps:
      - uses: actions/checkout@v4
        with:
          path: "Day Trading"              # D-08: exercise path-with-space
      - uses: astral-sh/setup-uv@v5
      - run: uv sync
        shell: pwsh
      - run: uv run pytest --tb=short -q
        shell: pwsh

  frontend-tests:
    runs-on: windows-latest
    defaults:
      run:
        working-directory: "Day Trading"
    steps:
      - uses: actions/checkout@v4
        with:
          path: "Day Trading"
      - uses: pnpm/action-setup@v3
        with:
          version: 9
      - run: pnpm install
        shell: pwsh
      - run: pnpm --filter web exec vitest run
        shell: pwsh
```

**Key decisions to enforce:**
- `windows-latest` only (D-07)
- `path: "Day Trading"` on checkout (D-08 — path-with-space test)
- `PYTHONUTF8: "1"` + `PYTHONIOENCODING: "utf-8"` (D-09)
- `astral-sh/setup-uv` (official uv Action — from CLAUDE.md stack)
- `pnpm/action-setup@v3` (pnpm 9.x — from CLAUDE.md stack)

---

### `docs/operations/backup.md` (doc, no-analog)

**No analog in codebase** — `docs/` directory does not exist yet.

**Structure from CONTEXT.md D-10/D-11/D-12:**
- DuckDB snapshot: daily at 16:10 ET via Windows Task Scheduler → `backup.ps1`
- Retention: 90 days for audit CSVs + DuckDB snapshots; indefinite for Parquet bars
- Encrypted-at-rest: BitLocker on the `data/` volume (document only; no scripted 7-zip)
- Section headers: Purpose, File Inventory, Backup Script, Retention Policy, Restore Procedure, Encryption

---

### `scripts/backup.ps1` (utility/script PowerShell, file-I/O)

**No analog in codebase** — no existing `.ps1` files in `scripts/`.

**Pattern from CONTEXT.md D-10/D-11 + D-12 (`scripts/` section):**
```powershell
# backup.ps1 — Daily DuckDB + audit-log snapshot (D-10).
# Intended to run via Windows Task Scheduler at 16:10 ET.
# Usage: pwsh -File scripts\backup.ps1

param(
    [string]$DataRoot = "$PSScriptRoot\..\data",
    [int]$RetentionDays = 90
)

$date = Get-Date -Format "yyyy-MM-dd"
$backupDir = Join-Path $DataRoot "backups\$date"
New-Item -ItemType Directory -Path $backupDir -Force | Out-Null

# 1. DuckDB snapshot
$srcDb = Join-Path $DataRoot "duckdb\trading.duckdb"
$dstDb = Join-Path $backupDir "trading.duckdb"
Copy-Item -Path $srcDb -Destination $dstDb -Force

# 2. Audit-log CSV copy
$srcCsv = Join-Path $DataRoot "logs\audit\$date.csv"
if (Test-Path $srcCsv) {
    Copy-Item -Path $srcCsv -Destination (Join-Path $backupDir "audit_$date.csv") -Force
}

# 3. Retention cleanup — remove backup dirs older than $RetentionDays
Get-ChildItem (Join-Path $DataRoot "backups") -Directory |
    Where-Object { $_.CreationTime -lt (Get-Date).AddDays(-$RetentionDays) } |
    Remove-Item -Recurse -Force

Write-Host "Backup complete: $backupDir"
```

---

## Shared Patterns

### UTF-8 Stdout Reconfigure (all CLI scripts)
**Source:** `scripts/run_backtest.py` lines 42–44
**Apply to:** `scripts/replay.py`, `scripts/gen_golden.py`
```python
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
```

### sys.path Bootstrap (all scripts invoking trading_core)
**Source:** `scripts/run_backtest.py` lines 48–51
**Apply to:** `scripts/replay.py`, `scripts/gen_golden.py`
```python
_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "packages" / "trading-core" / "src"
if _SRC.exists() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
```

### Structlog Setup
**Source:** `packages/trading-core/src/trading_core/logging.py` lines 56–129
**Apply to:** `scripts/replay.py`, `scripts/gen_golden.py`
```python
from trading_core.logging import get_logger, setup_logging

setup_logging(settings.audit_log_dir)
log = get_logger(__name__)
log = log.bind(symbol=args.symbol, tf=args.tf)
```

### DuckDB Parameterized Query (no f-string interpolation)
**Source:** `scripts/run_backtest.py` lines 256–265
**Apply to:** `scripts/replay.py`
```python
df = store._conn.execute(
    """
    SELECT symbol, timeframe, ts_utc, open, high, low, close, volume,
           rollover_seam, provider
    FROM bars
    WHERE symbol = ? AND timeframe = ? AND ts_utc >= ? AND ts_utc < ?
    ORDER BY ts_utc ASC
    """,
    [args.symbol, args.tf, args.frm, args.to],
).fetch_df()
```

### DuckDB Write Audit Event
**Source:** `packages/trading-core/src/trading_core/storage/duckdb_store.py` lines 667–709
**Apply to:** `scripts/replay.py` (drives `store.write_audit_event()` per bar); CSV schema is `["event_id", "ts_utc", "topic", "entity_id", "reason_code", "payload_json"]`
```python
store.write_audit_event(
    event_id=new_run_id(),
    ts_utc=bar.ts_utc,
    topic="risk_decisions",
    entity_id=signal.strategy_id,
    reason_code=decision.reason_code,
    payload_json=json.dumps({...}),
)
```

### Decimal-Only Arithmetic in Risk Path
**Source:** `packages/trading-core/src/trading_core/risk/full_risk_manager.py` (throughout)
**Apply to:** `scripts/replay.py` (Bar construction — `Decimal(str(row.open))`, never `float(row.open)`)
```python
Bar(
    ...
    open=Decimal(str(row.open)),
    high=Decimal(str(row.high)),
    low=Decimal(str(row.low)),
    close=Decimal(str(row.close)),
    volume=int(row.volume),
    rollover_seam=bool(row.rollover_seam),
)
```

### Test File Import Mode (no `__init__.py`)
**Source:** `packages/trading-core/tests/conftest.py` lines 22–26
**Apply to:** `packages/trading-core/tests/integration/test_replay_audit_log.py`
```python
# No __init__.py in tests/ — pytest --import-mode=importlib handles discovery.
# Access fixtures via direct import (conftest prepends tests/ to sys.path):
from fixtures.orb_day import orb_day_bars
```

### Finally-Block Resource Cleanup
**Source:** `scripts/run_backtest.py` lines 360–386
**Apply to:** `scripts/replay.py` (store.close() in finally)
```python
finally:
    try:
        if store is not None:
            store.close()
    except Exception:
        pass
```

---

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `.github/workflows/ci.yml` | config | — | No existing CI workflows in repo; first GitHub Actions file |
| `docs/operations/backup.md` | doc | — | No `docs/` directory exists yet; first operational runbook |
| `scripts/backup.ps1` | utility/script | file-I/O | No PowerShell scripts in `scripts/`; all scripts are Python CLIs |

---

## Metadata

**Analog search scope:** `scripts/`, `packages/trading-core/tests/integration/`, `packages/trading-core/tests/fixtures/`, `packages/trading-core/src/trading_core/` (storage, risk, execution, strategy, logging, config)
**Files scanned:** 12 source files read in full or targeted excerpts
**Pattern extraction date:** 2026-05-20
