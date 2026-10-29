# Phase 3 — Demand-aware optimization, evaluation experiments, and replenishment metrics

**Date:** 2026-10-29
**Repo:** `/home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting`
**Dataset:** `dataset/processed` (canonical, read-only) · **Artifacts:** `outputs/phase3/`
**Machine-readable result:** `outputs/phase3/phase3_experiments.json` (schema `phase3.experiments/2`)
**Predecessors:** `docs/PHASE_1_BASELINE_VERIFICATION.md`, `docs/PHASE_2_CONSTRAINT_ENGINE.md`, `reports/PHASE_2_REPORT.md`

> **Revision note.** An earlier Phase 3 draft used the **pick rule** as the second factor of the 2×2 and
> reported "54.0 % of the raw gain is fragmentation". That design is the architecture's §11.5 *pick-rule
> sensitivity* test — it changes how bins are charged, not how many bins a SKU occupies. It is retained here
> as a secondary design, and the primary 2×2 now manipulates a real **fragmentation policy**. The corrected
> answer is in §6: under quantity-aware picking, placement accounts for essentially all of the improvement and
> bin-count consolidation accounts for none of it.

---

## 1. Scope and acceptance criteria

Phase 3 answers six questions: (1) does demand-weighted travel improve; (2) is the gain placement or
fragmentation; (3) does it survive held-out demand; (4) what does replenishment cost; (5) how sensitive is any
of this to objective weights; (6) can every number be traced.

Accepted when: order-line travel is published with numerator/denominator; the 2×2 has four controlled cells
and calculated effects; the fit/holdout split is reproducible and leakage-checked; replenishment has defined
semantics and an objective term; the sweep reports feasibility and selection honestly; provenance covers
inputs, configuration, seeds and outputs; EDA states actual results; the dashboard contract exposes the new
metrics; and every layout used in a publishable comparison passes the independent Phase 2 validator.

## 2. Initial state (verified Phase 2)

Baseline repaired for feasibility with the objective disabled (1,071 → 0 `CAT-01`, 93/1,200 SKUs moved,
0 quantity changes); optimized layout feasible (0 violations, 6,375/6,375 units); evaluation gate blocks
infeasible comparisons; **181 Phase 2 tests passing**. The Phase 2 **−55.65 %** travel figure was computed
**in-sample** and is **not** a held-out result.

## 3. Metric contracts

| Metric | Definition | Numerator / denominator | Grain | Unit | Demand-weighted? | Artifact |
|---|---|---|---|---|---|---|
| `T` per line | Σ depot→bin shortest-path distances for the stops that line causes | — | order line | m | the line *is* the demand unit | `outputs/phase3/line_travel_<cell>.csv` |
| `demand_weighted_depot_distance` | `Σ_lines T(line)` over **resolved** lines | total metres / resolved lines | workload | m | yes, by line count | `phase3_experiments.json`, `phase3_cells.csv` |
| `mean_per_line_m` | `numerator / denominator` | as stated | line | m/line | no | same |
| pick-cycle time | travel/1.3 + 8 s×lines + 10 s×batch | — | batch | s | workload | **not re-derived in Phase 3** (no holdout batch artifact); Phase 2 in-sample values remain the only ones |
| throughput | orders / cycle hours | orders / hours | workload | orders/h | workload | same limitation |
| cube utilisation | occupied volume / usable stockable volume | cm³ / cm³ | warehouse | % | no | Phase 2 (immovable by construction) |
| replenishment travel | `Σ_(s,b) 2·trips(s,b)·depot_distance(b)` | metres / stocked SKU | layout | m | holdout demand sets `trips` | `phase3_replenishment.csv` |

**Why the aggregate is "demand-weighted" without a second weight.** The unit of account is the order line. A
SKU ordered in 200 lines contributes 200 distances; one ordered once contributes one. Multiplying by quantity
again would double-count: quantity only decides how many bins a line visits under `quantity_aware`. A
10-unit line and a 1-unit line at the same SKU/bin cost the same travel; that is the project's pick model,
not an omission.

