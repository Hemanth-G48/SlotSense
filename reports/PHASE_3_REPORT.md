# Phase 3 Report — Demand-aware optimization, experiments, and replenishment

**Date:** 2026-10-29
**Repo:** `/home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting`
**Dataset:** `dataset/processed` (canonical, read-only) · **Artifacts:** `outputs/phase3/`
**Detail:** `docs/PHASE_3_EXPERIMENTS_AND_DEMAND_METRICS.md` · **Machine-readable:** `outputs/phase3/phase3_experiments.json`

---

## Status

**COMPLETE.** All Phase 3 acceptance criteria that the project specification supports are implemented, run,
and evidenced. Two limits are documented rather than hidden: there is no new Streamlit view (the brief permits
delivering the data contract first when a view would be a redesign), and every effect is a deterministic
decomposition, not a significance test.

The headline correction: the held-out, quantity-aware improvement is **−48.29 %**, and it is a **placement**
effect. Bin-count consolidation alone is **+0.58 %** (slightly worse), not the "54 % fragmentation" an earlier
draft reported from the pick-rule sensitivity design.

---

## Files changed

| File | Purpose |
|---|---|
| `src/experiments/travel.py` | Order-line travel under two rules; `demand_weighted_depot_distance` with numerator/denominator, coverage, unresolved-line accounting, quantity-short reporting |
| `src/experiments/fragmentation.py` *(new)* | `min_bins` fragmentation policy: capacity-aware, distance-blind re-pack into a SKU's own bins; validator-gated with pinned retry |
| `src/experiments/factorial.py` | Generic 2×2 (`run_factorial_2x2`) for placement × fragmentation; keeps §11.5 pick-rule sensitivity (`run_2x2`) separate |
| `src/experiments/split.py` | Temporal order-level split; line-union completeness check (10 checks total) |
| `src/experiments/replenishment.py` | Restock-trip proxy; zero-demand SKUs make no trips; auditable counts |
| `src/optimization/replenishment.py` *(new)* | Shared trip/lot arithmetic used by the data frame wrapper and the objective |
| `src/optimization/objective.py` | `epsilon` + `Ψ_R` fifth term; per-component values and weighted contributions |
| `src/optimization/optimizer.py` | `replenishment_fn`; `_score`/`_components`; components in the log |
| `src/optimization/pipeline.py` | Threads fit-view demand and depot distances into `Ψ_R`; summary publishes components + replenishment |
| `src/models/config.py`, `configs/benchmark.json` | `epsilon` (default 0.0) |
| `src/experiments/run_phase3.py` | Runner: split → fit → primary 2×2 → all-bins outcome → pick-rule sensitivity → replenishment → sweep → provenance |
| `src/experiments/provenance.py` | Seeds, protocol, origin evidence, 33 output hashes; removes the `or True` origin shortcut |
| `app/phase3_contract.py` | Contract: design, cells, effects, all-bins, replenishment, sweep, completeness, feasibility |
| `app/dashboard_data.py` | `load_all()["phase3"]` exposes the contract; no metric recomputation |
| `tests/test_phase3_metrics.py`, `test_phase3_experiments.py`, `test_phase3_contract.py`, `test_phase3_fragmentation.py` *(new)*, `test_phase3_provenance.py` *(new)* | 42 Phase 3 tests |
| `docs/PHASE_3_EXPERIMENTS_AND_DEMAND_METRICS.md` | Full methodology, contracts, results, limitations |
| `ARCHITECTURE.md` (parent) | §11.4 objective term, §11.5 two designs, D22/D36/D46/D47/D48 closure text |
| `reports/BUILD_STATUS_REPORT.md` (parent) | Phase 3 status corrected |

---

## Metric definitions

```
T(line)                        = Σ depot→bin shortest-path distances for the stops that line causes
demand_weighted_depot_distance = Σ_over_resolved_lines T(line)
                                 numerator   = total metres
                                 denominator = resolved order lines
mean_per_line_m                = numerator / denominator
```

