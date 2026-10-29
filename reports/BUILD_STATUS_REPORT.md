# Build status report — Smart Warehouse Slotting & Optimization Engine

**Date:** 2026-10-29
**Subject:** what is built, what is partial, what is not built — against `PS_Track2.pdf` and `PROJECT.md`
**Code under report:** `epoch_hackathon/smart-warehouse-slotting` (the pasted working copy)
**Companion documents:** `ARCHITECTURE.md` v9.0, `PROJECT.md`, and `smart-warehouse-slotting/docs/PHASE_1_BASELINE_VERIFICATION.md` (Phase 1 evidence, 2026-10-29)

> **Phase 1 update (2026-10-29):** the environment is now reproducible (venv installed), the suite runs
> (**84 pass / 6 fail**), `run-all` completes locally in 43 s, and the baseline is **confirmed infeasible**
> (1,071 `CAT-01` violations at a 10 m radius). Sections 0, 1.1, 4, 6 and 7 below are updated accordingly.

> **Phase 2 update (2026-10-29):** constraint enforcement is now real and verified.
> The optimizer produces a **feasible** layout (0 violations, 6,375/6,375 units, 15,167 checks) and the
> `CAT-01` grid rejects nothing on this dataset because velocity ordering + hazard zoning already separate
> the forbidden pairs. The **as-supplied baseline is infeasible** (1,071 `CAT-01` at 10 m), so it was repaired
> **for feasibility only, objective disabled** (93/1,200 SKUs moved, 0 quantity changes) and the gate now
> publishes a **valid comparison: −55.65 % travel**, independently reproduced by a separate verifier process.
> The evaluation gate blocks infeasible layouts (`BLOCKED_INFEASIBLE_LAYOUT`, `run-all` exit 1) and the suite is
> **181 passed / 0 failed / 0 skipped**. Closed in the architecture register: **D7, D38, D40** (joining D5, D34, D26).
> Still not built, unchanged: T per order line, replenishment, provenance manifest, dashboard filters, the split,
> the 2×2 and the weight sweep — those are Phase 3/4.

> **Phase 3 update (2026-10-29):** demand-aware evaluation is now measurable, and the decomposition has been
> corrected. Travel is computed per **order line** and published as `demand_weighted_depot_distance` (numerator
> metres / denominator lines, 5,997/5,997 priced). A temporal, order-level fit/holdout split (3,790 / 1,625
> orders; 14,003 / 5,997 lines) passes **ten** leakage checks. The layout fitted on `A_FIT` is feasible
> (0 violations, 6,375/6,375 units). On the **holdout**, quantity-aware travel falls **−48.29 %**; the raw
> all-bins comparison is −60.65 %. The primary 2×2 now manipulates a real **fragmentation policy**
> (`as_is` vs `min_bins`): placement is **−245,161 m (−48.88 %)**, fragmentation is **+2,893 m (+0.58 %)** —
> the gain is placement, not consolidation (the earlier "54 % fragmentation" figure was the pick-rule
> sensitivity design, now reported separately). Restock-travel proxy falls **−40.34 %** (zero-demand SKUs no
> longer invent trips), and the term is wired as `Objective.epsilon` (default 0.0). Five weight vectors were
> swept; four produce one identical layout, `ε = 0.5` produces a second and trades 0.025 % restock travel for
> 0.107 % held-out pick travel; selection uses fit line travel and retains the default. Provenance (33 output
> hashes, seeds, protocol), EDA findings and the dashboard data contract are delivered; `load_all()` exposes
> `phase3`. Suite: **224 passed / 0 failed / 0 skipped**. Closed in the register: **D22, D29, D35, D36, D46,
> D47, D48** (joining D5, D7, D26, D34, D38, D40). Still open: dashboard view (D28/D44), seed variability, and
> the non-comparable historical artifacts.

