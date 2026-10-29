# The six changes, item by item

All line numbers refer to the current `docs/PHASE_2_CONSTRAINT_ENGINE.md` (284 lines) and
`tests/test_phase5_optimizer.py` (144 lines). Every artifact value below was re-derived on 2026-10-29 from
the delivered CSVs and summaries, or read from the source lines in `03-dossiers/d02-code-citations.txt`.
Dossier `d01` holds the probe output; `d04` holds the JSON fields.

## 1. Cycle time and throughput re-based — PASS

Required: quote the repaired baseline, not the infeasible as-supplied one.

Now (lines 169-170):

```
| Cycle time (repaired baseline → optimized) | 1,471,967 s → 747,845 s (−49.19 %) |
| Throughput (repaired baseline → optimized) | 13.24 → 26.07 orders/h (+96.90 %) |
```

`evaluation_summary.json` holds `baseline.total_route_time_sec = 1471967.35`,
`optimized.total_route_time_sec = 747845.0`, `baseline.throughput_orders_per_hr = 13.24`,
`optimized.throughput_orders_per_hr = 26.07`. Recomputed: **−49.194186 %** and **+96.903323 %**, which round
to the printed −49.19 % and +96.90 %. The as-supplied values (`1,484,035.5`, `13.14`) are still in the
evaluation summary as `diagnostic_baseline`, but a grep of the doc for `1,484,036` or `13.14` returns
nothing (dossier `d06`, grep exit 1).

## 2. Beam-check count attributed correctly — PASS

Required: the optimized layout's count is 662, not 960.

Line 80 now reads: "the optimized layout has **0 `SL-02` violations** over **662 beam groups** (the
repaired baseline evaluates 922, the as-supplied baseline 960 — quoting 960 for the optimized layout would
attribute another layout's count to it)."

`PHASE_2_EVIDENCE.json` → `structural_sl02.{optimized,repaired_baseline,as_supplied_baseline}.beam_groups`
= **662 / 922 / 960**. The delivered validation CSVs agree row-for-row: `SL-02` rows = 662 optimized, 922
repaired, 960 as supplied, with zero failures in each (dossier `d04`, and `d06` of the first review).

## 3. `objective.baseline_value` in §7 — PASS in §7, residual in §11

Required: quote `2321711.382`, not `2336184.141`, under the field name `baseline_value`.

Line 97 now reads `"baseline_value": 2321711.382`. The delivered `optimization_summary.json` holds
`objective.baseline_value = 2321711.3822095753` and `objective.baseline_value_as_supplied =
2336184.1414095755`; the quoted figure is the former. The `assignment_completeness`, `value`,
`per_rule_violations`, `violation_severity_score` and `globally_optimal` fields in the same block also
match the artifact.

