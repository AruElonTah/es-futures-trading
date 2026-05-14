# Pitfalls Research

**Domain:** Intraday ES Futures Backtest + Paper Trading System
**Researched:** 2026-05-14
**Confidence:** HIGH (canonical algotrading + prop-firm + Twelve Data / VectorBT / DuckDB known issues, verified against current docs and community sources)

> **Severity legend**
> - **Critical** — silently corrupts research conclusions; backtest "looks fine" but is wrong. These are the ones that make you trade real-equivalent capital on a lie.
> - **High** — visible failure that wastes days or destroys a prop-firm account.
> - **Medium** — annoying, recoverable, but routinely shipped by inexperienced systems.
> - **Low** — cosmetic / inconvenience.
>
> **Phase legend** (target roadmap shape — assumed but not yet fixed):
> - Phase 1: Data Layer (Twelve Data + DuckDB + RTH filtering + calendar)
> - Phase 2: Strategy Engine + Indicators
> - Phase 3: Backtester (VectorBT) + Fill Model
> - Phase 4: Optimization (grid + walk-forward)
> - Phase 5: Risk Manager + Signal Pipeline
> - Phase 6: Paper Executor + Audit Log
> - Phase 7: FastAPI + WebSocket Backend
> - Phase 8: Next.js UI + Lightweight Charts
> - Phase 9: TradingView MCP Integration
> - Phase 10: Operational Hardening (secrets, reproducibility, packaging)

---

## 1. Market Data Correctness

### MD-1: Continuous-contract rollover artifacts treated as real price moves

**Severity:** Critical
**What goes wrong:** Twelve Data's ES continuous series stitches front-month contracts together at rollover (typically the third Friday of the front quarter month, but Twelve Data does not document its exact rollover trigger). On a back-adjusted or non-adjusted series, the rollover day shows a gap of 5–25 ES points (carry/contango). A backtest reads that gap as a "huge move," ORB engulfs the prior range, and the strategy "wins" on a synthetic print that never tradable.
**Why it happens:** Developer assumes "ES=ES" and never inspects the seam. Most APIs (including Twelve Data) do not surface a rollover flag on the bar.
**Warning signs:**
- Outsized 1m bar around Thursday-before-third-Friday near 17:00 ET.
- Single-day P&L spike that disappears when you swap data vendor.
- ATR jumps anomalously on quarterly boundaries.
**Prevention:**
- At ingest, compute `abs(close[t] - close[t-1]) / close[t-1]` and flag any 1m bar > 0.5%; quarantine and review manually.
- Detect rollover dates explicitly (3rd Friday of Mar/Jun/Sep/Dec) and mark a `rollover_seam=True` column on the bars immediately before and after.
- Strategy must skip signal generation on rollover seam bars (or use `is_rollover` mask in entry conditions).
- Where possible, pull both the front contract symbol (e.g., `ESM26`) and continuous, and reconcile non-seam days to verify the stitch source.
- Document Twelve Data's adjustment method in `STACK.md`; if it's "non-adjusted," prefer adding a manual back-adjustment step before computing returns.
**Phase to address:** Phase 1 (Data Layer), with a regression test in Phase 3 (Backtester).

---

### MD-2: ETH bars leaking into the "RTH-only" dataset

**Severity:** Critical
**What goes wrong:** The pipeline says "RTH only" but the filter uses naive `datetime.hour` checks against local time, or filters on the wrong timezone. A handful of overnight bars sneak in, the ORB "opening range" is computed from 03:00 ET noise, and entries trigger off a fake range.
**Why it happens:** DST transitions, server-local-time confusion, Twelve Data sometimes returns timestamps in exchange time vs UTC depending on endpoint/parameter, and pandas `.tz_localize(None)` ambiguity.
**Warning signs:**
- ORB range width has long-tailed distribution with absurd outliers (e.g., 50+ ES points).
- Bars between 16:00–09:30 ET present in the "RTH" dataframe.
- Backtest equity curve has wins on dates without 09:30 ET prints in the visible candles.
**Prevention:**
- **Always-UTC discipline**: every bar stored in UTC with explicit `tz='UTC'`. Convert to `America/New_York` only for session-window comparison, never the other way.
- RTH filter as a tested function: `is_rth(ts_utc) -> bool` with unit tests for spring-forward, fall-back, and Friday close.
- Reject any inbound bar whose timestamp is not tz-aware; coerce, don't guess.
- Store the timezone-aware ET timestamp as a derived column for human inspection — never use it for math.
**Phase to address:** Phase 1 (Data Layer). Add a `tests/test_session_filter.py` covering both DST transitions before Phase 2.

---

### MD-3: CME equity-index holiday and half-day mishandling

**Severity:** High
**What goes wrong:** CME equity-index half-days (Day after Thanksgiving close ~13:00 ET, Christmas Eve close ~13:15 ET, Independence Day eve, etc.) and the holiday on July 3 when July 4 falls on a Saturday are treated as normal sessions. ORB triggers, but volume is 1/10th normal, slippage in reality is 4x; backtest assumes 16:00 close and "carries" a position into a non-existent session.
**Why it happens:** Developer hardcodes "9:30–16:00 ET, weekdays" or uses a generic `pandas_market_calendars.NYSE` calendar that doesn't match CME equity-index hours exactly.
**Warning signs:**
- Bars present on observed holidays (Good Friday, Thanksgiving).
- Trades held past actual session close.
- Trades on Black Friday with full-day P&L exposure.
**Prevention:**
- Use `pandas_market_calendars` with the `CMEGlobex_ES` or `CME_Equity` calendar, not `NYSE`. Verify each year's half-days against the [CME holiday calendar](https://www.cmegroup.com/trading-hours.html) at version bump time.
- Maintain a `cme_calendar.parquet` checked into the repo with explicit (date, session_open_utc, session_close_utc, is_half_day) rows for the full backtest window.
- Backtester refuses to execute on `is_half_day=True` unless `allow_half_day=True` is explicitly passed.
- Annual calendar refresh task scheduled (Q4 each year).
**Phase to address:** Phase 1 (Data Layer); enforcement in Phase 3 (Backtester).

---

### MD-4: Bar timestamp convention ambiguity (bar-open vs bar-close indexing)

**Severity:** Critical
**What goes wrong:** Twelve Data labels a 1-minute bar with its **open** time (the 09:30 bar covers 09:30:00 → 09:30:59). Code that treats it as bar-close (assuming the bar represents data from 09:29 → 09:30) generates signals one minute early and looks ahead 60 seconds. This is the single most common backtest-leakage source in intraday systems.
**Why it happens:** Different vendors use different conventions: Twelve Data and CME use bar-open; some legacy systems and TradingView's data feed return bar-close timestamps. Developer assumes without checking.
**Warning signs:**
- Backtest Sharpe > 4 with simple strategies.
- Strategy "knows" the 09:30 bar's high at 09:30:00 sharp.
- ORB range determined from a bar timestamped 09:30 that "should" be the first bar of the range — and the range-break entry fires on the same bar.
**Prevention:**
- Document the convention in `bars` table DDL as a column comment: `ts_utc -- bar OPEN time, UTC, inclusive`.
- At ingest, verify by intersecting against TradingView replay (`data_get_ohlcv` via MCP) for one known day and asserting equality.
- In the backtester, signal on bar `t` always uses data through `t-1`'s close; entries fill at `t+1`'s open at the earliest. Encode this in a single `next_bar_fill()` utility and forbid bar-`t` fills in the entry path.
- Add a unit test that constructs a synthetic series where a "perfect lookahead" strategy returns infinity, then verifies the framework prevents it.
**Phase to address:** Phase 1 (Data Layer) for the convention; Phase 3 (Backtester) for enforcement.

---

### MD-5: Twelve Data quirks — missing bars, throttling, holiday handling

**Severity:** High
**What goes wrong:**
- Twelve Data's free/Starter tier has rate limits (~8 req/min on free, ~55 on Starter). Bulk historical pulls silently truncate.
- Missing bars during thin sessions are returned as gaps (no row) — not as zero-volume bars. Code that does `df.iloc[i-1]` for "prior bar" then references the wrong time.
- Holiday days sometimes return empty responses; sometimes return the prior session's close repeated.
- Time alignment on first/last bar of the session occasionally off by one minute on DST transitions.
**Why it happens:** Twelve Data is a multi-asset aggregator; futures handling is less rigorous than its equities surface.
**Warning signs:**
- Backtest data has unexpected `NaN` gaps mid-session.
- `bar.next_ts - bar.ts != 60s` for many rows on a 1m series.
- API responses with `status: 'error'` or partial payloads.
**Prevention:**
- Wrap Twelve Data in a `TwelveDataClient` with retry-with-exponential-backoff on `429`, structured error parsing, and a request budget tracker.
- On ingest, reindex against expected session bars: `expected_index = pd.date_range(session_open, session_close, freq='1min', inclusive='left')` and assert no missing bars (or explicitly forward-fill volume=0 placeholder bars with a flag column).
- Reject empty responses on what should be a session day; raise loudly, don't silently store nothing.
- Snapshot raw API responses to `.cache/twelvedata/{date}/{symbol}.json` for forensic replay.
- Wire a daily "data quality" check: rowcount per session day, gap count, anomalous-volume count.
**Phase to address:** Phase 1 (Data Layer).

---

### MD-6: Daylight saving and "always-UTC" violations

