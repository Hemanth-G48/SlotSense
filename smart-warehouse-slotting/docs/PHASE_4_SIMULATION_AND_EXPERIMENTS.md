# Phase 4 — Simulation, evaluation, and controlled experiments

**Date:** 2026-10-29
**Repo:** `/home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting`
**Dataset:** `dataset/processed` (canonical, read-only) · **Artifacts:** `outputs/phase4/`
**Machine-readable result:** `outputs/phase4/phase4_experiments.json` (schema `phase4.experiments/1`)
**Independent verification:** `outputs/phase4/verification.json` (14/14 checks)

---

## 1. Scope and acceptance criteria

Phase 4 separates four things Phase 3 deliberately kept apart: layout quality, picking policy,
workload/regime, and simulation. It answers: does the optimized layout win under identical
conditions; how much does the result depend on the picking strategy; does it survive held-out
demand and different demand regimes; are weights stable; can every number be independently
recomputed.

Accepted when: the four 2×2 cells share one workload and one configuration; every publishable
layout passes the independent validator; travel, cycle time, throughput, demand-weighted travel,
fragmentation and replenishment all have explicit definitions; the fit/holdout split is verified;
the frozen layout is evaluated on unseen demand and on B/C regimes; headroom and rejection paths
are reported; machine-readable outputs are provenance-linked; an independent script reproduces
the headline metrics; and no statistical significance is claimed from one deterministic run.

## 2. Audit of the Phase 3 starting state

| Area | Current implementation | Verified? | Missing / incorrect behaviour |
|---|---|---|---|
| Baseline selection | `run_phase6` takes `baseline_path` + `baseline_variant`; Phase 4 passes `repaired_minimal`, never the as-supplied layout | **Yes** — independent validator; variant and source recorded | None for Phase 4 |
| Workload construction | `orders` filtered by scenario; batches of 5 orders sorted by `order_id`; one frame simulated twice | **Yes** — workload SHA-256 published | No stochastic arrivals; batch size fixed at 5 |
| Route simulation | Two policies: `nearest_neighbor` and `s_shape`; Dijkstra pairwise distances; depot tour | **Yes** — route sums and leg identity recomputed | `s_shape` is a documented node-order serpentine simplification, not a full aisle-grid S-shape |
| Metric calculation | Travel, cycle, throughput, cube, golden share, assignment completeness from route/validator outputs; Phase 3 line travel/fragmentation/replenishment attached per layout | **Yes** — independent recomputation | Pick time is per **order line**, not per stop (D37 remains open) |
| Feasibility gate | Both layouts validated before scoring; blocked comparisons publish no table | **Yes** — deliberate beam-overload test blocks | None |
| Fit/holdout | Phase 3 temporal order-level split, 10 checks, reused byte-for-byte | **Yes** — manifest hash and `verify_split` | No separate validation slice (fit/holdout only) |
| Experiment reproducibility | Deterministic simulation; layout and split hashes; provenance manifest | **Yes** — 14/14 independent checks | One deterministic run per cell; no seed variability |

Phase 3 already provided order-line travel, the leakage-safe split, the placement × fragmentation
2×2, replenishment and the weight sweep. Phase 4 did not rebuild those; it reused their definitions
and added the picking-policy experiment, operational cycle/throughput metrics, demand regimes,
headroom, rejection diagnostics and independent verification.

## 3. Baseline selection and feasibility

- **Supplied baseline:** `dataset/processed/storage_assignments_baseline.csv`, infeasible under
  `CAT-01` at 10 m (1,071 violations in Phase 2).
- **Comparison baseline:** `outputs/phase3/optimized_fit/baseline_repaired_assignments.csv`,
  variant **`repaired_minimal`**, repaired for feasibility with the objective disabled.
- **Optimized layout:** `outputs/phase3/optimized_fit/optimized_assignments.csv`, fitted on
  `A_FIT`, frozen by SHA-256 for every Phase 4 run.

Both layouts pass the independent validator in every cell (0 violations, 6,375/6,375 units,
100 % assignment completeness). The as-supplied baseline is never substituted for the repaired
one, and its metrics remain diagnostic-only inside each `evaluation_summary.json`.

## 4. Simulation and metric definitions

