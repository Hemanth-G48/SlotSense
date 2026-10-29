# Phase 2 — Part 3: Regression tests and honest repair of the legacy failures

**Phase:** 2, Part 3 of 6 (test work only — no optimizer/gate logic was modified)
**Date:** 2026-10-29
**Repository:** `/home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting` (not a Git repository)
**Python:** `.venv/bin/python` (3.14.4), pytest 9.2.0
**Dataset:** `../dataset/processed` — read only, never regenerated; `build-dataset` not run

---

## A. What this part changes

Part 2 (P2-2) made three things true: the optimizer returns a **feasible** layout on the
canonical dataset, the status vocabulary separates *execution* from *feasibility*, and the
evaluation gate refuses to score an infeasible layout. Part 3 makes the suite **assert those
properties**, so they cannot regress silently, and repairs the legacy tests that still encode
the pre-`CAT-01` assumption "the baseline is feasible".

Nothing in `src/` or `app/` was modified. Only `tests/` and this document changed.

### A.1 New test files

| File | Cases | What it pins |
|---|---|---|
| `tests/phase2_fixtures.py` | — (helper) | A tiny, deterministic, canonical-shaped dataset (24 bins, 4 SKUs, 3 baseline variants) written under the caller's `tmp_path`, plus a pipeline driver that mirrors `validate` + `optimize` + `simulate` into an owned output root. No test using it reads or writes the shared `outputs/` tree. |
| `tests/test_cat01_separation_radius.py` | 13 | CAT-01 radius semantics: closer than R rejected, farther allowed, **exactly R allowed (inclusive, `d + 1e-9 >= R`)**, float-tolerance at the boundary, compatible pairs never flagged, self-pairs not a separation constraint, R = 0 disables the rule, the validator honours the configured radius (not the default), and the **same configured radius reaches both the placer and the judge** through `run_phase5`. Also: an explicit optimizer/validator radius mismatch raises. |
| `tests/test_structural_scopes.py` | 14 | Beam (`SL-02`) is keyed by `(rack_id, bay, shelf_level)`; level (`SL-01`) by `(rack_id, shelf_level)`; rack (`RK-01`) by `rack_id`; bin (`LD-01`) by bin. Each scope is made to bind **alone**, with the neighbouring scopes asserted legal. Observed values are compared against independently summed loads. Placer allocation is capped by the beam residual. **Repair may not fix a beam violation by creating a CAT-01 violation**, nor **by pushing the load onto an overloaded shelf level** (both with a control proving the trade-off was really available). |
| `tests/test_inventory_integrity.py` | 7 | Units before == units after and per-SKU quantity equality; no SKU disappears; no duplicate `(sku, bin)` rows (and `DU-01` fires when one is injected); an unplaceable SKU is **reported** with its binding reason rather than dropped; a rejected separation candidate does not mutate the grid; validation does not mutate the layout. |
| `tests/test_feasibility_gate.py` | 11 | Zero CAT-01 but one beam violation is infeasible; the gate blocks an infeasible **baseline** and (symmetrically) an infeasible **optimized** layout with `evaluation_status == "BLOCKED_INFEASIBLE_LAYOUT"`, `comparison == []`, diagnostics labelled `diagnostic_only`; positive control publishes a comparison; `execution_status` is distinct from `feasibility_status`; a crashed run reports `ERROR` with feasibility `None` (not `INFEASIBLE`); missing metrics stay `None` and are never coerced to `0`. |
| `tests/test_determinism.py` | 6 | Same seed/config ⇒ identical assignment digest (sha256 over sorted rows) and identical objective across two runs, for all three baseline variants; two optimizer instances are independent and reproducible; repeated runs are idempotent; the configured radius is part of a run's identity. |
| `tests/test_artifact_isolation.py` | 4 | The four required delivery artifacts are produced by a real run **into `tmp_path`**; a run with an explicit output root leaves the shared `outputs/` tree byte-identical (checksum + mtime snapshot used as a *guard*, never as a source of expected values); every produced file lives under the given root; the audit written for a failing layout is row-per-violation with `rule_id`/`observed`/`limit`. |

### A.2 Legacy tests repaired (the six from `PHASE_1_BASELINE_VERIFICATION.md` §B)

