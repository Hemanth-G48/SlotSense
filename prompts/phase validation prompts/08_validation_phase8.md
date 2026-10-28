# VALIDATION PROMPT — PHASE 8: Integration, End-to-End Testing & Technical Documentation

You are an independent validator. Test the integrated pipeline, the four required artifact files,
the hardening/edge-case coverage, and the technical documentation from
`prompts/08_phase8_integration_docs.md`. Then score and return a confidence verdict.

## Scope (what Phase 8 was supposed to deliver)

1. **Single execution pipeline** — `app/main.py` CLI (or equivalent) that runs the full chain
   (config → data → analysis → validate → optimize → route simulation → evaluation → outputs),
   with each stage also independently invocable.
2. **The four required artifact files** — `optimized_assignments.csv`, `constraint_audit.csv`,
   `optimization_summary.json`, `baseline_assignments.csv` (plus evaluation/pick-route outputs).
3. **Hardening tests & edge cases** — malformed inputs, infeasible configurations, empty/edge
   cases; explicit failure reporting (exit codes/messages), not silent swallowing.
4. **End-to-end evaluation** — runtime, feasibility, KPI table (baseline/optimized/diff/%),
   reproducibility over seeds.
5. **Technical report** — `docs/TECHNICAL_REPORT.md` covering all required sections.
6. **README** — installation, how to run each stage and the full pipeline, dashboard launch,
   reproduction steps.

## Verification steps

### D8.1 Pipeline reproducibility (weight 0.20)
- [ ] A SINGLE command runs the whole pipeline from config to outputs.
- [ ] Re-running with the same seed reproduces the outputs (compare hashes/key numbers).

### D8.2 The four required artifacts (weight 0.25 — critical)
- [ ] All four files exist with the canonical schema in `outputs/`. `optimized_assignments.csv`
   is distinct from `baseline_assignments.csv`.
- [ ] **Re-run the Phase-4 validator** on the final `optimized_assignments.csv` → 0 violations,
   100% feasibility (final system proof).

### D8.3 End-to-end KPI table (weight 0.20)
- [ ] The evaluation summary reports baseline vs. optimized for distance, route time, cube
   utilization, safety (0), feasibility (100%), and runtime, with absolute diff + % change.
- [ ] **Recompute** at least the key KPIs from outputs and confirm they match the report.

### D8.4 Hardening / edge cases (weight 0.15)
- [ ] Malformed inputs (bad columns, missing IDs, wrong units), infeasible configs, and edge cases
   (empty orders, zero-capacity bins, incompatible-only SKUs) are tested and fail with explicit
   messages/exit codes.

### D8.5 Technical documentation (weight 0.15)
- [ ] Report covers: problem formulation/assumptions/scope; architecture & data flow; I/O schemas;
   constraint logic; ABC & affinity methods; optimization algorithm & objectives with weight
   calibration; computational complexity; baseline-vs-optimized methodology + actual results;
   EDA summary; trade-offs, limitations, future work.

### D8.6 README (weight 0.05)
- [ ] Reproduces install, per-stage run, full-pipeline run, dashboard launch.

## Deliverable-level check (the three required deliverables)
Cross-check all three problem-statement deliverables are genuinely met and record verdicts:
- **Working allocation prototype** — runs end to end and returns a verified feasible solution OR
   explicitly reports no feasible solution. (Verdict + evidence from D8.1–D8.3.)
- **Interactive optimization dashboard** — updates from underlying data, not hardcoded. (Reference
   the Phase-7 validator result.)
- **Technical & algorithmic documentation** — a new developer can reproduce and interpret results
   from the docs alone. (Verdict + evidence from D8.5.)

## Scoring
Score each deliverable 0–100 per `00_VALIDATION_OVERVIEW.md`. **A final optimized assignment with
any validator violation, or a pipeline that cannot be reproduced from one command, forces FAIL.**
Weighted phase score → PASS (≥80) / PARTIAL (50–79) / FAIL (<50).

## Acceptance (phase-level pass criteria)
- Single-command reproducibility, all four artifacts valid, KPI table matches, edge cases handled
   explicitly, technical report complete, all three deliverables verified. Report the final KPI
   numbers as evidence.

## Output
Write `outputs/validation/phase8_validation.json`, then a short prose summary: per-deliverable
verdicts, the three-deliverable sign-off, phase score, and the final list of blocking issues (or
"no blocking issues — all phases complete").