---
phase: 01-foundation-data-in
plan: 02
subsystem: trading-core-domain
tags: [pydantic-v2, structlog, protocol-seams, instruments-sot, settings, windows-utf8]
requires:
  - Plan 01-01 toolchain (uv 0.11.14 + Python 3.12 + .venv with pydantic 2.13.4, pydantic-settings 2.14.1, structlog 25.5.0, concurrent-log-handler, PyYAML 6.0.3)
provides:
  - trading_core.instruments.REGISTRY — ES/MES/SPY frozen Pydantic models (FND-06 SoT)
  - trading_core.data.Bar — Pydantic v2 frozen model rejecting naive + non-UTC datetime (MD-06)
  - trading_core.data.DataSource — async Protocol seam (MD-01); DataSourceError/Unavailable/RateLimited/GapDetected exception hierarchy
  - trading_core.strategy.Strategy — signature-only Protocol (Phase 2 implements)
  - trading_core.risk.RiskManager — signature-only Protocol (Phase 5 implements)
  - trading_core.execution.Executor — signature-only Protocol (Phase 5 implements)
  - trading_core.events.Event + BarReceived + DegradedStateEvent + Final[str] topic constants (TOPIC_BARS, TOPIC_SIGNALS, TOPIC_RISK_DECISIONS, TOPIC_FILLS, TOPIC_POSITIONS, TOPIC_EQUITY, TOPIC_DEGRADED_STATE)
  - trading_core.config.Settings — env > .env > yaml > defaults precedence; SecretStr-redacted twelvedata_api_key (FND-03; T-01-02-01)
  - trading_core.logging.setup_logging — Windows-safe UTF-8 reconfigure + correlation_id/signal_id contextvars + ConcurrentRotatingFileHandler audit.jsonl (FND-09)
affects:
  - Plans 03 (calendars/rth.py reads Instrument.calendar_name), 04 (DuckDBStore + TwelveDataSource depend on Bar / DataSource / Settings / setup_logging), 05 (seed_bars.py CLI wires Settings + logging + DataSource registry), 06 (api package imports DataSource + Settings)
  - .env.example (documented SecretStr redaction; Phase 5 keys placeholder)
tech-stack:
  added:
    python: ["PyYAML 6.0.3 (already in pydantic-settings transitive deps)", "AwareDatetime from pydantic 2.13"]
  patterns:
    - "Pydantic v2 Protocol seams without @runtime_checkable — static-only conformance"
    - "AwareDatetime + must_be_utc field_validator at the Bar boundary — unrepresentable naive/non-UTC timestamps"
    - "Pydantic Settings settings_customise_sources hooking YamlConfigSettingsSource (precedence env > .env > yaml > defaults > secrets)"
    - "structlog ConcurrentRotatingFileHandler + sys.stdout.reconfigure(utf-8, errors=replace) before any log line"
    - "Sentinel attribute on root logger for idempotent setup_logging (clears handlers on re-call)"
    - "Forward-referenced TYPE_CHECKING imports in protocol modules to avoid circular imports between data/strategy/risk/execution"
key-files:
  created:
    - packages/trading-core/src/trading_core/instruments.py
    - packages/trading-core/src/trading_core/data/__init__.py
    - packages/trading-core/src/trading_core/data/models.py
    - packages/trading-core/src/trading_core/data/protocols.py
    - packages/trading-core/src/trading_core/strategy/__init__.py
    - packages/trading-core/src/trading_core/strategy/protocols.py
    - packages/trading-core/src/trading_core/strategy/models.py
    - packages/trading-core/src/trading_core/risk/__init__.py
    - packages/trading-core/src/trading_core/risk/protocols.py
    - packages/trading-core/src/trading_core/risk/models.py
    - packages/trading-core/src/trading_core/execution/__init__.py
    - packages/trading-core/src/trading_core/execution/protocols.py
    - packages/trading-core/src/trading_core/execution/models.py
    - packages/trading-core/src/trading_core/events/__init__.py
    - packages/trading-core/src/trading_core/events/models.py
    - packages/trading-core/src/trading_core/config.py
    - packages/trading-core/src/trading_core/logging.py
    - packages/trading-core/tests/test_instruments.py
    - packages/trading-core/tests/test_bar_model.py
    - packages/trading-core/tests/test_protocols.py
    - packages/trading-core/tests/test_config.py
    - packages/trading-core/tests/test_logging.py
  modified:
    - packages/trading-core/tests/conftest.py (added es_instrument / mes_instrument / spy_instrument fixtures)
    - .env.example (Phase 5 placeholder comment + SecretStr redaction note)
