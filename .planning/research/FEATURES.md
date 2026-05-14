# Feature Research

**Domain:** Intraday ES Futures Backtest + Paper-Trading System with Bloomberg-Terminal-style UI
**Researched:** 2026-05-14
**Confidence:** HIGH for feature inventory (verified against multiple open-source backtesters, prop-firm platforms, and Bloomberg/OpenBB/TradingView docs). MEDIUM for prioritization specifics (driven by the operator profile in PROJECT.md, not a sample of users).

---

## 0. Reading Guide

This file is organized by the seven modules called out in PROJECT.md, not by table-stakes-vs-differentiator-vs-anti-feature globally. Each module has all three subsections in order:

1. **Table Stakes** — if missing, the system silently lies, looks broken, or violates the "trust the numbers" core value
2. **Differentiators** — meaningful edge over an off-the-shelf Backtrader script + Streamlit dashboard; usually defer past v1 unless cheap
3. **Anti-features** — things that look attractive but actively harm the project (scope traps, vanity metrics, or things that mislead the trader)

Complexity hints: **S** ≤ ~1 day, **M** ~2–5 days, **L** >1 week. Dependencies in the cross-module section at the bottom.

A note on rigor: in a paper/backtest system the **only** product is "numbers you can trust." That makes table-stakes here stricter than in a typical SaaS — anything that allows a silently-wrong number to escape into a P&L total is a bug, not a missing feature.

---

## 1. Market Data Ingestion

The hidden core. Most "my backtest doesn't match live" stories trace back here.

### Table Stakes

| Feature | Why Expected | Complexity | Notes |
|---|---|---|---|
| UTC-only storage; ET-only render | Every other policy creates DST + holiday bugs. Bloomberg, OpenBB, Nautilus, IB API all do this | S | Store `timestamp_utc: TIMESTAMPTZ`. Convert to `America/New_York` only at API boundary. Never mix. |
| RTH session filter (9:30:00–16:00:00 ET, inclusive-exclusive) | ORB and ATR sizing both break if ETH bars leak in | S | Apply at ingest, not at strategy. Drop bars outside session before persist. |
| CME equity-index holiday + early-close calendar | 4 early-close days/year (day after Thanksgiving, Christmas Eve, etc.) silently break "16:00 close" assumptions | S | Use `pandas_market_calendars` `CMEEquity` calendar. Cache to DuckDB. Verify against CME annual schedule. |
| Bar gap detection (expected-vs-actual bar count per session) | A missing 14:32 bar will silently break VWAP/ATR rolling windows | S | Per session: `expected = 390 / minutes_per_bar`. Flag any session where count < expected. Surface in a `data_quality` table. |
| Bar gap repair policy (explicit, not implicit) | The wrong default (forward-fill) creates fake bars that breakouts trigger off | M | Three policies: `drop` (default — session marked partial), `forward_fill_ohlc` (last close), `interpolate` (forbidden — anti-feature). Persist which policy was applied per bar. |
| Idempotent upsert keyed on `(symbol, timeframe, timestamp_utc)` | Re-running ingestion duplicates rows. Duplicates poison VBT. | S | DuckDB `INSERT OR REPLACE` or merge-on-conflict. Add unique index. |
| Continuous front-month symbol with rollover detection | ES rolls quarterly (3rd Friday of Mar/Jun/Sep/Dec, rolled Mon before). Without it, the chart "gaps" and false breakouts fire on roll day | M | Volume- or OI-based roll trigger if available; else use CME calendar (Monday prior to 3rd Friday). Store `contract_month` per bar so a roll can be audited. |
| Roll-adjustment method declared and stored | Unadjusted continuous → fake breakouts. Back-adjusted → returns differ from price moves. Mixing the two corrupts ratios. | M | Default: **back-adjusted by absolute difference** for charting + signal generation. Store **raw front-month** for exact P&L calculation. Both columns persisted. |
| Provider-agnostic `DataSource` interface | PROJECT.md mandates Polygon/IB/TradingView swap path | S | Abstract method `fetch(symbol, timeframe, start, end) -> DataFrame[bar_schema]`. Implementations live behind it. |
| Data quality report per ingest | "Did anything weird happen overnight?" needs to be answerable in 5 seconds | S | One row per session: bars_expected, bars_received, gaps_found, gap_repair_policy, source, fetched_at. |
| Bar schema validation at ingest boundary | High/Low must enclose Open/Close; Volume ≥ 0; no NaN/Inf | S | Pydantic/pandera. Fail loudly. Quarantine bad bars to `quarantine` table, don't silently drop. |

### Differentiators

| Feature | Value Proposition | Complexity | Notes |
|---|---|---|---|
| Multi-source reconciliation (Twelve Data vs TV MCP vs cached) | Detects bad Twelve Data bars by cross-checking against TradingView via MCP | M | "Trust the numbers" is the core value — this is the ultimate trust check. Run on demand, not every ingest. |
| Tick-value + multiplier registry per symbol | One source of truth for ES ($12.50/tick), MES ($1.25/tick), NQ ($5/tick) | S | Eliminates the most common P&L bug. Keep as a small TOML/JSON, version-controlled. |
| Snapshot the calendar at backtest time | If CME republishes holiday data later, old backtests stay reproducible | S | Persist calendar_version with each backtest run. |
| Continuous-contract methods toggle (back-adjusted, ratio-adjusted, unadjusted) | Different methods favor different strategy types; ORB is sensitive to absolute levels | M | Most users don't even know this is a choice. Surfacing it is differentiator. |
| Replay mode that pipes historical bars through the same WebSocket as live | "Live mode" and "research mode" share one code path, dramatically reduces bugs | M | Same idea as Nautilus's unified backtest/live engine. Big payoff. |

### Anti-Features

| Feature | Why Requested | Why Problematic | Alternative |
|---|---|---|---|
| Sub-minute / tick data ingestion | "More data = better backtest" | PROJECT.md is explicit: intraday only at 1m–15m. Tick data inflates storage 100×, requires WebSocket, and ORB cares about minute bars anyway | Stick to 1m bars as smallest unit. Tick-level fill modeling is bracketed inside the backtester, not the data layer. |
| Forward-fill on missing intraday bars (silent default) | "I want a continuous chart" | Creates synthetic prices that ORB and ATR will trade off. Hides data feed issues. | Drop with `data_quality` flag. Surface the gap in the UI. |
| Interpolated OHLC for gaps | "It looks cleaner" | Fabricates highs/lows that never traded — pure look-ahead bias for breakout strategies | Forbidden. Never offer this option. |
| ETH/Globex bar ingestion in v1 | "Why throw away data?" | Out of scope per PROJECT.md. Adds rollover-during-gap edge cases, low-liquidity bars that break ATR, and overnight session policy decisions | Drop at ingest. If wanted later, add a `session` column and filter downstream. |
| Smart "auto-fill from another provider" on gap | "Self-healing" | Mixes data sources within a single bar, breaks reproducibility, makes provenance untraceable | Per-session, per-source provenance. If a provider is missing data, mark the session bad and re-run the whole session from one source. |
| Live tick streaming "for v1" | "We'll need it eventually" | At 1m/5m/15m a REST poll is sufficient and removes an entire class of WS reconnect/dedup bugs | Defer. Add a `StreamingDataSource` interface only when a strategy needs sub-minute data. |

