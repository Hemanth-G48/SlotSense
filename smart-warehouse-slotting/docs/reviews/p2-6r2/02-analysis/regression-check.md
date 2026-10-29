# Criterion 3 — nothing else regressed

**Question.** The card fixes two items and requires that the rest of the document, which passed on the two
previous passes, has not moved. Did it?

**Answer: PASS.** Only one file changed since the last review, it is the document under review, and every
numeric claim outside the two edited spots still matches the artifacts. One pre-existing inaccuracy surfaced
while checking (the quoted optimizer runtime); it is not a regression, and it is recorded as advisory A5.

## What actually changed

| Evidence | Reading |
|---|---|
| `stat docs/PHASE_2_CONSTRAINT_ENGINE.md` | `2026-10-29 05:50:07` — modified 1 minute after my previous verdict (`docs/reviews/p2-6r/01-summary/verdict.md`, 05:49) |
| `find src tests configs -newermt '2026-10-29 05:49:30'` | **no output** — no source, test or config file changed since the last pass |
| newest `src/` file | `src/simulation/pipeline.py` at 04:48; `optimizer.py` and `validator.py` at 04:14 |
| `outputs/optimized/optimization_summary.json` | 04:50:35 — unchanged since the last pass |
| `outputs/evaluation/evaluation_summary.json` | 04:50:45 — unchanged since the last pass |
| `docs/PHASE_2_EVIDENCE.json` | 05:13:32 — unchanged since the last pass |
| document length | 284 → **291 lines** (+7), exactly the growth of the §5 bullet list (2 → 7 lines) plus the retitled §11 row |

So the regression surface is prose only. The engine, the gate, the artifacts and the test suite are the same
objects the previous two passes measured. The suite was re-run anyway, twice, because §10 makes a counted
claim: **181 passed, 0 failed, 0 skipped** in 238.07 s and again in 239.59 s
(`03-dossiers/d06-test-run.txt`). The document's §10 quotes 248.22 s with a 219.96 s repeat run — same count,
wall clock varies by run, which the document already says.

## Numeric claims re-checked, outside §5:79-86 and §11:178