decisions:
  - "Used pydantic-settings native YamlConfigSettingsSource (available since pydantic-settings 2.5) via settings_customise_sources hook instead of writing a custom YAML loader. Cleaner than 01-RESEARCH.md O-3's fallback path; same precedence outcome (env > .env > yaml > defaults > secrets)."
  - "Avoided the literal token `@runtime_checkable` in source code (including docstrings) so the done-criteria grep `grep -rn '@runtime_checkable' packages/trading-core/src/trading_core/` returns zero matches. Docstrings now read 'NO runtime-checkable decorator' instead. The Protocol classes never had the decorator — this is purely about not tripping the grep guard."
  - "Stubbed Signal / StrategyContext / RiskConfig / RiskState / RiskDecision / Fill as empty BaseModel(extra='forbid') classes with phase-owner docstrings. Phase 2 (Signal / StrategyContext) and Phase 5 (RiskConfig+ / Fill) fill in fields. This keeps Protocol forward references resolvable without dictating field shape."
  - "Used TYPE_CHECKING-gated imports in strategy/risk/execution protocols.py to avoid runtime circular imports (data/models imports nothing; strategy/protocols name-references Signal/StrategyContext from strategy/models which already imports nothing problematic; risk/protocols name-references Signal from strategy and RiskDecision/RiskState from risk/models — all forward-string refs)."
  - "Added a positive 'docstring documents OPEN-time' assertion in test_bar_model.py to lock MD-06 into a CI-enforceable signal. The model docstring contains both 'OPEN' and the example timestamp '09:30'."
metrics:
  duration: "~7 minutes 23 seconds"
  completed_date: "2026-05-14"
  tests_added: 67
  tests_passing: "68 / 68 (1 pre-existing test_import.py + 67 new across 5 test files)"
  commits: 3
---

# Phase 01 Plan 02: Trading-Core Domain Layer Summary

trading-core domain skeleton landed: ES/MES/SPY Instrument SoT registry, Bar model with mandatory tz-aware-UTC enforcement, all four Protocol seams (DataSource live; Strategy/RiskManager/Executor signature-only), Event hierarchy + topic constants, Pydantic Settings (env > .env > yaml > defaults), and structlog wired with correlation_id contextvars + Windows-safe UTF-8 reconfigure.

## Output Confirmation

`uv run python -c "from trading_core.data import DataSource, Bar; from trading_core.events import TOPIC_BARS"` succeeds with no output errors. Documented public surface (DataSource, Bar, Strategy, RiskManager, Executor, BarReceived, DegradedStateEvent, 7× TOPIC_*) all importable through their canonical package paths.

## Test Results

68/68 tests pass:

```
$ uv run pytest packages/trading-core/tests/ -q
....................................................................     [100%]
68 passed in 1.45s
```

Breakdown:

