# Phase 2 — Constraint engine, CAT-aware optimization, and feasibility enforcement

**Date:** 2026-10-29
**Repo:** `/home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting`
**Dataset:** `/home/hemanth/hackathon/epoch_hackathon/dataset/processed` (canonical, unmodified)
**Predecessor:** `docs/PHASE_1_BASELINE_VERIFICATION.md` (environment, 84/6 test baseline, 1,071 CAT-01 violations)
**Verdict:** **COMPLETE.** The canonical benchmark now produces a **feasible optimized layout** (0 violations, 6,375/6,375 units), the **baseline is repaired to feasibility without touching the objective**, and the evaluation gate publishes a **valid comparison: −55.65% travel**.

---

## 1. Objective and scope

Phase 2 owns constraint enforcement, optimization feasibility, result-status separation and the evaluation
feasibility gate. It does **not** own the demand-weighted travel rewrite (T per line), replenishment, the
fit/holdout split, the 2×2 pick-rule experiment or the weight sweep — those are Phase 3/4.

Success was defined as: *zero violations across every applicable hard constraint, verified independently, or
an honest `INFEASIBLE` with evidence* — never "the optimizer ran".

## 2. Defects established by Phase 1 (restated, then fixed)

| # | Defect | Phase 2 outcome |
|---|---|---|
| 1 | Baseline violates `CAT-01` **1,071 times** at the intended 10 m radius | Confirmed; baseline now repaired to 0 violations (objective untouched) |
| 2 | Optimizer's output carried **4 `SL-02` beam violations** — greedy tracked bin/level/rack but not beam | Fixed: beam ledger keyed `(rack, bay, shelf_level)`; result is 0 violations |
| 3 | Greedy was blind to `CAT-01` | Fixed: 3-D occupancy grid consulted before every placement |
| 4 | `separation_radius_m` existed only as a constructor default | Fixed: `configs/benchmark.json` + `Config`, threaded to optimizer and validator |
| 5 | Greedy/repair could emit an infeasible result as "the answer" | Fixed: bounded, full-validator-screened repair + explicit `INFEASIBLE` path |
| 6 | `run-all` published metrics for infeasible layouts with exit 0 | Fixed: gate blocks, `run-all` exits 1 |
| 7 | Six tests encoded "the baseline is feasible" | Rewritten to assert the *reporting contract*; suite is green and stronger |
| 8 | Tests read mutable `outputs/` files | Rewritten to build fixtures in `tmp_path` |

## 3. Files and functions changed

| File | Change | Card |
|---|---|---|
| `configs/benchmark.json` | `separation_radius_m: 10.0` added | P2-1 |
| `src/models/config.py` | `separation_radius_m` field, numeric ≥ 0 validation, rejects negatives | P2-1 |
| `src/optimization/separation.py` *(new)* | 3-D occupancy grid, `R`-sized cells, forbidden-pair lookup, dedupe of unordered pairs | P2-1 |
| `src/optimization/optimizer.py` | beam ledger + beam residual in `_split_quantity`; CAT-01 rejection before placement; diagnostics for unplaceable SKUs | P2-1 |
| `src/validation/validator.py` | radius threading only — rule semantics unchanged (rule ids identical: `SP VD LD SL RK HZ HD ER AS CP CAT REF QTY COMP INV DU`) | P2-1 |
| `src/optimization/baseline.py` *(new)* | `BaselineVariant`, `prepare_baseline_variant()`, feasibility-only repair with the objective disabled | P2-3b |
| `src/optimization/pipeline.py` | status separation (`execution_status` / `feasibility_status` / `assignment_completeness` / `objective`), repair stats, `baseline_variant` | P2-2, P2-3b |
| `src/simulation/pipeline.py` | evaluation gate: `evaluation_status`, `comparison_valid`, `diagnostic_only`, `blocked_layouts` | P2-2 |
| `app/main.py` | non-zero exit when the gate blocks; baseline-variant wiring | P2-2, P2-3b |
| `app/dashboard.py`, `app/dashboard_data.py` | render blocked evaluations as blocked, not as results | P2-2 |
| `tests/*` | 6 legacy tests rewritten; 8 new test modules | P2-3, P2-3b |