Unit: metres. Grain: order line aggregated to workload. Weighting is inherent in the line count — a SKU in
200 lines contributes 200 distances; quantity is not applied twice. Coverage is published: 5,997/5,997 lines
(100 %) in every cell; unresolved lines are counted with their reason, never priced at zero. Separately, **94
lines / 111 units** exceed the SKU's assigned stock (max 2 units per line); they are priced on the bins
visited and reported as `units_short`, which is a demand-vs-on-hand condition, not a missing assignment.

The optimizer's internal `D = Σ_records demand_frequency × distance` is a separate, record-based term; it is
published as `objective.components.D_travel` and never substituted for the line metric (recorded conflict:
`ARCHITECTURE.md` §11.2 annotates the name with "m·lines").

---

## 2×2 experiment

**Primary design.** Factor A = placement (`baseline_repaired` vs `optimized_fit`); Factor B = fragmentation
**policy** (`as_is` vs `min_bins`, a real layout manipulation). Controlled: warehouse, products, inventory,
constraints, radius 10 m, distance model, holdout workload, fit/holdout boundary. All four cells feasible
(0 violations, 6,375/6,375 units).

| Cell | Placement | Fragmentation | Feasible | Bins | `T` (m) | Mean/line (m) |
|---|---|---|---|---|---|---|
| A1 | baseline_repaired | as_is | ✅ | 1,425 | 501,569.0 | 83.6367 |
| A2 | baseline_repaired | min_bins | ✅ | 1,274 | 507,390.7 | 84.6074 |
| B1 | optimized_fit | as_is | ✅ | 1,290 | 259,336.6 | 43.2444 |
| B2 | optimized_fit | min_bins | ✅ | 1,271 | 259,300.7 | 43.2384 |

| Effect | Value | % of A1 |
|---|---|---|
| Placement (mean over B) | **−245,161.3 m** | **−48.88 %** |
| Fragmentation (mean over A) | **+2,892.9 m** | **+0.58 %** |
| Interaction (DiD) | −5,857.6 m | −1.17 % |

**Reading:** placement owns the gain. Consolidating the baseline from 1,425 to 1,274 bins *increases* travel
by 5,821.7 m because the distance-blind packer discards some near bins; on the optimized layout it lowers it
by 36.0 m. Under the `all_bins` accounting rule, where every bin is charged, the same four cells give a
fragmentation effect of **−87,475.3 m (−12.59 %)** — which is where a bin-count effect legitimately appears,
and why the old "54 %" number was an accounting artefact, not a layout property.

**Pick-rule sensitivity (secondary, architecture §11.5):** layout effect −331,758.2 m (−66.14 %), rule effect
+103,481.2 m, interaction −179,051.5 m. This is not a fragmentation treatment and is labelled as such.

---

## Fit/holdout integrity

Temporal, **order-level** split; fit = earlier 70 % of scenario-A history, holdout = later 30 %; no seed
because time ordering is total.

| View | Scenario | Orders | Lines | SKUs with demand |
|---|---|---|---|---|
| fit | `A_FIT` | 3,790 | 14,003 | 1,103 |
| holdout | `A_HOLDOUT` | 1,625 | 5,997 | 899 |

**Ten checks pass:** disjoint orders · union equals input · scenario rewritten per view · fit lines ⊆ fit
orders · holdout lines ⊆ holdout orders · no line in both · counts match manifest · **line union equals input**
· no duplicate (order, SKU) lines · manifest counts consistent. Each view is a complete tree with
`demand_summary` and `sku_affinity` recomputed; `run_phase5` is called with `fit_scenario=A_FIT` and
`affinity_scenario=A_FIT`. Holdout demand is passed only to the evaluator; the fit layout is frozen.

---

## Replenishment

```
trips(s,b) = ceil(on_hand(s,b) / lot(s));  lot(s) = ceil(daily_units(s) × 14)
travel     = Σ_(s,b) 2 × trips(s,b) × depot_distance(b)
```

