# Roadmap: ES Futures Trading System

## Milestones

- ✅ **v1.0 — Foundation to Full Terminal** — Phases 0–8 (shipped 2026-05-21)
- 📋 **v1.1** — Tech debt + first live improvements (planned)

---

## Phases

<details>
<summary>✅ v1.0 — Foundation to Full Terminal (Phases 0–8) — SHIPPED 2026-05-21</summary>

- [x] Phase 0: Provider Validation Spike (3/3 plans) — completed 2026-05-14
- [x] Phase 1: Foundation + Data In (6/6 plans) — completed 2026-05-15
- [x] Phase 2: Strategy Engine + Indicators (2/2 plans) — completed 2026-05-16
- [x] Phase 3: Vertical MVP Slice + Backtester (5/5 plans) — completed 2026-05-17
- [x] Phase 4: Optimization Grid + Walk-Forward (3/3 plans) — completed 2026-05-17
- [x] Phase 5: Risk Manager + Full Audit + Controls (5/5 plans) — completed 2026-05-18
- [x] Phase 6: TradingView MCP Bridge (5/5 plans) — completed 2026-05-19
- [x] Phase 7: Bloomberg-Density UI Polish (6/6 plans) — completed 2026-05-21
- [x] Phase 8: Operational Hardening + Reproducibility CI (3/3 plans) — completed 2026-05-20

Full details: `.planning/milestones/v1.0-ROADMAP.md`

</details>

### 📋 v1.1 — Tech Debt + First Live Improvements (Planned)

Phases and scope to be defined via `/gsd-new-milestone`.

**Top candidates (from v1.0 tech debt backlog):**
- [ ] Wire POST /backtests/run to BacktestEngine (UI Run Backtest becomes real)
- [ ] Fix ORB box coords in TVBridge (actual session H/L from StrategyContext)
- [ ] Fix silent UTC coercion in Bar storage
- [ ] Wire strategy hot-reload to live engine (propagate param updates)
- [ ] Phase 2 retroactive VERIFICATION.md
- [ ] REQUIREMENTS.md checkbox cleanup

---

## Progress

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 0. Provider Validation Spike | v1.0 | 3/3 | Complete | 2026-05-14 |
| 1. Foundation + Data In | v1.0 | 6/6 | Complete | 2026-05-15 |
| 2. Strategy Engine + Indicators | v1.0 | 2/2 | Complete | 2026-05-16 |
| 3. Vertical MVP Slice + Backtester | v1.0 | 5/5 | Complete | 2026-05-17 |
| 4. Optimization Grid + Walk-Forward | v1.0 | 3/3 | Complete | 2026-05-17 |
| 5. Risk Manager + Full Audit + Controls | v1.0 | 5/5 | Complete | 2026-05-18 |
| 6. TradingView MCP Bridge | v1.0 | 5/5 | Complete | 2026-05-19 |
| 7. Bloomberg-Density UI Polish | v1.0 | 6/6 | Complete | 2026-05-21 |
| 8. Operational Hardening + Reproducibility CI | v1.0 | 3/3 | Complete | 2026-05-20 |

---

*v1.0 shipped 2026-05-21. Next: `/gsd-new-milestone` to plan v1.1.*
