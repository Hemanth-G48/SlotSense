# Phase 5 Report — Dashboard Integration, D37 Timing Models, and Paired-Seed Robustness

**Status: COMPLETE**
**Date:** 2026-10-29
**Repo:** `/home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting`
**Canonical data:** `/home/hemanth/hackathon/epoch_hackathon/dataset/processed` (read-only)
**Methodology:** `docs/PHASE_5_DASHBOARD_AND_ROBUSTNESS.md`
**Artifacts:** `outputs/phase5/`

---

## 1. Summary

Phase 5 delivered three things that Phases 3 and 4 left open:

1. **A read-only Streamlit view** of the existing Phase 3 and Phase 4 contracts (D28/D44 partial).
2. **A configurable pick-time basis** with a controlled line-vs-stop comparison (D37).
3. **Five predeclared paired-seed runs** measuring optimizer variability, with zero observed variance.

The Phase 3 and Phase 4 artifacts were not regenerated or modified. Every comparison uses the frozen
`repaired_minimal` baseline, the frozen optimized layout, the A_HOLDOUT workload, CAT-01 at 10 m and the
independent validator.

---

## 2. Dashboard

### Views added

A seventh top-level tab, **Experiments**, with two sub-tabs:

- **Phase 3 — demand metrics:** cells, effects, split, replenishment, weight sweep, secondary pick-rule
  sensitivity, provenance.
- **Phase 4 — simulation:** cells, layout/policy effects, regimes A/B/C, headroom, diagnostics,
  verification, workload/layout identity.

All values are selected from `load_all()["phase3"]` / `load_all()["phase4"]` by
`app/phase5_views.py`. The view performs no arithmetic on experimental metrics; percentage changes and
effects come from the contract's own fields.

### Guardrails

- Missing contract → explicit warning, empty tables.
- Infeasible cell or failed verification → blocked flag and error banner.
- Phase 3 line travel and Phase 4 route travel are labelled as different metrics and never combined.
- Headroom is shown as risk, not a target.

### Evidence

`tests/test_phase5_dashboard.py` — 11 tests, including a full `streamlit.testing.v1.AppTest` run of
`app/dashboard.py` with **zero exceptions** and the expected tab labels.

The existing `tests/test_phase7_dashboard.py` asserted `len(at.tabs) == 9`; the new nested tabs changed that
count. It now asserts the required top-level and sub-tab labels instead — a deliberate update for the new
view, not a relaxed check.

---

## 3. D37 — pick time per line vs per stop

### Definitions

| Basis | Charge | Constant |
|---|---|---|
| `order_line` | every order line in a batch | 8.0 s/line |
| `stop` | every distinct bin visited by a batch | 8.0 s/stop |

A stop is one distinct bin holding any SKU in the batch; multiple lines or SKUs at the same bin share it.
`cycle = travel_time + pick_time + setup_time`; travel and setup are unchanged.

### Measured impact (A_HOLDOUT, nearest-neighbour, frozen layouts)

| Layout | Basis | Travel (m) | Lines | Stops | Cycle (s) | Throughput | Time/order (s) |
|---|---|---|---|---|---|---|---|
| baseline | line | 508,174.8 | 5,997 | 7,712 | 442,129.69 | 13.23 | 272.08 |
| baseline | stop | 508,174.8 | 5,997 | 7,712 | 455,849.69 | 12.83 | 280.52 |
| optimized | line | 234,208.0 | 5,997 | 5,963 | 231,386.00 | 25.28 | 142.39 |
| optimized | stop | 234,208.0 | 5,997 | 5,963 | 231,114.00 | 25.31 | 142.22 |

- Travel: **identical** in both bases.
- Baseline stop charging: **+13,720 s (+3.10 %)** — 7,712 stops exceed 5,997 lines.
- Optimized stop charging: **−272 s (−0.12 %)** — 5,963 stops are fewer than 5,997 lines.
- Improvement under stop basis: cycle **−49.30 %**, throughput **+97.27 %**.
- Improvement under line basis: cycle **−47.67 %**, throughput **+91.08 %**.

