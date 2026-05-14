# Research Synthesis — ES Futures Backtest + Paper-Trading System

**Researched:** 2026-05-14
**Inputs:** STACK.md, FEATURES.md, ARCHITECTURE.md, PITFALLS.md, PROJECT.md
**Overall confidence:** HIGH on architecture, stack mechanics, and pitfall taxonomy. MEDIUM on the Twelve Data provider for ES specifically (see Critical Finding #1).

The product is a single-operator local desktop-web application whose only deliverable is **trustworthy numbers**. Every roadmap decision below subordinates to that thesis: stack pins, architecture seams, MVP scope, and pitfall gates exist to make a backtest result reproducible, leakage-free, and survivable across walk-forward.

---

## Project Stack Summary

| Layer | Pick | Pinned Version |
|-------|------|----------------|
| Language / pkg | Python **3.11–3.12** (NOT 3.13) + **uv** + `uv.lock` committed | uv 0.11.x |
| Web (Py) | **FastAPI** + uvicorn[standard] + **Pydantic v2** | FastAPI 0.136.x, Pydantic 2.13.x |
| HTTP | **httpx** (sync+async, one API) | 0.27.x |
| Data | **pandas 2.2.x** (NOT 3.0) + polars 1.x on hot paths | pandas `>=2.2,<3.0` |
| Indicators | **pandas-ta-classic** + hand-rolled ATR (Wilder), VWAP, ORB high/low | — |
| Storage | **DuckDB 1.x + Parquet** (Hive-partitioned `symbol=/year=/month=`), single-writer | — |
| Calendars | **pandas_market_calendars** `CME_Equity` (NOT NYSE) | 5.x |
| Logging | **structlog** (JSON, correlation IDs) | latest |
| Backtest | **vectorbt OSS** | **1.0.0** |
| Frontend | **Next.js 16.2** + React 19 + TypeScript 5 | — |
| Charts | **lightweight-charts** vanilla (NO React wrapper) | **5.2.0** |
| FE state | TanStack Query v5 + Zustand + native WebSocket | — |
| Data provider | **Twelve Data REST** — wrapped behind `DataSource` interface (see Critical Finding #1) | latest |
| TradingView | `tradingview-mcp-jackson` MCP server, stdio subprocess of Core, supervised | 78 tools (already wired) |
| Test | pytest + pytest-asyncio + hypothesis + respx + freezegun | — |

Repo: **uv workspace monorepo**. Python lives in `packages/{trading-core, api, tv-bridge}`. Frontend lives in `apps/web/`. Config in YAML at repo root; secrets in `.env` (gitignored). NO Turborepo, NO Docker, NO Postgres for v1.

Full justification + version-compat matrix in `STACK.md` §"Version Compatibility Matrix" and §"What NOT to Use".

---

## Critical Findings

These came up across multiple researchers and must NOT be lost in roadmap planning.

### 1. Twelve Data does NOT cover ES futures (verified 2026-05-14)

Stack researcher checked Twelve Data's `/exchanges`, `/market-data`, and the official Python client README. Catalog is **Stocks / Forex / ETFs / Crypto / Commodities / Indices** — **CME equity-index futures (ES, MES) are NOT documented as supported**. The "Indices" page was "coming soon" as of May 2026.

**Mitigation (v1):** Use **SPY** (1m bars on Twelve Data, RTH 9:30–16:00 ET, tracks SPX/ES at 0.1× scale) as the working symbol behind the `DataSource` interface. ES port is mechanical (multiply by 10, swap tick value) once a futures-aware provider is plugged in.

**Roadmap impact:** A **data-provider validation spike must precede any strategy/optimization commit**. Until the spike resolves, the `DataSource` interface is doing more work than usual — every line of strategy code must be portable across SPY-Twelve-Data and (future) ES-Databento.

Sources: STACK.md §"Critical Caveat", §"Open Questions" #1; PROJECT.md "Twelve Data primary feed" constraint.

### 2. Same-bar fill leakage + bar-timestamp ambiguity is the #1 backtest correctness pitfall

Pitfalls cluster MD-4 + BL-1 + BL-2 + FR-2: Twelve Data labels bars by **open** time; VectorBT's default `from_signals` fills on the same bar's close; indicators computed through bar `t` include bar `t`'s high/low. Combined, these produce backtests with Sharpe > 4 that are pure look-ahead.

**Mitigation:** Wrap VBT in a `safe_from_signals()` helper that mandates `entries.shift(1)` and `price='nextbar'`. Add a "perfect lookahead returns finite Sharpe" assertion test — if a strategy using `close.shift(-1)` produces a finite (not infinite) Sharpe through the helper, the helper is broken.

**Roadmap impact:** This must be a **Phase-3 (Backtester) gate**. The first integration test of the engine is the lookahead assertion. No optimization work proceeds until this test is green.

Sources: PITFALLS.md MD-4, BL-1, BL-2, FR-2, OP-2; STACK.md §"Open Questions" #6.

### 3. Same `Strategy.on_bar()` code path in backtest and live is the load-bearing architectural invariant

Both the backtester (driven by a `SyntheticClock` over historical bars) and the live engine (driven by real bars off the bus) call the same `Strategy.on_bar(bar) -> Signal | None`. Same signal class, same risk manager, same paper executor. Only `DataSource` and (eventually) `Executor` swap.

**This is what makes "trust the numbers" achievable.** Backtrader, NautilusTrader, AAT all converged on this pattern; the projects that didn't are full of "why does live disagree with backtest" forensic investigations.

**Roadmap impact:** The four load-bearing `Protocol` seams (`DataSource`, `Strategy`, `RiskManager`, `Executor`) must be established in Phase 1–2. Any "backtest-specific shortcut" that bypasses one of them is technical debt that breaks the core thesis.

Sources: ARCHITECTURE.md §"System Overview" key choices, §"Anti-Pattern 1"; FEATURES.md §0 reading guide.

### 4. Prop-firm trailing drawdown has multiple variants — encode as an enum

Apex / Topstep / Bulenox / Tradeify each implement DD differently: **STATIC**, **TRAILING_EOD** (HWM updates on realized EOD equity only), **TRAILING_INTRADAY** (HWM tracks unrealized equity in real time). For a $50k Apex account the trailing floor is `hwm - $2,500`; touching $52.5k unrealized then giving back $500 silently blows the account if you tracked static DD only.

**Mitigation:** `DrawdownModel` enum + risk manager tracks **all three side-by-side in the audit log**, with the UI surfacing all three so a misconfiguration is visible. HWM must be **persisted to DuckDB on every update** (RM-6) — process restart must NOT reset HWM.

**Roadmap impact:** Phase 5 (Risk Manager) needs per-variant unit tests as a gate. The v1 default is `TRAILING_INTRADAY` (Apex). Multi-firm presets are P2 (v1.x).

Sources: PITFALLS.md RM-2, RM-4, RM-6; FEATURES.md §6 table stakes; PROJECT.md "prop-firm framing" context.

### 5. Vertical-MVP slice is Phase 3 — the integration gate, not Phase 9 polish

The minimum end-to-end demonstrably-useful system is: **pull one day of 1m bars → run ORB → emit one signal → paper-fill it → see candles + that signal + that fill on the Next.js chart**. Phases 1–2 are foundation/data; Phase 3 closes the visible loop.

Every later phase is **incremental depth on top of this skeleton**, not new structure. If something is fundamentally wrong with the architecture, Phase 3 surfaces it.

**Roadmap impact:** Phase 3 is the load-bearing milestone. Don't let "build everything in parallel" tempt the team into shipping the full backtester before the vertical slice closes. Backtest engine sophistication (Phase 4) happens AFTER the slice proves the pipes are connected.

Sources: ARCHITECTURE.md §"Suggested Build Order" Phase 3, §"dependency graph"; FEATURES.md §"MVP Definition".

### 6. TradingView MCP is a visualization peer, not a data source

Python (Twelve Data, or whatever the `DataSource` resolves to) is **canonical**. TV MCP is:
- (a) An **output surface** — every signal and fill is auto-drawn on the live TV chart via `draw_shape` (subscribes to `signals` + `fills` topics).
- (b) An **optional alternative `DataSource`** — `TVReplayDataSource` fetches bars from a TV replay session, useful for cross-validating Twelve Data.
- (c) A **manual alert authoring surface** — UI button → `alert_create`.

**Daily reconciliation:** at ingest, pull `data_get_ohlcv` from TV for the same RTH window and compare bar-by-bar against Twelve Data. Threshold: > 0.05% price difference on any bar raises an alert (TV-2).

**Failure isolation rule:** TV down ≠ trading halts. TVBridge is a bus *subscriber*, not a pipeline step. MCP errors are logged, not propagated (Anti-Pattern 4).

**Roadmap impact:** TV MCP wiring is **Phase 6** (after Phase 3 vertical slice + Phase 4 backtest + Phase 5 risk are solid). TV is decoration on top of a working brain, not part of the brain.

Sources: ARCHITECTURE.md §"TradingView MCP Integration" + §"Three roles TV plays"; PITFALLS.md TV-2, TV-4; PROJECT.md "Python is the brain".

### 7. Stack pinning matters — `uv.lock` is committed before first backtest

For reproducibility ("trust the numbers"):
- **`vectorbt==1.0.0`** (Apr 22, 2026 OSS finalization; pin exactly).
- **`pandas>=2.2,<3.0`** (pandas 3.0's Copy-on-Write + str-dtype defaults will silently change vectorbt outputs; wait until VBT publishes 3.0 support).
- **Python 3.11–3.12** (NOT 3.13 — numba/numpy/pandas wheel lag).
- **`uv.lock` is platform-resolution-complete** and committed *before* the first backtest is run. Backtest-result hashes (`git_sha`, `data_hash`, `param_hash`, `seed`) are only meaningful against a frozen environment.

**Roadmap impact:** Phase 1 (Foundation) includes locking the env and committing `uv.lock`. The reproducibility CI test (OP-2, OP-6) compares against the locked environment.

Sources: STACK.md §"Version Compatibility Matrix"; PITFALLS.md OP-2, OP-6.

---

## Feature Highlights

Compressed from FEATURES.md. Full module-by-module breakdown lives there.

### Table Stakes (P1 — must ship in v1)

The "trust the numbers" floor across all 7 modules:

1. **Symbol registry** with tick values (ES $12.50/tick, MES $1.25/tick) — single source of truth for every dollar-denominated calc downstream.
2. **UTC-only storage, ET-only render**, RTH session filter, CME equity-index calendar (NOT NYSE), continuous front-month with documented back-adjustment, idempotent upsert keyed on `(symbol, tf, ts_utc)`, bar gap detection.
3. **`Strategy.on_bar(bar) -> Signal | None`** base class, warm-up handling, deterministic given same input, ORB reference strategy as the canonical correctness test.
4. **Backtester:** next-bar-open fills, tick slippage, per-side commission, full attribution ledger (signal → risk decision → fill → exit), look-ahead leakage detector (1-bar-delay comparison), MAE/MFE per trade, EOD forced flat.
5. **Optimization:** grid search, walk-forward with configurable IS/OOS, per-fold persistence, 2-param heatmap, ranked OOS leaderboard (NOT IS).
6. **Signal Pipeline:** asyncio bus, risk gate (NO back-door), full audit log (DuckDB + CSV mirror), **separate** kill switch + flatten-all (different buttons, different hotkeys, different confirmations), deterministic event order.
7. **Risk Manager:** ATR-based sizing, daily-DD circuit breaker ($2k default), **prop-firm trailing DD** (intraday-variant default), max-contracts cap, MES sizing conversion, HWM persisted to DuckDB, audit-loggable risk decision.
8. **UI:** dense dark monospace multi-pane grid (chart / blotter / history / controls), live chart with ORB box + signal markers + stop/target lines, WebSocket-driven with REST snapshot on connect, hotkeys (F=flatten, K=kill, P=pause, ?=help), ET clock prominent, connection-status indicator.
9. **Reproducibility CI test:** same input + same code → bitwise-identical equity curve.

### Differentiators (P2 — v1.x after the core loop is verified)

Bloomberg-density command bar (`Ctrl+K` / `/`), replay scrubber synced across panels, Monte Carlo trade-shuffle bands, edge-ratio (IS/OOS) overfit flag, forensic panel (click trade → full audit chain), TradingView MCP chart sync + drawing, multi-prop-firm presets, "soft" warnings at 80% of DD limit, side-by-side backtest diff, MAE/MFE per trade.

### Anti-Features (must NOT ship — list is opinionated and load-bearing)

- **Same-bar / current-bar-at-close fills** — pure look-ahead.
- **Forward-fill or interpolated OHLC on gaps** — fabricates bars ORB will trade off.
- **Live broker order entry from UI** (out of scope per PROJECT.md).
- **Tick-level fill simulation from 1m bars** — feels precise, is a lie.
- **Mid-bar `on_tick` strategy hook** — out of scope; encourages look-ahead.
- **External message broker (Redis/Kafka) for v1** — single-operator localhost.
- **Risk-override / "I know what I'm doing" toggle** — eliminates the reason the risk manager exists.
- **Auto-restart-on-halt** — kill switch requires human acknowledgement.
- **Combined "halt and flatten" mega-button** — conflates two very different intents.
- **Genetic / Bayesian optimization** in v1 (PROJECT.md explicit).
- **Current-bar P&L animation, light-mode theme, mobile layout, in-app strategy editor** — wrong target for this operator.
- **One giant `pyproject.toml`** — optimization workers should not import FastAPI/MCP.

Full table with rationale per anti-feature in FEATURES.md (every module).

---

## Architecture Highlights

### Component graph (load-bearing)

```
Twelve Data REST ──► DataSource ──► StrategyEngine ──► Signal
                                                        │
                                                        ▼
                                              EventBus (asyncio)
                                                        │
                       ┌──────────────┬─────────────────┼──────────────┐
                       ▼              ▼                 ▼              ▼
                  RiskManager    PaperExecutor    FastAPI WS    TVBridge (MCP sidecar)
                       │              │                 │              │
                       └────► DuckDB + Parquet ◄────────┘              └──► TradingView Desktop
                              (single-writer)                                 (via CDP)

   Optimization workers (ProcessPoolExecutor) load bars read-only,
   write per-worker Parquet shards, orchestrator aggregates into DuckDB.
```

### Runtime model

| Process | Always running? | Why a separate process |
|---------|-----------------|------------------------|
| `trading-core` (Python, asyncio) | Yes | Brain. Hosts Core + FastAPI on uvicorn. Single asyncio loop. |
| `web` (Node, Next.js) | While UI is open | Frontend dev server (or `next start`). |
| `tradingview-mcp` (Node, stdio child) | Spawned on first TV call, supervised | MCP is stdio — subprocess of Core, not peer service. Auto-restart on disconnect. |
| `opt-worker-*` (Python subprocess) | Only during optimization | CPU-bound NumPy/Numba; GIL prevents in-proc parallelism. |
| TradingView Desktop | Always | User's existing app; CDP target for MCP. |

### Four load-bearing `Protocol` seams

```python
class DataSource(Protocol):    # MarketData
class Strategy(Protocol):       # StrategyEngine
class RiskManager(Protocol):    # RiskManager
class Executor(Protocol):       # PaperExecutor (later: live broker)
```

These are the seams that make provider/strategy/firm/executor swaps mechanical. Every other class is implementation.

### Repo layout (uv workspace monorepo, NOT Turborepo)

```
Day Trading/
├── pyproject.toml              # uv workspace root + uv.lock
├── config/                     # system.yaml, risk.yaml, strategies/orb.yaml
├── data/                       # DuckDB + Parquet (gitignored)
├── packages/                   # Python workspace members
│   ├── trading-core/           # market_data, strategy, backtest, optimization,
│   │   └── src/trading_core/   #   pipeline, risk, execution, storage, bus, config
│   ├── api/                    # FastAPI app + routers + WS broadcaster
│   └── tv-bridge/              # MCP stdio client + supervisor + drawings
├── apps/web/                   # Next.js 16.2 frontend
├── tests/                      # unit/, integration/, fixtures/
└── .planning/                  # GSD planning artifacts
```

Single `.venv` via uv workspace; separate `pyproject.toml` per package so opt workers only import `trading-core` (not fastapi/mcp). Full tree + rationale in ARCHITECTURE.md §"Repository Layout".

### Single-writer-per-table

Every table has exactly **one writer**:

| Table | Writer | Readers |
|-------|--------|---------|
| `bars` | MarketData | Strategy, Backtester, Optimizer, API |
| `signals`, `audit_log` | SignalPipeline | API, TVBridge |
| `fills`, `positions` | PaperExecutor | RiskManager, Equity, API |
| `risk_decisions` | RiskManager | API |
| `trades`, `equity` | Backtester | Optimizer, API |
| `opt_runs`, `opt_results` | Optimizer | API |

Single-writer also at the DuckDB-file level: the FastAPI backend holds the only writer connection. Notebooks and opt workers open `read_only=True`. Opt workers write per-worker Parquet shards, aggregated in a single-process pass (OP-3).

---

## Top Pitfalls to Plan Around

Top 10 by severity + roadmap-leverage. Full taxonomy and recovery strategies in PITFALLS.md §"Pitfall-to-Phase Mapping".

| # | Pitfall | Severity | Phase | Gate / Test |
|---|---------|----------|-------|-------------|
| 1 | **MD-4 / BL-1 — Same-bar fill + bar-timestamp leakage** (next-bar shift missing; bars labelled by open misread as close) | Critical | 1 (convention), **3 (gate)** | `safe_from_signals()` wrapper + "perfect lookahead → finite Sharpe" assertion |
| 2 | **MD-6 — DST / UTC violations** (any naive `datetime` corrupts session windows) | Critical | 1 (repo-wide) | Pre-commit lint blocks `datetime.now()` without tz; tests on `2026-03-08` + `2026-11-01` |
| 3 | **MD-1 — Rollover-seam artifacts treated as real moves** (quarterly Friday gaps look like breakouts) | Critical | 1 + 3 | `rollover_seam=True` column; strategies mask seam bars; quarantine review query |
| 4 | **BL-4 — Walk-forward fold contamination + "true holdout" burn** (peeking, objective shopping, window shopping) | Critical | **4 (gate)** | Lock IS/OOS + grid + objective in an ADR before first run; config-hash log; rate-limited holdout |
| 5 | **RM-1 — Sizing math ignoring tick value (ES vs MES)** | Critical | **5 (first commit)** | `instruments.py` SoT; `size(1000, 5, MES) == 40` and `size(1000, 5, ES) == 4` unit tests |
| 6 | **RM-2 / RM-6 — Trailing DD model wrong + HWM not persistent** (intraday vs EOD vs static) | Critical | 5 | `DrawdownModel` enum; per-variant tests; HWM persisted to DuckDB; refuse start without today's HWM row |
| 7 | **RM-4 — EOD flatten-all not enforced** (wall-clock task, NOT bar-driven) | Critical | 5 + 6 | Wall-clock scheduler at session_close − 60s; assertion `sum(position_sizes) == 0` after close |
| 8 | **FR-1 — Open-fill optimism on the cash open** (ORB is the worst case — 1.5–2 tick adverse) | Critical | 3 | Session-phase-aware slippage model; TV replay cross-check on 10 ORB trades |
| 9 | **UI-4 — Lightweight Charts TZ drift** (UTC seconds rendered in browser local TZ) | Critical | 8 | `timeFormatter` + `tickMarkFormatter` configured to `America/New_York`; visual smoke test |
| 10 | **OP-1 / OP-2 — Secrets in git + irreproducible backtests** (no seed, no data hash) | Critical | 1 + 3 | `.gitignore` + `gitleaks` pre-commit; `runs` table logs `git_sha / data_hash / param_hash / seed`; CI reproducibility test |

Honorable mentions:
- **TV-2** (TV as source of truth) — addressed by Critical Finding #6.
- **SP-3** (audit log doesn't survive a restart) — synchronous DuckDB writes on every event; kill-9 test.
- **OP-3** (DuckDB file locked) — single-writer convention; opt workers go through per-worker Parquet shards.
- **OP-4** (Windows path / encoding) — repo path has a space; `pathlib` + `utf-8` everywhere; CI on Windows.

Severity legend: **Critical** = silently corrupts research conclusions; **High** = visible failure that wastes days or destroys a prop-firm account.

---

## Suggested Phase Ordering

Derived from the architecture build-order, the feature MVP, the pitfall-phase mapping, and the data-provider unknown. Phase numbers below align with the phases used in PITFALLS.md §"Pitfall-to-Phase Mapping".

### Phase 0 — Provider validation spike (NEW; precedes Phase 1)

**Why first:** Critical Finding #1. We cannot commit strategy or backtest work until we know whether the canonical symbol is ES (Twelve Data) or SPY (proxy).

- Hit Twelve Data `/stocks?symbol=ES`, `/commodities?symbol=ES`, `/indices?symbol=SPX`. Document.
- Confirm SPY 1m bars are available on the chosen tier; verify rate-limit budget against a 2-year backfill (~196k bars).
- Smoke-test the TradingView MCP from a PowerShell `trading-core` process: spawn, `chart_set_symbol`, `data_get_ohlcv`, recover from restart.
- **Deliverable:** an ADR locking the v1 working symbol (SPY or ES) and the eventual provider-swap candidate (Databento / Polygon Futures / IB historical).

### Phase 1 — Foundation + Data In

- uv workspace scaffold; `uv.lock` committed.
- `.gitignore` + `.env.example` + `gitleaks` pre-commit (OP-1).
- Pydantic Settings + `config/*.yaml` loader.
- `EventBus` (asyncio pub/sub, in-process).
- DuckDB `Repo` skeleton + single-writer convention.
- `DataSource` protocol + `TwelveDataSource` impl.
- **UTC-only discipline**, RTH filter, CME calendar (`pandas_market_calendars` `CME_Equity`), rollover-seam detection, idempotent upsert, bar gap detection.
- Tick-value / instrument registry (`instruments.py`).
- Reproducibility scaffolding: `git_sha / data_hash / param_hash / seed` on every run.
- `seed_bars.py` CLI.

### Phase 2 — Strategy Engine + Indicators

- `Strategy` protocol + `StrategyContext` + warm-up handling.
- Indicator layer (ATR Wilder, VWAP, EMA, ADR) — no look-ahead.
- HTF features always `.shift(1)` after resample.
- `ORBStrategy` with all config knobs.
- Strategy ID + version stamped on every signal.

### Phase 3 — Vertical MVP Slice + Backtester (the integration gate)

**Delivers:** bar → ORB signal → paper fill → chart marker on the Next.js panel.

- `SignalPipeline` plumbing.
- Minimal `RiskManager` (1 MES contract, pass-through).
- Minimal `PaperExecutor` (next-bar fill, slippage, EOD flat).
- VectorBT in `backtest/engine.py` with **`safe_from_signals()` helper**.
- Fill simulation: next-bar-open + tick slippage + per-side commission.
- Metrics (Sharpe / Sortino / DD / WR / expectancy / PF) + MAE/MFE.
- Trade ledger with full attribution chain.
- **Look-ahead leakage detector** (BL-1 gate).
- **Reproducibility CI smoke test** (OP-2).
- FastAPI `/bars`, `/backtests`, `/ws` + WS broadcaster.
- Next.js chart panel: Lightweight Charts with `America/New_York` formatter (UI-4 gate).

### Phase 4 — Optimization (Grid + Walk-Forward)

- Grid expansion over typed param spaces.
- `ProcessPoolExecutor` worker harness; per-worker Parquet shards.
- Walk-forward via `vbt.Splitter` or calendar-aware splitter.
- **Lock IS/OOS + grid + objective + seed in an ADR before first run** (BL-4 gate).
- Per-fold persistence with hashes.
- Coarse-grid-first protocol; plateau detection; OOS Sharpe primary.
- **"True holdout" guard**: last 6 months refuses to be queried until explicit "go-live" command.
- UI: 2-param heatmap + OOS-ranked leaderboard + IS/OOS edge-ratio flag.

### Phase 5 — Risk Manager + Audit (full)

- ATR-based sizing using `instruments.py` (RM-1).
- `DrawdownModel` enum; default TRAILING_INTRADAY; all three tracked side-by-side (RM-2).
- Daily-DD circuit breaker; pre-trade `worst_case_loss` check (RM-3).
- HWM persisted to DuckDB; refuse start without today's session row (RM-6).
- EOD flatten-all wall-clock scheduler (RM-4).
- Max contracts cap; per-strategy concurrency cap.
- Risk decisions logged with reason codes; single-threaded risk loop (SP-2).
- **Separate** kill switch + flatten-all hotkeys.
- UI: blotter with positions + distance-to-stop + daily-DD bar.

### Phase 6 — TradingView MCP Bridge

- `TVBridge` supervisor + stdio MCP client (long-lived `ClientSession`).
- Auto-draw ORB box, signal arrows, stop/target lines.
- Overlay registry + daily cleanup + max-200 cap (TV-1).
- **Failure isolation**: TVBridge is subscriber, not pipeline step.
- UI button: "Sync chart to selected date" (REST `/tv/focus`).
- Daily Twelve-Data-vs-TV reconciliation (TV-2).
- Validate Python ATR ≈ TV ATR within tolerance.

### Phase 7 — Polish + Bloomberg-Density UI

- Multi-pane configurable grid; dense monospace styling pass.
- Trade history + equity curve + daily/cumulative stats.
- Strategy controls panel: toggle on/off, edit ORB params, hot-reload via YAML watch.
- **WebSocket reconnect**: exponential backoff + jitter; sequence numbers; snapshot resync on gap.
- Atomic state broadcasts.
- Command palette (`Ctrl+K`) + single-key shortcuts.
- "Last updated" indicator on every P&L widget.

### Phase 8 — Operational hardening + reproducibility CI

- Reference backtest in CI: equity-curve snapshot test.
- `Replay` command: re-feed bars from DuckDB through full pipeline; byte-match audit log.
- Per-day API-call cache + budget tracker.
- Cross-platform path / encoding tests; CI on Windows.
- Backup / encrypted-audit-log policy.

### Future (v2+ — explicitly deferred)

Bayesian/genetic optimization, live broker adapter, multi-strategy concurrent execution, multi-source data reconciliation as a continuous process, per-strategy correlation cap, bar-volume-throttled fill model, multi-timeframe within one strategy, hot-reload of strategy code.

---

## Open Questions for Phase Planning

### Phase 0 (provider validation spike)

1. **Does Twelve Data actually serve ES futures bars?** — hit `/stocks?symbol=ES`, `/commodities?symbol=ES`, `/indices?symbol=SPX`; document result; lock v1 symbol.
2. **Twelve Data 1m intraday rate limit on the chosen tier?** — verify a 2-year SPY backfill (~196k bars) fits in the day-budget.
3. **TradingView MCP authentication / re-attach across PowerShell sessions** — smoke test FastAPI ↔ MCP ↔ TV restart.
4. **DuckDB on Windows large-Parquet-partition file-locking** — 1 GB synthetic write test.

### Phase 1

5. **VectorBT 1.0.0 + pandas 2.2 + numpy compat on Windows** — verify with `uv pip compile`.
6. **Rollover-seam detection method for Twelve Data continuous** — reconcile against front-month symbol (e.g., `ESM26`).
7. **Twelve Data adjustment method** — document continuous policy.

### Phase 3

8. **VectorBT 1.0.0 `sl_stop` / `tp_stop` intrabar fill semantics** — smoke-test hand-computed expected trades.
9. **Lookahead detector implementation** — 1-bar-delay comparison, per-bar indicator-recomputation assertion, or both?

### Phase 4

10. **Walk-forward window selection** — IS length, OOS length, step, anchored vs rolling. Lock in ADR.
11. **Holdout-burn budget** — how many queries before "true holdout" is burned?
12. **Primary objective function** — OOS Sharpe? Sortino? Bootstrap-5th-percentile?

### Phase 5

13. **Current Apex / Topstep evaluation rules** — verify at implementation time.

### Phase 7+

14. **WebSocket message envelope schema** — sequence numbers, snapshot vs delta tags, `state_version` fields.
15. **Backup / audit-log retention policy.**

### Open question NOT answered by researchers

16. **Multi-strategy concurrency policy** — v1 risk manager enforces one active, or just allow one configured?

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| **Stack** | HIGH on Python/JS ecosystems and version pins; **MEDIUM** on Twelve Data for ES specifically | Twelve Data ES gap verified across 3 sources; SPY mitigation is HIGH-confidence. |
| **Features** | HIGH inventory; **MEDIUM** prioritization | Verified against NautilusTrader / Backtrader / vectorbt / TopstepX / Bloomberg / OpenBB / TradingView. |
| **Architecture** | HIGH | Four `Protocol` seams + single-writer rule are battle-tested. |
| **Pitfalls** | HIGH | Drawn from canonical algotrading + prop-firm + library-known-issues. |

### Identified gaps (cannot be resolved by research alone)

- **ES availability on Twelve Data** — needs an actual API call (Phase 0).
- **Rate-limit budget** — needs the user's tier confirmed (Phase 0).
- **VectorBT 1.0.0 fill-semantics edge cases** — needs the smoke test (Phase 3).
- **Current Apex / Topstep evaluation rules** — needs date-of-implementation verification (Phase 5).
- **Walk-forward window selection** — research can recommend ranges but the final lock-in is an ADR judgement call (Phase 4).

---

*Research synthesis for: intraday ES futures backtest + paper-trading system with Bloomberg-Terminal-style web UI and TradingView MCP integration.*
*Synthesized: 2026-05-14.*
