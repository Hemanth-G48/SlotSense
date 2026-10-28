# VALIDATION PROMPT — PHASE 5: Allocation Optimizer

You are an independent validator. Test the allocation optimizer from
`prompts/05_phase5_optimizer.md`, its outputs, and — critically — that it only ever emits
**feasible, hard-constraint-compliant** assignments. Score it and return a confidence verdict.

## Scope (what Phase 5 was supposed to deliver)

1. **`src/optimization/` modules** — `optimizer.py`, `objective.py`, algorithm modules (greedy,
   local search, optional annealing / MILP).
2. **`outputs/optimized_assignments.csv`** — SKU-to-location mapping with assigned quantity.
3. **`outputs/baseline_assignments.csv`** — the Phase-2 baseline, unchanged (never overwritten).
4. **`outputs/optimization_summary.json`** — objective values, weights, feasibility status,
   runtime, algorithm name/version, input dataset version, stopping reason.
5. **Tests** — feasibility, infeasibility handling, determinism-with-seed.

## Verification steps

### D5.1 Optimizer modules & pipeline (weight 0.15)
- [ ] Modules import and run end to end on Phase-2 data + Phase-3 analysis outputs.
- [ ] Runs deterministically given a seed (same inputs + seed → same assignment).

### D5.2 Objective definition & weights (weight 0.20)
- [ ] Objective covers travel (D), and includes affinity (A), ergonomics (E), utilization (U)
  terms with the weighted form `alpha*D + beta*A + gamma*E + delta*U`, or clearly documents a
  subset choice.
- [ ] **Safety is NOT inside the objective weights** — hard constraints handled by the Phase-4
  validator. Confirm no code path lets a lower objective score override a rejection.

### D5.3 Feasibility of the optimized assignment (weight 0.40 — highest)
- [ ] Run the **Phase-4 validator** on `optimized_assignments.csv` for at least two scenarios
  (A and C). The optimized layout must have **0 safety/feasibility violations** and 100%
  assignment feasibility.
- [ ] Every SKU is assigned, or explicitly reported infeasible with a reason (no forced invalid
  slots).

### D5.4 Improvement over baseline (weight 0.15)
- [ ] On the SAME orders and geometry, the optimizer objective (weighted cost) is better than the
  baseline's — record the travel-distance-cost delta (full travel-distance comparison happens in
  Phase 6; here, verify objective improvement and that high-velocity SKUs land in
  accessible/golden-zone locations).

### D5.5 Outputs (weight 0.10)
- [ ] `optimized_assignments.csv` and `baseline_assignments.csv` exist with canonical schema and
  are never conflated.
- [ ] `optimization_summary.json` records weights, feasibility status, runtime, algorithm, dataset
  version, stopping reason. Heuristic results are not labeled "globally optimal."

### D5.6 Tests (weight 0.10)
- [ ] `pytest` passes; infeasible-input handling is covered (a no-feasible-assignment case
  returns an explicit report, not a fake solution).

## Additional cross-check
Actually re-run the optimizer from a clean state and re-run the Phase-4 validator on its output —
record runtime and validator results as evidence.

## Scoring
Score each deliverable 0–100 per `00_VALIDATION_OVERVIEW.md`. **A single hard-constraint
violation in the optimized output caps verdict at FAIL.** Weighted phase score → PASS (≥80) /
PARTIAL (50–79) / FAIL (<50).

## Acceptance (phase-level pass criteria)
- Optimized assignment passes the validator (0 violations, 100% feasibility), improves over the
  baseline objective, is reproducible with a seed, and all metadata files are complete. Any
  feasibility violation is a blocking issue.

## Output
Write `outputs/validation/phase5_validation.json`, then a short prose summary: per-deliverable
verdicts, phase score, the Phase-4 re-validation result, and required rework before Phase 6.