# PHASE 4 — Constraint Validation Engine

## Goal
Build a **standalone, reusable validation engine** that verifies a candidate assignment against
every hard constraint. This is deliberately built BEFORE the optimizer so every future candidate
solution can be proven safe and feasible before it is accepted. Safety is a hard constraint, not a
soft objective.

## Context you need
- Read `Smart_Warehouse_Slotting_Execution_Plan.txt` PHASE 3 and sections 2 & 8 (constraint rules
  and the final validation checklist).
- Reference `warehouse_optimization_dataset_roadmap.txt` Phase 7 (safety/compatibility rules).
- The domain model and schemas from Phase 1; data tables from Phase 2.

## Tasks

Implement a validator that returns a clear `pass/fail` plus a **reason** for every rule. Enumerate
and implement, at minimum:

### 1. Spatial / dimensional
- SKU `width ≤ bin width`, `height ≤ bin height`, `depth ≤ bin depth` (allow orientation rules
  explicitly where permitted).
- Volumetric fit: total assigned volume ≤ bin usable volume, AND packing must be plausible —
  comparing total volume alone is insufficient; enforce per-dimension fit and (where modeled)
  arrangement feasibility for multiple units. Apply `total volume = quantity × unit volume`
  and `total weight = quantity × unit weight`.

### 2. Structural load
- Cumulative assigned weight at each **location** ≤ `max_weight_kg`.
- Cumulative load per **shelf level** and per **rack frame** ≤ configured structural limits
  (aggregate loads transferred to supporting structures).

### 3. Category & hazard compatibility
- Enforce an explicit compatibility matrix: prohibit incompatible hazardous/fragile/restricted
  combinations in the same location and in prohibited zones.
- Honor `allowed_handling` / `allowed_hazard` on each location.
- Respect severe-rule `severity` and `rule_reason`; treat `UNKNOWN` as unsafe (do not assume a
  missing rule means safe).

### 4. Ergonomic & handling
- Heavy-item **shelf-height** restrictions: heavy SKUs must not be placed in prohibited upper
  levels (and heavy SKUs at reachable heights where required).
- Golden-zone preference is a metric input later — the validator enforces the **hard** part
  (unsafe heights), not the preference itself.

### 5. Assignment integrity
- Assignment uniqueness: a SKU is assigned to distinct locations only where policy allows it
  (single-SKU-per-location model: `sum_j x_ij = 1`).
- Location availability and inventory capacity: quantity assigned ≤ location + residual capacity.
- Referential integrity: every assignment references an existing, existing-invalid location/SKU.

### 6. Error reporting & audit export
- Produce a structured **constraint audit** report: for each location/SKU/rule → pass/fail +
  reason + severity + rule id. Export as `outputs/constraint_audit.csv`.
- Provide a convenience `validate_assignment(assignment) -> (score, [violations])` API returning a
  list of all violations, not just the first.

### 7. Automated tests
Add positive and negative tests per rule (at least one passing and one failing case each):
- Dimensional overflow, orientation rules, cumulative weight at location/shelf/rack.
- Prohibited category/hazard combinations.
- Heavy-SKU at prohibited height.
- Duplicate / over-capacity assignments.
- Referential failures.

## Deliverables / outputs for this phase
- `src/validation/validator.py` (+ rule modules) implementing all constraints.
- `outputs/constraint_audit.csv` example output.
- `tests/test_spatial_constraints.py`, `tests/test_weight_limits.py`, `tests/test_safety_rules.py`
  (and any others) — all passing.

## Acceptance checks (verify before finishing)
- [ ] Every rule returns pass/fail + a human-readable failure reason.
- [ ] All hard constraints are enforced as **hard**, with no location to soften them.
- [ ] Validator runs standalone on an assignment without the optimizer.
- [ ] Positive and negative tests pass; boundary/empty inputs handled.
- [ ] Rejecting an infeasible assignment is explicit, not silent.

## Constraints / gotchas
- Build this before touching the optimizer. This is the most important protective step in the
  whole project.
- Never let objective weights override these rules — a "better" travel score must never produce a
  safety violation.
- Keep the error log explicit: report violations rather than silently correcting them (e.g., if
  a baseline is infeasible, report it, don't quietly fix it).