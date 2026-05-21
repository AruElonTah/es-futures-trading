# Milestones: ES Futures Trading System

---

## v1.0 — Foundation to Full Terminal

**Shipped:** 2026-05-21
**Phases:** 9 (Phases 0–8)
**Plans:** 45
**Timeline:** 2026-05-14 → 2026-05-21 (7 days)
**Commits:** 288
**Code:** ~53,900 Python LOC · ~19,900 TypeScript LOC

### Delivered

A single-operator intraday ES futures backtest + paper-trading system with a Bloomberg-density 4-pane terminal. The core value — "Trust the numbers: every reported backtest result is reproducible, leakage-free, and survives walk-forward" — is validated end-to-end.

### Key Accomplishments

1. **Phase 0**: Validated TradingView MCP as v1 primary data feed; confirmed Twelve Data does not cover ES futures (demoted to SPY-proxy secondary). ADR committed as forensic record.
2. **Phase 1**: Complete monorepo scaffold — uv workspace, DuckDB+Parquet with idempotent RTH upserts, CME equity-index calendar, EventBus, gitleaks + no-naive-tz pre-commit hooks, structlog audit trail.
3. **Phase 2**: Look-ahead-safe ATRWilder / VWAP / EMA / ADR indicators; ORBStrategy with leakage-proof integration test (ATR-before ≠ ATR-after); StrategyRegistry + orb.yaml config-driven.
4. **Phase 3**: Integration gate closed — bar → ORB signal → paper fill → Lightweight Charts marker. `safe_from_signals()` wrapper + BL-1 lookahead detector + bitwise-identical equity-curve CI test all green.
5. **Phase 4**: Grid + walk-forward optimization with `ProcessPoolExecutor` workers; pre-run ADR gate; true holdout guard (max 3 burns/quarter); OOS-Sharpe leaderboard; 2-param heatmap in UI.
6. **Phase 5**: Full prop-firm risk manager — ATR sizing from `instruments.py`, 3 DrawdownModel variants (STATIC/TRAILING_EOD/TRAILING_INTRADAY) tracked side-by-side, HWM persists across `kill -9`, kill/flatten as separate hotkeys with confirmation dialogs.
7. **Phase 6**: TVBridge supervised MCP session — ORB box + signal overlays auto-drawn on live TradingView chart; overlay registry with 200-shape cap; TVReplayDataSource feeds `Strategy.on_bar()` through TV replay.
8. **Phase 7**: Bloomberg-density 4-pane Next.js terminal — drag/resize panes, WS exponential backoff + sequence-gap resync, trade history + equity curve, strategy hot-reload controls. Human UAT 8/8 passed.
9. **Phase 8**: Byte-identical audit log replay CI; GitHub Actions Windows CI with path-with-space + UTF-8 tests; backup.ps1 + retention policy.

### Gaps at Close

| Gap | Severity | Item |
|-----|----------|------|
| Gap-10 | Medium | POST /backtests/run UI button never calls BacktestEngine (CLI path works) |
| Gap-7 | Medium | ORB box drawn with stub coords, not actual session H/L |
| Gap-1 | Medium | Silent naive→UTC coercion in Bar storage |
| Gap-2..5 | Low | Phase 1 data pipeline correctness issues |
| Gap-6 | Low | BL-1 win-rate test assertion too loose |
| Gap-8 | Info | REQUIREMENTS.md checkboxes stale at close |
| Gap-9 | Info | Phase 2 missing VERIFICATION.md |

Full details: `.planning/v1.0-MILESTONE-AUDIT.md`

### Tech Debt Backlog (First-Priority v1.1)

1. **Wire POST /backtests/run to BacktestEngine** — UI Run Backtest becomes real
2. **Fix ORB box coords** — TVBridge reads session H/L from StrategyContext instead of stub entry ×1.001
3. **Fix silent UTC coercion** — Bar storage rejects naive timestamps at ingestion boundary
4. **Wire hot-reload to live engine** — strategy param update actually propagates to running engine

---

*First entry — v1.0 shipped 2026-05-21*
