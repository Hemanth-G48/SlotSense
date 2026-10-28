# PHASE 7 — Interactive Optimization Dashboard

## Goal
Build an interactive visualization interface that displays the warehouse layout, demand-class and
utilization views, baseline-vs-optimized pick routes, and KPI comparisons. It MUST be connected to
the **actual** allocation and simulation outputs — not hardcoded example charts.

## Context you need
- Read `Smart_Warehouse_Slotting_Execution_Plan.txt` PHASE 6 and section 6 (recommended stack:
  Streamlit or React front-end; Plotly for charts).
- Reference `useful_repos/warehouse-operations-optimization/app.py` (Streamlit + Plotly dashboard)
  and `useful_repos/smart-warehouse/smart-warehouse-web` (warehouse grid visualization + API).
- Inputs: all output CSVs/JSON from Phases 2, 3, 5, 6.

## Tasks

### 1. Choose the stack
- Primary recommendation: **Streamlit** app served from `app/main.py` with Plotly for charts
  (fastest path to a working demo). A React app is acceptable if you prefer, but keep it reading
  the same output files.

### 2. Layout & warehouse grid visualization
- Render racks / bays / shelf levels / bins as a grid or floor-plan.
- Color-code locations by: demand class (A/B/C), cube utilization, or safety/constraint status.
- Support zoom/overview of zones, aisles, and shelf levels.

### 3. Demand & analysis views (from Phase 3)
- ABC Pareto curve + SKU-count / pick-share by class.
- Affinity / co-occurrence visualization (lift-heatmap or cluster graph).
- Volume & capacity-class distribution.

### 4. Routes & comparative views (from Phase 6)
- Overlay **baseline vs. optimized pick routes** on the warehouse layout.
- Side-by-side or toggleable comparison of the two layouts.

### 5. KPI cards & charts
- Show distance, route time, cube utilization, safety compliance, feasibility, runtime for both
  baseline and optimized, with absolute diff and % change.
- Include a clear before/after bar chart.

### 6. Inspection & selection
- Selecting an SKU or a location shows its assignment and constraint details.
- Show constraint-violation details (from `constraint_audit.csv`) and the optimization summary.

### 7. Interactivity & exports
- Let the user change input configuration (e.g., layout params) or select a completed
  optimization run; the displayed results MUST update from the underlying data.
- Provide downloadable assignment and evaluation reports (CSV/JSON).

### 8. Live playground (nice-to-have)
- Sliders for routing strategy and batch size that re-run the Phase 6 simulation and live-update
  savings, filtering to a cached subset for responsiveness.

## Deliverables / outputs for this phase
- `app/main.py` (+ `app/pages/*` if using Streamlit multi-page) implementing all views above.
- A requirements addition for the dashboard stack.
- Screenshots or a runnable demo path that proves the dashboard renders real outputs.

## Acceptance checks (verify before finishing)
- [ ] The layout, demand views, routes, and KPIs all read from generated output files, not
    hardcoded data.
- [ ] Selecting a completed run or an SKU/location updates the displayed results from the data.
- [ ] Assignments and evaluation reports are exportable.
- [ ] The dashboard runs from a fresh state using the Phase-2/5/6 outputs.
- [ ] Safety status and constraint violations are visible, not just travel metrics.

## Constraints / gotchas
- Acceptance test (from the plan): changing the input configuration or choosing a completed run
  updates the displayed charts from underlying data.
- Don't hide safety/feasibility — surface violations; a lower-travel layout that violates
  constraints must not be shown as "better."
- Reuse the Phase-6 simulation for the playground rather than re-implementing metrics in the UI.