| Metric | Definition | Numerator / denominator | Grain | Unit |
|---|---|---|---|---|
| Batch construction | orders sorted by `order_id`, consecutive groups of 5 | — | batch | orders |
| Route | depot → distinct pick bins → depot, ordered by policy | — | batch | — |
| `total_travel_distance_m` | Σ Dijkstra leg distances over all batch tours | — | workload | m |
| `total_route_time_sec` | Σ per-batch cycle time | — | workload | s |
| per-batch cycle | `distance / 1.3 + 8 s × order_lines + 10 s` | — | batch | s |
| `throughput_orders_per_hr` | orders completed / (total cycle / 3600) | orders / hours | workload | orders/h |
| `avg_time_per_order_sec` | total cycle / orders | seconds / order | workload | s/order |
| `demand_weighted_depot_distance` | Phase 3: Σ depot→bin per order line, quantity-aware | metres / resolved lines | order line → workload | m |
| fragmentation | bins used, multi-bin SKUs, bins/SKU | bins / SKUs | layout | count, ratio |
| replenishment travel | `Σ 2·trips·depot_distance`, 14-day lots | metres / stocked SKU | layout | m |
| cube utilisation | occupied volume / usable volume | cm³ / cm³ | warehouse | % |
| assignment completeness | valid assignments / required assignments | SKUs / SKUs | layout | % |

**What is policy-dependent and what is not.** Simulator travel, cycle time and throughput vary
with the routing policy. `demand_weighted_depot_distance`, fragmentation and replenishment describe
the layout and are invariant across policies; they are reported once per layout, not pretended to
be four independent measurements.

**Missing values.** A blocked comparison publishes no metric table. A layout with an unresolved
line reports coverage and the unresolved count rather than pricing it at zero. A missing denominator
(zero travel, zero orders) fails the fairness check and blocks publication.

## 5. Fair-comparison controls

Every cell uses: the same holdout workload (`workload_id` hash), warehouse geometry, inventory
(6,375 units), batch size 5, picker speed 1.3 m/s, pick time 8 s/line, setup 10 s/batch, metric
definitions and validator. Only layout and routing policy vary. The fairness block records:

- `same_workload: true` with the workload SHA-256 and counts;
- both layouts independently feasible and assignment-complete;
- positive travel/cycle/order denominators;
- the evaluation gate's verdict (`publishable: true` only when all of the above hold).

`run_phase6` now exposes this as `integrity`; the Phase 4 runner refuses to continue if any cell's
integrity is false.

## 6. 2×2 experiment design and results

Factors: **layout** (`baseline_repaired` vs `optimized_fit`) × **picking policy**
(`nearest_neighbor` vs `s_shape`). Workload: 1,625 orders / 5,997 lines / 9,626 units (`A_HOLDOUT`).

| Cell | Layout | Policy | Feasible | Travel (m) | Cycle (s) | Throughput (orders/h) |
|---|---|---|---|---|---|---|
| A1 | baseline_repaired | nearest_neighbor | ✅ | 508,174.8 | 442,129.7 | 13.23 |
| A2 | baseline_repaired | s_shape | ✅ | 508,355.6 | 442,268.8 | 13.23 |
| B1 | optimized_fit | nearest_neighbor | ✅ | 234,208.0 | 231,386.0 | 25.28 |
| B2 | optimized_fit | s_shape | ✅ | 234,950.7 | 231,957.3 | 25.22 |

## 7. Main effects and interaction

| Metric | Layout effect | Policy effect | Interaction |
|---|---|---|---|
| Travel (m) | **−273,685.85 (−53.86 %)** | **+461.75 (+0.09 %)** | +561.90 |
| Cycle time (s) | **−210,527.58 (−47.62 %)** | +355.20 (+0.08 %) | +432.23 |
| Throughput (orders/h) | **+12.02 (+90.85 %)** | −0.03 (−0.23 %) | −0.06 |
| Time per order (s) | −129.56 (−47.62 %) | +0.22 (+0.08 %) | +0.26 |
| Demand-weighted travel (m) | −242,232.45 (−48.29 %) | 0 (layout metric) | 0 |
| Replenishment travel (m) | −258,427.15 (−40.34 %) | 0 (layout metric) | 0 |

Formulas: layout = mean over policies of `Y(opt,p) − Y(base,p)`; policy = mean over layouts of
`Y(l,s) − Y(l,nn)`; interaction = `(Y(opt,s) − Y(base,s)) − (Y(opt,nn) − Y(base,nn))`.
Negative is better for travel/cycle/time-per-order; positive is better for throughput.

**Reading.** The layout effect dominates by two orders of magnitude. S-shape is slightly worse than
nearest-neighbour on both layouts (+0.09 % travel), and the interaction (+561.9 m) means the
optimized layout's advantage is 561.9 m smaller under S-shape — still −53.78 % versus its own
baseline, so the choice of policy does not change the conclusion. All cells remain feasible.

## 8. Fit/holdout methodology

Phase 3's temporal, order-level 70/30 split is reused unchanged: fit 3,790 orders / 14,003 lines;
holdout 1,625 / 5,997. Ten checks pass (disjoint, union equals input, line-union completeness,
scenario rewrite, no duplicate order-SKU lines, manifest consistency). Both layouts are frozen by
SHA-256 before evaluation; no refit, retune or policy selection uses holdout outcomes.