### Decision

**`order_line` remains the authoritative default; `stop` is a configurable sensitivity.**

`PROJECT.md` does not define the pick-time unit, and every Phase 2/3/4 cycle/throughput figure is line-based.
Switching the default would silently rescale the historical series. The stop model is now available via
`pick_time_basis="stop"` and documented as a sensitivity. Travel conclusions are unaffected; cycle/throughput
claims must state their basis.

D37 is closed in the architecture register with this compatibility default.

---

## 4. Paired-seed robustness

### Random sources

Only simulated annealing uses randomness (`random.Random(seed)`). The greedy starter, repair, batching,
routing and simulation are deterministic. The study therefore measures **optimizer variability only**.

### Design

- Seeds: **42, 43, 44, 45, 46** (predeclared).
- Fit on `A_FIT`, validate, hash, freeze; evaluate the frozen layout on `A_HOLDOUT`.
- One fixed `repaired_minimal` baseline reused across pairs.
- Same workload, policy, batch size, speed, pick-time basis and gate.
- No seed selected by holdout performance; no refit after holdout.

### Results

| Seed | Feasible | Units | Travel (m) | Cycle (s) | Throughput | Moves accepted | Layout hash |
|---|---|---|---|---|---|---|---|
| 42 | yes | 6,375 | 234,208.0 | 231,386.0 | 25.28 | 43 | `cafa55e805e8…` |
| 43 | yes | 6,375 | 234,208.0 | 231,386.0 | 25.28 | 26 | `cafa55e805e8…` |
| 44 | yes | 6,375 | 234,208.0 | 231,386.0 | 25.28 | 28 | `cafa55e805e8…` |
| 45 | yes | 6,375 | 234,208.0 | 231,386.0 | 25.28 | 30 | `cafa55e805e8…` |
| 46 | yes | 6,375 | 234,208.0 | 231,386.0 | 25.28 | 18 | `cafa55e805e8…` |

- **5/5 successful**, 0 failed.
- **1 unique layout**, identical to the Phase 3 optimized layout.
- 0 violations, 6,375/6,375 units, 0 duplicate SKU-bin pairs in every run.
- Paired travel difference: **−273,966.8 m / −53.9119 %**, SD **0.0**, IQR **0.0**.
- Paired cycle difference: **−210,743.69 s**, SD **0.0**.
- Paired throughput difference: **+12.05 orders/h**, SD **0.0**.

The annealer's search path varies (18–43 accepted moves), but its best incumbent never beats the greedy
starter on this instance. The output is deterministic despite a stochastic component.

**No significance test is claimed.** Five paired seeds with zero variance are an exploratory robustness
check, not a confidence interval.

---

## 5. Safeguards

- Original as-supplied baseline remains infeasible; `repaired_minimal` is the comparison reference.
- CAT-01 at 10 m and every structural constraint unchanged.
- Independent validator passed every published layout.
- Inventory conserved: 6,375 units / 1,200 SKUs / 0 duplicates.
- Split unchanged: temporal, order-level, 70/30; ten checks pass.
- No holdout leakage into fitting, tuning or seed selection.
- Structural headroom unchanged and reported as risk (bin weight 100 %, volume 99.93 %).

---

## 6. Files changed

### New

| Path | Purpose |
|---|---|
| `src/experiments/run_phase5.py` | D37 comparison + paired-seed runner; writes `outputs/phase5/` |
| `src/evaluation/verify_phase5.py` | Independent recomputation of D37, seeds, hashes (50 checks) |
| `app/phase5_views.py` | Pure contract-to-table shaping for the dashboard |
| `tests/test_phase5_d37.py` | 8 timing-model tests |
| `tests/test_phase5_dashboard.py` | 11 contract/UI tests |
| `tests/test_phase5_robustness.py` | 7 artifact/verifier tests |
| `docs/PHASE_5_DASHBOARD_AND_ROBUSTNESS.md` | methodology and results |
| `outputs/phase5/**` | D37, seed, provenance and verification artifacts |

