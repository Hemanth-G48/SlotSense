# Phase 2 Report — Constraint engine, CAT-aware optimization, and feasibility enforcement

**Date:** 2026-10-29
**Repo:** `/home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting`
**Dataset:** `/home/hemanth/hackathon/epoch_hackathon/dataset/processed` (canonical, unmodified)
**Detailed evidence:** `docs/PHASE_2_CONSTRAINT_ENGINE.md` · `docs/PHASE_2_EVIDENCE.json` · `docs/PHASE_1_BASELINE_VERIFICATION.md`

---

## Status

**COMPLETE.**

Every engineering criterion in the Phase 2 definition of done is met and independently verified: `CAT-01`
gates during allocation at the configured 10 m, beam capacity is tracked and the four `SL-02` violations are
gone, the final layout is validated by a separate engine, the evaluation gate refuses to publish infeasible
comparisons, inventory is preserved exactly, and the canonical benchmark yields a **feasible pair with a
−55.65 % travel improvement** reproduced by an independent verifier process.

One procedural caveat, stated plainly rather than buried: the fourth and final reviewer pass ended in
`REQUEST CHANGES` on a **documentation citation** (VD-01's greedy-path tolerance and an off-by-one line
reference). That is fixed, and the class of defect it belongs to is now covered by
`tools/check_phase2_doc.py`, which asserts 35 claims against code and artifacts and exits 0. **No explicit
reviewer `APPROVE` exists for §5 of the design document.**

---

## Files changed

| File | Why |
|---|---|
| `configs/benchmark.json` | `separation_radius_m: 10.0` — the radius is now configured, not defaulted |
| `src/models/config.py` | `separation_radius_m` field, numeric, ≥ 0, negative rejected |
| `src/optimization/separation.py` *(new, 5.2 KB)* | 3-D occupancy grid for `CAT-01`; cell size = radius; forbidden-pair set from `compatibility_rules` |
| `src/optimization/optimizer.py` | beam ledger keyed `(rack_id,bay,shelf_level)`; beam residual in `_split_quantity`; `CAT-01` rejection before placement; diagnostics for unplaceable SKUs |
| `src/optimization/baseline.py` *(new)* | `BaselineVariant` + feasibility-only repair of the baseline with the objective disabled |
| `src/optimization/pipeline.py` | status separation (`execution_status` / `feasibility_status` / `assignment_completeness` / `objective`), repair stats, `baseline_variant` |
| `src/validation/validator.py` | radius threading only — **rule semantics unchanged** (all 16 rule families, same IDs) |
| `src/simulation/pipeline.py` | evaluation gate: `evaluation_status`, `comparison_valid`, `diagnostic_only`, `blocked_layouts` |
| `app/main.py` | non-zero exit when the gate blocks; baseline-variant wiring |
| `app/dashboard.py`, `app/dashboard_data.py` | render blocked evaluations as blocked, not as results |
| `tests/` — 8 new modules, 4 legacy files rewritten | 181 tests, all passing; no test skipped, xfailed or deleted |
| `tools/check_phase2_doc.py` *(new)* | machine-checks the Phase 2 report's factual claims |

---

## Constraint implementation

**`CAT-01`** — forbidden category pairs must be ≥ 10 m apart in **3-D Euclidean distance** between bin
coordinates. 13 forbidden pairs from `compatibility_rules` (`allowed == False`, distinct categories). Boundary
is inclusive (`d + 1e-9 >= R`). The greedy consults a grid indexed by R-sized cells before accepting any bin, so
the check is a neighbour lookup, not an n² sweep; the validator applies the same rule independently.

**Beam capacity** — the greedy maintains `beam_cap` / `beam_load` keyed `(rack_id, bay, shelf_level)` and passes
the beam residual into `_split_quantity` alongside bin, level and rack. Precedence matches the validator's
aggregation. Result: **0 `SL-02` violations over 662 beam groups**, down from 4.

**Other structural scopes** — `LD-01` (bin weight), `VD-01` (bin volume), `SL-01` (level), `RK-01` (rack) are
all enforced; the delivered layout is at 99.37 % of one beam and 99.56 % of one level (see *Canonical benchmark
results* — "feasible" here means "legal", not "roomy").

