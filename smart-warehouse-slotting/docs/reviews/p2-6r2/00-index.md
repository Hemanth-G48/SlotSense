# P2-6R2 — third and final review: objective base + tolerance direction

**Task:** `t_833a749e` (kanban; assignee `reviewer`, run 21)
**Date:** 2026-10-29
**Repo:** `/home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting`
**Under review:** `docs/PHASE_2_CONSTRAINT_ENGINE.md` — 291 lines, sha256
`fb517fe6512e3d05f20b0c8565a31fef9ca4bacc25e3aa83565301f07209c871`, mtime 2026-10-29 05:50:07
**Evidence base:** `outputs/optimized/optimization_summary.json`, `outputs/evaluation/evaluation_summary.json`,
`docs/PHASE_2_EVIDENCE.json`, `outputs/optimized/optimized_assignments.csv`, and the source under `src/`
**Predecessors:** `docs/reviews/p2-6/` (task `t_14be9e41`, item 9 docs truthfulness) and
`docs/reviews/p2-6r/` (task `t_ac784eda`, R1/R2)
**Verdict:** REQUEST CHANGES on one clause — see `01-summary/verdict.md`. This index carries navigation and
provenance only.

## Where to look

| Question | File |
|---|---|
| Should this be approved, and what exactly must change? | `01-summary/verdict.md` |
| Is the §11 objective row on the repaired base, and does −61.13 % recompute? | `02-analysis/objective-base.md` |
| Does §5 match the code per scope, including the `LD-01`/`VD-01` direction? | `02-analysis/tolerance-direction.md` |
| Did anything outside the two edits regress? | `02-analysis/regression-check.md` |
| What did the tolerance probe actually print? | `03-dossiers/d01-probe-output.txt` |
| What do the validator, placer and tests say, verbatim? | `03-dossiers/d02-code-citations.txt` |
| Which lines of the document are quoted, and is `2,336,184` really gone? | `03-dossiers/d03-doc-greps.txt` |
| What values do the run summaries and the evidence file hold? | `03-dossiers/d04-artifact-fields.txt` |
| What did the independent re-aggregation and arithmetic print? | `03-dossiers/d05-regression-probe.txt` |
| Is the test suite still green, and how many tests? | `03-dossiers/d06-test-run.txt` |

## Provenance

- **No `.git` in this checkout.** The review compares the current files against the recorded artifacts and
  against the line snapshots in `docs/reviews/p2-6r/03-dossiers/`, not against a diff. Timestamps do the
  change-attribution work: the document is the only file modified since the previous verdict, and
  `find src tests configs -newermt '2026-10-29 05:49:30'` returns nothing.
- **Everything was re-derived here**, not carried forward: the §11 objective percentage and both comparison
  percentages from `optimization_summary.json` (`d01`), the §11 performance rows from
  `evaluation_summary.json`, and the §11.2 structural headroom by re-aggregating the delivered
  `optimized_assignments.csv` against `products.csv` and `locations.csv` with no pipeline code (`d05`).
- **The tolerance question was decided by code plus measurement**, not by reading the prose: the validator's
  and placer's comparison sites are quoted with line numbers in `d02`, and a probe over 1,027 canonical unit
  weights and 1,194 unit volumes × 400 random residuals (plus every exact `n * unit` boundary and the boundary
  one ULP below) measured the largest overdraft the placer's split arithmetic ever accepts (`d01`).
- **The suite was executed twice** in this review: 181 passed both times (`d06`), which is also the argument
  that the untouched code is still in the state the previous passes certified.
- Absolute paths in every file's `SOURCES` block are the navigation affordance: each one names what a
  consumer will find if it goes one layer deeper.

## Pyramid layout

```
docs/reviews/p2-6r2/
├── 00-index.md                      ← this file
├── 01-summary/
│   └── verdict.md                   ← L1: verdict, per-item status, the one required edit
├── 02-analysis/                     ← L2: one file per dimension
│   ├── objective-base.md            ← item 3: §11:178 re-derived
│   ├── tolerance-direction.md       ← item 6: per-scope code table + probe, R1
│   └── regression-check.md          ← criterion 3: 24 claims re-checked + suite
└── 03-dossiers/                     ← L3: raw output, flat
    ├── d01-probe-output.txt         ← tolerance + objective probe output
    ├── d02-code-citations.txt       ← validator/optimizer/separation/test excerpts
    ├── d03-doc-greps.txt            ← §5 verbatim, and the retracted string is absent
    ├── d04-artifact-fields.txt      ← artifact lines with file:line references
    ├── d05-regression-probe.txt     ← re-aggregation output + arithmetic
    └── d06-test-run.txt             ← full suite, twice
```

SOURCES (LAYER 1 NAVIGATION)
/home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting/docs/reviews/p2-6r2/01-summary/verdict.md
 -> The verdict (REQUEST CHANGES), the per-item status table, and R1 with replacement wording

/home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting/docs/reviews/p2-6r2/02-analysis/objective-base.md
 -> Why item 3 passes: the three objective fields, the recomputation, and the grep

/home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting/docs/reviews/p2-6r2/02-analysis/tolerance-direction.md
 -> Why the direction passes and the `LD-01` magnitude does not

/home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting/docs/reviews/p2-6r2/02-analysis/regression-check.md
 -> The untouched numeric claims and the suite re-run

/home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting/docs/reviews/p2-6r2/03-dossiers/
 -> Raw evidence behind every claim in this pyramid
