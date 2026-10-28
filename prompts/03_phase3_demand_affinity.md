# PHASE 3 — Demand, Affinity & Velocity Analysis Modules

## Goal
Build the analysis modules that convert raw transaction history into actionable placement
priorities: per-SKU demand frequency and velocity, ABC classification, order-affinity scores,
and volume profiles. These outputs feed the optimizer (Phase 5).

## Context you need
- Read `Smart_Warehouse_Slotting_Execution_Plan.txt` PHASE 2 and section 2 (the
  "Requirement → implementation → evidence" table for ABC, affinity, and golden-zone).
- Reference `useful_repos/Warehouse-Order-Picking-Operational-Analytics` and
  `useful_repos/warehouse-operations-optimization/src/slotting_optimization.py` for ABC method
  patterns.
- Input tables come from Phase 2 (`orders`, `order_items`, `products`, `locations`).

## Tasks

### 1. Demand frequency & velocity
For every SKU compute:
- `demand_frequency` = number of distinct orders containing the SKU.
- `total_units_sold` and `total_units_picked` per period.
- A recency-informed velocity score if you have timestamps (e.g., weighted by trailing-window decay).
Aggregate across the chosen primary demand scenario (Scenario A by default; keep B and C available).

### 2. ABC classification (documented Pareto rule)
- Rank SKUs by demand from highest to lowest.
- Compute cumulative demand share.
- Apply documented, configurable thresholds: Class A = first 80% of cumulative demand,
  Class B = next 15%, Class C = remainder. (Thresholds come from config and must be recorded.)
- Emit a classification table: `sku_id`, demand metrics, rank, cumulative share, `abc_class`.

### 3. Order affinity / co-occurrence
- Build SKU-pair co-occurrence counts from orders.
- Compute support, confidence, and lift for pairs (or Apriori itemsets).
- Cluster frequently co-ordered products into affinity groups/clusters (e.g., connected
  components or community detection on a lift-weighted graph).
- Emit an affinity matrix and a cluster assignment: `(sku_a, sku_b, co_count, support, confidence,
  lift)` and `(sku_id, affinity_cluster_id)`.

### 4. Volume & capacity-class profiling
- Profile SKU unit-volume and weight distributions.
- Compute total storage volume/weight required per SKU given inventory quantities.
- Map each SKU to a suitable storage-capacity class (which bin sizes it can fit).
- Identify volume-mismatch and density opportunities (from the EDA in Phase 2).

### 5. Outputs as structured files
Write:
- `outputs/abc_classification.csv`
- `outputs/demand_summary.csv`
- `outputs/affinity_matrix.csv`
- `outputs/affinity_clusters.csv`
- `outputs/volume_profiles.csv`

Make each module importable (`src/analytics/`) and testable in isolation with small fixtures.

## Deliverables / outputs for this phase
- `src/analytics/` modules: `demand.py`, `abc.py`, `affinity.py`, `volume_profile.py`.
- The five structured output files above.
- Unit tests for each module (Pareto boundary cases, affinity math correctness, empty/edge input).

## Acceptance checks (verify before finishing)
- [ ] ABC classes partition all SKUs and match the documented thresholds on the demand scenario.
- [ ] Affinity scores (support/confidence/lift) are mathematically correct on a sample.
- [ ] Volume profiles map every SKU to at least one compatible capacity class.
- [ ] Output schemas match the naming/units conventions.
- [ ] Modules run standalone on the Phase-2 data without the optimizer.

## Constraints / gotchas
- These are **inputs** to the optimizer — implement them now, in isolation, before the optimizer.
- Affinity and velocity are soft preferences for placement; they must never cause a
  safety/feasibility violation later.
- Keep aggregation methods (frequency vs. picked units vs. units sold) explicit and consistent
  between ABC and the optimizer's demand term.