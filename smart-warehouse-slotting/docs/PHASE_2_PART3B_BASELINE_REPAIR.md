# Phase 2 · Part 3b — repairing the baseline to feasibility so a comparison can exist

Status: **done**. `run-all` exits **0**, `evaluation_status: OK`, `comparison_valid: true`,
`blocked_layouts: []`, with the gate itself unchanged.

Date: 2026-10-29 · Repo: `smart-warehouse-slotting` · Card: `t_c84341a8`

Every number below was re-measured on this machine after the change (command and exit codes in
§3, independent re-verification in §9). Nothing here is copied from an earlier run.

---

## 1. Why this card existed

The feasibility gate was doing its job. The layout it refused was the *baseline*:

| layout | rows | SKUs | units | violations | checks |
|---|---|---|---|---|---|
| baseline as supplied | 1,425 | 1,200 | 6,375 | **1,071 × CAT-01** | 20,699 |
| optimized | 1,288 | 1,200 | 6,375 | 0 | 15,167 |

`run-all` therefore exited 1 with `BLOCKED_INFEASIBLE_LAYOUT`, `comparison_valid: false`,
`diagnostic_only: true`, `blocked_layouts: ["baseline"]` — and the project had **no valid
improvement claim**, because there was nothing legal to compare against.

The fix is not to weaken the gate. It is to produce a baseline that is legal *without becoming
an optimization result*.

---

## 2. What the repair does (and does not do)

### Reuses the P2-2 repair engine

`SlottingOptimizer.repair_feasibility_only(assignments, repair=...)` runs the **same** loop
added in P2-2 (`_repair`): bounded (`max_moves`, `max_seconds`), deterministic, cycle-guarded
(`_record_digest`), and it screens **every** candidate with the full Phase-4 validator. The
acceptance rule is unchanged: *a move is accepted only when it strictly removes violations and
introduces none* (`_is_strict_improvement`).

### Objective fully disabled

Three properties are guaranteed by construction, not by convention:

* nothing in the repair path calls `Objective.evaluate` (pinned by
  `tests/test_baseline_repair.py::test_repair_never_consults_the_objective`, which makes
  `Objective.evaluate` raise and still gets a feasible repair); `repair_feasibility_only`
  contains no scoring call at all — it validates, repairs, and returns;
* there is **no starter selection** — the input layout is the layout being repaired;
* there is **no annealing / refinement pass** — refinement is objective-driven and is not run.

So travel, affinity, ergonomics and utilisation cannot influence a single accepted move.

### Smallest move that clears a constraint

`RepairConfig(candidate_mode="feasibility")` switches the neighbourhood from "relocate toward
dispatch, then swap" to:

1. only bins the placer predicts are already legal — unoccupied, statically eligible
   (fit/hazard/handling/heavy-height), CAT-01-clear against the *current* layout via the same
   `SeparationGrid` rule data and tolerance the validator uses, inside the bin's own weight and
   volume capacity, and inside the beam/level/rack residual (with the record's departure from
   its old scope accounted for exactly, never double-counted);
2. ordered by **3-D displacement from the record's current bin** — dispatch distance, the travel
   proxy the objective mode sorts by, is deliberately not consulted;
3. the generic P2-2 neighbourhood is still offered afterwards as a last resort, so the feasibility
   mode is never *narrower* than P2-2's.

Every candidate is still validated in full; the screen only decides what is *proposed*.

### One correctness fix the repair needed

`_violation_keys` used `(rule_id, sku_id, location_id)`. For CAT-01 that identity is unstable: the
rule reports *one side* of a bin pair, so a bin violating against 21 neighbours produced one key,
and moving that bin made the same physical pairs reappear under a different key — which
`_is_strict_improvement` then misread as "this move introduced 24 new violations". The repair
therefore rejected sound moves: 10 accepted / 852 rejected in 60 s.

