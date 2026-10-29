# Phase 6 Report — Clean Reproducibility, Optimizer Effectiveness & Simulation Validity

**Status: PARTIALLY COMPLETE** — D13, optimizer, simulation, capacity and regression criteria are
implemented and independently verified; dashboard/experiment management remains partial (D28/D44).
**Date:** 2026-10-29
**Repo:** `/home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting`
**Dataset:** `/home/hemanth/hackathon/epoch_hackathon/dataset/processed` (read-only)
**Entry point:** `./run-all`
**Artifacts:** `outputs/phase6/runs/<run_id>/`

---

## 1. Baseline state before changes

| Item | Finding |
|---|---|
| Version control | **No Git repository** at the checkout or any parent directory |
| Reproduction entry point | **Absent** — no root `run-all`, no Makefile, no `pyproject.toml` |
| Dependency manager | `uv` 0.11.14, Python 3.14.4, `requirements.txt` only |
| Tests before Phase 6 | **273 passed / 0 failed / 0 skipped** |
| Phase 5 verifier | **50/50 checks passed** |
| Phase 5 seed finding | 5 seeds, 1 unique layout, starter == final objective **625,551.4241** |
| Frozen optimized layout | `cafa55e805e817306913186d92889801728a30a3012ffa9a1722e27c3003bd6b` |
| Canonical inventory | 6,375 units, 1,200 SKUs, 0 duplicate SKU-bin pairs |

D13 was open for a concrete reason, not a documentation gap: no single command regenerated the evidence chain, and the existing `app/main.py` pipeline wrote to the shared `outputs/` tree.

---

## 2. Requirements audited

| Requirement | Original status | Phase 6 result |
|---|---|---|
| D13 clean-checkout reproduction | OPEN | **implemented and verified in a fresh Git clone** |
| Optimizer effectiveness | unexplained (seeds identical) | **defect found and fixed; search limits explained** |
| Simulation validity | assumed | **hand-calculated fixtures pass; `s_shape` limitation documented** |
| Capacity safety | 100 % bin weight, 99.93 % volume | **perturbations fail safely; no target invented** |
| Dashboard/experiment management | D28/D44 open | **run registry added; launch/edit/segment filters remain open** |
| Regression safety | 273 passing | **294 passing in the isolated chain** |

---

## 3. Changes

### 3.1 Reproducibility

| File | Change |
|---|---|
| `run-all` | shell entry point |
| `tools/run_all.py` | preflight, isolated artifacts, stage logs, failure propagation, manifest, latest pointer |
| `tools/verify_phase6.py` | independent 27-check run verification |
| `app/main.py` | `OUTPUT_ROOT` env; isolated optimized path passed to simulation |
| `app/dashboard_data.py` | `OUTPUTS_DIR` env |
| `src/experiments/run_phase4.py` | `PHASE3_DIR` env |
| `src/experiments/run_phase5.py` | `PHASE3_DIR`, `PHASE4_DIR` env |
| `src/evaluation/verify.py` | derives Phase 3/dataset paths from the artifact, not the conventional output layout |
| `docs/PHASE_6_REPRODUCIBILITY.md` | setup, stages, isolation, failure behavior, clean-room procedure |

### 3.2 Optimizer

**Defect found:** `_random_neighbor()` returned `None` for **any layout with fewer than two assignment records**. The guard was intended to protect the swap operator, but it also disabled relocation, so a one-record layout could never move to a better bin.

**Fix:** swap requires ≥2 records; relocation works for one. RNG call order for layouts with ≥2 records is unchanged, preserving frozen Phase 2–5 comparability.

**Test:** `tests/test_phase6_optimizer.py` — 4 passed; hand fixture moves `L_FAR` → `L_NEAR`, score 1000.398 → 100.398.

### 3.3 Simulation

No production timing or routing change. Added `tests/test_phase6_simulation.py` (5 tests) with hand-calculated route/cycle values independent of production functions.

### 3.4 Capacity

`tools/capacity_perturbation.py` and `tests/test_phase6_capacity.py` (3 tests). No target added; the gate remains the validator.

### 3.5 Dashboard

`app/phase6_registry.py` plus a read-only **Phase 6 reproducibility runs** expander in the existing Experiments tab. `tests/test_phase6_registry.py` (3 tests).

---

## 4. Experiments and results

### 4.1 Optimizer audit

**Hand fixture**

| Item | Value |
|---|---|
| Start | `L_FAR`, score 1000.398148 |
| Refined | `L_NEAR`, score 100.398148 |
| Improved | **true** |
| Feasible | **true** |

**Canonical A_FIT probe** (seed 42, 600 sampled neighbours)

| Metric | Value |
|---|---|
| Starter objective | 625,551.424114 |
| Starter feasible | true |
| Assignment records | 1,290 |
| Independent `D_travel` | 622,468.975 |
| Objective `D_travel` | 622,468.975 |
| `D` matches independent | **true** |
| Feasible neighbours | 270 / 600 |
| Invalid or infeasible | 330 / 600 |
| Improving neighbours | **2 / 600** |
| Best improvement | **−0.0704** (0.000011 %) |
| `_refine` final objective | 625,551.424114 |
| `_refine` delta | 0.0 |
| Layout changed | false |

