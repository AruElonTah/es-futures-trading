---
phase: 01-foundation-data-in
reviewed: 2026-05-15T00:00:00Z
depth: standard
files_reviewed: 27
files_reviewed_list:
  - packages/trading-core/src/trading_core/__init__.py
  - packages/trading-core/src/trading_core/instruments.py
  - packages/trading-core/src/trading_core/config.py
  - packages/trading-core/src/trading_core/logging.py
  - packages/trading-core/src/trading_core/calendars/__init__.py
  - packages/trading-core/src/trading_core/calendars/rth.py
  - packages/trading-core/src/trading_core/data/__init__.py
  - packages/trading-core/src/trading_core/data/models.py
  - packages/trading-core/src/trading_core/data/protocols.py
  - packages/trading-core/src/trading_core/data/twelvedata.py
  - packages/trading-core/src/trading_core/data/tradingview.py
  - packages/trading-core/src/trading_core/events/__init__.py
  - packages/trading-core/src/trading_core/events/bus.py
  - packages/trading-core/src/trading_core/events/models.py
  - packages/trading-core/src/trading_core/execution/__init__.py
  - packages/trading-core/src/trading_core/execution/models.py
  - packages/trading-core/src/trading_core/execution/protocols.py
  - packages/trading-core/src/trading_core/risk/__init__.py
  - packages/trading-core/src/trading_core/risk/models.py
  - packages/trading-core/src/trading_core/risk/protocols.py
  - packages/trading-core/src/trading_core/storage/__init__.py
  - packages/trading-core/src/trading_core/storage/schema.sql
  - packages/trading-core/src/trading_core/storage/duckdb_store.py
  - packages/trading-core/src/trading_core/storage/runs.py
  - packages/trading-core/src/trading_core/strategy/__init__.py
  - packages/trading-core/src/trading_core/strategy/models.py
  - packages/trading-core/src/trading_core/strategy/protocols.py
  - packages/api/src/api/__init__.py
  - packages/api/src/api/app.py
  - scripts/seed_bars.py
  - scripts/hooks/no_naive_tz.py
  - .pre-commit-config.yaml
  - .gitleaks.toml
  - pyproject.toml
  - packages/trading-core/pyproject.toml
  - packages/api/pyproject.toml
  - apps/web/app/page.tsx
  - apps/web/app/layout.tsx
  - apps/web/next.config.ts
  - apps/web/tsconfig.json
  - apps/web/package.json
  - apps/web/eslint.config.mjs
findings:
  critical: 4
  warning: 8
  info: 6
  total: 18
status: issues_found
---

# Phase 01: Code Review Report

**Reviewed:** 2026-05-15
**Depth:** standard
**Files Reviewed:** 27 source files (+ 4 config + 6 web stubs reviewed lightly per scope; tests excluded by scope)
**Status:** issues_found

## Top 3 Fixes Gating Downstream Work

1. **CR-01 — DuckDB upsert is NOT idempotent under DST rollover for TIMESTAMPTZ in DuckDB 1.x.** The PK uses `TIMESTAMPTZ` but `INSERT OR REPLACE` semantics rely on byte-identical timestamps. Twelve Data returns `pandas.Timestamp(v["datetime"], tz="UTC").to_pydatetime()`, whose microseconds are zeroed; the gap-detector path produces the same. *However* the seed_bars pipeline calls `pd.to_datetime(out["ts_utc"], utc=True)` again on `_set_ts_index` (effectively a no-op) and re-emits `.itertuples()` — fine. The real bug: the `data_hash()` payload column projection re-uses the row order from `df`, but the DuckDB `upsert_bars` writes via `executemany` row-by-row with float casts, while `data_hash` reads the source `df` directly with whatever dtype the adapter chose. A re-run after a pyarrow patch upgrade can drift the hash. Pin pyarrow but also assert column dtypes are explicit in `data_hash` (cast every numeric column to `float64` before serializing). See CR-01 below.

