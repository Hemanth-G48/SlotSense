# Item 5 — Is the reported feasibility the validator's, or could an optimizer self-report leak in?

**Verdict: PASS**

## What the checklist asked

The reported `feasibility` must come from the validator, not from the optimizer's own flag. Find any path
where a self-report could leak in.

## The production path

`src/optimization/pipeline.py`:

```
143   optimized, log = optimizer.optimize()
147   result = validator.validate(optimized)          <-- fresh full validation of the returned layout
190   "feasibility_status": "FEASIBLE" if result.is_feasible else "INFEASIBLE"
191   "feasibility": result.is_feasible,
213   "n_violations": len(result.violations),
214   "violations_by_rule": by_rule,
```

`result` is the only input to the status fields. The optimizer's own `log.feasibility_status`
(`optimizer.py:1145-1162`) is written into `optimization_summary.json`? — **no**. The summary's keys come from
`log` for scores, runtimes, move counts, unplaced SKUs and repair statistics, and from `result` for every
feasibility field. `log.feasibility_status` is never read by `_run_phase5`; it is only set.

The evaluation side is independent of both: `src/simulation/pipeline.py:220-225` re-validates the baseline and
the optimized layout from their CSVs with `validate_assignment(..., separation_radius_m=radius)`, and
`:227-235` derives `blocked_layouts` from those two results.

## The paths I checked for a leak

| Candidate path | Verdict |
|---|---|
| `optimization_summary.json["feasibility"]` | From `validator.validate()` at `pipeline.py:147`. Clean. |
| `optimization_summary.json["starter_feasible"]` (`pipeline.py:231`) | `log.starter_feasible`, which is `starter_result.is_feasible` from `self.validator.validate(...)` at `optimizer.py:1112,1122`. A validator verdict, not a self-flag. Clean. |
| `optimization_summary.json["repair"]["feasible"]` | `current_result.is_feasible` from `_repair` (`optimizer.py:960`), which is the same validator's output at `:936`. Clean. |
| `optimization_summary.json["repair"]["final_layout"]` (baseline path) | `baseline.py:312-313` re-validates the repaired layout *after* the loop, and `:322-326` adopts the variant only if that independent verdict is feasible **and** `check_inventory_conservation` agrees. Clean. |
| `evaluation_summary.json["feasibility"]` | `run_phase6`'s own `validate_assignment` calls. Clean. |
| `evaluation_summary.json["feasibility"]["*.violations_by_rule"]` | Recomputed from those results (`:100-109`). Clean. |
| Dashboard "Solver status" | `app/dashboard.py:346` prefers `feasibility_status` from the summary and only falls back to the boolean `feasibility` — both pipeline-written. `:1844` uses `summary["feasibility"]` and cross-checks `n_violations == 0` at `:1914`. Clean. |

One structural caveat worth stating plainly: `run_phase5` builds a **single** `Validator` instance
(`pipeline.py:117`) and hands it to the optimizer, then reuses it for the final verdict. So "independent"
here means *the rule engine is the arbiter, not the optimizer's bookkeeping* — it does not mean a second
process. The second-process re-derivation was P2-4's job, and I re-verified that the evidence file is still
true of the files on disk: **12/12 recorded sha256s match** (`03-dossiers/d08-evidence-sha256-check.txt`), and
its verdict (`VERIFIED FEASIBLE`, 0 violations at 10.0 m, 100 % completeness) is what the pipeline claims.

There is no code path in which the optimizer's output is trusted because the optimizer said so.

## Advisory (cosmetic)

`src/optimization/pipeline.py:57-66` deliberately leaves `feasibility` and `feasibility_status` as `None`
when the run crashed, "rather than being reported as INFEASIBLE". The dashboard does not honour that:
`app/dashboard.py:346-347` and `:1844-1845` render `None` as **"INFEASIBLE"**, i.e. it displays a verdict the
validator never produced. Both spots also show an explicit error banner (`:341-342`, and the block at
`:1830-1839`), so the information is not lost — but "unknown" and "infeasible" are different answers and the
gate went to some trouble to keep them apart.

SOURCES (LAYER 3 NAVIGATION)
/home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting/docs/reviews/p2-6/03-dossiers/d08-evidence-sha256-check.txt
 -> Independent re-verification: 12/12 sha256s still match, so the P2-4 verdict applies to today's files
/home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting/docs/reviews/p2-6/03-dossiers/d03-gate-blocked-both-directions.txt
 -> A run where the pipeline's verdicts are reproduced end-to-end through the CLI
