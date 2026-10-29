# P2-6R verdict — REQUEST CHANGES

**Question.** Do the six changes requested in the first review of item 9 (docs truthfulness) hold, without
introducing a new inaccuracy?

**Verdict: REQUEST CHANGES.** Four of the six are fully fixed (items 1, 2, 4, 5). Item 3 is fixed in §7 but
the same misattribution survives at §11:171. Item 6 states the right tolerances but justifies them with a
claim that is false for two of the five rules it lists. Both remaining edits are one line each.

## Per-item status

| # | Required change | Status | Where it stands |
|---|---|---|---|
| 1 | Cycle time / throughput re-based on the repaired baseline | **PASS** | §11:169-170 = 1,471,967 s → 747,845 s (−49.19 %) and 13.24 → 26.07 orders/h (+96.90 %); both recompute exactly, and no `1,484,036` / `13.14` remains in the doc |
| 2 | Beam-check count attributed to the optimized layout | **PASS** | §5:80 = 662 optimized, 922 repaired, 960 as supplied; all three match the evidence file |
| 3 | `objective.baseline_value` = 2321711.382 in §7 | **PASS in §7, residual in §11** | §7:97 matches the artifact; §11:171 still quotes 2,336,184 (the as-supplied value) with no label, so the doc now contradicts itself — see R1 |
| 4 | Structural headroom disclosed | **PASS** | §11.2:206-218 and §14:250 carry the 99.37 % beam, 99.56 % level and one-bin-at-limit disclosures; all three re-derived, including `LOC002136` at exactly 30.00/30.00 kg |
| 5 | Configured radius in `tests/test_phase5_optimizer.py` | **PASS as carded** | The call now passes `separation_radius_m=cfg.separation_radius_m` (:80-83) with the assertion unchanged (:84); the test passes. A1 notes the sibling phase-6 fixture, which my original item 5 also named |
| 6 | Precise §4 counting and §5 tolerances | **PARTIAL** | §4:58 is correct; §5:79 states the right tolerances but its "the placer is stricter … cannot accept a placement the validator would reject" clause is false for `LD-01`/`VD-01` — see R2 |

## Required before approval

**R1 — `docs/PHASE_2_CONSTRAINT_ENGINE.md:171`, re-base the objective row.** The row
`| Optimizer objective (un-normalised v1 form) | 2,336,184 → 902,393 (−61.4 %) |` quotes
`baseline_value_as_supplied`, not the repaired `baseline_value` that §7:97 now names. Recomputed:
−61.3732 % as supplied, **−61.1324 % repaired**; the summary's headline `objective_improvement_pct` is
**61.132**. Change to `2,321,711 → 902,393 (−61.13 %)`, or keep 2,336,184 and label the row
`(as supplied → optimized, −61.37 %)`. This is the last "mixes bases" row in a table whose other rows are
against the repaired baseline.

**R2 — `docs/PHASE_2_CONSTRAINT_ENGINE.md:79`, correct the safety argument.** The placer is stricter than
the validator only for `SL-01`/`SL-02`/`RK-01` (+1e-9 vs +1e-6). For `LD-01`/`VD-01` the validator compares
with no tolerance, while the placer accepts `n*unit <= residual + 1e-9` and its guard tolerates a residual
down to −1e-9 kg / −1e-6 cm³ — i.e. marginally **looser**, not stricter. Replace the clause with: "for the
aggregate scopes the placer is stricter than the validator; for `LD-01`/`VD-01` its 1e-9 is marginally
looser than an exact comparison, and no reachable divergence exists on this dataset (1,027 unit weights
against boundary residuals found none; all three layouts have zero `LD-01`/`VD-01` violations)." This keeps
the honest statement and drops the false generalization.

## Advisory (not blocking)

**A1 — `tests/test_phase6_evaluation.py:34-40`.** The evaluation fixture still calls `run_phase6(...)`
without `separation_radius_m`, so it falls back to `DEFAULT_SEPARATION_RADIUS_M` (`pipeline.py:136-140`).
This was the second half of my original item 5; the card's restatement named only the phase-5 test. One
keyword argument closes it.

**A2 — `docs/PHASE_2_CONSTRAINT_ENGINE.md:58`.** Name the layout in the 3,594/1,425 example. 1,425 bins is
shared by both baselines, but 3,594 is the as-supplied count; the repaired baseline records 1,039 CAT-01
checks and the optimized layout records 0 (its closest forbidden pair is 27.2 m, so no pair enters the
window). "3,594 checks for the 1,425 bins of the as-supplied baseline" removes the last ambiguity.

**A3 — `docs/PHASE_2_CONSTRAINT_ENGINE.md:214`.** "a 0.6 % increase in stock on one beam … would flip the
layout infeasible" is 0.04 pp too tight: the headroom is 1.364 kg on a 214.636 kg load = 0.6354 %, so a
0.6 % increase (1.288 kg) still fits and the flip threshold is 0.64 %. The paragraph's point stands; say
"a 0.64 % increase" or "well under 1 %".

## Implication

The Phase 2 engine, gate and evidence are unchanged and still sound; this is a documentation-sign-off
question. Approve once R1 and R2 are applied. Items 1, 2, 4 and 5 need no further work.

SOURCES (LAYER 2 NAVIGATION)
/home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting/docs/reviews/p2-6r/02-analysis/six-item-verification.md
 -> Per-item evidence: artifact values, line references, and the re-derivation behind every PASS

/home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting/docs/reviews/p2-6r/02-analysis/residual-issues.md
 -> Why R1 and R2 are blocking, the code paths that decide R2, and the three advisories
