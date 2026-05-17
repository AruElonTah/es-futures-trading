# Optimization Run ADR — [Short Title]

**Date:** YYYY-MM-DD
**Status:** proposed | accepted | superseded
**Author:** [author]

---

## Context

[Describe why you are running this optimization. What question are you trying to answer?
What hypothesis does this grid test?]

---

## Decision

Run a grid + walk-forward optimization with the following parameters:

### Required Fields

| Field | Value | Notes |
|-------|-------|-------|
| `is_oos_split` | IS=6m OOS=1m rolling step=1m | Format: "IS=Xm OOS=Ym rolling step=Zm". Validated by `run_opt.py` by name. |
| `optspace_path` | config/strategies/orb.optspace.yaml | Path to the optspace.yaml defining the parameter grid |
| `objective` | oos_sharpe | Must be `oos_sharpe` — OPT-07 requirement. `run_opt.py` refuses any other value. |
| `seed` | 42 | Integer seed for reproducibility. Written to every `opt_runs` row. |

### Walk-Forward Configuration

- **IS window:** [e.g., 6 months / ~126 trading days]
- **OOS window:** [e.g., 1 month / ~21 trading days]
- **Step:** [e.g., 1 month — rolling forward]
- **Expected fold count:** [e.g., 8 folds over a 14-month bar window]

### Data Range

- **Symbol:** [e.g., SPY or CME_MINI:ES1!]
- **Timeframe:** [e.g., 1m]
- **From:** [YYYY-MM-DD]
- **To:** [YYYY-MM-DD]
- **Holdout guard:** [yes/no — if yes, `--burn-holdout` passed to `run_opt.py`]

---

## Rationale

[Why these parameter ranges? What prior run (if any) justifies narrowing from a coarse grid?
Reference the prior `opt_runs.run_id` if this is a fine-grid refinement (OPT-06 coarse-first rule).]

---

## Expected Outcomes

[What OOS Sharpe or edge ratio would indicate a positive result?
What result would lead you to abandon this parameter region?]

---

## Consequences

- ADR hash will be written to every `opt_runs` row for forensic provenance.
- Results are immutable once written — do not re-use a `run_id`.
- If `--burn-holdout` is used, this counts against the 3-burn quarterly quota (OPT-08).

---

## Acceptance Criteria

- [ ] `run_opt.py` completes without error (all 125 combos × N folds)
- [ ] `opt_results` table populated with expected row count
- [ ] OOS Sharpe leaderboard reviewed at `/optimizations`
- [ ] IS/OOS edge ratio < 2.0 for selected candidates (no obvious overfitting)
