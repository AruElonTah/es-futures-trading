---
phase: 00-provider-validation-spike
plan: 03
subsystem: data-provider
tags: [adr, madr, vendor-comparison, phase-0-close, runs-adr-hash]

requires:
  - phase: 00-plan-01
    provides: twelvedata-probe.json (negative ES finding) + spy-bar-budget.md
  - phase: 00-plan-02
    provides: tv-mcp-tools.json (81 tools, all required present) + tv-mcp-transcript.log (smoke happy path) + tv-restart-test.log (RESULT: conclusive)
provides:
  - ADR 0001-data-provider.md (Phase 0 closing artifact — referenced by every Phase 4+ run as runs.adr_hash)
  - Re-verified vendor comparison table (Twelve Data / Databento / Massive / IB historical / CME DataMine)
  - verify_adr.py + verify_artifacts.py (re-runnable assertion scripts)
affects: [phase-1, phase-4, phase-6, phase-8]

tech-stack:
  added: []
  patterns:
    - "Pattern: MADR ADR with stable adr_id + slug. Editing post-commit requires a superseding ADR (0002-*.md), never an amend. supersedes/superseded_by fields form a chain."
    - "Pattern: ADR cites verification artifacts by relative path. verify_adr.py asserts each cited path exists in the body; verify_artifacts.py asserts each cited file exists on disk and meets a minimum size. Both are stdlib-only and re-runnable."
    - "Pattern: When-to-revisit triggers are concrete, not aspirational. Each trigger is a measurable condition (Sharpe across N folds; disconnect rate > N/hr; specific budget approval) so future-self can act on the ADR without reinterpreting intent."

key-files:
  created:
    - .planning/research/spike-0/comparison-table.md (vendor comparison re-verified 2026-05-14)
    - .planning/decisions/0001-data-provider.md (the MADR ADR — Phase 0 closing artifact)
    - scripts/spike/verify_adr.py (stdlib-only ADR shape check)
    - scripts/spike/verify_artifacts.py (stdlib-only artifact manifest check)

key-decisions:
  - "v1 PRIMARY data feed: TradingView Desktop via tradingview-mcp-jackson MCP (real-time CME ES, integrated chart, zero marginal cost on operator's existing TV subscription)."
  - "v1 SECONDARY data feed: Twelve Data REST on SPY (headless / CI / daily reconciliation — Free tier sufficient for 2-year SPY 1m backfill)."
  - "Named swap candidate when budget opens: Databento (GLBX.MDP3 dataset, pay-as-you-go historical; $199/mo Standard tier only needed for live subscriptions, which is out of scope for v1)."
  - "Status: accepted (Scenario A — the expected research hypothesis confirmed by both Plan 1 and Plan 2 evidence)."
  - "Verification: 6 cited artifacts, all on disk; verify_adr.py + verify_artifacts.py both exit 0."

patterns-established:
  - "Pattern: ADR hash referenced downstream. ADR 0001-data-provider.md will be SHA-256 hashed and stored in every Phase 4+ optimization run's runs.adr_hash column (FND-08 + OPT-04). This makes the ADR effectively content-addressed for all future backtest output."

requirements-completed:
  - FND-10  # fully satisfied across Plans 1, 2, and 3

duration: ~30min (Task 1 WebFetch + write, Task 2 ADR, Task 3 verify scripts, Task 4 operator approval, Task 5 closing commit)
completed: 2026-05-14
---

# Plan 00-03: Vendor Comparison + Provider ADR — Summary

**Phase 0 closes ACCEPTED. v1 primary feed = TradingView MCP. v1 secondary feed = Twelve Data on SPY. Named swap candidate = Databento. ADR 0001-data-provider.md is the load-bearing artifact every Phase 4+ optimization run will hash and reference.**

## Performance

