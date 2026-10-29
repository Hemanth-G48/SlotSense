# PROJECT.md — Smart Warehouse Slotting & Optimization Engine

**Track:** Epoch Hackathon — Track 2
**Source of truth:** `PS_Track2.pdf` (body text). The PDF's title line reads *"PS: Smart Virtual
Rehabilitation Companion"* and is a copy/paste artefact from another track; the body — warehouse
slotting — is the governing content and everything below is derived from it.

> **Provenance rule for this document:** every requirement here is traceable to a sentence in the
> problem statement. Nothing is derived from an existing codebase. Where the PS is silent, the gap
> is recorded in *§9 Open decisions* rather than silently filled in.

---

## 1. What the PS asks for

A fulfilment centre loses throughput to **suboptimal SKU placement**. When high-demand items sit far
from packing stations, or heavy/bulky items are stored on upper shelf tiers without ergonomic
consideration, pickers burn their shift on travel. Poor layout also wastes warehouse volume, overloads
rack beams structurally, and creates safety risk by storing incompatible categories near each other.

The deliverable is an **end-to-end Smart Warehouse Slotting & Optimization Engine** that:

1. ingests raw warehouse layout topography, SKU physical metadata, and order transaction logs,
2. runs them through optimization logic,
3. produces a **fully feasible** layout assignment (every constraint satisfied),
4. and proves **quantitative efficiency gains over an unoptimized baseline layout**.

Four things must therefore coexist in one system: a **feasibility engine** (hard rules), an
**optimizer** (demand-aware placement), a **comparative evaluator** (baseline vs. optimized under
identical conditions), and a **data pipeline** the team sources itself.

---

## 2. Scope

### In scope (PS §2, §3, §4)

| Area | What it covers |
|---|---|
| Constraint engine | 3-D fit, volume, per-bin/per-shelf/per-rack weight, category & hazard separation, heavy-SKU height limits |
| Demand modelling | ABC/velocity extraction from order history, basket co-occurrence mining, golden-zone ergonomics |
| Allocation | Assignment of every SKU to physical bins/racks/shelf levels, satisfying all rules |
| Comparative evaluation | Baseline vs. optimized under identical demand, geometry, routing |
| Data pipeline | Self-sourced/synthesised demand, SKU master, and warehouse topology vectors + documented EDA |
| Presentation | Interactive dashboard (layout visuals, pick-path simulation, baseline vs. optimized metrics) |
| Documentation | Architecture, constraint logic, computational complexity, EDA insights, trade-offs |

### Explicitly not required by the PS

Recorded so the team does not gold-plate. These are **omissions from the PS, not prohibitions**:

- live WMS/ERP integration, real-time order streaming, or hardware/robotics control,
- multi-warehouse network optimisation (the PS speaks of *a* warehouse and one I/O dispatch area),
- picking-route optimisation as a research contribution — routing exists to *measure* slotting impact,
  so a standard heuristic is sufficient provided it is applied identically to both layouts,
- labour scheduling, cost accounting in currency, or carbon modelling (no metric named in the PS).

---

## 3. Requirements

Requirement IDs are stable; use them in the technical documentation and in the demo script.

### R1 — Rule-based & physical constraint enforcement

**R1.1 Volumetric & spatial bounds.** Match SKU 3-D dimensions (width, height, depth) and total volume
against target bin dimensions and structural capacity without exceeding limits.
*Acceptance:* for every assignment, each SKU dimension ≤ the corresponding bin dimension, and
`Σ(unit_volume × assigned_qty) ≤ usable bin volume`; the validator reports the observed value and the
limit for each check, and a deliberately over-sized assignment is rejected with a named rule.

**R1.2 Structural load & weight rating.** Total assigned weight per **shelf level** and per **rack
frame** must strictly respect maximum safe load-bearing limits.
*Acceptance:* shelf-level and rack-level loads are aggregated across all bins on that shelf/rack (not
just per bin) and compared to their own limits; a synthetic overload is detected at both levels.
Three distinct limits exist and are enforced independently: per-bin, per-shelf-level, per-rack.

**R1.3 Category & hazard compatibility.** Enforce a physical separation matrix: hazardous materials
isolated from standard inventory; fragile items kept out of high-risk zones; heavy SKUs barred from
upper shelf tiers.
*Acceptance:* a declared compatibility/separation matrix exists as data (not hard-coded per SKU), the
validator checks hazard class against zone allowance and handling type against zone allowance, and
heavy handling types are rejected above the configured maximum shelf level. Each violation names the
rule, the SKU, the location, the observed class, and the permitted set.

**R1.4 Hard vs. soft separation.** Rule violations are *hard* — a layout with any violation is
infeasible and cannot be presented as a result. Optimisation objectives never trade a violation for a
better score.

### R2 — Demand-aware & frequency-driven optimization

