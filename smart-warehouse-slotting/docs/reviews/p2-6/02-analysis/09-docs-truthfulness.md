# Item 9 — Docs truthfulness

**Verdict: FAIL** — four misattributed numbers and one material omission in
`docs/PHASE_2_CONSTRAINT_ENGINE.md`, all traceable and all fixable without re-running anything.

## What the checklist asked

Every number in `PHASE_2_CONSTRAINT_ENGINE.md` traces to evidence; no "valid improvement" claim if a layout
is infeasible; `BUILD_STATUS_REPORT.md` not marked complete.

## What is sound

The headline claims hold, and I re-derived each of them from the delivered artifacts rather than from the
doc:

| Claim | Re-derived | Source |
|---|---|---|
| −55.65 % travel vs the repaired baseline | **−55.653 %** (1,691,478.55 m → 750,119.50 m) | `evaluation_summary.json` |
| Repair cost −0.92 % travel | **−0.919 %** (1,707,167.15 m → 1,691,478.55 m) | `evaluation_summary.json.diagnostic_baseline` |
| Violations 1,071 → 0 → 0 | **1,071 / 0 / 0** | `optimization_summary`, `validation_status`, `evaluation_summary` |
| Checks 20,699 / 18,077 / 15,167 | **20,699 / 18,077 / 15,167** | `optimization_summary`, `evaluation_summary` |
| Rows/SKUs/units 1,425/1,200/6,375 and 1,288/1,200/6,375 | exact | the three assignment CSVs |
| 13 forbidden pairs | **13** | `optimization_summary.separation_grid.forbidden_pairs` |
| Grid: 1,293 queries, 0 rejections | **1,293 / 0** | same |
| Canonical repair not exercised (0 moves) | **0 / 0 / `already_feasible`** | `optimization_summary.repair` |
| 96 records relocated, 93 SKUs, 0 quantity changes | **96 / 1,425 records, 6.737 %**, conservation exact | `evaluation_summary.baseline_repair` |
| 18 comparison rows | **18** | `evaluation_summary.comparison` |
| Repaired-baseline max beam utilisation 72.5 % (from 55.6 %) | **72.49 %** (from **55.56 %**) | independent aggregation, `03-dossiers/d07-beam-headroom.txt` |
| No "valid improvement" claim against an infeasible layout | correct — the doc states the comparison is against the repaired baseline and that the as-supplied one is diagnostic only | §8, §11, §14.2 |
| `BUILD_STATUS_REPORT.md` not marked complete | correct — it still classifies the build as 8 executed / 8 partial / 4 not built and ends with a numbered "still missing" list | `reports/BUILD_STATUS_REPORT.md` §0 and §8 |

`docs/PHASE_2_EVIDENCE.json` is genuinely current, not aspirational: **12/12 recorded sha256s still match the
files on disk** (`03-dossiers/d08-evidence-sha256-check.txt`), including both summaries and all three
assignment CSVs.

## F1 (major) — §11's cycle-time and throughput rows compare against the *infeasible* layout

`docs/PHASE_2_CONSTRAINT_ENGINE.md:169-170`:

```
| Cycle time | 1,484,036 s → 747,845 s |
| Throughput | 13.14 → 26.07 orders/h |
```

Those two baseline figures are `1,484,035.5` and `13.14` — the **as-supplied** (`diagnostic_baseline`)
metrics. The repaired comparison baseline is `1,471,967.35 s` and `13.24 orders/h`. Both are in the delivered
`evaluation_summary.json`, side by side:

```
baseline (repaired)      total_route_time_sec 1,471,967.35   throughput_orders_per_hr 13.24
diagnostic_baseline      total_route_time_sec 1,484,035.50   throughput_orders_per_hr 13.14
```

So the same table mixes bases: its travel row is against the repaired baseline (−55.65 %), while its cycle and
throughput rows are against the layout §8 says must not be compared. The effect is to flatter the result —

| Measure | As written (infeasible baseline) | Correct (repaired baseline) |
|---|---|---|
| Cycle-time reduction | −49.61 % | −49.19 % |
| Throughput gain | +98.40 % | +96.90 % |

**Fix:** use the repaired-baseline figures (`1,471,967 s`, `13.24 orders/h`) and, if the as-supplied numbers
are worth keeping, put them in a separate labelled row — `docs/PHASE_2_PART3B_BASELINE_REPAIR.md:197` already
does exactly that with a three-column `13.14 → 13.24 → 26.07`. The error appears to have crept in when that
table was condensed.

## F2 (major) — §5 attributes the wrong beam-check count to the optimized layout

`docs/PHASE_2_CONSTRAINT_ENGINE.md:80`:

> Verified empirically: the optimized layout has **0 `SL-02` violations** over 960 beam checks (Phase 1 had 4).

960 is the **as-supplied baseline's** beam-group count. The optimized layout evaluates **662** SL-02 checks.
The delivered file says so directly:

```
validation_checks_optimized.csv      SL-02 rows = 662, failures = 0
validation_checks_baseline.csv       SL-02 rows = 922, failures = 0
outputs/validation_checks_baseline.csv (as supplied)   SL-02 rows = 960, failures = 0
```

and `docs/PHASE_2_EVIDENCE.json:213-215` records `beam_groups` as 960 / 922 / 662 for the three layouts. The
claim "0 SL-02 violations" is true; the count attached to it is not.

**Fix:** "…over **662** beam checks (the as-supplied baseline evaluates 960 and the repaired one 922; Phase 1's
optimizer output had 4 failures)."

