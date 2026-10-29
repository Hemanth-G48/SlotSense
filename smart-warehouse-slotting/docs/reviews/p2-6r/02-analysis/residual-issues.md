# Residual issues behind the verdict

Two blocking residuals (R1, R2) and three advisories (A1-A3). R1 is the same misattribution class as the
first review's F1/F3; R2 is the safety argument attached to the corrected tolerance sentence.

## R1 — §11:171 still quotes the as-supplied objective (blocking)

Line 171 of `docs/PHASE_2_CONSTRAINT_ENGINE.md`:

```
| Optimizer objective (un-normalised v1 form) | 2,336,184 → 902,393 (−61.4 %) |
```

`2,336,184` is `objective.baseline_value_as_supplied` (2,336,184.1414095755). The repaired comparison
baseline's objective is `objective.baseline_value = 2,321,711.3822095753`, which §7:97 now quotes
correctly. Recomputed improvements:

| Basis | Start | End | Improvement |
|---|---|---|---|
| Repaired baseline (the valid comparison) | 2,321,711.38 | 902,392.91 | **−61.1324 %** |
| As supplied (infeasible) | 2,336,184.14 | 902,392.91 | −61.3732 % |

The summary's headline `objective_improvement_pct` is **61.132**, not 61.4. Every other performance row in
§11 is against the repaired baseline (travel −55.65 %, cycle −49.19 %, throughput +96.90 %), so this row
silently switches bases — exactly the defect F1 fixed for cycle and throughput two rows above.

**Proposed fix:** `2,321,711 → 902,393 (−61.13 %)`, or keep the number and label the row
`(as supplied → optimized, −61.37 %)`. Either is honest; the unlabelled mix is not.

## R2 — §5:79's safety argument is false for LD-01/VD-01 (blocking)

The corrected sentence states the tolerances accurately, then concludes:

> The divergence is safe in the direction that matters — the placer is stricter than the validator, so it
> cannot accept a placement the validator would reject.

The code does not support the general claim:

| Rule | Validator | Placer | Who is stricter |
|---|---|---|---|
| `LD-01` bin weight | `total <= max_weight_kg`, no tolerance (`validator.py:406`) | `n*unit <= residual + 1e-9` (`optimizer.py:1208`); guard allows residual ≥ −1e-9 (`:561`) | **validator** by up to 1e-9 kg |
| `VD-01` bin volume | `total <= usable_volume_cm3`, no tolerance (`validator.py:428`) | same 1e-9 affordability; guard allows residual ≥ −1e-6 cm³ (`:564`) | **validator** by up to 1e-6 cm³ |
| `SL-02` beam | `load <= limit + 1e-6` (`validator.py:602`) | 1e-9 | placer |
| `SL-01` level | `load <= limit + 1e-6` (`validator.py:615`) | 1e-9 | placer |
| `RK-01` rack | `load <= limit + 1e-6` (`validator.py:628`) | 1e-9 | placer |

So for `LD-01`/`VD-01` the placer can, in principle, accept a placement the validator rejects — by at
most 1e-9 kg / 1e-6 cm³. The divergence is empirically unreachable on this dataset: 1,027 distinct
canonical unit weights against 11 boundary residuals (plus the exact `n*unit` boundaries) produced 0 cases
where the placer accepts a quantity in `(residual, residual + 1e-9]` (dossier `d01`), and all three
layouts record zero `LD-01`/`VD-01` violations (dossier `d04` / evidence file). The true statement is
"unreachable on this dataset", not "cannot happen by construction".

**Proposed fix:** keep the tolerance sentence, replace the conclusion with: "For the aggregate scopes the
placer is stricter than the validator (+1e-9 vs +1e-6). For `LD-01`/`VD-01` its 1e-9 is marginally looser
than an exact comparison, but no reachable divergence exists on this dataset: every canonical unit weight
against boundary residuals found none, and all three layouts have zero `LD-01`/`VD-01` violations."

## A1 — phase-6 fixture still uses the default radius (advisory)

`tests/test_phase6_evaluation.py:34-40` calls:

```python
result = run_phase6(
    PROCESSED,
    scenario="A",
    out=base / "evaluation",
    optimized_path=base / "optimized" / "optimized_assignments.csv",
)
```

`run_phase6`'s `separation_radius_m` defaults to `DEFAULT_SEPARATION_RADIUS_M`
(`src/simulation/pipeline.py:136-140`), so the fixture validates at 10.0 whatever
`configs/benchmark.json` says. This is the second half of the first review's item 5 (which named both
tests); the card's restatement named only the phase-5 test, so it is not counted as a failed item. Adding
`separation_radius_m=cfg.separation_radius_m` (the fixture already loads `cfg` at line 32) closes it.

## A2 — §4:58 does not name the layout in its example (advisory)

"3,594 checks for 1,425 occupied bins" is true of the as-supplied baseline. The repaired baseline also has
1,425 bins but records **1,039** CAT-01 checks; the optimized layout has 1,288 bins and **0** CAT-01 checks
(its closest forbidden pair is 27.2 m, so no pair enters the window). Saying "the 1,425 bins of the
as-supplied baseline" removes the last way to misread the example.

## A3 — §11.2's "0.6 % increase would flip the layout" is 0.04 pp too tight (advisory)

The beam headroom is 1.364 kg on a 214.636 kg load = **0.6354 %**. A 0.6 % increase adds 1.288 kg, leaving
0.076 kg, so the layout would still be feasible; the flip threshold is a **0.64 %** increase. The point of
the paragraph — sub-1 % headroom, brittle to inventory change — is right; only the threshold is slightly
off. "a 0.64 % increase" or "well under 1 % more stock" would be exact.

SOURCES (LAYER 3 NAVIGATION)
/home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting/docs/reviews/p2-6r/03-dossiers/d01-probe-output.txt
 -> Objective recomputation, the bin-at-limit count and the 1,027-weight tolerance probe

/home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting/docs/reviews/p2-6r/03-dossiers/d02-code-citations.txt
 -> Validator and placer tolerance code behind the R2 table

/home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting/docs/reviews/p2-6r/03-dossiers/d04-evidence-fields.txt
 -> objective fields, improvement percentages, beam/level utilisation, CAT-01 counts

/home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting/docs/reviews/p2-6r/03-dossiers/d07-doc-lines.txt
 -> Verbatim §5/§11/§11.2 lines and the phase-6 fixture
