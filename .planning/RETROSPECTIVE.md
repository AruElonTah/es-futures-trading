# Retrospective: ES Futures Trading System

---

## Milestone: v1.0 — Foundation to Full Terminal

**Shipped:** 2026-05-21
**Phases:** 9 (0–8) | **Plans:** 45 | **Timeline:** 7 days | **Commits:** 288

### What Was Built

1. TradingView MCP primary data feed — ES continuous front-month, confirmed working
2. Look-ahead-safe ORBStrategy: ATR/VWAP/EMA/ADR indicators with leakage-proof integration test
3. VectorBT backtester with `safe_from_signals()` wrapper, BL-1 CI gate, full attribution chain
4. Grid + walk-forward optimization: ProcessPoolExecutor, ADR gate, true holdout guard
5. Full prop-firm risk manager: 3 DrawdownModel variants, HWM persistence, kill-9 durability
6. TVBridge supervised MCP session: auto-draws ORB box + signal overlays on live TradingView chart
7. Bloomberg-density 4-pane Next.js terminal: WS reconnect/backoff, strategy hot-reload, trade history
8. Byte-identical reproducibility CI on Windows GitHub Actions

### What Worked

- **Vertical MVP gating at Phase 3** — closing the loop (bar → signal → chart marker) early caught integration issues before they stacked up
- **BL-1 lookahead detector** — the deliberately-leaking strategy CI test is valuable insurance; caught a subtle shift() issue during Phase 3
- **Protocol seams** (DataSource, Strategy, RiskManager, Executor) — meant Phase 5's FullRiskManager was a genuine drop-in swap with zero Phase 3 API changes
- **HWM kill-9 durability test** — caught a real concurrency race (21d42ff DuckDB thread-safety fix) that would have silently corrupted production
- **Phase 7 UAT block → inline fix** — 3 bugs found and fixed during UAT (StrictMode guard, autoSaveId, playwright testDir) rather than discovered post-ship

### What Was Inefficient

- **POST /backtests/run stub deferred to Phase 8 then never resolved** — a UI feature that always returns a fake result shipped in v1.0. Should have been a Phase 7 or 8 blocker, not a "Phase 8 concern" that fell through.
- **ORB box stub coords** (signal.entry × 1.001/0.999) — deferred at Phase 6 checkpoint via `auto_advance=true`, visible visual bug in TVBridge. Should have blocked Phase 6.
- **REQUIREMENTS.md and ROADMAP.md tracking not updated phase-by-phase** — Phase 4/5/8 all had stale "Pending" entries at milestone close; required a manual reconciliation pass. Live tracking during execution would eliminate this.
- **Phase 2 missing VERIFICATION.md** — the verifier was not run on Phase 2; only SUMMARY exists. Process gap that requires a retroactive fix.
- **`workflow.auto_advance=true` bypassing blocking gates** — Phase 6 and Phase 7 had blocking human-verify checkpoints that were auto-approved. This is fine for speed but should be explicitly noted in the SUMMARY, not silently skipped.

### Patterns Established

- **Gap closure plans (XX-05, XX-06)** for post-verification human UAT — effective pattern for separating code-verification from human browser testing
- **SUMMARY self-check section** — phase summaries include a `Self-Check: PASSED` section with explicit file/test assertions that serve as lightweight verification when a full VERIFICATION.md isn't run
- **`_isolate_logging` autouse fixture** — prevents structlog cache poisoning across pytest runs; established in Phase 1, used throughout
- **`_LockedConn` for DuckDB** — threading-safe connection wrapper for FastAPI's thread pool; prevents SQLite-style race conditions

### Key Lessons

1. **Don't defer UI stubs past the phase that introduces the feature** — `_run_backtest_task` was introduced in Phase 7 and deferred twice. Features introduced in a phase should be wired in that phase.
2. **`auto_advance=true` should require an explicit acknowledgement in the SUMMARY** — e.g., "blocking gate bypassed: will be resolved in gap-closure plan XX-06." Silent skips become tech debt surprises at milestone close.
3. **Tracking files (ROADMAP/STATE) should be updated atomically with each phase close** — stale tracking caused a false "Phase 5 not started" reading that required a forensic investigation.
4. **Windows-first CI from Phase 1** — the Phase 8 Windows CI additions could have been part of Phase 1's pre-commit setup; catching `uv.exe` vs `uv` and path-with-space issues earlier would have saved multiple WR-* fixes.
5. **The integration checker's BLOCKER finding is valuable** — running cross-phase wiring verification before milestone close revealed the `_run_backtest_task` stub gap that code review missed.

---

## Cross-Milestone Trends

| Metric | v1.0 |
|--------|------|
| Timeline | 7 days |
| Phases | 9 |
| Plans | 45 |
| Commits | 288 |
| Python LOC | ~53,900 |
| TypeScript LOC | ~19,900 |
| Open gaps at close | 10 (6 medium/low, 4 info) |
| UAT pass rate | 11/11 (Phase 5: 3/3, Phase 6: auto, Phase 7: 8/8) |
