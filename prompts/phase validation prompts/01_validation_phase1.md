# VALIDATION PROMPT — PHASE 1: Project Scaffold & Warehouse Domain Model

You are an independent validator. An agent was given the PHASE 1 build prompt
(`prompts/01_phase1_domain_model.md`) and produced a repository state. Your job is to verify
EVERY Phase-1 deliverable and acceptance check, score it, and return a confidence verdict. Do not
trust the builder's claims — locate the artifacts, run/verify them, and cite evidence.

## Scope (what Phase 1 was supposed to deliver)

1. **Repository scaffold** — the Python project structure and `requirements.txt` + `README.md`.
2. **Warehouse domain model** — typed data classes / schemas for Warehouse, Zone/Aisle/Rack/Bay/
   Shelf/Bin(Location), SKU/Product, Category, CompatibilityRule, Inventory, Order + OrderItem,
   StorageAssignment (baseline vs optimized kept separate).
3. **Input/output schemas & config** — canonical CSV/JSON column names, canonical units
   (cm, kg, cm³, m, UTC), and a `configs/` YAML/JSON file (topology, SKU mix, objective weights,
   ABC thresholds, storage rules).
4. **Warehouse geometry generator** — a deterministic (seeded) generator that computes real
   `(x,y,z)` coordinates, derives `distance_to_dispatch` from geometry, and labels ergonomic zones.
5. **Minimal baseline layout fixture** — a seeded, feasible baseline assignment (or deliberately
   flagged violations), persisted as CSV.
6. **Smoke test** — config → build small warehouse → seeded baseline → valid CSV outputs.

## Verification steps

### D1.4 & D1.1 Repository structure (weight 0.10)
- [ ] Check the directory tree matches the intended separation: `src/models`, `src/validation`,
  `src/analytics`, `src/optimization`, `src/routing`, `src/simulation`, `src/evaluation`,
  `tests`, `configs`, `outputs`, `docs`, `app`.
- [ ] `requirements.txt` declares at least pandas/numpy/pytest; `README.md` documents setup.

### D1.2 Domain model (weight 0.25)
- [ ] Every entity above is represented with the documented fields:
  - Location has stable `location_id`, hierarchy ids (zone/aisle/rack/bay/shelf_level),
    `(x,y,z)`, internal w/h/d (cm), `max_weight_kg`, `usable_volume_cm3`, ergonomic zone label,
    `allowed_handling`/`allowed_hazard`, `distance_to_dispatch_m`.
  - SKU has `sku_id`, name, category, w/h/d (cm), `unit_weight_kg`, computed `unit_volume_cm3`,
    `handling_type`, `hazard_class` (explicit `NONE`/`UNKNOWN`, never blank), `data_source`.
- [ ] Baseline and optimized assignments are separate types/attributes (baseline never overwritten).
- [ ] Units/column names are consistent with the schema doc.

### D1.3 Schemas & config (weight 0.15)
- [ ] Config file loads and validates (bad config is rejected, not silently accepted).
- [ ] Objective weights (alpha/beta/gamma/delta) present with documented defaults.

### D1.4 Geometry generator (weight 0.20)
- [ ] Same seed → byte-identical geometry (determinism).
- [ ] `distance_to_dispatch` derived from coordinates, not independent/arbitrary.
- [ ] Ergonomic zone labels assigned by shelf level and distance (golden zone present).

### D1.5 Baseline fixture (weight 0.15)
- [ ] Baseline assignment persists as CSV, uses only **feasible** locations (or violations
  explicitly flagged), and never gets overwritten later.

### D1.6 Smoke test (weight 0.15)
- [ ] Run it: loads config → builds warehouse → writes valid outputs. Must pass.
- [ ] Outputs are valid CSV with the canonical schema.

## Scoring

- Give every deliverable a 0–100 confidence score using the protocol in
  `00_VALIDATION_OVERVIEW.md`.
- Compute the weighted phase score and assign PASS (≥80) / PARTIAL (50–79) / FAIL (<50).
- Confidence must reflect evidence: a "should work" with no run/verification cannot score above 70
  for that deliverable.

## Acceptance (phase-level pass criteria)

- Structure, domain model, config, geometry generator, baseline fixture, and smoke test all PASS
  (≥80 weighted). If any critical artifact is missing or the smoke test fails, verdict is PARTIAL
  or FAIL and you must list blocking issues.

## Output

Write `outputs/validation/phase1_validation.json` per the schema in `00_VALIDATION_OVERVIEW.md`,
then give a short prose summary: per-deliverable verdicts, the phase score, and the top 3
blocking issues (or "no blocking issues"). If the phase needs fixes, list exactly what rework is
required before Phase 2 may begin.