**Interpretation:** the annealer is capable of improving a layout (hand fixture), but the canonical greedy starter is already at a local optimum under the objective: only 2/600 random neighbours improved at all, and the best was 0.07 objective units. The search is not broken; its random relocation/swap neighbourhood has low yield, and the objective weights are connected (Phase 3's ε=0.5 layout differs). No improvement is forced and no global-optimality claim is made.

### 4.2 Simulation fixtures

| Fixture | Expected | Result |
|---|---|---|
| Two-stop tour | 5 + 10 + 6 = 21 m; cycle 21/1.3 + 16 + 10 s | pass |
| Three lines, one bin | 24 s line, 8 s stop; 10 m tour | pass |
| Throughput identity | orders / (cycle/3600) | pass |
| Missing assignment | 2 lines, 1 stop, no invented travel | pass |
| Empty workload | zeros + basis | pass |

### 4.3 Capacity perturbation

| Scope | Location | Observed | +1 unit result |
|---|---|---|---|
| Bin weight | `LOC002120` | 30/30 kg (100 %) | `LD-01` 40 kg > 30 kg; `SL-01` 86.5 > 86.4 kg |
| Bin volume | `LOC000193` | 107,923.2/108,000 cm³ (99.93 %) | `VD-01` 161,885 > 108,000 cm³ |

Inventory-only change fails `INV-02`. Baseline layout is feasible with 0 violations and 6,375 units. The hard gate, not a dashboard warning, rejects the perturbation.

### 4.4 D37 and seeds (reused, not redefined)

- D37 travel identical across line/stop bases; stop basis cycle **−49.30 %**, throughput **+97.27 %**; line basis remains the default.
- Five seeds, one unique layout, zero variance in paired travel/cycle/throughput; the annealer's accepted-move path varies but its incumbent does not.

---

## 5. Run results

*Both runs below passed; their manifests and logs are the evidence. A run is not called PASS until
`verification.json` says so.*

| Run | Status | Stages | Tests | Phase 6 verifier |
|---|---|---|---|---|
| `phase6-dev-05` | **PASS** | 10/10 | **294 passed / 0 failed / 0 skipped** (266 s) | **27/27 checks** |
| `clean-01` | **PASS** | 10/10 | **294 passed / 0 failed / 0 skipped** (247 s) | **27/27 checks** |

`clean-01` ran in a fresh Git clone of the Phase 6 source snapshot (`8df87d5`, clean worktree) with a
fresh virtualenv and no `outputs/`. It took **35 min 50 s**, including all five Phase 3 sweep fits, five
Phase 5 seed fits, the full suite, audits and the Phase 6 verifier. The run is copied to
`outputs/phase6/runs/clean-01/`; the dataset manifest is `28abd23eb798c8f8…` over 13 files.

---

## 6. Test results

| Command | Result |
|---|---|
| `pytest tests/test_phase6_*.py -q` | **27 passed** (includes pre-existing Phase 6 evaluation tests) |
| Full suite in isolated chain | **294 passed / 0 failed / 0 skipped** |
| Phase 4 verifier | **14/14** |
| Phase 5 verifier | **50/50** |

No test was deleted, skipped or weakened. `tests/test_phase7_dashboard.py` and `tests/test_phase9_dashboard_data.py` were made run-directory aware, not relaxed.

---

## 7. Classification

| Criterion | Classification |
|---|---|
| D13 clean-checkout reproduction | **IMPLEMENTED AND INDEPENDENTLY VERIFIED** (fresh Git clone, clean worktree, 10/10 stages, 27/27) |
| Optimizer effectiveness | **IMPLEMENTED AND INDEPENDENTLY VERIFIED** (defect fixed; objective audited) |
| Simulation validity | **IMPLEMENTED AND INDEPENDENTLY VERIFIED** (fixtures) |
| Capacity safety | **IMPLEMENTED AND INDEPENDENTLY VERIFIED** (perturbations + gate) |
| Dashboard/experiment management | **PARTIALLY IMPLEMENTED** (registry; no launch/edit/segment filters) |
| Regression safety | **IMPLEMENTED AND VERIFIED** (294 passing) |

**Overall: PARTIALLY COMPLETE.** The critical P0 gate (D13) is closed and independently verified. The
remaining partial criterion is dashboard/experiment management: the run registry and contract views exist,
but D28 segment filters and the rest of D44 (run launching, editable weights, segment rows) are not built.

---

## 8. Remaining limitations

1. **No official Git history** — the clean clone is of a Phase 6 source snapshot, not an original
   project commit; the mechanics of a fresh checkout are verified, not a lost history.
2. **External dataset** — reproducibility assumes the read-only canonical dataset at the documented path.
3. **Weak canonical neighbourhood** — 2/600 improving neighbours, best 0.07 units; no claim that the layout is globally optimal.
4. **`s_shape` is a node-order simplification** — not a physically validated serpentine route.
5. **Pick-time constants remain assumptions** — 8 s/line and 8 s/stop are not time-study measurements.
6. **Dashboard remains read-only** — no run launching, editable weights or segment filters (D28/D44 partial).
7. **Very low headroom** — bin weight 100 %, volume 99.93 %; any inventory change needs revalidation.