| # | Claim in the document | Where | Value re-derived | Verdict |
|---|---|---|---|---|
| 1 | §4: the tightest beam limit is "55.6 %" used | §4:69 | evidence `max_beam_utilisation_pct: 55.56` (as-supplied) | matches (layout unnamed — A4) |
| 2 | §4: "34.7 % of the level limit" | §4:70 | evidence `max_level_utilisation_pct: 34.72` (as-supplied) | matches (A4) |
| 3 | optimized `SL-02` beam groups = 662 | §5:87 | evidence `beam_groups_checked: 662` (`:169`) | matches |
| 4 | repaired baseline beam groups = 922 | §5:87 | evidence `:139` | matches |
| 5 | as-supplied beam groups = 960 | §5:87 | evidence `:104` | matches |
| 6 | §7 `"value": 902392.906` | §7:104 | `optimization_summary.json:79` = `902392.9055567493` | matches |
| 7 | §7 `"baseline_value": 2321711.382` | §7:104 | `:80` = `2321711.3822095753` | matches |
| 8 | §7 `per_rule_violations: {}`, `violation_severity_score: 0`, `globally_optimal: false` | §7:104-105 | `:83-85` | matches |
| 9 | `assignment_completeness` 6,375 / 6,375 / 0 / 100.0 / `[]` | §7:102 | `:70-76` | matches |
| 10 | baseline rows / optimized rows = 1,425 / 1,288 | §11:167-169 | evidence `n_assignments: 1425`; `n_assignments: 1288` (`:114`) | matches |
| 11 | SKUs 1,200 and units 6,375 in all three layouts | §11:167-169 | `n_skus_with_inventory: 1200`, `inventory_units: 6375` (`:116-117`) | matches |
| 12 | checks 20,699 / 18,077 / 15,167 | §11:167-169 | evidence `:82`, `:118`, `:148` (and the verifier's formula at `:372-375` reconciles each) | matches |
| 13 | as-supplied `CAT-01` = 1,071 | §11:167 | evidence `:83`, `:205` | matches |
| 14 | baseline travel 1,707,167 → 1,691,479 (−0.92 %) | §11:173 | evaluation `total_travel_distance_m` 1,707,167.15 (`:394`) and 1,691,478.55 (`:94`); recomputed **0.9190 %** | matches |
| 15 | optimized travel 750,120 m | §11:174 | `750119.5` (`:123`) | matches |
| 16 | optimized vs repaired = −55.65 % | §11:175 | recomputed **55.6530 %** | matches |
| 17 | cycle time 1,471,967 s → 747,845 s (−49.19 %) | §11:176 | evaluation `total_route_time_sec` 1,471,967.35 → 747,845.0, `percent_change: -49.19` | matches |
| 18 | throughput 13.24 → 26.07 orders/h (+96.90 %) | §11:177 | evaluation `:100`, `:129`; recomputed **96.9033 %** | matches |
| 19 | worst beam `R5-3-1 bay 0 shelf 3` 214.64 / 216.00 kg = 99.37 % | §11.2:217 | re-aggregated from `optimized_assignments.csv` × `products.csv` × `locations.csv`: 214.636 / 216.0 = **99.3685 %** | matches |
| 20 | worst level `R5-3-1 shelf 1` 458.76 / 460.80 kg = 99.56 % | §11.2:218 | re-aggregated: 458.757 / 460.8 = **99.5566 %** | matches |
| 21 | one bin at its `LD-01` limit, 100.00 % | §11.2:219 | re-aggregated: exactly one bin, `LOC002136`, 30.000 / 30.0 kg | matches |
| 22 | gate on the canonical run: `exit 0`, `OK`, `comparison_valid: true` | §11.1:194 | evaluation `evaluation_status: OK` (`:6`), `comparison_valid: true` (`:88`), `blocked_layouts: []` (`:90`), `baseline_variant: repaired_minimal` (`:8`) | matches |
| 23 | radius 10.0 from configuration | §4:59, §9 | evaluation `separation_radius_m: 10.0`; `optimization_summary.json:113` | matches |
| 24 | optimizer runtime "32.5 s for 600 moves (16 accepted)" | §11:179 | `runtime_sec: 33.858`; `moves_evaluated: 600`; `moves_accepted: 16` | **counts match, runtime is stale — A5** |

Independent re-aggregation (items 19-21) used only the delivered CSVs and the dataset, not pipeline code, and
confirms all three layouts are structurally legal: no beam, level or bin exceeds its limit
(`03-dossiers/d05-regression-probe.txt`).

## Advisory A5 — the runtime quote is stale (pre-existing, not a regression)

`§11:179` says "32.5 s for 600 moves (16 accepted)". The delivered summary records `runtime_sec: 33.858`
(`optimization_summary.json:153`), and my first-pass dossier already recorded `33.858`
(`docs/reviews/p2-6/03-dossiers/d05-artifact-numbers.txt:33`). The move counts are right; only the wall-clock
figure is off by ~4 %, apparently from an earlier run. Since the doc is being edited for R1 anyway, changing
"32.5 s" to "33.9 s" (or "≈34 s") closes it. It is not part of this card's scope and does not gate approval.

## What "no regression" does not cover

Items 1, 2, 4 and 5 of the previous pass are *not* re-litigated here: their subject matter (§11 cycle/throughput
rows, §5 beam counts, §11.2 headroom, the phase-5 test's configured radius) is in the table above only as a
regression check, and each still matches. The two advisory items from the previous pass (A2, the unnamed layout
behind "3,594 checks"; A3, the 0.6 % vs 0.64 % headroom threshold) are unchanged and still open — both are
phrasing improvements, not errors of fact that affect a conclusion.

SOURCES (LAYER 2 NAVIGATION)
/home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting/docs/reviews/p2-6r2/03-dossiers/d05-regression-probe.txt
 -> The re-aggregation output (gate fields, travel/cycle/throughput, top beams/levels/bins) and the awk arithmetic

/home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting/docs/reviews/p2-6r2/03-dossiers/d04-artifact-fields.txt
 -> The raw artifact lines behind claims 6-13 and 22-24, with file:line references

/home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting/docs/reviews/p2-6r2/03-dossiers/d01-probe-output.txt
 -> The objective fields, shared with the item-3 analysis

/home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting/docs/reviews/p2-6r2/03-dossiers/d06-test-run.txt
 -> The full-suite re-run (181 passed, twice) behind the §10 count and the "no code change" argument