---

## 2. Strategy Engine

### Table Stakes

| Feature | Why Expected | Complexity | Notes |
|---|---|---|---|
| `Strategy` base class with `on_bar(bar) -> Signal \| None` | Specified in PROJECT.md. Bar-event interface is the contract every other module assumes. | S | Stateless contract; state lives on the instance. |
| Bar-aligned timestamps in the strategy's clock | Strategy must never see a bar before it has "closed." Most look-ahead bugs come from violating this | S | `on_bar` is called only after the bar is final. No mid-bar peeks. |
| Warm-up bar handling | A strategy needing a 14-period ATR returns no signals for the first 14 bars; trying to generate one before warmup is a leakage source | S | Strategy declares `required_history: int`. Engine suppresses `on_bar` calls until threshold is reached. |
| Signal de-duplication within a bar | Same strategy can generate the same signal twice if logic isn't idempotent → double position | S | One `(strategy_id, symbol, bar_ts)` → at most one signal. Engine enforces. |
| Signal object schema: side, entry, stop, target, size_hint, timestamp, strategy_id, reason | PROJECT.md spec. Without `reason`, audit log is useless. | S | Pydantic. `reason` is a short string ("ORB long break") — humans read it later. |
| Strategy ID + version (semantic) stamped on every signal | If the strategy changed between two backtests, the comparison is meaningless without versioning | S | `strategy_id = "orb_v0.3.1"`. Bump on parameter-default change. |
| Indicator layer (ATR, VWAP, EMA, ADR) with bar-aligned outputs | PROJECT.md explicit | M | All indicators consume only bars up to and including current. Unit test: indicator value at bar N must equal value at bar N when run with truncated history. |
| Deterministic given same input | Same bars in → same signals out, every run | S | No `random` calls. If randomness ever needed, take a `random.Random(seed)` injected by engine. |
| ORB reference strategy as the canonical correctness test | PROJECT.md seed. Also serves as the "if this breaks, everything breaks" smoke test | M | Configurable opening-range minutes (5/15/30), ATR-based stop, R-multiple target. |

### Differentiators

| Feature | Value Proposition | Complexity | Notes |
|---|---|---|---|
| Multi-strategy concurrent execution (independent capital silos) | Lets you forward-test ORB-5m alongside ORB-15m without cross-contamination | M | Each strategy gets its own `Portfolio` slice. Risk manager aggregates at the top. |
| Strategy hot-reload from disk | Edit, save, see signals immediately without restart | M | Watch the strategy file, reload module, swap instance. Mostly a DX win. |
| "Why?" introspection: strategy can attach feature values to a signal | When a signal fires, you can see the ATR value, current ORB high/low, etc. — invaluable for forensic replay | S | `signal.features: dict[str, float]` — strategy fills in whatever it computed. |
| Bar-by-bar state snapshot to DuckDB | Replay any signal with full strategy state at the moment | M | Heavy on disk; gate behind a `debug=True` flag per backtest. |
| Multi-timeframe within one strategy (1m bars + 5m context) | ORB-style strategies often want HTF bias filter | M | Strategy declares timeframes consumed. Engine routes correctly. |

### Anti-Features

| Feature | Why Requested | Why Problematic | Alternative |
|---|---|---|---|
| Mid-bar signal generation ("on_tick" hook) | "I want to react to a spike inside the bar" | Out of scope for 1m+ data. Encourages look-ahead. Allows strategies that can't be reproduced from bar data alone | Forbidden in v1. If needed later, add a separate `on_tick` interface guarded by a "requires tick data" flag. |
| ML / RL strategy types | "Modern" | Explicitly out of scope per PROJECT.md. Adds training-time leakage, model drift tracking, GPU plumbing — none of which serve the ORB validation thesis | Defer until deterministic strategy pipeline is verified end-to-end. |
| "Live edit and apply to running backtest" | DX shiny | Backtests must be reproducible. Mid-flight edits make results non-reproducible by definition | Edit, re-run. Backtests are fast. |
| Magic indicators that read forward (Repainting indicators) | Often packaged with TradingView-style libraries | Will produce backtest results that cannot occur in live | Indicators must explicitly declare `look_ahead = 0`. CI test for any indicator: value at bar N must match value computed when only bars 0..N exist. |
| Strategy "auto-tuning" inside the engine | "Strategies that adapt" | Cross-cuts optimization and signal generation. Creates an in-sample-on-every-bar trap. | Put adaptation in optimization module, with explicit IS/OOS boundaries. |

---

## 3. Backtesting Module

This is the truth-teller. Everything here exists to prevent self-deception.

### Table Stakes

| Feature | Why Expected | Complexity | Notes |
|---|---|---|---|
| **Next-bar-open fill** as default for market orders | Single biggest source of look-ahead in backtests is "I saw the close, I bought at the close." Next-bar-open mirrors live | S | Backtrader and Nautilus both default to this. Cite "next bar's open" in code comments. |
| Stop fills at trigger price + slippage (not at the stop price exactly) | Stops are market orders once triggered; assuming a perfect stop fill overstates results by 1–3 ticks per trade | S | `fill_price = stop_price + slippage_ticks * tick_size * direction`. |
| Limit fills only if bar's range crosses the limit | Otherwise a limit "fills" just because price closed past it later | S | Standard logic; both Backtrader and Nautilus do this. |
| Commission per contract per side ("half-turn"), with round-turn shown separately | Mixing the two is a 2× P&L error | S | Default: $0.62/side for MES, $2.50/side for ES (CME exchange + clearing). Configurable. |
| Slippage in ticks, configurable per strategy/side | Live ES slippage on a 5m breakout is typically 1–2 ticks; 0 ticks is fantasy | S | Default 1 tick for ES limit/market on intraday, 2 ticks for stop fills. Explicit config. |
| Tick-value and contract-multiplier respected in P&L math | $1 of ES P&L is 0.25/12.50 = wrong by 50× if you use point-value | S | Use the symbol registry from Module 1. |
| Standard metrics: total return, Sharpe, Sortino, max DD, win rate, expectancy, profit factor | PROJECT.md spec. Industry-standard set. | S | Compute all on `pnl_per_trade` series and `equity_curve`. |
| Trade ledger persisted with **full attribution chain**: signal → risk decision → fill → exit | "Why did I take this trade?" must be answerable in one query | M | DuckDB table with FKs from `trades` → `risk_decisions` → `signals`. PROJECT.md says full attribution. |
| Look-ahead leakage detector | A strategy that runs perfectly on a 1-bar-delayed feed AND on the regular feed has no leakage; mismatched results = leakage | M | Run the same backtest twice: once normal, once with all features delayed by 1 bar. If signals differ in count or timing, surface a warning. |
| Reproducibility: same code + same data + same params → bitwise-identical equity curve | The core value of the project depends on this | S | Seed any RNG. No `datetime.now()` inside the engine. Pin pandas/numpy versions. |
| Exit-reason taxonomy (stop, target, EOD flat, manual flat, opposite-signal) | Aggregate stats by exit reason — where the strategy is actually winning/losing | S | Enum stored on each trade. |
| End-of-day forced flat for intraday strategies | Holding overnight inflates win rate by capturing gap-up. Intraday must be intraday | S | At 15:55 ET (configurable), flatten all positions at next-bar open. |