## F3 (major) — §7 quotes a JSON field value the field does not hold

`docs/PHASE_2_CONSTRAINT_ENGINE.md:97`:

```json
"objective": {"value": 902392.906, "baseline_value": 2336184.141, "per_rule_violations": {},
```

The delivered `optimization_summary.json` has

```
objective.value                     902392.9055567493
objective.baseline_value            2321711.3822095753     <-- the repaired baseline
objective.baseline_value_as_supplied 2336184.1414095755    <-- the number the doc quotes
```

Every other figure in that block matches. The excerpt is presented as the artifact and is not the artifact;
a reader who trusts the field name will believe the summary compares against an infeasible layout.

**Fix:** change to `"baseline_value": 2321711.382, "baseline_value_as_supplied": 2336184.141`, or label the
excerpt as abridged.

## F4 (major) — the doc omits the delivered layout's structural headroom, which its own evidence records

`docs/PHASE_2_CONSTRAINT_ENGINE.md:196-198` is the only place headroom is discussed:

> **Repair packs some beams harder**: max beam utilisation rises from **55.6 %** (as supplied) to **72.5 %**
> (repaired) — still legal, but the feasible baseline sits closer to the `SL-02` limit than the infeasible one
> did. Any further repair would need to watch that scope.

That is accurate about the baseline, and it leaves the reader with the opposite of the important fact. The
**delivered optimized layout** is the tight one:

| Scope | Load | Limit | Utilisation |
|---|---|---|---|
| optimized beam `R5-3-1 bay 0 shelf 3` | 214.64 kg | 216.00 kg | **99.37 %** (1.36 kg headroom) |
| optimized level `R5-3-1 shelf 1` | 458.76 kg | 460.80 kg | **99.56 %** (2.04 kg headroom) |
| optimized bin `LOC002136` | 30.00 kg | 30.00 kg | **100.00 %** (exactly at the LD-01 limit) |
| repaired baseline, tightest beam | 130.49 kg | 180.00 kg | 72.49 % |

For a phase whose deliverable is "constraints enforced, verified", that is material: the shipped answer has
well under 1 % headroom on two independent structural scopes, so any change to SKU weights, quantities or the
topology would breach `SL-02` or `SL-01` before it affected anything else. The omission is not an error of
measurement — `docs/PHASE_2_EVIDENCE.json:212-223` measures it and says so:

> `"optimized": {"beam_groups": 662, "over_limit": 0, "max_utilisation_pct": 99.37}`
> `"note": "Beam limits are nearly binding in the optimized layout (99.4 % of the tightest beam) but not
> exceeded; no SL-02 violation remains in any delivered layout."`

**Fix:** add that sentence and a row to §11.1, and note the level scope (99.56 %) and the one bin sitting
exactly on its LD-01 limit, which the evidence file does not mention at all.

## F5 (minor) — §4's counting rule is imprecise

`docs/PHASE_2_CONSTRAINT_ENGINE.md:58`: "one check per unordered bin pair; a bin is never compared with
itself." A check is recorded per unordered bin pair **whose categories are a forbidden pair and which fall in
the same or an adjacent R-sized cell** — 3,594 checks for 1,425 bins on the as-supplied layout, not ~1 M. The
"never compared with itself" half is correct.

**Fix:** "one check per unordered bin pair that can violate the rule (forbidden category pair, within one
R-sized cell)."

## F6 (minor) — §5's tolerance sentence is false

`:79` "Precedence matches the validator: bin → beam → level → rack, all with the same 1e-6 tolerance." The
validator applies `+1e-6` only to SL-01/SL-02/RK-01; LD-01 and VD-01 have **no** tolerance; the placer uses
`1e-9` and its volume guard tolerates `1e-6`, i.e. looser than VD-01. Full table in
`02-analysis/03-beam-accounting.md`. No reachable divergence exists on this dataset
(`03-dossiers/d09-tolerance-hunt.txt`), so this is a documentation statement that is simply untrue of the
code.

## Advisory — the build status report is stale even though it is not "complete"

`reports/BUILD_STATUS_REPORT.md` passes the letter of the check (it is not marked complete), but its body
contradicts its own update blocks:

* §0 says "Nothing has been run end-to-end on this machine — the pipeline needs pandas and the venv is empty —
  so no result in this repository is *verified*", while the Phase-1 and Phase-2 blocks at the top say the
  environment is resolved and the suite runs.
* §0's table row "**End-to-end run** | **1** | `run-all` completes locally — but publishes results from an
  infeasible baseline (see §6)" was true before the baseline repair and is not true now.
* §9's reproduction block still says "full pipeline — **BLOCKED** until pandas is installed" and passes
  `--fit-scenario A --eval-scenario B`, which `app/main.py` does not accept (`run-all` takes `--config`,
  `--processed`, `--seed`, `--scenario` only). The command as written fails.

Not part of this card's verdict, but the document will mislead whoever reads it next.

SOURCES (LAYER 3 NAVIGATION)
/home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting/docs/reviews/p2-6/03-dossiers/d06-doc-claim-crosscheck.txt
 -> Every doc number checked against the artifact it names, with the three misattributions shown side by side
/home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting/docs/reviews/p2-6/03-dossiers/d07-beam-headroom.txt
 -> The headroom figures the doc omits
/home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting/docs/reviews/p2-6/03-dossiers/d05-artifact-numbers.txt
 -> The full artifact dump the "what is sound" table is derived from
