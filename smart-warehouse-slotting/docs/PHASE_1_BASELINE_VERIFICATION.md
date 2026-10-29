# Phase 1 — Baseline Verification

**Phase:** 1 (environment, tests, baseline validation) — no optimizer/feature work
**Date:** 2026-10-29
**Repository:** `/home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting`
**Dataset under test:** `/home/hemanth/hackathon/epoch_hackathon/dataset/processed` (canonical v1 benchmark)
**Outcome:** environment **reproducible**; tests **execute** (84 pass / 6 fail); validator **runs**; baseline
**FAILS** validation with 1,071 `CAT-01` violations at a 10 m radius. Phase 1 is **COMPLETE** as an evidence
phase — the failing baseline is the finding, not a defect in the verification.

---

## A. Environment

| Item | Value | How verified |
|---|---|---|
| Repository root | `/home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting` | `pwd` |
| Version control | **not a Git repository** (`git rev-parse` → "NOT A GIT REPO"); no branch, no working tree | `git rev-parse --show-toplevel` |
| OS | Linux 7.2.6-pikaos, x86_64, PikaOS 4 | `uname -srm`, `/etc/os-release` |
| System Python | 3.14.7 | `python3 -V` |
| Venv Python | 3.14.4 (project `.venv`) | `.venv/bin/python -V` |
| Package manager | `uv` 0.11.14 (venv created with it; `pip` not used) | `uv --version` |
| Venv location | `<repo>/.venv` — valid, interpreter imports every requirement | import probe |
| Dataset | `../dataset/processed` — 2,304 locations, 1,200 products, 16,244 orders, 60,000 lines | row counts |

Installed versions in `.venv` (all satisfy `requirements.txt` floors):

| Package | Version | Floor |
|---|---|---|
| pandas | 3.1.0 | ≥2.0 |
| numpy | 2.5.4 | ≥1.24 |
| matplotlib | 3.11.2 | ≥3.7 |
| plotly | 7.1.0 | ≥5.0 |
| streamlit | 1.66.1 | ≥1.30 |
| pytest | 9.2.0 | ≥7.0 |

Install command (executed, exit 0):

```bash
cd <repo> && uv venv .venv --python 3.14 && uv pip install --python .venv/bin/python -r requirements.txt pytest
```

**Unresolved environment blockers:** none for test execution. Two caveats recorded rather than fixed:

1. `pandas 3.1.0` is well above the `>=2.0` floor; nothing failed, but the pin is loose enough that a future
   resolver could land on a different major.
2. There is **no lockfile**, so "reproducible" means "same floors on the same day", not "same versions
   forever". A `uv.lock` would make this claim stronger.

---

## B. Test results

**Command (full suite):**

```bash
.venv/bin/python -m pytest tests/ -q --tb=no -p no:cacheprovider
```

**Result: `6 failed, 84 passed` in 216.49 s (90 collected, 0 skipped, 0 errors, exit code 1).**

| Test | Classification | Root cause |
|---|---|---|
| `test_phase4_validator::test_baseline_feasible_on_benchmark` | implementation/expectation | baseline is infeasible under `CAT-01` |
| `test_phase5_optimizer::test_optimizer_feasible` | implementation/expectation | optimized layout inherits the infeasible start |
| `test_phase5_optimizer::test_optimizer_assignments_pass_phase4_validator` | implementation/expectation | same |
| `test_phase5_optimizer::test_optimizer_improves_over_baseline` | implementation/expectation | asserts `baseline_feasibility is True` |
| `test_phase6_evaluation::test_optimized_feasible_and_better` | implementation/expectation | asserts `baseline.constraint_violations == 0` |
| `test_phase8_integration::test_constraint_audit_is_not_header_only` | **artifact-state** | asserts every row of the *current* `outputs/constraint_audit.csv` is `passed == "true"`; the file now holds 1,071 violations |

All six are the same underlying fact — the suite encodes "the baseline is feasible", which stopped being true
when `CAT-01` went live. None is an environment failure. **No assertion was weakened, no test was skipped.**

**Run-to-run variance, recorded deliberately:** an earlier run in the same session gave `5 failed, 85 passed`.
The difference is `test_phase8_integration::test_constraint_audit_is_not_header_only`, which reads the
*current* `outputs/constraint_audit.csv` rather than a fixture — so its result depends on whether `validate`
ran after the last optimizer run. That is a test-design defect worth fixing in Phase 2, not a flake to hide.