### Differentiators

| Feature | Value Proposition | Complexity | Notes |
|---|---|---|---|
| Slippage models that scale with bar range | A breakout on a wide-range bar slips more than on a narrow-range bar. More realistic than a fixed tick count | M | `slippage = clamp(k * bar_range, min=1 tick, max=4 ticks)`. |
| Per-bar order book proxy (use bar volume to throttle fills) | If a 1m bar trades 200 contracts, your 10-contract market order is fine; on a 30-volume bar it isn't | M | Cap fill size at `min(order_size, alpha * bar_volume)`. Nautilus does this with L2; we approximate with bar volume. |
| Side-by-side backtest diff | "I changed one parameter — what changed?" highlights trades that flipped | M | Diff two trade ledgers by (entry_ts, side). Show added, removed, changed. |
| Equity curve confidence band via bar-resampled bootstrap | Conveys "is this strategy good, or was it lucky on this exact path?" | M | Resample with replacement at the trade level, plot 5/50/95 percentile equity curves. (Strictly belongs in Optimization, but the bootstrap belongs in backtest output too.) |
| MAE/MFE per trade | Diagnoses whether stops are too tight or targets too greedy | S | Max adverse excursion = worst unrealized loss inside the trade; MFE = best unrealized gain. Standard stat. |
| Backtest run hash (params + data hash + code hash) | Lets the UI cache and dedupe identical runs | S | SHA256 of `{strategy_id, params, data_window, slippage, commission}`. |

### Anti-Features

| Feature | Why Requested | Why Problematic | Alternative |
|---|---|---|---|
| Current-bar-at-close fills | "Looks like it would have filled there" | The signal that triggered the fill is computed FROM the close. Pure look-ahead. Inflates returns silently. | Next-bar-open. If user truly wants C2C fills, gate behind a `--i-know-this-is-leakage` flag. |
| Zero-slippage, zero-commission "ideal" mode | "I want to see pure alpha" | Numbers are misleading without context. Users compare ideal-mode Sharpe to broker-fee Sharpe. | Always show realistic. Offer a "frictionless" toggle but require both numbers visible side by side. |
| Backtest auto-runs every time params change in UI | "Live feel" | Encourages parameter overfitting via visual feedback. Promotes the worst kind of curve-fitting. | Run on explicit "Run Backtest" button. Show how many runs you've done in this session — gentle pressure not to over-iterate. |
| Tick-level fill simulation from 1m bars | "More realistic" | The 1m bar OHLC doesn't contain the path. Simulating ticks from OHLC is a lie that feels precise. | Stick to bar-level fills with explicit slippage model. If tick fidelity matters, ingest tick data (out of scope for v1). |
| Walk-back-to-fix when stop hits during entry bar | "Just take the entry" | The bar can hit stop before entry on a single 1m bar — the order matters and is unknowable without ticks. | Be conservative: assume the worst-case sequence on the bar (touched stop = stopped out). Document the rule. |
| Currency-of-the-month risk-free rate for Sharpe | Some libraries pull live T-bill rates | Adds a moving target to a "frozen" backtest result; changes Sharpe between runs | Use 0 risk-free rate for intraday Sharpe by convention. Document it. |

---

## 4. Parameter Optimization

### Table Stakes

| Feature | Why Expected | Complexity | Notes |
|---|---|---|---|
| Grid search across declared parameter spaces | PROJECT.md spec. Baseline that everything else builds on | S | Strategy declares `param_space: dict[str, Iterable]`. Engine cartesian-products. |
| Walk-forward analysis with configurable IS/OOS window split | PROJECT.md spec. Single biggest defense against curve-fitting | M | Anchored or rolling windows; user picks IS length, OOS length, step. Default: 60-day IS, 20-day OOS, 20-day step. |
| Per-fold result persistence (params, IS metrics, OOS metrics, equity curve) | PROJECT.md spec. Needed to spot a strategy that wins IS and loses OOS — the textbook overfit | S | DuckDB tables `optim_runs`, `optim_folds`. FK to `backtests`. |
| Out-of-sample leaderboard ranked by OOS metric, not IS | Sorting by IS Sharpe rewards overfitting | S | Default sort: OOS Sharpe descending. IS metric is shown but explicitly secondary. |
| Heatmap export for any 2-param slice | PROJECT.md spec. Plateau-vs-spike geometry is how you eyeball robustness | M | Pivot a third metric (Sharpe) over two params. Save PNG + raw CSV. |
| Stability metric across walk-forward folds | A strategy with Sharpe 2.5 in one fold and -0.5 in another is unstable, even if mean is positive | S | Mean / std of fold Sharpes ("WF efficiency"). Surface it next to mean Sharpe. |
| Multi-metric reporting per parameter set | Optimizing on a single metric is the second-most-common overfit trap | S | Return Sharpe, Sortino, MaxDD, Profit Factor, # trades, win rate — all per param set. |
| Result reproducibility | Same param grid + same data + same code → identical leaderboard | S | Seed any RNG inside optimization. Hash inputs to the run. |

### Differentiators

| Feature | Value Proposition | Complexity | Notes |
|---|---|---|---|
| Edge ratio (IS metric ÷ OOS metric) auto-flagged when > 1.5 | Captures "looks great in-sample, crumbles out" in one number | S | Color-coded in leaderboard. Anything ≥ 2 is a red flag. |
| Monte Carlo trade-shuffle confidence intervals | Answers "is this equity curve a real edge or a lucky ordering?" | M | Shuffle trade returns 1000× with replacement, plot 5/95 percentile equity curves. Standard QuantConnect/StatOasis practice. |
| Parameter-stability heatmap (instead of just performance heatmap) | A region of params with uniformly good Sharpe is more trustworthy than a single spike | M | Plot std of Sharpe across folds for each param cell. Look for low-std plateaus. |
| Optimization "budget" / pruning (skip clearly bad params early) | Grid over a wide range is expensive; cuts cycles 10× | M | Optional; for v1 brute-force grid is fine. |
| Param-set diff: "what changed and how" | When user picks a new winner, show what they're really changing | S | Compare current best vs previous best, surface deltas + likely-trade impact. |
| Robustness check: re-run winning params on slightly perturbed data | If a 1-tick slippage perturbation tanks Sharpe, the strategy is fragile | M | Bump slippage by ±1 tick, commission ±25%, see if metrics survive. |

### Anti-Features

