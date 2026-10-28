# VALIDATION PROMPT — PHASE 7: Interactive Optimization Dashboard

You are an independent validator. Test the interactive dashboard from
`prompts/07_phase7_dashboard.md`. The critical acceptance test is that it displays REAL output
data and updates from the data — not hardcoded charts. Score it and return a confidence verdict.

## Scope (what Phase 7 was supposed to deliver)

1. **Dashboard app** — `app/main.py` (+ `app/pages/*`) using Streamlit (or an equivalent React
   front-end), with Plotly charts.
2. **Layout / warehouse-grid visualization** — racks, bays, shelves, bins; color-coded by demand
   class, utilization, or safety status.
3. **Demand & analysis views** — ABC Pareto curve, affinity (lift/cluster), volume/capacity-class
   distribution (fed by Phase 3 outputs).
4. **Routes & comparative views** — baseline vs. optimized pick routes overlaid/toggled on the
   layout (fed by Phase 6 outputs).
5. **KPI cards & charts** — distance, route time, cube utilization, safety, feasibility, runtime;
   before/after with diff and % change.
6. **Inspection & selection** — selecting an SKU/location shows its assignment and constraint
   details; constraint violations and optimization summary visible.
7. **Exports** — downloadable assignment and evaluation reports (CSV/JSON).
8. **Live playground (nice-to-have)** — routing strategy / batch-size sliders that re-run the
   Phase-6 simulation and live-update.

## Verification steps

### D7.1 App runs (weight 0.15)
- [ ] Dashboard launches without error from the current repo state (`streamlit run app/main.py`
   or equivalent) and renders.

### D7.2 Connects to real data (weight 0.30 — critical)
- [ ] Every view reads from generated output files/artifacts (Phase 2/3/5/6 CSVs & JSON), NOT
   hardcoded data. Inspect the code paths feeding each chart.
- [ ] **Acceptance test:** changing the input configuration or selecting a different completed
   optimization run updates the displayed results from the underlying data. Demonstrate this by
   switching between two runs (or two demand scenarios) and confirming the numbers change.

### D7.3 All required views present (weight 0.20)
- [ ] Layout grid with demand-class/utilization/safety coloring.
- [ ] ABC Pareto + affinity + volume views.
- [ ] Baseline vs. optimized routes (overlay or toggle).
- [ ] KPI cards (distance, time, utilization, safety, feasibility, runtime) with before/after diffs.
- [ ] SKU/location inspection with constraint details (from `constraint_audit.csv`).

### D7.4 Safety & feasibility surfaced (weight 0.20)
- [ ] Constraint-violation and safety status are visible (a low-travel layout that violates
   constraints must NOT be shown as "better").

### D7.5 Exports (weight 0.10)
- [ ] Assignment and evaluation reports are downloadable (CSV/JSON) from the UI.

### D7.6 Playground (weight 0.05, nice-to-have)
- [ ] If present, sliders re-run the Phase-6 simulation and live-update; must reuse the Phase-6
   simulation, not re-implement metrics.

## Scoring
Score each deliverable 0–100 per `00_VALIDATION_OVERVIEW.md`. **Failure of the D7.2 "updates from
real data" acceptance test caps the phase at PARTIAL** (the dashboard is then only a static mock).
Weighted phase score → PASS (≥80) / PARTIAL (50–79) / FAIL (<50).

## Acceptance (phase-level pass criteria)
- App runs, renders real data, all required views present, safety surfaced, exports work. If the
   dashboard uses hardcoded charts or cannot update from data, it is not acceptable as
   Deliverable 2.

## Output
Write `outputs/validation/phase7_validation.json`, then a short prose summary: per-deliverable
verdicts, phase score, the update-from-data acceptance test result, and required rework before
Phase 8.