**Conflict recorded, not silently resolved.** `ARCHITECTURE.md` §11.2 annotates
`demand_weighted_depot_distance` with unit "m·lines" and calls it "the quantity the optimizer minimises". The
optimizer's internal `D` is `Σ_assignment_records demand_frequency × distance` (a sum over records, which
charges a SKU once per bin). The D35 deliverable is the **order-line** quantity, which is metres, not metres
× lines. Both are published and named separately: `demand_weighted_depot_distance` = order-line aggregate;
`objective.components.D_travel` = the optimizer's record-based term. They are never substituted for each
other, and no improvement percentage is computed by mixing them.

**Unresolved lines are reported, not dropped.** A line whose SKU has no assigned bin, or whose selected bin
has no distance, cannot be priced. It is excluded from numerator *and* denominator, but published as
`lines_unresolved` with `lines_total` and `coverage_pct`, plus a per-line `unresolved_travel_<cell>.csv` with
the reason (`no_assignment`, `missing_distance`). The canonical holdout has 5,997/5,997 priced lines
(100 % coverage) in every cell.

**Quantity shortfall is separate from unresolved.** 94 holdout lines (111 units, at most 2 per line) request
more units than the SKU's assigned stock. They are still priced on the bins actually visited and reported as
`lines_quantity_short` / `units_short`; this is demand-versus-on-hand (assumption A-7), not a missing
assignment, and it does not change the distance definition.

## 4. Order-line travel implementation

`src/experiments/travel.py`. Two pick rules, both from the same layout and Dijkstra distance model:

- **`all_bins`** — the picker visits every bin holding the SKU (the v1 simulator's assumption).
- **`quantity_aware`** — the picker visits the nearest bins until the line's quantity is covered; a spilled
  line adds the next nearest bin. `quantity_short` is reported when total stock cannot cover the line.

`T` is the sum of depot→bin distances for the stops the line causes. The route model charges each stop once;
the line's quantity decides how many stops, never a multiplier on distance. Repeated SKUs across orders each
get their own line; multiple lines for one SKU are independent; a multi-unit line is one `T`; batched orders
are out of scope because the holdout workload is a line set, not a batch plan.

## 5. Demand-weighted travel — publication

Published in `phase3_experiments.json` (`two_by_two.cells[]`), `phase3_cells.csv` and the per-line audit files.
Every aggregate carries `numerator_m`, `denominator_lines`, `lines_total`, `lines_unresolved`, `coverage_pct`
and `mean_per_line_m`. The audit files sum exactly to the published cell value (verified: 5,997 rows and the
same total to the millimetre for all four cells).

## 6. The 2×2 placement × fragmentation experiment

### 6.1 Factors and levels

| Factor | Reference level | Alternative level | What it manipulates |
|---|---|---|---|
| **A — placement** | `baseline_repaired` | `optimized_fit` | which bins hold each SKU (fitted on `A_FIT`) |
| **B — fragmentation policy** | `as_is` | `min_bins` | how many of a SKU's own bins remain occupied |

`min_bins` re-packs each SKU's on-hand into as few of **its own** assigned bins as capacity allows
(bin weight, bin volume, beam, level, rack), releasing empty bins. Retained bins are chosen by **descending
static unit capacity, tie-broken by `location_id`**; depot distance is deliberately not consulted, so the
factor cannot smuggle in a proximity improvement. The packer reuses the optimizer's ledger and calls the
independent validator; a SKU that cannot be re-packed is pinned to its original rows and the pass retries.
The appended statistics report the used-bin mean depot distance before/after (96.82 → 96.23 m on the
baseline, 70.81 → 70.45 m on the optimized), so the small residual proximity change is visible.

### 6.2 Controls

Same warehouse geometry, products, inventory (6,375 units), hard constraints and 10 m separation radius,
Dijkstra distance model, holdout workload (5,997 lines), and fit/holdout boundary. The only intended
differences are the two factor levels. All four cells pass the independent validator with 0 violations and
exact inventory conservation.

### 6.3 Cells (outcome: `demand_weighted_depot_distance`, quantity-aware)

| Cell | Placement | Fragmentation | Feasible | Bins | Multi-bin SKUs | `T` (m) | Mean/line (m) |
|---|---|---|---|---|---|---|---|
| A1 | baseline_repaired | as_is | ✅ | 1,425 | 208 | **501,569.0** | 83.6367 |
| A2 | baseline_repaired | min_bins | ✅ | 1,274 | 74 | **507,390.7** | 84.6074 |
| B1 | optimized_fit | as_is | ✅ | 1,290 | 89 | **259,336.6** | 43.2444 |
| B2 | optimized_fit | min_bins | ✅ | 1,271 | 71 | **259,300.7** | 43.2384 |

### 6.4 Effects

| Effect | Value (m) | % of A1 | Reading |
|---|---|---|---|
| Placement (mean over fragmentation levels) | **−245,161.3** | **−48.88 %** | the optimized layout is much closer under either fragmentation level |
| Fragmentation policy (mean over placements) | **+2,892.9** | **+0.58 %** | consolidating bins alone **increases** travel slightly |
| Interaction (DiD) | **−5,857.6** | −1.17 % | the placement gain is 5.9 km larger when stock is consolidated |

Formulas: factor A = mean over B of `Y(a1,b) − Y(a0,b)`; factor B = mean over A of `Y(a,b1) − Y(a,b0)`;
interaction = `(Y(a1,b1) − Y(a0,b1)) − (Y(a1,b0) − Y(a0,b0))`. Negative = fewer metres.

**Interpretation.** Placement owns the result. Consolidation from 1,425 to 1,274 bins on the baseline
*raises* demand-weighted travel by 5,821.7 m (+1.16 %) because the distance-blind packer discards some near
bins; on the already-consolidated optimized layout it lowers it by 36.0 m (−0.014 %). The interaction is the
difference between those two changes. Reducing the bin count is not a travel lever unless the retained bins
are the near ones — which is a placement decision, not a fragmentation one.

### 6.5 The same four cells under `all_bins` (accounting sensitivity)

Because the v1 rule charges every bin a SKU occupies, a bin-count effect appears only there:

| Cell | `all_bins` T (m) |
|---|---|
| A1 | 694,576.0 |
| A2 | 524,645.8 |
| B1 | 273,292.0 |
| B2 | 268,271.5 |

| Effect | Value (m) | % of A1 |
|---|---|---|
| Placement | −338,829.1 | −48.78 % |
| Fragmentation | **−87,475.3** | **−12.59 %** |
| Interaction | +164,909.6 | +23.74 % |

This is the honest version of the old "54 %" claim: fragmentation *does* matter under the all-bins rule, but
that rule is the thing being varied, not the layout. Under the quantity-aware rule — the defensible pick
model — the fragmentation effect is +0.58 %, not 54 %.

### 6.6 Pick-rule sensitivity (architecture §11.5, secondary)

The earlier design is retained separately, using the two `as_is` layouts and varying the rule:

| Cell | Layout | Rule | T (m) |
|---|---|---|---|
| — | baseline_repaired | all_bins | 694,576.0 |
| — | baseline_repaired | quantity_aware | 501,569.0 |
| — | optimized_fit | all_bins | 273,292.0 |
| — | optimized_fit | quantity_aware | 259,336.6 |

Layout effect −331,758.2 m (−66.14 % of the quantity-aware baseline); rule effect +103,481.2 m (+20.63 %);
interaction −179,051.5 m. This quantifies how much the raw comparison depends on the accounting rule; it is
**not** a fragmentation treatment and is not reported as one.

## 7. Fit/holdout split and leakage checks

`src/experiments/split.py`. **Temporal, order-level**: orders sorted by `order_timestamp` then `order_id`;
first 70 % is the fit view, last 30 % the holdout. Order-level because a basket shares one picking trip;
temporal because a random split would fit on later history and evaluate on earlier.

| View | Scenario | Orders | Lines | SKUs with demand | Window |
|---|---|---|---|---|---|
| fit | `A_FIT` | 3,790 | 14,003 | 1,103 | earliest 70 % |
| holdout | `A_HOLDOUT` | 1,625 | 5,997 | 899 | latest 30 % |

Each view is a **complete tree**: `demand_summary` and `sku_affinity` are recomputed per view, so fit cannot
see holdout demand. Physical tables (warehouse, products, inventory, baseline, graph) are copied unchanged.

**Ten checks, all passing:** disjoint orders · union equals input population · scenario ids rewritten per
view · fit lines belong to fit orders · holdout lines belong to holdout orders · no line in both views · line
counts match the manifest · line union equals the input line count · no duplicate (order, SKU) lines ·
manifest counts consistent. The split rebuilds to identical hashes, so it is reproducible without a seed.

`run_phase5` takes `fit_scenario` / `affinity_scenario`; the Phase 3 run passes `A_FIT` for both, so demand
**and** affinity are mined on fit data only. Holdout demand is passed only to the evaluator.

## 8. Replenishment semantics, metric and objective term

The dataset has no replenishment events, supplier data or restock policy. It has per-bin on-hand, demand over
a known window, and depot distances. The supported proxy:

```
daily_units(s) = units_demanded(s) / window_days          window_days = 180
lot(s)         = ceil(daily_units(s) × cover_days)        cover_days  = 14 (assumption)
trips(s, b)    = ceil(on_hand(s, b) / lot(s))             0 when demand(s) = 0
travel         = Σ_(s,b) 2 × trips(s, b) × depot_distance(b)
```

**Zero-demand SKUs make zero trips.** A SKU stocked but not demanded in the window is not restocked during
that window; charging `ceil(on_hand/1)` trips would invent work. Its 874 units are reported separately
(`units_in_skus_without_demand`). This correction changes the absolute numbers from the earlier draft
(baseline 817,730.8 → 640,634.9 m) but not the conclusion.

| Cell (holdout demand) | Trips | Replenishment travel (m) | Mean/stocked SKU (m) | Bins |
|---|---|---|---|---|
| A1 baseline / as_is | 3,516 | **640,634.9** | 533.9 | 1,425 |
| A2 baseline / min_bins | 3,495 | **638,574.9** | 532.1 | 1,274 |
| B1 optimized / as_is | 3,495 | **382,207.7** | 318.5 | 1,290 |
| B2 optimized / min_bins | 3,494 | **382,189.1** | 318.5 | 1,271 |

Direct B1 vs A1 = **−40.34 %**. Fragmentation policy alone (mean over placements) = **−1,039.3 m (−0.16 %)**;
placement alone accounts for the rest. Bins fall 9.47 % while trips fall only 0.60 % (fewer destinations, more
trips per destination), and travel falls 40.34 % because the retained bins are much closer (mean 96.82 →
70.81 m).

**Objective integration.** `Objective` now carries `epsilon` and a fifth term `ε·Ψ_R`, where `Ψ_R` is the
same replenishment travel. `epsilon` defaults to **0.0**, which reproduces the Phase 2 objective bit-for-bit;
the short-circuit means no candidate pays the cost of the proxy unless the weight is non-zero. The pipeline
threads fit-view demand and depot distances into the optimizer, and the summary publishes
`D/A/E/U/R` components plus weighted contributions. Hard constraints remain the validator's exclusive
verdict — a huge `epsilon` cannot make an infeasible layout acceptable (regression test).

**What is not modelled:** schedule, trip batching, vehicle capacity, labour cost, forward-pick areas.
`cover_days = 14` is an assumption. This is a proxy for restock *travel*, not an operational plan.

## 9. Weight sensitivity

`src/experiments/run_phase3.py`. Five vectors over the existing weights plus `epsilon`; each fitted on
`A_FIT`, each independently validated, each scored once on holdout.

| Config | α | β | γ | δ | ε | Fit feasible | Fit objective | Fit `D` | Fit `R` | Fit T (m) | Holdout T (m) | Layout SHA (12) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| default | 1.0 | 0.4 | 0.3 | 0.2 | 0.0 | ✅ | 625,551.4 | 622,469.0 | 423,520.7 | 588,046.5 | 259,336.6 | `cafa55e805e8` |
| travel_only | 1.0 | 0.0 | 0.0 | 0.0 | 0.0 | ✅ | 622,469.0 | 622,469.0 | 423,520.7 | 588,046.5 | 259,336.6 | `cafa55e805e8` |
| affinity_heavy | 1.0 | 1.0 | 0.3 | 0.2 | 0.0 | ✅ | 628,588.2 | 622,469.0 | 423,520.7 | 588,046.5 | 259,336.6 | `cafa55e805e8` |
| ergonomics_heavy | 1.0 | 0.4 | 1.0 | 0.2 | 0.0 | ✅ | 627,084.4 | 622,469.0 | 423,520.7 | 588,046.5 | 259,336.6 | `cafa55e805e8` |
| replenishment_heavy | 1.0 | 0.4 | 0.3 | 0.2 | 0.5 | ✅ | 837,309.6 | 622,520.4 | 423,415.1 | 588,055.8 | 259,612.6 | `b4a17623c358` |

**What this measures.** β/γ/δ change the reported objective by reweighting fixed components and leave the
layout **identical** (same SHA): the greedy starter is velocity-and-distance ordered and never consults the
objective, and the 600-candidate annealing pass found no improving move. This is an algorithmic fact, not a
data finding. `ε = 0.5` **does** change the layout because it changes the annealing score landscape: it buys
105.6 m of fit restock travel (−0.025 %) for 51.4 m of fit objective travel (+0.008 %) and 276.1 m of
holdout pick travel (+0.107 %). The trade-off is real but negligible at this weight scale.

**Selection protocol.** Selection uses a *common* metric — fit demand-weighted travel (quantity-aware) —
among independently feasible runs, with the default kept on ties. Raw objective values are never compared
across weight vectors: different weights make them different scales, and minimising the sum would simply
prefer the vector that deletes penalty terms. Holdout is reported for every variant and never used to choose.
The default is retained; `travel_only` is byte-identical, so there is nothing to gain by switching.

## 10. Objective and evaluation integrity

- Hard feasibility is separate from objective value: every cell's `feasibility_status` comes from the
  independent `Validator`, never from the objective.
- The optimizer's record-based `D` is not the published order-line metric (§3).
- Every rate publishes numerator and denominator; no percentage is computed from a zero denominator.
- The Phase 2 gate still blocks infeasible comparisons; all four cells are `FEASIBLE` with 0 violations.
- Infeasible cells are retained in the design and flagged, never dropped or substituted (tested).
- The Phase 2 **−55.65 %** is labelled **in-sample** everywhere; the Phase 3 headline is the direct holdout
  comparison.
- `phase3_experiments.json` carries `integrity.publishable_comparison = true` only because all four cells
  passed independent validation and inventory conservation.

## 11. Provenance

`outputs/phase3/provenance.json` (schema `phase3.provenance/1`) records: 12 per-table SHA-256 + row counts;
origin evidence (generator script / build script / generation manifest) and the resulting origin; licence and
retrieval status (`not applicable` only because the evidence shows in-repo synthesis, else `unknown`);
configuration path + SHA-256 + full config + objective weights; experiment id and scenario; seeds (optimizer
42, split `null` with the reason); split manifest path + SHA-256; evaluation protocol (fit/holdout/outcome/
feasibility/selection); transformation list; software versions and platform; and **33 output artifacts** with
path, SHA-256 and row count — including every line-travel audit, every sweep layout and every per-variant
summary. Missing provenance is marked `unknown` with a reason; nothing is guessed. The checkout is not a Git
repository, recorded as `vcs.git = false`.

## 12. EDA findings (actual values, with consequences)

| Question | Actual result | Interpretation | Operational consequence | Limitation |
|---|---|---|---|---|
| Demand concentration (ABC) | A = **293 SKUs (24.4 %)** carry **15,993/20,000 = 79.97 %** of demand; top 20 % carry 76.37 % | the fast-mover set is ~300 SKUs, not 1,200 | golden-zone and proximity effort should target ~293 SKUs; the other 907 are fill | ABC boundary puts the crossing SKU in A only until 80 % is crossed (79.965 %) |
| Is demand frequency a proxy for units? | correlation **0.9988**; top 10 % hold 63.52 % of frequency and 63.16 % of units | frequency and unit demand are nearly the same axis in this dataset | the objective's frequency weighting does not materially differ from a unit weighting here; do not claim they are independent levers | synthetic demand generator ties them |
| Affinity structure | 13,062 pairs; **5,114 (39.1 %)** clear co ≥ 2 & lift ≥ 1; **469 (3.6 %)** clear co ≥ 8 & lift ≥ 5; **114 clusters**, 457 SKUs, largest 10 | adjacency opportunity is sparse and small | affinity can only be a secondary term; a large β would trade travel for a thin signal | thresholds are config choices; cluster count is threshold-dependent |
| Volume vs capacity | **1,099/1,200** SKUs fit the median bin; median SKU occupies **2.27 %** of a bin; top 10 % hold **67.04 %** of volume | the instance is volume-slack for the long tail, volume-concentrated at the head | one-SKU-per-bin wastes space for the tail; consolidation is the space lever, not a travel lever | bounding-box volume, no 3-D packing |
| Velocity vs volume | A SKUs are 57.46 % of units but only **20.93 %** of volume | fast movers are small; volume-heavy SKUs are spread across classes | a single "A items in golden" rule ignores the volume-heavy tail; slotting must trade pick proximity against cube | descriptive, not causal |
| Golden-zone capacity | **576** level-2 bins vs **293** A SKUs; optimized layout puts A stock in golden for only **81 A SKUs (27.6 %)**; baseline 77 (26.3 %) | the golden lever is abundant but unused | the ergonomics term (γ) is too weak relative to travel and the greedy ignores it; a future phase should either raise γ or constrain golden placement | counts stock presence, not pick frequency per level |
| Fragmentation vs travel | baseline 208 multi-bin SKUs / 1,425 bins; optimized 89 / 1,290; `min_bins` reaches 74 / 1,274 (baseline) and 71 / 1,271 (optimized) | bin count can be cut ~10 % without touching placement | but the 2×2 shows this does **not** reduce quantity-aware travel (+0.58 %); placement does | one deterministic instance |

**Relationship to the layout result.** The −48.30 % held-out travel gain is a placement effect: the
optimized layout's used bins are much closer to dispatch (mean 70.81 m vs 96.82 m). Restock travel falls
40.34 % for the same reason, not because bins were consolidated. Consolidation alone changes restock travel
by −0.16 %.

## 13. Dashboard data contract

`app/phase3_contract.py` exposes `load_phase3()` and is wired into `app/dashboard_data.py` as
`load_all()["phase3"]`. Fields: experiment id, split (method/unit/fraction/seed/fit/holdout/checks), baseline
variant, design (factors, levels, cell ids, controls), four cells with cell id, placement, fragmentation
policy, feasibility, `demand_weighted_depot_distance`, numerator/denominator/coverage, fragmentation stats;
effects; the all-bins outcome; the pick-rule sensitivity design; replenishment per cell with assumptions; the
sweep with objective components and selection; assignment completeness; objective components; per-cell
feasibility and `publishable_comparison`; `evaluation_status` (`held_out` vs `in_sample_or_unverified`); and
the methodology caveat. Missing artifacts return `"unavailable"` with the command that produces them —
**nothing is defaulted to 0**.

**Limitation, stated.** No Streamlit view was added: `dashboard.py` is a 2,800-line single-page app whose
layout is built around the Phase 2 evaluation artifacts, and a new tab would be a redesign the brief excludes.
The contract is delivered and loaded; a Phase 4 view can render it without recomputing anything.

## 14. Tests and results

```bash
.venv/bin/python -m pytest tests/test_phase3_metrics.py tests/test_phase3_experiments.py \
  tests/test_phase3_contract.py tests/test_phase3_fragmentation.py \
  tests/test_phase3_provenance.py -q
# 43 passed
```

The full suite result is recorded in §14.1 after the run below.

Covers: single-SKU/single-line travel · line-count demand weighting · quantity-aware coverage and spill ·
all-bins over-charging · no double multiplication by quantity · missing assignment and missing distance
reported with coverage · quantity-short reporting · empty workload with no denominator · per-line table
summing to the aggregate · lot sizing · hand-checked replenishment trips/travel · zero-demand SKUs make no
trips · replenishment growth under fragmentation · `epsilon` component and Phase 2 reproduction · infeasible
layout cannot be made acceptable by a weight · 2×2 cell values and effects on a hand-calculated fixture ·
infeasible cells retained and flagged · fragmentation consolidation, determinism, capacity-bound retention,
pinned retry and infeasible fallback · temporal split ordering, disjointness, line-union completeness,
reproducibility, per-view demand recomputation, manifest fields · provenance seeds/hashes/origin ·
contract unavailability and status downgrade.

### 14.1 Full suite

```
command: .venv/bin/python -m pytest -q
result:  224 passed, 0 failed, 0 skipped
```

No test was skipped, weakened or removed. The 181 Phase 2 tests still pass; the Phase 3 test set grew from
25 to 43 with the fragmentation policy, all-bins outcome, provenance and objective-term coverage.

## 15. Actual results and calculations

**Headline, held-out, quantity-aware:** baseline repaired 501,569.025 m → optimized 259,336.575 m =
**−242,232.450 m = −48.29 %**. This is the direct B1-vs-A1 comparison on demand that did not influence the
layout.

**Raw all-bins comparison:** 694,575.975 → 273,292.025 m = **−60.65 %**, of which bin-count consolidation
alone accounts for −12.59 percentage points and placement for the rest. The older −55.65 % Phase 2 figure
remains in-sample and is not comparable.

**2×2 placement main effect:** −245,161.3 m (−48.88 % of A1). **Fragmentation main effect:** +2,892.9 m
(+0.58 %). **Interaction:** −5,857.6 m. All effects are decompositions of one deterministic workload, not
significance tests.

**Replenishment, holdout demand:** 640,634.9 → 382,207.7 m = **−40.34 %**; trips 3,516 → 3,495; bins
1,425 → 1,290.

**Weight sweep:** four of five vectors produce one layout; `ε = 0.5` produces a second layout that trades
0.025 % restock travel for 0.107 % holdout pick travel. The default is retained by the fit-travel rule.

## 16. Reproduce

```bash
cd /home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting

# full run (split -> fit -> 2x2 -> replenishment -> sweep -> provenance), ~4 min
.venv/bin/python -m src.experiments.run_phase3

# core path without the sweep, ~1 min
.venv/bin/python -m src.experiments.run_phase3 --skip-sweep

# Phase 3 tests
.venv/bin/python -m pytest tests/test_phase3_metrics.py tests/test_phase3_experiments.py \
  tests/test_phase3_contract.py tests/test_phase3_fragmentation.py tests/test_phase3_provenance.py -q

# full suite
.venv/bin/python -m pytest -q
```

Outputs land in `outputs/phase3/`; the canonical dataset is never written to. The previous Phase 3 artifact
set is archived at `outputs/_archive/phase3_pre_redesign_*.tar.gz`.

## 17. Limitations and blockers

1. **One deterministic instance per configuration.** No seed variability, so every effect is a decomposition,
   not a significance test. The sweep's two layouts are two points, not a sensitivity curve.
2. **The greedy starter ignores the objective weights.** β/γ/δ cannot change a placement, so the sweep
   measures the *reported* objective, not the search's response to those terms. Only ε changed the layout
   (through annealing). A weight-sensitive starter is a Phase 4 change and would invalidate Phase 2's layout.
3. **`min_bins` is a real layout change**, not an independent dial: it retains a subset of each SKU's bins.
   Retention is distance-blind, but the residual proximity change (≈0.6 %) is reported rather than assumed away.
4. **Replenishment is a proxy.** No schedule, batching, vehicle capacity or labour cost; `cover_days = 14`
   is an assumption. Zero-demand SKUs are excluded from trips by rule, not observed.
5. **Split is temporal on one history.** No seasonality or regime-shift test; the holdout is the later 30 %
   of scenario A.
6. **Throughput and cycle time were not re-derived on holdout** because the holdout workload has no batch
   artifact. Phase 2's in-sample values remain the only ones; they are not quoted as held-out.
7. **Dashboard view not built** — contract and loader only (D28/D44 remain open).
8. **Historic artifacts remain non-comparable** (Phase 1 E.3).
9. **The objective's record-based `D` still charges a SKU once per bin.** It is reported separately from the
   published line metric; unifying them is a Phase 4 decision, not a silent redefinition.