2. **CR-02 — `trading_days()` silently violates documented half-open semantics on a same-day range.** When `start==end`, it returns the full single day instead of empty. Callers (`is_rth`, `expected_rth_timestamps`, `RthFilter.find_gaps`) downstream of `seed_bars --from X --to X` will treat that as "one trading day" and emit phantom gaps for the entire RTH session. This is the canonical "off-by-one in the load-bearing session filter" that the focus areas flag as project-critical.

3. **CR-03 — `Bar` Pydantic model declares `Decimal` for OHLC but the entire pipeline coerces to `float` before persistence.** That defeats the explicitly-stated "Decimal not float because float drift produces 1-tick miscounts at boundaries; over a 252-day backtest those miscounts compound into multi-thousand-dollar reproducibility gaps" rationale in `instruments.py` lines 5–10. The Bar model is essentially decorative in Phase 1 — every fill / risk / hash path uses `float`. Either drop the Decimal façade or fix the pipeline to honor it.

## Summary

The Phase 1 implementation is competent: tz-aware UTC discipline is enforced at the `Bar` and `is_rth` boundaries, secrets handling has a redaction sentinel and dual gitleaks/structlog gates, the EventBus FIFO contract is correct, and the seed_bars CLI's `try/finally` audit-chain is sound. Most issues are *correctness drift between layers*: documented contracts in one module not reflected in another module's coercions.

The four BLOCKER findings each erode "trust the numbers" in a concrete, reproducible way: (1) hash-stability rides on column dtypes that aren't asserted, (2) a same-day session range returns the wrong shape, (3) the Decimal contract is dead-on-arrival, (4) `_set_ts_index` corrupts callers that pass an already-indexed DataFrame. None are exploitable security vulnerabilities (paper-trading, no broker keys), but each one corrupts a backtest in a way the reviewer's eye would miss.

| Severity | Count |
|---|---|
| Critical (BLOCKER) | 4 |
| Warning | 8 |
| Info | 6 |
| **Total** | **18** |

---

## Critical Issues

### CR-01: `data_hash()` is not byte-stable across pipeline shapes

**File:** `packages/trading-core/src/trading_core/storage/runs.py:102-131`

**Issue:** `data_hash(df)` projects `_DATA_HASH_COLS = ["symbol","timeframe","ts_utc","open","high","low","close","volume","rollover_seam","provider"]` and sha256's the pyarrow Parquet bytes. The pyarrow flags are correctly set (`compression="none"`, `use_dictionary=False`, `write_statistics=False`), but **column dtypes are never asserted**:

- `TwelveDataSource.fetch_bars` returns OHLC as Python `float` (line 227–230 of `twelvedata.py`).
- `TradingViewDataSource.fetch_bars` returns OHLC as Python `float` (line 311–314 of `tradingview.py`).
- `seed_bars._set_ts_index` does `pd.to_datetime(out["ts_utc"], utc=True)` which can return `datetime64[ns, UTC]` *or* `datetime64[us, UTC]` depending on pandas version (pandas 2.2.x defaults to `ns` for from-string conversion but `us` for from-datetime when the source is a Python `datetime`).
- `rollover_seam` is computed as a Python list of `bool` → pandas object dtype unless coerced to `bool_`.

If any of these dtypes drifts across patch versions (or between the two adapters), `data_hash` returns a different hex for byte-identical bar content. That's the *exact failure mode* the Phase 3 reproducibility CI gate is supposed to catch — but it would fail the gate on a routine pandas patch upgrade, not on a real bar mutation.

**Why it matters:** The reproducibility CI gate (FND-08) is the load-bearing test that protects every Phase 4+ optimization run. If `data_hash` is fragile under upstream-patch churn, the gate flaps and the team learns to ignore it — "trust the numbers" collapses.

**Fix:** Force explicit dtypes inside `data_hash` before serialization:

```python
def data_hash(df: pd.DataFrame) -> str:
    projected = (
        df[_DATA_HASH_COLS]
        .sort_values(["symbol", "timeframe", "ts_utc"])
        .reset_index(drop=True)
    )
    # Lock dtypes so a pandas/pyarrow patch upgrade cannot drift the hash.
    projected = projected.astype({
        "symbol": "string",
        "timeframe": "string",
        "open": "float64",
        "high": "float64",
        "low": "float64",
        "close": "float64",
        "volume": "int64",
        "rollover_seam": "bool",
        "provider": "string",
    })
    projected["ts_utc"] = pd.to_datetime(projected["ts_utc"], utc=True).astype(
        "datetime64[ns, UTC]"
    )
    table = pa.Table.from_pandas(projected, preserve_index=False)
    ...
```

Add a unit test that constructs the same logical bar twice with different source dtypes and asserts the hash matches.

---

### CR-02: `trading_days()` returns a full day for same-day inclusive range, breaking documented half-open semantics

**File:** `packages/trading-core/src/trading_core/calendars/rth.py:54-79`

**Issue:** The docstring claims half-open `[start, end)` semantics, then carves out a special case:

```python
if end_d > start_d:
    end_d = end_d - timedelta(days=1)
```

When `start_d == end_d`, the schedule is called with that same date on both bounds — returning that one trading day **inclusively**. This is documented as intentional ("so `is_rth` can ask 'is today a trading day?' without phantom-empty results"), but it leaks out to every other caller:

- `expected_rth_timestamps(symbol, tf, start=X, end=X)` returns all 390 1m bars for X (not zero). 
- `RthFilter.find_gaps` with `start == end` reports the entire RTH session as missing.
- `seed_bars.py --from 2024-01-02 --to 2024-01-02` would attempt to load the entire 2024-01-02 RTH window (the inverse of half-open `[X, X) == empty`).

The session filter is the load-bearing artifact that protects every backtest. A user passing a single-day range will silently get a different shape than the docstring promises.

**Why it matters:** Either the half-open semantics are real or they aren't. The dual contract (half-open in general, inclusive on same-day) is the kind of bug that produces "but the backtest said it was profitable" debugging sessions six weeks later.