Holdout result (nearest-neighbour, the project's reported policy): **508,174.8 → 234,208.0 m =
−53.91 %**; cycle time 442,129.7 → 231,386.0 s (−47.67 %); throughput 13.23 → 25.28 orders/h
(+91.1 %). Under S-shape: 508,355.6 → 234,950.7 m = −53.78 %.

## 9. Held-out demand regimes

Regimes are defined by the dataset's actual scenario generators (A = head-heavy, B = flat,
C = clustered), not by choosing favourable holdout slices. B and C were never used for fitting.

| Regime | Orders | Lines | Units | SKUs | Top-10 % unit share | A SKUs | Baseline travel | Optimized travel | Change |
|---|---|---|---|---|---|---|---|---|---|
| A_HOLDOUT | 1,625 | 5,997 | 9,626 | 899 | 58.62 % | 271 | 508,174.8 m | 234,208.0 m | **−53.91 %** |
| B | 5,420 | 20,000 | 32,080 | 1,200 | 15.41 % | 856 | 1,834,069.9 m | 1,222,102.9 m | **−33.37 %** |
| C | 5,409 | 20,000 | 32,008 | 1,200 | 15.39 % | 861 | 1,653,629.4 m | 955,970.4 m | **−42.19 %** |

Throughput: A 13.23 → 25.28 (+91.1 %); B 12.34 → 17.56 (+42.3 %); C 13.50 → 21.49 (+59.2 %).
The gain persists in every regime but is strongest where demand is most concentrated and the
workload is the smaller temporal holdout. B/C are full scenario populations, so their absolute
travel is much larger than the A holdout; percentage changes are the comparable quantity.

Limitations: B and C are different synthetic generators, not resamples of A; no seasonality or
regime-transition test exists; each regime is one deterministic workload.

## 10. Objective-weight sensitivity

Phase 3's five-vector sweep is reused; no Phase 4 rerun was needed because the dataset, split,
layout fitting and metric definitions match. The selected configuration is **default**
(α=1.0, β=0.4, γ=0.3, δ=0.2, ε=0.0), and its layout SHA-256 matches the frozen optimized layout
(`selected_matches_frozen_layout: true`).

| Config | α | β | γ | δ | ε | Fit feasible | Fit T (m) | Holdout T (m) | Layout SHA (12) |
|---|---|---|---|---|---|---|---|---|---|
| default | 1.0 | 0.4 | 0.3 | 0.2 | 0.0 | ✅ | 588,046.5 | 259,336.6 | `cafa55e805e8` |
| travel_only | 1.0 | 0.0 | 0.0 | 0.0 | 0.0 | ✅ | 588,046.5 | 259,336.6 | `cafa55e805e8` |
| affinity_heavy | 1.0 | 1.0 | 0.3 | 0.2 | 0.0 | ✅ | 588,046.5 | 259,336.6 | `cafa55e805e8` |
| ergonomics_heavy | 1.0 | 0.4 | 1.0 | 0.2 | 0.0 | ✅ | 588,046.5 | 259,336.6 | `cafa55e805e8` |
| replenishment_heavy | 1.0 | 0.4 | 0.3 | 0.2 | 0.5 | ✅ | 588,055.8 | 259,612.6 | `b4a17623c358` |

Four vectors produce one identical layout; ε=0.5 produces a second that trades −0.025 % restock
travel for +0.107 % holdout pick travel. Selection used fit demand-weighted travel, not the raw
objective and not the holdout. The weights are therefore **not operationally discriminating** on
this instance; the Phase 4 conclusion does not depend on a tuned weight vector.

## 11. Rejection diagnostics

Every `run_phase6` result now carries structured diagnostics per layout:

- layout id and publishable flag;
- failure categories (bin weight/volume, level, beam, rack, separation, inventory, dimensions, hazard, handling);
- affected SKUs and bins;
- per-violation observed vs limit, unit, reason, and whether it blocks publication;
- a next investigation step.

All Phase 4 layouts are feasible, so the diagnostic block records empty failure sets. The
failure path itself is tested: a beam-overloaded baseline produces
`BLOCKED_INFEASIBLE_LAYOUT`, `comparison: []`, `publishable: false`, and a `beam_load` category —
it is never converted into a zero-travel comparison.

## 12. Structural utilization and headroom

Measured from the independent validator's own checks (`observed / limit`); the 90/95 % bands are
reporting thresholds, not new constraints.