> **Phase 4 update (2026-10-29):** the optimized layout now wins on **held-out simulation**, not only on the
> line metric. A layout × picking-policy 2×2 (baseline vs optimized × `nearest_neighbor` vs `s_shape`) runs on
> one frozen A-holdout workload (1,625 orders / 5,997 lines): travel **508,174.8 → 234,208.0 m (−53.91 %)**,
> cycle time **442,129.7 → 231,386.0 s (−47.67 %)**, throughput **13.23 → 25.28 orders/h (+91.1 %)**. The
> layout effect is **−53.86 %** of travel; the policy effect is **+0.09 %** (S-shape slightly worse) and the
> interaction **+561.9 m**, so the choice of policy does not change the verdict. The improvement persists on
> held-out regimes **B (−33.37 %)** and **C (−42.19 %)**, which were never used for fitting. Every publishable
> cell has 0 violations, 6,375/6,375 units and 100 % assignment completeness. A new independent verifier
> recomputes travel, cycle, throughput, effects, split integrity, inventory, headroom and provenance hashes:
> **14/14 checks pass**. Structural headroom is now quantified and tight: bin weight **100 %**, bin volume
> **99.93 %**, level **98.06 %**, beam **98.76 %**, rack **69.36 %**. Phase 4 adds a read-only contract
> (`load_all()["phase4"]`) but no Streamlit view. Suite: **247 passed / 0 failed / 0 skipped**. Still open:
> dashboard view (D28/D44), per-stop pick time (D37), seed variability, and the low-headroom risk.

---

## 0. Verdict (current, Phase 4)

The **design** covers every PS requirement (§15 of `ARCHITECTURE.md`, 20 rows, each with a mechanism). The
**code executes end-to-end on this machine**: `run_phase3` rebuilds the split, fits on `A_FIT`, validates
every cell independently, runs the placement × fragmentation 2×2, the replenishment metric, the weight sweep
and the provenance manifest; `run_phase4` runs the layout × picking-policy 2×2, demand regimes B/C, headroom,
rejection diagnostics and provenance, and `tools/verify_phase4.py` recomputes the headline numbers (14/14).
The canonical baseline was repaired to feasibility (1,071 → 0 `CAT-01`, objective disabled), the optimized
layout is feasible (0 violations, 6,375/6,375 units), and the frozen holdout gives **−53.91 % travel**,
**−47.67 % cycle time** and **+91.1 % throughput** under nearest-neighbour; S-shape changes travel by only
**+0.09 %**. The suite is **247 passed / 0 failed / 0 skipped**. Remaining gaps: no dashboard view
(D28/D44), per-stop pick time (D37), one deterministic instance, and very low structural headroom.

> **Historical note.** §1–§7 below are the original **Phase 1** assessment (84 pass / 6 fail, infeasible
> baseline, no local end-to-end run) retained as history. They are superseded by this verdict and the Phase
> 1/2/3/4 update blocks above; their present-tense gaps must not be read as the current state.

---

## 1. What is built

### 1.1 Built **and executed in this session**

| Item | Evidence |
|---|---|
| **`D34` — four structural limits with defined units** | `apply_structural_limits()` in `src/data_processing/generate.py`; regenerated topology: 2,304 bins, **0 inconsistent beams, 0 level mismatches, 0 rack mismatches**; sample beam 144.0 / level 921.6 / rack 2,815.2 kg |
| **`D5` — `CAT-01` category separation** | `_check_category_separation()` in `src/validation/validator.py`; 3-D Euclidean, 13 forbidden pairs, grid index, configurable `separation_radius_m` |
| **Unit tests for both** | `tests/test_structural_and_separation.py` — **8 tests, all passing** (`python3 -m unittest`), covering: bin overload, beam-overload-while-level-legal, level-overload-while-beams-legal, derated rack, forbidden pair too close/far, allowed pair, radius sensitivity |
| **Validator run on the real baseline** | 20,699 checks; `SL-02` 960, `SL-01` 550, `RK-01` 144, `CAT-01` 3,594; max load ratios 55.6% / 34.7% / 29.2% |
| **Full test suite executed** | `.venv/bin/python -m pytest tests/ -q` → **84 passed / 6 failed / 0 skipped** in 216 s. All 6 failures trace to the baseline no longer being feasible under `CAT-01` |
| **`run-all` executed locally** | exit 0 in 42.9 s; wrote analysis, optimized and evaluation artifacts; baseline and optimized layouts both infeasible (1,071 and 4 violations) |

### 1.2 Implemented, present in source, **not executed here**

These have working code and committed artifacts from a prior run on another machine. They are not verified in
this checkout.

| Requirement | Where | Artifact |
|---|---|---|
| R1.1 volumetric & spatial bounds | `validator.SP-01`, `VD-01` | `outputs/constraint_audit.csv` |
| R2.1 ABC velocity | `src/analytics/abc.py` | `outputs/analysis/abc_classification.csv` |
| R2.6 inventory conservation | `validator.INV-01/02/03` | 6,375 units placed, 0 violations |
| R3.1 baseline artifact | `storage_assignments_baseline.csv` | 1,425 rows |
| R3.2 identical conditions | `simulation/pipeline.py` | `evaluation_summary.notes` |
| data vectors `PROJECT.md D1–D3` | generator + schema registry | `dataset/processed/*` |
| `PROJECT.md D-1` prototype | `app/main.py run-all` | `outputs/**` |
| Route simulation / evaluation | `src/simulation`, `src/evaluation` | `pick_routes.csv`, `optimization_metrics.csv` |