| Feature | Why Requested | Why Problematic | Alternative |
|---|---|---|---|
| Genetic / Bayesian optimization in v1 | "Faster optimization" | Explicitly out of scope per PROJECT.md. Adds search-bias considerations on top of fitting bias | Defer until grid + WF is shown to produce stable winners. |
| One-shot "best parameters" selection over full history | Easy to ship, easy to demo | Maximally overfit. Single biggest cause of paper-strategies-that-die-live. | Always walk-forward. Refuse to expose a "use full history" optimize button. |
| Ranking by raw return | "Show me the most profitable" | Rewards leverage and DD-blindness | Rank by OOS Sharpe (or Sortino) with MaxDD as a tiebreaker, never raw return. |
| Auto-deploy "the best params" to live strategy | "Set and forget" | Promotes overfit params into production. Live strategy should be human-promoted with sign-off. | Optimization writes a `candidate_params.toml`; promotion is a separate manual command. |
| Heatmap of a non-orthogonal param pair (e.g., stop_atr vs target_atr where target = N×stop) | Looks pretty | Slice has a built-in linear constraint; the visual "edge" is actually the constraint geometry, not a finding | Heatmap only over independent parameters. |

---

## 5. Signal Pipeline

The path from "strategy says X" to "paper executor records Y." Hardest part to get right and the most expensive when wrong.

### Table Stakes

