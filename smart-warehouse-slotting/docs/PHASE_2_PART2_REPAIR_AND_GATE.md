# Phase 2 · Part 2 — Constraint-safe repair, status vocabulary, evaluation gate

Scope: close the three defects assigned to P2-2 in `docs/PHASE_1_BASELINE_VERIFICATION.md`
(§E.1 partial, §E.2, and the missing repair phase). No Phase 3/4 work, no constraint relaxation,
no radius change, no test weakening.

- Repo: `/home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting`
- Dataset (read-only): `../dataset/processed`
- Python: `.venv/bin/python`
- Separation radius in force: `10.0 m` (`configs/benchmark.json` → `Config.separation_radius_m`)

---

## 1. What changed

| Defect | Fix |
|---|---|
| Repair/refinement could leave or create hard violations; an infeasible starter had no repair path | New bounded, deterministic, cycle-guarded repair loop (`SlottingOptimizer._repair`) that screens every move with the **full** validator and only accepts moves that remove violations without creating new ones; `_refine` now never returns a layout that is less feasible than its input |
| Feasibility was conflated with execution | `optimization_summary.json` now carries `execution_status`, `feasibility_status`, `assignment_completeness` and a structured `objective`, while keeping every previous key |
| No evaluation gate | `run_phase6` validates baseline and optimized **before** scoring; if either is infeasible it writes `evaluation_status: BLOCKED_INFEASIBLE_LAYOUT`, labels all metrics `diagnostic_only`, publishes no comparison, and `run-all`/`simulate` exit non-zero |

## 2. Repair algorithm (`src/optimization/optimizer.py`)

Trigger: the chosen starter (greedy or baseline, whichever the optimizer selected) fails the
independent validator. A feasible starter is reported as `already_feasible` and costs nothing.

Targeting (`_problem_bins`, diagnostics only — the validator still judges):
- bin-level violations contribute their own bin;
- aggregate rules (`SL-02` beam, `SL-01` level, `RK-01` rack) name a scope, so the overloaded
  scopes are recomputed with the validator's own aggregation and every bin carrying load in
  them is added;
- `CAT-01` contributes the reported bin plus any bin within the radius holding a forbidden
  counterpart category, so either side of the pair can be moved.

Candidate moves (`_repair_candidates`), per problem record in sorted
`(sku_id, location_id, index)` order, capped at `max_problem_records` (80):
1. **Relocate**: the record moves (quantity unchanged) to a statically eligible, unoccupied bin,
   nearest-to-dispatch first, capped at `max_candidates_per_record` (40).
2. **Swap**: the record trades bins with another record when both SKUs statically accept the
   other's bin, sorted, capped at 40.

Every candidate is evaluated by `validator.validate(candidate, record_checks=False)` — all
rules, not just the violated one.

Acceptance rule (`_is_strict_improvement`):
- reject any candidate that contains a violation key `(rule_id, sku_id, location_id)` the current
  layout does not already have — a move may never fix one scope by breaking another;
- accept when the violation count strictly decreases;
- or when the count is equal but the severity-ordered score (`high=1000, medium=100, low=10`)
  decreases and no key was added.

Bounds and determinism:
- `RepairConfig(max_moves=400, max_seconds=20.0, max_candidates_per_record=40, max_problem_records=80)`
  on `OptimizerConfig.repair`; no RNG — sorted iteration only, so the same input produces the
  same move sequence;
- cycle guard: a set of layout digests; a repeated assignment vector is never re-evaluated
  (`cycles_detected`).

Reported (`optimization_summary.repair`, also `OptimizationLog.repair`): `initial_violations`,
`final_violations`, per-rule breakdowns before/after, severity scores, `moves_attempted`,
`moves_accepted`, `moves_rejected`, `cycles_detected`, `unresolved_violations`,
`termination_reason` (`already_feasible | feasible | no_improving_move | max_moves | max_time`),
`feasible`, `runtime_sec`, and the configured bounds.