### Modified

| Path | Change |
|---|---|
| `src/simulation/simulator.py` | `pick_time_basis`, `pick_time_stop_sec`, explicit `n_pick_lines` / `n_pick_stops`; summary no longer derives lines from pick time |
| `src/simulation/pipeline.py` | `pick_time_basis` parameter, validation, published basis and per-stop constant |
| `src/evaluation/metrics.py` | publishes `total_pick_stops` and `pick_time_basis` |
| `app/dashboard.py` | imports the view module; adds the Experiments tab; read-only renderer |
| `tests/test_phase7_dashboard.py` | replaces brittle tab-count assertion with required labels |
| `README.md` | seven tabs, Experiments view |
| `ARCHITECTURE.md` | D37 closed; pick-time basis documented; backlog 31 open / 17 closed |
| `reports/BUILD_STATUS_REPORT.md` | Phase 5 verdict and evidence |

Phase 3/4 code, layouts, metrics and artifacts were not modified.

---

## 7. Tests

| Command | Result |
|---|---|
| `.venv/bin/python -m pytest tests/test_phase5_d37.py -q` | **8 passed** |
| `.venv/bin/python -m pytest tests/test_phase5_dashboard.py -q` | **11 passed** |
| `.venv/bin/python -m pytest tests/test_phase5_robustness.py -q` | **7 passed** |
| `.venv/bin/python -m pytest -q` | **273 passed / 0 failed / 0 skipped** (243.17 s) |
| `.venv/bin/python -m src.evaluation.verify_phase5` | **50/50 checks passed** |

No test was skipped or removed. The only test edit outside Phase 5 files replaces a hard-coded tab count
with assertions on the required tab labels.

---

## 8. Reproduction

```bash
cd /home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting
.venv/bin/python -m src.experiments.run_phase5     # 4 min 46 s
.venv/bin/python -m src.evaluation.verify_phase5   # 50 checks
.venv/bin/python -m pytest -q                      # 4 min 18 s
```

The runner refuses to start if the Phase 3 split checks fail or a frozen layout is missing. It reads
`outputs/phase3/` and `outputs/phase4/` but writes only under `outputs/phase5/`.

---

## 9. Remaining gaps

1. **D37 physical calibration** — 8 s/line and 8 s/stop are assumptions; no time study.
2. **Five seeds, zero variance** — the annealer is weak on this instance (600 evaluations; best = starter); a
   stronger search could produce seed-dependent layouts.
3. **Simulation remains deterministic** — no demand, travel-time or picker variability.
4. **Dashboard is read-only** — no run triggering, weight editing or segment filters (D28 remains open).
5. **D44 remains open** — no run registry or segment-level rows beyond the experiment views.
6. **Very low structural headroom** — bin weight 100 %, volume 99.93 %; any inventory change needs validation.
7. **`s_shape`** remains a node-order simplification; regimes B/C remain different generators.
8. **D13 remains the P0** — a clean-checkout `run-all` reproduction is still the gate for calling every figure
   fully reproduced.

---

## 10. Benchmark interpretation

- Phase 3 line travel **−48.29 %** remains valid and comparable.
- Phase 4 travel **−53.91 %**, cycle **−47.67 %**, throughput **+91.1 %** remain valid **under the line basis**.
- The stop-basis sensitivity gives cycle **−49.30 %** and throughput **+97.27 %**; it must be labelled, not
  substituted into the Phase 4 series.
- The five seeds reproduce the Phase 4 optimized layout byte-for-byte; no new performance claim is introduced.
- No statistical significance, causality or optimality claim is made.
