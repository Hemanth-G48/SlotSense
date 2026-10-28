# PHASE 5 — Allocation Optimizer

## Goal
Build the core allocation engine that produces a **globally useful, physically feasible**
SKU-to-location assignment. The optimizer combines demand velocity, order affinity, golden-zone
ergonomics, and travel distance — while every candidate solution is re-validated by the Phase 4
validator. Safety and feasibility are hard constraints; they cannot be traded for a better score.

## Context you need
- Read `Smart_Warehouse_Slotting_Execution_Plan.txt` PHASE 4 and section 4 (decision variables,
  objectives, and strategy comparison) carefully.
- Read `warehouse_optimization_dataset_roadmap.txt` Phase 7.3 (record optimizer metadata).
- Reference `useful_repos/warehouse-slotting-optimizer/slotting_optimizer.py` and
  `useful_repos/warehouse-operations-optimization/src/slotting_optimization.py` for assignment
  patterns.
- Inputs: domain model (Phase 1), data (Phase 2), analysis outputs (Phase 3), validator (Phase 4).

## Tasks

### 1. Formalize decision variables & constraints
- `x_ij = 1` if SKU `i` assigned to location `j`, else `0`.
- `sum_j x_ij = 1` for SKUs on a single-location policy (extend to quantities if mixed storage).
- `x_ij <= a_ij` (a_ij = 1 iff SKU compatible with location per validator).
- Enforce location capacity, structural load, and compatibility **as hard constraints** via the
  validator after every move/swap.

### 2. Define the objective
A practical start: `minimize sum_i sum_j d_i * c_j * x_ij` where `d_i` = demand/pick frequency of
SKU `i` and `c_j` = travel cost to access location `j`.

Then extend to a documented weighted objective:
```
minimize  alpha*D + beta*A + gamma*E + delta*U
```
where D = travel cost, A = affinity penalty (separate co-ordered SKUs), E = ergonomic penalty
(golden-zone for frequent picks; safe height for heavy SKUs), U = space-utilization penalty
(match SKU footprint to capacity). Weights `alpha, beta, gamma, delta` come from config and must
be calibrated + documented. **Safety rules are NOT part of these weights** — they are enforced
hard by the validator.

### 3. Generate a feasible initial allocation
- Greedy: place highest-velocity SKUs into accessible/golden-zone locations near dispatch first,
  respecting compatibility and capacity. Check feasibility incrementally.
- Place co-ordered SKUs in nearby pick-faces where feasible.
- If no feasible assignment exists for a SKU, record it explicitly (do not force an invalid slot).

### 4. Improve with a constrained refinement method
- Implement **local search** (swap/move SKUs between locations, evaluate delta objective, keep
  improving feasible moves). This is the primary refinement method.
- Add **simulated annealing** for larger/complex layouts to escape local optima (parameter-tuned,
  seeded).
- **Optional** (validation benchmark): a MILP formulation on a small/medium instance (e.g.
  OR-Tools or `scipy.optimize.milp`) to assess solution quality against the heuristics.
- Recommended path: greedy starter → local search → (optionally) simulated annealing, with MILP
  as a small-instance benchmark.

### 5. Re-validate & audit every solution
- Every accepted candidate must pass the Phase 4 validator.
- Produce an **optimization log**: initial vs. final objective, number of moves/swaps evaluated,
  runtime, feasibility status, and whether the stopping criterion was reached.
- Do NOT label a heuristic result as globally optimal unless that is actually established.

### 6. Outputs
Write:
- `outputs/optimized_assignments.csv` — SKU-to-location mapping (with assigned quantity).
- `outputs/baseline_assignments.csv` — the baseline mapping used for evaluation (unchanged from
  Phase 2).
- `outputs/optimization_summary.json` — objective values, weights, feasibility status, runtime,
  algorithm name/version, input dataset version, stopping reason.

## Deliverables / outputs for this phase
- `src/optimization/optimizer.py`, `objective.py`, and any algorithm modules (greedy, local search,
  annealing, optional MILP).
- The three output files above.
- Tests (positive feasibility, infeasibility handling, deterministic-with-seed where applicable).

## Acceptance checks (verify before finishing)
- [ ] Optimized assignment passes **100%** of hard constraints in the Phase 4 validator.
- [ ] Every SKU is assigned (or explicitly reported infeasible with a reason).
- [ ] Objective improves over the baseline on the chosen (same-order, same-geometry) evaluation.
- [ ] Run is reproducible given a seed and its config/weights are recorded.
- [ ] The log reports whether feasibility was achieved and the stopping reason.

## Constraints / gotchas
- Hard constraints always dominate objective weights.
- Keep optimized and baseline assignments in separate files; never overwrite the baseline.
- Do not claim global optimality for heuristic results.
- If infeasible configurations are given as input, handle and report them explicitly rather than
  silently returning a "best effort" assignment as if it were feasible.