**Severity:** Critical
**What goes wrong:** Code uses `datetime.now()` (naive, local) somewhere — typically in the live paper executor or in a "today's session" calculation. On the DST transition day, the session window is off by an hour, and the entire day's trades execute against the wrong RTH window or the executor flattens too early/late.
**Why it happens:** Python's stdlib timezone story is fragile; one naive `datetime` is enough to corrupt downstream math.
**Warning signs:**
- Trades on second-Sunday-of-March or first-Sunday-of-November look wrong by exactly 60 minutes.
- `df.index.tz` is `None` somewhere in the pipeline.
- Tests pass locally but break on a server with a different `TZ` env var.
**Prevention:**
- Project-wide rule: every `datetime` is `tz-aware` and UTC. Add a pre-commit lint (regex for `datetime.now()` without `tz=`).
- Define `ET = ZoneInfo("America/New_York")` and use it only at session-boundary computation and human display.
- Unit-test the session-window function on `2026-03-08` (spring forward), `2026-11-01` (fall back), and Friday-into-Monday transitions.
**Phase to address:** Phase 1 (Data Layer), enforced repo-wide.

---

## 2. Backtest Leakage

### BL-1: Same-bar signal generation and fill

**Severity:** Critical
**What goes wrong:** Signal computed using bar `t`'s close, then filled at bar `t`'s close (or open). In live trading, you cannot have the close before you can place the order. Backtest returns are inflated by exactly the average bar range times trade frequency.
**Why it happens:** VectorBT's `Portfolio.from_signals(close, entries, ...)` by default fills at the same bar's close when `entries[t]=True`. Developer doesn't override `from_signals(... open=open_px, price='nextbar')` or shift entries.
**Warning signs:**
- Sharpe > 3 on a simple strategy.
- Backtest beats forward-walk dramatically.
- Equity curve looks "too clean."
**Prevention:**
- Always use `Portfolio.from_signals(entries=entries.shift(1).fillna(False), price=open)` or use VectorBT's `price='nextbar'` flag. Document explicitly: **signal at t → fill at open of t+1**.
- Add a `noop_lookahead_test.py`: a strategy that uses `close.shift(-1)` should still result in a normal Sharpe after `next_bar_fill()` is applied. (If it produces infinite Sharpe, the fill model has a leak.)
- Wrap `from_signals` in a `safe_from_signals()` helper that enforces the shift and refuses unshifted entries.
**Phase to address:** Phase 3 (Backtester) — the first integration test of the engine.

---

### BL-2: ATR / indicator computed including the signal bar

**Severity:** Critical
**What goes wrong:** `atr = vbt.ATR.run(high, low, close, window=14).atr` followed by `stop = entry - atr * 2`. The `atr` at the signal bar already includes the signal bar's high/low — which uses information you wouldn't have until the bar closes (you decide to enter at open of t+1, but you sized your stop using the high of t+1).
**Why it happens:** Vectorized indicator libraries return values aligned to the bar that just closed; developer doesn't shift them when using them for an open-of-next-bar entry.
**Warning signs:**
- Stops are suspiciously close to actual reversal points.
- Win rate above 60% on a breakout strategy.
- Removing the ATR-shift line dramatically changes backtest outcome — that's the leak.
**Prevention:**
- Rule: **any indicator used for a t+1 decision must be `.shift(1)` aligned**.
- Wrap ATR/EMA/etc. in `Indicator.snapshot_at(t)` that returns the indicator value computed using only bars `[0..t-1]`.
- Add a leakage detector: for the signal bar, assert `indicator[t] == indicator_recomputed_from_bars_through_t_minus_1`.
**Phase to address:** Phase 2 (Indicators) and Phase 3 (Backtester).

---

### BL-3: Higher-timeframe filter look-ahead

