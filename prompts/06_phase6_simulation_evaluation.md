# PHASE 6 — Route Simulation & Baseline-vs-Optimized Evaluation

## Goal
Quantitatively prove improvement. A visually better layout is not enough — the problem statement
requires concrete metrics comparing the baseline and optimized layouts under **identical**
demand, geometry, and routing assumptions.

## Context you need
- Read `Smart_Warehouse_Slotting_Execution_Plan.txt` PHASE 5 and section 5 (metrics, formulas, and
  evaluation rules) carefully.
- Read `warehouse_optimization_dataset_roadmap.txt` Phase 8 (travel graph, metrics).
- Reference `useful_repos/warehouse-operations-optimization/src/simulation.py` (S-shape /
  nearest-neighbor) and `useful_repos/Warehouse-Order-Picking-Operational-Analytics` (Manhattan +
  S-shape heuristics).
- Inputs: location graph + coordinates (Phase 1/2), baseline & optimized assignments (Phase 2/5),
  order demand (Phase 2), validator (Phase 4).

## Tasks

### 1. Build the warehouse travel graph
- Nodes = storage locations + dispatch depot; edges = reachable pairs through warehouse aisles,
  weighted by travel distance (metres).
- Compute routes from the **dispatch depot** to required locations and back (depot-to-locations-
  to-depot), unless the operational workflow specifies otherwise.
- **Do not** treat straight-line distance through racks/walls as walking distance.

### 2. Implement routing heuristics
- Implement at least one (ideally both):
  - **S-Shape / serpentine**: traverse each aisle containing a pick fully, snaking through the
    warehouse (most common real-world manual strategy).
  - **Nearest-Neighbor (greedy TSP)**: from current position, always go to the nearest unvisited pick.
- Group orders into pick batches (configurable batch size) for multi-item trips.

### 3. Define the simulation model
- Cycle time = travel time (distance ÷ picker speed) + pick time (per line) + batch setup time +
  any modeled delays.
- Throughput = orders completed ÷ total cycle time (orders/hour).
- Pick speed and pick time come from configuration (e.g., 1.3 m/s; ~8 s per line) and must be
  documented.

### 4. Run the baseline-vs-optimized comparison
- Use the **same** order workload, SKU quantities, warehouse geometry, routing algorithm, and
  assumptions for BOTH layouts.
- Validate the baseline too. If the baseline has violations, **report them** (do not silently
  correct) and still show the comparison.
- Compute and record for each layout:
  1. **Total pick travel distance** — sum of route distances across evaluated orders.
  2. **Pick route completion time** — travel time + modeled handling/delays.
  3. **Volumetric cube utilization** — occupied usable volume / usable storage volume × 100
     (document denominator excludes inaccessible/reserved space).
  4. **Safety compliance** — count of hard-rule violations (must be **0** for optimized).
  5. **Assignment feasibility** — valid / total assignments × 100 (must be **100%**).
  6. **Optimization runtime** — wall-clock time (recorded, not assumed).
- Compute travel distance reduction % and utilization delta (percentage points).
- Repeat randomized tests over multiple order mixes / seeds to check stability. Use fixed seeds.

### 5. Write reproducible results
- `outputs/pick_routes.csv` — route sequences and distance per route (baseline + optimized).
- `outputs/optimization_runs.csv` and `outputs/optimization_metrics.csv` — per-run algorithm,
  objective, status, and the metric table (baseline, optimized, absolute diff, % change).
- A `outputs/evaluation_summary.json` with the final result table.

### 6. Tests
- Verify routing distance math on small known layouts.
- Verify S-shape vs nearest-neighbor on a sample.
- Verify that running the same demand on both layouts is reproducible (fixed seeds).

## Deliverables / outputs for this phase
- `src/routing/graph.py`, `src/routing/heuristics.py`, `src/simulation/simulator.py`,
  `src/evaluation/metrics.py`.
- The four output files above with the completed result table.
- Tests for routing and metric correctness.

## Acceptance checks (verify before finishing)
- [ ] Identical demand + routing assumptions applied to both layouts.
- [ ] Baseline validated and reported (violations surfaced, not hidden).
- [ ] Optimized layout has 0 safety violations and 100% assignment feasibility.
- [ ] Distance, route time, and cube utilization are measured and reproducible.
- [ ] Final result table filled with real figures (metrics, diffs, % changes).

## Constraints / gotchas
- Never compare a deliberately-infeasible baseline as if it were a valid layout.
- Use the SAME routing algorithm for both (the comparison isolates slotting, not routing).
- Document the utilization denominator and whether occupied volume is bounding-box vs. packed.
- Reproducibility is mandatory — fixed seeds, recorded config.