`Violation` now carries an optional `pair` (the two bins, sorted) and `Violation.identity` uses it
for pairwise rules. This is bookkeeping only: no rule id, threshold, check, count, explanation or
persisted row changed — the as-supplied layout still reports exactly **1,071 CAT-01 at 20,699
checks**, and the per-rule check histogram is unchanged apart from the layout itself
(`CAT-01` 3,594 → 1,039, see §10). After the fix the same repair accepts **96 / 96** candidates
in 7.5 s.

### Failure semantics

If the repair cannot reach feasibility inside its bounds, the **repair result is not adopted**:
`baseline_variant` stays `as_supplied`, the evaluation keeps the illegal baseline, and the gate
keeps blocking. Pinned by
`test_repair_that_cannot_reach_feasibility_keeps_the_gate_blocking` (bounds `max_moves=0`).

---

## 3. Actual run — command, exit code, gate outcome

```
$ .venv/bin/python app/main.py run-all --processed ../dataset/processed --scenario A
== validate ==
   baseline feasible=False violations=1071 checks=20699
== baseline repair ==
   baseline_variant=repaired_minimal source=.../outputs/baseline_repaired_assignments.csv
   repair: 1071 -> 0 violations ({'CAT-01': 1071} -> {}), moves attempted=96 accepted=96
           rejected=0, terminated=feasible in 7.535s
   movement: 96/1425 records relocated, 1471.373 m total, median 12.01 m
   conservation: units 6375/6375 exact=True duplicate_pins=0
== analysis ==
== optimize ==
   execution=OK feasibility=FEASIBLE violations=0 rules={}
== simulate ==
   evaluation_status=OK comparison_valid=True blocked_layouts=[] baseline_variant=repaired_minimal
== done ==
EXIT=0        (real 0m53.993s)
```

| field | value |
|---|---|
| exit code | **0** |
| `execution_status` | `OK` |
| `evaluation_status` | `OK` |
| `comparison_valid` | `true` |
| `diagnostic_only` | `false` |
| `blocked_layouts` | `[]` |
| `baseline_variant` | `repaired_minimal` |
| baseline feasibility | `FEASIBLE`, 0 violations, 18,077 checks |
| optimized feasibility | `FEASIBLE`, 0 violations, 15,167 checks |
| comparison rows published | 18, every row `diagnostic_only: false` |

---

## 4. Repair statistics (verbatim from `outputs/optimized/optimization_summary.json`)

| stat | value |
|---|---|
| initial violations / by rule | 1,071 / `{"CAT-01": 1071}` |
| final violations / by rule | **0** / `{}` |
| initial → final severity score | 1,071,000 → **0** |
| moves attempted | 96 |
| moves accepted | **96** |
| moves rejected | 0 |
| cycles detected | 0 |
| unresolved violations | 0 |
| termination reason | `feasible` |
| runtime | 7.535 s |
| bounds | `max_moves=4000`, `max_seconds=240`, `candidate_mode="feasibility"` |
| objective | disabled (`objective_enabled: false`, `scope: "feasibility only"`) |

Inventory conservation, checked exactly and independently of the validator:

| check | value |
|---|---|
| units assigned / required | **6,375 / 6,375** |
| SKUs placed / required | 1,200 / 1,200 |
| unplaced SKUs | `[]` |
| unknown SKUs | `[]` |
| duplicate (SKU, bin) pairs | **0** |
| rows | 1,425 |
| `exact` | **true** |

Movement — the evidence that this is a repair and not a re-slot:

| stat | value |
|---|---|
| records relocated / total | **96 / 1,425 (6.74 %)** |
| records unchanged | 1,329 |
| total displacement | 1,471.37 m |
| mean / median / max / min | 15.33 m / 12.01 m / 36.00 m / 1.97 m |
| relocations under 10 m / 10–20 m / 20–30 m / over 30 m | 47 / 22 / 10 / 17 |

Per-record `(SKU, quantity)` is preserved row-for-row; only 96 bin cells changed. The repaired CSV
is `outputs/baseline_repaired_assignments.csv` (verified: `sku_id` and `assigned_quantity` columns
identical row-for-row to the canonical input, `location_id` differs in exactly 96 rows).

