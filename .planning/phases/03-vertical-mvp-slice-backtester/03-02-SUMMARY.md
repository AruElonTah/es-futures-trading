---
phase: "03"
plan: "02"
subsystem: backtest-execution-risk
tags:
  - backtest
  - vbt
  - paper-executor
  - risk
  - slippage
  - eod-flatten
  - wave-2
dependency_graph:
  requires:
    - 03-01-SUMMARY  # D-10 Fill/RiskDecision/RiskState/RiskConfig fields
    - 02-02-SUMMARY  # ORBStrategy driver pattern
    - 01-02-SUMMARY  # execution/models.py + risk/models.py stubs
  provides:
    - safe_from_signals-wrapper   # BT-02, D-13 enforced at the only VBT call site
    - PassThroughRiskManager      # BT-03 minimal RiskManager Protocol impl
    - PaperExecutor               # BT-03, BT-08 next-bar fill + slippage + EOD flatten
  affects:
    - 03-03-PLAN  # BacktestEngine consumes all three new components
    - 03-04-PLAN  # FastAPI routes use PaperExecutor for live fills
tech_stack:
  added:
    - vectorbt.Portfolio.from_signals via safe_from_signals wrapper (D-13)
    - ZoneInfo("America/New_York") DST-correct session-phase slippage
    - Decimal-only price arithmetic throughout PaperExecutor (T-03-02-04)
    - instruments.get(symbol).tick_size as sole tick_size source (T-03-02-03)
    - unittest.mock.patch + classmethod spy for VBT kwargs capture in tests
  patterns:
    - TDD RED-GREEN on both tasks (4 commits: 2 test + 2 impl)
    - _shift_bool() uses .where(notna(), False).astype(bool) to avoid FutureWarning
    - check_exit() returns (reason, price) tuple or None (no Fill mutation at this level)
    - is_last_rth_bar as caller-provided bool (executor does not own calendar logic)
key_files:
  created:
    - packages/trading-core/src/trading_core/backtest/__init__.py
    - packages/trading-core/src/trading_core/backtest/safe_signals.py
    - packages/trading-core/src/trading_core/risk/pass_through.py
    - packages/trading-core/src/trading_core/execution/paper.py
    - packages/trading-core/tests/test_safe_signals.py
    - packages/trading-core/tests/test_pass_through_risk.py
    - packages/trading-core/tests/test_paper_executor.py
  modified:
    - packages/trading-core/src/trading_core/risk/__init__.py
    - packages/trading-core/src/trading_core/execution/__init__.py
decisions:
  - "safe_from_signals uses .where(notna(), False).astype(bool) instead of .fillna(False).infer_objects(copy=False) — the latter still emits FutureWarning under pandas 2.3.3 (installed version higher than pinned 2.2.x)"
  - "Mock spy for VBT kwargs capture uses classmethod(spy) patch — autospec approach failed for classmethods; directly patching the classmethod attribute works correctly"
  - "PaperExecutor.check_exit returns (reason, price) tuple instead of Fill — caller (BacktestEngine) needs to build the full Fill with signal_id; executor stays thin"
  - "exit_reason='target' on entry Fill is a sentinel (not exit semantics) — entry fills must use one of the D-11 literals; 'target' chosen as placeholder; Phase 5 to split entry/exit Fill models"
  - "slippage_ticks=0 on EOD-flat exit — fill_price=bar.close already has no adverse adjustment; zero ticks reflects that no order routing occurred"
  - "PassThroughRiskManager docstring explicitly calls out accepted T-03-02-05 risk — Phase 5 must replace with prop-firm logic"
metrics:
  duration: "~22 minutes"
  completed: "2026-05-17"
  tasks: 2
  files: 9
---

# Phase 03 Plan 02: safe_from_signals + PassThroughRiskManager + PaperExecutor Summary

## One-liner

Lookahead-safe VBT wrapper with string-price guard and shift(1) enforcement, minimal pass-through risk manager clamping to max_contracts, and paper executor with DST-correct session-phase slippage, stop-first intrabar conflict resolution (D-12), and EOD flatten (BT-08).

## What Was Built

### Task 1 — safe_from_signals Wrapper (BT-02, D-13)

**`packages/trading-core/src/trading_core/backtest/safe_signals.py`**:

The only legitimate `vbt.Portfolio.from_signals` call site (excluded from the pre-commit hook registered in Plan 01).

