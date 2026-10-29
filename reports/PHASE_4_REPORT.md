# Phase 4 Report — Simulation, evaluation, and controlled experiments

**Date:** 2026-10-29
**Repo:** `/home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting`
**Artifacts:** `outputs/phase4/` · **Detail:** `docs/PHASE_4_SIMULATION_AND_EXPERIMENTS.md`
**Independent verification:** `outputs/phase4/verification.json` (14/14 checks)

---

## Status

**COMPLETE.** The held-out 2×2, demand regimes, fair-comparison gates, operational metrics, headroom,
rejection diagnostics, provenance and independent verifier are implemented and run. The only UI gap is
documented: the Phase 4 contract is loaded by the dashboard data layer, but no new Streamlit tab was built
(the brief permits machine-readable delivery plus a documented UI limitation).

Headline: on the frozen holdout, nearest-neighbour travel falls **508,174.8 → 234,208.0 m = −53.91 %**;
cycle time falls **−47.67 %**; throughput rises **13.23 → 25.28 orders/h (+91.1 %)**. The picking-policy
effect is tiny (**+0.09 % travel** for S-shape), and the interaction (**+561.9 m**) does not change the
conclusion.

## Starting state

Phase 3 left a verified baseline repair, a feasible optimized layout fitted on `A_FIT`, a temporal
fit/holdout split with 10 checks, order-line demand-weighted travel, the placement × fragmentation 2×2,
replenishment, a five-vector weight sweep and provenance. It did **not** evaluate picking policies, publish
cycle time / throughput per cell, evaluate demand regimes, report structural headroom, structure rejection
diagnostics, or independently recompute its summaries. Phase 4 added those without refitting the layout.

## Files changed

| File | Purpose |
|---|---|
| `src/evaluation/fairness.py` *(new)* | Workload SHA-256 identity; explicit fairness/denominator/publication checks |
| `src/evaluation/headroom.py` *(new)* | Per-scope utilization from the validator's own observed/limit checks |
| `src/evaluation/diagnostics.py` *(new)* | Structured rejection categories, affected SKUs/bins, observed vs limit, blocking flag |
| `src/evaluation/factorial.py` *(new)* | Generic 2×2 main effects and difference-in-differences |
| `src/evaluation/verify.py` *(new)* | Independent recomputation of travel, cycle, throughput, effects, inventory, split, headroom, hashes |
| `tools/verify_phase4.py` *(new)* | CLI for the verifier; exits non-zero on failure |
| `src/experiments/run_phase4.py` *(new)* | Holdout 2×2, regimes B/C, headroom, diagnostics, provenance |
| `src/simulation/pipeline.py` | `routing_strategy` / `batch_size`; workload identity, integrity, headroom, diagnostics |
| `src/evaluation/metrics.py` | Publishes pick lines, travel/pick/setup time components |
| `src/experiments/split.py` | `verify_split` accepts a manifest read from disk |
| `app/phase4_contract.py` *(new)*, `app/dashboard_data.py` | Read-only Phase 4 contract, loaded as `load_all()["phase4"]` |
| `tests/test_phase4_fairness.py` *(new)*, `tests/test_phase4_contract.py` *(new)* | 23 Phase 4 tests |
| `docs/PHASE_4_SIMULATION_AND_EXPERIMENTS.md` *(new)* | Full methodology, results, limitations |
| `reports/BUILD_STATUS_REPORT.md`, `ARCHITECTURE.md` | Phase 4 evidence and architecture notes |

## Simulation and metric definitions

```
batches: orders sorted by order_id, groups of 5
route:   depot → distinct bins holding the batch's SKUs → depot
travel:  Σ Dijkstra leg distances over all batches (m)
cycle:   per batch = distance / 1.3 + 8 s × order_lines + 10 s
throughput = total orders / (total cycle / 3600)        (orders/h)
time per order = total cycle / total orders             (s/order)
demand_weighted_depot_distance = Phase 3 Σ depot→bin per order line (m; layout-level)
fragmentation = bins used / SKUs stocked, multi-bin SKUs
replenishment = Phase 3 proxy, 14-day lots, zero-demand SKUs excluded
```

Units, grain and numerator/denominator semantics are documented in the detail report. A missing metric is
reported unavailable or blocks publication; it is never shown as zero. Pick time is per **order line**
(the Phase 2/3 definition); the per-stop target (D37) remains open.