**Never written by the repair:** `dataset/processed/storage_assignments_baseline.csv` (canonical
input, sha256 `c564c077…` unchanged) and `outputs/baseline_assignments.csv` (the as-supplied
copy, sha256 `5c2a1626…` unchanged; still written only by `validate`/`run-all` from the canonical
input).

---

## 5. Three-way comparison (actual evaluation output)

Identical workload, geometry and routing for all layouts (`identical_orders_geometry_routing`).

| metric | as-supplied baseline | repaired baseline | optimized |
|---|---|---|---|
| feasibility | **INFEASIBLE** | **FEASIBLE** | **FEASIBLE** |
| violations by rule | `{"CAT-01": 1071}` | `{}` | `{}` |
| checks run | 20,699 | 18,077 | 15,167 |
| assignment feasibility | 94.08 % | 100 % | 100 % |
| units / SKUs / rows | 6,375 / 1,200 / 1,425 | 6,375 / 1,200 / 1,425 | 6,375 / 1,200 / 1,288 |
| total travel distance | 1,707,167.15 m | 1,691,478.55 m | **750,119.50 m** |
| avg travel per batch | 1,576.33 m | 1,561.85 m | 692.63 m |
| avg travel per order | 315.27 m | 312.37 m | 138.53 m |
| total pick-cycle time | 1,484,035.5 s | 1,471,967.35 s | 747,845.0 s |
| avg cycle time per order | 274.06 s | 271.83 s | 138.11 s |
| throughput | 13.14 orders/h | 13.24 orders/h | **26.07 orders/h** |
| cube utilisation | 15.42 % | 15.42 % | 15.42 % |
| golden-zone demand share | 37.72 % | 38.05 % | **61.44 %** |
| class-A SKUs outside golden | 134 | 134 | 137 |
| affinity separation | 133.32 m | 127.52 m | **55.43 m** |

Published comparison (18 rows, `comparison_valid: true`, every row `diagnostic_only: false`):

* travel −55.65 %, cycle time −49.19 %, throughput **+96.9 %**, affinity separation −56.53 %,
  cube utilisation unchanged (same inventory, same volume), golden-zone share +23.39 pp.

The as-supplied layout is **not** part of the comparison. It is published under
`diagnostic_baseline` (`diagnostic_only: true`) with its full metrics, its 1,071 violations, and
a delta against the evaluated baseline — so the cost of repairing stays visible. Its constraint
audit is exported separately as
`outputs/evaluation/constraint_audit_baseline_as_supplied.csv` (1,071 rows).

---

## 6. How much of the travel delta survives?

