# P2-6 adversarial review — verdict and priority actions

**Task:** `t_14be9e41` (kanban), Phase 2 part 6 of 6 — the final gate on
`smart-warehouse-slotting` Phase 2.
**Reviewed against:** `docs/PHASE_2_CONSTRAINT_ENGINE.md`, `docs/PHASE_2_EVIDENCE.json`,
`docs/PHASE_1_BASELINE_VERIFICATION.md`, the P2-1…P2-5 handoffs, and the code and artifacts themselves.

---

## Verdict: REQUEST CHANGES

Nine of the ten checklist items pass. **Item 9 (docs truthfulness) fails**: four numbers in
`PHASE_2_CONSTRAINT_ENGINE.md` are attached to the wrong object, and the document omits the one structural
fact about the delivered layout that its own evidence file records.

## First, the automatic-trigger check the checklist demands

None of the four automatic-REQUEST-CHANGES conditions fired, and that is stated first because it is the
question the orchestrator most needs answered:

| Trigger | Finding |
|---|---|
| A constraint was **weakened** | **No.** CAT-01 is still 3-D Euclidean at 10 m from `compatibility_rules` where `allowed == False` and `category_a != category_b`, boundary inclusive at `d + 1e-9 >= R`, one check per unordered bin pair, no self-comparison. I confirmed the placer's grid and the validator reach the same verdict on 11 hand-built adversarial geometries, including exactly-on-the-radius, cell-boundary straddles, negative coordinates and a 3-D diagonal — against a brute-force O(n²) oracle as well. |
| The **radius was changed** | **No.** `configs/benchmark.json:29` is `10.0`; the effective value appears in five artifacts and in `run_history`; the one radius literal left in the tree is the documented `DEFAULT_SEPARATION_RADIUS_M` constant, and no module re-declares it. A test proves the config value decides both placement and verdict by running the pipeline at 10 m and at 11 m. |
| A **test was muted** | **No.** 181 passed, 0 failed, 0 skipped, 0 xfailed, 0 errors. No `xfail`, no `expectedFailure`, no unconditional `skip` anywhere in `tests/`. The six Phase-1 failures were rewritten, not relaxed — each still asserts what it asserted before, and four now assert strictly more. |
| A number was **fabricated** | **No.** Every disputed figure is a real number from a real artifact. The defect is misattribution — `1,484,036 s` / `13.14 orders/h` are the *infeasible* as-supplied baseline's metrics quoted as the comparison baseline; `960` is the as-supplied baseline's beam-group count quoted as the optimized layout's (662); `2,336,184` is `baseline_value_as_supplied` quoted under the field name `baseline_value`. |

So the request is not a rejection of the phase. It is: the engine is sound and independently reproducible,
and the write-up overstates two performance rows and under-reports one risk.

---

## What must change before this can be approved

1. **`docs/PHASE_2_CONSTRAINT_ENGINE.md:169-170` — re-base the cycle-time and throughput rows.**
   Use the repaired comparison baseline: cycle `1,471,967 s → 747,845 s` (−49.19 %, not −49.61 %) and
   throughput `13.24 → 26.07 orders/h` (+96.90 %, not +98.40 %). If the as-supplied figures are worth keeping,
   put them in their own labelled row; `docs/PHASE_2_PART3B_BASELINE_REPAIR.md:197` already has the correct
   three-column form. As written, one table compares against the repaired baseline for travel and against the
   infeasible layout for time and throughput — the comparison §8 of the same document forbids.

2. **`docs/PHASE_2_CONSTRAINT_ENGINE.md:80` — fix the beam-check count.** The delivered optimized layout
   evaluates **662** SL-02 checks, not 960. 960 belongs to the as-supplied baseline (repaired: 922). The
   "0 SL-02 violations" claim is true; the count attached to it is not.

3. **`docs/PHASE_2_CONSTRAINT_ENGINE.md:97` — fix the quoted JSON.** `objective.baseline_value` is
   `2321711.382`; the quoted `2336184.141` is `baseline_value_as_supplied`. Quote both, correctly named.

4. **`docs/PHASE_2_CONSTRAINT_ENGINE.md:196-198` — disclose the delivered layout's structural headroom.**
   The optimized layout runs at **99.37 %** of a beam limit (214.64 / 216.00 kg), **99.56 %** of a level limit
   (458.76 / 460.80 kg) and exactly **100 %** of one bin limit. `docs/PHASE_2_EVIDENCE.json:212-223` measures
   and states this; the user-facing document discusses only the baseline's 55.6 % → 72.5 % and leaves the
   reader believing the baseline is the tight layout. For a feasibility deliverable, sub-1 % headroom on two
   independent structural scopes is the risk a reader most needs.

