# Phase 3 & Phase 4 — Combined Report

**Project:** Smart Warehouse Slotting & Optimization Engine
**Repo:** `/home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting`
**Date:** 2026-10-29
**Detailed reports:** `reports/PHASE_3_REPORT.md`, `reports/PHASE_4_REPORT.md`
**Methodology:** `docs/PHASE_3_EXPERIMENTS_AND_DEMAND_METRICS.md`, `docs/PHASE_4_SIMULATION_AND_EXPERIMENTS.md`

---

## Status

| Phase | Status | Core outcome |
|---|---|---|
| **Phase 3** — demand-aware metrics, placement vs fragmentation, fit/holdout, replenishment, weight sweep, provenance | **COMPLETE** | Held-out quantity-aware travel **−48.29 %**; placement effect **−48.88 %**, fragmentation effect **+0.58 %** |
| **Phase 4** — simulation, layout × picking-policy 2×2, demand regimes, headroom, diagnostics, independent verification | **COMPLETE** | Held-out simulator travel **−53.91 %**, cycle time **−47.67 %**, throughput **+91.1 %**; policy effect only **+0.09 %** |

Both phases preserve the Phase 2 hard-constraint guarantees: every publishable layout passes the independent validator with **0 violations**, **6,375/6,375 units**, and **100 % assignment completeness**.

---

## Phase 3 — what was built

Phase 3 moved evaluation from record-based accounting to **order-line** demand-weighted travel and separated placement from fragmentation.

### Metric contract

```
T(line) = Σ depot→bin Dijkstra distances for the stops that line causes
demand_weighted_depot_distance = Σ T(line) over resolved lines
  numerator   = total metres
  denominator = resolved order lines (5,997/5,997; coverage 100 %)
mean_per_line_m = numerator / denominator
```

The optimizer's internal `D = Σ demand_frequency × distance` over assignment records remains a separate field (`objective.components.D_travel`); it is never substituted for the published line metric.

### Placement × fragmentation 2×2 (holdout, quantity-aware)

| Cell | Placement | Fragmentation | Feasible | Bins | Travel (m) |
|---|---|---|---|---|---|
| A1 | baseline_repaired | as_is | ✅ | 1,425 | 501,569.0 |
| A2 | baseline_repaired | min_bins | ✅ | 1,274 | 507,390.7 |
| B1 | optimized_fit | as_is | ✅ | 1,290 | 259,336.6 |
| B2 | optimized_fit | min_bins | ✅ | 1,271 | 259,300.7 |

- Placement effect: **−245,161.3 m (−48.88 %)**
- Fragmentation effect: **+2,892.9 m (+0.58 %)** — consolidation alone does not reduce travel
- Interaction: **−5,857.6 m**
- Under `all_bins`, fragmentation is **−87,475.3 m (−12.59 %)** — a bin-count effect exists only where every bin is charged

The earlier “54 % fragmentation” claim was retracted: it came from the pick-rule sensitivity design, not a fragmentation treatment.

### Fit/holdout and replenishment

- Temporal, order-level 70/30 split: fit **3,790 orders / 14,003 lines / 1,103 SKUs**; holdout **1,625 / 5,997 / 899**.
- Ten leakage checks pass, including line-union completeness and no duplicate order-SKU lines.
- Replenishment proxy (14-day lots, zero-demand SKUs excluded): **640,634.9 → 382,207.7 m = −40.34 %** on holdout.
- `ε·Ψ_R` objective term implemented; `epsilon` defaults to 0.0, reproducing Phase 2.

### Weight sensitivity

Five vectors; four produce one identical layout, `ε=0.5` produces a second that trades −0.025 % restock travel for +0.107 % holdout pick travel. Selection used fit demand-weighted travel; default retained.

### Phase 3 tests

Phase 3 targeted: **43 passed**. Full suite at that point: **224 passed / 0 failed / 0 skipped**.

---

## Phase 4 — what was added

Phase 4 separates layout quality from picking policy and adds operational simulation, regimes, headroom and independent verification.

### Simulation definitions

```
batches: orders sorted by order_id, groups of 5
route:   depot → distinct bins holding the batch's SKUs → depot
travel:  Σ Dijkstra leg distances over all batches (m)
cycle:   per batch = distance / 1.3 + 8 s × order_lines + 10 s
throughput = orders / (total cycle / 3600)   (orders/h)
time per order = total cycle / total orders  (s/order)
```

Pick time remains per order line (the Phase 2/3 definition); the per-stop target (D37) remains open.

### Layout × picking-policy 2×2 (holdout)

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

