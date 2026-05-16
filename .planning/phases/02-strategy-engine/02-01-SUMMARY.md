---
phase: 02-strategy-engine
plan: "01"
subsystem: strategy-models-indicators
tags:
  - indicators
  - pydantic
  - look-ahead-safety
  - decimal
  - atr
  - vwap
  - ema
  - adr
dependency_graph:
  requires:
    - 01-06-PLAN.md (FastAPI shell + trading_core package scaffolding)
    - packages/trading-core/src/trading_core/data/models.py (Bar model)
  provides:
    - trading_core.strategy.models (Signal, StrategyContext — consumed by 02-02 ORBStrategy)
    - trading_core.indicators (ATRWilder, SessionVWAP, EMA, ADR — consumed by 02-02)
    - tests/fixtures/orb_day.py (orb_day_bars — consumed by 02-02 integration tests)
  affects:
    - 02-02-PLAN.md (ORBStrategy depends on all 4 indicators + Signal + StrategyContext)
tech_stack:
  added:
    - trading_core.indicators package (new)
    - tests/fixtures/orb_day.py (new fixture)
  patterns:
    - IndicatorBase.push/snapshot_at/current look-ahead-safe API
    - Decimal-only arithmetic in price computation paths
    - ADR float/Decimal boundary (pandas resampling uses float; final result converted to Decimal)
    - BL-3 HTF shift: daily_ranges.shift(1) before rolling mean
key_files:
  created:
    - packages/trading-core/src/trading_core/indicators/__init__.py
    - packages/trading-core/src/trading_core/indicators/base.py
    - packages/trading-core/src/trading_core/indicators/atr.py
    - packages/trading-core/src/trading_core/indicators/vwap.py
    - packages/trading-core/src/trading_core/indicators/ema.py
    - packages/trading-core/src/trading_core/indicators/adr.py
    - packages/trading-core/tests/test_indicators.py
    - packages/trading-core/tests/fixtures/orb_day.py
    - packages/trading-core/tests/test_strategy_models.py
  modified:
    - packages/trading-core/src/trading_core/strategy/models.py
    - packages/trading-core/tests/fixtures/__init__.py
decisions:
  - "Signal.ts_utc: copied must_be_utc field_validator from Bar (rejects naive + non-UTC); StrategyContext.ts_utc uses AwareDatetime only (internal timestamps always UTC — no external feed risk)"
  - "Signal.entry/stop/target/size_hint: Field(gt=Decimal('0')) positive constraint enforced at Pydantic level"
  - "ATRWilder: incremental implementation (stores _prior_atr via _values[-1]); O(1) per push after warmup; no float in computation path"
  - "SessionVWAP: stateful accumulators (_cum_tpv, _cum_vol, _last_date) with session reset on ET date change; snapshot_at correctness preserved because _values[t-1] stores the post-push state"
  - "EMA: SMA seed on first period bars; _values[-1] gives prev_ema for subsequent bars"
  - "ADR: recomputes from scratch on every push (O(n) but acceptable for Phase 2); float/Decimal round-trip at pandas boundary per CLAUDE.md allowance; BL-3 enforced via shift(1)"
  - "orb_day_bars: 2024-01-02 (EST day) chosen so 14:30 UTC = 09:30 ET exactly; bar[15] is the breakout (close=471.25 > ORB high=471.00)"
metrics:
  duration: "~290 seconds (most time in ADR leakage proof — O(n^2) from-scratch recompute)"
  completed: "2026-05-16"
  tasks: 3
  files: 11
---

# Phase 2 Plan 01: Signal + StrategyContext Models + Indicator Package Summary

**One-liner:** Look-ahead-safe ATRWilder, SessionVWAP, EMA, ADR indicators with push/snapshot_at/current API; frozen Pydantic v2 Signal + StrategyContext models; BL-3 shift enforced on ADR; 45 tests all green.

