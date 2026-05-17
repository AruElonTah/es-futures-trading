---
phase: "03"
fixed_at: 2026-05-17T00:00:00Z
review_path: .planning/phases/03-vertical-mvp-slice-backtester/03-REVIEW.md
iteration: 1
findings_in_scope: 7
fixed: 7
skipped: 0
status: all_fixed
---

# Phase 03: Code Review Fix Report

**Fixed at:** 2026-05-17T00:00:00Z
**Source review:** `.planning/phases/03-vertical-mvp-slice-backtester/03-REVIEW.md`
**Iteration:** 1

**Summary:**
- Findings in scope: 7 (3 Critical + 4 Warning)
- Fixed: 7
- Skipped: 0

---

## Fixed Issues

### CR-001: Exit check fires on signal bar before entry fills

**Files modified:** `packages/trading-core/src/trading_core/backtest/engine.py`
**Commit:** `2b71149`
**Applied fix:** Added `if i < entry_idx: continue` guard at the top of the Step 5 exit-check block. The guard prevents `check_exit` from being called on bar `i` when the entry fill is placed at `bars[i+1]` (i.e., `entry_idx = i + 1`). On the signal bar the position does not yet exist in market terms, so skipping exit evaluation on that bar is correct. Exit checking begins at `entry_idx` where the fill has actually been placed.

---

### CR-002: Equity curve uses `init_cash` instead of `prev_equity` for unrealized PnL

**Files modified:** `packages/trading-core/src/trading_core/backtest/engine.py`
**Commit:** `d7af1ea`
**Applied fix:** Introduced a `realized_equity: float = init_cash` variable that accumulates closed-trade PnL after each exit. The unrealized branch now uses `realized_equity + unrealized` instead of `init_cash + unrealized`, and the exit branch uses `realized_equity += pnl; equity_per_bar[i] = realized_equity`. This means the equity curve correctly reflects prior closed-trade gains/losses when a second (or later) trade is open. Note: this is a logic fix — requires human verification that the numbers match expected hand-computed values.

---

### CR-003: SQL injection via unescaped apostrophe in Parquet path

**Files modified:** `packages/api/src/api/routes/backtests.py`
**Commit:** `0c09cab`
**Applied fix:** Replaced the f-string interpolation of `parquet_path_str` directly into the DuckDB SQL string with a parameterized `$1` binding. The query is now `"FROM read_parquet($1) ORDER BY ts_utc ASC"` with `[parquet_path_str]` as the parameter list. This eliminates the SQL injection vector for paths containing apostrophes (e.g., Windows user directories like `C:/Users/O'Brien/...`).

---

### WR-001: `_EQUITY_ROOT` parent-count brittle against directory restructure

**Files modified:** `packages/api/src/api/routes/backtests.py`
**Commit:** `0ec51b8`
**Applied fix:** Added a `_find_repo_root(start: Path) -> Path` function that walks upward from the given path until it finds a directory containing `pyproject.toml`. Both the module-level `_EQUITY_ROOT` computation and the inline `_repo_root` reference in `get_backtest_equity` now call `_find_repo_root(Path(__file__).resolve())` instead of hard-coding `.parents[5]`. The fix is robust against directory restructures and makes the root-finding intent explicit.

---

### WR-002: WebSocket client silently consumes all exceptions

**Files modified:** `apps/web/hooks/useStream.ts`
**Commit:** `bae4070`
**Applied fix:** Restructured `ws.onmessage` so the `try/catch` wraps only `JSON.parse(event.data)`. On parse failure the handler returns early (malformed JSON is still silently dropped). The `switch` routing block is moved outside the try/catch so TypeErrors, ReferenceErrors, and Zustand store errors from case handlers propagate normally to the browser console.

---

### WR-003: `useBars` URL parameters are not encoded

**Files modified:** `apps/web/hooks/useBars.ts`
**Commit:** `0817deb`
**Applied fix:** Replaced the template-literal query string `?symbol=${symbol}&tf=${tf}&limit=${limit}` with `const params = new URLSearchParams({ symbol, tf, limit: String(limit) })` and `fetch(\`${API_BASE}/bars?${params}\`)`. `useEquityCurve` and `useEquityTrades` in `useBacktests.ts` use `runId` only in URL path segments (not query params), so they were inspected and confirmed not to have the same issue — no change needed there.

---

### WR-004: `no_direct_vbt.py` hook exits via `sys.exit` inside `main()`

**Files modified:** `scripts/hooks/no_direct_vbt.py`
**Commit:** `4555a41`
**Applied fix:** Replaced `sys.exit(1)` and `sys.exit(0)` inside `main()` with `return 1` and `return 0`. Moved `sys.exit(main(sys.argv))` to the `if __name__ == "__main__"` block. The function signature `-> int` now matches its actual behavior. Unit tests can now call `main(["file.py"])` directly and assert on the integer return code without the test process being terminated.

---

## Skipped Issues

None — all findings were fixed.

---

_Fixed: 2026-05-17T00:00:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
