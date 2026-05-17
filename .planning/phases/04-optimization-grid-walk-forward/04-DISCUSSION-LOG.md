# Phase 4: Optimization Grid + Walk-Forward - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-17
**Phase:** 04-optimization-grid-walk-forward
**Areas discussed:** optspace.yaml design + ORB grid bounds, Walk-forward window type, ProcessPoolExecutor work unit, Optimization UI placement

---

## optspace.yaml Design + ORB Grid Bounds

| Option | Description | Selected |
|--------|-------------|----------|
| Embedded in orb.yaml | Add an `optspace` block to the existing strategy config file | |
| Standalone file (`orb.optspace.yaml`) | Separate file — strategy behavior vs search bounds are distinct concerns | ✓ |
| `type: range/step` syntax | Arithmetic ranges (min/max/step) | |
| `type: list` syntax | Explicit value lists — better for non-uniformly-spaced ORB params | ✓ |

**User's choice:** Claude's discretion (user said "proceed as you see fit")
**Notes:** List syntax chosen because ORB param values (5, 10, 15, 20, 30 minutes; 1.0–3.0 ATR mult) aren't evenly spaced in a meaningful way. Separate file keeps strategy config clean. First coarse grid: 5×5×5 = 125 combos, matching ROADMAP success criterion #2 example exactly.

---

## Walk-Forward Window Type

| Option | Description | Selected |
|--------|-------------|----------|
| Anchored (expanding IS window) | IS window grows from a fixed start date; OOS steps forward | |
| Rolling (fixed-width IS window) | IS window of fixed duration slides forward; keeps training data recent | ✓ |

**User's choice:** Claude's discretion
**Notes:** Rolling chosen because it keeps IS data recent — anchored windows accumulate increasingly stale bars, which is problematic for regime-sensitive ORB strategies. Default: IS=6m, OOS=1m, step=1m. VectorBT OSS `Splitter.from_n_rolling()` supports this natively.

---

## ProcessPoolExecutor Work Unit

| Option | Description | Selected |
|--------|-------------|----------|
| Per-(combo × fold) task | One task per (param set, fold) pair — finer granularity, more IPC overhead | |
| Per-param-combo worker | One task per param set, worker runs all folds for that combo | ✓ |
| Per-fold worker | One task per fold, worker runs all 125 combos for that fold | |

**User's choice:** Claude's discretion
**Notes:** Per-param-combo chosen for simplicity: 125 futures, each worker loads bars once, runs walk-forward for its single param set, writes one Parquet shard. Matches ROADMAP language ("per-worker Parquet shards"). Fewer IPC boundaries than per-(combo × fold). Orchestrator aggregates 125 shards in a single pass.

---

## Optimization UI Placement

| Option | Description | Selected |
|--------|-------------|----------|
| New `/optimizations` route | Dedicated page — clean separation, no dashboard layout disruption | ✓ |
| New panel within `/dashboard` | Adds to existing 2-pane layout — Phase 7 will redo this anyway | |
| Modal / drawer from dashboard | Lightweight but cramped for a leaderboard + heatmap | |

**User's choice:** Claude's discretion
**Notes:** New route chosen to keep `/dashboard` clean ahead of Phase 7's multi-pane redesign. Dashboard gets a header link to `/optimizations`. Phase 7 will dock it as a resizable pane. Plotly heatmap via `react-plotly.js` per CLAUDE.md ("de facto choice").

---

## Claude's Discretion

All four areas were decided at Claude's discretion — user said "proceed as you see fit." Decisions are documented above with rationale grounded in ROADMAP requirements and the project's "trust the numbers" core value.

Additional discretionary choices captured in CONTEXT.md:
- Worker count defaults to `os.cpu_count() - 1`
- No live progress WebSocket in Phase 4 (2s polling instead — simpler)
- Coarse-grid-first check is structural (refuses the run if no prior coarser run exists), not just advisory

## Deferred Ideas

- Live WebSocket progress bar during optimization — Phase 7
- Docking `/optimizations` as a resizable dashboard pane — Phase 7
- Optimization run triggering from Strategy Controls panel — Phase 7
- Bayesian / Optuna / genetic optimization — v2 (explicit project constraint)
- Monte Carlo bootstrap bands — v2 (V2-OPT-03)
- Max-workers CLI flag — deferred if not needed
- Optimization run comparison / diff view — v2 candidate