5. **`tests/test_phase5_optimizer.py:80` — pass the configured radius.**
   `validate_assignment(assignments, skus, wh, comp, inventory)` silently validates at the *default* 10 m
   instead of the configured value. It is green only because both are 10.0. One-line fix, and the same for
   `tests/test_phase6_evaluation.py:34-39`.

6. **`docs/PHASE_2_CONSTRAINT_ENGINE.md:58` and `:79` — two imprecise sentences.** The counting rule is "one
   check per unordered bin pair that can violate the rule (forbidden category pair, within one R-sized cell)",
   not per every bin pair (3,594 checks for 1,425 bins). And "all with the same 1e-6 tolerance" is untrue:
   LD-01 and VD-01 have no tolerance, SL-01/SL-02/RK-01 have `+1e-6`, and the placer works at `1e-9`. The two
   should share a tolerance in code as well; I found no reachable divergence on this dataset, so this is a
   contract defect, not a live violation.

None of these requires re-running the pipeline. Items 1–4 and 6 are edits to one document; item 5 is one
keyword argument in two tests.

---

## What is genuinely good, and should not be disturbed while fixing the above

* **The gate works, and I ran it rather than reading it.** `run-all` exits **0** with `evaluation_status: OK`
  when both layouts are feasible; with an infeasible, unrepairable baseline it exits **1** with
  `BLOCKED_INFEASIBLE_LAYOUT`, `comparison: []` and all 18 diagnostic rows flagged; with an infeasible
  optimized layout it exits **1** and blocks on `["optimized"]`. Both directions, real CLI, real exit codes.
* **Feasibility is the validator's, everywhere.** No path exists in which the optimizer's own flag reaches
  `feasibility` or `feasibility_status`; the summary fields come from a fresh full validation of the returned
  layout, and the evaluation re-validates both layouts from their CSVs.
* **Repair cannot oscillate, and the proof does not depend on the cycle guard.** Every accepted move strictly
  decreases `(|violations|, severity_score)` lexicographically, which is a well-founded order; the hash-based
  `seen` set is a second net, not the argument.
* **Inventory is exactly conserved and nothing is dropped silently.** 6,375 → 6,375 → 6,375 units, 1,200 SKUs
  in all three layouts, `unresolved_skus: []`, and an unplaceable SKU is reported with its binding reason
  rather than vanished.
* **The independent evidence file is real.** All 12 of its recorded sha256s still match the files on disk, so
  its `VERIFIED FEASIBLE` verdict applies to today's artifacts, not to some earlier state.
* **Scope was respected.** No `T` per line, no replenishment, no split, no 2×2, no sweep, no new dashboard
  feature; `objective.py`, `metrics.py`, `routing/`, `analytics/` and the simulator are untouched.

SOURCES (LAYER 2 NAVIGATION)
/home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting/docs/reviews/p2-6/02-analysis/01-radius-config-threading.md
 -> Item 1: how the radius reaches the placer and the judge, and where it is recorded

/home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting/docs/reviews/p2-6/02-analysis/02-cat01-semantics.md
 -> Item 2: CAT-01's exact semantics and the 11-case proof that placer and validator cannot disagree

/home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting/docs/reviews/p2-6/02-analysis/03-beam-accounting.md
 -> Item 3: beam/level/rack aggregation, the residual ledger, the "partial then topped up" question, and the two advisory findings

/home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting/docs/reviews/p2-6/02-analysis/04-repair-safety.md
 -> Item 4: boundedness, determinism, the non-oscillation argument, and two live repair runs

/home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting/docs/reviews/p2-6/02-analysis/05-feasibility-independence.md
 -> Item 5: every path checked for an optimizer self-report, and the one advisory leak in the dashboard

/home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting/docs/reviews/p2-6/02-analysis/06-evaluation-gate.md
 -> Item 6: the gate verified by three real CLI runs, with exact commands and exit codes

/home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting/docs/reviews/p2-6/02-analysis/07-test-integrity.md
 -> Item 7: the 181-passed run, why nothing was muted, and the classification of all six Phase-1 failures

/home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting/docs/reviews/p2-6/02-analysis/08-inventory-completeness.md
 -> Item 8: units before/after, and how an unplaceable SKU is reported instead of dropped

/home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting/docs/reviews/p2-6/02-analysis/09-docs-truthfulness.md
 -> Item 9 (FAIL): findings F1-F6 with the artifact value beside each disputed doc value

/home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting/docs/reviews/p2-6/02-analysis/10-scope.md
 -> Item 10: what changed in the Phase-2 window and what did not