## Tasks Completed

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| 1 | Fill Signal + StrategyContext Pydantic v2 models | 56f63d3 | strategy/models.py, test_strategy_models.py |
| 2 | Indicator base + ATRWilder + SessionVWAP + EMA + ADR | bfb6d25 | indicators/*.py |
| 3 | Leakage proof tests + orb_day fixture | bfb6d25 | test_indicators.py, fixtures/orb_day.py |

Note: Tasks 2 and 3 were committed together as they form a coherent unit (implementation + tests).

## Signal + StrategyContext Field Decisions

**Signal fields (9 total):**
- `strategy_id: str`, `strategy_version: str` — strategy identity
- `ts_utc: AwareDatetime` — bar open time; `must_be_utc` validator copied from Bar (rejects naive + non-UTC offsets)
- `side: Literal["long", "short"]`
- `entry`, `stop`, `target`, `size_hint: Decimal` — all `Field(gt=Decimal("0"))` (positive constraint)
- `signal_id: str` — `default_factory=lambda: str(uuid.uuid4())` auto-generated UUID

**StrategyContext fields (8 total):**
- `rollover_seam: bool`, `warmup_complete: bool`, `bar_index: int`, `ts_utc: AwareDatetime`
- `atr`, `session_vwap`, `ema`, `adr: Decimal | None` — None during warmup

Both models: `frozen=True, extra="forbid"`.

**StrategyContext.ts_utc deviation from plan:** Plan said "do NOT copy must_be_utc to StrategyContext.ts_utc — just use AwareDatetime". Followed exactly — AwareDatetime already rejects naive; internal context timestamps are always UTC so the extra validator is not needed.

## Indicator Design Choices

### ATRWilder
- **Incremental** (not rebuild-from-scratch): `_values[-1]` gives `prev_atr` inside `_compute_current()` since `_values` contains all prior results at compute time.
- `warmup_bars = period + 1`: bar[0] has no prev_close, so TR starts at bar[1]; need `period` TRs for initial SMA.
- **No float()** in computation path: verified by test suite structure.

### SessionVWAP
- **Stateful accumulators** (`_cum_tpv`, `_cum_vol`, `_last_date`) with ET date comparison for session reset.
- `snapshot_at(t)` correctness is preserved because `_values[t-1]` was computed and stored at push time — the cumulative state at that moment is encoded in the stored result.
- `warmup_bars = 1`: valid from first bar.

### EMA
- **SMA seed** when `len(_bars) == period`; `_values[-1]` gives `prev_ema` for all subsequent pushes.
- `warmup_bars = period`.

### ADR (float/Decimal boundary)
- **Recompute-from-scratch on every push** (O(n) per push, O(n²) total). Acceptable for Phase 2; Phase 4 may optimize with incremental daily tracking.
- **Float/Decimal boundary**: `float(b.high)` and `float(b.low)` used only inside the pandas resample path; `Decimal(str(round(result, 4)))` converts back at the boundary. Per CLAUDE.md: "ADR resampler may use pandas float internally with explicit Decimal round-trip at the boundary."
- **BL-3 enforcement**: `daily["range"].shift(1).rolling(period).mean()` — shift(1) ensures today's partial range never appears in today's ADR.
- `warmup_bars = (period + 1) * 390` conservative upper bound.

## Leakage Proof Results

All 4 indicators pass `snapshot_at(t) == recompute-from-scratch(bars[:t])`:
- **ATRWilder**: verified for t in range(0, 50) + range(100, 110) — 60 t-values
- **SessionVWAP**: verified for t in range(0, 30) + range(100, 110) — 40 t-values
- **EMA(20)**: verified for t in range(0, 50) — 50 t-values
- **ADR(10)**: verified at day-boundary t-values [0, 390, 780, 1170, 2340, 3120, 3900]

**BL-3 specific test**: `test_adr_bl3_today_outlier_excluded` — pushes an extreme outlier bar (high=999, low=1) as the first bar of day 12 and verifies ADR is identical to a run with a normal bar (today's range excluded by shift).

## orb_day_bars Fixture

390 Bar objects for 2024-01-02 (EST, 14:30-21:00 UTC):
- Bars 0-14: ORB window; open=high=471.00, low=470.50, close=470.75, volume=1000
- Bar 15: breakout; open=471.00, high=471.50, low=471.00, close=471.25, volume=50000
- Bars 16-389: post-breakout; close=471.25, volume=1000
- All: rollover_seam=False, timeframe="1m", symbol="SPY"

`rollover_seam_day_bars()` wraps `orb_day_bars()` with bar[0].rollover_seam=True.

## Test Results

```
packages/trading-core/tests/test_strategy_models.py  18 passed
packages/trading-core/tests/test_indicators.py       27 passed
All Phase 1 tests                                   207 passed, 1 skipped
Total regressions: 0
```

## Deviations from Plan

### Auto-fixed (Rule 2): Tasks 2 and 3 committed together

Tasks 2 (indicator implementations) and 3 (leakage tests + fixture) were written and committed together rather than separately. Both tasks share the same test file (`test_indicators.py`) and the fixture is needed by the tests, so a single coherent commit was appropriate.

### No other deviations

- All indicator implementations match the plan's interface spec exactly
- ADR float/Decimal boundary follows the explicit plan allowance
- orb_day_bars matches the 390-bar structure specified in the plan interfaces

## Known Stubs

None — all fields are fully implemented.

## Threat Flags

No new security-relevant surface introduced beyond what the plan's threat model covers. All threats (T-02-01-01 through T-02-01-04) are mitigated:
- T-02-01-01 (future bar bleed): structural guarantee via `_values[t-1]` pattern
- T-02-01-02 (ADR BL-3): `shift(1)` enforced; test `test_adr_bl3_today_outlier_excluded` asserts
- T-02-01-03 (non-UTC Signal.ts_utc): `must_be_utc` validator on Signal
- T-02-01-04 (mutable Signal): `frozen=True` on both models

## Self-Check: PASSED

- strategy/models.py: exists with Signal + StrategyContext
- indicators/__init__.py, base.py, atr.py, vwap.py, ema.py, adr.py: all exist
- test_strategy_models.py: 18 passed
- test_indicators.py: 27 passed (including leakage proofs for all 4 indicators)
- fixtures/orb_day.py: exists
- Commits 56f63d3 and bfb6d25: both present in git log
- Phase 1 regression: 207 passed, 0 failures