**Stdlib-only subset (runs without the venv):**

```bash
python3 -m unittest tests.test_structural_and_separation -v      # 8 tests, OK
```

**Blocked tests:** none.

---

## C. Pipeline results

| Operation | Command | Exit | Outcome |
|---|---|---|---|
| `build-dataset` | — | — | **NOT RUN.** `build_dataset_cmd` writes to a fixed `DEFAULT_OUTPUT` (`../dataset/processed`); running it would overwrite the canonical dataset and every downstream artifact. The generator was instead exercised in isolation (see below) |
| Generator (isolated) | `build_warehouse(json.load(configs/dataset.json))` | 0 | 2,304 locations; `beam_`/`level_`/`rack_max_weight_kg` consistent for every scope (0 mismatches) |
| `validate` (S4) | `.venv/bin/python app/main.py validate --processed ../dataset/processed` | 0 | wrote `outputs/validation_status.json`, `constraint_audit.csv`, `validation_checks_baseline.csv`, `baseline_assignments.csv`, `dataset_validation.json` |
| `run-all` | `.venv/bin/python app/main.py run-all --processed ../dataset/processed --scenario A` | **0** | completed in 42.9 s; wrote analysis, optimized and evaluation artifacts — **despite an infeasible baseline** (see E.2) |

Pre-run artifacts were preserved: `outputs.foreign-backup/` (11 MB, byte-copy of the committed outputs
produced on another machine).

Artifacts written this phase (paths relative to the repo):

```
outputs/validation_status.json
outputs/constraint_audit.csv
outputs/validation_checks_baseline.csv
outputs/baseline_assignments.csv
outputs/dataset_validation.json
outputs/analysis/{abc_classification,demand_summary,affinity_matrix,affinity_clusters,volume_profiles}.csv
outputs/optimized/{optimized_assignments.csv,optimization_summary.json,run_history.json}
outputs/evaluation/{evaluation_summary.json,optimization_metrics.csv,pick_routes.csv,pick_route_stops_*.csv,constraint_audit_*.csv}
```

**Dataset-level validation** (`outputs/dataset_validation.json`): `ok: true`, `hard_errors: 0` — after the
metadata repair described in E.5.

---

## D. Baseline validation

| Quantity | Value |
|---|---|
| Storage locations | **2,304** |
| Locations used by the baseline | **1,425** (61.8%) |
| Assignment rows | **1,425** across **1,200 SKUs** |
| Units assigned | **6,375** |
| Inventory rows / units | **1,425 / 6,375** |
| Reconciliation | **exact** — assignments and inventory agree row-for-row and unit-for-unit |
| Validator checks executed | **20,699** |
| Violations | **1,071**, all `CAT-01` (hard) |
| Assignment feasibility | **94.08%** (1,129 of 1,200 SKUs) |
| Rule-check pass rate | **94.83%** |
| Verdict | `feasible: false`, `safety_compliant: false` |

**Checks by scope** (from the same run): `SL-02` beam 960, `SL-01` level 550, `RK-01` rack 144,
`CAT-01` pair checks 3,594. Maximum observed load ratios: beam **55.6%**, level **34.7%**, rack **29.2%** —
so no structural limit binds; only separation fails.

**Configured separation radius:** the validator's default, **`separation_radius_m = 10.0`**. The key is **not
present in any `configs/*.json`**; the value in force is the constructor default. This is a configuration
gap, not a chosen parameter (E.6).

**CAT-01 sensitivity** (same baseline, radius varied — no change to constraints or layout):

| Radius | `CAT-01` violations | Feasible |
|---|---|---|
| **10 m (in force)** | **1,071** | No |
| 5 m | 169 | No |
| 2 m | 0 | Yes |

Example violations from the validator output:

```
[CAT-01] CAT010 at LOC002058 and CAT001 at LOC001971 are 7.64 m apart (< 10 m)
[CAT-01] CAT010 at LOC002058 and CAT003 at LOC001951 are 7.77 m apart (< 10 m)
```

**Distinctions, stated explicitly:**

- Validator execution: **succeeded** (exit 0, 20,699 checks recorded).
- Baseline layout: **failed validation** (1,071 hard violations).
- Validation completion: **completed** — this is not a BLOCKED case.

---

## E. Confirmed blockers

