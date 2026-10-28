# VALIDATION PROMPT — PHASE 3: Demand, Affinity & Velocity Analysis Modules

You are an independent validator. Test the analysis modules from Phase 3
(`prompts/03_phase3_demand_affinity.md`) and their outputs, score them, and return a confidence
verdict. Verify by running the modules on the Phase-2 data and checking the math directly.

## Scope (what Phase 3 was supposed to deliver)

1. **`src/analytics/` modules** — `demand.py`, `abc.py`, `affinity.py`, `volume_profile.py`
   (importable, testable).
2. **abc_classification.csv** — `sku_id`, demand metrics, rank, cumulative share, `abc_class`.
3. **demand_summary.csv** — frequency, units sold, velocity per SKU.
4. **affinity_matrix.csv** — `(sku_a, sku_b, co_count, support, confidence, lift)`.
5. **affinity_clusters.csv** — `(sku_id, affinity_cluster_id)`.
6. **volume_profiles.csv** — per-SKU volume/weight profile and compatible capacity classes.
7. **Unit tests** for each module (Pareto boundary, affinity math, edge/empty input).

## Verification steps

### D3.1 Modules & testability (weight 0.15)
- [ ] All four modules import and expose the documented functions.
- [ ] They run standalone on the Phase-2 data without the optimizer.

### D3.2 ABC classification (weight 0.25)
- [ ] Run on Phase-2 Scenario A; every SKU has an A/B/C class.
- [ ] **Recompute by hand** on a sample: the A boundary is the first ~80% of cumulative demand,
  B next ~15%, C the remainder — match the documented config thresholds.
- [ ] The union of A+B+C covers all SKUs exactly once.

### D3.3 Demand summary (weight 0.10)
- [ ] demand_frequency = distinct orders containing SKU; values are non-negative and consistent.

### D3.4 Affinity (weight 0.25)
- [ ] **Recompute** support/confidence/lift for a few pairs by hand from `order_items`; must match.
- [ ] co_count counts distinct orders containing both SKUs.
- [ ] Clusters are derived from the affinity graph (not arbitrary).

### D3.5 Volume profiles (weight 0.10)
- [ ] Every SKU maps to ≥1 compatible capacity class; volume/weight computed as quantity × unit.

### D3.6 Unit tests (weight 0.15)
- [ ] `pytest` passes; each test file covers its module's edge cases.

## Scoring
Score each deliverable 0–100 per `00_VALIDATION_OVERVIEW.md`; weighted phase score → PASS (≥80) /
PARTIAL (50–79) / FAIL (<50). Evidence: run output + hand-recomputed comparison for ABC and
affinity.

## Acceptance (phase-level pass criteria)
- All modules run, ABC partitions every SKU per the documented thresholds, affinity math is
  correct on a hand-checked sample, volume profiles cover all SKUs. A wrong ABC boundary or
  incorrect affinity math is a blocking issue.

## Output
Write `outputs/validation/phase3_validation.json`, then a short prose summary: per-deliverable
verdicts, phase score, top issues and required rework before Phase 4 (note: Phase 4 validator is
independent of Phase 3, but Phase 3 outputs feed the optimizer in Phase 5).