Direct nearest-neighbour holdout: **−53.91 % travel**, **−47.67 % cycle time**, **+91.1 % throughput**. S-shape changes travel by only +0.09 %, so the conclusion is about placement, not routing.

### Held-out demand regimes

| Regime | Orders | Lines | Units | Top-10 % share | Baseline travel | Optimized travel | Change |
|---|---|---|---|---|---|---|---|
| A_HOLDOUT | 1,625 | 5,997 | 9,626 | 58.62 % | 508,174.8 m | 234,208.0 m | **−53.91 %** |
| B (flat) | 5,420 | 20,000 | 32,080 | 15.41 % | 1,834,069.9 m | 1,222,102.9 m | **−33.37 %** |
| C (clustered) | 5,409 | 20,000 | 32,008 | 15.39 % | 1,653,629.4 m | 955,970.4 m | **−42.19 %** |

B/C were never used for fitting; they are different synthetic demand generators, not resamples.

### Structural headroom (optimized layout)

| Scope | Max utilization | ≥95 % of checks | Limiting record |
|---|---|---|---|
| Bin weight | **100.00 %** | 0.543 % | `LOC002120` |
| Bin volume | **99.93 %** | 1.008 % | `LOC000193` |
| Shelf level | **98.06 %** | 1.488 % | `R5-3-1` level 1 |
| Beam | **98.76 %** | 0.754 % | `R5-3-1` bay 0 level 1 |
| Rack | 69.36 % | 0 % | `R5-3-3` |

Feasible but nearly full: any inventory change requires fresh validation.

### Independent verification

`tools/verify_phase4.py` recomputes route sums, cycle identity, throughput, percentage changes, 2×2 effects, inventory conservation, split integrity, regime counts, headroom and provenance hashes: **14/14 checks passed**.

### Phase 4 tests

Phase 4 targeted: **23 passed**. Full suite: **247 passed / 0 failed / 0 skipped**.

---

## Combined benchmark

| Item | Phase 3 (line metric) | Phase 4 (simulation, NN) |
|---|---|---|
| Baseline variant | `repaired_minimal` | `repaired_minimal` |
| Workload | A holdout, 5,997 lines | A holdout, 1,625 orders / 5,997 lines |
| Baseline travel | 501,569.0 m (line metric) | 508,174.8 m (batch tours) |
| Optimized travel | 259,336.6 m | 234,208.0 m |
| Change | **−48.29 %** | **−53.91 %** |
| Cycle time | not re-derived in Phase 3 | 442,129.7 → 231,386.0 s (**−47.67 %**) |
| Throughput | not re-derived in Phase 3 | 13.23 → 25.28 orders/h (**+91.1 %**) |
| Replenishment | 640,634.9 → 382,207.7 m (**−40.34 %**) | same layout-level metric |
| Hard constraints | 0 violations, all cells | 0 violations, all cells/regimes |
| Inventory | 6,375 = 6,375 | 6,375 = 6,375 |
| Independent checks | — | 14/14 |

The two travel percentages are **different metrics**: Phase 3 sums depot→bin distance per order line; Phase 4 sums actual batch tour legs. They are not interchangeable.

---

## Remaining blockers

1. **D37 — pick time per line, not per stop.** Preserved for Phase 2/3 comparability; changing it rescales cycle time and throughput.
2. **One deterministic run per configuration** — no seeds, confidence intervals or paired stochastic trials.
3. **`s_shape` is a node-order simplification**, not a full physical aisle serpentine.
4. **Regimes B/C are different generators**, not resamples; no seasonality or transition test.
5. **No dashboard view** — `load_all()["phase3"]` and `load_all()["phase4"]` expose contracts, but no new Streamlit tabs render them.
6. **Very low structural headroom** — 100 % bin weight, 99.93 % volume, 98–99 % level/beam.
7. **Demand-weighted line travel is policy-invariant** — reported beside, not instead of, simulator travel.

---

## Artifacts

- **Phase 3:** `outputs/phase3/phase3_experiments.json`, `phase3_cells.csv`, `phase3_fragmentation.csv`, `phase3_replenishment.csv`, `phase3_sweep.csv`, `provenance.json`, per-line travel audits.
- **Phase 4:** `outputs/phase4/phase4_experiments.json`, `phase4_cells.csv`, `phase4_effects.csv`, `phase4_regimes.csv`, `phase4_headroom.csv`, `phase4_diagnostics.json`, `verification.json`, `provenance.json`, per-policy/per-regime evaluation artifacts.

Both phases are deterministic, held-out where claimed, and free of statistical-significance or real-world-savings claims.