| question | answer |
|---|---|
| absolute travel reduction, as-supplied → optimized | 957,047.65 m (−56.061 %) |
| absolute travel reduction, repaired → optimized | **941,359.05 m (−55.653 %)** |
| share of the absolute reduction that survives | **98.36 %** |
| cost of repairing, in travel | 15,688.60 m (**0.919 %** of the baseline's travel) |
| cost of repairing, in the published percentage | **0.408 percentage points** |

**Plainly: the delta barely shrinks.** Repairing the baseline for feasibility cost 0.92 % of its
own travel, so 98.36 % of the optimized-vs-baseline travel reduction survives, and the headline
moves from −56.06 % (invalid comparison) to −55.65 % (valid comparison). Throughput, golden-zone
share and affinity separation are unchanged to within rounding; the repaired baseline is still
clearly an unoptimised layout (38.05 % golden-zone demand share vs 61.44 %, affinity 127.5 m vs
55.4 m, 134 of 294 class-A SKUs still outside the golden zone).

The claim that is now publishable:

> Against a **feasible** baseline holding the same 6,375 units in 1,425 bins, the optimized layout
> cuts pick travel by 55.65 % and pick-cycle time by 49.19 %, and raises throughput by 96.9 %,
> with 0 hard violations in either layout.

---

## 7. Where each fact lives

`outputs/optimized/optimization_summary.json`

```json
{
  "baseline_variant": "repaired_minimal",
  "baseline_source": ".../outputs/baseline_repaired_assignments.csv",
  "baseline_as_supplied_source": ".../dataset/processed/storage_assignments_baseline.csv",
  "baseline_note": "Baseline repaired for feasibility only with the objective disabled: …",
  "baseline_repair": { "attempted": true, "objective_enabled": false, "scope": "feasibility only",
                       "candidate_mode": "feasibility", "initial_violations": 1071,
                       "initial_violations_by_rule": {"CAT-01": 1071},
                       "final_violations": 0, "final_violations_by_rule": {},
                       "moves_attempted": 96, "moves_accepted": 96, "moves_rejected": 0,
                       "cycles_detected": 0, "unresolved_violations": 0,
                       "termination_reason": "feasible", "runtime_sec": 7.535,
                       "initial_severity_score": 1071000, "final_severity_score": 0,
                       "feasible": true, "conservation": {...}, "movement": {...},
                       "final_layout": {...} },
  "baseline_feasibility": true, "baseline_violations_by_rule": {},
  "baseline_feasibility_as_supplied": false,
  "baseline_violations_by_rule_as_supplied": {"CAT-01": 1071},
  "baseline_objective": 2321711.38, "baseline_objective_as_supplied": 2336184.14,
  "objective_improvement_pct": 61.132,
  "objective_improvement_pct_vs_as_supplied": 61.373
}
```

`outputs/evaluation/evaluation_summary.json`

```json
{
  "evaluation_status": "OK", "comparison_valid": true, "blocked_layouts": [],
  "baseline_variant": "repaired_minimal", "baseline_source": ".../baseline_repaired_assignments.csv",
  "baseline_repair": { … same payload … },
  "baseline_note": "Baseline repaired for feasibility only with the objective disabled: …",
  "feasibility": {"baseline": {"is_feasible": true,  "n_violations": 0},
                  "optimized": {"is_feasible": true, "n_violations": 0}},
  "diagnostic_baseline": {"baseline_variant": "as_supplied", "diagnostic_only": true,
                          "feasibility": {"is_feasible": false,
                                          "violations_by_rule": {"CAT-01": 1071}},
                          "metrics": { … }, "delta_vs_evaluated_baseline": { … }}
}
```

`baseline_note` is recorded at the **top level of both** summaries as well as inside
`baseline_repair`, so either file alone states that the baseline was repaired for feasibility only
with the objective disabled. `run_history.json` records `baseline_variant` and
`baseline_repair_termination` per run (last three entries: `repaired_minimal` / `feasible`).

Files written by this card: `outputs/baseline_repaired_assignments.csv`,
`outputs/evaluation/constraint_audit_baseline_as_supplied.csv`.

*Note:* `outputs/optimization/optimization_summary.json` is a stale artifact from a standalone
`optimize --output outputs/optimization` run on 2026-10-28. It is not written by `run-all`, not
read by the dashboard (`app/dashboard_data.py` reads `outputs/optimized/`), and it has no
`baseline_variant` key. Ignore it; `outputs/optimized/optimization_summary.json` is the one.

---

## 8. What was explicitly NOT touched

| item | evidence |
|---|---|
| separation radius | still one value, `10.0` m (`Config.from_json(configs/benchmark.json)`), threaded from config to both the placer and the validator; pinned by `tests/test_cat01_separation_radius.py` |
| capacities / structural limits | no change to any `*_max_weight_kg`, bin weight or usable volume; `locations.csv` sha256 unchanged |
| rule set | no rule id, threshold, severity or explanation changed; the as-supplied layout still reports exactly 1,071 CAT-01 at 20,699 checks, and the same 16 rule ids run on every layout |
| dataset | `dataset/processed/storage_assignments_baseline.csv` sha256 `c564c077…` and `locations.csv` sha256 `ff27b087…` unchanged |
| optimized layout | `outputs/optimized/optimized_assignments.csv` sha256 `1269e1114e77b631f06cbcdbcb9aaf2588246f8a6cbb8e6ea1d7439444cf16f0` before and after this run — and **byte-identical** to a phase-5 run invoked with `baseline_variant=None` (the pre-P2-3b call shape), see §9 |
| evaluation gate | block/publish logic unmodified; only the **input** it validates changed (the repaired baseline file is passed in explicitly and validated by the gate like any other layout) |
| configs | `configs/benchmark.json` sha256 `e786f77c…` unchanged |

The optimizer still starts from the as-supplied baseline for its own starter selection
(`run_phase5` builds it with `initial_assignments=baseline`), so the repaired baseline cannot
perturb the optimized layout. That is deliberate and commented in `src/optimization/pipeline.py`.

---

## 9. Verification performed

| check | result |
|---|---|
| `run-all` exit code | **0** (twice: before and after adding `baseline_note`) |
| full test suite | **181 passed, 0 failed, 0 skipped** (237.77 s, exit 0) = 172 pre-existing + 9 new |
| new baseline-repair suite | **9 passed** (0.89 s) |
| repaired CSV re-validated independently | 0 violations, 18,077 checks (`validate_assignment` called directly on the file) |
| as-supplied baseline re-validated independently | 1,071 CAT-01, 20,699 checks — rule set intact |
| conservation re-checked independently | 6,375/6,375 units, 1,200 SKUs, 0 duplicate pins, 0 unplaced, 0 unknown |
| **variant cannot influence the optimized layout** | phase 5 run with `baseline_variant=None` → `optimized_assignments.csv` sha256 `1269e111…`, **byte-identical** to the delivered file |
| **determinism on the real dataset** | two independent repairs → both sha256 `17380197ee66…`, identical movement stats, 96/96 moves |
| optimized layout re-validated | 0 violations, 15,167 checks, 1,288 rows, 6,375 units |
| canonical dataset + as-supplied copy | sha256 identical before and after the run |
| artifact isolation | `tests/test_artifact_isolation.py` fingerprints `outputs/` around a full pipeline run and asserts it is unchanged |

New tests (`tests/test_baseline_repair.py`, 9 cases): feasibility + conservation + input
immutability; minimal movement (untouched records keep their bin, displacement bounded); proof
that the objective is never evaluated; determinism; an already-feasible baseline is left alone;
caller-disabled repair; conservation failure modes; a bounded failure keeps the gate blocking; and
the end-to-end "repaired baseline publishes a valid comparison with the as-supplied metrics kept
as a diagnostic (and the note recorded at the top level)" case.

---

## 10. Honest limitations

* **It is a repair, not a proof of minimality.** The loop relocates one record at a time in
  deterministic order and picks the nearest bin the placer predicts is legal. 96 records / 1,471 m
  is a small, measured repair, not a globally optimal (minimum-movement) solution.
* **It still moves stock, sometimes a long way.** 47 of the 96 relocations were under 10 m, but 17
  exceeded 30 m (max 36.00 m). Those are the records whose whole neighbourhood was occupied by a
  conflicting category, so the nearest legal bin was far away. None of it is objective-driven.
* **The check count is not a coverage metric, and it is not identical across layouts.** CAT-01
  works on a spatial grid of cell size R and only enumerates bin pairs that are close enough to
  violate, so its row count follows the layout: **3,594 pairs examined for the as-supplied layout,
  1,039 for the repaired one, 0 for the optimized one**. Zero pairs examined is a *sound* vacuous
  pass (any pair closer than R would fall in adjacent cells and be enumerated), but it is weaker
  evidence than 1,039 passing checks. `SL-01` (550 → 527), `SL-02` (960 → 922) and `RK-01`
  (144 → 138) shrink for the same reason: fewer bins sit in over-full scopes. All 16 rule ids run
  on all three layouts.
* **`diagnostic_baseline` is a diagnostic.** Its as-supplied metrics are comparable in basis
  (same orders, geometry, routing) but they describe an illegal layout and must never be quoted
  as the baseline of an improvement claim.
* **The repaired baseline is only adopted when it is genuinely feasible.** If a future dataset
  makes the repair fall short, `run-all` goes back to exit 1 with a block and the repair stats
  explaining why — by design.