## 2×2 experiment

Layout (`baseline_repaired` vs `optimized_fit`) × picking policy (`nearest_neighbor` vs `s_shape`), same
holdout workload, geometry, inventory, batch size, speed, pick/setup times and validator.

| Cell | Layout | Policy | Feasible | Travel (m) | Cycle (s) | Throughput |
|---|---|---|---|---|---|---|
| A1 | baseline_repaired | nearest_neighbor | ✅ | 508,174.8 | 442,129.7 | 13.23 |
| A2 | baseline_repaired | s_shape | ✅ | 508,355.6 | 442,268.8 | 13.23 |
| B1 | optimized_fit | nearest_neighbor | ✅ | 234,208.0 | 231,386.0 | 25.28 |
| B2 | optimized_fit | s_shape | ✅ | 234,950.7 | 231,957.3 | 25.22 |

| Metric | Layout effect | Policy effect | Interaction |
|---|---|---|---|
| Travel | **−273,685.9 m (−53.86 %)** | +461.8 m (+0.09 %) | +561.9 m |
| Cycle time | **−210,527.6 s (−47.62 %)** | +355.2 s (+0.08 %) | +432.2 s |
| Throughput | **+12.02 orders/h (+90.85 %)** | −0.03 (−0.23 %) | −0.06 |
| Time per order | −129.56 s (−47.62 %) | +0.22 s (+0.08 %) | +0.26 s |
| Demand-weighted travel | −242,232.5 m (−48.29 %) | 0 (layout metric) | 0 |
| Replenishment travel | −258,427.2 m (−40.34 %) | 0 (layout metric) | 0 |

All effects are deterministic decompositions of one workload, not significance tests.

## Held-out evaluation

Phase 3 split reused byte-for-byte: fit 3,790 orders / 14,003 lines; holdout 1,625 / 5,997. Ten checks pass;
both layouts frozen by SHA-256 before evaluation; no refit or retune.

| Metric (A_HOLDOUT, NN) | Baseline | Optimized | Change |
|---|---|---|---|
| Travel | 508,174.8 m | 234,208.0 m | **−53.91 %** |
| Cycle time | 442,129.7 s | 231,386.0 s | −47.67 % |
| Throughput | 13.23 orders/h | 25.28 orders/h | +91.1 % |
| Demand-weighted travel | 501,569.0 m | 259,336.6 m | −48.29 % |
| Replenishment travel | 640,634.9 m | 382,207.7 m | −40.34 % |

Under S-shape the direct travel change is −53.78 %, so the policy does not change the verdict.

## Demand regimes

Defined before evaluation from the dataset's generators; B/C were never used for fitting.

| Regime | Orders | Lines | Units | Top-10 % share | Baseline travel | Optimized travel | Change |
|---|---|---|---|---|---|---|---|
| A_HOLDOUT | 1,625 | 5,997 | 9,626 | 58.62 % | 508,174.8 m | 234,208.0 m | **−53.91 %** |
| B (flat) | 5,420 | 20,000 | 32,080 | 15.41 % | 1,834,069.9 m | 1,222,102.9 m | **−33.37 %** |
| C (clustered) | 5,409 | 20,000 | 32,008 | 15.39 % | 1,653,629.4 m | 955,970.4 m | **−42.19 %** |

Throughput changes: A +91.1 %, B +42.3 %, C +59.2 %. The gain persists everywhere; it is strongest on the
concentrated, smaller holdout. B/C are different synthetic generators, not resamples.

## Weight sensitivity

Phase 3's five-vector sweep is reused; selected config **default** (α=1.0, β=0.4, γ=0.3, δ=0.2, ε=0.0) and
its SHA-256 matches the frozen layout (`selected_matches_frozen_layout: true`).

| Config | Fit feasible | Fit demand-weighted T | Holdout T | Layout SHA (12) |
|---|---|---|---|---|
| default | ✅ | 588,046.5 | 259,336.6 | `cafa55e805e8` |
| travel_only | ✅ | 588,046.5 | 259,336.6 | `cafa55e805e8` |
| affinity_heavy | ✅ | 588,046.5 | 259,336.6 | `cafa55e805e8` |
| ergonomics_heavy | ✅ | 588,046.5 | 259,336.6 | `cafa55e805e8` |
| replenishment_heavy (ε=0.5) | ✅ | 588,055.8 | 259,612.6 | `b4a17623c358` |