| Scope | Optimized max | Optimized ≥95 % of checks | Baseline max | Optimized limiting record |
|---|---|---|---|---|
| Bin weight (LD-01) | **100.00 %** | 0.543 % | 100.00 % | `LOC002120` |
| Bin volume (VD-01) | **99.93 %** | 1.008 % | 99.67 % | `LOC000193` |
| Shelf level (SL-01) | **98.06 %** | 1.488 % | 72.15 % | `R5-3-1` level 1 |
| Beam (SL-02) | **98.76 %** | 0.754 % | 72.49 % | `R5-3-1` bay 0 level 1 |
| Rack (RK-01) | 69.36 % | 0 % | 36.05 % | `R5-3-3` |

Feasible is not the same as spare. The optimized layout is at 100 % of one bin's weight, 99.93 %
of one bin's volume, and 98–99 % of a level and a beam. That is a real operational risk: any
quantity change, re-slot or demand shift needs re-validation before publication. The Phase 2
report's historical 99.37 % beam / 99.56 % level figures belonged to an earlier optimized artifact;
the frozen Phase 3 layout measures 98.76 % / 98.06 % here. No 95 % placement target was introduced.

## 13. Independent verification results

`tools/verify_phase4.py` re-reads the raw route tables and layout CSVs and recomputes, without
trusting the summary:

```
checks: 14  failed: 0
route sums reproduce travel; cycle identity holds per batch
throughput = orders / cycle hours
travel effects and the direct holdout change recompute
inventory conserved; no duplicate (SKU, bin) pairs
split disjoint and complete; regime counts reconcile
headroom recomputes from validation_checks_*.csv
provenance hashes match
```

Tolerance is 0.05 m/s for sums (the simulator rounds to 2 dp) and 0.001 percentage points for the
direct change (reported to 3 dp). The verifier exits non-zero on any failure; the Phase 4 run is
green.

## 14. Test commands and actual counts

```
.venv/bin/python -m pytest tests/test_phase4_fairness.py tests/test_phase4_contract.py -q
→ 23 passed

.venv/bin/python -m pytest -q
→ 247 passed, 0 failed, 0 skipped
```

Phase 4 adds 23 tests: workload identity, fairness gates (zero denominator, incomplete assignment,
infeasible layout), hand-calculated factorial effects, headroom, diagnostics categories, routing
policies, deterministic simulation, the end-to-end gate (feasible vs beam-overloaded), regime
reconciliation, and the dashboard contract. No test was skipped or weakened; all 224 Phase 1–3
tests still pass.

## 15. Runtime and resource limitations

| Step | Runtime |
|---|---|
| Phase 4 full run (2 holdout policies + 2 regime scenarios + artifacts) | 33 s |
| One `run_phase6` holdout evaluation | ~7 s |
| Independent verifier | < 1 s |
| Full test suite | ~4–5 min |

No GPU, no network, no external service. The cost is dominated by pairwise Dijkstra distances and
the independent validator, not by simulation.

## 16. Remaining issues

1. **D37 — pick time is per order line, not per stop.** The architecture's target is per stop; Phase
   4 preserves the Phase 2/3 definition so historical comparisons remain valid. Changing it would
   rescale cycle time and throughput and must be a separately validated phase.
2. **One deterministic run per cell.** No seeds, confidence intervals or paired stochastic trials;
   effects are decompositions, not significance tests.
3. **`s_shape` is a node-order simplification**, not a true aisle serpentine over the physical grid.
4. **Regimes B/C are different generators, not resamples.** No seasonality or transition test.
5. **No dashboard view** — `app/phase4_contract.py` is loaded by `load_all()`, but no new Streamlit
   tab renders it.
6. **The optimized layout has almost no structural headroom** (100 % bin weight, 99.93 % volume,
   98–99 % level/beam). Any inventory change requires re-validation.
7. **Demand-weighted line travel is layout-level**, so its policy effect is zero by construction;
   it is reported beside, not instead of, simulator travel.

## 17. Reproduction

```bash
cd /home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting

# build Phase 3 first if outputs/phase3 is absent
.venv/bin/python -m src.experiments.run_phase3

# Phase 4: holdout 2x2 + regimes + headroom + diagnostics + provenance
.venv/bin/python -m src.experiments.run_phase4

# independent recomputation (writes outputs/phase4/verification.json)
.venv/bin/python tools/verify_phase4.py

# Phase 4 tests
.venv/bin/python -m pytest tests/test_phase4_fairness.py tests/test_phase4_contract.py -q
```

Outputs: `outputs/phase4/phase4_experiments.json`, `phase4_cells.csv`, `phase4_effects.csv`,
`phase4_regimes.csv`, `phase4_headroom.csv`, `phase4_diagnostics.json`, `verification.json`,
`provenance.json`, plus per-run `cells/<policy>/` and `regimes/<scenario>/` evaluation artifacts.
The canonical dataset is never written to.
