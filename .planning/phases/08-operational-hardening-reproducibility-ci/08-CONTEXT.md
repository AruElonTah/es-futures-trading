# Phase 8: Operational Hardening + Reproducibility CI - Context

**Gathered:** 2026-05-20
**Status:** Ready for planning

<domain>
## Phase Boundary

Close out v1 with three deliverables: (1) a `scripts/replay.py` command that re-feeds historical bars bar-by-bar through the full live engine path and asserts byte-identical audit-log CSV output against a committed golden fixture; (2) a GitHub Actions CI workflow running on `windows-latest` covering both Python (pytest) and frontend (vitest) tests; (3) a `docs/operations/backup.md` policy doc and `scripts/backup.ps1` runbook.

**In scope:**
- `scripts/replay.py` CLI — bar-by-bar replay through `DataSource → Strategy → FullRiskManager → PaperExecutor → audit_log`
- Committed golden audit-log CSV fixture at `packages/trading-core/tests/fixtures/golden_audit/`
- `test_replay_audit_log_byte_identical` — CI assertion comparing replay output to golden fixture
- `.github/workflows/ci.yml` — `windows-latest` jobs for Python (uv sync + pytest) and frontend (pnpm install + vitest run)
- CI exercises path-with-spaces (repo path contains a space) and asserts UTF-8 encoding throughout
- `docs/operations/backup.md` — DuckDB snapshot cadence, Parquet retention, audit-log retention, BitLocker note
- `scripts/backup.ps1` — daily DuckDB snapshot + CSV copy to a `data/backups/` directory

**Out of scope:**
- Linux / macOS CI runners — Windows-only per OP-4
- Encrypted backup archives (7-zip AES) — document BitLocker as the recommendation instead
- New strategy features, UI changes, or risk changes

</domain>

<decisions>
## Implementation Decisions

### Replay Pipeline Design

- **D-01: `replay.py` drives the bar-by-bar live engine path, not `BacktestEngine`.** Instantiates `ORBStrategy` + `FullRiskManager` (from `config/risk.yaml`) + `PaperExecutor` and calls `strategy.on_bar()` / `risk_manager.check()` / `executor.fill()` in sequence — the same execution path as the live paper-trading engine. This is the only path that produces an `audit_log` CSV comparable to a real live session.

- **D-02: `FullRiskManager` with `config/risk.yaml`.** Replay loads the same risk config the original session used. Required for the audit log to match (same sizing, same DD decisions, same reason codes).

- **D-03: Replay reads bars from DuckDB** (`DuckDBStore.get_bars(symbol, tf, from_date, to_date)`), not from a live `DataSource`. The replay is always against persisted bar data — no TV MCP, no Twelve Data calls.

- **D-04: Replay writes audit events to a separate temp output path**, not the live `data/logs/audit/` directory. The CLI accepts `--output-dir` (default: a `tmp_path` managed by the test; explicit path for manual runs). This avoids polluting the live audit log.

### Replay Golden Source

- **D-05: Committed golden CSV fixture in the repo.** A known-good audit-log CSV for a specific synthetic test day is generated once and checked into `packages/trading-core/tests/fixtures/golden_audit/2024-06-12.csv`. The test runs `replay.py` against the same synthetic bars fixture (`orb_day_bars()`) and byte-compares the output against the committed golden. Deterministic, works on a clean clone, no live data dependency.

- **D-06: Golden fixture generation** — a `scripts/gen_golden.py` helper (or a pytest `--update-golden` flag) generates the golden file from the current engine. Once checked in, the golden must match every CI run. Any intentional audit-log schema change requires explicitly regenerating and committing the golden.

### CI Setup

- **D-07: GitHub Actions `.github/workflows/ci.yml` with `windows-latest` runner.** Two jobs:
  1. `python-tests`: `actions/checkout` → `astral-sh/setup-uv` → `uv sync` → `uv run pytest --tb=short -q`
  2. `frontend-tests`: `actions/checkout` → `pnpm/action-setup@v3` → `pnpm install` → `pnpm --filter web exec vitest run`
  Both jobs run on `windows-latest`. CI triggers on push and pull_request to `master`/`main`.

