# Phase 7 artifacts

| Path | Meaning |
|---|---|
| `optimizer_compare.json` | Controlled A_FIT comparison: seed 42, 600 evaluations, legacy vs targeted relocation only. |
| `optimizer/legacy/` | Frozen legacy-arm layout and run summary. |
| `optimizer/targeted/` | Targeted-arm layout and run summary. |
| `timing_sensitivity.json` | Hypothetical 6/8/10 s pick-time sweep on A_HOLDOUT; travel invariant. |
| `timing/<basis>_<sec>/` | Per-run simulation outputs for the sweep. |
| `baseline/` | Baseline-variant preparation used by both arms. |
| `verification.json` | Independent Phase 7 verifier result (18 checks). |

The canonical dataset and Phase 2–6 outputs were not modified. The default optimizer neighbourhood remains
`legacy`; `targeted` is an opt-in experiment and produced the same final layout and objective.