| Test | Change | Justification |
|---|---|---|
| `test_phase4_validator::test_baseline_feasible_on_benchmark` → `test_baseline_feasibility_is_reported_correctly_on_benchmark` | Asserts the validator's CAT-01 count equals an **independent** pair-by-pair distance count, and that an infeasible verdict implies reported violations plus an `INFEASIBLE` gate status. | "The baseline passes" is not a contract; reporting its verdict correctly is. Phase 1 measured 1,071 violations at 10 m — the old assertion contradicted the finding. |
| `test_phase5_optimizer::test_optimizer_improves_over_baseline` | Replaced `baseline_feasibility is True` with: improvement on the objective (kept), status/violation consistency, the reported baseline verdict equal to an independently computed one, and `feasibility_status == "FEASIBLE"` for the optimizer's own output. | The baseline is genuinely infeasible; asserting it is feasible asserts a false premise. The improvement claim is preserved and now sits on a layout that is itself valid. |
| `test_phase6_evaluation::test_optimized_feasible_and_better` | Asserts the **gate invariant** unconditionally (`comparison_valid` ⇔ both layouts feasible; `BLOCKED_INFEASIBLE_LAYOUT` ⇔ not both feasible; `blocked_layouts` = exactly the infeasible ones), keeps `optimized` feasibility/0 violations/100 % assignment feasibility as unconditional hard assertions, and confines the travel/utilization "better" claims to the branch where a comparison is actually published. | The evaluation must be *either* a valid comparison *or* an explicit block — never a comparison presented as evidence for an invalid layout. No hard constraint was dropped. |
| `test_phase8_integration::test_constraint_audit_is_not_header_only` | Stops reading `outputs/constraint_audit.csv`. Regenerates the audit in `tmp_path` for a clean layout (PASS rows) and a failing one (one row per violation), and checks the checks export carries `rule_id`/`observed`/`limit`. | The old test asserted the *state* of a mutable artifact — it failed whenever a pipeline run had written violations there (the 5-vs-6 failure flake recorded in Phase 1). |
| `test_phase8_integration::test_four_required_artifacts_exist` → `test_required_artifacts_are_produced_by_the_pipeline` | Runs the real phases into `tmp_path` and asserts the four required artifacts appear there. | Same class of defect: existence in `outputs/` is run-order dependent. The artifact *contract* (names, non-empty, reproducible) is stronger and deterministic. |
| `test_phase8_integration::test_optimized_output_is_feasible_via_summary` → `test_optimized_output_is_consistent_with_its_summary` | Reads the summary from an owned run and asserts the status/violation/units contract holds. | Removes the dependency on the last committed `outputs/optimized/optimization_summary.json` while keeping every substantive assertion. |

**Not changed, and why:** `test_phase5_optimizer::test_optimizer_feasible` and
`test_phase5_optimizer::test_optimizer_assignments_pass_phase4_validator` were already
*dishonest failures* — P2-2 made the optimizer return a feasible layout (0 violations,
6,375/6,375 units), so both now pass while asserting the true contract. No assertion was
weakened, skipped, or deleted anywhere; the suite has 0 skipped tests.

### A.3 Artifact isolation

* Every pipeline test in this part writes into `tmp_path`.
* `tests/phase2_fixtures.py::produce_delivery_artifacts` is the only way these tests run the
  real phases, so the output root is always explicit.
* `tests/test_artifact_isolation.py` proves the isolation instead of assuming it: it
  fingerprints the shared `outputs/` tree (size, mtime, sha256) before and after a full
  `validate` → `optimize` → `simulate` run and asserts nothing changed.
* The shared `outputs/` tree is never used as a source of expected values in any file
  added or modified by this part.

---

## B. Results

**Command (full suite):**

```bash
cd /home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting
.venv/bin/python -m pytest tests/ -q
```

**Before this part (measured at the start of it): `4 failed, 113 passed in 188.74 s` (exit 1).**
The four failures were exactly the four still-broken legacy tests (`test_phase4_validator::test_baseline_feasible_on_benchmark`,
`test_phase5_optimizer::test_optimizer_improves_over_baseline`,
`test_phase6_evaluation::test_optimized_feasible_and_better`,
`test_phase8_integration::test_constraint_audit_is_not_header_only`). The other two tests listed
in Phase 1 §B (`test_optimizer_feasible`, `test_optimizer_assignments_pass_phase4_validator`)
had already started passing after P2-2, because the optimizer now really returns a feasible
layout.