**Fix:** Pick one semantic and document it. The safer choice for "trust the numbers" is honest half-open everywhere — let `is_rth` query the calendar with `start_d, end_d` (it's already going to compare against the window anyway, so a single-day inclusive helper can live as a private `_trading_day_membership` function). Concretely:

```python
def trading_days(calendar_name: str, start, end) -> pd.DatetimeIndex:
    """Half-open [start, end) trading-day index."""
    cal = mcal.get_calendar(calendar_name)
    start_d = start.date() if isinstance(start, datetime) else start
    end_d = end.date() if isinstance(end, datetime) else end
    if end_d <= start_d:
        return pd.DatetimeIndex([])
    sched = cal.schedule(start_date=start_d, end_date=end_d - timedelta(days=1))
    return sched.index

def _is_trading_day(calendar_name: str, d: date) -> bool:
    return not mcal.get_calendar(calendar_name).schedule(d, d).empty
```

Then rewrite `is_rth` to call `_is_trading_day(inst.calendar_name, et_date)`.

---

### CR-03: `Bar` declares `Decimal` for OHLC but the entire pipeline uses `float`

**File:** `packages/trading-core/src/trading_core/data/models.py:39-45`
**Related:** `packages/trading-core/src/trading_core/data/twelvedata.py:227-230`, `tradingview.py:311-314`, `storage/duckdb_store.py:133-138`, `storage/schema.sql:9-12`

**Issue:** `Bar` declares:

```python
open: Decimal
high: Decimal
low: Decimal
close: Decimal
```

But:

- `TwelveDataSource.fetch_bars` builds OHLC columns as `[float(v["open"]) for v in values]`.
- `TradingViewDataSource.fetch_bars` does the same: `[float(b["open"]) for b in bars]`.
- `storage/schema.sql` declares `open DOUBLE`, `high DOUBLE`, `low DOUBLE`, `close DOUBLE`.
- `DuckDBStore.upsert_bars` calls `float(d["open"])` on every row.
- The live `TradingViewDataSource.subscribe_bars` does construct a `Bar`, passing `b["open"]` (a float from the adapter) which Pydantic v2 silently coerces to `Decimal(float)` — that *captures* the float's IEEE-754 imprecision, not the original vendor decimal string.

The `instruments.py` docstring (lines 5–10) explicitly states "Decimal — not float — because ATR-based position sizing depends on exact arithmetic. Float drift produces 1-tick miscounts at boundaries; over a 252-day backtest those miscounts compound into multi-thousand-dollar reproducibility gaps."

So the model says one thing and the implementation does another. The Decimal in `Bar` is a decorative type-hint that's actively misleading: a reader of `data/models.py` who needs to write Phase 5 risk math will assume bar prices are exact decimals when they have already been round-tripped through float.

**Why it matters:** The exact correctness rationale that `instruments.py` documents has been silently inverted at every persistence boundary. Either the project commits to Decimal-end-to-end (which means schema → `DECIMAL(18,8)`, Twelve Data adapter reading `v["open"]` as `Decimal(v["open"])` — Twelve Data returns strings, not floats, so this is feasible) or it commits to float-end-to-end and the `Bar` model and the `instruments.py` rationale need updating.

**Fix (Option A — preferred for "trust the numbers"):** Honor Decimal end-to-end.

```python
# twelvedata.py
"open": [Decimal(v["open"]) for v in values],  # Twelve Data returns strings
# tradingview.py — TV returns floats from JS, so accept the loss here OR cast via repr:
"open": [Decimal(repr(b["open"])) for b in bars],
# schema.sql
open DECIMAL(18, 8) NOT NULL,
# duckdb_store.py — drop the float() casts; pass Decimal through.
```

**Fix (Option B — pragmatic):** Drop the Decimal type from `Bar`, update `instruments.py` rationale to scope Decimal to pricing-metadata only (tick_value, tick_size, point_value where exact arithmetic still matters), and document that bar OHLC is `float64` end-to-end.

Either fix is acceptable; doing nothing is not.

---

### CR-04: `_set_ts_index` corrupts a DataFrame that already has `ts_utc` as the index

**File:** `scripts/seed_bars.py:103-116`

**Issue:**

```python
def _set_ts_index(df: pd.DataFrame) -> pd.DataFrame:
    if "ts_utc" not in df.columns:
        # Already indexed (e.g., adapter returned an indexed shape).
        return df
    out = df.copy()
    out["ts_utc"] = pd.to_datetime(out["ts_utc"], utc=True)
    return out.set_index("ts_utc")
```

The early return assumes "no `ts_utc` column ⇒ already indexed by ts_utc." That assumption is wrong in two scenarios:

1. A future adapter could return a DataFrame indexed by a *different* DatetimeIndex (e.g., `pd.RangeIndex`) with no `ts_utc` column at all — `_set_ts_index` returns it unchanged and `rth.filter` then raises (or worse, silently drops every row because the index has no UTC tz).
2. A test-mocked DataFrame with `ts_utc` already on the index but ALSO duplicated as a column — `set_index("ts_utc")` would error or produce a double-indexed shape.

More importantly: `pd.to_datetime(out["ts_utc"], utc=True)` on an already-tz-aware UTC column is a no-op — but on a tz-naive column it *silently localizes to UTC*, masking a real bug (an adapter regression that returns naive timestamps would never be caught here; it would just be silently re-labeled as UTC).

**Why it matters:** The "tz-aware UTC everywhere" invariant must be load-bearing, not best-effort. The `no_naive_tz` hook only catches `datetime.now()` patterns; it does not catch a DataFrame column that arrives naive from an adapter.

**Fix:** Assert preconditions explicitly:

```python
def _set_ts_index(df: pd.DataFrame) -> pd.DataFrame:
    if "ts_utc" in df.columns:
        ts = df["ts_utc"]
        # Detect naive series early — do NOT silently localize.
        if pd.api.types.is_datetime64_any_dtype(ts) and ts.dt.tz is None:
            raise ValueError("ts_utc column is naive; adapter must return tz-aware UTC")
        out = df.copy()
        out["ts_utc"] = pd.to_datetime(out["ts_utc"], utc=True)
        return out.set_index("ts_utc")
    # No ts_utc column — must already be indexed by tz-aware UTC.
    if df.index.tz is None:
        raise ValueError("DataFrame has no ts_utc column and index is not tz-aware")
    return df
```

---

## Warnings

### WR-01: `_publish_degraded` swallowing in `TradingViewDataSource` can hide bus misconfiguration

**File:** `packages/trading-core/src/trading_core/data/tradingview.py:138-153`

**Issue:** `_publish_degraded` wraps `bus.publish(...)` in a bare `except Exception`. If the operator wires the adapter against a typo'd topic (e.g., they construct a bus that rejects `degraded_state`), every degraded-state notification is silently dropped and only a `WARNING` line is logged.

**Why it matters:** The whole point of the degraded-state event is operator visibility (UI banner). Swallowing the publish failure means the UI silently stops getting CDP-disconnect signals — degraded the moment it's most needed.

**Fix:** Tighten the catch and re-raise on programmer-error classes (`KeyError`, `ValueError`); only swallow legitimate transport-layer failures (`asyncio.CancelledError` is the only realistic case for a bus that already returned from publish). Or at minimum, escalate the log line to `ERROR`.

---

### WR-02: `subscribe_bars` polling loop has no cancellation/cleanup propagation

**File:** `packages/trading-core/src/trading_core/data/tradingview.py:321-409`

**Issue:** The `while True:` loop yields bars in an async generator. When the consumer breaks out of `async for`, Python sends `GeneratorExit` to the generator — but the inner `try/except Exception` at line 405 catches it (since `BaseException` propagates differently from `Exception`, but `GeneratorExit` is a `BaseException`, so this is actually safe). However, the `await asyncio.sleep(poll_seconds)` at the end of the loop will swallow cancellation if the consumer cancels the parent task — there is no way to break out faster than `poll_seconds` (up to 15 min for `15m` timeframe).

**Why it matters:** A graceful shutdown of seed_bars or the FastAPI app will hang up to 15 minutes waiting on a 15m subscribe loop's sleep.

**Fix:** Use a cancellable sleep — `await asyncio.wait_for(asyncio.Event().wait(), timeout=poll_seconds)` with an `asyncio.TimeoutError` swallow, or thread a cancel `Event` through the constructor.

---

### WR-03: `EventBus.publish` is not concurrency-safe under subscribe/unsubscribe races

**File:** `packages/trading-core/src/trading_core/events/bus.py:70-81`

**Issue:** `publish` snapshots the queue list inside the lock, then iterates and `await q.put(event)` outside the lock. That's correct for ordering, but: if a subscriber's `async with bus.subscribe(topic) as sub:` block exits *between* the snapshot and the put, the event is still delivered to the now-unsubscribed queue. That queue is GC'd (no other refs), but Python keeps it alive for the duration of the `put`. Net effect: an event sits in a queue nobody will ever read, and the queue is held in memory until the publisher returns from the iteration. Not a leak, but it violates the "exit cleanly stops delivery" expectation.

More subtly: the order-preservation guarantee documented in the docstring ("Per-subscriber `put` calls are awaited in registration order to preserve deterministic ordering for tests") only holds *if* every subscriber's queue has capacity. With unbounded queues this is true. The docstring should explicitly note that adding bounded queues in Phase 5/7 will break the deterministic ordering guarantee.

**Why it matters:** Plan 5/7 may quietly add bounded queues and break test determinism.

**Fix:** Add a docstring note: "Deterministic ordering depends on unbounded queues. A future bounded-queue refactor must revisit this guarantee." Optionally, after the snapshot, re-check membership before put: `if q in self._subscribers.get(topic, []): await q.put(event)`. (This requires re-acquiring the lock per put, which costs the deterministic-ordering guarantee — trade-off.)

---

### WR-04: `RthFilter.filter` expansion of `end = idx.max() + 1 day` interacts with CR-02 to over-include

**File:** `packages/trading-core/src/trading_core/calendars/rth.py:206-224`

**Issue:**

```python
start = idx.min().to_pydatetime()
end = idx.max().to_pydatetime() + timedelta(days=1)
...
expected = expected_rth_timestamps(symbol, tf, start, end)
```

`end = idx.max() + 1 day` is meant to "include the day of the last bar." But `expected_rth_timestamps` calls `trading_days(start, end)`, which (per CR-02) has the same-day exception. If `idx.min().date() == idx.max().date()` (a single-day DataFrame), `start.date() == idx.min().date()`, `end.date() = start.date() + 1`. So `trading_days` sees `end_d > start_d`, decrements to `start_d`, and queries `[start_d, start_d]` — correct shape. But because of the special-case-on-same-day in CR-02, this only works *because the input is two distinct dates*. Any direct caller of `expected_rth_timestamps(start=X, end=X)` gets the wrong shape.

**Why it matters:** Cross-coupled correctness. Fix CR-02 first; this gets simpler.

**Fix:** Bundled with CR-02 fix.

---

### WR-05: `RolloverDetector.annotate` mutates `df["rollover_seam"]` via a list of bool — silent dtype drift

**File:** `packages/trading-core/src/trading_core/calendars/rth.py:334-344`

**Issue:**

```python
df["rollover_seam"] = [
    is_rollover_seam(t.to_pydatetime() if isinstance(t, pd.Timestamp) else t)
    for t in ts
]
```

A list of Python `bool` assigned to a pandas column produces `object` dtype, not `bool`. Subsequent `data_hash` serialization of `rollover_seam` then includes Python object header bytes (via pyarrow) — see CR-01.

**Why it matters:** Feeds CR-01 reproducibility-hash fragility.

**Fix:**

```python
df["rollover_seam"] = pd.Series(
    [is_rollover_seam(...) for t in ts], index=df.index, dtype="bool"
)
```

---

### WR-06: `is_rollover_seam` uses ET-local date but the symbol may use a CME calendar — the "3rd-Friday" anchor needs an explicit timezone

**File:** `packages/trading-core/src/trading_core/calendars/rth.py:303-321`

**Issue:** `is_rollover_seam` converts `ts_utc` to ET-local date, then compares against `third_friday(year, month)`. The 3rd-Friday convention is documented as a calendar convention (CME equity-index roll date). The conversion to ET is *probably* right — but it's not justified anywhere in the docstring, and it's wrong for `SPY` (an NYSE ETF that doesn't roll). The function is supplied no instrument symbol, so it can't honor "only ES/MES roll." The `seed_bars` pipeline calls `RolloverDetector.annotate(df)` unconditionally — meaning SPY bars get a `rollover_seam=True` annotation around every 3rd Friday, which is meaningless and corrupts SPY's bar-level metadata.

**Why it matters:** SPY's `rollover_seam` column will carry phantom-true values on/around 3rd Fridays. Any downstream filter that skips seams will silently drop SPY bars on those days, corrupting backtests on the SPY-proxy ingest path (which is the entire reason Twelve Data ships in Phase 1).

**Fix:** Either gate the detector by symbol/asset class:

```python
class RolloverDetector:
    def annotate(self, df: pd.DataFrame, *, symbol: str | None = None) -> pd.DataFrame:
        inst = get(symbol) if symbol else None
        if inst is not None and inst.asset_class != "future":
            df = df.copy()
            df["rollover_seam"] = pd.Series(False, index=df.index, dtype="bool")
            return df
        # ... existing logic
```

And update `seed_bars.py` to pass `symbol=args.symbol`.

---

### WR-07: `config.Settings` `extra="ignore"` silently swallows typos in YAML / env vars

**File:** `packages/trading-core/src/trading_core/config.py:33-41`

**Issue:** `SettingsConfigDict(..., extra="ignore")` means a typo in `config/system.yaml` (e.g., `defualt_provider:`) is silently ignored. The default for that setting then quietly applies — operator thinks they configured Twelve Data; the system defaults to TradingView.

**Why it matters:** Production-config drift. A misconfigured provider in optimization runs corrupts the audit chain.

**Fix:** `extra="forbid"` for typed settings, with a clearly-documented escape hatch (a nested `Extras: dict[str, Any]` field if pluggable config is truly needed). The docstring claims this is "intentional" but cites no constraint that requires it.

---

### WR-08: `seed_bars.py` SUMMARY documents `DUCKDB_PATH` env override that is not wired

**File:** `scripts/seed_bars.py:136`, `packages/trading-core/src/trading_core/config.py:47`

**Issue:** `01-05-SUMMARY.md` line 36 says: "`argparse `--duckdb-path` override + DUCKDB_PATH env override on Settings — tests scope all DB writes to tmp_path so the operator's real DuckDB is never touched`". The code, however, only supports `--duckdb-path`; the env-variable override depends on pydantic-settings env handling, which uses field name `duckdb_path` (so the env var would be `DUCKDB_PATH` upper-cased). That part *is* wired by pydantic-settings convention.

But: the script's resolution `duckdb_path = getattr(args, "duckdb_path", None) or settings.duckdb_path` does the right thing. The risk is the *documented* contract (in SUMMARY) and the *actual* contract (auto-derived by pydantic-settings) are not asserted by any test in the integration suite. A `case_sensitive=True` config change later would silently break the env override.

**Why it matters:** Documentation/code drift in a security-sensitive path (test isolation: operator's production DuckDB).

**Fix:** Add `env_prefix=""` and `case_sensitive=False` explicitly to `SettingsConfigDict`, and add a unit test that asserts `DUCKDB_PATH=/tmp/x Settings().duckdb_path == Path("/tmp/x")`.

---

## Info

### IN-01: `TwelveDataSource` uses `await asyncio.sleep(9)` AFTER the request — wastes 9s on the last call

**File:** `packages/trading-core/src/trading_core/data/twelvedata.py:194-198`

**Issue:** The pacing sleep fires unconditionally after every fetch, including the final one before the CLI exits. For a single-window backfill this is 9 seconds of dead wall-clock on every run.

**Fix:** Move the pacing logic out of the adapter into the calling loop (e.g., `seed_bars` paginates and paces between iterations). Or pace *before* the next request, not after the current one — the first request can fire immediately.

---

### IN-02: Unreachable `yield` inside `TwelveDataSource.subscribe_bars` after `raise NotImplementedError`

**File:** `packages/trading-core/src/trading_core/data/twelvedata.py:249-257`

**Issue:** The `if False: yield` trick is real (Python's parser needs `yield` to classify the function as an async-generator) — but the comment claims it's for "mypy/Pyright" inference. Mypy's narrowing handles `AsyncIterator[Bar]` return annotations on async functions without the `if False: yield` hack. The trick exists because Python's `def`/`async def` parser uses `yield` presence as the signal, not the annotation. The comment is misleading.

**Fix:** Update the comment to: "Python classifies a function as an async-generator only if `yield` is syntactically present in the body. Without this unreachable yield, the function would be a coroutine returning an `AsyncIterator[Bar]`, not an async-generator — which violates the Protocol's `AsyncIterator[Bar]` return contract at call sites that consume it with `async for`."

---

### IN-03: `_construct_source` return type is `object` — defeats mypy narrowing

**File:** `scripts/seed_bars.py:90-100`

**Issue:** `def _construct_source(...) -> object:` then `await source.fetch_bars(...)` requires `# type: ignore[attr-defined]` (line 183). The `DataSource` Protocol exists exactly to type this; the function should return `DataSource`.

**Fix:** `def _construct_source(...) -> DataSource:` and import `DataSource` from `trading_core.data.protocols`.

---

### IN-04: `param_hash` uses `default=str` — silently lossy on `Path` objects

**File:** `packages/trading-core/src/trading_core/storage/runs.py:89-99`

**Issue:** `json.dumps(args, ..., default=str)` converts a `pathlib.Path` to its OS-native string. On Windows that's `"C:\\Users\\..\\..\\data\\duckdb\\trading.duckdb"`; on POSIX it would be `"/home/.../trading.duckdb"`. The same logical CLI args produce different hashes across platforms.

**Why it matters:** The reproducibility CI gate may run on Windows (operator) and Linux (future CI) — `param_hash` will diverge. Not a Phase 1 problem (no CI yet) but flag for Phase 8.

**Fix:** Normalize path-like values to `as_posix()` before hashing, or document that `param_hash` is platform-scoped (and Phase 8 CI runs on a single OS).

---

### IN-05: `apps/web/AGENTS.md` warning not enforced anywhere

**File:** `apps/web/AGENTS.md`, `apps/web/CLAUDE.md`

**Issue:** AGENTS.md says "This is NOT the Next.js you know. Read the relevant guide in `node_modules/next/dist/docs/` before writing any code." There is no lint rule, no pre-commit hook, and no test that enforces this. A Phase 3 contributor implementing the chart panel will likely miss this entirely.

**Fix:** Either remove the warning (and lean on TypeScript strict mode + eslint-config-next to catch breaking changes) or add a smoke test (`pnpm build` must pass in CI). Out of scope for v1 per CONTEXT.md, but flagging so it doesn't fall through the cracks.

---

### IN-06: `apps/web/package.json` pins dependencies inconsistently

**File:** `apps/web/package.json:11-29`

**Issue:** Dependencies are pinned with `^` for some (`@types/node`, `eslint`, `postcss`, `tailwindcss`) and exact versions for others (`@tanstack/react-query: 5`, `lightweight-charts: 5.2.0`, `next: 16.2.6`, `react: 19.2.4`, `zustand: 5`). The "trust the numbers" invariant in CLAUDE.md requires deterministic versions — `tailwindcss: 3.4` (no patch) and `react: 19.2.4` (exact) are correct; `eslint: ^9` is not. `pnpm-lock.yaml` locks transitives, so this is recoverable, but the package.json signals inconsistent intent.

**Fix:** Decide one policy (exact for prod, ^ for dev tooling) and apply uniformly. Or note in a comment that pnpm-lock.yaml is the authoritative pin and package.json's range syntax is informational.

---

## File-by-File Map

| File | Findings |
|---|---|
| `packages/trading-core/src/trading_core/calendars/rth.py` | CR-02, WR-04, WR-05, WR-06 |
| `packages/trading-core/src/trading_core/data/models.py` | CR-03 |
| `packages/trading-core/src/trading_core/data/tradingview.py` | WR-01, WR-02 |
| `packages/trading-core/src/trading_core/data/twelvedata.py` | CR-03, IN-01, IN-02 |
| `packages/trading-core/src/trading_core/events/bus.py` | WR-03 |
| `packages/trading-core/src/trading_core/storage/duckdb_store.py` | CR-03 |
| `packages/trading-core/src/trading_core/storage/runs.py` | CR-01, IN-04 |
| `packages/trading-core/src/trading_core/config.py` | WR-07 |
| `scripts/seed_bars.py` | CR-04, WR-08, IN-03 |
| `apps/web/AGENTS.md`, `package.json` | IN-05, IN-06 |
| All other reviewed files | Clean |

---

_Reviewed: 2026-05-15_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