A SKU with zero demand in the window makes **zero** trips (874 stocked units are reported separately), which
removes the earlier over-count.

| Cell (holdout demand) | Trips | Travel (m) | Bins |
|---|---|---|---|
| A1 baseline / as_is | 3,516 | 640,634.9 | 1,425 |
| A2 baseline / min_bins | 3,495 | 638,574.9 | 1,274 |
| B1 optimized / as_is | 3,495 | **382,207.7** | 1,290 |
| B2 optimized / min_bins | 3,494 | 382,189.1 | 1,271 |

B1 vs A1 = **−40.34 %**. Fragmentation policy alone = −1,039.3 m (−0.16 %); placement accounts for the rest.
Bins fall 9.47 % but trips only 0.60 %, and travel falls 40.34 % because the bins are much closer
(mean 96.82 → 70.81 m).

**Objective:** `ε·Ψ_R` is implemented and unit-tested; `epsilon` defaults to 0.0 and reproduces Phase 2
bit-for-bit. `ε = 0.5` is in the sweep. Limits: no schedule, batching, vehicle capacity, labour or currency;
`cover_days = 14` is an assumption.

---

## Weight sensitivity

Five vectors, all fitted on `A_FIT`, all independently feasible, all scored once on holdout.

| Config | α | β | γ | δ | ε | Fit objective | Fit `D` | Fit `R` | Fit T | Holdout T |
|---|---|---|---|---|---|---|---|---|---|---|
| default | 1.0 | 0.4 | 0.3 | 0.2 | 0.0 | 625,551.4 | 622,469.0 | 423,520.7 | 588,046.5 | 259,336.6 |
| travel_only | 1.0 | 0.0 | 0.0 | 0.0 | 0.0 | 622,469.0 | 622,469.0 | 423,520.7 | 588,046.5 | 259,336.6 |
| affinity_heavy | 1.0 | 1.0 | 0.3 | 0.2 | 0.0 | 628,588.2 | 622,469.0 | 423,520.7 | 588,046.5 | 259,336.6 |
| ergonomics_heavy | 1.0 | 0.4 | 1.0 | 0.2 | 0.0 | 627,084.4 | 622,469.0 | 423,520.7 | 588,046.5 | 259,336.6 |
| replenishment_heavy | 1.0 | 0.4 | 0.3 | 0.2 | 0.5 | 837,309.6 | 622,520.4 | 423,415.1 | 588,055.8 | 259,612.6 |

**Finding:** four vectors produce the **same layout** (same SHA-256) because the greedy starter ignores the
objective and the annealing pass found no improving move; β/γ/δ only reweight fixed components. `ε = 0.5`
does change the layout: −105.6 m fit restock travel (−0.025 %) for +276.1 m holdout pick travel (+0.107 %).

**Selection:** common metric = fit demand-weighted travel; default retained on ties. Raw objective sums are
never compared across weight vectors. Holdout is reported for every variant and never used to choose.

---

## Provenance and EDA

`outputs/phase3/provenance.json` records 12 input table hashes + row counts, config path/hash/weights, seeds
(optimizer 42; split `null` with reason), split manifest hash, evaluation protocol, origin evidence, software
versions, and 33 output hashes — including every per-line audit, every sweep layout and every per-variant
summary. Unknowns are marked `unknown` with a reason; `vcs.git = false` (not a repository).

**EDA (actual values):**

