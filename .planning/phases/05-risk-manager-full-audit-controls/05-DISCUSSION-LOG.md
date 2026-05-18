# Phase 5: Risk Manager + Full Audit + Controls - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-18
**Phase:** 05-risk-manager-full-audit-controls
**Areas discussed:** RiskConfig expansion + account equity, risk_state schema + HWM restart

---

## RiskConfig expansion + account equity

### Q1: Where does RiskConfig live?

| Option | Description | Selected |
|--------|-------------|----------|
| New config/risk.yaml | Risk params in their own file, separate from strategy configs. Cleaner separation — risk is an operator-level concern. | ✓ |
| Extend config/system.yaml | Merge into the existing system-level config. Fewer files, but mixes system settings with trading risk params. | |
| Inline in orb.yaml | Per-strategy risk config. Would need duplication if a second strategy is added in v2. | |

**User's choice:** New config/risk.yaml

---

### Q2: What is account_equity in this paper-trading system?

| Option | Description | Selected |
|--------|-------------|----------|
| Static value in risk.yaml | Set once (e.g., $50,000 default), never auto-updated. Simple and reproducible. | ✓ |
| Seeded from yesterday's DuckDB equity close | Bootstrap from the realized equity curve. More realistic but adds startup dependency. | |
| You decide | Claude picks the implementation. | |

**User's choice:** Static value in risk.yaml ($50,000 default)

---

### Q3: What defaults go in risk.yaml? (max_risk_per_trade_pct)

| Option | Description | Selected |
|--------|-------------|----------|
| 1% | risk_$ = $500/trade on $50k. Clamped to max_contracts=2 MES in most scenarios. Conservative. | ✓ |
| 2% | risk_$ = $1000/trade. Still clamped by max_contracts in practice. | |
| You decide | Claude picks — likely 2% since RM-01 unit test uses risk_$=1000. | |

**User's choice:** 1% (max_risk_per_trade_pct = 0.01)

---

### Q4: RM-01 unit test says size(risk_$=1000, stop_ticks=5, MES)==40. With $50k + 1%, risk_$=500. How to read the test?

| Option | Description | Selected |
|--------|-------------|----------|
| Test passes risk_$ directly (not via account_equity × pct) | Sizing function is a pure function. RM-01 tests it with risk_$=1000 directly, independent of config. | |
| Test uses account_equity=$100k + 1% to produce risk_$=1000 | Ties test to specific config value. | |
| You decide | Claude handles test fixture design — likely direct risk_$ parameter. | ✓ |

**User's choice:** You decide (Claude decides: pure function approach, test passes risk_$ directly)

---

## risk_state schema + HWM restart

### Q1: risk_state table design (append-only vs. upsert)

| Option | Description | Selected |
|--------|-------------|----------|
| Append-only (one row per update) | Full audit trail of every risk state change. Naturally survives kill -9. | ✓ |
| Upsert (one row per trading day) | Simpler queries for current state, but loses intraday history and risks partial-update on kill -9. | |
| You decide | Claude picks — likely append-only. | |

**User's choice:** Append-only

---

### Q2: HWM bootstrap on restart

| Option | Description | Selected |
|--------|-------------|----------|
| Query last risk_state row for yesterday | SELECT last row WHERE date=yesterday. Use equity_$ as today's starting HWM for all 3 DD models. Day-1 exception: use account_equity from risk.yaml. | ✓ |
| Query backtests equity_curve_path | Read yesterday's equity Parquet. More accurate but adds file-read dependency. | |
| You decide | Claude picks — likely option 1. | |

**User's choice:** Query last risk_state row for yesterday

---

### Q3: risk_state schema — 3 DD models side-by-side

| Option | Description | Selected |
|--------|-------------|----------|
| 6 DD columns + common fields | ts_utc, date, session_id, equity_$, realized_pnl_$, open_exposure_$, hwm_static, floor_static, hwm_trailing_eod, floor_trailing_eod, hwm_trailing_intraday, floor_trailing_intraday | ✓ |
| Separate table per DD model | 3 tables, cleaner per-model schema but 3× tables and JOIN complexity. | |
| You decide | Claude picks — likely 6 DD columns in one table. | |

**User's choice:** 6 DD columns + common fields in one append-only table

---

## Claude's Discretion

- **Sizing unit test fixture design:** Pure function `size_for_stop(risk_dollars, stop_ticks, instrument)`. RM-01 tests call it with `risk_dollars=1000` directly (not via config). `FullRiskManager` computes `risk_dollars = account_equity × max_risk_per_trade_pct` before calling the function.
- **Audit log architecture (not discussed):** New `audit_log` DuckDB table + daily CSV mirror at `data/logs/audit/{date}.csv`. Synchronous DuckDB INSERT + CSV append + flush on every event. Satisfies SP-03's "survives kill -9" requirement.
- **Engine state mechanism (not discussed):** DuckDB `engine_state` table (persistent) + in-memory `asyncio.Event` (fast signaling). Dual mechanism for persistence + performance. `POST /kill` inserts row + sets Event. `POST /flatten` sequences close + state reset.

## Deferred Ideas

- Drag/resize multi-pane layout integrating the blotter — Phase 7
- WebSocket sequence numbers + snapshot resync for blotter — Phase 7 (SP-06)
- Soft warnings at 80% of daily-DD threshold — v2 (V2-UI-06)
- Multi-strategy concurrency cap — v2 (V2-MS-01)
