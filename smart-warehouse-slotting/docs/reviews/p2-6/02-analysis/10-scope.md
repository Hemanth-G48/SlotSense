# Item 10 — Scope: no Phase 3/4 work, no unrelated refactors

**Verdict: PASS** (evidence is mtime-plus-change-list, because the working copy has no VCS)

## What the checklist asked

No Phase 3/4 work (T per line, replenishment, split, 2×2, sweep, new dashboard features) and no unrelated
refactors.

## The working copy has no VCS

```
$ git status --short
fatal: not a git repository (or any parent up to mount point /)
```

So scope cannot be argued from a diff. It is argued from two independent things: which files changed inside
the Phase-2 window, and what the Phase-2 change lists say they changed.

## Files touched in the Phase-2 window (2026-10-29 02:42 – 04:48)

```
02:42  src/models/config.py                    radius field + validation
02:43  src/optimization/separation.py          NEW — CAT-01 placement grid
03:01  tests/test_phase2_greedy_constraints.py  NEW
03:20  app/dashboard_data.py                   gate labelling
03:26  app/dashboard.py                        gate labelling + radius threading
03:40  tests/test_cat01_separation_radius.py   NEW
03:43  tests/test_feasibility_gate.py          NEW
03:44  tests/phase2_fixtures.py                NEW
03:44  tests/test_artifact_isolation.py        NEW
03:45  tests/test_phase4_validator.py          legacy test rewritten
03:45  tests/test_phase5_optimizer.py          legacy test rewritten
03:45  tests/test_phase6_evaluation.py         legacy test rewritten
03:46  tests/test_phase8_integration.py        legacy test rewritten
03:50  tests/test_determinism.py               NEW
03:50  tests/test_inventory_integrity.py       NEW
03:57  tests/test_structural_scopes.py         NEW
04:14  src/optimization/optimizer.py           beam ledger, CAT-01 gate, repair
04:14  src/validation/validator.py             radius threading + pair identity
04:15  src/optimization/baseline.py            NEW — feasibility-only baseline repair
04:16  src/optimization/pipeline.py            status separation, repair stats
04:48  app/main.py                             non-zero exit on gate block
04:48  src/simulation/pipeline.py              evaluation gate
04:48  tests/test_baseline_repair.py           NEW
```

Every one of those files is named in `docs/PHASE_2_PART2_REPAIR_AND_GATE.md:239-245` or
`docs/PHASE_2_PART3B_BASELINE_REPAIR.md`. Nothing appears that the change lists do not account for.

## Nothing from Phase 3/4

| Phase 3/4 item | Status |
|---|---|
| `T` per order line / `demand_weighted_depot_distance` | **Not done.** `src/optimization/objective.py` was last modified 2026-10-28 23:23 — before Phase 2 — and still implements the v1 form `alpha*D + beta*A + gamma*E + delta*U` (`objective.py:1-50`). Doc §14.5 says the same. |
| Replenishment metric/term | **Not done.** `grep -rniE "replenish"` in `src/` and `app/` finds only explicit "Not modeled" statements (`app/dashboard.py:1820-1828`, `app/dashboard_data.py:1038-1040, 1097`). No implementation, no new field. |
| Fit/holdout split | **Not done.** No `split` dataset code; the only `split` hits are `str.split` on CSV columns. |
| 2×2 pick-rule experiment | **Not done.** No occurrence anywhere in `src/` or `app/`. |
| Weight sweep | **Not done.** No occurrence; `moves_evaluated` is still the annealing iteration count, not a sweep. |
| New dashboard features | **Not done.** `app/dashboard.py` and `app/dashboard_data.py` changed only to render a blocked evaluation as blocked, show `feasibility_status`/repair stats/completeness, and pass the configured radius into the dashboard-triggered evaluation — exactly the three items listed in `docs/PHASE_2_PART2_REPAIR_AND_GATE.md:126-130, 239-242`. `BUILD_STATUS_REPORT.md` §8 still lists "Dashboard segment rows + run/zone/class filters" as **not built**. |

## Unrelated refactors

The untouched list is the evidence that this was not a broad sweep:

```
src/analytics/*            unchanged (18:14)
src/data_processing/pipeline.py, derive.py, eda.py   unchanged (18:14)
src/evaluation/metrics.py  unchanged (18:14)
src/models/io.py, synthetic.py                       unchanged (18:14)
src/routing/graph.py, heuristics.py                  unchanged (23:23 / 18:14)
src/simulation/simulator.py                          unchanged (18:14)
src/validation/audit.py, loader.py                   unchanged (18:14 / 02:04, Phase 1)
```

`src/data_processing/{schema,generate}.py`, `src/models/entities.py`, `src/validation/loader.py` and
`tests/test_structural_and_separation.py` carry 02:03-02:08 timestamps — that is the **Phase-1** structural-limit
metadata repair described in `docs/PHASE_1_BASELINE_VERIFICATION.md` §E.5 (hence
`dataset/processed/locations.csv.bak-pre-limits`), not Phase-2 work.

## Caveat

Without a VCS I cannot prove the *contents* of a touched file were not also refactored. I read
`optimizer.py`, `validator.py`, `pipeline.py` (both), `baseline.py`, `separation.py`, `app/main.py` and
`src/simulation/pipeline.py` in full for this review; nothing in them is unrelated to constraint enforcement,
feasibility reporting or the gate. That is a judgement from reading, and it is the strongest statement the
absence of version control allows.

SOURCES (LAYER 3 NAVIGATION)
/home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting/docs/reviews/p2-6/03-dossiers/d10-environment-and-attribution.txt
 -> The mtime listing both halves of this analysis are built from