- **D-08: Path-with-spaces coverage.** The repo checkout path on GitHub Actions `windows-latest` runners does not contain spaces by default. To exercise the "Day Trading" path-with-space, the workflow explicitly checks out to `C:\Users\runneradmin\Day Trading\` using the `path:` option on `actions/checkout`. This exercises the actual Windows dev environment shape per ROADMAP OP-4.

- **D-09: UTF-8 assertion.** `run_backtest.py` already reconfigures stdout/stderr to UTF-8 at startup. The CI job adds `$env:PYTHONUTF8 = "1"` and `$env:PYTHONIOENCODING = "utf-8"` as env vars. The pytest suite asserts that audit-log CSV files written during replay are UTF-8 encoded (open with `encoding='utf-8'`, no BOM).

### Backup Policy

- **D-10: Daily DuckDB snapshot after session close.** `backup.ps1` copies the live DuckDB file (`data/duckdb/trading.duckdb`) to `data/backups/{date}/trading.duckdb` and copies `data/logs/audit/{date}.csv` to `data/backups/{date}/audit_{date}.csv`. Intended to run via Windows Task Scheduler at 16:10 ET daily.

- **D-11: Retention windows:**
  - Audit-log CSVs: 90 days (rolling delete of files older than 90 days in `data/backups/`)
  - Parquet bars (`data/parquet/`): indefinite — the full bar history is the core research asset
  - DuckDB snapshots: 90 days (mirrors audit-log window)

- **D-12 (Claude): Encrypted-at-rest is documented, not scripted.** `backup.md` notes that BitLocker drive encryption on the `data/` volume satisfies the encrypted-at-rest requirement. `backup.ps1` does not include 7-zip/AES logic — the ROADMAP says "option", not "required".

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase Goal + Requirements
- `.planning/ROADMAP.md` §"Phase 8: Operational Hardening + Reproducibility CI" — Goal, 3 success criteria (replay.py + golden fixture, Windows CI + path-with-space + UTF-8, backup.md + backup.ps1), requirements (SP-04), Notes (single REQ-ID; OP-4 Windows dev environment match; v1 milestone closure).
- `.planning/ROADMAP.md` §"Cross-Phase Guardrails" — Reproducibility CI must stay green (this phase expands it); four Protocol seams must not be bypassed.
- `.planning/REQUIREMENTS.md` — SP-04 full requirement spec.
- `CLAUDE.md` — Stack constraints (Python 3.12, uv, pytest, DuckDB 1.x, PowerShell primary).

### Prior Phase Decisions Feeding Phase 8
- `.planning/phases/05-risk-manager-full-audit-controls/05-CONTEXT.md` — D-09 (audit_log schema: event_id, ts_utc, topic, entity_id, reason_code, payload_json; DuckDB-first + CSV mirror; synchronous writes); D-10 (engine_state DuckDB table); D-02 (account_equity = $50k static).
- `.planning/phases/03-vertical-mvp-slice-backtester/03-CONTEXT.md` — FND-08 reproducibility CI (programmatic BacktestEngine invocation, bitwise-identical Parquet test already passing).

### Existing Code — Key Files for Phase 8
- `packages/trading-core/tests/integration/test_reproducibility.py` — Existing FND-08 bitwise-identical equity-curve test. Phase 8 adds the analogous audit-log test alongside it.
- `packages/trading-core/tests/integration/test_phase5_kill9.py` — Pattern for subprocess-based integration tests with real DuckDB paths.
- `packages/trading-core/tests/fixtures/orb_day.py` (`orb_day_bars()`) — Synthetic ORB day bar fixture used by reproducibility tests. Phase 8 uses the same fixture to generate the golden audit-log CSV.
- `scripts/run_backtest.py` — CLI pattern to follow for `replay.py` (argparse, UTF-8 stdout reconfiguration, exit codes 0/1, structlog).
- `packages/trading-core/src/trading_core/storage/duckdb_store.py` — `get_bars()` method for reading bars; `write_audit_event()` for writing audit rows in replay.
- `packages/trading-core/src/trading_core/risk/full.py` — `FullRiskManager` — instantiated by `replay.py` with `config/risk.yaml`.
- `packages/trading-core/src/trading_core/execution/paper.py` — `PaperExecutor` — used in replay loop.
- `config/risk.yaml` — Loaded by `FullRiskManager` in replay.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `orb_day_bars()` fixture (`tests/fixtures/orb_day.py`): synthetic 390-bar RTH day. Phase 8 re-uses it to generate the golden audit-log CSV and drive the replay assertion test — no new fixture needed.
- `run_backtest.py` script: established pattern for CLI scripts (argparse, UTF-8 reconfigure, structured logging, exit codes). `replay.py` follows the same skeleton.
- `test_reproducibility.py`: pattern for the replay test — same `tmp_path`, same assertion style.
- `DuckDBStore.write_audit_event()` (Phase 5): already exists. Replay drives through the same write path.

### Established Patterns
- **UTF-8 stdout reconfiguration at top of every CLI script** — already in `run_backtest.py`. `replay.py` must do the same (copy the `sys.stdout = io.TextIOWrapper(...)` block).
- **`pytest --import-mode=importlib`**, no `tests/__init__.py` — all new test files follow this.
- **Argparse choices= for symbol/tf** — security pattern from `run_backtest.py` T-03-03-01.
- **Decimal-only arithmetic** in risk paths — must be preserved in replay.

### Integration Points
- `replay.py` → `DuckDBStore.get_bars()` → `ORBStrategy.on_bar()` → `FullRiskManager.check()` → `PaperExecutor.fill()` → `DuckDBStore.write_audit_event()` → output CSV
- `.github/workflows/ci.yml` → `astral-sh/setup-uv` (official uv GitHub Action) → `uv sync` → `uv run pytest`
- `backup.ps1` → copies `data/duckdb/trading.duckdb` + `data/logs/audit/{date}.csv` → `data/backups/{date}/`

</code_context>

<specifics>
## Specific Ideas

- **Golden generation command:** `uv run pytest packages/trading-core/tests/integration/test_replay_audit_log.py --update-golden` — a pytest flag that writes `tests/fixtures/golden_audit/2024-06-12.csv` instead of asserting against it. Controlled by a `--update-golden` custom CLI option registered in `conftest.py`.
- **CI checkout path:** `.github/workflows/ci.yml` uses `actions/checkout@v4` with `path: 'Day Trading'` so the working directory is `$env:GITHUB_WORKSPACE\Day Trading` — matching the local `C:\Users\Admin\Desktop\Day Trading` shape.
- **`backup.ps1` retention cleanup:** `Get-ChildItem data\backups -Directory | Where-Object { $_.CreationTime -lt (Get-Date).AddDays(-90) } | Remove-Item -Recurse -Force`
- **`backup.md` location:** `docs/operations/backup.md` — create the `docs/operations/` directory as part of this phase.

</specifics>

<deferred>
## Deferred Ideas

- None — discussion stayed within phase scope.

</deferred>

---

*Phase: 08-operational-hardening-reproducibility-ci*
*Context gathered: 2026-05-20*