Key behaviors:
- `isinstance(price, str)` guard raises `ValueError` with substrings `"price must be an array"` and `"Numba JIT"` — protects against the `price='nextbar'` Numba crash (Pitfall 1)
- Internal `_shift_bool()` uses `shifted.where(shifted.notna(), False).astype(bool)` — avoids FutureWarning under pandas 2.2+/2.3.x (Pitfall 3)
- Shifts `entries`, `exits`, and (when supplied) `short_entries`/`short_exits` by 1 bar
- Optional kwargs (`sl_stop`, `tp_stop`, `open`, `high`, `low`) only injected when non-None — no surprises for VBT's Numba inner loop
- Sentinel comment: `# NOTE: This is the ONLY legitimate call site for vbt.Portfolio.from_signals`

**`packages/trading-core/src/trading_core/backtest/__init__.py`**: Module docstring only.

**`packages/trading-core/tests/test_safe_signals.py`**: 11 tests replacing the Wave 0 xfail stub:
- `TestRejectsStringPrice`: 4 tests (nextbar, Numba JIT mention, any string, float is OK)
- `TestInternalShift`: 4 tests with classmethod spy (entries shifted, exits shifted, short_entries shifted, short_entries=None not injected)
- `TestNoFutureWarning`: 1 test using `warnings.catch_warnings()` + `simplefilter("error", FutureWarning)`
- `TestReturnPassthrough`: 1 test verifying return type is `vbt.Portfolio`
- `TestEndToEndSmoke`: 1 test — 30-bar VBT run with no crash, non-negative trade count

### Task 2 — PassThroughRiskManager + PaperExecutor (BT-03, BT-08, D-10, D-12)

**`packages/trading-core/src/trading_core/risk/pass_through.py`** (`PassThroughRiskManager`):
- `async def check(signal, state) -> RiskDecision`: always returns `approved=True`, `reason="pass_through"`, `adjusted_size=min(int(signal.size_hint), config.max_contracts)`
- Structurally satisfies `RiskManager` Protocol — no inheritance
- Accepted risk T-03-02-05 documented in class docstring (paper-only, Phase 5 replaces)

**`packages/trading-core/src/trading_core/execution/paper.py`** (`PaperExecutor`):
- `_slippage_ticks(bar_ts_utc, symbol)`: `bar_ts_utc.astimezone(ZoneInfo("America/New_York")).time()` — DST-correct; returns 2 in `[9:30, 9:45)` ET, 1 off-peak
- `fill_entry(signal, decision, next_bar) -> Fill`: adverse fill (long=`open+adj`, short=`open-adj`); `exit_reason="target"` sentinel; `slippage_ticks` from session phase
- `check_exit(*, side, entry_price, stop, target, bar, is_last_rth_bar) -> tuple | None`: stop-first D-12; returns `(exit_reason, exit_price)` or `None`
- `fill_exit(*, signal, exit_reason, exit_price, exit_ts_utc, fill_qty) -> Fill`: exit Fill with opposite side; `slippage_ticks=0` on `eod_flat`

**`packages/trading-core/tests/test_pass_through_risk.py`**: 4 tests:
- `test_approved_is_true_async`, `test_reason_is_pass_through`
- `test_size_hint_5_clamped_to_1_with_max_1`, `test_size_hint_2_with_max_3_gives_2`

**`packages/trading-core/tests/test_paper_executor.py`**: 24 tests (replacing Wave 0 xfail stub):
- `TestSlippageWindow`: 6 tests including DST spring-forward (2026-03-09 EDT cases)
- `TestEntryFill`: 5 tests (long/short price arithmetic, ES tick_size, Fill fields)
- `TestIntrabarConflict`: 7 tests (stop-only, target-only, both D-12, short side variations)
- `TestEODFlatten`: 4 tests (eod_flat reason/price, sum(positions)==0, slippage_ticks=0, EOD priority over neither-hit)

**`risk/__init__.py` + `execution/__init__.py`**: re-export `PassThroughRiskManager` and `PaperExecutor`.

## Commits

