# Phase 5 — Dashboard Integration, D37 Timing Models, and Paired-Seed Robustness

**Repo:** `/home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting`
**Canonical data:** `/home/hemanth/hackathon/epoch_hackathon/dataset/processed` (read-only)
**Date:** 2026-10-29
**Inputs:** Phase 3 and Phase 4 frozen layouts, split manifest, evaluation summaries, provenance
**Outputs:** `outputs/phase5/`

---

## 1. Scope and starting audit

Phase 5 is a continuation of Phases 3 and 4, not a re-run of them.

### 1.1 What already existed

| Area | State at audit |
|---|---|
| Phase 3 contract | `load_all()["phase3"]` — cells, effects, split, replenishment, sweep, feasibility, provenance |
| Phase 4 contract | `load_all()["phase4"]` — cells, effects, regimes, headroom, diagnostics, verification |
| Dashboard | Streamlit app with six tabs: Overview, Warehouse Layout, Pick Routes, Ergonomics, Exports, Inventory Mgmt |
| Dashboard views of Phase 3/4 | **absent** (D28/D44 remained open) |
| D37 pick-time basis | line-based hard-coded in the simulator; ARCHITECTURE describes per-stop as the target |
| Repeated runs | none; one deterministic result per cell, explicitly not a significance test |

The Phase 3 and Phase 4 artifacts were read, not rebuilt. The split manifest still passes its ten leakage checks, and both frozen layouts still match their recorded SHA-256 hashes.

### 1.2 Gaps addressed

1. A read-only Streamlit view of both contracts.
2. A configurable pick-time basis with a controlled comparison (D37).
3. Five predeclared optimizer seeds, paired against one fixed baseline, with descriptive statistics.
4. Independent verification of the new artifacts.
5. Documentation and build-status updates grounded in the runs.

No Phase 3/4 artifact was overwritten. Phase 5 writes only to `outputs/phase5/`.

---

## 2. Dashboard integration

### 2.1 What was added

A seventh tab, **Experiments**, containing two sub-tabs:

- **Phase 3 — demand metrics**
- **Phase 4 — simulation**

The tab is rendered by `render_experiments()` in `app/dashboard.py`; all shaping happens in `app/phase5_views.py`.

### 2.2 Phase 3 view

Displays, from the contract only:

- experiment ID, baseline variant, scenario, evaluation status, leakage-checked flag;
- A1/B1 demand-weighted travel and the placement effect;
- the four cells of the placement × fragmentation 2×2, with denominator lines and coverage;
- main effects and interaction;
- fit/holdout counts and the ten split checks;
- replenishment trips/travel/bins and the zero-demand rule;
- weight-sweep rows and the fit-based selection note;
- the secondary layout × pick-rule sensitivity **separately** from the primary 2×2;
- provenance and caveat fields.

### 2.3 Phase 4 view

Displays, from the contract only:

- experiment ID, baseline, evaluation status, independent-verification result;
- the four cells of the layout × picking-policy 2×2;
- layout/policy/interaction effects for every published metric;
- A_HOLDOUT, regime B and regime C rows with publishable flags;
- structural headroom by scope, de-duplicated across policies;
- rejection diagnostics and frozen-layout identities;
- workload order/line counts and the caveat.

### 2.4 What the view deliberately does not do

- It does not recompute percentages, averages, effects or headroom. Every displayed number is a contract field.
- It does not merge Phase 3 line travel with Phase 4 route travel; the caption states they are different metrics.
- It does not display a comparison as successful when a cell is infeasible or verification failed.
- It does not turn a missing contract into zero; missing contracts show an explicit warning.

### 2.5 Verification

`tests/test_phase5_dashboard.py` loads the real contracts and checks that:

- A1/B1 values and effects pass through unchanged;
- mutating a contract value changes the rendered value (proving no hidden recomputation);
- missing contracts produce `available=False` and empty tables;
- infeasible cells and failed verification set the blocked flag;
- units and metric labels are explicit;
- headroom has one row per layout/scope;
- the Streamlit app runs with **zero exceptions** and exposes the three new tab labels.

The smoke test uses `streamlit.testing.v1.AppTest` on `app/dashboard.py`. It rendered the full app with no exception.

---

## 3. D37 — pick time per line vs per stop

### 3.1 Definitions

| Model | Pick-time charge | Constant |
|---|---|---|
| `order_line` | every order line in the batch | 8.0 s per line |
| `stop` | every distinct physical bin visited by the batch | 8.0 s per stop |

A **stop** is one distinct bin holding any SKU in the batch. Two lines for the same SKU, or two SKUs in the same bin, share one stop. The route still visits each distinct bin once.

Cycle time is unchanged in form:

```
cycle_time = travel_time + pick_time + setup_time
travel_time = route_distance / 1.3 m/s
setup_time  = 10 s per batch
```

