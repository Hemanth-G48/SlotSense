# VALIDATION PROMPT — PHASE 4: Constraint Validation Engine

You are an independent validator. The Phase-4 validator is the **most safety-critical** part of the
project, so this validation is strict. Test the validation engine from
`prompts/04_phase4_validator.md`, score it, and return a confidence verdict. You must actively try
to make the validator FAIL with invalid assignments — a validator that only reports success is a
failure.

## Scope (what Phase 4 was supposed to deliver)

1. **`src/validation/` engine + rule modules** implementing, at minimum:
   - Spatial/dimensional (per-dimension fit, orientation, volumetric + packing feasibility).
   - Structural load (per-location, per-shelf, per-rack cumulative weight).
   - Category & hazard compatibility (explicit matrix, allowed handling/hazard, UNKNOWN unsafe).
   - Ergonomic & handling (heavy-SKU shelf-height restrictions).
   - Assignment integrity (uniqueness, availability, inventory capacity, referential integrity).
2. **`validate_assignment(...) -> (score, [violations])`** returning ALL violations, each with
   pass/fail + reason + severity + rule id.
3. **`outputs/constraint_audit.csv`** example export.
4. **Automated tests** — positive and negative cases per rule
   (`test_spatial_constraints.py`, `test_weight_limits.py`, `test_safety_rules.py`).

## Verification steps

### D4.1 API & completeness (weight 0.20)
- [ ] Every required rule category above is implemented (spatial, load@loc/shelf/rack,
  hazard/compatibility, ergonomic height, integrity). Missing a rule category = FAIL for this item.
- [ ] `validate_assignment` returns a list of violations, not just first-error.

### D4.2 Adversarial correctness on each rule (weight 0.40 — highest)
**Construct invalid assignments and confirm the validator REJECTS each:**
- [ ] SKU wider/taller/deeper than bin; volume overflow despite single-dimension fit (e.g., multiple
  units packed).
- [ ] Cumulative weight exceeding location limit AND exceeding shelf/rack structural limit.
- [ ] Hazardous + standard incompatible in one location; fragile in a high-impact zone; heavy in a
  prohibited upper level — the validator flags each with a reason.
- [ ] Duplicate assignment (SKU to two locations on single-location policy); quantity over
  capacity; assignment to a nonexistent location/SKU.
**And that it ACCEPTS** a clean, feasible assignment (no false positives).

### D4.3 Hard-constraint integrity (weight 0.20)
- [ ] Confirm the rules are hard (reject) and cannot be softened by any objective-weight parameter.
  There must be no code path where a travel/affinity score overrides a rejection.

### D4.4 Audit export (weight 0.10)
- [ ] `constraint_audit.csv` lists per-location/SKU/rule pass/fail + reason + severity + rule id.

### D4.5 Tests (weight 0.10)
- [ ] `pytest` passes all positive and negative test files; they exercise each rule category.

## Additional cross-checks
- Run the validator over the Phase-2 **baseline** assignment. Report how many violations it finds
  (a feasible baseline → 0; an intentionally-infeasible one → detected inline). Record this number
  in the report evidence.

## Scoring
Score each deliverable 0–100 per `00_VALIDATION_OVERVIEW.md`. Any rule that fails to reject an
obviously-invalid assignment caps that deliverable at 0 and forces the phase verdict to FAIL
until fixed. Weighted phase score → PASS (≥80) / PARTIAL (50–79) / FAIL (<50).

## Acceptance (phase-level pass criteria)
- All five rule categories implemented; adversarial invalid cases rejected; clean assignment
  accepted; tests pass; audit export works. Record the baseline-violation count as evidence.

## Output
Write `outputs/validation/phase4_validation.json`, then a short prose summary: per-deliverable
verdicts, phase score, the exact invalid cases you tried, which (if any) got through, and required
rework. Be explicit — this gate protects Phases 5, 6, and 7.