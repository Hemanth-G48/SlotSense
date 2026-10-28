# PHASE 1 — Project Scaffold & Warehouse Domain Model

## Goal
Set up the project repository and formally define the warehouse domain model, the input/output
schemas, and the configuration format. Nothing about optimization yet — only the data model and
the physical representation of the warehouse. This is the foundation every later phase depends on.

## Context you need
- Read `Smart_Warehouse_Slotting_Execution_Plan.txt` (esp. PHASE 1, sections 1–3, 4.1, and the
  project structure in section 6).
- Read the field definitions in `warehouse_optimization_dataset_roadmap.txt` (core tables in
  Phase 1.1 of the roadmap) for the canonical fields to mirror.

## Tasks

### 1. Set up the repository scaffold
Create a Python project with this structure (paths can be adapted, but keep the separation):

```
smart-warehouse-slotting/
  app/
    main.py
    pages/                # dashboard pages (built in Phase 7)
    components/
  src/
    models/               # domain dataclasses / pydantic models
    validation/           # Phase 4
    analytics/            # Phase 3
    optimization/         # Phase 5
    routing/              # Phase 6
    simulation/           # Phase 6
    evaluation/           # Phase 6
  tests/                  # pytest
  configs/
  outputs/                # csv/json exports
  docs/
  requirements.txt
  README.md
```

Dependencies to declare: `pandas`, `numpy`, `pytest` now; you will add `networkx`,
`plotly`, `streamlit`, and an LP solver (e.g. `ortools` or `scipy.optimize.milp`) in later phases.

### 2. Define the warehouse domain model (dataclasses + schemas)
Represent every entity as a typed data class. Minimum entities:

- **Warehouse** — id, name, layout_version.
- **Zone / Aisle / Rack / Bay / Shelf / Bin (Location)** — the physical hierarchy. Each location must have:
  - Stable `location_id` independent of which SKU is stored there.
  - `zone_id`, `aisle_id`, `rack_id`, `bay`, `shelf_level`.
  - `(x, y, z)` coordinates (metres).
  - Internal `width_cm`, `height_cm`, `depth_cm`.
  - `max_weight_kg` (per-location permissible load).
  - `usable_volume_cm3`.
  - `accessibility` / ergonomic zone label (e.g. `golden`, `secondary`, `reserve`).
  - `allowed_handling` / `allowed_hazard` categories (what may be stored there).
  - `distance_to_dispatch_m`.
- **SKU (Product)** — `sku_id`, `product_name`, `category_id`, `width_cm`, `height_cm`,
  `depth_cm`, `unit_weight_kg`, computed `unit_volume_cm3`, `handling_type`
  (e.g. `standard`, `fragile`, `heavy`, `temperature_controlled`), `hazard_class`
  (explicit `NONE` or `UNKNOWN` allowed, never blank), `data_source`.
- **Category** — `category_id`, `category_name`, `storage_requirements`.
- **CompatibilityRule** — `category_a`, `category_b`, `allowed`, `rule_reason`, `severity`.
- **Inventory** — `sku_id`, `location_id`, `quantity_on_hand`.
- **Order + OrderItem** — `order_id`, `timestamp`, `status`; `order_item` = `order_id`,
  `sku_id`, `quantity`.
- **StorageAssignment** — `sku_id`, `location_id`, `assigned_quantity`, `assignment_type`
  (`baseline` vs `optimized` — keep them separate, never overwrite baseline).

### 3. Define the input/output schemas and config
- Declare the canonical CSV/JSON column names and units. **Canonical units:** dimensions in cm,
  weight in kg, volume in cm³, coordinates & travel in metres, timestamps in UTC.
  - SKU volume = width × height × depth.
  - Total stored volume = quantity × unit volume; total weight = quantity × unit weight.
- Define a `configs/` format (YAML or JSON) that captures:
  - Warehouse topology parameters (zones, aisles, racks, shelf levels, bin sizes/module grid).
  - SKU mix proportions (see dataset roadmap Phase 4.1: ~25% small/light, 30% medium, 15% large,
    15% heavy, 10% fragile, 5% restricted/hazardous).
  - Objective weights `alpha, beta, gamma, delta` for travel/affinity/ergonomics/utilization
    (documented, defaults provided; safety is a hard constraint, NOT a weight).
  - ABC thresholds (e.g. A = first 80% cumulative demand, B = next 15%, C = remainder).
  - Single-SKU vs mixed-SKU storage rules and per-location inventory quantity limits.

### 4. Implement a warehouse geometry generator (structured topology)
Generate a valid, deterministic (seeded) warehouse layout from config:
- Hierarchy Warehouse → Zone → Aisle → Rack → Bay → Shelf → Bin.
- Compute real `(x, y, z)` coordinates from aisle/rack geometry.
- Derive `distance_to_dispatch` from coordinates (euclidean or Manhattan within aisles) — do
  NOT invent distances independently of the geometry.
- Assign ergonomic zone labels by shelf level and distance (golden = chest-to-waist, near dock).

### 5. Produce a minimal baseline layout fixture
Generate a small, clearly-labeled baseline assignment (e.g., random among **feasible** locations,
or the "current" layout from config) so later phases have something to improve. If you later
deliberately create an infeasible baseline for demonstration, report its violations separately.

## Deliverables / outputs for this phase
- Repo scaffold with `requirements.txt` and `README.md` documenting the model and setup steps.
- `src/models/` domain classes with full fields above.
- `configs/` example config file (validated on load).
- A `src/models/warehouse_topology.py` (or equivalent) that builds and serializes a seeded
  warehouse geometry.
- Schema documentation (list each table/class, its fields, types, units, and meaning).
- A passing smoke test that: loads config → builds a small warehouse → creates a minimal seeded
  baseline assignment → writes valid CSV outputs to `outputs/`.

## Acceptance checks (verify before finishing)
- [ ] Every warehouse location has a stable unique `location_id` and full coordinates/capacities.
- [ ] Every SKU has dimensions, weight (non-negative), category, handling, and explicit hazard class.
- [ ] Units and column names match the canonical schema exactly (documented in README).
- [ ] The geometry generator is deterministic for a fixed seed and produces valid coordinates.
- [ ] `distance_to_dispatch` is derived from geometry, not hardcoded independently.
- [ ] Baseline and optimized assignments are stored as separate types to avoid overwriting.
- [ ] Smoke test passes and writes valid output files.

## Constraints / gotchas
- Keep the model general enough to later accept a **real** dataset (e.g., Mendeley footwear
  warehouse) by mapping its columns into this schema — don't hardcode synthetic-only fields.
- Do not start building the optimizer yet. Domain model first.
- Document every assumption (e.g. "usable volume differs from bounding-box total because of
  packing inefficiency").