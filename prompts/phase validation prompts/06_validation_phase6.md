# VALIDATION PROMPT — PHASE 6: Route Simulation & Baseline-vs-Optimized Evaluation

You are an independent validator. Test the route simulator and the quantitative baseline-vs-optimized
evaluation from `prompts/06_phase6_simulation_evaluation.md`. Verify the math and the fairness of
the comparison, then score and return a confidence verdict.

## Scope (what Phase 6 was supposed to deliver)

1. **`src/routing/graph.py`** — travel graph (nodes = locations + dispatch depot; weighted edges
   through aisle connectivity), distances in metres.
2. **`src/routing/heuristics.py`** — S-shape and/or nearest-neighbor routing.
3. **`src/simulation/simulator.py`** — order batching, pick-cycle-time model
   (travel time + pick time + setup + delays), throughput.
4. **`src/evaluation/metrics.py`** — the six metrics (travel distance, route time, cube
   utilization, safety compliance, assignment feasibility, runtime).
5. **Outputs** — `pick_routes.csv`, `optimization_runs.csv`, `optimization_metrics.csv`,
   `evaluation_summary.json` with a filled result table.
6. **Tests** — routing-distance math, heuristic comparison, reproducibility.

## Verification steps

### D6.1 Travel graph correctness (weight 0.15)
- [ ] Nodes/edges connect only reachable locations through aisles; weights are real distances,
  NOT straight-line-through-walls on a sample.
- [ ] Routes start/end at the dispatch depot.

### D6.2 Routing math (weight 0.20)
- [ ] **Recompute by hand** a small route's distance from the layout coordinates; matches.
- [ ] S-shape vs nearest-neighbor produce distinguishable, sensible distances on a sample.

### D6.3 Fair comparison (weight 0.25 — critical)
- [ ] The SAME orders, quantities, geometry, routing algorithm, and assumptions run on BOTH
  layouts — confirm by inspection of how the simulator is invoked.
- [ ] The baseline is validated too; any baseline violations are REPORTED, not silently corrected.
- [ ] Both layouts' metrics are computed by identical code paths.

### D6.4 Metrics correctness (weight 0.25 — critical)
- [ ] **Recompute the KPI table** for the optimized layout from the pick routes and utilization
  and confirm it matches `optimization_metrics.csv` / `evaluation_summary.json`.
- [ ] Travel distance reduction % and utilization delta (percentage points) are computed per the
  documented formulas — verify on the actual numbers.
- [ ] Optimized layout: safety = 0 violations, feasibility = 100%. (Re-run the Phase-4 validator.)
- [ ] Runtime is wall-clock, recorded, and reproducible-over-seeds.

### D6.5 Reproducibility & exports (weight 0.10)
- [ ] Same seed(s) → identical results across runs; output files match the schema.

### D6.6 Tests (weight 0.05)
- [ ] `pytest` passes for routing/metrics.

## Scoring
Score each deliverable 0–100 per `00_VALIDATION_OVERVIEW.md`. A comparison that is not identical
across layouts (D6.3) or a metric table that does not match re-computation (D6.4) caps the phase
at PARTIAL or FAIL. Weighted phase score → PASS (≥80) / PARTIAL (50–79) / FAIL (<50).

## Acceptance (phase-level pass criteria)
- Fair comparison confirmed, metrics reproduce by hand, results reproducible over seeds, and the
  optimized layout is validated (0 safety violations, 100% feasibility). Report the actual numbers
  (reduction %, utilization delta, runtime) as evidence.

## Output
Write `outputs/validation/phase6_validation.json`, then a short prose summary: per-deliverable
verdicts, phase score, the hand-recomputed metric match/fail, and required rework before Phase 7.