| Task | Commit | Files |
|------|--------|-------|
| 1 RED: safe_from_signals tests | 7522110 | test_safe_signals.py |
| 1 GREEN: safe_from_signals impl | 5c314b2 | backtest/__init__.py, backtest/safe_signals.py, test_safe_signals.py |
| 2 RED: risk+executor tests | bb36ce0 | test_pass_through_risk.py, test_paper_executor.py |
| 2 GREEN: risk+executor impl | 58642ae | risk/pass_through.py, execution/paper.py, risk/__init__.py, execution/__init__.py |

## Test Results

- Task 1: 11 tests pass (safe_from_signals)
- Task 2: 28 tests pass (4 risk + 24 executor)
- Full suite: 313 passed, 1 skipped, 5 xfailed (6 pre-existing api/tv-bridge import failures — NOT caused by this plan)
- Pre-commit `no-direct-vbt-from-signals`: exit 0 (safe_signals.py is excluded; no other call sites)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] FutureWarning not suppressed by `.infer_objects(copy=False)` pattern**
- **Found during:** Task 1 GREEN — `TestNoFutureWarning` test failed with FutureWarning
- **Issue:** The plan spec + RESEARCH.md both specified `.fillna(False).infer_objects(copy=False)`. Under the installed pandas 2.3.3 (higher than pinned 2.2.x), this pattern still emits FutureWarning because the warning fires from `.fillna(False)` itself, before `infer_objects` has a chance to run
- **Fix:** Replaced with `shifted.where(shifted.notna(), other=False).astype(bool)` — verified FutureWarning-free across pandas 2.2.x and 2.3.x
- **Files modified:** `packages/trading-core/src/trading_core/backtest/safe_signals.py`
- **Commit:** 5c314b2

**2. [Rule 1 - Bug] Mock recursion when patching classmethod vbt.Portfolio.from_signals**
- **Found during:** Task 1 GREEN — tests using `patch.object(vbt.Portfolio, "from_signals", side_effect=_spy)` caused RecursionError because the side_effect called `vbt.Portfolio.from_signals` which was itself patched
- **Fix:** Replaced with `patch("trading_core.backtest.safe_signals.vbt.Portfolio.from_signals", new=classmethod(spy))` — patches the reference in `safe_signals` module's namespace instead of the class itself; spy captures kwargs and returns None (test validates kwargs not portfolio)
- **Files modified:** `packages/trading-core/tests/test_safe_signals.py`
- **Commit:** 5c314b2

## Known Stubs

None — all fields in `safe_from_signals`, `PassThroughRiskManager`, and `PaperExecutor` are wired to actual logic. No placeholder data flows to output.

## Known Debt

**exit_reason='target' sentinel on entry Fill (Phase 5 refinement)**

`PaperExecutor.fill_entry()` returns `Fill(exit_reason="target", ...)` as a structural placeholder. `Fill.exit_reason` is a D-11 four-value Literal; entry fills must carry one of these values, but "entry" has no semantic representation. The driver loop in Plan 03 distinguishes entry from exit fills by maintaining separate lists — the exit_reason on entry fills is never read for business logic.

**Phase 5 action required:** Split `Fill` into `EntryFill` and `ExitFill` models, or add a fifth literal `"entry"` to the Literal if that's cleaner. The current sentinel causes no correctness issue but is semantically confusing in the audit log.

## Threat Surface Scan

No new network endpoints, auth paths, or file access patterns introduced. All price math uses `Decimal` (T-03-02-04). All `tick_size` reads go through `instruments.get(symbol)` (T-03-02-03). The `isinstance(price, str)` guard covers T-03-02-01. Shift(1) enforcement covers T-03-02-02.

## Self-Check: PASSED

Verified created files exist:
- `packages/trading-core/src/trading_core/backtest/__init__.py`: FOUND
- `packages/trading-core/src/trading_core/backtest/safe_signals.py`: FOUND
- `packages/trading-core/src/trading_core/risk/pass_through.py`: FOUND
- `packages/trading-core/src/trading_core/execution/paper.py`: FOUND
- `packages/trading-core/tests/test_safe_signals.py`: FOUND
- `packages/trading-core/tests/test_pass_through_risk.py`: FOUND
- `packages/trading-core/tests/test_paper_executor.py`: FOUND

Verified commits exist in git log:
- 7522110: test(03-02) — FOUND
- 5c314b2: feat(03-02) safe_from_signals — FOUND
- bb36ce0: test(03-02) risk+executor — FOUND
- 58642ae: feat(03-02) PassThrough+Paper — FOUND
