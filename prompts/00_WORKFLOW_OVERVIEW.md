# Smart Warehouse Slotting & Optimization Engine — Phase-Wise Prompt Series

This folder contains a set of self-contained, phase-wise developer prompts for building the
**Smart Warehouse Slotting & Optimization Engine** end to end. Feed each prompt to an AI
coding agent (or a human team) in order. Each prompt is designed to be executed independently,
producing working, verifiable artifacts that the next phase builds on.

## Problem context (summary of PS_Track2)

Build an end-to-end engine that maps SKUs to physical warehouse locations (bins, racks,
shelf levels) based on:

- Historical demand patterns and SKU velocity (ABC classification).
- 3D spatial dimensions (width × height × depth) and volume against bin capacity.
- Physical weight bounds and structural (shelf/rack) load limits.
- Product category and hazard compatibility (separation matrix).
- Order affinity / co-occurrence (market basket analysis).
- Ergonomic golden-zone and heavy-item shelf-height rules.
- Pick-path distance and route completion time.

The system must option an inbound batch of orders through optimization logic and produce a
**feasible, constraint-compliant layout assignment** plus **quantitative proof of improvement
over an unoptimized baseline layout**.

### Three required deliverables

1. **Working allocation prototype** — accepts warehouse configuration, SKU metadata, and
   demand data; runs allocation; enforces all hard constraints; outputs a feasible,
   constraint-compliant storage assignment.
2. **Interactive optimization dashboard** — visualizes warehouse layout, demand-class
   heatmaps, baseline vs. optimized pick routes, and KPI comparisons (distance, time,
   utilization, safety).
3. **Technical & algorithmic documentation** — architecture, constraint-handling logic,
   computational complexity, EDA insights, and trade-off analysis.

### Key evaluation metrics

| Metric | Meaning | Target |
|---|---|---|
| Total pick travel distance | Sum of route distances across evaluated orders | Lower is better |
| Pick route completion time | Travel time + modeled handling/delays | Lower is better |
| Volumetric cube utilization | Occupied volume / usable storage volume × 100 | Higher is better |
| Safety compliance | Number of hard-rule violations | **Zero** in optimized layout |
| Assignment feasibility | Valid assignments / total assignments × 100 | **100%** |
| Optimization runtime | Wall-clock execution time | Reported, practical |

Travel distance reduction (%) = (Baseline − Optimized) / Baseline × 100.
Report utilization changes in percentage points, separately from relative percentage change.

### Core design principle (from the execution plan)

**Build the constraint validator and evaluation framework BEFORE advanced optimization or
dashboard styling.** Without a validator and an evaluation harness, the system may produce
attractive layouts without proving assignments are safe, feasible, or genuinely more efficient.
Safety and physical feasibility are HARD constraints — never softened by objective weights.

## The phase sequence (use these exact prompts in order)

| # | Phase | Prompt file | Core output |
|---|---|---|---|
| 1 | Project scaffold & warehouse domain model | `01_phase1_domain_model.md` | Repo skeleton, data schemas, configs, baseline layout |
| 2 | Dataset pipeline & EDA | `02_phase2_dataset_eda.md` | Curated/synthetic dataset + EDA report |
| 3 | Demand, affinity & velocity analysis | `03_phase3_demand_affinity.md` | ABC labels, affinity matrix, volume profiles |
| 4 | Constraint validation engine | `04_phase4_validator.md` | Reusable validator + tests |
| 5 | Allocation optimizer | `05_phase5_optimizer.md` | Feasible optimized assignment + log |
| 6 | Route simulation & baseline-vs-optimized evaluation | `06_phase6_simulation_evaluation.md` | Comparable metrics, reproducible results |
| 7 | Interactive dashboard | `07_phase7_dashboard.md` | Visualization connected to real outputs |
| 8 | Integration, testing & technical documentation | `08_phase8_integration_docs.md` | End-to-end pipeline + final report |

> Note on datasets: The problem statement provides no ready-made dataset. Phases 2 optionally
> sources real open data (e.g., Instacart, Online Retail II, Olist, Mendeley footwear warehouse)
> but always backs the main benchmark with clearly-labeled synthetic data generated over a
> unified SKU master so the whole constraint set is testable. See the dataset roadmap for details.

## How to use these prompts

- Create a clean working directory per phase (or keep one repo and implement phases in order).
- Give each prompt to an agent with its full text and the repo context. Each prompt is written
  to be run with the `prompts/` folder and the project docs available.
- After a phase completes, run its listed acceptance checks before moving on. Later phases
  assume the earlier artifacts exist with the documented schema.
- Keep all hard constraints, schemas, and metric definitions consistent with this overview and
  with `Smart_Warehouse_Slotting_Execution_Plan.txt` and `warehouse_optimization_dataset_roadmap.txt`.