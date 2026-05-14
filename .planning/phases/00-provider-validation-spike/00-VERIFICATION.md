---
phase: 00-provider-validation-spike
verified: 2026-05-14T18:30:00Z
status: passed
score: 3/3 success criteria verified
overrides_applied: 0
re_verification:
  previous_status: null
  previous_score: null
  gaps_closed: []
  gaps_remaining: []
  regressions: []
requirements_traceability:
  - id: FND-10
    description: "Provider-validation ADR committed to .planning/decisions/ documenting (a) Twelve Data's ES coverage as of the ADR date, (b) the chosen v1 primary feed (TradingView MCP) and rationale, (c) the eventual futures-aware swap candidate (Databento / Polygon Futures / IB)"
    declared_in_plans: ["00-01-PLAN.md", "00-02-PLAN.md", "00-03-PLAN.md"]
    status: SATISFIED
    evidence: ".planning/decisions/0001-data-provider.md contains all three mandated findings; verify_adr.py exits 0; the 6 cited verification artifacts exist on disk."
notes:
  - "ROADMAP marks Phase 0 with `Mode: mvp` but the phase goal is not in User-Story format. Verification proceeded against the 3 explicit Success Criteria from ROADMAP (the user-provided authoritative truths), not against an MVP user-flow table — informational only."
  - "REQUIREMENTS.md status table line 193 still lists FND-10 as 'Pending'. All three Plan SUMMARYs claim `requirements-completed: [FND-10]` and the ADR satisfies the requirement verbatim. The status-table row appears to be a stale tracking entry, not a substantive gap. Recommend updating REQUIREMENTS.md line 193 to 'Done' when Phase 0 is officially closed by the orchestrator."
---

# Phase 0: Provider Validation Spike — Verification Report

**Phase Goal:** Resolve the data-vendor unknown so Phase 1 can commit a `DataSource` implementation without rework.
**Verified:** 2026-05-14T18:30:00Z
**Status:** passed
**Re-verification:** No — initial verification

---

## Goal Achievement

The phase goal is achieved when the three ROADMAP Success Criteria are observably true in the codebase. All three are verified with concrete artifacts.

### Observable Truths (ROADMAP Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `.planning/decisions/0001-data-provider.md` ADR is committed and documents (a) verified Twelve Data ES coverage as of ADR date, (b) TradingView MCP confirmed as v1 primary feed with rationale, (c) eventual futures-aware swap candidate (Databento) with cost/coverage notes | ✓ VERIFIED | ADR exists at the canonical path (13,658 bytes, committed in `a0b8444`). Context §2 cites `twelvedata-probe.json` and states ES not in catalog. Decision §1 names TV MCP primary with rationale grounded in Phase 0 spike findings. Decision §3 names Databento with $199/$1,399/$3,500 monthly tiers and pay-as-you-go historical noted. |
| 2 | Smoke-test script spawns `tradingview-mcp-jackson` server, completes `chart_set_symbol`, pulls `data_get_ohlcv` for ES 1m for previous RTH session, and recovers cleanly after deliberate TV restart — full transcript stored under `.planning/research/spike-0/` | ✓ VERIFIED | `scripts/spike/tv_mcp_smoke.py` (19,039 bytes) spawns Node MCP via `stdio_client`. `tv-mcp-transcript.log` (51 lines) shows `tool=chart_set_symbol` (`CME_MINI:ES1!`), `tool=chart_set_timeframe` (`1`), `tool=chart_scroll_to_date` (`2026-05-13T20:00:00+00:00`), `tool=data_get_ohlcv` returning **300 bars** (ES price action 7493–7517). `tv-restart-test.log` (30 lines) shows pre-restart 3 OK cycles → `BEFORE_RESTART_MARKER` → FAIL cycles 13–14 (CDP unreachable + JS `_activeChartWidgetWV undefined`) → `AFTER_RESTART_MARKER` → 3 post-restart OK cycles → `RESULT: conclusive`. |
| 3 | Twelve Data smoke call against `/stocks?symbol=ES`, `/commodities?symbol=ES`, and `/etf?symbol=SPY` documents response shapes, rate-limit headers, and per-day-budget estimate for 2-year SPY 1m backfill (~196k bars) | ✓ VERIFIED | `twelvedata-probe.json` (6,381 bytes) records all 4 probes (+ `timeseries_SPY`) with `http_status`, `headers.api-credits-used` / `api-credits-left`, and full `body` (Eversource Energy collision on `/stocks`, empty array on `/commodities`, 5 SPY ETF entries, 5 1-min bars on `/time_series` with `1 used / 7 left`). `spy-bar-budget.md` (3,882 bytes) documents 196,560 bars / 40 calls / ~5 min wall-clock with 9 s pacing on Free tier (5% daily budget). |

