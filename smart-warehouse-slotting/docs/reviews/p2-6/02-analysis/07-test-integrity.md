# Item 7 — Test integrity against the Phase-1 baseline of 84 passed / 6 failed

**Verdict: PASS** — with **one required change** (`tests/test_phase5_optimizer.py:80`)

## The command and its output

```
$ cd /home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting
$ .venv/bin/python -m pytest tests/ -q --tb=no -p no:cacheprovider
........................................................................ [ 39%]
........................................................................ [ 79%]
.....................................                                    [100%]
181 passed in 242.06s (0:04:02)
$ echo $?
0
```

**181 passed, 0 failed, 0 skipped, 0 xfailed, 0 errors**, from 167 `def test_` functions across 18 files
(parametrize expands them to 181 collected). Phase 1 reported **90 collected, 84 passed, 6 failed** — so
+91 collected tests and 6 fewer failures, with nothing skipped to get there.

Verbatim in `03-dossiers/d01-pytest-full-suite.txt`.

## Nothing was muted

* `grep` for `skip|xfail|expectedFailure|pytest.mark` across `tests/`: **no `xfail`, no
  `expectedFailure`, and no unconditional `skip`.**
* The only `skipif` is `tests/test_phase9_dashboard_data.py:21` (`pytestmark = pytest.mark.skipif(...,
  reason="canonical dataset / evaluation outputs not generated")`) — a Phase-7/9 module that predates
  Phase 2 (mtime 2026-10-28 23:23).
* The eight `pytest.skip("canonical dataset not generated")` calls are conditional guards that did not fire:
  the suite reports **0 skipped**.
* `pytest.mark.parametrize` is used in three places (`test_structural_scopes.py:263`,
  `test_determinism.py:70`, `test_cat01_separation_radius.py:150`, `test_phase2_greedy_constraints.py:156`)
  to *add* cases, not to thin them.

## Every one of the six Phase-1 failures, classified

| Phase-1 failure | Current state | Weaker or stronger? |
|---|---|---|
| `test_phase4_validator::test_baseline_feasible_on_benchmark` | Renamed `test_baseline_feasibility_is_reported_correctly_on_benchmark` (`tests/test_phase4_validator.py:157`) | **Stronger.** It now recomputes the CAT-01 pair count independently (`:180-185`), requires `checks_run > 0` (`:186`), requires every violation to carry a rule id and reason (`:187`), and pins the gate verdict when infeasible (`:189-197`). |
| `test_phase5_optimizer::test_optimizer_feasible` | Unchanged in intent (`:49-54`) | **Same.** Still asserts `feasibility is True`, `n_violations == 0`, `units_placed == inventory_units`, `n_assignments >= n_skus_with_inventory`. |
| `test_phase5_optimizer::test_optimizer_assignments_pass_phase4_validator` | Still asserts `res.is_feasible` over a real re-validation (`:68-81`) | **Same, with a gap** — see the required change below. |
| `test_phase5_optimizer::test_optimizer_improves_over_baseline` | Rewritten (`:84-117`) | **Stronger.** It ends by *requiring* `feasibility_status == "FEASIBLE"` (`:115-117`), plus status/evidence consistency (`:100-105`) and agreement with an independently computed baseline verdict (`:107-112`). The old test asserted `baseline_feasibility is True` — a false premise; the new one removes the false premise without removing the demand. |
| `test_phase6_evaluation::test_optimized_feasible_and_better` | Rewritten (`:83-139`) | **Stronger.** It pins the gate invariant in both directions (`comparison_valid is both_feasible`, `:102-107`) *and* still requires the optimized layout to be valid (`:110-114`), `constraint_violations == 0`, `assignment_feasibility_pct == 100.0`. A blocked baseline is explicitly not usable as cover for an invalid answer. |
| `test_phase8_integration::test_constraint_audit_is_not_header_only` | Rebuilt on owned fixtures (`:42-79`) | **Stronger.** It now builds a clean *and* a failing dataset in `tmp_path` and asserts both audit shapes, plus the companion `validation_checks` export. The run-order dependence that Phase 1 flagged is gone. |

No test was deleted, and no assertion that mattered was dropped.

## New tests own their fixtures

* `tests/phase2_fixtures.py:176-340` writes a canonical-shaped tiny dataset under the **caller's** `tmp_path`;
  `:376-400` mirrors `validate` + `optimize` + `simulate` into an owned root.
* `tests/test_artifact_isolation.py` exists specifically to assert that a pipeline run with an explicit
  `--output` does not touch the shared `outputs/` tree (`:37` names the tree it must not touch; `:57-103` run
  everything under `tmp_path / "outputs"`).
* `tests/test_phase2_greedy_constraints.py` and `tests/test_structural_scopes.py` use no filesystem at all —
  they build `Warehouse`/`SKU` objects in memory (0 `tmp_path`, and `grep` finds no `to_csv`, `write_text`,
  `open(` or `mkdir` in either file).
* Empirical check: after the full 242 s suite, every mtime under `outputs/` is unchanged from before the run
  (`03-dossiers/d10-environment-and-attribution.txt`, last block).
* Two files still read `PROJECT_ROOT/outputs` (`test_phase9_dashboard_data.py:19`, guarded by `skipif`) —
  both predate Phase 2.

## Required change

**`tests/test_phase5_optimizer.py:80`**

```python
res = validate_assignment(assignments, skus, wh, comp, inventory)          # radius defaults to 10.0
```

should be

```python
res = validate_assignment(assignments, skus, wh, comp, inventory,
                          separation_radius_m=cfg.separation_radius_m)
```

`cfg` is already loaded in the `baseline_verdict` fixture (`:35-39`) and the sibling test at `:37-39` does
pass the configured radius. As written, the test that exists to prove "the optimized output passes the
validator" validates against `DEFAULT_SEPARATION_RADIUS_M` rather than the configured value; it is green
today only because both are 10.0, and it would silently keep passing if `configs/benchmark.json` moved to a
different radius — which is exactly the regression item 1 is meant to prevent.

`tests/test_phase6_evaluation.py:34-39` has the same shape: it calls `run_phase6(...)` without
`separation_radius_m`, so the evaluation fixture also falls back to the default. Same one-line fix
(`separation_radius_m=cfg.separation_radius_m`), lower priority because `test_cat01_separation_radius.py:250`
already proves the threading end-to-end.

SOURCES (LAYER 3 NAVIGATION)
/home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting/docs/reviews/p2-6/03-dossiers/d01-pytest-full-suite.txt
 -> The full-suite run, the collection counts, and the per-file counts
/home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting/docs/reviews/p2-6/03-dossiers/d10-environment-and-attribution.txt
 -> Proof the suite left outputs/ untouched, plus the mtime attribution used for scope