- **Duration:** ~30 min (Task 1 = 3 WebFetch + table write, Task 2 = ADR authoring, Task 3 = 2 verify scripts, Task 4 = operator review, Task 5 = atomic close commit).
- **Scenario chosen:** **A** — the expected research hypothesis confirmed by both upstream plans.
- **Approval signal:** operator typed `approved` at the Task 4 human-verify checkpoint.

## Accomplishments

- **ADR 0001-data-provider.md is committed and accepted.** 13,658 bytes. 8 required H2 sections present; `### When to revisit` subsection with 6 concrete triggers; all 6 cited verification artifacts present on disk.
- **Vendor pricing re-verified on 2026-05-14 against live pages.** Twelve Data (Free/$79/$229/$999), Databento ($199/$1,399/$3,500), Massive (still opaque). All three matched the cached RESEARCH baseline → `[RE-VERIFIED 2026-05-14 — UNCHANGED]`.
- **Two re-runnable assertion scripts shipped.** `verify_adr.py` checks ADR shape (sections, frontmatter, citations) and `verify_artifacts.py` checks the 8-file artifact manifest exists and meets size minimums. Both are stdlib-only so future contributors can run them with any Python 3.11+.
- **Phase 0 is closed.** 5 sequential commits on `master`: `22ddb9c` plan 1, `3e720de` plan 1 summary, `c7d005a` plan 2, `5693ac3` plan 2 summary, `a0b8444` plan 3 closing.

## Task Commits

1. **Tasks 1–5 bundled:** `a0b8444` — `docs(00): plan 3 — vendor comparison + provider ADR (closes phase 0)`