Four vectors produce one layout; ε=0.5 trades −0.025 % restock travel for +0.107 % holdout pick travel.
Selection used fit demand-weighted travel, never the holdout.

## Safety and diagnostics

All four cells and all three regimes: **0 hard violations**, 6,375/6,375 units, 100 % assignment
completeness. Headroom on the optimized layout:

| Scope | Max utilization | ≥95 % of checks | Limiting record |
|---|---|---|---|
| Bin weight | **100.00 %** | 0.543 % | `LOC002120` |
| Bin volume | **99.93 %** | 1.008 % | `LOC000193` |
| Shelf level | **98.06 %** | 1.488 % | `R5-3-1` level 1 |
| Beam | **98.76 %** | 0.754 % | `R5-3-1` bay 0 level 1 |
| Rack | 69.36 % | 0 % | `R5-3-3` |

Feasible but nearly full: any inventory change requires re-validation. The Phase 2 report's 99.37 % beam /
99.56 % level figures belonged to an earlier optimized artifact; the frozen Phase 3 layout measures
98.76 % / 98.06 %. No 95 % placement target was introduced.

Diagnostics expose category, affected SKUs/bins, observed vs limit and a blocking flag. A deliberate
beam-overloaded baseline produces `BLOCKED_INFEASIBLE_LAYOUT`, an empty comparison table and
`publishable: false`; it is never converted into a zero-travel result.

## Test results

```
.venv/bin/python -m pytest tests/test_phase4_fairness.py tests/test_phase4_contract.py -q
→ 23 passed

.venv/bin/python -m pytest -q
→ 247 passed, 0 failed, 0 skipped
```

No test skipped, weakened or removed. All 224 Phase 1–3 tests still pass. The independent verifier reports
**14/14 checks passed** (travel/cycle/throughput recomputation, cycle identity, effects, split, inventory,
regime counts, headroom, provenance hashes).

## Benchmark results

| Item | Value |
|---|---|
| Baseline variant | `repaired_minimal` (1,071 → 0 CAT-01, objective disabled during repair) |
| Workload | A holdout, 1,625 orders / 5,997 lines / 9,626 units |
| Baseline travel | 508,174.8 m |
| Optimized travel | **234,208.0 m** |
| Change | **−273,966.8 m = −53.91 %** |
| Cycle time | 442,129.7 → 231,386.0 s (−47.67 %) |
| Throughput | 13.23 → 25.28 orders/h (+91.1 %) |
| Demand-weighted (Phase 3) | 501,569.0 → 259,336.6 m (−48.29 %) |
| Replenishment (Phase 3) | 640,634.9 → 382,207.7 m (−40.34 %) |
| Hard constraints | 0 violations in every cell/regime |
| Inventory | 6,375 = 6,375; 0 duplicate pairs; 0 unplaced |
| Layout hashes | baseline + optimized frozen by SHA-256 |
| Verification | 14/14 independent checks |
| Runtime | Phase 4 run 33 s; suite ~4 min |

## Remaining blockers

1. **D37 — pick time per line, not per stop.** Preserved for comparability; changing it rescales cycle
   time/throughput and needs its own validated phase.
2. **One deterministic run per cell** — no seeds, confidence intervals or paired stochastic trials.
3. **`s_shape` is a node-order simplification**, not a full physical aisle serpentine.
4. **Regimes B/C are different generators**, not resamples; no seasonality/transition test.
5. **No dashboard view** — contract loaded, UI not built.
6. **Very low structural headroom** — 100 % bin weight, 99.93 % volume, 98–99 % level/beam.
7. **Demand-weighted line travel is policy-invariant** — reported beside simulator travel, not instead of it.

## Phase 5 readiness

**Yes for the Phase 4 scope.** Identical-workload comparisons, independent feasibility, the four-cell 2×2,
held-out and regime evaluation, weight reuse, headroom, diagnostics, machine-readable outputs and independent
verification are all evidenced. Phase 5 should: render the Phase 4 contract in a dashboard view; decide
whether to move pick time to the per-stop basis; and add repeated paired-seed runs if uncertainty estimates
are wanted. Until then, the −53.91 % result is a deterministic held-out comparison, not a significance claim.