If feasibility is not reached within bounds, the best layout found (monotone improvement) is
returned and the run is reported **INFEASIBLE** — never as success.

`_refine` changes: it validates its input, treats an infeasible input as score `+inf`, accepts
only feasible neighbours, tracks `best` only among feasible layouts, and returns the input
unchanged when no feasible neighbour exists. Final selection in `optimize()` prefers any feasible
candidate (lowest objective) over any infeasible one.

## 3. Status vocabulary (`outputs/optimized/optimization_summary.json`)

| Key | Values | Meaning |
|---|---|---|
| `execution_status` | `OK` \| `ERROR` | Did the process complete? On a crash the summary is still written with `ERROR`, the exception text, `feasibility_status: null` and `feasibility_evaluated: false`; the exception is re-raised. |
| `feasibility_status` | `FEASIBLE` \| `INFEASIBLE` | Derived **only** from `Validator.validate(optimized)`; never from optimizer bookkeeping. |
| `feasibility` | `true` \| `false` | Back-compat boolean alias for `feasibility_status`. |
| `assignment_completeness` | object | `units_required`, `units_placed`, `units_unplaced`, `complete`, `completeness_pct`, `unresolved_skus` (SKUs whose placed quantity ≠ on-hand). |
| `objective` | object | `value`, `baseline_value`, `starter_value`, `per_rule_violations`, `violation_severity_score`, `globally_optimal: false`. |
| `repair` | object | Repair statistics above. |

Kept for existing readers: `dataset`, `algorithm`, `objective_weights`, `separation_radius_m`,
`n_assignments`, `n_bins_used`, `n_skus_with_inventory`, `inventory_units`, `units_placed`,
`units_unplaced`, `unplaced_skus`, `n_violations`, `violations_by_rule`, `baseline_feasibility`,
`baseline_violations_by_rule`, `baseline_objective`, `starter_objective`, `final_objective`,
`objective_improvement_pct`, `starter_beam_violations`, `separation_grid`, `moves_evaluated`,
`moves_accepted`, `runtime_sec`, `stopping_reason`, `globally_optimal`, `top_violations` (when
infeasible). New: `baseline_feasibility_status`, `starter_feasible`. `run_history.json` entries
gain `execution_status`, `feasibility_status`, `violations_by_rule`, `repair_termination`,
`repair_moves_accepted`.

## 4. Evaluation gate (`src/simulation/pipeline.py::run_phase6`)

Order of operations: load → build both layouts → **validate both with the independent validator
(configured radius)** → simulate → metrics.

If either layout is infeasible:

- `evaluation_status: "BLOCKED_INFEASIBLE_LAYOUT"`, `comparison_valid: false`,
  `diagnostic_only: true`, `blocked_layouts: ["baseline" | "optimized"]`, `blocked_reason`;
- `feasibility` records each layout's `feasibility_status`, `n_violations`,
  `violations_by_rule`, `checks_run`, `top_violations`;
- `comparison` is an **empty list**; the table is only available as `diagnostic_comparison`,
  every row carries `diagnostic_only: true`, and `optimization_metrics.csv` gets a
  `diagnostic_only` column (`True`);
- `notes.comparison_published_as_valid_evidence: false`,
  `notes.comparison_is_diagnostic_only: true`;
- the diagnostic route/metric files are still written so the cause can be inspected, but they
  can no longer be mistaken for a valid comparison.

Exit codes: `app/main.py simulate` and `app/main.py run-all` raise `SystemExit` with a clear
message when the gate blocks (process exit code 1). `run-all` prints
`evaluation_status=BLOCKED_INFEASIBLE_LAYOUT` and the blocked layout list.

When both layouts are feasible: `evaluation_status: "OK"`, `comparison_valid: true`,
`diagnostic_only: false`, and the full `comparison` table is published; metrics rows carry
`diagnostic_only: false`.