| Finding | Value | Consequence |
|---|---|---|
| Demand concentration | A = 293 SKUs (24.4 %) → 15,993/20,000 (79.97 %); top 20 % → 76.37 % | target ~293 SKUs with proximity and golden placement |
| Frequency vs units | correlation 0.9988; top 10 % hold 63.52 % vs 63.16 % | frequency is not an independent lever in this dataset |
| Affinity | 13,062 pairs; 5,114 clear co≥2/lift≥1; 469 clear co≥8/lift≥5; 114 clusters / 457 SKUs, largest 10 | affinity can only be secondary; large β buys a thin signal |
| Volume | 1,099/1,200 fit the median bin; median SKU = 2.27 % of a bin; top 10 % hold 67.04 % | one-SKU-per-bin wastes the tail; consolidation is a space lever |
| Velocity vs volume | A = 57.46 % of units but 20.93 % of volume | fast movers are small; volume-heavy stock is spread across classes |
| Golden-zone capacity | 576 level-2 bins vs 293 A SKUs; only 81 A SKUs (27.6 %) have golden stock in the optimized layout | the lever is abundant but unused; γ is too weak and the greedy ignores it |
| Fragmentation | 208 → 89 multi-bin SKUs; min_bins reaches 74 / 71 | bin count is reducible, but it does not reduce quantity-aware travel |

---

## Test results

```
.venv/bin/python -m pytest tests/test_phase3_metrics.py tests/test_phase3_experiments.py \
  tests/test_phase3_contract.py tests/test_phase3_fragmentation.py tests/test_phase3_provenance.py -q
→ 43 passed

.venv/bin/python -m pytest -q
→ 224 passed, 0 failed, 0 skipped
```

No test skipped, weakened or removed. The 181 Phase 2 tests still pass; Phase 3 grew from 25 to 43 tests.

---

## Benchmark results

| Item | Value |
|---|---|
| Baseline variant | `repaired_minimal` (1,071 → 0 `CAT-01`, 93/1,200 SKUs moved, 0 quantity changes) |
| Fit layout | `FEASIBLE`, 0 violations, 6,375/6,375 units, `A_FIT` only, 35.1 s |
| Held-out travel (quantity-aware) | 501,569.0 → **259,336.6 m = −48.29 %** |
| Raw all-bins comparison | 694,576.0 → 273,292.0 m = −60.65 % |
| 2×2 placement effect | −245,161.3 m (−48.88 %) |
| 2×2 fragmentation effect | +2,892.9 m (+0.58 %) |
| Restock travel (holdout) | 640,634.9 → 382,207.7 m = −40.34 % |
| Hard constraints | 0 violations in all four cells at 10 m |
| Inventory reconciliation | 6,375 = 6,375; 0 duplicate pairs; 0 unplaced SKUs |
| Quantity shortfall | 94 lines / 111 units (max 2 per line); priced, reported, not dropped |
| Runtime | full run ≈4 min (split + fit + 2×2 + replenishment + 5-variant sweep + provenance) |

---

## Remaining blockers

1. **No Streamlit view** for Phase 3 — the contract is delivered and `load_all()["phase3"]` exposes it; a tab
   would be a dashboard redesign, which the brief excludes (D28/D44 stay open).
2. **One deterministic instance per configuration** — no seed variability or confidence intervals.
3. **The greedy starter ignores objective weights** — β/γ/δ cannot change a layout; only ε reached the search.
   A weight-sensitive starter is a Phase 4 decision.
4. **Replenishment is a proxy** — no schedule, batching, vehicle capacity or labour; `cover_days = 14` is an
   assumption.
5. **Split is temporal on one history** — no seasonality or regime-shift test.
6. **Throughput/cycle time not re-derived on holdout** — no batch artifact for the holdout workload; Phase 2
   in-sample values remain the only ones.
7. **Historical artifacts remain non-comparable** (Phase 1 E.3).

---

## Phase 4 readiness

**Yes, for the Phase 3 scope.** Order-line travel, the published aggregate, a real placement × fragmentation
2×2, the leakage-checked split, the replenishment metric and objective term, the weight sweep, provenance, EDA
and the dashboard contract are implemented, tested and reproducible. Phase 4 should: (a) render the contract in
a dashboard view; (b) decide whether to make the starter weight-sensitive (which re-tunes the layout and
invalidates Phase 2 comparability); (c) add seed/scenario variability if statistical claims are wanted. Until
(a)–(c), the −48.29 % figure must be quoted with the deterministic-workload caveat and never as a held-out
significance result.
