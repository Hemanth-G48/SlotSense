# VALIDATION PROMPT — PHASE 2: Dataset Pipeline & Exploratory Data Analysis (EDA)

You are an independent validator. Test the dataset produced in Phase 2
(`prompts/02_phase2_dataset_eda.md`) against its deliverables and acceptance checks, score it, and
return a confidence verdict. Verify by actually running the provided scripts and loading the data.

## Scope (what Phase 2 was supposed to deliver)

1. **Dataset architecture** — table design with `data_source` / `data_quality_status` on relevant
   tables; baseline assignments kept separate.
2. **Source curation (optional)** — raw source files preserved in `raw/`; provenance recorded.
3. **Synthetic benchmark dataset** — diverse SKU master (1,000–3,000 SKUs, 8–12 categories),
   warehouse topology (500–2,500 locations), order history (20,000–100,000 order lines) with
   **three demand scenarios** (A concentrated, B balanced, C co-occurrence), inventory,
   compatibility rules, feasible baseline.
4. **Cleaning & validation** — scripts reject/flag bad records (missing IDs, zero/negative dims or
   weights, negative quantities, dup unaggregated items, invalid timestamps, dup location IDs,
   dangling references) and log errors rather than deleting silently.
5. **EDA report** — demand velocity (Pareto/ABC), affinity matrix (support/confidence/lift),
   volumetric density & space profiling, with charts.
6. **Documentation** — source manifest + data dictionary (fields, units, provenance).

## Verification steps

### D2.1 & D2.2 Architecture + curation (weight 0.10)
- [ ] Tables/paths exist with the documented schema and provenance fields.
- [ ] Raw originals (if any) are unchanged in `raw/`; license/compatibility noted.

### D2.3 Synthetic benchmark dataset (weight 0.25)
- [ ] Load each file; check SKU count, category count, location count, order-line count are in the
  target ranges and are internally consistent (every order_item ↔ order ↔ sku; every assignment ↔
  location).
- [ ] Three demand scenarios exist and are clearly labeled; Association/C co-occurrence is present.
- [ ] Reproducibility: re-run generation with the same seed → identical dataset.

### D2.4 Cleaning & validation (weight 0.20)
- [ ] Validation script runs and reports the expected error log behavior on seeded bad input.
- [ ] Referential integrity, physical plausibility, and geometric consistency checks implemented.

### D2.5 EDA report (weight 0.30)
- [ ] ABC/Pareto analysis present (Class A/B/C with documented thresholds & cumulative curve).
- [ ] Affinity matrix with support/confidence/lift present.
- [ ] Volume-density vs. bin-capacity profiling present.
- [ ] Charts have labeled axes and are saved (for the dashboard/docs).

### D2.6 Documentation (weight 0.15)
- [ ] Source manifest + data dictionary exist, cover units and provenance (measured/sourced/
  inferred/synthetic).

## Scoring
Score each deliverable 0–100 per `00_VALIDATION_OVERVIEW.md`. Weighted phase score → PASS (≥80) /
PARTIAL (50–79) / FAIL (<50). Evidence required: file paths, row counts, command output, seed
reproducibility run.

## Acceptance (phase-level pass criteria)
- All tables load, referential integrity passes, three scenarios present, EDA covers velocity,
  affinity, and space, and generation is reproducible. Any critical broken reference (dangling
  sku/location) or missing EDA section is a blocking issue.

## Output
Write `outputs/validation/phase2_validation.json`, then a short prose summary: per-deliverable
verdicts, phase score, top issues and required rework before Phase 3 may begin.