`run_phase6` gained the keyword argument `separation_radius_m` (default
`DEFAULT_SEPARATION_RADIUS_M`); the CLI and the dashboard form pass `Config.separation_radius_m`.
`app/main.py simulate` gained `--config` so that radius comes from the same config as everywhere
else.

Dashboard (minimal, only to stop blocked metrics being displayed as normal): an error banner on
the Overview tab and the Exports tab when `evaluation_status == BLOCKED_INFEASIBLE_LAYOUT`, the
optimization block now shows `feasibility_status`, repair statistics and completeness, and
`report_payload` carries `evaluation_status`, `comparison_valid` and `blocked_layouts`.

## 5. Evidence (actual runs, final code state)

### 5.1 Full test suite

```
.venv/bin/python -m pytest tests/ -q --tb=line -p no:cacheprovider
4 failed, 113 passed in 221.89s (0:03:41)
```

The same four failures exist before and after this change (pre-change baseline measured at the
start of this card: `4 failed, 113 passed`). None is caused by P2-2:

| Test | Cause | Owner |
|---|---|---|
| `test_phase4_validator::test_baseline_feasible_on_benchmark` | Asserts the canonical baseline is feasible; the independent validator reports **1,071 CAT-01** violations at the configured 10 m radius. | P2-3 (restate as a gate-aware contract) |
| `test_phase5_optimizer::test_optimizer_improves_over_baseline` | Same assumption: `assert summary["baseline_feasibility"] is True`; the optimizer itself is feasible and better (902,392.9 < 2,336,184.1). | P2-3 |
| `test_phase6_evaluation::test_optimized_feasible_and_better` | `assert result["baseline"]["constraint_violations"] == 0`; baseline has 1,071 (reported, not hidden). The evaluation is now blocked, which is the intended Phase-2 behaviour. | P2-3 |
| `test_phase8_integration::test_constraint_audit_is_not_header_only` | Reads the mutable `outputs/constraint_audit.csv` and expects every row to pass; it now contains the baseline's 1,071 failing CAT-01 rows. Artifact-state dependent. | P2-3 |

### 5.2 Optimizer (canonical dataset)

```
.venv/bin/python app/main.py optimize --processed ../dataset/processed --config configs/benchmark.json
exit 0
execution_status: OK
feasibility_status: FEASIBLE    (independent validator: 0 violations)
assignment_completeness: 6375 / 6375 units, complete=true, unresolved_skus=[]
objective: 902392.9055567493 (baseline 2336184.1414095755, +61.373%)
violations_by_rule: {}
repair: termination_reason=already_feasible, moves_attempted=0, unresolved_violations=0
n_assignments=1288, n_bins_used=1288, runtime_sec=32.177
stopping_reason: max iterations reached (annealing)
```

Repair is a no-op on the canonical path because the P2-1 starter is already feasible — that is
the correct report, not a skipped check (`initial_violations=0`).

### 5.3 Evaluation gate (canonical dataset)

```
.venv/bin/python app/main.py simulate --processed ../dataset/processed --scenario A
exit 1
evaluation_status: BLOCKED_INFEASIBLE_LAYOUT
blocked_layouts: ["baseline"]
baseline : INFEASIBLE 1071  {"CAT-01": 1071}
optimized: FEASIBLE   0     {}
comparison rows published: 0 | diagnostic rows: 18 (all diagnostic_only=true)
stderr: BLOCKED by the feasibility gate: ... The diagnostic metrics are not valid evidence;
        fix the layouts and re-run.
```

`run-all` (same dataset, `--scenario A`) exits **1** and prints:

```
== validate ==
   baseline feasible=False violations=1071 checks=20699
== optimize ==
   execution=OK feasibility=FEASIBLE violations=0 rules={}
== simulate ==
   evaluation_status=BLOCKED_INFEASIBLE_LAYOUT
```

### 5.4 Gate positive control (both layouts feasible)

A scratch copy of the dataset whose `storage_assignments_baseline.csv` is the feasible optimized
layout (all other files symlinked read-only) runs clean:

```
exit 0
evaluation_status: OK, comparison_valid: true, diagnostic_only: false
feasibility: baseline FEASIBLE 0, optimized FEASIBLE 0
published comparison rows: 18 ; optimization_metrics.csv diagnostic_only = False
```

An optimized-only infeasible layout blocks too (`blocked_layouts: ["optimized"]`, exit 1).

### 5.5 Repair exercised directly

| Case | Input | Result |
|---|---|---|
| Two 100 kg SKUs on one 180 kg beam, empty bin on another beam | 1 × SL-02 | `moves_attempted=1, moves_accepted=1, termination=feasible`, final 0 violations, record relocated to the other beam |
| Same overload, no alternative beam | 1 × SL-02 | `termination=no_improving_move, feasible=false, unresolved=1`; input returned unchanged and reported INFEASIBLE |
| Trade-off move (SL-02+CAT-01 → SL-02+INV-02) | 2 violations | rejected by `_is_strict_improvement` (new violation key) |
| Already feasible | 0 violations | `already_feasible`, 0 moves, layout untouched |
| Real canonical baseline (1,071 CAT-01) with `max_moves=40` | dense infeasibility | 40 attempts in 2.35 s, `termination=max_moves`, `feasible=false`, 1,071 unresolved — bounded and honest |
| Inventory that cannot fit (2 × 60 kg in one 100 kg bin) via `optimize()` | under-stored | `feasibility_status=INFEASIBLE`, `stopping_reason="1 violations after repair (no_improving_move) and refinement"` |

### 5.6 Execution-error contract

`run_phase5` against an empty directory raises `FileNotFoundError` **and** leaves
`optimization_summary.json` with `execution_status: "ERROR"`,
`feasibility_status: null`, `feasibility_evaluated: false`, and the error text — a crash is not
reported as an infeasible layout.

## 6. Files changed

- `src/optimization/optimizer.py` — `RepairConfig`, `RepairStats`, `_problem_bins`,
  `_repair_candidates`, `_repair`, `_is_strict_improvement`, `_record_digest`,
  `_violation_breakdown/keys/severity`, `_static_eligible`; `_refine` rewritten to accept only
  feasible neighbours and never downgrade feasibility; `optimize()` runs repair on the chosen
  starter before refinement and selects the final layout by (feasible, objective).
- `src/optimization/pipeline.py` — status vocabulary, `assignment_completeness`, `objective`,
  `repair`, `baseline_feasibility_status`, `starter_feasible`, execution-error summary,
  extended `run_history.json` entries.
- `src/simulation/pipeline.py` — feasibility gate, `BLOCKED_INFEASIBLE_LAYOUT`, per-layout
  feasibility evidence, `diagnostic_only` labelling, `separation_radius_m` parameter.
- `app/main.py` — `simulate --config`; radius threading; non-zero exit from `simulate`/`run-all`
  when the gate blocks; optimizer warning when its layout is infeasible.
- `app/dashboard.py` — blocked-evaluation banners (Overview, Exports), solver-status/repair/
  completeness captions, radius threaded into the dashboard-triggered evaluation.
- `app/dashboard_data.py` — `report_payload` carries `evaluation_status`, `comparison_valid`,
  `blocked_layouts`; `optimization` availability is false after an `ERROR` run.
- `docs/PHASE_2_PART2_REPAIR_AND_GATE.md` — this document.
- Regenerated pipeline artifacts under `outputs/` (`optimized/`, `evaluation/`, `analysis/`,
  root validation files) from the commands above.

## 7. Reproduce

```bash
cd /home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting
.venv/bin/python -m pytest tests/ -q --tb=line -p no:cacheprovider
.venv/bin/python app/main.py optimize --processed ../dataset/processed --config configs/benchmark.json
.venv/bin/python app/main.py simulate --processed ../dataset/processed --scenario A   # exit 1 while the baseline is infeasible
.venv/bin/python app/main.py run-all --processed ../dataset/processed --scenario A     # exit 1, gate message
```