**Severity:** Critical
**What goes wrong:** Daily 20-SMA trend filter resampled from 1-minute bars. At 09:30 ET, the "current day" daily bar already includes future minutes that haven't happened. ORB long signals get filtered correctly against tomorrow's daily SMA.
**Why it happens:** `df.resample('1D').mean()` aligns the daily bar to that day's date; developer uses `daily_sma[current_date]` instead of `daily_sma[current_date - 1]`.
**Warning signs:**
- Adding a trend filter improves backtest dramatically (filters are usually ~neutral; if they add 50% to Sharpe, it's leakage).
- Filter value changes intraday in the backtest log.
**Prevention:**
- Higher-timeframe filters always reference the **previous** completed period: `daily_sma.shift(1)` after resampling.
- Use VectorBT's `resample` with `closed='right', label='right'` and then shift, or build daily features from `bars[date < current_date]` only.
- Unit test: daily_filter at `09:30 ET on day D` must equal daily_filter at `15:59 ET on day D` (i.e., constant across day D).
**Phase to address:** Phase 2 (Indicators) — and any feature engineering layer.

---

### BL-4: Walk-forward fold contamination

**Severity:** Critical
**What goes wrong:**
- "Meta-overfitting": adjusting window sizes, fitness metrics, or parameter grids based on OOS performance.
- "Implicit fitting": picking the indicator set after eyeballing the OOS curve.
- Information bleed: indicator warmup uses bars from the OOS window (e.g., a 200-period EMA at the start of the OOS fold uses 199 IS bars + 1 OOS bar — that's fine — but if you re-fit the EMA period on the OOS fold's first 20 bars, it's contamination).
- Re-running the entire WFO after tweaking *anything*, then reporting the new result as "the OOS result."
**Why it happens:** OOS data is the most psychologically scarce resource; the temptation to peek and adjust is constant.
**Warning signs:**
- OOS Sharpe close to IS Sharpe (a real strategy degrades 30–60% out-of-sample).
- "I just want to tweak the window size and re-run" thought.
- Different optimization runs converge on the same parameters — possibly indicating the OOS has been seen many times.
**Prevention:**
- Lock the parameter grid, fitness function, IS/OOS window sizes, and fold count **before** running the first walk-forward. Commit them to git. Any change requires a fresh seeded random partition and a written ADR (architecture decision record).
- Track every WFO run in DuckDB with `git_sha`, `data_hash`, `param_grid_hash`, and `seed`. If the same `(strategy, param_grid_hash, data_hash)` has been run > N times, raise a warning.
- Reserve a "true holdout" period (last 6 months of data) that the system refuses to query until a single "go-live" command is run. Each query against the holdout is logged and rate-limited.
- Indicator warmup uses bars *before* the IS window starts; warmup never spans into the OOS fold.
**Phase to address:** Phase 4 (Optimization). The "true holdout" guard is the single most important Phase 4 invariant.

---

### BL-5: Indicator warmup bias

**Severity:** High
**What goes wrong:** Backtest starts on the same bar as the first available data; the 14-period ATR is `NaN`/zero for the first 14 bars, the strategy generates degenerate signals (entry with `stop=entry`), trades get sized infinitely or zero. Or, the metrics are computed including the warmup period where no real trading happened.
**Why it happens:** Developer forgets that ATR/EMA need N bars to stabilize.
**Warning signs:**
- First N days of equity curve are flat or wildly volatile.
- "Why am I trading 10,000 contracts on day 1?"
**Prevention:**
- Standard practice: warmup buffer of `max(indicator_period) * 2` bars before the first signal-eligible bar.
- Backtester refuses to emit signals while `any(indicator.is_warming_up)`.
- WFO folds: warmup bars come from the period *prior* to the IS window; the IS window itself has no warmup bias.
**Phase to address:** Phase 3 (Backtester).

---

### BL-6: Survivorship in the data — not applicable to ES (single instrument), but watch the cousin

**Severity:** Low (informational, not directly an ES risk)
**What goes wrong:** Generic algotrading advice warns about survivorship bias. ES is a single continuously-listed product so it's not at risk. Listed here only so the team doesn't worry about a non-issue.
**Phase to address:** N/A.

---

## 3. Fill Realism

### FR-1: Fill-at-bar-open optimism on the cash open

**Severity:** Critical (for ORB specifically)
**What goes wrong:** Backtester assumes signals at 09:45 ET fill at the 09:46 bar's open. In reality, ORB signals cluster at the moment of range breakout; everyone else's stop is at the same price; slippage in the first 30 minutes of cash open is 1–3 ticks even on ES, more on MES. Backtest underestimates cost by $5–$15 per trade.
**Why it happens:** Default fill model is naive `fill_price = open_of_next_bar`. No slippage model.
**Warning signs:**
- Backtest commission/slippage line item is 5% of gross P&L (real-world ORB is 15–30%).
- Per-trade expectancy looks > 1.5R.
**Prevention:**
- Slippage model: `slippage_ticks = base_slippage + (volume_z_score < threshold) * extra_ticks`. For ES, `base_slippage = 1 tick` ($12.50/contract for ES, $1.25 for MES). First 5 minutes of session: `base_slippage = 2 ticks`.
- Configure slippage per-strategy and per-session-phase; ORB breakouts in the first 15 minutes assume 1.5 ticks adverse on entry.
- Validate against TradingView replay: pick 10 historical ORB trades, replay them via MCP, eyeball the realistic fill, compare to backtest fill.
- Round-trip commission floor: $4.04/contract for MES on prop platforms — encode this as a non-overridable minimum.
**Phase to address:** Phase 3 (Backtester) fill model; revisited in Phase 6 (Paper Executor) when calibrating to live-quote fills.

---

### FR-2: Same-bar entry + stop ambiguity

**Severity:** Critical
**What goes wrong:** Entry at 4500 with stop at 4495. Next bar has open=4500, low=4493, high=4502, close=4501. Did the stop fire (low < stop) or did the entry fill and ride to close? VectorBT's `from_signals` makes assumptions; without explicit ordering rules, you can get an in-bar P&L of `close - entry = +1`, when in reality you'd have been stopped out for `-5`.
**Why it happens:** OHLC bars don't preserve the sequence of price moves within the bar; backtester must adopt a convention.
**Warning signs:**
- Trades survive bars where `low < stop` and `high > target` (both should not be hits in the same bar).
- Backtest expectancy assumes "best case" intrabar behavior.
**Prevention:**
- Adopt **worst-case** intrabar convention: if both stop and target lie inside `[low, high]`, assume stop hits first.
- For entry+stop in the same bar (entry at open, stop hit later in bar): allow it (entry first, then stop), with `exit_reason='intrabar_stop'` logged.
- Optionally drop to 1-minute bars for stop/target resolution even when the strategy operates on 5m bars (sub-bar resolution).
- VectorBT: use `Portfolio.from_orders` with explicit per-bar order sequences, or use `from_signals` with `sl_stop` / `tp_stop` parameters which apply worst-case logic by default. Verify on a synthetic test bar.
**Phase to address:** Phase 3 (Backtester) — must be decided before the first ORB backtest is run.

---

### FR-3: No partial-fill or liquidity model on MES

**Severity:** Medium
**What goes wrong:** Sizing 5 MES contracts at the open; backtest assumes all 5 fill at one price. Reality on MES at 09:30:00.001 is one or two ticks of slippage for size > 3.
**Why it happens:** Most retail backtesters ignore order-book depth.
**Warning signs:** N/A at MES sizes ≤ 2 contracts (prop-firm reality). Becomes relevant if scaling to ≥ 5 contracts.
**Prevention:**
- For v1, document the assumption: "fills assume contracts ≤ 3 absorb against book at top-of-book + 1 tick slippage."
- When sizing exceeds 3 MES, append `+ 0.5 tick / additional contract` slippage.
**Phase to address:** Phase 3 (Backtester) fill model — document; revisit if max_size grows.

---

### FR-4: Overnight gap leakage via "RTH only" misconfiguration

**Severity:** High
**What goes wrong:** Strategy is RTH-only, but the data stored happens to include Globex bars. A position opened at 15:50 ET that wasn't flattened by 16:00 ET "rides" the overnight session in the backtest, getting a 20-point favorable gap that would never have happened (because the EOD flatten was supposed to fire).
**Why it happens:** Two failures conspire: (a) EOD flatten not enforced (see RM-4), (b) ETH bars accidentally present in the dataset (see MD-2).
**Warning signs:**
- Late-session trades have outsized average return.
- Holding period > 6.5 hours on a single trade.
**Prevention:**
- Backtester enforces a hard `force_flat_at = session_close - 1min` rule; any open position at session close is closed at `bar.close - slippage`.
- Verify post-flatten there are no rows with `position != 0` outside RTH.
**Phase to address:** Phase 3 (Backtester) and Phase 5 (Risk Manager).

---

## 4. Strategy Logic (ORB-Specific)

### SL-1: RTH vs Globex opening range confusion

**Severity:** Critical
**What goes wrong:** "Opening range" is computed from the first 15 minutes of available bars. If Globex bars leaked in, the "opening range" is the 18:00 ET Sunday range — 1500% wrong. Or, the range is correctly computed for RTH but indexed against Globex bar timestamps and the breakout check fires off the wrong reference.
**Why it happens:** ORB definition is "first N minutes of the cash session." Code defines it as "first N bars of the dataframe," which equals the cash session only if (a) the dataset is RTH-filtered and (b) the first bar is exactly the 09:30 ET bar.
**Warning signs:**
- ORB range high/low don't match what TradingView shows when you replay 09:30–09:45.
- Range widths in the 50+ ES point range routinely.
**Prevention:**
- Define ORB explicitly as: `range = bars[(ts_et.time >= 09:30) & (ts_et.time < 09:30 + N_minutes)]`.
- Unit test: synthetic dataset where Globex bars are present; ORB function must ignore them.
- Validate against TradingView MCP: `data_get_ohlcv` for 09:30–09:45 of a known day; compare ORB high/low.
**Phase to address:** Phase 2 (Strategy Engine).

---

### SL-2: Range-too-narrow / range-too-wide trap

**Severity:** High
**What goes wrong:** On low-volatility days the ORB range is 3 ES points wide; the strategy fires immediately on the first 1-tick break, gets whipsawed all morning, dies of slippage and commissions. On high-volatility (news) days the range is 40 points wide; by the time it breaks it's already exhausted.
**Why it happens:** Single-set parameters with no volatility-aware gate.
**Warning signs:**
- High trade count on low-ATR days.
- Win rate cliff on FOMC / NFP days.
**Prevention:**
- Acceptance filter: `range_width / atr_daily ∈ [0.3, 1.5]`. Below 0.3, skip the day. Above 1.5, skip.
- Add an absolute floor in ticks (e.g., minimum 4 ES points / 16 ticks).
- Track "no-trade days" — the strategy must be willing to do nothing.
**Phase to address:** Phase 2 (Strategy Engine).

---

### SL-3: False breakout / no confirmation

**Severity:** High
**What goes wrong:** Entry triggers on the first tick that breaks the range high. Half of these are wicks back into the range. Win rate ends up 30% with bad R/R.
**Why it happens:** Naive "if high > range_high: enter" without confirmation.
**Warning signs:** Win rate < 35%; many trades stopped within the same bar.
**Prevention:**
- Require **bar close** outside the range, not intra-bar wick.
- Optional: require breakout volume > 1.2 × range-period average volume.
- Optional: require breakout bar's body (close - open) > 0.5 × ATR.
- Make these orthogonal toggles in the parameter grid so optimization quantifies their impact.
**Phase to address:** Phase 2 (Strategy Engine) — implement as ORB v2 immediately after v1 baseline.

---

### SL-4: Re-entry after stop-out (multiple breakouts per day)

**Severity:** Medium
**What goes wrong:** Strategy enters, gets stopped, re-enters on the next breakout, stops again. Daily loss compounds.
**Why it happens:** No `max_entries_per_day` cap.
**Warning signs:** Single-day P&L < -2R; same day shows 3+ trades.
**Prevention:**
- Hard cap: `max_entries_per_day = 1` (or 2) for ORB. Once stopped, no more entries today regardless of further breakouts.
- Combine with risk-manager daily-loss circuit breaker.
**Phase to address:** Phase 2 (Strategy Engine) + Phase 5 (Risk Manager).

---

### SL-5: Late-session entries

**Severity:** Medium
**What goes wrong:** ORB breakout fires at 15:30 ET; trade has 25 minutes before forced EOD flatten. Insufficient time for the strategy's edge to play out.
**Why it happens:** No time-of-day cutoff.
**Warning signs:** Trades after 14:00 ET have negative expectancy.
**Prevention:**
- Configurable `latest_entry_time` (default 11:30 ET for ORB on ES — see Tradethatswing source).
- Strategy ignores breakouts after this time.
**Phase to address:** Phase 2 (Strategy Engine).

---

## 5. Optimization

### OPT-1: Overfitting via too-fine parameter grids

**Severity:** Critical
**What goes wrong:** Grid: `ORB minutes ∈ [5, 6, 7, 8, ..., 30]`, `ATR mult ∈ [1.0, 1.1, 1.2, ..., 3.0]`. 26 × 21 = 546 combos × 4 other dims = 50k combos. The "best" combo wins by luck — it's the right tail of a noise distribution.
**Why it happens:** "More resolution = better optimization" intuition is wrong for noisy financial data.
**Warning signs:**
- Optimization "winner" lies between two losers on the parameter landscape (un-robust peak).
- 2D heatmap of param-1 vs param-2 looks like random noise rather than a smooth surface.
- Top-1 and top-50 results differ wildly in parameter values.
**Prevention:**
- Coarse grids first: `ORB minutes ∈ [5, 10, 15, 20, 30]`, `ATR mult ∈ [1.5, 2.0, 2.5, 3.0]`. ~5×4 = 20 combos.
- Only refine around regions of stable performance — and even then, require neighbors to also perform well.
- Multiple-testing correction: divide significance threshold by number of combos. With 50k combos, a "significant" Sharpe must be enormous.
- Rank by **OOS robustness** (e.g., mean OOS Sharpe across folds, penalized by variance), not raw IS Sharpe.
**Phase to address:** Phase 4 (Optimization).

---

### OPT-2: Single-period bias

**Severity:** Critical
**What goes wrong:** Backtest on 2023 only; "found a great strategy"; deploy; 2024 regime change destroys it.
**Why it happens:** Convenience — recent data is fresh and "feels representative."
**Warning signs:**
- All testing on a single year.
- Equity curve is monotonic.
**Prevention:**
- Minimum 5-year backtest window (covers post-2020 vol regimes: 2020 spike, 2021 mean reversion, 2022 trend, 2023 chop, 2024 rally, 2025 mix).
- Walk-forward with at least 6 OOS folds.
- Regime tagging: tag trades by `vix_quintile`, `realized_vol_quintile`. A robust strategy works across at least 3 regimes.
**Phase to address:** Phase 4 (Optimization).

---

### OPT-3: Optimizing for return instead of robustness

**Severity:** High
**What goes wrong:** Sort by total return; pick top-1; that's the strategy. In reality, top-1 is often a single fluke trade away from being top-1000.
**Why it happens:** "Maximize PnL" is intuitive but mathematically the wrong objective in a noisy domain.
**Warning signs:**
- "Winner" has a single trade > 20% of total P&L.
- Profit factor > 3 with < 50 trades.
- Top-1 has dramatically different params from top-2 through top-10.
**Prevention:**
- Primary metric: **OOS Sharpe** (or Sortino) on aggregated OOS folds.
- Secondary filter: max drawdown < threshold, min trade count, profit factor in [1.3, 3.0] (suspiciously high = overfit).
- Use **plateau detection**: pick the center of a flat region in the param landscape, not the peak.
- Bootstrap trade sequences (resample with replacement) and require the 5th-percentile Sharpe to remain positive.
**Phase to address:** Phase 4 (Optimization).

---

### OPT-4: In-sample bleed via "objective shopping"

**Severity:** Critical
**What goes wrong:** Run WFO, OOS Sharpe is 0.4. Try Sortino — OOS Sortino is 0.9. Report Sortino. Or, change the daily-loss limit, re-run, pick the favorable result.
**Why it happens:** Each metric is correlated; testing many "objectives" against the same OOS data is the same as testing many strategies — it's still overfitting.
**Warning signs:**
- WFO has been re-run > 5 times on the same data window with cosmetic changes.
- Reported metric changed between iterations.
**Prevention:**
- Pre-commit to the objective function in writing before the first WFO run.
- Track every WFO run with the full config hash; refuse to publish a result from a config that has been "tweaked from a previous run on the same holdout."
- Use a deterministic seed and log it.
**Phase to address:** Phase 4 (Optimization).

---

### OPT-5: Walk-forward window selection bias

**Severity:** High
**What goes wrong:** Trying `(IS=6mo, OOS=1mo)` then `(IS=12mo, OOS=3mo)` then `(IS=24mo, OOS=6mo)` until OOS looks good. That's window-shopping, which is overfitting.
**Why it happens:** WFO has many knobs; each knob exercised against the same data leaks.
**Prevention:** Lock IS/OOS windows in an ADR before the first run. Justify the choice on **strategy half-life** logic, not on result quality.
**Phase to address:** Phase 4 (Optimization).

---

## 6. Risk Manager

### RM-1: Sizing math ignoring tick value (ES vs MES)

**Severity:** Critical
**What goes wrong:** `contracts = floor(risk_$ / stop_pts)` — missing the `* tick_value` term. On ES ($50/pt), a 5-point stop at $1000 risk gives `1000/5 = 200 contracts`, which would be $50k of risk. On MES ($5/pt), same formula gives 200 contracts, which is $5k risk — 5× the allowance. Account dies on first trade.
**Why it happens:** "ES" and "MES" used interchangeably in early dev; tick value not surfaced as a first-class constant.
**Warning signs:** Sizing returns > 5 MES contracts on a $50k prop account with 2% risk.
**Prevention:**
- Single source of truth: `instruments.py` with `ES.point_value = 50.0`, `MES.point_value = 5.0`, `ES.tick_value = 12.50`, `MES.tick_value = 1.25`, `ES.tick_size = 0.25`.
- Sizing function signature: `size(risk_dollars, stop_distance_pts, instrument: Instrument) -> int`. No bare floats.
- Unit tests: `size(1000, 5, MES) == 40`; `size(1000, 5, ES) == 4`.
- Integration assertion: max sized contracts at default config never exceeds prop-firm `max_contracts` limit.
**Phase to address:** Phase 5 (Risk Manager) — the very first commit of that phase.

---

### RM-2: Prop-firm trailing drawdown confused with static drawdown

**Severity:** Critical
**What goes wrong:** Apex's intraday trailing drawdown follows your **unrealized high-water mark** in real-time — touching $52,500 unrealized on a $50k account locks the floor at $50k. Most backtesters track static drawdown from start-of-day or from realized P&L only. System reports "we never hit DD"; reality says "you blew the account at 11:14 ET when you were up $2.6k unrealized and then gave back $500."
**Why it happens:** Trailing-vs-static rules are nuanced and vary across firms (Apex EOD vs Apex Intraday vs Topstep EOD). Code defaults to whatever's simpler.
**Warning signs:**
- "We backtested at $50k DD survival" while strategy has high intraday unrealized swings.
- Backtest never reports a DD breach but live paper account does.
**Prevention:**
- Encode DD model as an enum: `DrawdownModel.STATIC | TRAILING_EOD | TRAILING_INTRADAY`. Default for Apex sims: `TRAILING_INTRADAY`.
- For trailing intraday: track `equity_high_water_mark = max(equity_hwm, current_unrealized_equity)` every bar; floor = `hwm - $2000` (for the $50k account). Floor never moves down.
- For trailing EOD: update HWM only on `eod_realized_equity`.
- Track three side-by-side numbers in the audit log: `static_dd`, `eod_dd`, `intraday_dd`. Surface all three in the UI so misconfiguration is visible.
- For the $50k Apex account: the trailing DD is typically $2,500 (verify against current Apex evaluation rules at the time of implementation; rules change).
**Phase to address:** Phase 5 (Risk Manager) — explicit unit tests for each DD variant.

---

### RM-3: Daily-loss check after fill instead of before

**Severity:** Critical
**What goes wrong:** A trade is filled, P&L is updated, daily-loss check runs after, says "you're over the limit, halt trading." But the trade that breached is already on the books. Worse: a trade that *would* breach the limit fires the fill and only then is rejected — but the broker (live or paper) has the position.
**Why it happens:** Naive event order: `signal → fill → update_pnl → check_risk`.
**Warning signs:**
- Audit log shows a trade with `daily_pnl_after = -$2100` on a $2k DD account.
- Halt flag asserted *after* a trade that pushed past the floor.
**Prevention:**
- Pre-trade check: `if current_daily_pnl - worst_case_loss_of_proposed_trade < daily_loss_floor: reject`. `worst_case_loss = (entry - stop) * size * tick_value + slippage_estimate`.
- Risk manager owns the "approve / reject" decision in front of the executor; signal pipeline cannot bypass it.
- Test: synthetic scenario where daily P&L is -$1900 and proposed trade has $200 worst-case — must be rejected.
**Phase to address:** Phase 5 (Risk Manager).

---

### RM-4: EOD flatten-all not enforced

**Severity:** Critical (prop-firm violation)
**What goes wrong:** Position held past 15:59 ET (or whatever the prop firm's flat-by time is — Apex requires flat by 16:59 ET, Topstep by 15:10 ET on equity index). Account flagged for rule violation, evaluation reset.
**Why it happens:** EOD logic implemented as a strategy concern instead of a system-wide invariant.
**Warning signs:** Any `position_at(t_flat_required) != 0` in the audit log.
**Prevention:**
- Risk manager runs an `eod_sweep` task on a wall-clock schedule (independent of bar arrival). At `flat_by_time - 60s`, force-close all open positions.
- Backtester applies the same rule: positions open at `flat_by_time` are exited at `bar.close`.
- Assertion: at session_end+1bar, `sum(position_sizes) == 0`. Failing this assertion fails the test suite.
**Phase to address:** Phase 5 (Risk Manager) + Phase 6 (Paper Executor).

---

### RM-5: "Max contracts" / reset windows not modeled

**Severity:** High
**What goes wrong:** Apex limits max contracts per account size — $50k account is typically 5 minis / 50 micros during evaluation, dropping to "scaling rules" on funded. Strategy sizes to 8 MES; rule violated.
**Why it happens:** Static config doesn't map to firm-specific contract caps.
**Prevention:**
- `RiskConfig` has explicit `max_contracts: int`, `max_contracts_during_news: int`, `scaling_threshold_pnl: float`.
- Per Apex's evaluation rules (verify at implementation time), modeling: `max_micros = 10 × account_size_in_50k_units`.
**Phase to address:** Phase 5 (Risk Manager).

---

### RM-6: HWM (high-water mark) not persistent across restart

**Severity:** Critical (silent prop violation)
**What goes wrong:** Process crashes at 13:00 ET with equity at $52,000 (HWM locked at $52k → floor at $50k). Restart at 13:30; HWM re-initialized to $50k account starting balance; floor reset to $48k. Trader thinks they have $4k of cushion; actually has $2k.
**Why it happens:** State-in-memory only.
**Prevention:**
- HWM and DD floor persisted to DuckDB on every update.
- On startup, risk manager loads HWM from DuckDB; refuses to start if no HWM row exists for today's session (must be explicitly initialized).
**Phase to address:** Phase 5 (Risk Manager).

---

## 7. Signal Pipeline

### SP-1: Duplicate signals on bar reprocessing

**Severity:** High
**What goes wrong:** A bar arrives late or is corrected; strategy re-fires on it; the audit log gets two entries; the executor places two orders.
**Why it happens:** Bar handlers idempotency not enforced.
**Warning signs:** Two `signal_id`s with identical `(strategy_id, bar_ts, side)`.
**Prevention:**
- `signal_id = hash(strategy_id, bar_ts, side, entry_price, stop_price)`. Executor refuses to act on duplicate `signal_id`.
- Bar ingest is idempotent (upsert by `(symbol, ts_utc)`).
**Phase to address:** Phase 6 (Paper Executor) + Phase 1 (Data Layer).

---

### SP-2: Race between signal and risk check

**Severity:** High
**What goes wrong:** Signal emitted on bar close; meanwhile, a prior trade's exit fill arrives and updates P&L. Risk check uses pre-exit P&L (no longer accurate). Trade approved on stale risk state.
**Why it happens:** Async event bus without serialization on the risk-manager queue.
**Prevention:**
- Single-threaded risk-manager event loop (asyncio task with a single queue). All P&L updates and signal approvals serialize through it.
- Each risk check captures `risk_state_version`; reject if state has advanced since the signal was created (force re-check).
**Phase to address:** Phase 5 (Risk Manager) + Phase 6 (Paper Executor).

---

### SP-3: Audit log doesn't survive a restart

**Severity:** High
**What goes wrong:** Audit log is an in-memory list flushed periodically. Process crashes mid-session; the last 30 minutes of signals/decisions/fills are gone. Cannot reconstruct what happened.
**Why it happens:** "I'll add persistence later."
**Prevention:**
- Audit log writes synchronously to DuckDB on every event (signal, risk decision, fill, exit, position update). DuckDB single-process write is fine.
- CSV mirror written in append mode with `flush()` after every line, for human inspection.
- Test: kill -9 the process mid-trade; assert that the last decision before kill is in DuckDB.
**Phase to address:** Phase 6 (Paper Executor) — audit-log persistence is the first deliverable of that phase.

---

### SP-4: No replay-from-log mechanism

**Severity:** Medium (becomes High if production runs are not reproducible)
**What goes wrong:** Something went wrong yesterday; cannot reconstruct the bar-by-bar decision tree. Cannot test a hotfix against the historical scenario.
**Why it happens:** Audit log persisted, but no consumer that re-plays it.
**Prevention:**
- Build a `Replay` command: given a date, re-feed bars from DuckDB through the strategy + risk + executor pipeline in deterministic order. Output must byte-match the original audit log (modulo wall-clock timestamps).
- Determinism requires fixed seeds, fixed parameters at the time of the run (commit hash in audit log).
**Phase to address:** Phase 6 (Paper Executor), validated in Phase 10 (Operational).

---

## 8. UI / Web App

### UI-1: Bloomberg-density without keyboard navigation

**Severity:** High (this is a project core-value mismatch)
**What goes wrong:** Bloomberg density done with mouse-only nav becomes overwhelming — 12 panels of dense data and no way to focus a single one without grabbing the cursor.
**Why it happens:** Density is treated as a visual goal, not an interaction goal.
**Prevention:**
- Every panel keyboard-focusable (`Tab` cycles, `Esc` returns to grid).
- Command palette (`Ctrl+K`) for all actions: change symbol, toggle strategy, jump to date, open backtest config.
- Single-key shortcuts for common actions: `c` for chart, `b` for blotter, `p` for P&L, `o` for optimization.
- No action should require > 2 mouse clicks if a keyboard shortcut exists.
**Phase to address:** Phase 8 (Next.js UI) — keyboard nav is a Phase 8 acceptance criterion, not an afterthought.

---

### UI-2: WebSocket reconnect storms

**Severity:** High
**What goes wrong:** Connection drops; client reconnects immediately; server is briefly slow; client retries; cascade. Or worse: the reconnect re-subscribes to all topics and re-emits a snapshot, doubling positions on the UI.
**Why it happens:** Naive reconnect without backoff or deduplication.
**Prevention:**
- Exponential backoff with jitter: `delay = min(30s, base * 2^attempts) * uniform(0.5, 1.5)`.
- Server: snapshot-on-subscribe; client treats snapshot as authoritative replacement, not append.
- Sequence numbers on every message; client detects gaps and requests snapshot resync, not replay.
- Max reconnect attempts before alerting user; no silent forever-retry.
**Phase to address:** Phase 7 (FastAPI Backend) + Phase 8 (UI).

---

### UI-3: P&L display lags real state

**Severity:** High (operator misjudges position)
**What goes wrong:** UI shows P&L computed from the last received bar (e.g., 5 minutes old); operator thinks they're up $400; actually they're down $100. Decision made on stale data.
**Why it happens:** P&L pushed on bar-close events only.
**Prevention:**
- UI subscribes to a `position_state_v2` channel that pushes on every state change (fill, partial fill, mark-to-market update on each tick or each 5-second poll).
- Display "last update: 14:32:05 (2s ago)" prominently on every P&L widget; stale = > 10s = visual warning.
- Backend computes unrealized P&L on demand from latest quote, not from stale bar close.
**Phase to address:** Phase 7 + Phase 8.

---

### UI-4: Chart timezone drift between Lightweight Charts and backend

**Severity:** Critical
**What goes wrong:** Backend sends UTC timestamps; Lightweight Charts (default) treats them as the user's local timezone for display. ORB box "drawn" at 09:30 ET ends up rendered at 14:30 on a UTC-rendering chart. User questions the system's correctness.
**Why it happens:** Lightweight Charts' time scaling assumes UTC seconds since epoch but displays in the browser's local TZ unless configured.
**Prevention:**
- Backend always sends `time = unix_seconds_utc`.
- Lightweight Charts options: `localization.timeFormatter` and `timeScale.tickMarkFormatter` configured to render in `America/New_York` regardless of browser locale.
- Visual smoke test: 09:30 ET vertical line on chart should align with the candle whose backend `ts_utc` corresponds to 09:30 ET (14:30 UTC during EST, 13:30 UTC during EDT).
- Same rule for overlays: ORB box, signal markers, stop/target lines.
**Phase to address:** Phase 8 (UI) — first chart-render acceptance criterion.

---

### UI-5: Order blotter & equity curve race

**Severity:** Medium
**What goes wrong:** Trade closes; equity curve updates from one channel; blotter updates from another; for ~1 second the blotter shows the open position and the equity curve shows the realized P&L from the close. Operator sees impossible state.
**Why it happens:** Independent WebSocket channels with independent latencies.
**Prevention:**
- Atomic state broadcasts: single `state_update` message contains `{positions, equity, last_fills}` — UI applies all-or-nothing.
- Or: include a monotonic `state_version`; UI buffers messages and applies in order.
**Phase to address:** Phase 7 (FastAPI Backend).

---

## 9. TradingView MCP Integration

### TV-1: Chart drawings accumulate forever

**Severity:** Medium (degrades MCP performance over time)
**What goes wrong:** Each ORB box, entry arrow, stop line is `draw_shape`'d onto the chart but never cleaned up. After a week of paper trading, the chart has thousands of overlay shapes; TradingView gets sluggish; MCP calls slow.
**Why it happens:** Easy to draw; cleanup is an afterthought.
**Prevention:**
- Every shape created via MCP returns an `entity_id`; store in a `tv_overlay_registry` table keyed by `(session_date, kind)`.
- Daily cleanup task on session start: list all overlays with `session_date < today - 5 days` and delete via MCP.
- Manual `tv:clear-overlays` command.
- Cap: max 200 overlays at any time; if exceeded, oldest auto-removed.
**Phase to address:** Phase 9 (TradingView MCP Integration).

---

### TV-2: TV treated as source of truth instead of Python

**Severity:** Critical (data divergence corrupts research)
**What goes wrong:** Operator uses TradingView to look at a chart; backtest reads from Twelve Data; they disagree (TV uses CME data, Twelve Data may use a different vendor's adjustment). Decisions made looking at TV chart that the backtester can never reproduce.
**Why it happens:** TV is what the operator sees; psychologically becomes authoritative.
**Prevention:**
- Document explicitly: **Python (Twelve Data) is canonical; TV is a visualization peer.**
- Validation procedure: at ingest time, for each new day, pull `data_get_ohlcv` from TV for the same RTH window and compare bar-by-bar against Twelve Data. Log discrepancies. Threshold for raising an alert: > 0.05% price difference on any bar.
- Reports / backtest outputs always cite the Twelve Data hash / version; TV state is only "advisory."
- If TV and Twelve Data diverge persistently, that's a Phase 1 data-source decision point — not something to paper over.
**Phase to address:** Phase 9 (TradingView MCP Integration) + Phase 1 (Data Layer).

---

### TV-3: Replay state assumptions broken by user

**Severity:** Medium
**What goes wrong:** System invokes `replay_start` at 2026-04-15 09:30 ET; user scrolls the chart manually; the next `replay_step` starts from a different point; backtest seeded from "replay state" is now wrong.
**Why it happens:** TV chart is a shared resource; user has full control even while system is using it.
**Prevention:**
- Before each replay-fed action, call `replay_status` to verify the current replay position matches what we expect. If not, abort or re-seek.
- Lock convention: when system is mid-operation, set an on-chart visible "SYSTEM ACTIVE — DO NOT MOVE" label via `draw_shape`.
- Never assume replay state is what we left it; always read it.
**Phase to address:** Phase 9.

---

### TV-4: TV indicator names / values mismatch with Python indicators

**Severity:** Medium
**What goes wrong:** Python computes ATR(14) using Wilder's smoothing; TV's ATR is by default RMA-based; values differ by 5–10%. Drawn stop on TV doesn't match the stop the system actually uses.
**Why it happens:** Indicator math is not standardized across libraries.
**Prevention:**
- Use TV's exact formulas when computing in Python (RMA for ATR, etc.).
- Validation: pull `data_get_study_values` for ATR on a sample day; assert agreement with Python's ATR within rounding tolerance.
- Make this part of the indicator unit tests.
**Phase to address:** Phase 2 (Indicators) — validate against TV early so deviations don't accumulate.

---

## 10. Operational

### OP-1: Twelve Data API key committed to git

**Severity:** Critical (security + free-tier abuse)
**What goes wrong:** API key in code or in a non-gitignored `.env`. Pushed to GitHub. Public scrapers harvest it within hours; rate limit gets burned; possible billing exposure if the key is on Starter tier with billing attached.
**Why it happens:** `.env.example` versioned correctly, but `.env` not gitignored, or hardcoded for a quick test.
**Prevention:**
- Project-root `.gitignore` includes `.env`, `.env.*`, `*.key`, `secrets.toml`, `.venv/`, `__pycache__/`, `*.duckdb`, `*.duckdb.wal`, `data/`, `.cache/`.
- `.env.example` committed with placeholder values only.
- Pre-commit hook: `gitleaks` or `detect-secrets` scanning every staged file.
- API keys loaded via `pydantic-settings` from environment; never accept hardcoded fallbacks.
- Audit: `git log -p -S "TWELVEDATA_API_KEY"` returns nothing committed.
**Phase to address:** Phase 1 (Data Layer) — `.gitignore` + secret-loading is the very first commit, before any API code.

---

### OP-2: Irreproducible backtests (no seed, no data hash)

**Severity:** Critical
**What goes wrong:** Backtest reports "Sharpe 1.4." Re-run the same backtest tomorrow on the same data; get Sharpe 1.7. (Random tiebreaker in fill ordering, random shuffling in cross-validation, or just data has been updated.)
**Why it happens:** RNG not seeded; data immutability not enforced.
**Warning signs:** Same config + same data + same code → different output.
**Prevention:**
- Every backtest run logs: `git_sha`, `data_hash` (`sha256` of the parquet bars used), `param_hash`, `seed`, `wall_time_start_utc`. All saved to a `runs` table in DuckDB.
- `np.random.seed`, `random.seed`, and any framework-specific seeds set from a single config entry.
- Data files are immutable post-ingest; updates create a new parquet partition with a new hash, never mutate.
- Run identity = `hash(git_sha, data_hash, param_hash, seed)`. Same identity → must produce same output. Add a CI smoke test.
**Phase to address:** Phase 3 (Backtester) + Phase 10 (Operational).

---

### OP-3: DuckDB file locked by another process

**Severity:** High (Windows-specific friction)
**What goes wrong:** UI backend has a write connection to `data.duckdb`. Operator opens DBeaver or runs an ad-hoc python script that also opens a write connection. Second process throws `IO Error: Could not set lock on file: ... is held by ... (PID xxxx)`. DuckDB does **not** support multi-process writes.
**Why it happens:** Operator habit + DuckDB's intentional concurrency model (single writer per file).
**Prevention:**
- Architecture rule: exactly **one** process holds the write connection — the FastAPI backend. Everything else (notebooks, ad-hoc scripts, the optimizer worker) opens `read_only=True`.
- For multi-process writes (e.g., parallel WFO workers): each worker writes to its own per-worker parquet file under `runs/wfo_{run_id}/worker_{n}.parquet`, then the orchestrator does a single-process aggregation pass into the main DuckDB.
- Document this in `STACK.md` and surface in onboarding.
- Wrap connection acquisition with timeout + clear error message: "DuckDB file locked by PID X. Close that process or use read_only=True."
**Phase to address:** Phase 1 (Data Layer) — establish the single-writer convention before any worker process is added.

---

### OP-4: Windows path / encoding bugs

**Severity:** Medium
**What goes wrong:**
- Hardcoded forward slashes break on Windows.
- Long-path issues (`>260` chars) when nesting `.planning/research/...` under `C:\Users\Admin\Desktop\Day Trading\`.
- File handles inherited by subprocesses (Windows) keep DuckDB files locked even after `conn.close()`.
- Unicode in audit logs (em-dashes, emoji) breaks `open(..., 'w')` with default `cp1252` encoding.
**Why it happens:** Most Python algotrading content is Unix-centric.
**Prevention:**
- All paths via `pathlib.Path`, never string concatenation.
- File opens always specify `encoding='utf-8'`.
- Run `chcp 65001` in PowerShell setup; document in onboarding.
- Test suite runs on Windows in CI (not just Linux).
- Avoid spaces in repo path — but the project lives at `C:\Users\Admin\Desktop\Day Trading\` which **has a space**, so every shell invocation must quote paths.
**Phase to address:** Phase 1 (Data Layer) — set up cross-platform path handling early.

---

### OP-5: Twelve Data rate-limit silent truncation

**Severity:** High
**What goes wrong:** Bulk historical pull at startup; ~10 of 30 requested days return partial data because the rate limit triggers; the pipeline silently stores the partial set; tomorrow's gap-detection misses the truncation because "the days exist."
**Why it happens:** API doesn't always raise; sometimes just returns fewer bars.
**Prevention:**
- Per-day bar-count validator: each RTH session must have exactly `expected_bars` (390 for 1m, 78 for 5m, 26 for 15m, minus half-days). If short, mark `quality='incomplete'` and force re-fetch on next run.
- Budget tracker enforces request pacing client-side; never let the server be the rate-limiter.
- Log every API call's request/response into `.cache/twelvedata/api_calls.jsonl` for forensic review.
**Phase to address:** Phase 1 (Data Layer).

---

### OP-6: No CI / no test gate on backtest-sensitive changes

**Severity:** High
**What goes wrong:** A refactor to the fill model changes a number; backtest results shift; nobody notices until a real strategy decision has been made on the new (different) numbers.
**Why it happens:** Trading code looks like "research code" — undertested by industry default.
**Prevention:**
- Reference backtest (e.g., ORB on 2024-01–2024-06 with fixed params) checked into CI. If `mean_return`, `sharpe`, or `max_dd` shift by more than 1%, build fails — and a human must explicitly bless the change with a commit note.
- Tag every commit with whether it's a "behavior-changing" or "behavior-preserving" change.
- Snapshot test of equity curve: stored as a parquet; CI compares row-by-row.
**Phase to address:** Phase 10 (Operational), but the reference-backtest scaffold lands in Phase 3.

---

### OP-7: Single TradingView instance, single chart — concurrent-access conflict

**Severity:** Medium
**What goes wrong:** The Python system controls the chart via MCP. Operator wants to use the same chart for manual analysis. They fight over symbol/timeframe state.
**Why it happens:** TV Desktop is a single-pane app from the system's POV.
**Prevention:**
- "System mode" vs "manual mode" toggle in the UI. In manual mode, MCP calls that change chart state are paused; only reads remain.
- Use a secondary TV layout / tab for system overlays so primary chart stays user-controlled.
**Phase to address:** Phase 9.

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Hardcode tick value as `50.0` in sizing code | Saves writing `instruments.py` | First MES integration silently 10x sizing → blown prop account | **Never** |
| Use naive `datetime` somewhere "just for a quick print" | Skips tz boilerplate | One DST transition corrupts session windows | **Never** in production code; OK in throwaway notebooks |
| `from_signals(close, entries)` without next-bar shift | Faster prototyping | Reports inflated Sharpe; you trust the wrong strategy | **Only** in a clearly-named `prototype_lookahead.py` with banner comment; never in `backtest/` |
| Single-period (1-year) backtest to "validate the pipeline" | Quick smoke test | Strategy decisions made on regime-dependent fluke | OK as a smoke test; not OK as the basis for parameter selection |
| Skip rollover-seam detection because "it's only quarterly" | Saves 1 day of dev | One mystery trade wins a contest; you can't reproduce it | **Never** for ES |
| Audit log to CSV only (no DuckDB) | Easier debugging | Process crash loses last hour; no relational query | OK during local dev only; required in DuckDB by Phase 6 ship |
| Skip walk-forward, optimize on full history | Faster optimization | Overfits guaranteed | **Never** for parameter selection; OK for "is the engine wired up" smoke test |
| Hardcode RTH window as 9:30–16:00 ignoring half-days | Saves calendar setup | Strategy "trades" on closed days; trades held into nothing | OK for first hour of dev; required by end of Phase 1 |
| Same TV chart for both system overlays and manual analysis | Quicker setup | State conflicts | OK during dev; address by Phase 9 ship |
| Polling instead of WebSocket for UI updates | Simpler backend | Lag, server load | OK for v0 UI; WebSocket required by Phase 8 ship |

---

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| Twelve Data | Trust `time_series` returns N bars when requested N | Validate against expected RTH bar count; fetch with bar-count check |
| Twelve Data | Use `?timezone=America/New_York` for some calls and UTC for others | Always pass `timezone=UTC`; convert in our code |
| Twelve Data | Treat continuous ES symbol as a stable instrument | Detect rollover seams; flag bars; reconcile against front-month symbol |
| VectorBT | `Portfolio.from_signals(close, entries=signal_series)` | `Portfolio.from_signals(close=close, open=open, entries=entries.shift(1), price='nextbar', sl_stop=...)` |
| VectorBT | Backtest in-place modifies indicator series | Pre-compute indicators, shift, then call backtest |
| DuckDB | Open second writer connection from a Jupyter notebook while UI is running | Always `read_only=True` from notebooks |
| DuckDB | `conn.close()` in Python but exception was raised → connection not actually closed | Use `with duckdb.connect(...) as conn:` context manager |
| pandas | `tz_localize(None)` to "make timestamps simpler" | Never. Carry timezone info; convert only at display |
| Lightweight Charts | Pass datetime strings | Pass UNIX seconds (UTC); configure tick formatter for ET display |
| TradingView MCP | Assume chart state persists across MCP calls | Always read state before acting; never assume |
| TradingView MCP | Create thousands of shapes for live signals | Use a registry; cleanup on schedule |
| FastAPI WebSocket | `await ws.send_json(payload)` without sequence number | Include monotonic `seq` on every message for ordering / gap detection |
| asyncio | Mix threading-based code (a sync API call) into the event loop without `run_in_executor` | Twelve Data REST calls go through `httpx.AsyncClient` or `run_in_executor` |
| Next.js | Server components reading process env at build time | Use `NEXT_PUBLIC_*` correctly; secrets stay server-side |

---

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Re-read entire DuckDB table per UI tick | UI lag spikes; CPU pegged | Push deltas via WebSocket; cache last-state | Once you have > 30 days of bars (~10k rows/day @ 1m) |
| WFO without parallelism | 4-hour optimizations | `concurrent.futures.ProcessPoolExecutor` for IS folds; per-fold parquet output | Beyond ~500 param combos × 10 folds |
| VectorBT call per parameter combo (Python loop) | Optimization is 100× slower than necessary | Vectorize across params via `vbt.IndicatorFactory` / param grid as columns | Beyond ~50 combos |
| Storing 1m bars as JSON / CSV | Slow ingest, slow reads | Parquet + DuckDB columnar | Past 3 months of 1m bars |
| Pandas `apply` in indicator computation | Slow indicators dominate runtime | Use vectorized numpy/numba | Always avoid in hot paths |
| Lightweight Charts with > 50k bars loaded | UI freezes | Load on-demand windowed; aggregate to higher timeframes for zoomed-out views | Past 6 months of 1m bars on a single chart |
| WebSocket broadcast to all clients on every bar | Backend CPU spikes | Per-client subscription filtering; only send what they're viewing | Multi-pane UI with > 5 active subscriptions |
| Re-running ATR per bar in live executor | Latency per bar > 100ms | Incremental update (Welford-style) | At 1m granularity, fine. At sub-minute, breaks |

---

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| `.env` not gitignored, API key in repo | Twelve Data key scraped; rate limit exhausted; potential billing exposure | `.gitignore` + pre-commit `gitleaks` |
| Logging API key in error messages | Key leaks to log files; log files end up in screenshots / issues | Mask all `*_API_KEY` env vars in log formatter |
| FastAPI binds to `0.0.0.0` by default | Local UI exposed to LAN; potentially internet if port-forwarded | Bind to `127.0.0.1` only |
| No auth on the FastAPI backend | If anyone else is on the network, they can change strategy params, kick off trades | OK for v1 (single operator, localhost); document the constraint; revisit if ever exposed |
| TradingView MCP credentials in plain config | MCP can read/write the TV account | Store in OS-level secret store or `.env` with same protections as API keys |
| Audit log written to a world-readable path | Trade history is sensitive (even paper trades reflect strategy IP) | `.planning/audit/` not committed; permissions set; backup encrypted |
| DuckDB file shared across users | Trade history readable by anyone with the file | Single-user Windows account; file under user profile, not shared dirs |

---

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| Modal dialogs for confirmations on every action | Decision fatigue in dense UI | Confirm only for destructive actions (delete strategy, reset HWM); other actions reversible |
| P&L color: green/red without considering colorblindness | ~8% of male users can't distinguish | Use shape (▲▼), sign explicit, or use blue/orange palette |
| Dense numerical columns without proper alignment | Hard to scan | Right-align numerics, monospace digits, decimal-point aligned |
| Live equity curve animation that scrolls smoothly | Distracting; hides spikes | Discrete bar-by-bar updates; persistent vertical line at current time |
| Mouse-only interaction for strategy on/off | Slow to react in fast markets | Single-key toggle (`Space`) for paper trading global on/off |
| Showing only realized P&L; unrealized hidden | Operator misjudges exposure | Show both realized and unrealized side-by-side; total P&L row |
| No way to see "why was this trade rejected by risk?" | Operator confused; loses trust | Audit log surfaced in UI; every rejected signal shows its reason chain |
| Backtest results UI doesn't surface data hash / git sha | Hard to know which "Sharpe 1.4" you're looking at | Every result card shows `data_hash`, `git_sha`, `seed`, `param_hash` in small mono text |
| Optimization results buried in tables | Hard to spot robust regions | 2D heatmap of any 2-param slice; click to drill into trades |

---

## "Looks Done But Isn't" Checklist

Things that appear complete but are missing critical pieces. Run this checklist at each phase transition.

- [ ] **Data ingest**: Verify rollover seams flagged. Run a query: `SELECT date, max(abs_pct_change) FROM bars GROUP BY date ORDER BY 2 DESC LIMIT 20`. Top results should be FOMC/news days, not quarterly Fridays.
- [ ] **Data ingest**: Verify holiday handling. `SELECT date FROM bars WHERE date IN ('2024-11-29', '2024-12-24', ...)` should return half-day partial counts, not full sessions.
- [ ] **RTH filter**: Verify on DST transitions. Manually inspect 2024-03-10, 2024-11-03 (and equivalent 2025/2026 dates) — sessions should be 6.5 hours real-time, no 5.5 or 7.5 hour days.
- [ ] **Backtest engine**: Run a "perfect lookahead" strategy (uses `close.shift(-1)`); apply the framework's signal-shifting helper; assert Sharpe is NOT infinite. If it is, the helper is broken.
- [ ] **Indicators**: For each indicator (ATR, EMA, VWAP), assert `indicator[t]` is unchanged by appending bars `[t+1, t+2, ...]` to the input series.
- [ ] **WFO**: Verify warmup bars come from before the IS window, not within. Inspect the input slice for each fold.
- [ ] **Risk manager**: Run the "$50k account, trailing intraday DD" test. Simulate equity going to $52.5k unrealized, then back to $50.1k. System should flag DD breach (floor was $50k).
- [ ] **Risk manager**: EOD flatten test. Simulate session ending with a position open. Assert position closed at session close, not held.
- [ ] **Sizing**: Run `size(1000, 5, MES)` and `size(1000, 5, ES)`; verify outputs are 40 and 4 respectively.
- [ ] **Audit log**: Kill -9 the process during a trade; restart; verify last decision is recoverable from DuckDB.
- [ ] **Replay**: Take yesterday's audit log; replay it; assert byte-equal output (modulo timestamps).
- [ ] **WebSocket**: Drop the connection 100 times; verify no message loss (sequence numbers continuous) and no duplicate positions.
- [ ] **Chart**: Verify ORB box drawn at 09:30–09:45 ET on a chart actually overlays the 09:30–09:45 ET candles in EST and EDT.
- [ ] **TradingView MCP**: Verify ATR computed in Python matches ATR shown in TradingView on a known day.
- [ ] **Reproducibility**: Run a backtest twice; assert all output numbers identical to 6 decimals.
- [ ] **Secrets**: `git log --all -p | grep -i "api_key" | grep -v "\.example"` returns nothing.
- [ ] **Windows paths**: Run the full test suite from a path containing a space (mirror the real `Desktop\Day Trading\` location).

---

## Recovery Strategies

When pitfalls occur despite prevention, how to recover.

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Rollover seam not flagged | LOW (data fix), HIGH (any decision made on contaminated backtest is suspect) | Add seam detection retroactively; re-run all backtests; tag old results as "pre-fix"; compare new vs old to assess decision impact |
| ETH bars leaked into "RTH" data | MEDIUM | Filter retroactively; re-ingest from Twelve Data with correct filter; re-run backtests |
| Same-bar fill leakage discovered | HIGH | All prior backtest results invalid; re-run with fixed engine; revert any strategy decisions made on old numbers |
| Indicator leakage (ATR included signal bar) | HIGH | Same as above |
| WFO contamination (meta-overfitting) | VERY HIGH | The OOS data is "burned." Reserve a new untouched holdout period; cannot recover the original; document the burn in an ADR |
| Prop-firm DD model wrong | MEDIUM (paper) / CRITICAL (live) | Recompute DD on existing trade log with correct model; if breach found, restart paper account for psychological reset |
| API key leaked to git | MEDIUM | Rotate key immediately at Twelve Data; `git filter-repo` to remove from history; force-push (only on solo repo); audit log access |
| Audit log lost in crash | LOW (paper) / HIGH (any live) | Improve persistence immediately; for the lost window, mark trades as "unknown reason"; backfill from broker statements (not applicable here, paper only) |
| DuckDB file locked | LOW | Kill the conflicting process; release lock; document the offender; add to read_only convention |
| Reproducibility broken | MEDIUM | Add seed/hash logging; re-run "canonical" backtests; commit baseline outputs |
| Wrong tick value (ES vs MES) | HIGH | Audit all trade sizing in log; recompute risk for affected period; if real-money equivalent risk exceeded plan, halt and review |
| EOD flatten missed | HIGH (prop violation) | Manual close; reset HWM if needed; add hard kill-switch on a separate scheduler thread |
| Lightweight Charts TZ drift | LOW | Fix formatter; verify visually on known timestamps |

---

## Pitfall-to-Phase Mapping

| Pitfall | Severity | Prevention Phase | Verification |
|---------|----------|------------------|--------------|
| MD-1 Rollover seams | Critical | Phase 1 | Quarterly Fridays flagged; quarantine review |
| MD-2 ETH bar leakage | Critical | Phase 1 | DST transition unit tests pass; no bars outside 09:30–16:00 ET in RTH dataset |
| MD-3 Holiday/half-day mishandling | High | Phase 1 | `pandas_market_calendars` CME_Equity used; calendar parquet committed |
| MD-4 Bar timestamp convention | Critical | Phase 1, enforced Phase 3 | Single `next_bar_fill()` utility; lookahead-test infinite-Sharpe assertion |
| MD-5 Twelve Data quirks | High | Phase 1 | Per-day bar-count validator passes; raw responses cached |
| MD-6 DST / UTC discipline | Critical | Phase 1, repo-wide | Pre-commit lint for `datetime.now()`; tests on DST dates |
| BL-1 Same-bar fill | Critical | Phase 3 | `safe_from_signals()` helper enforced; lookahead test |
| BL-2 Indicator includes signal bar | Critical | Phase 2 + 3 | `Indicator.snapshot_at(t)` interface; leakage detector |
| BL-3 HTF look-ahead | Critical | Phase 2 | HTF features shifted; constancy test across intraday |
| BL-4 WFO fold contamination | Critical | Phase 4 | Config-hash logging; "true holdout" guard; param/window lock-in ADR |
| BL-5 Indicator warmup bias | High | Phase 3 | Warmup buffer; refuse signals during warmup |
| FR-1 Open-fill optimism | Critical | Phase 3 | Slippage model with session-phase awareness; TV replay validation |
| FR-2 Same-bar entry+stop | Critical | Phase 3 | Worst-case intrabar convention documented and tested |
| FR-3 Partial-fill model | Medium | Phase 3 | Documented assumption; revisit if size grows |
| FR-4 Overnight leak | High | Phase 3 + 5 | Forced flatten at session close in backtester and risk |
| SL-1 RTH vs Globex ORB confusion | Critical | Phase 2 | Explicit time-of-day ORB definition; TV cross-check |
| SL-2 Narrow/wide range | High | Phase 2 | Range/ATR ratio gate |
| SL-3 False breakout | High | Phase 2 | Bar-close confirmation; volume filter |
| SL-4 Re-entry compounding | Medium | Phase 2 + 5 | `max_entries_per_day` cap |
| SL-5 Late entries | Medium | Phase 2 | `latest_entry_time` parameter |
| OPT-1 Too-fine grid | Critical | Phase 4 | Coarse-first protocol; plateau detection |
| OPT-2 Single-period bias | Critical | Phase 4 | Min 5-year window; regime tagging |
| OPT-3 Return-not-robustness | High | Phase 4 | Sharpe + drawdown + bootstrap as primary; plateau pick |
| OPT-4 Objective shopping | Critical | Phase 4 | Pre-commit objective ADR; run-config hashing |
| OPT-5 Window shopping | High | Phase 4 | Lock IS/OOS windows in ADR before first run |
| RM-1 Tick-value sizing | Critical | Phase 5 | `instruments.py` SoT; unit tests for ES and MES |
| RM-2 Trailing vs static DD | Critical | Phase 5 | DrawdownModel enum; per-variant unit tests |
| RM-3 Post-fill risk check | Critical | Phase 5 | Pre-trade `worst_case_loss` check |
| RM-4 EOD flatten | Critical | Phase 5 + 6 | Wall-clock scheduler; backtester assertion |
| RM-5 Max contracts | High | Phase 5 | Per-firm config; static cap |
| RM-6 HWM not persistent | Critical | Phase 5 | DuckDB-persisted HWM; refuse start without today's row |
| SP-1 Duplicate signals | High | Phase 6 + 1 | Deterministic `signal_id`; executor dedup |
| SP-2 Race in risk check | High | Phase 5 + 6 | Single-threaded risk loop; state-version check |
| SP-3 Audit log restart loss | High | Phase 6 | Synchronous DuckDB writes; kill-9 test |
| SP-4 No replay | Medium | Phase 6 + 10 | `Replay` command; deterministic re-execution |
| UI-1 No keyboard nav | High | Phase 8 | Tab cycle; command palette; single-key shortcuts |
| UI-2 WebSocket storms | High | Phase 7 + 8 | Backoff+jitter; snapshot resync |
| UI-3 P&L lag | High | Phase 7 + 8 | `position_state_v2` channel; staleness indicator |
| UI-4 Chart TZ drift | Critical | Phase 8 | Tick formatter with ET conversion; visual smoke test |
| UI-5 Blotter/equity race | Medium | Phase 7 | Atomic state broadcast |
| TV-1 Drawing accumulation | Medium | Phase 9 | Registry table; daily cleanup |
| TV-2 TV as truth | Critical | Phase 9 + 1 | Documented Python-canonical policy; daily reconciliation |
| TV-3 Replay state | Medium | Phase 9 | `replay_status` check before each action |
| TV-4 Indicator mismatch | Medium | Phase 2 | Match TV's formula (RMA, etc.); cross-validation test |
| OP-1 API key leak | Critical | Phase 1 (first commit) | `.gitignore`, `gitleaks`, pydantic-settings |
| OP-2 Irreproducible backtests | Critical | Phase 3 + 10 | Run-identity hashing; CI reproducibility test |
| OP-3 DuckDB file lock | High | Phase 1 | Single-writer architecture; documented |
| OP-4 Windows path bugs | Medium | Phase 1 | `pathlib`; UTF-8 encoding; CI on Windows |
| OP-5 Rate-limit truncation | High | Phase 1 | Per-day bar-count validator |
| OP-6 No CI gate | High | Phase 10 (scaffold Phase 3) | Reference backtest in CI; equity-curve snapshot test |
| OP-7 TV concurrent access | Medium | Phase 9 | System mode toggle; secondary layout |

---

## Sources

- [E-mini S&P 500 Futures Calendar — CME Group](https://www.cmegroup.com/markets/equities/sp/e-mini-sandp500.calendar.html)
- [CME Group Holiday and Trading Hours](https://www.cmegroup.com/trading-hours.html)
- [Apex Trader Funding — Trailing/Static Drawdown Threshold](https://support.apextraderfunding.com/hc/en-us/articles/4408610260507-How-Does-the-Trailing-Static-Drawdown-Threshold-Work-Master-Course)
- [Apex Trader Funding — Evaluation Rules](https://support.apextraderfunding.com/hc/en-us/articles/31519769997083-Evaluation-Rules)
- [Trailing Drawdown — Survival Guide (CrossTrade)](https://crosstrade.io/learn/risk-management/trailing-drawdown-survival-guide)
- [Unrealized Trailing Drawdown Explained (Damn Prop Firms)](https://damnpropfirms.com/trading-strategies/unrealized-trailing-drawdown-explained-apex-trader-funding-rules-with-real-life-examples/)
- [VectorBT — base / portfolio docs](https://vectorbt.dev/api/portfolio/base/)
- [VectorBT — features (look-ahead bias notes)](https://vectorbt.dev/getting-started/features/)
- [VectorBT discussion: signal generation patterns](https://github.com/polakowo/vectorbt/discussions/196)
- [PyQuant News — Intraday backtesting with VectorBT Pro](https://www.pyquantnews.com/the-pyquant-newsletter/intraday-backtesting-with-vectorbt-pro)
- [Walk-Forward Optimization (Wikipedia)](https://en.wikipedia.org/wiki/Walk_forward_optimization)
- [Walk-Forward Optimization: How It Works, Its Limitations — QuantInsti](https://blog.quantinsti.com/walk-forward-optimization-introduction/)
- [Walk-Forward Analysis vs Backtesting — Surmount](https://surmount.ai/blogs/walk-forward-analysis-vs-backtesting-pros-cons-best-practices)
- [How to Use Walk Forward Analysis: You May Be Doing It Wrong — Unger Academy](https://ungeracademy.com/posts/how-to-use-walk-forward-analysis-you-may-be-doing-it-wrong)
- [Continuous Futures Contracts for Backtesting Purposes — QuantStart](https://www.quantstart.com/articles/Continuous-Futures-Contracts-for-Backtesting-Purposes/)
- [Continuous Futures (Interactive Brokers)](https://www.interactivebrokers.co.uk/en/software/tws.bak/usersguidebook/technicalanalytics/continuous.htm)
- [DuckDB — Concurrency](https://duckdb.org/docs/current/connect/concurrency)
- [DuckDB Issue #17158 — IO Error: Could not set lock on file (Python)](https://github.com/duckdb/duckdb/issues/17158)
- [DuckDB Discussion #4899 — Concurrent writes](https://github.com/duckdb/duckdb/discussions/4899)
- [Opening Range Breakout Strategy — Trade That Swing](https://tradethatswing.com/opening-range-breakout-strategy-up-400-this-year/)
- [Opening Range Breakout — Build Alpha](https://www.buildalpha.com/opening-range-breakout/)
- [ORB Trading Strategy for Futures — Metrotrade](https://www.metrotrade.com/orb-open-range-breakout-trading-strategy/)
- [Twelve Data — API Documentation](https://twelvedata.com/docs)
- Personal practice / industry consensus on intraday backtesting hygiene (no single URL)

---

*Pitfalls research for: Intraday ES Futures Backtest + Paper Trading System*
*Researched: 2026-05-14*
