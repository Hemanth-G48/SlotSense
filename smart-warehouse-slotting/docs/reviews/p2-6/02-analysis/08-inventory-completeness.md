# Item 8 — Inventory conservation and completeness

**Verdict: PASS**

## What the checklist asked

Units before == units after; no SKU silently dropped; unresolved SKUs reported.

## Units

| Layout | Rows | SKUs | Units |
|---|---|---|---|
| Baseline, as supplied | 1,425 | 1,200 | 6,375 |
| Baseline, repaired | 1,425 | 1,200 | 6,375 |
| Optimized | 1,288 | 1,200 | 6,375 |

No layout loses a SKU, and no layout changes the unit total. Dossier `03-dossiers/d05-artifact-numbers.txt`
and `03-dossiers/d02-gate-runall-pass.txt`.

## What the pipeline reports

`optimization_summary.json`:

```json
"assignment_completeness": {"units_required": 6375, "units_placed": 6375, "units_unplaced": 0,
                            "complete": true, "completeness_pct": 100.0, "unresolved_skus": []}
```

`_assignment_completeness` (`src/optimization/pipeline.py:258-278`) computes `units_required` from the
inventory, `units_placed` from the returned assignments, and lists every SKU whose placed quantity differs
from its on-hand in either direction — so over-storage is reported as well as under-storage.

## The rule that catches a dropped SKU even if the layout looks clean

`Validator._check_completeness` (`src/validation/validator.py:660-677`) takes the expected set from the
inventory keys when an inventory is supplied (`:662`), not from the assignments. A SKU that vanished from the
layout is therefore a `COMP-01` violation, not an absence. The canonical run reports 0.

## "No SKU silently dropped" is enforced at the source

The starter never truncates:

* `UnplacedSku` (`optimizer.py:148-165`) records `sku_id`, `units_required`, `units_unplaced`,
  `binding_reason` and a human-readable `detail`.
* The starter appends one for every SKU it cannot finish and logs a warning (`optimizer.py:515-527`).
* `_unplaced_reason` (`optimizer.py:401-435`) ranks the blockers by how many candidate bins each removed and
  names the binding constraint — `fit`, `hazard`, `handling`, `capacity` or `separation` — instead of saying
  "could not place".
* `_eligibility_stage` (`optimizer.py:366-399`) separates "no bin is big enough" from "no bin accepts this
  hazard class" from "no bin accepts this handling type", which are three different remedies.
* The summary surfaces both the per-SKU list and the total: `unplaced_skus` and `units_unplaced`.

## Tests that pin it

| Test | What it pins |
|---|---|
| `tests/test_inventory_integrity.py:115-124` | A SKU that fits no bin at all (200 cm cube, 2 units on hand) is **reported**, with `units_unplaced == 2`, and the rest of the layout is still complete |
| `tests/test_inventory_integrity.py:60-61, 75` | `assignment_completeness.complete is True` and `unresolved_skus == []` on a clean run |
| `tests/test_phase2_greedy_constraints.py:399-411` | Capacity is named as the binding reason when stock exceeds the warehouse; the unplaced remainder is exact |
| `tests/test_phase2_greedy_constraints.py:414-438` | `fit` and `hazard` are named for the two static walls |
| `tests/test_phase2_greedy_constraints.py:440-465` | **Every** SKU is either placed or reported — no third outcome |
| `tests/test_phase5_optimizer.py:57-65` | Per-SKU sums equal on-hand exactly, and at least one SKU legitimately spans several bins (multi-bin is not mistaken for duplication) |
| `tests/test_baseline_repair.py:84, 209` | Repair conserves units and leaves `unplaced_skus == []`; a deliberately unplaceable SKU appears as `["SKU_A"]` |

The canonical evidence file corroborates independently: `skus_short: []`, `skus_over: []`,
`duplicate_sku_bin_rows: 0`, `multi_sku_bins: 0` (`docs/PHASE_2_EVIDENCE.json`).

## Note

The greedy processes only SKUs with `inventory > 0` (`optimizer.py:465-468`), so a SKU with zero on-hand is
neither placed nor required — which is the correct reading of "no SKU silently dropped": the requirement is
the inventory, and the canonical inventory has 1,200 SKUs, all of which appear in all three layouts.

SOURCES (LAYER 3 NAVIGATION)
/home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting/docs/reviews/p2-6/03-dossiers/d05-artifact-numbers.txt
 -> Rows / SKUs / units for all three layouts, and the completeness block
/home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting/docs/reviews/p2-6/03-dossiers/d08-evidence-sha256-check.txt
 -> The independent verifier's integrity findings, still valid for the current files