**Score:** 3/3 truths verified.

### Required Artifacts (Level 1–3: Exists, Substantive, Wired)

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `.planning/decisions/0001-data-provider.md` | MADR ADR with 8 H2 sections + `### When to revisit`; cites 6 verification artifacts | ✓ VERIFIED | 13,658 bytes; `verify_adr.py` exits 0 with `PASS: ADR shape OK (size=13658 bytes, sections=8, citations=6)`. Frontmatter parses (`adr_id: 0001`, `slug: data-provider`, `status: accepted`, `deciders: [Nathaniel Greene]`, `date: 2026-05-14`). |
| `.planning/research/spike-0/twelvedata-probe.json` | 4 probes with raw response bodies + rate-limit headers + redacted URLs | ✓ VERIFIED | 6,381 bytes; all 4 probe keys present (`stocks_ES`, `commodities_ES`, `etf_SPY`, `timeseries_SPY`); `apikey=<TWELVEDATA_API_KEY>` redaction holds (4/4 occurrences redacted, 0 raw keys). |
| `.planning/research/spike-0/spy-bar-budget.md` | 196,560-bar math + per-tier table + recommendation + observed-headers | ✓ VERIFIED | 3,882 bytes; contains `Total bars: 196,560`, per-tier feasibility table, "1min SPY is available on the operator's current tier" verification (branch a), observed-headers table, calculation worksheet block. |
| `.planning/research/spike-0/tv-mcp-tools.json` | Sorted tool list + `all_required_present: true` | ✓ VERIFIED | 2,138 bytes; `tool_count: 81`; `required_tools_present` shows all 4 (`tv_health_check`, `chart_set_symbol`, `chart_set_timeframe`, `data_get_ohlcv`) = true; `all_required_present: true`. |
| `.planning/research/spike-0/tv-mcp-transcript.log` | ≥50 lines, 3 critical tool-call markers | ✓ VERIFIED | 6,110 bytes, 51 lines. Contains `tool=tv_health_check`, `tool=chart_set_symbol`, `tool=data_get_ohlcv`. End-of-run summary block confirms `calls_made=7`, `tool_count_observed=81`. Restore-on-exit confirmed (lines 45–51 show restore to `CME_MINI:ESM2026`/`3`). |
| `.planning/research/spike-0/tv-mcp-stderr.log` | Forensic dump (placeholder acceptable) | ✓ VERIFIED | 253 bytes — placeholder note documenting that mcp SDK 1.x's `stdio_client` does not expose subprocess stderr. Limitation explicitly carried forward as an ADR Consequence (Negative bullet 3) for Phase 6 TVBridge. |
| `.planning/research/spike-0/tv-restart-test.log` | ≥30 lines with BEFORE/AFTER markers + observed FAIL + `RESULT: conclusive` | ✓ VERIFIED | 2,760 bytes, 30 lines. `BEFORE_RESTART_MARKER` at line 11, `AFTER_RESTART_MARKER` at line 25, FAIL cycles at lines 21–22 (between markers), final line: `RESULT: conclusive`. `observed_failure_during_restart=True` confirmed in summary. |
| `.planning/research/spike-0/comparison-table.md` | 5-vendor table re-verified as-of date | ✓ VERIFIED | 6,583 bytes; all 5 vendors present (Twelve Data, Databento, Massive, IB historical, CME DataMine); `Verified: 2026-05-14`; "Why Databento", "Do-not-swap-to", and "Findings from the Phase 0 spike" sections all present. |
| `scripts/spike/twelvedata_probe.py` | Stdlib-only 4-endpoint probe | ✓ VERIFIED | 5,953 bytes; carries `PHASE 0 SPIKE` sentinel; uses `urllib.request` (no `httpx` / `requests` per grep). |
| `scripts/spike/tv_mcp_smoke.py` | Async MCP client w/ allowlist + restore | ✓ VERIFIED | 19,039 bytes; uses `mcp.ClientSession` + `stdio_client`; `ALLOWED_TOOLS` + `REQUIRED_TOOLS` allowlists present; restore-on-exit confirmed by transcript lines 45–51. |
| `scripts/spike/tv_mcp_restart.py` | Restart-cycle state machine w/ markers | ✓ VERIFIED | 15,466 bytes; BEFORE/AFTER markers + `observed_failure_during_restart` flag; file-marker resume path documented as Deviation #1 in SUMMARY (acceptable — orchestrator drives from non-TTY). |
| `scripts/spike/verify_adr.py` | Stdlib-runnable ADR shape check | ✓ VERIFIED | 4,804 bytes; exits 0; checks size 1.5–20 KB, 8 H2 sections, frontmatter required keys, 6 cited artifacts. |
| `scripts/spike/verify_artifacts.py` | Stdlib-runnable artifact manifest check | ✓ VERIFIED | 2,096 bytes; exits 0; checks 8-entry manifest with minimum-byte thresholds. |