Only `pick_time` changes unit. The per-event constants are separate config fields (`pick_time_sec`, `pick_time_stop_sec`), so the comparison does not hide a multiplier.

### 3.2 Controlled comparison

Same frozen layouts, same A_HOLDOUT workload (1,625 orders / 5,997 lines), same nearest-neighbour policy, same batching, speed, setup and validation gate.

| Layout | Basis | Travel (m) | Pick lines | Pick stops | Pick time (s) | Cycle (s) | Throughput (orders/h) | Time/order (s) |
|---|---|---|---|---|---|---|---|---|
| baseline | order_line | 508,174.8 | 5,997 | 7,712 | 47,976 | 442,129.69 | 13.23 | 272.08 |
| baseline | stop | 508,174.8 | 5,997 | 7,712 | 61,696 | 455,849.69 | 12.83 | 280.52 |
| optimized | order_line | 234,208.0 | 5,997 | 5,963 | 47,976 | 231,386.00 | 25.28 | 142.39 |
| optimized | stop | 234,208.0 | 5,997 | 5,963 | 47,704 | 231,114.00 | 25.31 | 142.22 |

Travel is identical to the tenth of a metre in both bases. Setup time is identical. The change is confined to the pick component.

- Baseline: stop charging costs **+13,720 s (+3.10 %)** because the baseline layout spreads the same 5,997 lines over **7,712** stops.
- Optimized: stop charging saves **−272 s (−0.12 %)** because the optimized layout covers the same lines in **5,963** stops.
- Improvement therefore strengthens under the stop model: cycle **−49.30 %** (vs −47.67 % line), throughput **+97.27 %** (vs +91.08 % line).

### 3.3 Decision

**Authoritative default: `order_line`.**

Reasons:

1. `PROJECT.md` defines the pick cycle as travel + pick + setup but does not define the pick-time unit.
2. Every Phase 2/3/4 cycle-time and throughput figure was produced with the line model. Switching the default would silently rescale historical metrics.
3. The line model charges each pick instruction, which is the safer operational assumption when a picker must scan/confirm every line even at a shared bin.
4. The stop model is implemented and published as a **sensitivity**, not a replacement.

`ARCHITECTURE.md` §10 describes per-stop charging as the target; that remains a design preference, not a specification requirement that overrides comparability. The stop model is now available via `pick_time_basis="stop"` for any future evaluation.

**Consequence for reporting:** travel percentages are unaffected. Cycle/throughput percentages must state their basis; line-based Phase 4 figures remain the comparable series. A stop-based run is not mixed into the Phase 4 table.

---

## 4. Random sources and paired-seed design

### 4.1 Audit

| Source | Random? | Evidence |
|---|---|---|
| Greedy starter | No | velocity-ordered, deterministic tie-breaks |
| Constraint repair | No | deterministic move scan; `already_feasible` on every seed |
| Simulated annealing | **Yes** | `random.Random(seed)` for move selection/acceptance |
| Batching | No | orders sorted by `order_id`, fixed groups of 5 |
| Routing | No | nearest-neighbour / node-order S-shape |
| Simulation | No | no RNG; route sums reproduce byte-for-byte |

Only the annealer is stochastic. The study therefore measures **optimizer variability**, not simulation variability.

### 4.2 Design

- Seeds predeclared: **42, 43, 44, 45, 46**.
- For each seed: fit on `A_FIT` only (same config and weights), validate, hash, freeze, then evaluate the frozen layout on `A_HOLDOUT`.
- Baseline: one fixed `repaired_minimal` layout, reused in every pair.
- Same workload, batching, policy (`nearest_neighbor`), speed, pick-time basis (line) and gate in every pair.
- No seed was selected by holdout performance. No layout was refit after seeing holdout.

### 4.3 Results

| Seed | Status | Layout SHA-256 | Feasible | Units | Travel (m) | Cycle (s) | Throughput | Moves accepted |
|---|---|---|---|---|---|---|---|---|
| 42 | ok | `cafa55e805e8…` | yes | 6,375 | 234,208.0 | 231,386.0 | 25.28 | 43 |
| 43 | ok | `cafa55e805e8…` | yes | 6,375 | 234,208.0 | 231,386.0 | 25.28 | 26 |
| 44 | ok | `cafa55e805e8…` | yes | 6,375 | 234,208.0 | 231,386.0 | 25.28 | 28 |
| 45 | ok | `cafa55e805e8…` | yes | 6,375 | 234,208.0 | 231,386.0 | 25.28 | 30 |
| 46 | ok | `cafa55e805e8…` | yes | 6,375 | 234,208.0 | 231,386.0 | 25.28 | 18 |