## 4. Final constraint semantics

**`CAT-01` — category separation.**
- Metric: **3-D Euclidean distance between bin coordinates** (`x, y, z`), not aisle path length. A rack's two
  sides are ~1 m apart physically and tens of metres apart by walking route; a walking radius would permit
  the adjacency the rule exists to prevent.
- Pairs: `compatibility_rules` where `allowed == False` and `category_a != category_b` — **13 forbidden pairs**
  in the canonical dataset.
- Boundary: **inclusive** — a pair at exactly `R` passes (`d + 1e-9 >= R`).
- Counting: the grid evaluates only **forbidden-category pairs whose bins fall inside the same R-sized cell window**, one check per unordered pair — 3,594 checks for 1,425 occupied bins. A bin is never compared with itself. The check is not a full n² sweep, and the count is not `n(n−1)/2`.
- Radius: **10.0 m**, from configuration (not a default).

**Structural scopes — four, each against its own field.**
| Rule | Aggregate key | Limit field |
|---|---|---|
| `LD-01` | one bin | `max_weight_kg` |
| `SL-02` | `(rack_id, bay, shelf_level)` | `beam_max_weight_kg` |
| `SL-01` | `(rack_id, shelf_level)` | `level_max_weight_kg` |
| `RK-01` | `rack_id` | `rack_max_weight_kg` |

The limits are proportional by construction (uniform structure), but the **loads are not**: the canonical run
reaches 55.6 % of the tightest beam limit and only 34.7 % of the level limit, which is exactly why the beam
check exists separately.

## 5. How beam capacity is accounted for

- The greedy builds `beam_cap[(rack,bay,level)]` from `beam_max_weight_kg` and tracks `beam_load[...]` beside
  the bin, level and rack ledgers.
- `_split_quantity` receives residual **bin, beam, level and rack** capacity and returns the minimum, so a
  placement can never exceed any scope.
- Precedence matches the validator: bin → beam → level → rack. **Tolerances are per rule and per code path; the
  placer is not uniformly stricter.** Readings below are taken from the code, not recalled:

| Rule | Validator | Placer — greedy path | Placer — move filter | Who is stricter |
|---|---|---|---|---|
| `LD-01` weight | none — `total <= max_weight_kg` (l. 406) | `_units_affordable(bin_weight, unit_weight)` → 1e-9 (`WEIGHT_EPSILON_KG`, l. 1267, called l. 1306) | `> max_weight_kg + WEIGHT_EPSILON_KG` → 1e-9 (l. 832) | validator, by 1e-9 kg |
| `VD-01` volume | none — `total <= usable_volume_cm3` (l. 428) | `_units_affordable(volume, unit_volume_cm3)` → 1e-9 (l. 1267, called l. 1306) | `> usable_volume_cm3 + 1e-6` (l. 834) | validator, by 1e-9 cm³ (greedy) / 1e-6 cm³ (move filter) |
| `SL-01` / `SL-02` / `RK-01` | `<= limit + 1e-6` (l. 602, 615, 628) | ledger audit at 1e-9 (`WEIGHT_EPSILON_KG`, l. 594, 598, 602) | `> cap + 1e-6` (l. 841, 843, 845) | equal in the move filter, stricter in the ledger audit |
| `CAT-01` | rejects when `d + 1e-9 < R` | `d + 1e-9 < radius` (l. 684) | same | identical |

  Three consequences worth stating rather than hiding. First, **the placer is more permissive than the validator
  only on `LD-01` (by 1e-9 kg) and `VD-01` (by 1e-9 cm³ on the greedy path, 1e-6 cm³ in the move filter)**; every
  structural-load comparison is equal or stricter, so a placement cannot pass the placer and fail `SL`/`RK`
  validation. Second, **the placer is internally inconsistent**: the same beam/level/rack scope is guarded at
  1e-6 in the move filter and audited at 1e-9 in the greedy ledger, and `VD-01` likewise varies by path. Harmless
  today (both inside the validator's tolerance), but "the placer's tolerance" is not a single number, and a future
  change to one path could silently diverge from the other. Third, **`_units_affordable` applies
  `WEIGHT_EPSILON_KG` to a volume residual in cm³** — a unit-name mismatch that is numerically negligible
  (1e-9 cm³) but semantically wrong, and exactly the kind of thing a units review should catch.
  An adversarial probe across 1,027 unit weights × 400 residual levels plus exact-boundary cases found no
  reachable overdraft.
- Verified empirically: the optimized layout has **0 `SL-02` violations** over **662 beam groups** (the repaired baseline evaluates 922, the as-supplied baseline 960 — quoting 960 for the optimized layout would attribute another layout's count to it). Phase 1 had 4 such violations.

## 6. How feasibility is computed

The final layout is re-validated by `Validator.validate()` in a fresh call, using the configured radius, after
the optimizer returns. The optimizer's own flags are never the source of truth for `feasibility_status`; the
summary records the validator's `checks_run`, `n_violations` and `violations_by_rule`.

## 7. Status separation

`optimization_summary.json` now carries four independent concepts:

```json
"execution_status": "OK",
"feasibility_status": "FEASIBLE",
"assignment_completeness": {"units_required": 6375, "units_placed": 6375, "units_unplaced": 0,
                            "complete": true, "completeness_pct": 100.0, "unresolved_skus": []},
"objective": {"value": 902392.906, "baseline_value": 2321711.382, "per_rule_violations": {},
              "violation_severity_score": 0, "globally_optimal": false}
```

Process exit `0` no longer implies feasibility; `execution_status` describes completion only.

## 8. Evaluation gate

`run_phase6` independently validates **both** layouts before publishing anything:

| Field | Meaning |
|---|---|
| `evaluation_status` | `OK` or `BLOCKED_INFEASIBLE_LAYOUT` |
| `comparison_valid` | true only when both layouts pass validation |
| `diagnostic_only` | true when metrics are shown for debugging but are **not** a valid comparison |
| `blocked_layouts` | which layouts failed, e.g. `["baseline"]` |
| `baseline_variant` | `as_supplied` or `repaired_minimal` |

Blocked behaviour, captured live before the baseline repair:

```
run-all exit code ..... 1
evaluation_status ..... BLOCKED_INFEASIBLE_LAYOUT
comparison_valid ...... false
blocked_layouts ....... ["baseline"]
message ............... "BLOCKED by the feasibility gate: ... The diagnostic metrics are not valid
                        evidence; fix the layouts and re-run."
```

## 9. Configuration and effective radius

- Authoritative location: `configs/benchmark.json` → `"separation_radius_m": 10.0`
- Validated by `Config.from_json` (numeric, ≥ 0, negative rejected)
- Single source: the optimizer and the validator both receive it from `Config`; no module hard-codes it
- Recorded in `optimization_summary.json` and `evaluation_summary.json` as `separation_radius_m`

## 10. Test results (actual)

```
.venv/bin/python -m pytest tests/ -q --tb=no -p no:cacheprovider
→ 181 passed in 248.22 s   (0 failed, 0 skipped, 181 collected; repeat run after the radius fix: 219.96 s)
```

- Phase 1 baseline was **84 passed / 6 failed / 90 collected**; the suite is now **181 collected, all passing** (+91 tests).
- New fixture-based modules and their counts: `test_phase2_greedy_constraints.py` 21,
  `test_structural_scopes.py` 10, `test_inventory_integrity.py` 7, `test_determinism.py` 4 (**54** in those
  four), plus `test_cat01_separation_radius.py`, `test_feasibility_gate.py`, `test_artifact_isolation.py` and
  `test_baseline_repair.py`.
- **No test was skipped, xfailed or deleted.** The only `skipif` in the tree predates Phase 2 (phase-9 dashboard).
- Legacy tests were *strengthened*, not loosened:
  - `test_baseline_feasibility_is_reported_correctly_on_benchmark` recomputes `CAT-01` pair-by-pair
    independently and asserts the validator matches that count;
  - `test_optimized_feasible_and_better` pins the gate invariant in both directions
    (`comparison_valid is both_feasible`);
  - `test_constraint_audit_is_not_header_only` builds tiny datasets in `tmp_path` and checks a clean **and** a
    failing audit.

## 11. Canonical benchmark results

Radius 10.0 m, scenario A, config `configs/benchmark.json`, dataset unmodified.

| Layout | Rows | SKUs | Units | Checks | Violations by rule | Feasible |
|---|---|---|---|---|---|---|
| Baseline, as supplied | 1,425 | 1,200 | 6,375 | 20,699 | `CAT-01`: **1,071** | **No** |
| Baseline, repaired (objective disabled) | 1,425 | 1,200 | 6,375 | 18,077 | **none** | **Yes** |
| **Optimized** | **1,288** | **1,200** | **6,375** | 15,167 | **none** | **Yes** |

| Performance (identical workload, 5,415 orders, 1,083 batches) | Value |
|---|---|
| Baseline travel (as supplied → repaired) | 1,707,167 m → 1,691,479 m (−0.92 %) |
| Optimized travel | **750,120 m** |
| **Optimized vs repaired baseline** | **−55.65 %** |
| Cycle time (repaired baseline → optimized) | 1,471,967 s → 747,845 s (**−49.19 %**) |
| Throughput (repaired baseline → optimized) | 13.24 → 26.07 orders/h (**+96.90 %**) |
| Optimizer objective (un-normalised v1 form, repaired baseline → optimized) | 2,321,711 → 902,393 (**−61.13 %**) |
| Optimizer runtime | 32.5 s for 600 moves (16 accepted); `globally_optimal: false` |

### 11.1 Independent verification (P2-4, separate process)

A verifier re-derived every number from `dataset/processed` in its own process, reading the radius from
`configs/benchmark.json` and refusing to trust any pipeline summary. Result: **`VERIFIED FEASIBLE`** —
`docs/PHASE_2_EVIDENCE.json`.

| Cross-check | Pipeline claim | Independent value | Match |
|---|---|---|---|
| `separation_radius_m` | 10.0 | 10.0 (asserted from config) | ✅ |
| optimized `feasibility_status` | FEASIBLE | FEASIBLE | ✅ |
| optimized violations by rule | `{}` | `{}` (15,167 checks) | ✅ |
| repaired-baseline violations | `{}` | `{}` (18,077 checks) | ✅ |
| as-supplied baseline | INFEASIBLE | 1,071 `CAT-01` (20,699 checks) | ✅ |
| gate on the canonical run | exit 0, `OK` | exit 0, `comparison_valid: true`, 18 comparison rows | ✅ |

Integrity, re-checked per SKU: units assigned == on hand for all three layouts; `skus_short: []`,
`skus_over: []`; `duplicate_sku_bin_rows: 0`; no SKU in a nonexistent bin; `multi_sku_bins: 0`.

Two facts the verifier added that the pipeline summary does not report:

- **The as-supplied baseline fails only at 10 m**: violations involve pairs as close as **3.2 m**; 169 pairs
  are under 5 m and none under 2 m; **71 of 1,200 SKUs** are implicated.
- **Repair packs some beams harder**: max beam utilisation rises from **55.6 %** (as supplied) to **72.5 %**
  (repaired) — still legal, but the feasible baseline sits closer to the `SL-02` limit than the infeasible one
  did. Any further repair would need to watch that scope.

**Repair footprint — the reason the comparison is fair:** 93 of 1,200 SKUs (7.8 %) changed bins; **96 records
moved**; **zero quantity changes**. The repair moved stock only far enough to satisfy `CAT-01`, which is why
the baseline's travel barely changed (0.92 %) and the improvement survives intact.

### 11.2 Structural headroom of the delivered layout

The optimized layout is feasible, but only just. The verifier recorded its worst structural scopes:

| Scope | Observed | Limit | Utilisation |
|---|---|---|---|
| Beam — rack `R5-3-1`, bay 0, shelf 3 | 214.64 kg | 216.00 kg | **99.37 %** |
| Level — rack `R5-3-1`, shelf 1 | 458.76 kg | 460.80 kg | **99.56 %** |
| One bin | at its `LD-01` limit | — | **100.00 %** |

So "0 violations" is true but **not robust**: a 0.6 % increase in stock on one beam, or any change to the
inventory snapshot, would flip the layout infeasible. This is a property of the greedy filling the best-located
bins to the brim, and it should be read as a *risk*, not as slack. A production version would need either a
headroom constraint (e.g. refuse placements above 95 % of any structural limit) or a repair pass that
redistributes load away from the binding beam.

## 12. Inventory reconciliation and completeness

| Check | Result |
|---|---|
| Units assigned vs on hand (baseline, repaired, optimized) | 6,375 = 6,375 = 6,375 |
| Per-SKU quantity changes during repair | **0** |
| Duplicate `(sku, bin)` rows | 0 |
| Unplaced SKUs | 0 (`unresolved_skus: []`) |
| `assignment_completeness` | 100.0 % |

## 13. Remaining violations

None. Both published layouts have **zero** violations across all 16 rule families at 10 m.

## 14. Known limitations

1. **Repair is not exercised by the canonical optimized run.** The greedy already reaches feasibility, so the
   canonical pass records `initial_violations: 0, moves_attempted: 0`. Repair is proven by unit tests and by
   the baseline repair (93 SKUs moved), but not by a hard canonical case.
2. **The as-supplied baseline is infeasible and remains so on disk.** It is preserved
   (`dataset/processed/storage_assignments_baseline.csv` untouched); the comparison uses
   `outputs/baseline_repaired_assignments.csv`, labelled `baseline_variant: repaired_minimal`. Any external
   reproduction must use that variant or expect the gate to block.
3. **`CAT-01` grid never rejected a candidate on the canonical run** (1,293 queries, 0 rejections). The rule is
   satisfied, but on this dataset velocity ordering plus hazard zoning get there without the grid needing to
   say no. The rejection path is covered only by tests.
4. **Baseline travel is 4.46× the committed historical figure** (1,707,167 m vs 382,544 m) with an identical
   layout and workload — the committed artifacts came from a different dataset build (Phase 1, §E.3). No
   historical percentage is comparable to these numbers.
5. **The objective is still the v1 un-normalised form**; per-term contributions and normalisation are Phase 3.
6. **The delivered layout has almost no structural headroom** — 99.37 % of one beam, 99.56 % of one level, one bin exactly at its `LD-01` limit (see §11.2). Feasible, but brittle to any inventory change.
7. **The placer uses two tolerances for the same structural scopes** — 1e-6 in the move filter, 1e-9 in the greedy ledger audit (see §5). Both sit inside the validator's 1e-6, so no reachable divergence exists today, but the duplication is a latent inconsistency rather than a designed one.
8. **Deliverables are not reproduced by an outside party yet**: these are local runs on this machine.

## 15. Reproduce

```bash
cd /home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting
.venv/bin/python -m pytest tests/ -q --tb=no -p no:cacheprovider      # 181 passed

# full pipeline with the repaired baseline (valid comparison)
.venv/bin/python app/main.py run-all --processed ../dataset/processed --scenario A
echo $?                                                              # 0; evaluation_status OK

# what "blocked" looks like: point the gate at the as-supplied baseline
# (the baseline variant is recorded in outputs/*_summary.json)

# independent re-validation, radius read from config
.venv/bin/python - <<'PY'
import json, pandas as pd
from pathlib import Path
from src.validation.loader import *
from src.validation.validator import Validator
proc = Path("../dataset/processed")
wh = load_warehouse_from_locations(pd.read_csv(proc/"locations.csv"))
skus = load_skus(pd.read_csv(proc/"products.csv"))
rules = load_compatibility_rules(pd.read_csv(proc/"compatibility_rules.csv"))
inv = load_inventory(pd.read_csv(proc/"inventory.csv"))
R = json.loads(Path("configs/benchmark.json").read_text())["separation_radius_m"]
for name in ("storage_assignments_baseline", "../outputs/baseline_repaired_assignments", "../outputs/optimized/optimized_assignments"):
    p = proc/f"{name}.csv" if not name.startswith("..") else Path(f"{name}.csv")
    df = pd.read_csv(p)
    res = Validator(skus, wh, rules, inventory=inv, separation_radius_m=R).validate(load_assignments(df))
    print(name, len(df), res.is_feasible, len(res.violations))
PY
```
