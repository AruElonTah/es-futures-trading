---
phase: 01-foundation-data-in
verified: 2026-05-15T00:00:00Z
status: gaps_found
score: 14/19 must-haves verified
overrides_applied: 0
re_verification:
  previous_status: none
  previous_score: n/a
  gaps_closed: []
  gaps_remaining: []
  regressions: []
gaps:
  - truth: "Every row in `bars` is tz-aware UTC (Success Criterion #2, FND-05, MD-06)"
    status: partial
    reason: "CR-04: `scripts/seed_bars.py:_set_ts_index` (lines 103-116) calls `pd.to_datetime(out['ts_utc'], utc=True)` which **silently localizes** a tz-naive column to UTC rather than rejecting it. A future adapter regression that emits naive timestamps would be re-labeled as UTC with no error. The Bar model boundary defends against this in tests, but the seed_bars CLI pipeline does not construct Bar objects between fetch_bars and DuckDB upsert — the column simply flows through DataFrame transforms. Net effect: the load-bearing 'tz-aware UTC everywhere' invariant is best-effort, not enforced, at the production ingest path."
    artifacts:
      - path: "scripts/seed_bars.py"
        issue: "_set_ts_index silently localizes naive→UTC instead of raising ValueError"
    missing:
      - "Add explicit precondition check: `if ts.dt.tz is None: raise ValueError('ts_utc column is naive; adapter must return tz-aware UTC')` BEFORE the to_datetime call"
      - "Reject DataFrames with no `ts_utc` column AND non-tz-aware index"

  - truth: "Idempotent re-run produces zero new bar rows AND identical data_hash (Success Criterion #2, FND-08)"
    status: partial
    reason: "CR-01: `runs.data_hash()` (storage/runs.py:102-131) projects columns and emits pyarrow Parquet bytes WITHOUT asserting column dtypes. Multiple upstream paths can produce different dtypes for the same logical data: TwelveDataSource emits `volume` via `int()` (Python int), TradingViewDataSource may emit `int` or `float`, `_set_ts_index`'s `pd.to_datetime(..., utc=True)` can produce `datetime64[ns, UTC]` OR `datetime64[us, UTC]` depending on the source, and `rollover_seam` is built from a Python `list[bool]` (object dtype, not bool — see WR-05). Any one of these drifting across a pandas/pyarrow patch upgrade produces a different hash for byte-identical bar content — exactly the failure mode the Phase 3 reproducibility CI gate is supposed to catch, but instead the gate would flap on routine patch upgrades. The integration test in test_seed_bars_e2e.py asserts equality within a single Python invocation (where dtypes are necessarily consistent) — it does NOT lock the cross-version stability that 'trust the numbers' requires."
    artifacts:
      - path: "packages/trading-core/src/trading_core/storage/runs.py"
        issue: "data_hash does not lock column dtypes before pyarrow serialization"
      - path: "packages/trading-core/src/trading_core/calendars/rth.py"
        issue: "RolloverDetector.annotate produces object-dtype rollover_seam column (WR-05)"
    missing:
      - "Inside data_hash: `projected = projected.astype({'symbol':'string','timeframe':'string','open':'float64','high':'float64','low':'float64','close':'float64','volume':'int64','rollover_seam':'bool','provider':'string'})`"
      - "Force `projected['ts_utc'] = pd.to_datetime(projected['ts_utc'], utc=True).astype('datetime64[ns, UTC]')`"
      - "Add unit test: build the same logical bar via two different code paths (different source dtypes) and assert data_hash matches"
      - "Fix RolloverDetector.annotate to emit `pd.Series(..., dtype='bool')`"

  - truth: "Bar OHLC arithmetic is exact (Decimal end-to-end), as documented in instruments.py rationale and MD-06"
    status: failed
    reason: "CR-03: The Bar Pydantic model declares `open/high/low/close: Decimal` but the entire pipeline coerces to float at every persistence boundary. TwelveDataSource emits `float(v['open'])`; TradingViewDataSource emits `float(b['open'])`; schema.sql declares `DOUBLE`; DuckDBStore.upsert_bars calls `float(d['open'])` on every row. The `instruments.py` docstring (lines 7-10) explicitly states 'Decimal — not float — because ATR-based position sizing depends on exact arithmetic. Float drift produces 1-tick miscounts at boundaries; over a 252-day backtest those miscounts compound into multi-thousand-dollar reproducibility gaps.' This rationale is silently inverted at every boundary. The Bar model is decorative; a Phase 5 risk-math author reading data/models.py will assume Decimal-exact prices when float drift has already occurred. This directly undermines the project's stated 'trust the numbers' core value."
    artifacts:
      - path: "packages/trading-core/src/trading_core/data/models.py"
        issue: "Bar declares Decimal but pipeline ignores it"
      - path: "packages/trading-core/src/trading_core/data/twelvedata.py"
        issue: "Coerces OHLC to float in fetch_bars"
      - path: "packages/trading-core/src/trading_core/data/tradingview.py"
        issue: "Coerces OHLC to float in fetch_bars"
      - path: "packages/trading-core/src/trading_core/storage/schema.sql"
        issue: "OHLC columns declared as DOUBLE"
      - path: "packages/trading-core/src/trading_core/storage/duckdb_store.py"
        issue: "upsert_bars float-casts every row"
    missing:
      - "Pick an authoritative representation: either honor Decimal end-to-end (adapters read v['open'] as Decimal(v['open']); schema → DECIMAL(18,8); drop the float() casts) OR drop the Decimal declaration from Bar and update instruments.py rationale to scope Decimal to pricing-metadata only (tick_value/tick_size/point_value)"
      - "Document the decision in an ADR under .planning/decisions/"

  - truth: "Same-day RTH range query returns half-open [start, end) shape (load-bearing for any caller of trading_days/expected_rth_timestamps/RthFilter.find_gaps)"
    status: failed
    reason: "CR-02: `calendars/rth.py:trading_days` (lines 54-79) has a special-case-on-same-day that contradicts the documented half-open semantics. When `start == end`, it returns the full single day inclusively; when `end > start`, it correctly carves off `end_d - 1 day`. The docstring acknowledges this dual contract intentionally — but it leaks out: `expected_rth_timestamps(symbol, tf, start=X, end=X)` returns all 390 1m bars for X (should be 0 under half-open); `RthFilter.find_gaps(start=X, end=X)` reports the entire RTH session as missing; `seed_bars.py --from 2024-01-02 --to 2024-01-02` would attempt to load the entire 2024-01-02 RTH window (which the half-open contract says should be empty). This is the canonical 'off-by-one in the load-bearing session filter' the project's stated core value cannot survive. WR-04 also depends on this fix."
    artifacts:
      - path: "packages/trading-core/src/trading_core/calendars/rth.py"
        issue: "trading_days() dual semantics: half-open when end>start, inclusive when start==end; leaks into expected_rth_timestamps and find_gaps"
    missing:
      - "Make trading_days() honestly half-open everywhere (return empty DatetimeIndex when end<=start)"
      - "Add a private _is_trading_day(calendar, date) helper for is_rth's 'is today a trading day?' query so it doesn't depend on the special case"
      - "Add a test: expected_rth_timestamps('SPY','1m', date(2024,6,12), date(2024,6,12)) returns 0 timestamps (currently returns 390)"

  - truth: "Rollover-seam flag is correct for SPY (SPY is an NYSE ETF that does NOT roll; MD-08 specifies 3rd-Friday-of-Mar/Jun/Sep/Dec which is a CME futures convention)"
    status: failed
    reason: "WR-06: `is_rollover_seam` and `RolloverDetector.annotate` are called UNCONDITIONALLY on every adapter output, with no per-symbol gate. SPY bars flowing through seed_bars get a phantom `rollover_seam=True` annotation around every 3rd Friday of Mar/Jun/Sep/Dec, even though SPY does not roll. Success Criterion #2 states the `rollover_seam` column should be True on quarterly boundary bars — but ROADMAP/REQ-IDs (MD-08) describe this as a continuous-contract rollover detector, not a calendar-date marker. Any downstream filter that skips seams will silently drop SPY bars on those days, corrupting backtests on the SPY-proxy ingest path — which is the entire Phase 1 demo path. This is exactly the kind of quiet correctness bug 'trust the numbers' is designed to prevent."
    artifacts:
      - path: "packages/trading-core/src/trading_core/calendars/rth.py"
        issue: "RolloverDetector.annotate has no symbol gate; applies to SPY"
      - path: "scripts/seed_bars.py"
        issue: "Calls rollover.annotate(df) unconditionally with no --symbol consultation"
    missing:
      - "Add symbol/asset_class gate to RolloverDetector.annotate: future → run the detector; etf/stock → set rollover_seam=False for every row"
      - "Plumb args.symbol through annotate() in seed_bars.py"
      - "Add a test: SPY bars on 2026-03-20 (3rd Fri of Mar) get rollover_seam=False; ES bars on the same day get rollover_seam=True"