**Tolerances are not uniform** and this is now documented per rule *and per code path*: the placer is more
permissive than the validator only on `LD-01` (1e-9 kg) and `VD-01` (1e-9 cm³ greedy / 1e-6 cm³ move filter);
every load comparison is equal or stricter. The placer is also internally inconsistent (1e-6 in the move
filter vs 1e-9 in the ledger audit for the same load scopes) — harmless today, recorded as a latent risk.

**Repair** — bounded, deterministic, cycle-guarded, accepts only strict improvements in the full validator's
verdict, re-validates with the complete rule set, and reports moves attempted/accepted/rejected/unresolved plus
a termination reason. It cannot trade one violation for another.

---

## Feasibility and evaluation

Feasibility is never read from the optimizer. The final layout is re-validated in a fresh `Validator.validate()`
call using the configured radius, and `feasibility_status` is derived from that result.

`optimization_summary.json` separates four concepts that used to be one boolean:

```json
"execution_status": "OK",
"feasibility_status": "FEASIBLE",
"assignment_completeness": {"units_required": 6375, "units_placed": 6375, "unplaced": 0, "complete": true},
"objective": {"value": 902392.906, "baseline_value": 2321711.382, "per_rule_violations": {},
              "globally_optimal": false}
```

The **gate** validates both layouts before publishing anything:

| Situation | Result |
|---|---|
| Either layout infeasible | `evaluation_status: BLOCKED_INFEASIBLE_LAYOUT`, `comparison_valid: false`, every metric `diagnostic_only`, `run-all` exits **1** |
| Both feasible | `evaluation_status: OK`, `comparison_valid: true`, 18 comparison rows, `run-all` exits **0** |

Measured live in both directions by the reviewer: an infeasible baseline and an infeasible optimized layout each
produced exit 1, zero comparison rows, and all diagnostic rows flagged.

---

## Test results

```
.venv/bin/python -m pytest tests/ -q --tb=no -p no:cacheprovider
→ 181 passed in 219.96 s   (0 failed, 0 skipped, 181 collected)
```

- Phase 1 baseline: **84 passed / 6 failed / 90 collected** → now **181 collected, all passing** (+91 tests).
- New modules: `test_phase2_greedy_constraints.py` (21), `test_structural_scopes.py` (10),
  `test_inventory_integrity.py` (7), `test_determinism.py` (4), plus `test_cat01_separation_radius.py`,
  `test_feasibility_gate.py`, `test_artifact_isolation.py`, `test_baseline_repair.py`.
- **No test deleted, skipped, xfailed or weakened.** The only `skipif` predates Phase 2.
- The six Phase 1 failures were replaced with *stronger* contracts: an independent pair-by-pair `CAT-01`
  recount, gate invariants asserted in both directions, and `tmp_path` fixtures instead of reading `outputs/`.

---

## Canonical benchmark results

Radius **10.0 m** from `configs/benchmark.json`; scenario A; dataset unmodified.

| Layout | Rows | SKUs | Units | Checks | Violations | Feasible |
|---|---|---|---|---|---|---|
| Baseline, as supplied | 1,425 | 1,200 | 6,375 | 20,699 | **1,071 `CAT-01`** | No |
| Baseline, repaired (objective disabled) | 1,425 | 1,200 | 6,375 | 18,077 | none | **Yes** |
| **Optimized** | **1,288** | **1,200** | **6,375** | 15,167 | none | **Yes** |

| Performance (identical workload: 5,415 orders, 1,083 batches, 20,000 lines) | Baseline (repaired) | Optimized | Change |
|---|---|---|---|
| Travel distance | 1,691,479 m | 750,120 m | **−55.65 %** |
| Pick-cycle time | 1,471,967 s | 747,845 s | **−49.19 %** |
| Throughput | 13.24 orders/h | 26.07 orders/h | **+96.90 %** |
| Objective (v1 un-normalised) | 2,321,711 | 902,393 | **−61.13 %** |