The same misattribution survives, however, at line 171 (§11's performance table), which quotes 2,336,184
as the starting objective with no label. Recomputed: −61.3732 % as supplied vs **−61.1324 % repaired**;
the summary's `objective_improvement_pct` is **61.132**. That row is R1 in
`02-analysis/residual-issues.md`.

## 4. Structural headroom disclosed — PASS

Required: disclose the delivered layout's near-binding structural scopes, state that "0 violations" is
brittle, and add the limitation.

Lines 204-218 add §11.2 with the table:

| Scope | Observed | Limit | Utilisation |
|---|---|---|---|
| Beam — rack `R5-3-1`, bay 0, shelf 3 | 214.64 kg | 216.00 kg | 99.37 % |
| Level — rack `R5-3-1`, shelf 1 | 458.76 kg | 460.80 kg | 99.56 % |
| One bin | at its `LD-01` limit | — | 100.00 % |

Independent re-aggregation of `outputs/optimized/optimized_assignments.csv` against
`products.csv`/`locations.csv` (dossier `d01`): beam load **214.636 kg** / 216.0 = **99.368519 %**; level
load **458.757 kg** / 460.8 = **99.556641 %**; exactly one bin at exactly 100 % of `max_weight_kg` —
**`LOC002136`, 30.0 / 30.0 kg**, with no other bin within 1e-9 of its limit. This matches
`PHASE_2_EVIDENCE.json` (`max_utilisation_pct` 99.37 beam / 99.56 level) and the first review's
independent dossier `d07`.

The explicit "0 violations is true but **not robust**" paragraph is at lines 214-218, and limitation #6 at
line 250 repeats the three figures. The 0.6 % clause in that paragraph is off by 0.04 pp — the actual
headroom is 0.635 % of the beam load — noted as A3, advisory only.

## 5. Configured radius in the phase-5 test — PASS as carded

Required: the optimized-output validation must pass `separation_radius_m=cfg.separation_radius_m` rather
than rely on the module default.

`tests/test_phase5_optimizer.py:80-83` now reads:

```python
cfg = Config.from_json(PROJECT_ROOT / "configs" / "benchmark.json")
res = validate_assignment(
    assignments, skus, wh, comp, inventory, separation_radius_m=cfg.separation_radius_m
)
assert res.is_feasible, f"optimized output has violations: {[v.reason for v in res.violations[:5]]}"
```

The assertion is unchanged (still a full re-validation and `is_feasible`), so the change strengthens the
test rather than weakening it; before, it validated at `DEFAULT_SEPARATION_RADIUS_M` (10.0,
`src/models/config.py:20`). The test was run alone against the canonical dataset: **1 passed in 34.70s**
(dossier `d05`).

The sibling fixture in `tests/test_phase6_evaluation.py:34-40` still calls `run_phase6` without the
configured radius; `run_phase6` falls back to `DEFAULT_SEPARATION_RADIUS_M` (`src/simulation/pipeline.py:136-140`).
That was the second half of my original item 5 but is outside the card's restatement — advisory A1.

## 6. §4 counting rule and §5 tolerances — PARTIAL

**§4:58 (counting) is correct.** It now says the grid evaluates only forbidden-category pairs inside the
same R-sized cell window, one check per unordered pair, "3,594 checks for 1,425 occupied bins … not
`n(n−1)/2`", and that a bin is never compared with itself. `PHASE_2_EVIDENCE.json`
(`cat01_sensitivity.note`) records the validator evaluating **3,594** forbidden pairs inside its
neighbourhood window, against 114,986 in a full scan of the as-supplied layout. The 1,425-bin figure is the
as-supplied/repaired baseline's bin count. (The example does not name the layout; see A2.)

**§5:79 (tolerances) is correct.** `LD-01`/`VD-01` apply none (`validator.py:406,428`), `SL-01`/`SL-02`/
`RK-01` apply `+1e-6` (`validator.py:602,615,628`), and the placer compares at `1e-9`
(`optimizer.py:48,1208`). The earlier blanket "all with the same 1e-6 tolerance" is gone.

**§5:79 (safety argument) is not correct.** The next clause — "the placer is stricter than the validator,
so it cannot accept a placement the validator would reject" — holds for the three aggregate scopes but not
for `LD-01`/`VD-01`. The placer's `_units_affordable` accepts `n` while `n*unit <= residual + 1e-9`, and
its runtime guard tolerates a bin weight residual down to −1e-9 kg and a volume residual down to −1e-6 cm³
(`optimizer.py:561,564`); the validator, with no tolerance, rejects any overshoot. So for the two bin rules
the placer is marginally **looser**, not stricter. The divergence is empirically unreachable — 1,027
canonical unit weights against boundary residuals found 0 cases (dossier `d01`), and all three layouts
have zero `LD-01`/`VD-01` violations — but the sentence as written is a general code contract and is false
for two of the five rules it lists. That is R2.

SOURCES (LAYER 3 NAVIGATION)
/home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting/docs/reviews/p2-6r/03-dossiers/d01-probe-output.txt
 -> The re-derivation: headroom loads, bin-at-limit count, cycle/throughput deltas, objective fields, tolerance probe

/home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting/docs/reviews/p2-6r/03-dossiers/d02-code-citations.txt
 -> validator.py and optimizer.py excerpts that decide the §5 tolerance claim

/home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting/docs/reviews/p2-6r/03-dossiers/d04-evidence-fields.txt
 -> Evidence-file and summary fields behind items 2, 3 and 4

/home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting/docs/reviews/p2-6r/03-dossiers/d05-changed-test-run.txt
 -> The changed test's real run: 1 passed in 34.70s

/home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting/docs/reviews/p2-6r/03-dossiers/d06-doc-greps.txt
 -> Line-level greps for the as-supplied figures, beam counts and objective values

/home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting/docs/reviews/p2-6r/03-dossiers/d07-doc-lines.txt
 -> Verbatim doc lines and test excerpts cited above