### E.1 — The optimizer does not search with `CAT-01` (D40) — **open**
`run-all` produced a layout with **4 violations, all `SL-02` (beam)**, while fixing every `CAT-01` pair.
Two causes, both confirmed from output: the greedy tracks residual capacity for bin, level and rack but
**not for beam**, and its repair step is objective-blind. `optimization_summary.json` reports
`feasibility: false`, `n_violations: 4`, `stopping_reason: "4 violations after refinement"`.
*Impact:* no layout in this repository is currently feasible under the full rule set.

### E.2 — No feasibility gate before evaluation (D38) — **open**
`run-all` exited **0** and computed evaluation metrics for an infeasible baseline *and* an infeasible
optimized layout. `evaluation_summary.notes` records `baseline_constraint_violations: 1071`,
`optimized_constraint_violations: 4`, and still publishes travel, throughput and utilisation.
*Impact:* the pipeline cannot be used as evidence until it refuses to score infeasible input.

### E.3 — Committed artifacts are not reproducible from this dataset (D13) — **confirmed, quantified**
Same layout (baseline assignments byte-identical, 1,425 rows), same workload (5,415 orders, 1,083 batches,
20,000 pick lines), yet:

| Metric | Committed artifact (foreign) | Local run |
|---|---|---|
| baseline travel | 382,544.2 m | **1,707,167.2 m** (4.46×) |
| baseline cycle time | 465,094.8 s | 1,484,035.5 s |

Distance truth is **not** the explanation: graph depot distance and the `distance_to_dispatch_m` column agree
exactly (mean 98.9 m, ratio 1.00×, all 2,304 bins reachable). Therefore the committed artifacts were produced
against a **different geometry/dataset build**, and every published percentage is non-comparable to this
checkout.
*Impact:* no historical number may be quoted until artifacts are regenerated locally (now possible).

### E.4 — Six tests encode the pre-`CAT-01` assumption — **open**
Listed in §B. Five assert baseline/optimized feasibility; one asserts the current audit file is all-pass.
*Impact:* the suite cannot go green until E.1 is fixed (or the assertion is legitimately restated).

### E.5 — Dataset metadata drifted from the data — **resolved in Phase 1**
Adding the two limit fields to `dataset/processed/locations.csv` (needed for `SL-01`/`SL-02`) broke dataset
validation with 4 hard errors: column order vs the schema registry, a stale manifest hash, and two fields
missing from `data_dictionary.csv`.
**Fixed:** columns reordered to the registry order, both fields added to the dictionary (99 rows),
`generation_manifest.files["processed/locations.csv"].sha256` recomputed.
Verified: `dataset_validation.json` → `ok: true, hard_errors: 0`.

### E.6 — `separation_radius_m` is implicit — **open**
The radius in force (10 m) comes from a constructor default; no config file carries it.
*Impact:* the single parameter that decides whether the baseline passes is not visible in configuration.

### E.7 — No version control — **open**
The working copy is not a Git repository, so changes made in this phase cannot be attributed, diffed or
reverted through VCS. (A sibling checkout, `SlotSense/smart-warehouse-slotting`, is the untouched original.)

---

## F. Commands to reproduce