deferred: []

human_verification:
  - test: "Visually load the Next.js placeholder page in a browser"
    expected: "`apps/web/app/page.tsx` renders the headline 'ES Futures Trading System' with the dark monospace theme + Tailwind v3 styling. Operator confirms the page renders, the Tailwind classes apply (black background, gray-200 text, font-mono), and no console errors."
    why_human: "pnpm build exit-0 + tsc exit-0 + grep matches prove the build succeeds and emits the literal text, but visual rendering with Tailwind classes applied at runtime requires a browser session — the test suite has no Playwright integration in Phase 1."
  - test: "Run the seed_bars CLI against the live Twelve Data API for SPY 1m for a 1-day window with a real TWELVEDATA_API_KEY"
    expected: "`runs.status='ok'`, `SELECT COUNT(*) FROM bars` = 390 (or close, accounting for any real provider gaps), `bar_gaps` populated if gaps exist, no API key value appearing in `data/logs/audit/<date>.jsonl`. Re-run should produce 0 new bar rows. This is the actual MD-09 + #2 acceptance — the test suite only covers respx-mocked invocations."
    why_human: "Test suite runs against respx mocks (no live network, no real API key). The live happy-path was deliberately deferred — but until an operator runs it once, the project has not proven the adapter end-to-end against the real provider response shape, rate-limit headers, or pacing behavior."
  - test: "Run the seed_bars CLI against the real TradingView MCP server for ES 1m for a 1-day window with TradingView Desktop running"
    expected: "Bars written to DuckDB, no DegradedStateEvent published on the bus during a healthy run. Killing TV Desktop mid-run produces a DegradedStateEvent and a status='failed' runs row."
    why_human: "Test suite mocks the MCP ClientSession + stdio_client. Live verification requires TradingView Desktop running on the operator's machine with the MCP server up — the test suite cannot exercise this path. Phase 6 will own the full TVBridge supervisor, but Phase 1's TradingViewDataSource adapter has not been exercised against the real CDP/MCP stack since the Phase 0 spike."
  - test: "Run `uv run pre-commit run --all-files` against a clean clone after a fresh `pre-commit install`"
    expected: "Both hooks (gitleaks + no-naive-tz) install correctly via corepack/uv, run against the current tree, and exit 0. No path-with-space surprises."
    why_human: "Reproducing the smoke from a clean clone (not the dev machine where the gitleaks binary is already cached) is the only way to confirm pre-commit's binary fetch works under operator constraints. SUMMARY claims this is green but the gitleaks-binary test in the suite is conditionally skipped when the cache is empty (per Plan 05 SUMMARY 'Captured stdout' section)."
