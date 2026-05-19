---
phase: 06-tradingview-mcp-bridge
reviewed_at: "2026-05-19"
depth: standard
files_reviewed: 24
status: issues_found
findings:
  critical: 4
  warning: 7
  info: 4
  total: 15
---

# Phase 06 Code Review

## Critical (Blocker)

### CR-01 — Mid-file import in duckdb_store.py
**File:** `packages/trading-core/src/trading_core/storage/duckdb_store.py:64`
**Issue:** `import pandas as pd` placed mid-file after the `_LockedConn` class body — breaks import ordering and risks subtle failures if module-level code above that line references `pd`.
**Fix:** Move `import pandas as pd` to the top-level imports block.

### CR-02 — Raw DuckDB connection access bypasses lock in bridge.py
**File:** `packages/tv-bridge/src/tv_bridge/bridge.py:504-509`
**Issue:** `_draw_orb_box_if_new` directly accesses `self._store._conn.execute(...)`, bypassing the `_LockedConn` thread-serialization wrapper. Risks corrupt results under concurrent access.
**Fix:** Add a public `DuckDBStore` method (e.g. `is_orb_box_drawn(session_date)`) and call it instead of reaching into `_conn` directly.

### CR-03 — Reconciliation only compares close prices; bad volume denominator
**File:** `packages/tv-bridge/src/tv_bridge/reconciliation.py:200-203`
**Issue:** (a) Only `close` prices compared — OHLC divergences (especially `high`/`low`) are invisible. (b) Volume denominator `max(vol_twelve, 1)` produces false-positive alerts when a vendor reports zero volume.
**Fix:** (a) Extend to `open`, `high`, `low`. (b) Skip volume comparison when both sources report zero volume.

### CR-04 — Unbounded hang in replay.py finally block
**File:** `packages/tv-bridge/src/tv_bridge/replay.py:271`
**Issue:** `finally: await session.call_tool("replay_stop", {})` has no timeout. If TV Desktop is unresponsive, `fetch_bars` hangs indefinitely.
**Fix:** Wrap in `asyncio.wait_for(..., timeout=5.0)` matching the step timeout already used in this file.

---

## Warning

### WR-01 — AuthorTVAlertButton: timer leak on unmount
**File:** `apps/web/components/AuthorTVAlertButton.tsx`
**Issue:** `setTimeout(() => setToast(null), 6000)` is never cleared on component unmount.
**Fix:** Store timer ID in a ref and clear it in a `useEffect` cleanup or in `finally`.

### WR-02 — Flatten confirm failures silently ignored in blotter UI
**File:** `apps/web/app/dashboard/blotter/page.tsx`
**Issue:** Non-2xx response from flatten POST is swallowed with no user feedback.
**Fix:** Check `res.ok` and surface an error toast on failure.

### WR-03 — Supervisor CancelledError handler doesn't clear session
**File:** `packages/tv-bridge/src/tv_bridge/bridge.py`
**Issue:** `except asyncio.CancelledError` re-raises without setting `self._session = None`. `is_connected` returns stale `True` after cancellation.
**Fix:** Set `self._session = None` before re-raising.

### WR-04 — Cleanup calendar fallback too aggressive
**File:** `packages/tv-bridge/src/tv_bridge/cleanup.py`
**Issue:** `_trading_days_ago` fallback returns `today - timedelta(days=n * 2)` when schedule is short, potentially deleting far more overlays than intended.
**Fix:** Raise `ValueError` or return `today` (retain everything) on fallback rather than using an unpredictable cutoff.

### WR-05 — Double-deletion produces spurious cleanup_partial audit rows
**File:** `packages/tv-bridge/src/tv_bridge/cleanup.py`
**Issue:** `nightly_cleanup` calls `draw_remove_one` for overlays already soft-deleted by `DELETE /tv/alerts/{id}`, writing misleading `cleanup_partial` audit rows.
**Fix:** Filter to `deleted_at IS NULL` in `list_overlays_older_than`, or skip `cleanup_partial` rows when `deleted_at` is already set.

### WR-06 — Hardcoded MCP server path duplicated across two modules
**File:** `packages/tv-bridge/src/tv_bridge/bridge.py`, `packages/tv-bridge/src/tv_bridge/replay.py`
**Issue:** `C:/Users/Admin/tradingview-mcp-jackson/` hardcoded in both files instead of reading from `Settings`.
**Fix:** Centralise in `Settings.tv_mcp_server_path` and read from there in both modules.

### WR-07 — Unstable React list key in blotter page
**File:** `apps/web/app/dashboard/blotter/page.tsx`
**Issue:** Trade list rows use array index as React key, causing incorrect re-renders on inserts/deletes.
**Fix:** Use a stable unique field (e.g. `trade.fill_id`) as the key.

---

## Info

### IN-01 — `__init__.py` public API surface too wide
**File:** `packages/tv-bridge/src/tv_bridge/__init__.py`
**Suggestion:** Narrow `__all__` to externally-consumed symbols only.

### IN-02 — Missing index on `tv_overlays.trading_date`
**File:** `packages/trading-core/src/trading_core/storage/schema.sql`
**Suggestion:** Add `CREATE INDEX IF NOT EXISTS idx_tv_overlays_trading_date ON tv_overlays(trading_date)` to keep `nightly_cleanup` queries fast as rows accumulate.

### IN-03 — `run_backtest.py` active data source not logged
**File:** `scripts/run_backtest.py`
**Suggestion:** Log the active data source at `INFO` level at script start so operators know which source is in use.

### IN-04 — EventBus not torn down in failure isolation test
**File:** `packages/tv-bridge/tests/integration/test_tv_failure_isolation.py`
**Suggestion:** Add `await bus.shutdown()` in a `finally` block to prevent background task leakage into subsequent tests in the same pytest session.