```bash
# 0. environment
cd /home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting
uv venv .venv --python 3.14
uv pip install --python .venv/bin/python -r requirements.txt pytest

# 1. versions actually used
.venv/bin/python -V && .venv/bin/python -m pip --version 2>/dev/null || uv pip list --python .venv/bin/python

# 2. full test suite (6 fail / 84 pass — expected until E.1 is fixed)
.venv/bin/python -m pytest tests/ -q --tb=no -p no:cacheprovider

# 3. stdlib-only subset (8 pass)
python3 -m unittest tests.test_structural_and_separation -v

# 4. dataset-level validation
.venv/bin/python app/main.py validate --processed ../dataset/processed --output outputs

# 5. full pipeline (completes but publishes infeasible results — see E.2)
.venv/bin/python app/main.py run-all --processed ../dataset/processed --scenario A

# 6. CAT-01 sensitivity at three radii (independent of the pipeline)
.venv/bin/python - <<'PY'
import csv, collections, pathlib, sys
sys.path.insert(0, ".")
from src.models.entities import *
from src.validation.validator import Validator
proc = pathlib.Path("../dataset/processed")
rows = lambda n: list(csv.DictReader(open(proc/f"{n}.csv", newline="")))
wh = Warehouse("WH", "c", "1")
for r in rows("locations"):
    wh.locations[r["location_id"]] = Location(
        location_id=r["location_id"], zone_id=r["zone_id"], aisle_id=r["aisle_id"], rack_id=r["rack_id"],
        bay=int(r["bay"]), shelf_level=int(r["shelf_level"]), x=float(r["x_m"]), y=float(r["y_m"]), z=float(r["z_m"]),
        width_cm=float(r["width_cm"]), height_cm=float(r["height_cm"]), depth_cm=float(r["depth_cm"]),
        max_weight_kg=float(r["max_weight_kg"]), usable_volume_cm3=float(r["usable_volume_cm3"]),
        beam_max_weight_kg=float(r["beam_max_weight_kg"]), level_max_weight_kg=float(r["level_max_weight_kg"]),
        shelf_max_weight_kg=float(r["shelf_max_weight_kg"]), rack_max_weight_kg=float(r["rack_max_weight_kg"]),
        allowed_handling=tuple(r["allowed_handling"].split("|")), allowed_hazard=tuple(r["allowed_hazard"].split("|")))
skus = {r["sku_id"]: SKU(r["sku_id"], r["product_name"], r["category_id"], float(r["width_cm"]),
        float(r["height_cm"]), float(r["depth_cm"]), float(r["unit_weight_kg"]),
        HandlingType(r["handling_type"]), HazardClass(r["hazard_class"])) for r in rows("products")}
b = lambda s: str(s).strip().lower() in ("true", "1")
rules = [CompatibilityRule(r["rule_id"], r["category_a"], r["category_b"], b(r["allowed"])) for r in rows("compatibility_rules")]
inv = collections.Counter()
for r in rows("inventory"): inv[r["sku_id"]] += int(r["quantity_on_hand"])
asg = [StorageAssignment(r["sku_id"], r["location_id"], int(r["assigned_quantity"]), AssignmentType.BASELINE)
       for r in rows("storage_assignments_baseline")]
for radius in (10.0, 5.0, 2.0):
    v = Validator(skus, wh, rules, inventory=dict(inv), separation_radius_m=radius)
    res = v.validate(asg)
    print(radius, len(res.violations), dict(collections.Counter(x.rule_id for x in res.violations)))
PY
```

---

## G. Phase 1 exit checklist

| # | Criterion | Verdict | Evidence |
|---|---|---|---|
| 1 | Environment reproducible, or blockers documented | **PASS** | §A; one-command install reproduced from an empty `.venv`; loose pandas floor and absent lockfile recorded |
| 2 | All executable tests run and recorded | **PASS** | §B — 84 pass / 6 fail / 0 skipped, 216 s; stdlib subset 8/8 |
| 3 | Baseline generation/loading attempted via documented workflow | **PASS** | §C — `build-dataset` deliberately not run (would overwrite tracked inputs); baseline loaded and validated through the real CLI |
| 4 | Baseline feasibility and `CAT-01` status established from evidence | **PASS (failing baseline)** | §D — 1,071 violations, `feasible: false`, radius 10 m, sensitivity table |
| 5 | `docs/PHASE_1_BASELINE_VERIFICATION.md` exists with reproducible commands | **PASS** | this file |
| 6 | `BUILD_STATUS_REPORT.md` reflects only verified updates | **PASS** | §H below; only environment, test, baseline and D13 claims were changed |
| 7 | No Phase 2 optimizer work or unsupported performance claims introduced | **PASS** | no optimizer/objective/scoring source was modified; the only source changes were the Phase-0 limit fields already in place before this phase |

**Phase 1 verdict: COMPLETE**, with a **failing baseline** as its principal finding.

---

## H. Changes to `BUILD_STATUS_REPORT.md`

Updated, because Phase 1 evidence changes the claim:

- **Environment blocker → resolved.** `pandas`, `numpy`, `matplotlib`, `plotly`, `streamlit`, `pytest` are installed
  in the project venv; the "cannot run the pipeline" blocker no longer holds.
- **"0 verified" → partially superseded.** The pipeline now runs locally, so D13 is *actionable*; it is not yet
  *closed*, because the local run disagrees with the committed artifacts by 4.46× (E.3).
- **Test totals added as measured facts** (84 / 6), replacing the earlier "could not run".
- **Baseline feasibility** now recorded from a local run, with the `CAT-01` count and radius.
- Everything not retested in Phase 1 (dashboard filters, replenishment, provenance manifest, split, 2×2,
  weight sweep) is left as previously reported.

Not changed: no optimizer performance claim was added, and the project is not marked complete.