| Feature | Why Expected | Complexity | Notes |
|---|---|---|---|
| In-process pub/sub bus (asyncio) | PROJECT.md spec. Async because the UI lives on the other side of a WebSocket | M | `asyncio.Queue` per topic or a tiny custom bus. No external broker (no Redis/Kafka) for v1. |
| Risk-check gate between Signal and Order | Every algo trading incident report ever cites "the algo got around the risk check" | S | Signal goes to a `RiskManager.evaluate(signal) -> Decision` before paper executor sees it. No back-door. |
| Audit log of every signal, decision, fill | PROJECT.md spec. Forensic replay depends on it. Also the only way to prove "the system did what it was supposed to" | M | DuckDB table per event type, all join on a single `event_id`. CSV mirror for grep-ability. |
| **Kill switch** (one button / one key / one API call → stop all strategies, do not flatten) | Industry standard, FINRA-cited. The single most important safety control | S | `/halt` endpoint + UI button + keyboard shortcut. Sets a global "no new signals accepted" flag. Existing positions remain (don't compound a problem). |
| **Flatten-all** (separate from kill switch) | Different intent: not "stop trading" but "go to flat now" | S | Separate button, separate hotkey, separate confirmation. UI must NOT conflate these two. |
| Daily-drawdown circuit breaker | PROJECT.md spec ($2k DD). Mandatory if mirroring prop firm — both Topstep and Apex auto-flatten | S | Tracks intraday equity vs day_start_equity. At threshold: flatten, set "no new trades until 17:00 ET" flag. |
| Per-strategy capital cap | PROJECT.md spec. Without it, one strategy can starve another | S | Strategy declares `max_capital_pct`. Risk manager enforces. |
| Per-strategy concurrency cap | A buggy strategy spamming entries is the canonical failure mode | S | `max_open_positions_per_strategy`. Default 1 for ORB. |
| Deterministic event order | Two signals firing on the same bar must always be handled in the same order or backtest ≠ live | S | Stable tie-break: timestamp, then strategy_id alphabetical. |
| Idempotency on order intent | If the bus retries, you don't get two orders | S | Each signal has a UUID; executor refuses duplicates. |
| Replay mode: feed historical audit log back through the pipeline, get bit-identical result | The forensic proof that the system is deterministic | M | Read `signals` and `bars` tables, replay through the same risk manager. Compare equity curve to original. |

### Differentiators

| Feature | Value Proposition | Complexity | Notes |
|---|---|---|---|
| "Why was this signal rejected?" inline in audit log | Risk rejections are usually mysterious. Stamp the rejection reason. | S | `risk_decision: APPROVED \| REJECTED(reason)`. |
| Per-strategy pause (vs kill) | "Pause ORB, keep mean-reversion running" | S | Per-strategy flag in addition to global halt. |
| Dry-run mode that emits signals but never sends to executor | Lets you verify a new strategy is producing sensible signals without touching positions | S | `--dry-run` per strategy. Signals still audited. |
| Replay scrubber that drives the pipeline from a past time | "What would the system have done at 10:42:30 yesterday?" | M | Powerful — bridges backtest and live mentally. |
| Hot configuration reload (risk limits, capital caps) | Adjust risk on the fly without restart | S | Watch a `risk_config.toml`, reload on change, log every change. |

### Anti-Features

| Feature | Why Requested | Why Problematic | Alternative |
|---|---|---|---|
| External message broker (Redis, Kafka) for v1 | "Production-grade" | Adds a process to manage, a serialization format to debug, and reconnect logic to write. Single-process asyncio is sufficient at 1m+ bars | Defer until the system actually spans processes. |
| Silent risk-check bypass mode | "I want to test what would happen without limits" | The path "I'll just disable it for a sec" is how every catastrophic loss happens | If needed, expose as a `simulate_no_risk` backtest mode — but the *live* pipeline must never have this switch. |
| Auto-restart after kill switch trips | "Self-recovery" | Kill switch should require human acknowledgement of the reason | Manual `/resume` only. Log the resume event with operator note. |
| Combined "halt and flatten" mega-button | "One click to stop everything" | Conflating intent: "stop trading" vs "exit positions" mean very different things on a real account | Two separate controls, two separate confirmations. |
| Real-time signal Slack/Discord/SMS push in v1 | "I want to know when ORB fires" | Adds external secrets, rate limits, network failure modes. Out of scope. | UI WebSocket is the channel. Add notifications later if proven useful. |

---

## 6. Risk Manager

### Table Stakes

| Feature | Why Expected | Complexity | Notes |
|---|---|---|---|
| ATR-based position sizing formula, single source of truth | PROJECT.md spec. The formula must live in exactly one place | S | `contracts = floor(risk_$ / (stop_ticks × tick_value))`. Take `tick_value` from the symbol registry, never inline. |
| Max-contracts hard cap | Apex / Topstep both impose contract caps. Prop-firm parity. | S | Per-strategy and global. Reject any signal that would exceed. |
| Daily-drawdown circuit breaker ($2k default) | PROJECT.md spec | S | See Signal Pipeline. The math lives here; the action lives in Signal Pipeline. |
| **Prop-firm-style trailing drawdown** (Apex / Topstep model) | PROJECT.md framing: this is the path to funded capital. Live math must match what the prop firm will judge you on | M | Trailing high-water mark, drawdown floor at HWM − $2k (or $2.5k for $50k Apex). Track separately from "session drawdown." Read the Apex / Topstep rule docs precisely — both intraday-trailing and EOD-trailing variants exist (Apex 4.0). |
| Pre-trade checks (capital available, contracts available, DD ok, session ok) | One failure path: "We took the trade but couldn't actually" | S | All checks idempotent + side-effect-free. Decision logged. |
| Post-trade state: realized P&L, open exposure, equity HWM | PROJECT.md spec. Drives the trailing DD math | S | Updated atomically after each fill. |
| Session boundary risk (no new entries after T-N minutes before close) | A 15:58 entry on a 1m chart can't realistically work | S | "No new trades after 15:50 ET" — configurable. |
| Risk rules as data, not code | When you discover "I want max-3-trades-per-day," editing Python is friction | M | TOML/JSON `risk_rules.toml` schema. Risk manager interprets it. |
| MES vs ES sizing handled at the risk layer | PROJECT.md: signals reason in ES; risk manager converts to MES contracts | S | Risk manager knows: "I have a 4-point stop, $50 risk budget → MES has tick_value 1.25, so contracts = floor(50 / (16 × 1.25)) = 2." |
| Audit-loggable risk decision (APPROVED with sized N, REJECTED with reason) | Same audit trail as signal pipeline | S | Single source of truth for "why did/didn't we trade?" |

### Differentiators

| Feature | Value Proposition | Complexity | Notes |
|---|---|---|---|
| Multiple prop-firm presets (Apex 4.0 intraday, Apex 4.0 EOD, Topstep, Tradeify, Bulenox) | Test the same strategy under different rulesets | S | Each preset is a `risk_rules.toml`. |
| Volatility-adjusted risk caps (cut size on high-ATR days) | High-ATR days slip more and have wider tails. Static sizing is too aggressive | M | Risk-$ scales with `current_ATR / median_ATR`. |
| "Soft" warnings before hard breaches (80% of DD limit) | The single most useful UX feature for not getting busted by the prop firm | S | Logged + surfaced in UI. Doesn't change behavior. |
| Per-strategy correlation cap (don't take signal B if it correlates 0.9 with already-open signal A) | Avoids "ORB and trend strategy both got long" double-down | M | Pairwise return correlation tracked. Veto on threshold. |
| Auto-pause on N consecutive losers | Captures "something is wrong" without waiting for DD | S | E.g., after 5 stop-outs in a row, pause that strategy and notify. |

### Anti-Features

| Feature | Why Requested | Why Problematic | Alternative |
|---|---|---|---|
| Risk override / "I know what I'm doing" toggle | "Just this once" | Eliminates the entire reason the risk manager exists. Live, this is how accounts blow up. | No override. To trade past the limit, edit risk config explicitly (which is logged). |
| Position pyramiding by default | "Add to winners" | Inflates fragility under noise; very few intraday strategies survive scrutiny here | If wanted, must be an opt-in per-strategy feature, not a global default. |
| Kelly criterion sizing | Mathematically tempting | Kelly assumes known edge and infinite reinvestment; intraday futures violates both. Half-Kelly still oversizes. | Fixed-fractional ATR sizing is robust. Surface "what Kelly would say" as informational only. |
| Cross-strategy compounding within the trading day | "Use ORB profits to fund mean-reversion entries" | Mid-day capital is path-dependent; coupling strategies amplifies drawdowns | Each strategy uses its day-start allocation. Reconcile at session close. |
| "Risk by % of P&L today" rules | Sounds like discipline | Behavioral trap: a strategy that risks less after losses and more after wins is hot-handing. Anti-Kelly | Static $-risk per trade. Adjust via volatility, not via P&L. |

---

## 7. UI (FastAPI + Next.js + Lightweight Charts, Bloomberg-style)

### Table Stakes

| Feature | Why Expected | Complexity | Notes |
|---|---|---|---|
| Dense, dark, monospace, multi-pane grid layout | PROJECT.md mandates Bloomberg-style. Whitespace-heavy "modern" SaaS UI is the wrong vibe | M | CSS grid; configurable rows/cols. Default 2×2 with chart top-left, blotter top-right, history bottom-left, controls bottom-right. |
| **Live chart panel** with: ES candles, ORB box overlay, signal markers, active stop/target lines | PROJECT.md spec | M | TradingView Lightweight Charts v5. Custom series for ORB box and signal markers. Stop/target as horizontal lines that update live. |
| **Order blotter panel**: open positions with avg price, unrealized P&L, distance to stop | PROJECT.md spec | M | Update via WebSocket; updates at every bar close + every state change. Sort by strategy. |
| **Trade history panel**: closed trades table + running equity curve + daily/cumulative stats | PROJECT.md spec | M | Two sub-panes: scrollable trade table on top, equity curve below. Click trade → chart jumps to that bar. |
| **Strategy controls panel**: toggle strategy on/off, edit ORB params live, kick off backtests, view optimization heatmaps | PROJECT.md spec | M | Param edits go through risk config reload, NOT mid-flight strategy edits. |
| WebSocket-driven live updates with REST snapshot on connect | Industry-standard pattern; PROJECT.md endpoints spec | M | On connect: REST GET full state. After: WebSocket diffs. Reconnect: REST again. |
| Kill switch button + flatten-all button (separate, distinct, separately confirmed) | Safety. Most consumer trading UIs get this wrong | S | Two physically separate buttons. Different colors. Different hotkeys. Different confirmation dialogs. |
| Hotkeys: `F` = flatten-all, `K` = kill, `P` = pause strategy, `?` = help | Bloomberg / DOM / OpenBB all keyboard-driven. Mouse-only is slow | S | All hotkeys discoverable via `?`. Display modifier (`Ctrl+`) for destructive ones. |
| ET clock (with seconds) prominently shown | Intraday operator needs to know "are we 4 minutes from close?" at a glance | S | Top bar. Bonus: also show time-until-session-close countdown. |
| "Strategy state" widget: armed / paused / killed; LED-style status indicator | A glance must reveal whether the system is even trading | S | One pill per strategy, three colors. |
| Connection status (data feed, backend) visible always | Silent disconnects are the worst class of UI bug | S | Top bar dot. Red = offline. Reconnecting state visible. |
| All numeric values monospaced, right-aligned, with consistent decimal places | Bloomberg-density requirement. Floats jittering left/right is unreadable | S | Tabular-nums CSS. Format per quantity type. |

### Differentiators

| Feature | Value Proposition | Complexity | Notes |
|---|---|---|---|
| **Command bar** (Bloomberg `/`-style or VS Code `Ctrl+K`) | Power-user navigation: `/jump 14:30`, `/strategy orb_v2`, `/backtest`, `/optim` | M | Single text input, fuzzy-matched against a registry of commands. Bloomberg's killer feature in spirit, not in literal keys. |
| **Replay scrubber** for historical data | Drag time slider, watch the chart + blotter + history advance bar-by-bar. Bridges backtest and live | M | Driven by Signal Pipeline replay mode. Speed control 1×/4×/16×/max. TradingView Lightweight Charts supports it natively. |
| Saved layouts (per workflow: "research view," "trading view," "optimization view") | Operator switches modes during the day | M | Persist grid config + widget params to local JSON. |
| TradingView MCP chart sync | PROJECT.md first-class | M | Two-way sync of focused symbol / time / drawings. Use `chart_set_symbol`, `chart_scroll_to_date`, `draw_shape` from MCP. |
| "Forensic" panel: click a trade, see signal payload, risk decision, fill events, equity at that moment | Audit + learning tool | M | Joins the audit log tables. |
| 2-param heatmap viewer with interactive picker | PROJECT.md spec; rendering quality matters | M | Hover shows full metric set; click loads that param set into the controls panel. |
| Walk-forward fold viewer (IS / OOS overlay per fold) | Reveals overfit at a glance | M | Per-fold equity curves overlaid; OOS in solid color, IS in faint. |
| Trade-flag annotations on the chart (entry, stop, target, exit reason) | Marker click → forensic panel | M | Use Lightweight Charts markers + tooltips. |
| Bar replay synced across panels | Move the scrubber → chart, blotter, history all rewind together | M | Single replay clock, broadcast to all panels. |
| Light keyboard chord support for symbol/timeframe (`G E S`, `T 5`, etc.) | Bloomberg `<F8>` `equity` `<GO>` aesthetic | S | Optional, but cheap to add once command bar exists. |

### Anti-Features

| Feature | Why Requested | Why Problematic | Alternative |
|---|---|---|---|
| Live broker order entry from UI | "Real-trading polish" | Out of scope per PROJECT.md. Removes the bulk of safety work for v1 | Paper executor only. UI surfaces paper P&L. |
| Mobile / responsive layout | "It'd be cool on phone" | Dense Bloomberg-style does not work on mobile. Trying to make it inflates CSS scope and waters down the desktop experience | Desktop-only. Lock min-width 1280px. |
| Light-mode / theme switcher in v1 | DX shiny | Dark is the spec; light mode doubles design QA without serving the user (single operator who wants dark) | Defer; keep CSS variables so a light theme is *possible* later, but ship one theme. |
| Animations, transitions, "modern" UI flourishes | Default React component libraries ship these | Distract from numbers; add render cost; Bloomberg-style is intentionally austere | Instant state changes. No animation on data updates. |
| "Charts that look like TradingView" with hundreds of indicators built in | Feature comparison | We HAVE TradingView via MCP. Replicating it in-app is duplicate effort and worse UX | The UI chart shows what backend signals say. For deep TA, use TradingView Desktop via MCP. |
| Auto-trade-execution buttons on the chart (drag stop, drag target → modify order) | "TradingView-style trading from chart" | Risky shortcut surface in a paper system, dangerous if a live broker is added later. Out of scope for v1 | Strategy controls panel only. No in-chart order modification. |
| Real-time P&L animation (counters spinning, color flashes) | "Feels alive" | Encourages screen-glued behavior, biases toward over-trading | Update on bar close, with single-frame highlight. No spinning. |
| Generic "alerts" subsystem in v1 | "Bloomberg has alerts" | Adds notification scheduler, secrets, rate limits | TradingView MCP `alert_create` for alerts; UI surfaces them. No in-app notification engine. |
| In-app strategy editor (write Python in the browser) | "Notebook-style" | Encourages mid-flight edits; defeats reproducibility | Strategies live in `.py` files; UI shows current code in read-only view. |
| Configurable column sets and column orders for every table on day 1 | Looks customizable | Inflates UI state and persistence. One thoughtful default beats infinite knobs | Ship opinionated defaults. Add reorder/show-hide only after operator asks. |

---

## Cross-Module Feature Dependencies

```
[Tick-value & contract registry (Module 1)]
        ├──required by──> [Backtest P&L math (3)]
        ├──required by──> [Risk Manager ATR sizing (6)]
        └──required by──> [Signal Pipeline (5)]

[Bar schema + RTH filter (1)]
        ├──required by──> [Strategy Engine (2)]
        └──required by──> [Backtester (3)]

[CME calendar + rollover detection (1)]
        ├──required by──> [Backtester reproducibility (3)]
        └──required by──> [Signal Pipeline session gating (5)]

[Strategy ID + version (2)]
        ├──required by──> [Audit log (5)]
        ├──required by──> [Backtest run hash (3)]
        └──required by──> [Optimization fold persistence (4)]

[Backtest engine (3)]
        ├──required by──> [Optimization (4)]
        └──enhances────> [Replay mode (5/7)]

[Risk Manager decision (6)]
        ├──required by──> [Signal Pipeline gate (5)]
        └──required by──> [Audit log "why rejected?" (5/7)]

[Audit log (5)]
        ├──required by──> [Forensic panel (7)]
        ├──required by──> [Replay scrubber (7)]
        └──required by──> [Reproducibility test (3)]

[Signal Pipeline pub/sub (5)]
        ├──required by──> [Live chart panel (7)]
        ├──required by──> [Blotter (7)]
        └──required by──> [Strategy state widget (7)]

[TradingView MCP integration (7)]
        ├──enhances────> [Forensic panel (7)]
        └──enhances────> [Data quality reconciliation (1)]

[Kill switch / flatten-all (5)]
        ├──required by──> [UI controls (7)]
        └──conflicts───> [Auto-restart-on-halt (anti-feature)]

[Walk-forward + IS/OOS persistence (4)]
        └──required by──> [Optimization heatmap viewer (7)]
```

### Dependency Notes

- **Symbol registry (Module 1) is upstream of everything that touches dollars.** The single most-leveraged 200 lines of code in the project. Build it first, in its own module, with a unit test that asserts MES tick_value = 1.25 and ES tick_value = 12.50.
- **Backtester (3) is upstream of Optimization (4).** Cannot meaningfully optimize until backtests are deterministic and leakage-checked.
- **Signal Pipeline audit log (5) is upstream of the forensic panel and replay scrubber (7).** Without rich audit data, the UI features that justify Bloomberg-style density become facades.
- **Risk Manager decision schema (6) is upstream of the audit log (5).** Build the decision dataclass before wiring the bus.
- **Kill switch + flatten-all (5) conflict with auto-restart-on-halt (correctly marked anti-feature).** Human-acknowledgement gate must be enforced.
- **Walk-forward (4) is upstream of any honest leaderboard.** Without it, the optimization module produces overfit recommendations.
- **TradingView MCP (7)** is an enhancer for several modules but is not on the critical path for v1 correctness. Wire it after the rest of the pipeline is trustworthy.

---

## MVP Definition

### Launch With (v1) — "Trust the numbers" baseline

The minimum to make the project's core value testable: a strategy can be researched, optimized, paper-traded, and the system's numbers are reproducible and honest.

- [ ] **Symbol registry with tick values** — every downstream P&L depends on it (S)
- [ ] **Twelve Data REST ingestion → DuckDB with UTC storage, RTH filter, CME calendar, gap detection** — Module 1 table stakes (M)
- [ ] **Continuous front-month with documented back-adjustment** — without this, charts lie on roll day (M)
- [ ] **`Strategy` base + ORB reference strategy** — PROJECT.md seed strategy (M)
- [ ] **Indicator layer (ATR, VWAP, EMA, ADR)** with bar-aligned look-ahead-zero contract (M)
- [ ] **Backtester: next-bar-open fills, tick slippage, per-side commission, full attribution ledger** (M)
- [ ] **Look-ahead leakage detector (1-bar-delay comparison test)** — non-negotiable for the trust thesis (M)
- [ ] **Standard metrics + MAE/MFE per trade** (S)
- [ ] **Grid search + walk-forward with IS/OOS leaderboard + 2-param heatmap** (M)
- [ ] **Signal Pipeline: asyncio bus, risk gate, paper executor, full audit log** (M)
- [ ] **Kill switch + flatten-all (separate)** (S)
- [ ] **Risk Manager: ATR sizing, daily DD circuit breaker, trailing prop-firm DD, max contracts, MES sizing conversion** (M)
- [ ] **UI: chart + blotter + history + controls panels, dark dense layout, WebSocket-driven, kill/flatten hotkeys** (L)
- [ ] **Reproducibility test in CI: same input → same equity curve, bitwise** (S)

### Add After Validation (v1.x) — once the core loop is verified

Triggered by: the first strategy survives walk-forward + 1 month of paper.

- [ ] Command bar (Bloomberg `/`-style)
- [ ] Replay scrubber synced across panels
- [ ] Monte Carlo trade-shuffle confidence bands
- [ ] Edge ratio / WF stability flags in optimizer
- [ ] Forensic panel (click trade → full audit chain)
- [ ] TradingView MCP chart sync + drawing of ORB/entries/stops
- [ ] Multi-prop-firm preset risk rule sets (Apex 4.0 IT, Apex 4.0 EOD, Topstep, Tradeify)
- [ ] Saved layouts
- [ ] "Soft" warnings at 80% of DD limit
- [ ] Side-by-side backtest diff

### Future Consideration (v2+) — defer until operator pulls

- [ ] Multi-strategy concurrent execution (independent capital silos)
- [ ] Multi-source data reconciliation (TV MCP vs Twelve Data)
- [ ] Per-strategy correlation cap
- [ ] Bar-volume-throttled fill model
- [ ] Bayesian/genetic optimization (explicitly out of scope per PROJECT.md but reconsider after v1.x stable)
- [ ] Live broker adapter (currently out of scope; gate behind dedicated milestone)
- [ ] Multi-timeframe within one strategy
- [ ] Hot-reload of strategy code

---

## Feature Prioritization Matrix (top-15)

| Feature | User Value | Implementation Cost | Priority |
|---|---|---|---|
| Symbol/tick-value registry | HIGH | LOW | P1 |
| UTC storage + RTH filter + CME calendar | HIGH | LOW | P1 |
| Continuous front-month + rollover handling | HIGH | MEDIUM | P1 |
| `Strategy` + ORB reference | HIGH | MEDIUM | P1 |
| Next-bar-open fills + slippage + commission | HIGH | LOW | P1 |
| Look-ahead leakage detector | HIGH | MEDIUM | P1 |
| Walk-forward IS/OOS | HIGH | MEDIUM | P1 |
| Audit log of signal → decision → fill | HIGH | MEDIUM | P1 |
| Kill switch + flatten-all (separate) | HIGH | LOW | P1 |
| Trailing prop-firm drawdown + daily DD breaker | HIGH | MEDIUM | P1 |
| Dense dark UI grid (chart/blotter/history/controls) | HIGH | HIGH | P1 |
| Hotkeys (F/K/P/?) | MEDIUM | LOW | P1 |
| Reproducibility CI test | HIGH | LOW | P1 |
| 2-param heatmap | MEDIUM | MEDIUM | P2 |
| Command bar | MEDIUM | MEDIUM | P2 |
| Replay scrubber | MEDIUM | MEDIUM | P2 |
| Monte Carlo trade-shuffle | MEDIUM | MEDIUM | P2 |
| TradingView MCP chart sync | MEDIUM | MEDIUM | P2 |
| Forensic panel | MEDIUM | MEDIUM | P2 |
| Multi-prop-firm presets | LOW | LOW | P2 |
| Multi-strategy execution | LOW | HIGH | P3 |
| Multi-source data reconciliation | LOW | MEDIUM | P3 |

**Priority key:** P1 = must have for v1 launch; P2 = should have, add in v1.x after validation; P3 = v2+.

---

## Competitor / Reference Feature Analysis

| Feature | NautilusTrader | Backtrader | VectorBT | TopstepX / Apex / Tradovate | Bloomberg / OpenBB | Our Approach |
|---|---|---|---|---|---|---|
| Bar / tick fills | Tick-level via L2 order book | Bar-level with slippage callbacks | Vectorized, bar-level with slippage models | Live broker (not applicable) | n/a | Bar-level next-bar-open + tick slippage |
| Walk-forward | Native | Add-on | Native via param sweep | n/a | n/a | Native, IS/OOS persistence + heatmap |
| Look-ahead detection | Engine architecture prevents most | Manual discipline | Manual discipline | n/a | n/a | Explicit 1-bar-delay leakage test in CI |
| Audit / replay | Event-sourced from inception | Limited | Trade ledger | Real | n/a | DuckDB audit log + replay mode |
| Prop-firm trailing DD | No native concept | Manual | Manual | Native, enforced firm-side | n/a | First-class risk rule |
| Kill switch + flatten | Not OOTB | Not OOTB | n/a | Firm-side enforced | n/a | First-class; two separate controls |
| Dense terminal UI | n/a | n/a | n/a | Dark, multi-pane | Dense, keyboard-driven, command-driven | Bloomberg-style dark grid + command bar |
| Replay scrubber | Backtest reruns | n/a | n/a | n/a | n/a | UI scrubber drives Signal Pipeline replay |
| 2-param heatmap | Via plotly | Via add-on | Native | n/a | n/a | Native, click-loads-params UX |

---

## Sources

### Backtesting frameworks
- [Backtrader: Commission Schemes](https://www.backtrader.com/docu/commission-schemes/commission-schemes/) — futures commission and margin semantics
- [Backtrader: Slippage](https://www.backtrader.com/docu/slippage/slippage/) — fixed and percentage slippage, per-order-type behavior
- [NautilusTrader: Backtesting](https://nautilustrader.io/docs/latest/concepts/backtesting/) — L2/L3 slippage, futures activation/expiration, tick-level realism
- [VectorBT: Getting started](https://vectorbt.dev/) — Numba-vectorized backtesting, native heatmap
- [Battle-Tested Backtesters: VectorBT, Zipline, Backtrader](https://medium.com/@trading.dude/battle-tested-backtesters-comparing-vectorbt-zipline-and-backtrader-for-financial-strategy-dee33d33a9e0) — feature comparison
- [Choosing the Best Backtesting Software for Futures (QuantStrategy.io)](https://quantstrategy.io/blog/choosing-the-best-backtesting-software-for-futures-a/) — futures-specific feature inventory
- [Backtrader vs NautilusTrader vs VectorBT vs Zipline-reloaded (autotradelab)](https://autotradelab.com/blog/backtrader-vs-nautilusttrader-vs-vectorbt-vs-zipline-reloaded) — framework selection criteria

### Backtest realism / pitfalls
- [Look-Ahead Bias in Backtests (Michael Harris)](https://mikeharrisny.medium.com/look-ahead-bias-in-backtests-and-how-to-detect-it-ad5e42d97879) — detection methodology
- [Look-Ahead Bias: The Invisible Killer (Quantreo)](https://www.newsletter.quantreo.com/p/look-ahead-bias-the-invisible-killer) — detection: delay-features test
- [Freqtrade: Lookahead Analysis](https://www.freqtrade.io/en/stable/lookahead-analysis/) — production-ready leakage detector design
- [Backtesting Limitations: Slippage and Liquidity (LuxAlgo)](https://www.luxalgo.com/blog/backtesting-limitations-slippage-and-liquidity-explained/) — practical slippage values
- [QuantConnect: Slippage](https://www.quantconnect.com/docs/v2/writing-algorithms/reality-modeling/slippage/key-concepts) — slippage modeling primitives

### Walk-forward / optimization
- [Walk-Forward Optimization (StrategyQuant)](https://strategyquant.com/doc/strategyquant/walk-forward-optimization/) — IS/OOS partitioning, fold mechanics
- [QuantConnect: Walk Forward Optimization](https://www.quantconnect.com/docs/v2/writing-algorithms/optimization/walk-forward-optimization) — algorithm spec
- [Walk-Forward Optimization (QuantInsti)](https://blog.quantinsti.com/walk-forward-optimization-introduction/) — anchored vs rolling, edge ratio
- [Robustness Testing for Algo Trading Strategies (BuildAlpha)](https://www.buildalpha.com/robustness-testing-guide/) — Monte Carlo trade shuffle, perturbation
- [Interpretable Hypothesis-Driven Trading (arXiv 2512.12924)](https://arxiv.org/html/2512.12924v1) — parameter stability heatmap example
- [Novel approach to trading strategy parameter optimization (arXiv 2602.10785)](https://arxiv.org/html/2602.10785) — double OOS, block bootstrap

### CME / futures data
- [CME Group: Equity Index Roll Dates](https://www.cmegroup.com/trading/equity-index/rolldates.html) — authoritative rollover schedule
- [Continuous Futures Data Explained (QuantVPS)](https://www.quantvps.com/blog/continuous-futures-contracts-explained) — back-adjustment methods
- [Understanding Futures Contract Rolls (Trade Brigade)](https://tradebrigade.co/understanding-futures-contract-rolls/) — ES/NQ practical rollover practice

### Prop-firm risk model
- [Topstep: Daily Loss Limit](https://help.topstep.com/en/articles/8284207-what-is-the-daily-loss-limit-and-what-happens-if-i-exceed-it) — auto-liquidation behavior
- [Apex: Intraday Trailing Drawdown Explained](https://support.apextraderfunding.com/hc/en-us/articles/45683513113115-Intraday-Trailing-Drawdown-Explained) — trailing DD math
- [Best Prop Firm Trading Platforms 2026 (Damn Prop Firms)](https://damnpropfirms.com/best-prop-firm-trading-platforms/) — TopstepX / Tradovate / Rithmic feature comparison
- [Topstep vs Apex vs Bulenox (QuantVPS)](https://www.quantvps.com/blog/topstep-vs-apex-vs-bulenox) — risk parameter comparison
- [Trailing Drawdown explained (Propfirmapp)](https://propfirmapp.com/learn/trailing-drawdown) — variants (intraday vs EOD)
- [Prop Firm Compliance Dashboard (TradesViz)](https://www.tradesviz.com/blog/prop-firm-compliance-tracking/) — UI patterns for DD buffer visualization

### ORB strategy
- [Opening Range Breakout Strategy (TradeThatSwing)](https://tradethatswing.com/opening-range-breakout-strategy-up-400-this-year/) — rules-based ORB
- [Opening Range Breakout (LiteFinance)](https://www.litefinance.org/blog/for-beginners/trading-strategies/opening-range-breakout-strategy/) — parameter ranges
- [ORB Trading Strategy for Futures (MetroTrade)](https://www.metrotrade.com/orb-open-range-breakout-trading-strategy/) — ES-specific implementation notes
- [ORB Backtest (QuantifiedStrategies)](https://www.quantifiedstrategies.com/opening-range-breakout-strategy/) — historical edge data
- [Micro Futures for Volatility Trading (VolatilityBox)](https://volatilitybox.com/research/micro-futures-for-volatility-trading/) — MES sizing math
- [Futures Contract Specifications 2026 (ProptradingVibes)](https://proptradingvibes.com/blog/futures-contract-specifications) — ES/MES tick values

### Bloomberg / OpenBB / dense UI
- [Bloomberg Keyboard (FGCU)](https://library.fgcu.edu/bloomberg/keyboard) — keyboard-first navigation reference
- [Bloomberg Tips & Tricks (INSEAD)](https://www.insead.edu/sites/insead/files/assets/dept/library/docs/bloomberg-tips-tricks--shortcuts.pdf) — command bar, function codes
- [OpenBB Terminal Structure & Navigation](https://docs.openbb.co/cli/structure-and-navigation) — keyboard-driven menus
- [OpenBB Terminal 2.0](https://openbb.co/blog/openbb-terminal-2-acai) — dashboards (Streamlit, Voila, Next.js+FastAPI) reference for our stack choice

### TradingView / Lightweight Charts
- [TradingView Lightweight Charts](https://www.tradingview.com/lightweight-charts/) — 45KB chart library
- [Lightweight Charts: Panes](https://tradingview.github.io/lightweight-charts/docs/panes) — multi-pane primitive
- [Lightweight Charts v5 release](https://www.tradingview.com/blog/en/tradingview-lightweight-charts-version-5-50837/) — current major
- [TradingView Synchronized Bar Replay](https://www.tradingview.com/blog/en/synchronized-bar-replay-45933/) — replay scrubber UX reference
- [TradingView Multi-chart Layouts](https://www.tradingview.com/support/solutions/43000629990-leveraging-multi-chart-layouts-in-your-analysis/) — dense workspace UX

### Algo trading risk / pipeline
- [Trading System Kill Switch (NYIF)](https://www.nyif.com/articles/trading-system-kill-switch-panacea-or-pandoras-box) — kill-switch design considerations
- [FINRA: Market Access](https://www.finra.org/rules-guidance/guidance/reports/2021-finras-examination-and-risk-monitoring-program/market-access) — regulatory framing of pre-trade risk checks
- [Risk Management Strategies for Algo Trading (LuxAlgo)](https://www.luxalgo.com/blog/risk-management-strategies-for-algo-trading/) — pipeline pattern (signal → risk → execution → audit)
- [Data Pipeline Design in an Algorithmic Trading System (Edwin Salguero)](https://medium.com/@edwinsalguero/data-pipeline-design-in-an-algorithmic-trading-system-ac0d8109c4b9) — pub/sub patterns

---

*Feature research for: intraday ES futures backtest + paper-trading system with Bloomberg-Terminal-style UI*
*Researched: 2026-05-14*