### Key Link Verification (Level 4: Data Flowing)

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `.planning/decisions/0001-data-provider.md` | `twelvedata-probe.json` | Verification artifacts §, cited by relative path | ✓ WIRED | Cited in Verification artifacts §; file exists on disk (6,381 bytes); `verify_adr.py` asserts citation present. |
| `.planning/decisions/0001-data-provider.md` | `tv-mcp-transcript.log` | Verification artifacts §, cited by relative path | ✓ WIRED | Cited; file exists (6,110 bytes); referenced in Context §2 (300-bar smoke result). |
| `.planning/decisions/0001-data-provider.md` | `tv-restart-test.log` | Verification artifacts §, cited by relative path | ✓ WIRED | Cited; file exists (2,760 bytes); referenced in Decision § for `RESULT: conclusive`. |
| `.planning/decisions/0001-data-provider.md` | `spy-bar-budget.md` | Positive Consequences § + Verification artifacts § | ✓ WIRED | Cited; file exists (3,882 bytes); referenced in Positive Consequences (~5 min wall-clock cite). |
| `.planning/decisions/0001-data-provider.md` | `comparison-table.md` | Verification artifacts § | ✓ WIRED | Cited; file exists (6,583 bytes). |
| `.planning/decisions/0001-data-provider.md` | `tv-mcp-tools.json` | Verification artifacts § + Negative Consequences § | ✓ WIRED | Cited; file exists (2,138 bytes); referenced for `tool_count: 81` pin. |
| `verify_artifacts.py` | 8-entry manifest of spike artifacts | `pathlib.Path.exists()` + `stat().st_size` per entry | ✓ WIRED | Re-run confirmed exit 0 with all 8 PASS lines. |
| `verify_adr.py` | ADR shape | `re.search` for sections, frontmatter parse, citation substring check | ✓ WIRED | Re-run confirmed exit 0. |
| `twelvedata_probe.py` | `twelvedata-probe.json` | `urllib.request.urlopen` → `json.dumps` → `Path.write_text` | ✓ WIRED + DATA FLOWING | JSON shows live response bodies dated `2026-05-14T17:11:03.517307+00:00` with real data (3 Eversource entries on `/stocks`, 5 SPY ETF entries on `/etf`, 5 1-min bars on `/time_series`). |
| `tv_mcp_smoke.py` | `tv-mcp-transcript.log` + `tv-mcp-tools.json` | `_log()` helper + `Path.write_text` at end of `main()` | ✓ WIRED + DATA FLOWING | Transcript shows live ES bars (open=7493.75 … 7517.75) from `2026-05-14T17:32Z` run; tools.json shows 81 enumerated tool names. |
| `tv_mcp_restart.py` | `tv-restart-test.log` | Per-cycle log writes + BEFORE/AFTER sentinels | ✓ WIRED + DATA FLOWING | 30-line log shows real failure window (cycle 13: `tool call timed out`; cycle 14: `JS evaluation error: TypeError: Cannot read properties of undefined`) bracketed by markers. |