---

## 2. What is partial

Mechanism exists; a named gap remains. All of these produce numbers that must not be published as results yet.

| Requirement | What exists | What is missing |
|---|---|---|
| **R1.3 hazard & category separation** | `HZ-01`, `HD-01` (incl. `fragile`), `ER-01`, and now `CAT-01` — which **gates** | The **optimizer does not search with `CAT-01`** — the greedy is category-blind and Phase A repair is objective-blind, so it will produce layouts the validator now rejects (`D40`); the committed baseline already does |
| **R1.4 hard vs soft separation** | one engine, four verdicts designed | `is_feasible` still collapses every violation into one boolean (`D7`) |
| **R2.3 affinity** | pair statistics, clustering, penalty term | two threshold sets — the reported metric and the optimizer use different filters (`D18`) |
| **R2.4 golden-zone ergonomics** | `Γ` term and a share metric | term weights by `d(s)`, metric by `d(s) × units` (`D33`) |
| **R3.3 required metrics** | registry, comparison table | fragmentation vs placement never measured (no 2×2, `D22`); in-sample (`D21`); no split (`D46`) |
| **R3.4 honesty of claims** | metric classes in `metrics.py` | no numerator/denominator in the artifact; no `derived` labels (`D23`); cycle time still mislabelled |
| **EDA mandate** | ABC, affinity, volume artifacts exist | no findings-with-consequences written; no volume-vs-capacity profile narrative (§11.8 |
| **`PROJECT.md D-3` documentation** | `docs/TECHNICAL_REPORT.md` (288 lines) | no trade-off analysis (weight sweep absent, `D36`), no EDA findings |

---

## 3. What is not built

| Requirement | Why it is not built |
|---|---|
| **R2.2 proximity to I/O** | `T` is summed per assignment record, not per order line, and is **never published** (`D29`, `D35`). The optimised quantity cannot be inspected |
| **R2.5 replenishment** | No statement, no metric. The PS names "ergonomic & replenishment efficiency"; the repo answers with nothing (`D47`) |
| **Provenance: source, licence, retrieval date** | `metadata/source_manifest.json` is specified (§5.3) but never emitted (`D48`) |
| **`PROJECT.md D-2` dashboard** | Six tabs exist, but **no run/zone/class filtering**, and per-segment metric rows do not exist (`D28`, `D44`) |

Also absent as *artefacts*: `split-dataset` (full-tree fit/holdout), the 2×2 pick-rule table, the weight-sweep
table, the determinism test, and the fail-fast ceiling for the dense distance matrix.

---

## 4. Environment blockers (why "verified" is zero)

| Blocker | Status |
|---|---|
| pandas/numpy missing from the default interpreter | **RESOLVED** — `.venv` now holds pandas 3.1.0, numpy 2.5.4, matplotlib 3.11.2, plotly 7.1.0, streamlit 1.66.1, pytest 9.2.0 (uv) |
| `.venv` empty | **RESOLVED** — same install |
| No network | **RESOLVED** — PyPI reachable; install completed |
| Committed artifacts produced on another machine | **CONFIRMED and quantified** — local baseline travel 1,707,167 m vs the artifact's 382,544 m (4.46×) with an identical layout and workload. See §6 |
| README's 1,534 assignments vs the artifact's 1,358 | **unresolved** — the local baseline has 1,425 assignment rows; neither figure reconciles yet |
| No lockfile | **open** — `requirements.txt` carries floors only, so version reproducibility is same-day, not guaranteed |

What *did* run without pandas: the generator (stdlib only), the validator (stdlib only), and the new unit
tests. That is how D34 and D5 were verified despite the blockers.

---

## 5. What changed in this session

| File | Change |
|---|---|
| `src/data_processing/generate.py` | **+53** — `apply_structural_limits()`, called by both topology builders |
| `src/validation/validator.py` | **+128 / −39** — `CAT-01` with 3-D grid, four-scope structural checks, `separation_radius_m` |
| `src/models/entities.py` | **+8 / −1** — `beam_max_weight_kg`, `level_max_weight_kg` |
| `src/data_processing/schema.py` | **+4 / −2** — both fields registered |
| `src/validation/loader.py` | **+2** — maps the new columns with fallbacks |
| `src/optimization/pipeline.py` | **+4 / −1** — passes the radius into the validator |
| `tests/test_structural_and_separation.py` | **+176 (new)** — 8 tests, all passing |
| `dataset/processed/locations.csv` | patched with the two new columns (backup `locations.csv.bak-pre-limits`) |
| `ARCHITECTURE.md` | D34, D5 moved to §16.4 *closed*; statuses updated to 8 implemented / 8 partial / 4 specified |

---

## 6. The finding that changes the plan

**With `CAT-01` live, the committed baseline is not feasible.**

| Separation radius | `CAT-01` violations | Feasible? |
|---|---|---|
| 10 m | **1,071** | No |
| 5 m | 169 | No |
| 2 m | 0 | Yes |

The previous "0 violations, feasible" was true only because the rule did not exist. Three consequences:

1. The reported improvement figures were computed on a layout that the PS's own separation requirement
   rejects — they cannot be presented as a feasible result.
2. The optimizer must be made `CAT`-aware (greedy ordering + objective-aware repair), or it will keep
   returning infeasible layouts or fall back to the baseline.
3. `separation_radius_m` is now a real design parameter with a measured curve, not a default.

**And the optimizer still cannot satisfy it.** The local `run-all` produced a layout that fixes every
`CAT-01` pair but introduces **4 beam (`SL-02`) violations**, because the greedy tracks residual capacity for
bin, level and rack but not for beam, and its repair step is objective-blind. `optimization_summary.json`:
`feasibility: false`, `n_violations: 4`. `run-all` still exited **0** and published metrics — there is no
feasibility gate before evaluation (`D38`).

---

## 7. Claims that must not be made yet

- ❌ "−27% travel distance" — in-sample, and computed before `CAT-01` existed.
- ❌ "0 constraint violations" — true only for the rules that existed then.
- ❌ "zero-tolerance safety compliance" — separation is now gating, and the baseline fails it.
- ❌ "end-to-end pipeline runs" — it cannot run on this machine.
- ❌ "structurally verified" — `SL-02` executes and passes now, but no stress instance has been run.
- ✅ "the separation matrix is enforced" — true as of this session, at unit and baseline level.
- ✅ "four structural limits exist, with defined units, and are independently checked" — true as of this session.
- ❌ "−56% travel distance" (the local run's figure) — computed on an infeasible baseline and not comparable
  to the committed −27%, which came from a different dataset build.

---

## 8. Next steps, in dependency order

| # | Action | Unblocks |
|---|---|---|
| 1 | Make greedy + repair `CAT`-aware; re-run `optimize` at `R = 10 m` | R1.3, and every layout result |
| 2 | `T` per order line + publish `demand_weighted_depot_distance` | R2.2 |
| 3 | 2×2 pick-rule table (fragmentation vs placement) | R3.3 |
| 4 | `split-dataset` full trees + fit/holdout run | R3.3, R3.4 |
| 5 | Replenishment metric + term | R2.5 |
| 6 | Dashboard segment rows + run/zone/class filters | `PROJECT.md D-2` |
| 7 | Provenance manifest | `PROJECT.md D4` |
| 8 | Fix the environment (pandas), then `run-all` | turns every "reported" into "verified" |

Items 1–4 are what make a number publishable. Item 8 is what makes it reproducible.

---

## 9. Reproduce what this report claims

```bash
cd epoch_hackathon/smart-warehouse-slotting

# unit level — works without pandas
python3 -m unittest tests.test_structural_and_separation -v      # 8 passed

# generator consistency — works without pandas
python3 - <<'PY'
import sys, json; sys.path.insert(0, ".")
from src.data_processing.generate import build_warehouse
locs, _, _ = build_warehouse(json.load(open("configs/dataset.json")))
print(len(locs), locs[0]["beam_max_weight_kg"], locs[0]["level_max_weight_kg"])
PY

# validator on the committed baseline — works without pandas (stdlib CSV reader)
# see §6 numbers: R=10 -> 1071 violations, R=5 -> 169, R=2 -> 0

# full pipeline — BLOCKED until pandas is installed
python3 -m pytest tests/ -q
python3 app/main.py run-all --processed ../dataset/processed --fit-scenario A --eval-scenario B
```

---

*Report generated from executed commands only. Where a number could not be reproduced on this machine it is
labelled "reported" and traced to the artifact that contains it.*