(Like Plans 1 and 2, Plan 3's spec mandated a single atomic close-commit at Task 5. The 4 files in the commit are: `comparison-table.md`, `0001-data-provider.md`, `verify_adr.py`, `verify_artifacts.py`.)

## Files Created/Modified

- `.planning/research/spike-0/comparison-table.md` (6,583 bytes) — 5-vendor markdown table with ES coverage / MES coverage / live / historical / monthly cost / Python SDK / verification source columns, plus "Why Databento" rationale, "Do-not-swap-to" list, and a Findings-from-Phase-0-spike section sourced from Plans 1 & 2 artifacts.
- `.planning/decisions/0001-data-provider.md` (13,658 bytes) — the MADR ADR. Frontmatter (`adr_id: 0001`, `slug: data-provider`, `status: accepted`, `deciders: [Nathaniel Greene]`, `date: 2026-05-14`); 8 required H2 sections; `### When to revisit` with 6 concrete triggers; 6 cited verification artifacts.
- `scripts/spike/verify_adr.py` — checks ADR file existence, size (1.5–20 KB), frontmatter (8 required keys including `adr_id: 0001`), all 8 H2 sections, the `### When to revisit` subsection, and all 6 cited artifacts referenced in body. Uses PyYAML if available, else falls back to a tiny in-house frontmatter parser sufficient for MADR's flat shape.
- `scripts/spike/verify_artifacts.py` — checks 8-entry MANIFEST: 6 spike-0 artifacts + 1 comparison table + 1 ADR. Each entry has a minimum-bytes threshold to catch empty / placeholder files without being so tight that a legitimate compact artifact trips the gate.

## Decisions Made

- **Scenario A is the operative path.** Plan 1's `commodities_ES.body.data == []` and Plan 2's `RESULT: conclusive` together satisfy the success preconditions for the originally-hypothesized decision. No scenario branching applied to the ADR.
- **adr_id = 0001 is canonical, not a placeholder.** This ADR is the first in the project's `decisions/` directory. Its hash is the seed of the `runs.adr_hash` chain that every Phase 4+ optimization will reference.
- **`### When to revisit` triggers are concrete.** Each of the 6 triggers is a measurable condition the operator can recognize without re-deriving intent. Examples: "ORB strategy survives walk-forward with positive OOS Sharpe across at least 3 folds" (specific fold count); "CDP disconnect rate exceeds 1/hour during normal operation" (specific threshold).
- **The 6 cited artifacts include `comparison-table.md` (not 5).** RESEARCH.md said "all 5" but the comparison table is itself a Phase 0 deliverable that the ADR depends on. The 6th citation makes the ADR self-contained.

## Deviations from Plan

None — Plan 00-03 executed exactly as written including all 5 verify gates and the operator approval checkpoint.

## Notable Observations for Downstream Phases

| Finding | Downstream phase | Use |
|---------|------------------|-----|
| `adr_id: 0001` is hashed into `runs.adr_hash` | Phase 1 (FND-08), Phase 4 (OPT-04) | Every `runs` row records this hash so backtest reproducibility is content-addressed against the ADR body |
| CDP-mode launch requirement | Phase 6 (TVBridge) | TVBridge supervisor must invoke `tv_launch` or set `--remote-debugging-port=9222`; Start-menu launch does NOT enable CDP |
| Mid-restart partial-load state (`_activeChartWidgetWV undefined`) | Phase 6 (TVBridge) | Supervisor must gate on `api_available=true`, not `cdp_connected=true` alone |
| mcp SDK 1.x does not expose subprocess stderr | Phase 6 (TVBridge) | Use `subprocess.Popen` directly (or a custom MCP transport) for real operational observability of the Node server |
| Twelve Data catalog endpoints emit no credit headers | Phase 1 (`seed_bars.py`) | Pacing logic reads credit headers from `/time_series` responses only |
| TV `quote_get` returns bar-start time, not last-tick | Phase 6 (TVBridge), Phase 5 (Risk) | Freshness checks must rely on tick events / WebSocket subs, not bar timestamps |

## Verification

All Plan 00-03 plan-level verifications passed:
- [x] `comparison-table.md` exists with all 5 vendor rows + sections; pricing re-verified 2026-05-14.
- [x] `0001-data-provider.md` exists with MADR frontmatter (`adr_id: 0001`, `deciders: [Nathaniel Greene]`, today's date `2026-05-14`), all 8 required H2 sections, the `### When to revisit` subsection, and 6 cited verification artifacts.
- [x] `verify_adr.py` and `verify_artifacts.py` are stdlib-runnable and both exit 0.
- [x] Operator typed `approved` at the Task 4 checkpoint.
- [x] All 4 Plan-3 files in single atomic commit `a0b8444` titled `docs(00): plan 3 — vendor comparison + provider ADR (closes phase 0)`.
- [x] `git log --oneline -5` shows 3 sequential Phase 0 plan-commits (plan 1 `22ddb9c`, plan 2 `c7d005a`, plan 3 `a0b8444`), interleaved with the 2 plan-SUMMARY commits.

## Phase 0 success criteria check (from ROADMAP.md)

- [x] **Criterion 1:** `.planning/decisions/0001-data-provider.md` is committed and documents (a) verified Twelve Data ES coverage as of the ADR date (negative — `commodities_ES.body.data == []`), (b) TradingView MCP confirmed as the v1 primary feed with rationale, (c) the eventual futures-aware swap candidate (Databento, with cost/coverage notes).
- [x] **Criterion 2:** A PowerShell-runnable smoke-test script spawns the `tradingview-mcp-jackson` server, completes `chart_set_symbol`, pulls `data_get_ohlcv` for ES 1m for the previous RTH session, and recovers cleanly after a deliberate TV restart. Full transcript stored under `.planning/research/spike-0/` (`tv-mcp-transcript.log`, `tv-restart-test.log`).
- [x] **Criterion 3:** A Twelve Data smoke call against `/stocks?symbol=ES`, `/commodities?symbol=ES`, and `/etf?symbol=SPY` documents response shapes, rate-limit headers, and the per-day-budget estimate for a 2-year SPY 1m backfill (`twelvedata-probe.json` and `spy-bar-budget.md`).

**Phase 0 status: CLOSED. Phase 1 (Foundation + Data In) is unblocked.**