### Probe Execution (Step 7c)

| Probe | Command | Result | Status |
|-------|---------|--------|--------|
| `scripts/spike/verify_artifacts.py` | `.venv-spike/Scripts/python.exe scripts/spike/verify_artifacts.py` | `=== ALL 8 ARTIFACTS PRESENT AND NON-EMPTY ===` (exit 0) | ✓ PASS |
| `scripts/spike/verify_adr.py` | `.venv-spike/Scripts/python.exe scripts/spike/verify_adr.py` | `PASS: ADR shape OK (size=13658 bytes, sections=8, citations=6)` (exit 0) | ✓ PASS |

Both probes shipped in this phase were re-executed by the verifier from a clean process and both exit 0 against the committed state of the repo.

### Behavioral Spot-Checks (Step 7b)

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| ADR redaction holds — no raw API key in committed JSON | `grep -c "apikey=" twelvedata-probe.json` vs `grep -c "apikey=<TWELVEDATA_API_KEY>"` | 4 total = 4 redacted | ✓ PASS |
| Git history sequence intact — Phase 0 commits in expected order | `git log --oneline -8` | 3 plan commits + 3 SUMMARY commits + 2 prior-Phase-0 commits in order | ✓ PASS |
| TV MCP smoke can re-run on demand (live TV w/ CDP per environment hint) | `tv_mcp_smoke.py` — not re-executed; sufficient evidence in committed transcript | — | ? SKIP (would mutate operator's chart; transcript already captures conclusive run) |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| FND-10 | 00-01-PLAN.md, 00-02-PLAN.md, 00-03-PLAN.md | Provider-validation ADR documenting Twelve Data ES coverage, v1 primary feed (TV MCP) + rationale, swap candidate (Databento) | ✓ SATISFIED | ADR `.planning/decisions/0001-data-provider.md` covers all 3 mandated findings verbatim. `verify_adr.py` exit 0 is the re-runnable assertion that the shape holds. |

**Orphaned requirements:** None. FND-10 is the sole Phase 0 requirement per ROADMAP and REQUIREMENTS.md row 193; all three plans declared it in their frontmatter `requirements:` field.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| — | — | — | — | No `TBD`, `FIXME`, `XXX`, `TODO`, `HACK`, `PLACEHOLDER` found in any of the 5 spike scripts. No anti-patterns in the ADR body. The `tv-mcp-stderr.log` placeholder is documented explicitly in the ADR's Negative Consequences (mcp SDK 1.x limitation), so it is not unresolved debt — it is a known constraint carried forward to Phase 6. |

### Human Verification Required

None. All three ROADMAP Success Criteria are programmatically verifiable against committed artifacts. The operator-review checkpoint at Plan 3 Task 4 ("type approved") already occurred before the closing commit landed (per `00-03-SUMMARY.md` line 57). Subjective ADR quality is the operator's responsibility at that gate; the verifier does not re-judge it.

### Gaps Summary

No gaps. All artifacts exist with substantive content. The ADR cites real spike findings (not aspirational ones). The smoke transcript shows live ES bars at real prices and a conclusive restart cycle. The Twelve Data probe documents the expected negative on ES and the expected positive on SPY 1m. Two re-runnable verification scripts (shipped this phase) both exit 0 from a fresh process.

### Minor Tracking Inconsistency (Informational, Not a Gap)

`.planning/REQUIREMENTS.md` line 193 still shows `| FND-10 | Phase 0 | Pending |` in the status table even though all three Plan SUMMARYs declare `requirements-completed: [FND-10]` and the ADR satisfies the requirement. This is a documentation-bookkeeping lag, not a substantive gap — the requirement is observably satisfied in the codebase. Recommend the orchestrator update line 193 to `Done` (or equivalent) when officially marking Phase 0 closed.

---

_Verified: 2026-05-14T18:30:00Z_
_Verifier: Claude (gsd-verifier)_