**After this part: `172 passed, 0 failed, 0 skipped, 0 errors in 226.05 s` (exit 0).**

| Metric | Before | After |
|---|---|---|
| Collected | 117 | 172 (55 new) |
| Passed | 113 | **172** |
| Failed | 4 | **0** |
| Skipped / xfailed | 0 | **0** |
| Runtime | 188.74 s | 226.05 s |

The +37 s is the canonical optimizer/simulation work already present in the suite plus ~5 s of
new fixture-based tests; no test was made slower by design.

**Remaining failures: none.** Nothing was skipped, xfailed, deleted, or weakened to reach this
state — every assertion that used to encode "the baseline is feasible" now encodes the
contract that replaced it (§A.2).

Sanity evidence for the repaired baseline test (canonical dataset, configured radius 10 m):

```
radius_m           = 10.0
assignments        = 1425
checks_run         = 20699
reported CAT-01    = 1071
independent CAT-01 = 1071     <- computed by the test with math.dist, without the validator
total violations   = 1071
violations_by_rule = {'CAT-01': 1071}
feasibility_status = INFEASIBLE
```

The stdlib-only subset documented in Phase 1 still runs unchanged:
`python3 -m unittest tests.test_structural_and_separation -v` → 8 tests, OK.

### D. Targeted runs (each new file, on its own)

```bash
.venv/bin/python -m pytest tests/test_cat01_separation_radius.py -q   # 13 passed in 0.46s
.venv/bin/python -m pytest tests/test_structural_scopes.py -q          # 14 passed in 0.05s
.venv/bin/python -m pytest tests/test_inventory_integrity.py -q        #  7 passed in 0.60s
.venv/bin/python -m pytest tests/test_feasibility_gate.py -q           # 11 passed in 0.85s
.venv/bin/python -m pytest tests/test_determinism.py -q                #  6 passed in 1.07s
.venv/bin/python -m pytest tests/test_artifact_isolation.py -q         #  4 passed in 0.62s
```

Repaired files, run on their own:

```bash
.venv/bin/python -m pytest tests/test_phase4_validator.py -q                          # 13 passed in 0.66s
.venv/bin/python -m pytest tests/test_phase5_optimizer.py tests/test_phase6_evaluation.py -q  # 12 passed in 143.14s
.venv/bin/python -m pytest tests/test_phase8_integration.py -q                        #  6 passed in 67.89s
```

### E. Files changed (no version control in this repository)

Added:

```
tests/phase2_fixtures.py
tests/test_cat01_separation_radius.py
tests/test_structural_scopes.py
tests/test_inventory_integrity.py
tests/test_feasibility_gate.py
tests/test_determinism.py
tests/test_artifact_isolation.py
docs/PHASE_2_PART3_TESTS.md
```

Modified:

```
tests/test_phase4_validator.py    (baseline test restated; independent CAT-01 count helper)
tests/test_phase5_optimizer.py    (improvement test restated; independent baseline verdict fixture)
tests/test_phase6_evaluation.py   (gate invariant; hard assertions kept, "better" claims scoped to a valid comparison)
tests/test_phase8_integration.py  (audit + artifact tests moved to tmp_path; reproducibility test uses tmp_path)
```

Not touched: anything under `src/` or `app/` (optimizer, gate, validator, dashboard), the
dataset under `../dataset/processed`, and `configs/`.

---

## C. Remaining risks / follow-ups

1. **Two pre-existing dashboard suites still read the shared `outputs/` tree**
   (`test_phase7_dashboard.py`, `test_phase9_dashboard_data.py`). They exist to prove the
   dashboard consumes *real* generated artifacts, and isolating them requires threading an
   outputs root through `app/dashboard_data.py` (`load_all()` takes no path today) — application
   code outside this card's scope. `test_phase9` is guarded by a `skipif`; `test_phase7` is not,
   so it would fail in a clean checkout. Flagged for a follow-up card.
2. **Runtime.** The suite is dominated by the canonical optimizer runs (P2-2 chose 20 s repair
   + 600 annealing iterations). The new tests add ~5 s in total because they run on a 24-bin
   fixture.
3. **The canonical benchmark tests still depend on `../dataset/processed`.** They skip (not
   fail) when it is absent; that is a pre-existing, documented precondition rather than a way to
   get green.