**Integrity:** units 6,375 = on-hand 6,375 for all three layouts; **zero quantity changes** during baseline
repair; 0 duplicate `(sku,bin)` rows; 0 unplaced SKUs; 0 multi-SKU bins; completeness 100 %.

**Repair footprint:** 93 of 1,200 SKUs (7.8 %) changed bins, 96 records moved. The baseline's own travel moved
only 0.92 %, which is why the improvement survives intact rather than being an artefact of a broken reference.

**Structural headroom — the uncomfortable part:** the optimized layout sits at **99.37 %** of one beam
(214.64 / 216.00 kg) and **99.56 %** of one level (458.76 / 460.80 kg), with **one bin exactly at its `LD-01`
limit**. "0 violations" is true but brittle: a small inventory change flips it infeasible.

**Independent verification:** a separate verifier process re-derived every figure from the dataset and returned
`VERIFIED FEASIBLE`, matching the pipeline's claims on 6/6 cross-checks, including the radius read from config.

---

## Reproducibility

```bash
cd /home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting
uv venv .venv --python 3.14 && uv pip install --python .venv/bin/python -r requirements.txt pytest

.venv/bin/python -m pytest tests/ -q --tb=no -p no:cacheprovider     # 181 passed
.venv/bin/python app/main.py run-all --processed ../dataset/processed --scenario A
echo $?                                                              # 0 — evaluation_status OK
.venv/bin/python tools/check_phase2_doc.py                           # 35 claims verified
```

Four review rounds were run against this work. **All findings were documentary — zero implementation defects.**
The four recurring failure modes (mixed metric bases, a count borrowed from another layout, an objective quoted
from the wrong field, tolerances guessed instead of read) are now machine-checked rather than reviewed by eye.

---

## Remaining blockers

1. **Repair is not exercised by the canonical optimized run** — the greedy reaches feasibility unaided, so
   `moves_attempted: 0`. Repair is proven by unit tests and by the baseline repair (96 moves), not by a hard
   canonical case.
2. **`CAT-01` never rejects on this dataset** — 1,293 queries, 0 rejections. Velocity ordering plus hazard zoning
   separate the forbidden pairs unaided; the rejection path is covered only by tests.
3. **Structural headroom ≈ 0.6 %** — feasible but brittle (see above).
4. **As-supplied baseline remains infeasible on disk** and is deliberately preserved; the comparison uses
   `outputs/baseline_repaired_assignments.csv` marked `baseline_variant: repaired_minimal`. A reproduction that
   skips that variant will be blocked by the gate — by design.
5. **Historical artifacts are not comparable**: local baseline travel is 1,707,167 m vs the committed
   artifact's 382,544 m (4.46×) with an identical layout and workload — a different dataset build (Phase 1
   finding E.3). No historical percentage may be quoted alongside these numbers.
6. **Placer tolerance duplication** (1e-6 vs 1e-9 for the same load scopes) — latent, no reachable divergence.
7. **Not version-controlled** — the working copy is not a Git repository; changes are tracked only by file
   timestamps and review artifacts.

---

## Phase 3 readiness

**Ready to start, with one sequencing note.**

The constraint foundation Phase 3 builds on is now solid and independently verified: one validator, four verdicts,
a feasible optimized layout, a repaired feasible baseline, and a gate that will refuse to publish anything
infeasible. Phase 3's headline work — `T` per order line and publishing `demand_weighted_depot_distance`, the
2×2 fragmentation/placement decomposition, and the fit/holdout split — can proceed on top of this without
revisiting the constraint engine.

The sequencing note: **Phase 3's improvement percentages must be computed against the repaired baseline**, and
the 99.37 % / 99.56 % headroom means any change that touches inventory or bin capacities can flip feasibility.
Phase 3 should either adopt a headroom constraint (e.g. ≤ 95 % of any structural limit) or re-run the repair
after any inventory change, before quoting a new delta.

Not started in Phase 2 and still outstanding from the architecture backlog: `T` per line (D29), publishing `T`
(D35), the 2×2 (D22), the split (D46), replenishment (D47), the provenance manifest (D48), dashboard filters
(D28/D44), the weight sweep (D36) and EDA findings.