---

# Phase 1: Foundation + Data In — Verification Report

**Phase Goal:** A scaffolded monorepo with repo-wide UTC/RTH discipline can backfill RTH-only ES/SPY bars from the configured `DataSource` into DuckDB + Parquet with idempotent upserts, gap detection, and rollover-seam flags.

**Verified:** 2026-05-15T00:00:00Z
**Status:** gaps_found
**Re-verification:** No — initial verification
**Score:** 14/19 must-haves verified
**Live test run:** `uv run pytest -q` → 195 passed, 1 skipped (63s wall-clock)

## Executive Summary

Phase 1 ships impressive *breadth*: every plan completed, every REQ-ID has an implementing module, the test suite is green, the FastAPI shell is live, the Next.js stub builds, pre-commit hooks are installed. The acceptance smoke does pass.

But the **goal** — "trust the numbers" — has five correctness gaps that all four 01-REVIEW BLOCKER findings independently surface:

1. The "every row is tz-aware UTC" success criterion is *best-effort* in the CLI pipeline, not load-bearing (CR-04 silent naive→UTC localization in `_set_ts_index`).
2. The "idempotent re-run produces zero new rows AND identical data_hash" success criterion is locked only within a single Python invocation — across pandas/pyarrow patch upgrades, the hash will drift on byte-identical bar content (CR-01 + WR-05 unguarded dtypes).
3. The `instruments.py` Decimal rationale is silently inverted at every persistence boundary (CR-03 Bar model decorative).
4. The session filter has a dual contract (half-open in general, inclusive on same-day) that leaks into every caller (CR-02).
5. SPY bars get phantom `rollover_seam=True` flags around CME futures roll dates (WR-06; corrupts the demo ingest path).

None of these crash the suite. All five are silent backtest-corrupters in the exact way Phase 1 exists to prevent. The four CR-* items in 01-REVIEW.md are not orthogonal review findings — they each erode one of the four ROADMAP success criteria, and they should be treated as verification gaps, not just code-review nits.

## Goal Achievement

### Observable Truths (vs. ROADMAP Phase 1 Success Criteria + PLAN must_haves)