- Successful runs: **5/5**; failed: **0/5**.
- Unique layouts: **1**; all hashes equal the Phase 3 optimized layout.
- Every run: 0 violations, 6,375/6,375 units, 0 duplicate SKU-bin pairs.
- Paired travel difference: **−273,966.8 m**, **−53.9119 %**, SD **0.0**, IQR **0.0**.
- Paired cycle difference: **−210,743.69 s**, SD **0.0**.
- Paired throughput difference: **+12.05 orders/h**, SD **0.0**.

The annealer's **search path** varies by seed (18–43 accepted moves), but its **best incumbent** never beats the greedy starter on this instance. The result is therefore deterministic in output even though the optimizer contains randomness.

### 4.4 Statistical statement

Five paired seeds with zero variance do not support a significance claim, and none is made. The correct statement is: on this instance, the optimizer's stochastic component does not change the selected layout or any held-out metric across the five predeclared seeds. This is an **exploratory robustness check**, not a confidence interval.

---

## 5. Safeguards preserved

- Original as-supplied baseline remains infeasible; `repaired_minimal` is still the comparison reference.
- CAT-01 at 10 m and all structural constraints unchanged.
- Every published layout passes the independent validator.
- Inventory: 6,375 units, 1,200 SKUs, zero duplicate pairs.
- Split remains temporal, order-level, 70/30; ten checks pass.
- No holdout data used for fitting, tuning or seed selection.
- Headroom is reported as risk, not relaxed.
- Phase 3/4 artifacts are byte-identical to their pre-Phase-5 versions (hashes recorded).

---

## 6. Reproducibility

```bash
cd /home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting
.venv/bin/python -m src.experiments.run_phase5        # ~4 min 45 s
.venv/bin/python -m src.evaluation.verify_phase5      # independent recomputation
.venv/bin/python -m pytest -q                         # full suite
```

Artifacts:

| Path | Contents |
|---|---|
| `outputs/phase5/phase5_experiments.json` | combined D37 + seed results |
| `outputs/phase5/d37_timing_models.{json,csv}` | per-basis layout metrics |
| `outputs/phase5/d37/<basis>/` | routes, evaluation summary, per-batch CSV |
| `outputs/phase5/paired_seeds.{json,csv}` | per-seed records and descriptive stats |
| `outputs/phase5/seeds/seed_<n>/` | fit summary, layout, holdout evaluation |
| `outputs/phase5/provenance.json` | inputs, config, seeds, output hashes |
| `outputs/phase5/verification.json` | 50 independent checks |

---

## 7. Tests

| Command | Result |
|---|---|
| `pytest tests/test_phase5_d37.py` | 8 passed |
| `pytest tests/test_phase5_dashboard.py` | 11 passed |
| `pytest tests/test_phase5_robustness.py` | 7 passed |
| `pytest tests/test_phase5_*.py` | **26 passed** |
| `pytest -q` (full) | **273 passed / 0 failed / 0 skipped** (243.17 s) |

New tests cover: one line/one stop, multi-line one bin, multi-SKU one bin, multi-bin batch, empty workload, invalid basis, pipeline travel invariance, contract pass-through, mutation/no-recomputation, missing/blocked states, unit labels, headroom de-duplication, seed records, provenance, and the independent verifier.

No existing test was skipped, weakened or deleted.

---

## 8. Limitations

1. **Line-based default is a compatibility choice, not a physical measurement.** No time study supports 8 s/line or 8 s/stop.
2. **Stop definition is batch-local distinct bins.** It does not model pick faces, congestion, or multiple picks at a bin by different pickers.
3. **Five seeds are a small, exploratory sample.** Zero variance means the annealer did not find a better incumbent, not that the layout is optimal.
4. **The annealer's search is weak on this instance** (600 evaluations, 18–43 accepted moves, best = starter). A stronger search could produce seed-dependent layouts.
5. **Simulation remains deterministic and single-scenario per pair.** No stochastic demand, travel-time noise or picker variability.
6. **Dashboard is read-only.** It does not trigger runs or edit weights; that would be a larger redesign.
7. **`s_shape` is still a node-order simplification**, and Phase 4's very low headroom (100 % bin weight) remains a risk.
8. **No statistical significance** is claimed anywhere; the design does not support it.

---

## 9. Comparability with Phases 3 and 4

| Figure | Still comparable? | Condition |
|---|---|---|
| Phase 3 line travel (−48.29 %) | yes | same split, baseline, workload and metric |
| Phase 4 travel (−53.91 %) | yes | same frozen layouts and line-based simulation |
| Phase 4 cycle (−47.67 %), throughput (+91.1 %) | yes | **line-based only**; stop-based values are a separate sensitivity |
| Phase 4 policy effect (+0.09 %) | yes | unchanged |
| Headroom | yes | unchanged layout |

Phase 3 and Phase 4 artifacts were not regenerated, so their published numbers remain exactly as reported. Phase 5 adds a stop-basis sensitivity that must be labelled as such.
