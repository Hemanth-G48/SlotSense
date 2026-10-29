# Item 3 — the §11 objective row is on the repaired baseline and recomputes

**Question.** §7 was corrected on the previous pass but §11:171 (as the file then stood) still quoted the
as-supplied objective
(`2,336,184`) against the optimized value, producing `−61.4 %` on a mixed base. Is the row now on one base,
and does the percentage follow from the artifact?

**Answer: PASS.**

## The field the row must quote

`outputs/optimized/optimization_summary.json:78-86` carries three objective values, not one:

```
"objective": {
  "value": 902392.9055567493,
  "baseline_value": 2321711.3822095753,            <- repaired baseline (the comparison baseline)
  "baseline_value_as_supplied": 2336184.1414095755, <- the infeasible layout, diagnostic only
  "starter_value": 902392.9055567493,
  ...
}
```

The run's own `baseline_variant` is `repaired_minimal` (`:4`), and `baseline_objective` (`:128`) repeats
`2321711.3822095753`. So the comparison base for every "vs baseline" row in §11 is **2,321,711**, and
`2,336,184` is a different layout's number.

## What the document says now

`docs/PHASE_2_CONSTRAINT_ENGINE.md:178`:

```
| Optimizer objective (un-normalised v1 form, repaired baseline → optimized) | 2,321,711 → 902,393 (**−61.13 %**) |
```

- Both figures round correctly: `2321711.3822095753 → 2,321,711`, `902392.9055567493 → 902,393`.
- The row is labelled with its base ("repaired baseline"), which is what was missing before.

## Re-derivation

```
(2321711.3822095753 − 902392.9055567493) / 2321711.3822095753 × 100 = 61.132425 %
```

rounded to two decimals: **61.13 %**. The artifact's own summary field agrees exactly:
`objective_improvement_pct = 61.132` (`optimization_summary.json:139`).

Cross-checks against the other direction, so the two bases cannot be confused again:

| Base | Baseline value | Optimized | Recomputed | Artifact field |
|---|---|---|---|---|
| repaired (used) | 2,321,711.382 | 902,392.906 | **61.1324 %** → 61.13 % | `objective_improvement_pct = 61.132` |
| as supplied (diagnostic) | 2,336,184.141 | 902,392.906 | 61.3732 % → 61.37 % | `objective_improvement_pct_vs_as_supplied = 61.373` |

Note the old row's `−61.4 %` was also mis-rounded on its own (wrong) base: 61.3732 % rounds to 61.37 %, not
61.4 %. The retracted string does not appear anywhere in the document:

```
$ grep -n -e "2,336,184" -e "2336184" -e "61.4" docs/PHASE_2_CONSTRAINT_ENGINE.md
(no output)
```

The §7 JSON block (`:104`) still shows `"baseline_value": 2321711.382`, so §7 and §11 now quote the same
field, and `2,336,184` appears nowhere in the doc — including in §14 limitation 2, which describes the
as-supplied baseline without quoting its objective (correctly, since it is not a compared value).

## Why this is a pass rather than a pass-with-a-note

The prior failure mode was a *mixed base*: a percentage computed from two different layouts. The row now has
one base, a label naming it, and a rounded value that matches both the arithmetic and the artifact's own
percentage field to three decimals. There is nothing left to reconcile.

SOURCES (LAYER 2 NAVIGATION)
/home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting/docs/reviews/p2-6r2/03-dossiers/d01-probe-output.txt
 -> The probe run that printed the three objective fields and recomputed both percentages

/home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting/docs/reviews/p2-6r2/03-dossiers/d03-doc-greps.txt
 -> The grep proving 2,336,184 / 2336184 / 61.4 are absent, plus the §11 row verbatim

/home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting/docs/reviews/p2-6r2/03-dossiers/d04-artifact-fields.txt
 -> optimization_summary.json objective block and both improvement-percentage fields with line numbers

/home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting/outputs/optimized/optimization_summary.json
 -> The artifact of record for objective.value, objective.baseline_value and objective_improvement_pct