| #   | Truth                                                                                                                                                                                  | Status         | Evidence                                                                                                                                                                                                                                                                                       |
| --- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | `uv sync` from a clean clone produces working `.venv` with locked tech-stack versions (Success #1)                                                                                     | ✓ VERIFIED     | `uv run pytest -q` → 195 passed; `uv.lock` contains all 11 FND-02 pins (vectorbt 1.0.0, pandas 2.3.3, pydantic 2.13.4, fastapi 0.136.1, duckdb 1.5.2, structlog 25.5.0, httpx 0.27.2, pyarrow 17.x, pytest 8.4.2, hypothesis 6.152.7, respx 0.23.1, freezegun 1.5.5) per Plan 01-01 SUMMARY     |
| 2   | All 3 Python packages + apps/web are importable workspace members (Success #1)                                                                                                          | ✓ VERIFIED     | `uv run python -c "import trading_core, api, tv_bridge; print('imports ok')"` → prints "imports ok"; `pnpm --filter web build` exits 0 (19s); `from api.app import app` resolves                                                                                                              |
| 3   | seed_bars CLI produces `bars` table with all rows tz-aware UTC (Success #2)                                                                                                            | ✗ FAILED       | **CR-04** — `scripts/seed_bars.py:_set_ts_index` silently localizes naive→UTC via `pd.to_datetime(..., utc=True)` instead of raising. The Bar model defends at the field-validator boundary in tests, but the CLI does NOT construct Bar objects between adapter and upsert. See gaps section. |
| 4   | seed_bars produces NO ETH bars; CME half-days honored (Success #2)                                                                                                                     | ✓ VERIFIED     | `calendars/rth.py:rth_window_utc` honors `market_close` from `pandas_market_calendars`; Plan 03 SUMMARY confirms Black Friday 2024-11-29 produces 210 bars not 390; ETH-only DataFrame returns empty under `RthFilter().filter()` per test_rth_filter.py::test_strips_eth_bars                |
| 5   | Idempotent re-run produces zero new bar rows (Success #2)                                                                                                                              | ✓ VERIFIED     | `DuckDBStore.upsert_bars` uses explicit `ON CONFLICT (symbol, timeframe, ts_utc) DO UPDATE SET col = EXCLUDED.col`; `test_seed_bars_e2e.py::test_rerun_zero_new_bars_same_data_hash` asserts the COUNT remains 390 across two invocations                                                       |
| 6   | Idempotent re-run produces identical `data_hash` (Success #2 + FND-08)                                                                                                                | ✗ FAILED       | **CR-01 + WR-05** — `data_hash()` does not lock dtypes before pyarrow serialization. The intra-process re-run test passes (dtypes consistent within a single Python run), but the cross-version stability needed for Phase 3 reproducibility CI is not enforced. See gaps section.            |
| 7   | `bar_gaps` table populated for any missing intra-RTH bars (Success #2 + MD-07)                                                                                                          | ✓ VERIFIED     | `RthFilter.find_gaps_as_dataframe` produces `[symbol, timeframe, ts_utc]` shape; `DuckDBStore.upsert_gaps` writes to `bar_gaps`; `test_seed_bars_e2e.py::test_partial_with_gaps_exits_2` asserts 5 dropped bars produce 5 gap rows and exit code 2                                              |
| 8   | `rollover_seam` is True on 3rd-Friday-of-Mar/Jun/Sep/Dec boundary bars (Success #2 + MD-08)                                                                                            | ⚠️ PARTIAL     | `is_rollover_seam` correctly flags 3rd Fridays; but **WR-06** — flag is unconditionally applied to SPY (an NYSE ETF that does not roll). Phase 1 demo ingest path (SPY 1m) gets phantom seam annotations. Phase 2's ORB strategy skip-on-seam logic would silently drop SPY bars on those days. |
| 9   | `pytest` runs cleanly on DST-transition cases 2026-03-08 and 2026-11-01 (Success #3)                                                                                                   | ✓ VERIFIED     | Plan 03 deviated from the plan-asserted 2026-11-01 trading day (correctly identified as a Sunday) to 2026-11-02; both DST fixtures (`dst_spring_forward_2026_03_09`, `dst_fall_back_2026_11_02`) green in test_rth_filter.py; DST UTC-offset table in Plan 03 SUMMARY verifies the math.        |
| 10  | Pre-commit rejects naive `datetime.now()` (Success #3 + FND-05)                                                                                                                       | ✓ VERIFIED     | `scripts/hooks/no_naive_tz.py packages/trading-core/tests/fixtures/bad_naive_datetime.py` exits 1 (verified live during verification: lines 16 + 20 flagged); AST-based per Pitfall 8; not regex                                                                                                |
| 11  | Pre-commit rejects fake API key via gitleaks (Success #3 + FND-04)                                                                                                                    | ✓ VERIFIED     | `.gitleaks.toml` allowlists the `<TWELVEDATA_API_KEY>` sentinel; `.pre-commit-config.yaml` pins gitleaks v8.24.2; `bad_api_key.py` fixture is path-allowlisted so working-tree scans stay clean while the rule still rejects on direct `gitleaks detect --no-git --source <path>` invocation     |
| 12  | Every CLI run inserts a runs row with `git_sha`, `data_hash`, `param_hash`, `seed`, and ADR hash (Success #4 + FND-08)                                                                | ✓ VERIFIED     | `scripts/seed_bars.py` finally-block (lines 237-263) writes the 10-field row on every code path including adapter failure; `storage/runs.py` ships all five helpers; ADR hash recomputed from `.planning/decisions/0001-data-provider.md` bytes                                                |
| 13  | `instruments.py` is the only file with hardcoded tick_value / point_value / session_times (Success #4 + FND-06)                                                                       | ✓ VERIFIED     | `instruments.py` ships Decimal-typed registry; `calendars/rth.py` reads `inst.rth_open_et` / `inst.rth_close_et` / `inst.calendar_name` — no duplicated session times anywhere; verified live: `get('ES').tick_value == Decimal('12.50')`, `get('MES').tick_value == Decimal('1.25')`, etc.    |
| 14  | But the Decimal rationale for OHLC arithmetic is enforced end-to-end (FND-06 + instruments.py docstring lines 7-10 explicit rationale)                                                | ✗ FAILED       | **CR-03** — Bar model declares `Decimal` for OHLC but every persistence boundary (TwelveDataSource line 227-230, TradingViewDataSource line 311-314, schema.sql `DOUBLE`, upsert_bars `float(d['open'])`) coerces to float. The rationale is silently inverted. See gaps section.              |
| 15  | All 4 Protocol seams defined (FND-07 + MD-01)                                                                                                                                          | ✓ VERIFIED     | DataSource, Strategy, RiskManager, Executor all in their respective protocols.py files; no `@runtime_checkable` decorator; Plan 04's `uv run mypy --strict` exits clean for both live adapters against DataSource                                                                                |
| 16  | EventBus FIFO per topic + asyncio in-process pub/sub (FND-07)                                                                                                                          | ✓ VERIFIED     | `events/bus.py` ships `EventBus` + `Subscription`; 11 test_event_bus tests green covering single-publish single-subscriber, two-subscribers FIFO, different-topic isolation, late-subscriber no-replay                                                                                          |
| 17  | Same-day RTH range query honors half-open `[start, end)` semantics (consistent contract across helpers + RthFilter + seed_bars)                                                       | ✗ FAILED       | **CR-02** — `trading_days()` has a dual contract: half-open when `end > start`, inclusive when `start == end`. `expected_rth_timestamps('SPY','1m', X, X)` returns 390 bars (should be 0 under half-open); `RthFilter.find_gaps` and `seed_bars --from X --to X` inherit the leak. See gaps.    |
| 18  | FastAPI shell exposes `/health` and proves the trading-core import graph (FND-01)                                                                                                     | ✓ VERIFIED     | `packages/api/src/api/app.py` defines `app = FastAPI(...)` + single `@app.get('/health')`; module-level `from trading_core.config import Settings` + `_settings = Settings()`; verified live: `[r.path for r in app.routes]` = `['/openapi.json', '/docs', '/docs/oauth2-redirect', '/redoc', '/health']` |
| 19  | structlog JSON logging with correlation IDs (FND-09)                                                                                                                                   | ✓ VERIFIED     | `trading_core/logging.py` ships `setup_logging` with `correlation_id` + `signal_id` contextvars + JSONRenderer + ConcurrentRotatingFileHandler + Windows UTF-8 reconfigure; 6 test_logging tests green                                                                                          |

**Score:** 14/19 truths VERIFIED + 1 PARTIAL + 4 FAILED. Status: `gaps_found`.

### Required Artifacts

All artifacts exist on disk and are non-stub. The failures above are about **correctness behavior**, not about artifact existence.

| Artifact                                                                                  | Expected                                                  | Status     | Details                                                                                                |
| ----------------------------------------------------------------------------------------- | --------------------------------------------------------- | ---------- | ------------------------------------------------------------------------------------------------------ |
| `pyproject.toml` + `uv.lock`                                                              | uv workspace + FND-02 pins                                | ✓ VERIFIED | All 11 pins present; workspace members editable                                                        |
| `packages/trading-core/src/trading_core/instruments.py`                                   | SoT registry (FND-06)                                     | ✓ VERIFIED | ES/MES/SPY frozen Pydantic; 14 Decimal occurrences                                                     |
| `packages/trading-core/src/trading_core/data/models.py`                                   | Bar with AwareDatetime + utc validator                    | ⚠️ DECORATIVE | Decimal type is decorative (CR-03); UTC validator does work but pipeline doesn't construct Bar objects |
| `packages/trading-core/src/trading_core/data/protocols.py`                                | DataSource Protocol (MD-01)                               | ✓ VERIFIED | mypy --strict clean against both live adapters                                                         |
| `packages/trading-core/src/trading_core/calendars/rth.py`                                 | RthFilter + Rollover + Gap (MD-05/07/08)                  | ⚠️ PARTIAL | Functional but CR-02 + WR-05 + WR-06 correctness issues                                                |
| `packages/trading-core/src/trading_core/events/bus.py`                                    | EventBus (FND-07)                                         | ✓ VERIFIED | FIFO per topic; 11 tests green                                                                         |
| `packages/trading-core/src/trading_core/storage/schema.sql`                               | DDL with composite PK (MD-04)                             | ✓ VERIFIED | `PRIMARY KEY (symbol, timeframe, ts_utc)`; OHLC declared as DOUBLE (relates to CR-03)                  |
| `packages/trading-core/src/trading_core/storage/duckdb_store.py`                          | ON CONFLICT upserts (MD-04)                               | ✓ VERIFIED | Explicit `ON CONFLICT ... DO UPDATE SET col = EXCLUDED.col`; Hive Parquet partitioning                 |
| `packages/trading-core/src/trading_core/storage/runs.py`                                  | uuid7 + git_sha + adr_hash + param_hash + data_hash       | ⚠️ PARTIAL | All five helpers present; data_hash byte-stability not enforced via dtype assertions (CR-01)            |
| `packages/trading-core/src/trading_core/data/twelvedata.py`                               | Httpx adapter; redaction; rate-limit headers (MD-03)      | ✓ VERIFIED | Lazy api-key read; `_redact_url` substitutes apikey; raises RateLimited/DataSourceUnavailable          |
| `packages/trading-core/src/trading_core/data/tradingview.py`                              | mcp.ClientSession adapter (MD-02)                         | ✓ VERIFIED | tv_health_check gate; DegradedStateEvent on disconnect; per-call session                               |
| `packages/trading-core/src/trading_core/config.py`                                        | Pydantic Settings (FND-03)                                | ✓ VERIFIED | env > .env > yaml > defaults precedence; SecretStr-redacted twelvedata_api_key                          |
| `packages/trading-core/src/trading_core/logging.py`                                       | structlog + correlation_id (FND-09)                       | ✓ VERIFIED | Windows-safe UTF-8 reconfigure; ConcurrentRotatingFileHandler; contextvars                              |
| `scripts/seed_bars.py`                                                                    | Composed CLI (MD-09)                                      | ⚠️ PARTIAL | Pipeline composes correctly; CR-04 silent naive→UTC localization + rollover-on-SPY are gaps            |
| `scripts/hooks/no_naive_tz.py`                                                            | AST-based hook (FND-05)                                   | ✓ VERIFIED | AST walk for `<bare-name datetime>.now()` / `.utcnow()`; ignores comments + docstrings                  |
| `.pre-commit-config.yaml` + `.gitleaks.toml`                                              | gitleaks + no-naive-tz wiring (FND-04 + FND-05)           | ✓ VERIFIED | gitleaks v8.24.2 pinned; allowlist for `<TWELVEDATA_API_KEY>` + bad_api_key.py path                     |
| `packages/api/src/api/app.py` + `apps/web/app/page.tsx`                                   | FastAPI shell + Next.js stub                              | ✓ VERIFIED | Only `/health` exposed (T-01-06-01); page renders headline + Phase 1 placeholder text                   |
| `.planning/decisions/0001-data-provider.md`                                               | ADR for FND-10 (Phase 0 deliverable, consumed by Phase 1) | ✓ VERIFIED | adr_hash() round-trips; locked in storage/runs.py ADR_PATH                                              |

### Key Link Verification

| From                          | To                                                       | Via                                                                | Status         | Details                                                                                                                                       |
| ----------------------------- | -------------------------------------------------------- | ------------------------------------------------------------------ | -------------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| `scripts/seed_bars.py`        | `trading_core.storage.duckdb_store.DuckDBStore`          | composes the upsert+gap+rollover+runs pipeline                     | ✓ WIRED        | imports + usage verified                                                                                                                      |
| `scripts/seed_bars.py`        | `trading_core.data.twelvedata.TwelveDataSource`          | PROVIDERS registry maps `--provider` to adapter class              | ✓ WIRED        | `_construct_source` constructs TwelveDataSource on twelvedata; TradingViewDataSource on tradingview                                            |
| `scripts/seed_bars.py`        | naive datetime detection at the ingest boundary           | `_set_ts_index` should raise on naive ts_utc                       | ✗ NOT WIRED    | **CR-04** silently localizes instead of raising; the wiring is present but wrong-direction (loosens UTC discipline rather than enforcing it)  |
| `scripts/seed_bars.py`        | `RolloverDetector.annotate(df, symbol=...)`              | seed_bars should pass `args.symbol` so detector can gate on asset_class | ✗ NOT WIRED    | **WR-06** — annotate() takes no symbol arg; called unconditionally; SPY gets phantom seams                                                    |
| `storage/runs.py:data_hash`   | dtype-stable serialization                                | explicit `astype` cast before pyarrow Parquet write                | ✗ NOT WIRED    | **CR-01** — pyarrow flags are correct but dtypes are not asserted; hash drifts on patch upgrades                                              |
| `.pre-commit-config.yaml`     | `scripts/hooks/no_naive_tz.py`                           | local hook entry calls the AST scanner                             | ✓ WIRED        | verified: hook invocation exits 1 against the bad fixture                                                                                     |
| `.pre-commit-config.yaml`     | `.gitleaks.toml`                                         | gitleaks hook reads custom config + allowlist                      | ✓ WIRED        | verified: `pre-commit run --all-files` exits 0                                                                                                |
| `packages/api/src/api/app.py` | `trading_core.config.Settings`                           | proves api → trading-core import graph                             | ✓ WIRED        | `from trading_core.config import Settings; _settings = Settings()` at module top                                                              |
| `Bar.open: Decimal`           | persistence layer Decimal preservation                   | adapters should emit Decimal; schema should be DECIMAL              | ✗ NOT WIRED    | **CR-03** — adapters float() everything; schema is DOUBLE; the Decimal type is decorative                                                     |
| `trading_days(X, X)`          | half-open contract (returns empty for same-day)          | consistent semantics across helpers + RthFilter                    | ✗ NOT WIRED    | **CR-02** — dual contract leaks into every caller                                                                                              |

### Data-Flow Trace (Level 4)

| Artifact                                  | Data Variable           | Source                                                          | Produces Real Data | Status     |
| ----------------------------------------- | ----------------------- | --------------------------------------------------------------- | ------------------ | ---------- |
| `seed_bars.py` (CLI)                      | `df` (bars DataFrame)   | TwelveDataSource.fetch_bars (respx-mocked in tests; live API)   | Yes (in test)      | ✓ FLOWING  |
| `apps/web/app/page.tsx`                   | (static placeholder)    | none (server component, no data fetch)                          | N/A — placeholder  | ✓ FLOWING  |
| `packages/api/src/api/app.py` `/health`   | dict literal            | hardcoded (intentional per Phase 1 contract; Phase 3 expands)    | Yes (static)       | ✓ FLOWING  |
| `runs.data_hash`                          | bytes for sha256        | pyarrow Parquet of projected df                                 | Yes but fragile    | ⚠️ STATIC dtype (see CR-01) |
| `RolloverDetector.annotate`               | `rollover_seam` column  | `is_rollover_seam(ts)` applied to every row                     | Yes, but for SPY this is phantom data | ⚠️ HOLLOW (WR-06)        |

### Behavioral Spot-Checks

| Behavior                                                                                                      | Command                                                                                                  | Result                                  | Status  |
| ------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------- | --------------------------------------- | ------- |
| Full test suite passes                                                                                        | `uv run pytest -q --tb=no`                                                                               | `195 passed, 1 skipped in 63.41s`       | ✓ PASS  |
| Workspace members importable                                                                                  | `uv run python -c "import trading_core, api, tv_bridge"`                                                 | `imports ok`                            | ✓ PASS  |
| instruments.py values exact                                                                                   | `uv run python -c "from trading_core.instruments import get; print(get('ES').tick_value, ...)"`          | `ES tick= 12.50 MES tick= 1.25 SPY tick= 0.01` | ✓ PASS  |
| FastAPI app instance + only /health route registered                                                          | `uv run python -c "from api.app import app; print(type(app).__name__, [r.path for r in app.routes if hasattr(r,'path')])"` | `FastAPI ['/openapi.json', '/docs', '/docs/oauth2-redirect', '/redoc', '/health']` | ✓ PASS  |
| AST naive-tz hook rejects bad fixture                                                                         | `python scripts/hooks/no_naive_tz.py packages/trading-core/tests/fixtures/bad_naive_datetime.py; echo $?` | exit 1; 2 violations on lines 16 + 20   | ✓ PASS  |
| seed_bars.py live network smoke (real Twelve Data API)                                                        | n/a — needs operator-provided TWELVEDATA_API_KEY and a network                                            | n/a                                     | ? SKIP (routed to human)  |
| seed_bars.py against real TradingView MCP                                                                     | n/a — needs TV Desktop running + MCP server                                                              | n/a                                     | ? SKIP (routed to human)  |

### Probe Execution

No project probes (`scripts/*/tests/probe-*.sh`) declared in the PLANs or referenced in SUMMARYs. Behavioral spot-checks (above) and `uv run pytest -q` substitute for probe execution in this Python project. Test-suite results captured in §Behavioral Spot-Checks.

### Requirements Coverage

| Requirement | Source Plan | Description                                                          | Status     | Evidence                                                                                                |
| ----------- | ----------- | -------------------------------------------------------------------- | ---------- | ------------------------------------------------------------------------------------------------------- |
| FND-01      | 01-01, 01-06 | uv workspace + 3 Python packages + apps/web importable               | ✓ SATISFIED | Plan 01-01 scaffolds; Plan 01-06 FastAPI shell proves the import graph; tests green                     |
| FND-02      | 01-01       | `uv.lock` pins of FND-02-mandated versions                            | ✓ SATISFIED | All 11 pins resolved in `uv.lock`; Plan 01-01 SUMMARY documents the resolved versions                   |
| FND-03      | 01-02       | Pydantic Settings + `.env` + `.env.example` + `config/*.yaml` merge   | ✓ SATISFIED | `Settings` ships with native `YamlConfigSettingsSource`; 8 test_config tests green                       |
| FND-04      | 01-05       | gitleaks pre-commit hook                                              | ✓ SATISFIED | gitleaks v8.24.2 wired; `.gitleaks.toml` allowlist; `pre-commit run --all-files` exits 0                |
| FND-05      | 01-05       | UTC discipline + AST naive-datetime hook                              | ⚠️ PARTIAL  | AST hook in place; **BUT** CR-04 — seed_bars CLI silently re-labels naive→UTC instead of rejecting, undermining the "UTC discipline" invariant the hook is meant to enforce in concert with code-level guards |
| FND-06      | 01-02       | `instruments.py` SoT with tick_value/point_value/tick_size            | ⚠️ PARTIAL  | Registry exists with Decimal pricing **BUT** CR-03 — the documented Decimal rationale is inverted everywhere prices flow through the pipeline; instruments.py docstring is misleading |
| FND-07      | 01-03       | EventBus (asyncio in-process pub/sub) typed topics                    | ✓ SATISFIED | EventBus + Subscription + 7 topic constants; 11 tests                                                    |
| FND-08      | 01-04       | `runs` table with git_sha/data_hash/param_hash/seed/adr_hash          | ⚠️ PARTIAL  | All five helpers exist; runs row written on every CLI exit **BUT** CR-01 — data_hash byte-stability not enforced across pandas/pyarrow patch versions; Phase 3 reproducibility CI gate would flap |
| FND-09      | 01-02       | structlog JSON + correlation IDs                                      | ✓ SATISFIED | logging.py wires setup_logging; 6 tests green                                                            |
| MD-01       | 01-02, 01-04 | `DataSource` Protocol                                                | ✓ SATISFIED | Protocol defined; both adapters mypy --strict clean                                                      |
| MD-02       | 01-04       | `TradingViewDataSource` via MCP                                       | ✓ SATISFIED | mcp.ClientSession + stdio_client; tv_health_check gate; DegradedStateEvent on disconnect                 |
| MD-03       | 01-04       | `TwelveDataSource` (httpx + rate-limit headers + redaction)           | ✓ SATISFIED | Raw httpx (Pitfall 6 — no SDK); `_redact_url` with `<TWELVEDATA_API_KEY>` sentinel                       |
| MD-04       | 01-04       | DuckDB + Hive Parquet idempotent upsert; single-writer                | ✓ SATISFIED | Explicit ON CONFLICT (Pitfall 2); Hive partitioning via projected year/month columns; idempotency test  |
| MD-05       | 01-03       | CME equity-index calendar RTH filter                                  | ⚠️ PARTIAL  | Hybrid CME_Equity / NYSE filter works **BUT** CR-02 — half-open contract has a same-day inclusive special case that leaks into every caller |
| MD-06       | 01-02       | Bar timestamps documented as open-time                                | ✓ SATISFIED | Bar model docstring lines 1-7 documents OPEN-time convention; test asserts docstring contains the text  |
| MD-07       | 01-03, 01-04 | Bar-gap detector + `bar_gaps` table                                  | ✓ SATISFIED | `find_gaps_as_dataframe` + `DuckDBStore.upsert_gaps`; integration test asserts 5 dropped bars → 5 gap rows |
| MD-08       | 01-03       | Rollover-seam detector (3rd-Friday-of-Mar/Jun/Sep/Dec)                | ⚠️ PARTIAL  | Detector works for futures **BUT** WR-06 — applied unconditionally; SPY gets phantom seams              |
| MD-09       | 01-05       | `seed_bars.py` CLI                                                    | ⚠️ PARTIAL  | CLI exists and composes the pipeline; integration tests green **BUT** CR-04 + WR-06 + the Decimal/dtype trio together mean the CLI does not honor every "trust the numbers" invariant Phase 1 was meant to lock |

**Coverage:** 18/18 Phase 1 REQ-IDs addressed (MD-10 deferred to Phase 6 per ROADMAP Notes — not a gap). No orphaned requirements. 10 fully SATISFIED; 8 PARTIAL (with concrete gap citations); 0 entirely BLOCKED.

### Anti-Patterns Found

Beyond the 4 BLOCKERs already cited from 01-REVIEW.md, the following non-blocking warnings from the review are reproduced here for completeness — they were inspected during verification and the file states match:

| File                                                | Line(s)        | Pattern             | Severity   | Impact                                                                                                                                                  |
| --------------------------------------------------- | -------------- | ------------------- | ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `scripts/seed_bars.py`                              | 103-116        | Silent naive→UTC localization in `_set_ts_index` | 🛑 Blocker | CR-04 — undermines Success #2 "every row is tz-aware UTC" by silently re-labeling instead of rejecting                                                  |
| `packages/trading-core/src/trading_core/storage/runs.py` | 102-131  | Unlocked dtypes in `data_hash` before pyarrow serialize | 🛑 Blocker | CR-01 — undermines Success #2 / FND-08 reproducibility CI cross-version stability                                                                       |
| `packages/trading-core/src/trading_core/data/models.py` | 39-45 + adapters + schema | Decorative `Decimal` declaration | 🛑 Blocker | CR-03 — inverts the instruments.py documented rationale; future Phase 5 risk math will silently use floats                                              |
| `packages/trading-core/src/trading_core/calendars/rth.py` | 54-79 | `trading_days` same-day inclusive special case | 🛑 Blocker | CR-02 — leaks into every downstream caller (`expected_rth_timestamps`, `find_gaps`, `seed_bars --from X --to X`)                                       |
| `packages/trading-core/src/trading_core/calendars/rth.py` | 303-321, 324-344 | Rollover detector applied to SPY without symbol gate | ⚠️ Warning | WR-06 — phantom seam annotations on the Phase 1 demo ingest path                                                                                       |
| `packages/trading-core/src/trading_core/calendars/rth.py` | 334-344 | `RolloverDetector.annotate` emits object-dtype list | ⚠️ Warning | WR-05 — contributes to CR-01 hash fragility                                                                                                            |
| `packages/trading-core/src/trading_core/data/tradingview.py` | 138-153 | `_publish_degraded` swallows all exceptions | ⚠️ Warning | WR-01 — UI banner silently stops when bus is misconfigured                                                                                              |
| `packages/trading-core/src/trading_core/data/tradingview.py` | 321-409 | `subscribe_bars` non-cancellable sleep | ⚠️ Warning | WR-02 — graceful shutdown blocks up to 15 min on a 15m subscribe loop                                                                                  |
| `packages/trading-core/src/trading_core/events/bus.py` | 70-81 | Subscribe/unsubscribe race in `publish` | ⚠️ Warning | WR-03 — event delivered to unsubscribed queue; non-load-bearing but documented for Phase 5/7 bounded-queue refactor                                     |
| `packages/trading-core/src/trading_core/config.py` | 33-41 | `extra="ignore"` silently swallows yaml typos | ⚠️ Warning | WR-07 — operator-misconfigured provider in optimization runs corrupts the audit chain (Phase 4 risk)                                                   |
| `scripts/seed_bars.py` | (env var override doc) | DUCKDB_PATH override documented but not asserted | ⚠️ Warning | WR-08 — `case_sensitive=False` not asserted; a later config change could silently break test isolation                                                  |
| `packages/trading-core/src/trading_core/data/twelvedata.py` | 194-198 | 9s pacing AFTER request | ℹ️ Info    | IN-01 — wastes 9s on the last call of every backfill                                                                                                    |
| `scripts/seed_bars.py` | 90-100 | `_construct_source` returns `object` | ℹ️ Info    | IN-03 — defeats mypy narrowing; `# type: ignore[attr-defined]` at line 183 + line 205                                                                  |
| `packages/trading-core/src/trading_core/storage/runs.py` | 89-99 | `param_hash` `default=str` on Path | ℹ️ Info    | IN-04 — `param_hash` will diverge between Windows and Linux runs; flag for Phase 8 cross-platform CI                                                  |

**Debt markers:** zero `TBD` / `FIXME` / `XXX` found in any Phase 1 source file under `packages/trading-core/src/` or `scripts/`. The audit-trail gate is clean.

### Human Verification Required

Listed in `human_verification:` frontmatter above. Summary:

1. **Visual smoke of Next.js placeholder** — `pnpm build` and `tsc --noEmit` exit 0, but no Playwright integration in Phase 1; operator must open the page in a browser and confirm Tailwind classes apply and the page renders without console errors.
2. **Live Twelve Data smoke** — Test suite uses respx mocks; the real adapter has not been exercised against a live SPY 1m backfill since Phase 0. Run `seed_bars --symbol SPY --tf 1m --from 2024-01-02 --to 2024-01-03 --provider twelvedata` with a real TWELVEDATA_API_KEY and confirm idempotent re-run + no key value appearing in audit JSONL.
3. **Live TradingView MCP smoke** — Test suite mocks the MCP ClientSession; the real adapter has not been exercised against TV Desktop since Phase 0. Run `seed_bars --symbol ES --tf 1m --from <recent-date> --to <recent-date+1> --provider tradingview` with TV Desktop running.
4. **Clean-clone pre-commit smoke** — Reproduce `uv run pre-commit run --all-files` from a fresh clone (not the dev machine where gitleaks binary is cached) to confirm pre-commit's binary fetch works.

These four items do not block the structural verdict but are required for full Phase 1 closure-confidence given the project's "trust the numbers" stance.

### Gaps Summary (narrative)

Phase 1 ships every artifact the ROADMAP demanded and every plan's `done` criterion is satisfied at the artifact-existence level. The test suite is green (195 passed, 1 skipped). The acceptance smoke is green. The summaries are detailed and honest about their auto-fixes.

But goal-backward verification finds **five behavior gaps** that each erode one of the four ROADMAP Phase 1 success criteria:

- **CR-04** (silent naive→UTC localization) ⇒ Success Criterion #2's "every row is tz-aware UTC" is best-effort, not load-bearing.
- **CR-01 + WR-05** (data_hash dtype fragility) ⇒ Success Criterion #2's idempotency contract is intra-process only; the cross-version Phase 3 reproducibility CI gate Plan 04 explicitly anticipated would flap on pandas/pyarrow patch upgrades.
- **CR-03** (Decimal façade) ⇒ Success Criterion #4's "instruments.py is the only file with hardcoded tick_value..." passes the literal grep but the documented Decimal-exact-arithmetic rationale is inverted at every persistence boundary; the Bar model's Decimal type is decorative.
- **CR-02** (`trading_days` dual contract) ⇒ Success Criterion #2's gap-detection and same-day RTH range queries leak the inclusive special case into every caller; `seed_bars --from X --to X` silently does something different from `--from X --to X+1day`.
- **WR-06** (rollover on SPY) ⇒ Success Criterion #2's `rollover_seam` column carries phantom-true values on the Phase 1 demo ingest path; Phase 2's ORB strategy skip-on-seam logic will silently drop SPY bars on quarterly Fridays.

The project's stated core value — "trust the numbers" — is incompatible with any of these gaps shipping into Phase 2 without remediation. The right closure path is `/gsd-plan-phase --gaps` to author a Phase 1.1 inserted gap-closure plan that addresses all five concerns before Phase 2 begins. Three of the five (CR-01, CR-02, CR-03) are small surgical fixes (under 50 lines each). CR-04 is a single-function rewrite. WR-06 is a symbol gate on the detector + a one-line change in seed_bars.

**Recommendation:** Phase 1 is **functionally complete but not goal-complete**. Treat as `gaps_found` and create a focused gap-closure plan. Do not proceed to Phase 2 until at least CR-01, CR-02, CR-03, and CR-04 are remediated — these four are the load-bearing correctness gates for everything downstream. WR-06 can ship in the same plan or as a Phase 2 prelude (the rollover gate is a one-liner once `args.symbol` is plumbed through `annotate()`).

---

_Verified: 2026-05-15T00:00:00Z_
_Verifier: Claude (gsd-verifier)_
_Methodology: goal-backward (start from ROADMAP §Phase 1 success criteria + Phase 1 REQ-IDs; verify each against codebase)_
_Live verification commands run: `uv run pytest -q`, `uv run python -c <import smoke>`, `python scripts/hooks/no_naive_tz.py <bad_fixture>`, `uv run python -c <FastAPI route enum>`, `uv run python -c <instruments grep>`_