**R2.1 Velocity profiling (ABC).** Process the historical order stream to extract item demand
frequency and velocity, and classify SKUs into Class A (high), B (medium), C (low).
*Acceptance:* classification is computed from transaction data with a documented rule (Pareto-based
cumulative-share thresholds) and is reproducible from the input files; the class boundary rule is
stated in the documentation.

**R2.2 Proximity of A-class to I/O.** High-velocity SKUs map to prime accessibility zones near the
input/output dispatch area.
*Acceptance:* the objective contains an explicit demand-weighted distance-to-dispatch term, and the
evaluation reports the change in demand-weighted distance from baseline to optimized.

**R2.3 Order affinity & co-occurrence.** Mine basket data for item co-occurrence and cluster
frequently co-ordered products into adjacent pick-faces to cut multi-item pick path traversal.
*Acceptance:* a derived affinity table exists (pair, co-occurrence count, and an association score such
as lift); the optimizer uses it; the evaluation reports a co-occurrence-weighted separation metric
(average distance between related SKU pairs) for both layouts.

**R2.4 Golden-zone ergonomics.** High-frequency picks should sit at chest-to-waist picking heights.
*Acceptance:* the topology carries an ergonomic zone / shelf-level band, the objective penalises
high-demand SKUs outside it, and the evaluation reports the demand-weighted share of units pickable
from the golden band for both layouts.

**R2.5 Replenishment awareness.** The PS names *"Ergonomic & Replenishment Efficiency"* as one
consideration. The engine must at minimum state how replenishment interacts with the chosen layout
(e.g. restock travel to dispersed bins) and report it as a metric or a documented trade-off — not
leave it unaddressed.

**R2.6 Inventory conservation.** Optimization relocates stock; it never invents, duplicates, or drops
it. Every SKU's on-hand quantity is fully placed, spanning multiple bins when a single bin cannot hold
it.
*Acceptance:* `Σ assigned_qty per SKU == on-hand qty` for every SKU, checked by the validator; both
layouts are validated and their violation counts reported.

### R3 — Comparative evaluation & impact engine

**R3.1 Baseline.** An initial/random SKU distribution exists as a first-class artifact, is itself
feasible-or-explicitly-reported, and is the reference for every improvement claim.

**R3.2 Identical conditions.** Both layouts are simulated under the same demand history, same geometry,
same routing strategy, and the same inventory totals — otherwise the comparison is invalid.

**R3.3 Required metrics.** The comparison must report, at minimum:

| Metric | PS wording | Definition the engine must document |
|---|---|---|
| Travel distance | *total pick path travel distance reduction* | total distance over the simulated pick workload, identical batches, % reduction vs. baseline |
| Cube utilization | *overall volumetric cube utilization (fill rate %)* | occupied inventory volume ÷ usable storage volume; state explicitly whether the denominator is the whole warehouse or the occupied bins |
| Pick route completion time | *pick route completion time* | travel + pick + setup time per batch, and throughput in orders/hour |
| Safety compliance | *zero-tolerance safety rule compliance* | violation count per layout; both must be 0, or the gap is stated |

**R3.4 Honesty of claims.** A metric that cannot improve by construction (e.g. total warehouse fill
when inventory is fixed) must be reported with its construction explained, plus a metric that *does*
move (e.g. fill rate of active bins, bins occupied). No improvement may be presented without its
numerator, denominator, and the identical-conditions statement.

---

## 4. Data mandate (PS §3)

**No dataset is provided.** The team must search, identify, acquire, synthesise, or curate its own
pipeline. "Synthesise" is explicitly permitted; "unattributed" is not — every field must carry a
provenance note (real / derived / synthetic + rule).

### D1 — Order & demand data
Required fields: `Order_ID`, `SKU_ID`, `Quantity`, `Timestamp`.
Acceptable sources named in the PS: Instacart Market Basket Analysis, Kaggle Online Retail II, Olist
Brazilian E-Commerce — or a custom synthetic transaction generator.

### D2 — SKU physical master data
Required fields: `SKU_ID`, `Width`, `Height`, `Depth`, `Weight`, `Category`, `Hazard_Class`,
`Handling_Type`.

### D3 — Warehouse topological grid
Required fields: `Location_ID`, `Zone`, `Aisle_Number`, `Rack_ID`, `Bay`, `Shelf_Level`,
`X_Y_Z_Coordinates`, `Max_Weight_Capacity`, `Volumetric_Capacity`, `Distance_to_Dispatch_Depot`.

### D4 — Provenance
Each of the three vectors states its source, licence, retrieval date, and — for anything synthetic —
the generating rule and seed, so a reviewer can reproduce the dataset.

---

## 5. EDA mandate (PS §3)

Documented **before** the allocation engine is described, and reproducible from the shipped data:

1. **Demand velocity profiling** — Pareto (80/20) analysis; SKUs categorised into Class A / B / C.
   Ship the cumulative-share curve and the threshold rule.
