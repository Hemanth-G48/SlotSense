# Item 6 — The evaluation gate, verified by running it

**Verdict: PASS**

## What the checklist asked

With an infeasible baseline or an infeasible optimized layout, `evaluation_summary.json` must be marked
`BLOCKED_INFEASIBLE_LAYOUT`, metrics must not be presented as a valid comparison, and `run-all` must exit
non-zero. **Verify by actually running it, not by reading the code.**

## The gate's shape

| Element | Where |
|---|---|
| Both layouts validated before anything is scored | `src/simulation/pipeline.py:214-225` |
| `blocked_layouts` built from the validator's two verdicts | `:226-231` |
| `evaluation_status`, `comparison_valid`, `diagnostic_only`, `blocked_reason` | `:367-388`, `:431-436` |
| A blocked run publishes **no** comparison; the table moves to `diagnostic_comparison` and every row is flagged | `:387-388`, `:295-296`, `:448` |
| Non-zero exit | `app/main.py:138-146` `_exit_if_evaluation_blocked` raises `SystemExit(...)`; called from `run_all` at `:263` and from `run_simulate` at `:208` |

## Run (a) — the PASS path, so the gate is not a permanent block

Command (inside a byte copy of the repo beside a copy of the dataset, so the delivered `outputs/` tree was
never rewritten):

```
.venv/bin/python app/main.py run-all --processed ../dataset/processed --scenario A
```

Observed: **`RUNALL_EXIT_CODE=0`**, 56 s, and

```
   baseline_variant=repaired_minimal
   repair: 1071 -> 0 violations, moves attempted=96 accepted=96 rejected=0, terminated=feasible in 7.806s
   conservation: units 6375/6375 exact=True duplicate_pins=0
== optimize ==
   execution=OK feasibility=FEASIBLE violations=0 rules={}
== simulate ==
   evaluation_status=OK comparison_valid=True blocked_layouts=[] baseline_variant=repaired_minimal
```

## Run (b) — an infeasible BASELINE, through `run-all`

Fixture: the canonical dataset with one SKU's on-hand raised 47 units above what its baseline row assigns.
That yields INV-02, and an INV violation names no bin, so `_problem_bins` has nothing to target, the repair
terminates `no_improving_move`, conservation fails (`6375/6422 exact=False`), the repaired layout is refused,
and `baseline_variant` stays `as_supplied`.

Command:

```
.venv/bin/python app/main.py run-all --processed <fixture>/processed --scenario A
```

Observed: **exit code 1**, stderr

```
BLOCKED by the feasibility gate: evaluation_status=BLOCKED_INFEASIBLE_LAYOUT, infeasible layout(s)=baseline.
The diagnostic metrics are not valid evidence; fix the layouts and re-run.
```

and `evaluation_summary.json`:

```
evaluation_status      'BLOCKED_INFEASIBLE_LAYOUT'
comparison_valid       False
diagnostic_only        True
blocked_layouts        ['baseline']
baseline_variant       'as_supplied'
comparison rows        0
diagnostic_comparison  present, every row flagged diagnostic_only: True (18 rows)
feasibility[baseline]  INFEASIBLE n=1072 {'CAT-01': 1071, 'INV-02': 1}
feasibility[optimized] FEASIBLE   n=0 {}
```

Note that the *optimized* layout was feasible here and the run still blocked: the gate is not satisfied by
one good side.

## Run (c) — an infeasible OPTIMIZED layout, through `simulate`

Command:

```
.venv/bin/python app/main.py simulate --processed <dataset>/processed \
    --optimized <dataset>/processed/storage_assignments_baseline.csv --output <scratch> --scenario A
```

(the as-supplied baseline, with its 1,071 CAT-01 violations, passed as the optimized layout)

Observed: **exit code 1**, stderr

```
BLOCKED by the feasibility gate: evaluation_status=BLOCKED_INFEASIBLE_LAYOUT, infeasible layout(s)=optimized.
```

and a summary with `comparison rows 0`, `diagnostic_comparison` present with 18 rows all flagged
`diagnostic_only: True`, `blocked_layouts: ['optimized']`, `feasibility[optimized] INFEASIBLE n=1071`.

## Source of these numbers

Full verbatim output of all three runs: `03-dossiers/d02-gate-runall-pass.txt` and
`03-dossiers/d03-gate-blocked-both-directions.txt`. Both blocked runs exited **1**, not 2 and not 0.

## One residual observation

A blocked run still writes the `baseline` and `optimized` metric dictionaries and a populated
`optimization_metrics.csv`. That is deliberate — the metrics are needed to diagnose *why* a layout failed —
and they are labelled: both dictionaries carry `diagnostic_only: true`, every table row carries
`diagnostic_only: true`, `comparison` is empty, and `notes.comparison_published_as_valid_evidence` is
`false`. A consumer that reads `comparison` (or `comparison_valid`) cannot mistake it for evidence. A
consumer that reaches past `comparison` into `diagnostic_comparison` and ignores the flag has been warned
twice.

SOURCES (LAYER 3 NAVIGATION)
/home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting/docs/reviews/p2-6/03-dossiers/d02-gate-runall-pass.txt
 -> The exit-0 pass path, verbatim
/home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting/docs/reviews/p2-6/03-dossiers/d03-gate-blocked-both-directions.txt
 -> Both exit-1 blocked paths, verbatim, including the full evaluation_summary.json