| File | Count | Coverage |
| --- | --- | --- |
| test_import.py | 1 | Pre-existing Plan 01 import smoke. |
| test_instruments.py | 23 | ES/MES/SPY exact-Decimal pricing; unknown-symbol KeyError lists known instruments; frozen mutation raises; extra='forbid' rejects unknown fields; rth_open_et / rth_close_et pattern enforced. |
| test_bar_model.py | 8 | Happy-path construction; naive datetime rejected; non-UTC tz rejected with 'must be tz-aware UTC' message; negative volume rejected; zero volume accepted (illiquid bar); frozen mutation raises; docstring documents OPEN-time convention. |
| test_protocols.py | 22 | DataSource async signatures + exception hierarchy; Strategy/RiskManager/Executor attribute shape; absence of `_is_runtime_protocol`; BarReceived + DegradedStateEvent construct; 7 topic constants are str; Final[str] annotations intact; full public-surface import smoke. |
| test_config.py | 8 | defaults without .env; TWELVEDATA_API_KEY → SecretStr; per-key defaults (duckdb_path / parquet_root / audit_log_dir); yaml merges; env wins over yaml; SecretStr redacts in repr/str. |
| test_logging.py | 6 | audit_dir created; idempotent setup (re-call doesn't duplicate handlers); JSON record contains correlation_id from contextvar; record has level + iso-UTC timestamp; reconfigure runs when stdout encoding is cp1252; reconfigure skipped when already utf-8. |

## Done-Criteria Spot Checks

| Check | Result |
| --- | --- |
| `grep -n Decimal packages/trading-core/src/trading_core/instruments.py` | 14 matches (≥6 required) |
| `grep -nE 'tick_value\s*=\s*Decimal' packages/trading-core/src/trading_core/instruments.py` | exactly 3 lines |
| `grep pandas_market_calendars` in `instruments.py` | none — calendar_name is Literal string only |
| `grep -rn '@runtime_checkable' packages/trading-core/src/trading_core/` | zero matches |
| `grep -n AwareDatetime packages/trading-core/src/trading_core/data/models.py` | 1 match |
| `grep -n TOPIC_BARS\|TOPIC_DEGRADED_STATE packages/trading-core/src/trading_core/events/models.py` | both present |
| `grep -n sys.stdout.reconfigure packages/trading-core/src/trading_core/logging.py` | present |
| `grep -n ConcurrentRotatingFileHandler packages/trading-core/src/trading_core/logging.py` | present |
| `grep -n SecretStr packages/trading-core/src/trading_core/config.py` | present |
| `uv run python -c "from trading_core.config import Settings; s = Settings(); print(s.duckdb_path)"` | prints `data\duckdb\trading.duckdb` |
| `uv run python -c "from trading_core.instruments import get; print(get('ES').tick_value, get('MES').tick_value, get('SPY').tick_value)"` | prints `12.50 1.25 0.01` |

## Resolved Choice — pydantic-settings YAML Source

01-RESEARCH.md §Open Question O-3 anticipated needing to choose between pydantic-settings v2 native YAML support vs a custom `settings_customise_sources` shim. Investigation at the start of Task 3:

```
$ uv run python -c "from pydantic_settings import YamlConfigSettingsSource; print('available')"
available
```

pydantic-settings 2.14.1 ships `YamlConfigSettingsSource` natively and PyYAML 6.0.3 is already pulled transitively (no new dependency added). We hook it via `settings_customise_sources` (Pydantic-Settings' documented extension point) to fix the precedence chain at: env > .env > yaml > defaults > secrets. The `yaml_file` path is declared in `model_config` (`SettingsConfigDict(yaml_file="config/system.yaml", yaml_file_encoding="utf-8", extra="ignore")`).

The `extra="ignore"` is deliberate — adding a new key to `config/system.yaml` does not require a Settings code change to land; downstream phases (Plan 04 storage, Plan 05 seed_bars) can ship new yaml keys + their consuming code in the same commit.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Doc-only token avoidance] Rephrased Protocol docstrings to avoid the literal `@runtime_checkable` token**
- **Found during:** Task 2 verification (done-criteria grep)
- **Issue:** The plan's done criteria says `grep -rn '@runtime_checkable' packages/trading-core/src/trading_core/` returns zero matches. The initial docstrings contained the phrase `NO `@runtime_checkable`` (in backticks) which counts as a match. False positive on the audit — but the criterion is unambiguous.
- **Fix:** Rephrased the four protocol-module docstrings to read "NO runtime-checkable decorator" instead of "NO `@runtime_checkable`". No behavioral change; tests still pass.
- **Files modified:** `data/protocols.py`, `strategy/protocols.py`, `risk/protocols.py`, `execution/protocols.py`
- **Commit:** f76e521 (Task 2's commit — fix applied before commit)

**2. [Rule 3 - Blocker resolved up front] Verified pydantic-settings native YamlConfigSettingsSource availability before authoring `settings_customise_sources`**
- **Found during:** Task 3 setup
- **Issue:** 01-RESEARCH.md O-3 left the choice open between native and custom YAML loader; the plan said "if pydantic-settings v2 native YAML support is unavailable, supply a custom settings_customise_sources classmethod that adds YAML source".
- **Fix:** Probed availability first (`YamlConfigSettingsSource` is importable in pydantic-settings 2.14.1; PyYAML 6.0.3 is transitively installed). Used native source; documented in `## Resolved Choice` above.
- **Files modified:** none; informed the implementation choice
- **Commit:** 5b1fce2

### Other Notes

- The `tool.uv.dev-dependencies` deprecation warning continues to appear (carried over from Plan 01-01). Not addressed in this plan — out of scope; a future cleanup plan can migrate to `[dependency-groups]`.
- A SettingsConfigDict pre-existing warning may surface in some Pydantic-Settings versions about `yaml_file` not being a known field. Mitigated by `extra="ignore"`. Tests pass cleanly.

## Authentication Gates

None — no network access required for this plan (pure code authoring + tests against synthetic fixtures).

## Threat Model Disposition Confirmations

| Threat ID | Mitigation Implemented |
| --- | --- |
| T-01-02-01 (API key in logs) | `Settings.twelvedata_api_key: SecretStr | None` — `test_settings_secret_str_redacts_in_repr` proves `repr(s)` / `str(s)` do not contain the value. Structlog adapter-side redaction lands in Plan 04. |
| T-01-02-02 (naive Bar timestamps) | `Bar.ts_utc: AwareDatetime` + `must_be_utc` validator — `test_rejects_naive_datetime` and `test_rejects_tz_aware_non_utc` both green. |
| T-01-02-03 (Windows file-lock DoS on log rotation) | `ConcurrentRotatingFileHandler` (not `WatchedFileHandler`) — verified by `grep` and used in `test_setup_logging_creates_audit_dir`. |
| T-01-02-04 (Pydantic dumping fields on validation error) | Accepted; Pydantic v2 SecretStr redacts by default. Documented in `config.py` module docstring. |
| T-01-02-05 (Mutable Instrument registry) | `model_config = ConfigDict(frozen=True, extra="forbid")` — `test_mutation_raises_validation_error` + `test_extra_field_rejected` green. |

## Self-Check: PASSED

**Files verified to exist:**

- FOUND: packages/trading-core/src/trading_core/instruments.py
- FOUND: packages/trading-core/src/trading_core/data/__init__.py
- FOUND: packages/trading-core/src/trading_core/data/models.py
- FOUND: packages/trading-core/src/trading_core/data/protocols.py
- FOUND: packages/trading-core/src/trading_core/strategy/__init__.py
- FOUND: packages/trading-core/src/trading_core/strategy/protocols.py
- FOUND: packages/trading-core/src/trading_core/strategy/models.py
- FOUND: packages/trading-core/src/trading_core/risk/__init__.py
- FOUND: packages/trading-core/src/trading_core/risk/protocols.py
- FOUND: packages/trading-core/src/trading_core/risk/models.py
- FOUND: packages/trading-core/src/trading_core/execution/__init__.py
- FOUND: packages/trading-core/src/trading_core/execution/protocols.py
- FOUND: packages/trading-core/src/trading_core/execution/models.py
- FOUND: packages/trading-core/src/trading_core/events/__init__.py
- FOUND: packages/trading-core/src/trading_core/events/models.py
- FOUND: packages/trading-core/src/trading_core/config.py
- FOUND: packages/trading-core/src/trading_core/logging.py
- FOUND: packages/trading-core/tests/test_instruments.py
- FOUND: packages/trading-core/tests/test_bar_model.py
- FOUND: packages/trading-core/tests/test_protocols.py
- FOUND: packages/trading-core/tests/test_config.py
- FOUND: packages/trading-core/tests/test_logging.py

**Commits verified in git log:**

- FOUND: c96ae91 feat(01-02): add Instrument SoT registry with ES/MES/SPY (FND-06)
- FOUND: f76e521 feat(01-02): add Bar model, Event hierarchy, and 4 Protocol seams (MD-01, MD-06)
- FOUND: 5b1fce2 feat(01-02): add Pydantic Settings + structlog setup (FND-03, FND-09)