2. **Affinity & co-occurrence matrix** — market-basket mining (Apriori or an association score) to
   find product pairs and clusters appearing in the same order batch. Ship the matrix, the support /
   confidence / lift definition, and the clustering method.
3. **Volumetric density & space profiling** — product volume distributions against bin capacity
   classes, exposing under-utilisation, volume-mismatch bottlenecks, and density opportunities.

Each EDA output must be presented as a *finding with a consequence for the design*, not a chart dump.

---

## 6. Deliverables (PS §4)

**D-1 Working allocation prototype.** Accepts warehouse configuration + SKU/demand datasets, runs the
allocation algorithm, outputs feasible constraint-compliant storage assignments. It must be runnable
end-to-end from a clean checkout with documented setup, and it must emit the assignment file plus a
machine-readable constraint report.

**D-2 Interactive optimization dashboard.** Visualises (a) the layout — grid/heatmap of storage
locations over the warehouse plan, (b) pick-path travel simulation, (c) performance metrics
baseline vs. optimized. "Interactive" means the viewer can select/filter (zone, class, scenario) and
see the numbers update — not a static screenshot deck.

**D-3 Technical & algorithmic documentation.** System architecture; constraint-handling logic; the
**computational complexity** of the algorithm(s); EDA insights; and a **trade-off analysis** (what the
optimizer sacrifices, e.g. affinity cohesion vs. dispatch proximity, and at what runtime).

---

## 7. Definition of done

The project is done when all of the following are true:

1. A clean checkout runs the full pipeline with one documented command sequence: data → EDA →
   baseline → optimize → evaluate → dashboard.
2. The optimized assignment has **zero** hard-constraint violations, and the validator can demonstrably
   *fail* a seeded bad layout (the rules are real, not decorative).
3. The baseline and optimized layouts were simulated under identical demand/geometry/routing, and the
   comparison table reports travel distance, cube utilisation, pick-route time/throughput, and safety
   compliance.
4. Every improvement claim states its numerator, denominator, and definition; metrics that cannot move
   by construction are labelled as such.
5. The three data vectors ship with provenance and the EDA notebook/report reproduces the ABC split,
   the affinity matrix, and the volume-vs-capacity profile.
6. The dashboard serves the three required views and every number on it is traceable to a generated
   artifact.
7. The technical document contains architecture, constraint logic, complexity, EDA insight, trade-offs.

---

## 8. Traceability — PS sentence → requirement

| PS location | Statement | Requirement |
|---|---|---|
| §1 | high-demand items far from packing stations | R2.1, R2.2 |
| §1 | heavy/bulky on upper tiers without ergonomic consideration | R1.3, R2.4 |
| §1 | underutilised warehouse volume | R1.1, R3.3 (cube) |
| §1 | structural weight overload on rack beams | R1.2 |
| §1 | incompatible categories stored near one another | R1.3 |
| §2 | ingest layout + SKU metadata + order logs | D1–D3 |
| §2 | fully feasible layout + explicit quantitative proof | R1.4, R3.1–R3.4 |
| §2.1 | volumetric & spatial bounds | R1.1 |
| §2.1 | structural load & weight rating | R1.2 |
| §2.1 | category & hazard separation matrix | R1.3 |
| §2.2 | ABC velocity profiling | R2.1 |
| §2.2 | order affinity & co-occurrence → adjacent pick faces | R2.3 |
| §2.2 | ergonomic & replenishment efficiency | R2.4, R2.5 |
| §2.3 | baseline vs optimized simulation | R3.1, R3.2 |
| §2.3 | travel distance, cube utilisation, completion time, safety | R3.3 |
| §3 | self-sourced pipeline, three vectors, field lists | D1–D3 |
| §3 | EDA: Pareto/ABC, affinity matrix, volumetric profiling | §5.1–5.3 |
| §4 | prototype, dashboard, technical documentation | D-1, D-2, D-3 |

---

## 9. Open decisions (the PS is silent — decide and record)

These are gaps the PS does not resolve. Each must be answered explicitly in the technical
documentation rather than assumed silently:

1. **Cube-utilisation denominator** — whole warehouse vs. occupied bins. (Whole-warehouse fill cannot
   move when inventory is fixed; the PS asks for "fill rate %" without specifying.)
2. **Hazard taxonomy depth** — how many hazard classes, and whether the separation matrix is
   class-pair-level or zone-level.
3. **One SKU per bin vs. co-storage** — the PS mandates *separation* rules but not whether a bin may
   hold multiple compatible SKUs.
4. **Shelf-level semantics** — is level 0 the floor, and what band counts as chest-to-waist?
5. **Replenishment model** — the PS names replenishment efficiency but defines no replenishment
   process (trip frequency, pallet replenishment, forward-pick areas).
6. **Scenario count** — how many demand histories to simulate; whether multi-scenario results must be
   averaged or reported per scenario.
7. **Scale target** — no SKU/bin count is specified; the team sets a scale it can demonstrate within
   the judging window and states the runtime at that scale.
