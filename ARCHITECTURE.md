# ARCHITECTURE.md — Smart Warehouse Slotting & Optimization Engine

| Field | Value |
|---|---|
| Version | 9.3 — design specified against `PS_Track2.pdf` (pass 11), updated with Phase 6 reproducibility and Phase 7 optimizer-neighbourhood evidence. "Specified" means every PS requirement has a mechanism here; it does **not** mean the code exists (§15) or that no decisions remain (§18). |
| Status | Every PS requirement resolves to a mechanism in this document (§15). §16 lists what is not yet built. |
| Derived from | `PS_Track2.pdf` (Track 2, warehouse slotting) and `PROJECT.md` (R1–R3, data vectors, deliverables) |
| Verification | `python tools/check_architecture.py` asserts the document's structural invariants |

**How to read this.** §1–§14 are the design, and they are normative: sufficient to build from without
further decisions. §15 maps every PS requirement to the mechanism that satisfies it and states whether the
code implements it. §16 is the implementation backlog — not a list of design gaps. A requirement with no
mechanism would be a bug in this document; a requirement with a mechanism but no code is a task.

**ID namespaces.** A bare deviation ID such as `D34` means a row in §16. `PROJECT.md` uses its own spellings —
`D1–D3` for the data vectors, `D-1…D-3` for the deliverables — and this document cites them with that spelling
plus a qualifier (`PROJECT.md D-3 (documentation)`), never as a bare code.

---

## 1. What the PS asks for, and the four guarantees that answer it

The brief describes a fulfilment centre losing throughput to poor slotting, then requires an end-to-end
engine that ingests layout, SKU and order data, produces a **fully feasible** assignment, and **proves**
improvement over an unoptimized baseline.

| Guarantee | PS source | Architectural consequence |
|---|---|---|
| **G1 Feasibility is absolute** | §2.1, §2.3 "zero-tolerance safety" | one constraint engine shared by baseline, every candidate and the final answer; violations are not tradeable |
| **G2 Placement is demand-aware** | §2.2 | a multi-term objective in which every term has a published metric and every metric traces to a term |
| **G3 Claims are comparable and honest** | §2.3 | a simulation + evaluation stage with an identical-conditions contract, a metric registry, and a prohibition on bare percentages |
| **G4 Data is ours to source and prove** | §3 | three self-sourced vectors, a licence-bearing provenance manifest, and EDA as a pipeline stage |

Supporting: **decision determinism** (same inputs and seed ⇒ same layout, metrics and routes; summaries still
carry runtime and paths, so files are not byte-identical and need not be) and **one source of truth per
fact** (one schema registry, one rule catalogue, one travel-distance function, one golden-band value).

---

## 2. Scope

In: constraint engine, demand analytics, allocation optimizer, route simulation, comparative evaluation,
dashboard, dataset pipeline, technical documentation.

Out: live WMS/ERP integration, real-time streaming, robotics control, multi-warehouse networks,
currency/labour costing. Routing exists to *measure* slotting impact — a standard heuristic suffices
provided it is applied identically to both layouts.

---

## 3. System context

```
   open data / synthetic generator
              │
              ▼
   ┌─────────────────────┐      ┌──────────────┐      ┌───────────────┐
   │  Dataset builder    │─────▶│  Constraint  │◀────▶│  Optimizer    │
   │  (+ split builder)  │      │    engine    │      │ greedy/repair │
   └─────────┬───────────┘      └──────┬───────┘      │   + anneal    │
             │                         │              └───────┬───────┘
             ▼                         ▼                      ▼
   ┌─────────────────────┐      ┌──────────────┐      ┌───────────────┐
   │  EDA / analytics    │      │  Simulator   │─────▶│  Evaluation   │
   └─────────┬───────────┘      └──────┬───────┘      └───────┬───────┘
             └───────────────┬─────────┴──────────────────────┘
                             ▼
                    ┌──────────────────┐
                    │ Dashboard (read) │
                    └──────────────────┘
```

Actors: **operator** (runs the pipeline, reads the dashboard) and **judge** (reproduces results, reads the
report). No server, no accounts: a batch pipeline plus a read-only view over its artifacts.

---

## 4. Containers and dependency rules

| Container | Owns | May not |
|---|---|---|
| `app/main.py` | CLI orchestration | contain domain logic |
| `src/data_processing` | schema registry, generator, dataset validator, EDA plumbing, split builder | import the optimizer |
| `src/analytics` | demand, ABC, affinity, volume profiles | mutate processed data |
| `src/validation` | rule catalogue, feasibility verdicts | optimise, score, rank |
| `src/optimization` | objective, greedy, repair, annealing, merge/split | define what is legal |
| `src/routing` | travel graph (Dijkstra) and separation geometry (3-D) | confuse the two |
| `src/simulation` | batches, routes, cycle time | invent timings |
| `src/evaluation` | registry, comparison, decomposition, segment rows | hide a non-moving metric |
| `app/dashboard*` | presentation | write artifacts or compute metrics |

`src/validation` never imports `src/optimization` — that is what makes "same rules for baseline and answer"
structural; no `src/*` imports `app/*`; the dashboard is read-only.

---

## 5. Data architecture

### 5.1 Tables (12)

Registered once in `src/data_processing/schema.py` — column order, dtype, unit, meaning — so generator,
dictionary and validator cannot drift.

| Table | Grain | Purpose |
|---|---|---|
| `warehouses` | `warehouse_id` | layout version, data source, quality |
| `categories` | `category_id` | taxonomy, storage notes |
| `products` | `sku_id` | W/H/D, unit volume, weight, handling, hazard |
| `locations` | `location_id` | zone/aisle/rack/bay/shelf, XYZ, **four limits**, ergonomic zone, allowed handling/hazard |
| `inventory` | `sku_id + location_id` | on-hand per bin |
| `compatibility_rules` | `rule_id` | category-pair matrix (55 rows, 13 forbidden in v1) |
| `orders` | `order_id` | header + `scenario_id` |
| `order_items` | `order_id + sku_id` | lines + quantity |
| `storage_assignments_baseline` | `sku_id + location_id` | the unoptimized reference layout |
| `location_graph` | `from + to` | aisle network for travel distance |
| `demand_summary` | `scenario_id + sku_id` | frequency, units, rank, cumulative share, ABC class |
| `sku_affinity` | `scenario_id + sku_a + sku_b` | co-count, support, confidence, lift |

**Units, fixed once:** dimensions cm; weight kg; volume cm³; coordinates and distances m; timestamps UTC.

### 5.2 Structural limits — four independent fields

v1 carries one ambiguous `shelf_max_weight_kg`. The design requires four limits per bin, each generated and
validated independently:

| Field | Scope | Meaning |
|---|---|---|
| `max_weight_kg` | bin | what this bin may hold |
| `beam_max_weight_kg` | `(rack, bay, shelf_level)` | what one shelf beam carries — 2 bins in v1 |
| `level_max_weight_kg` | `(rack, shelf_level)` | what one level carries across bays |
| `rack_max_weight_kg` | `rack` | what the rack frame carries across bays and levels |

Independence is a requirement: if the rack limit is derived from the level limits it is implied by them, and
"independent checks" becomes one check performed four times. The generator derives all four from a per-class
beam capacity with documented multipliers; the validator compares each aggregate against its own field.

### 5.3 Provenance

Every row carries `data_source ∈ {measured, sourced, inferred, synthetic, derived}` plus, where relevant,
`data_quality_status` and `physical_confidence`. Sourced spines ship `metadata/source_manifest.json` keyed by
spine with **source, licence, retrieval date, transformation**; a row's `data_source` must resolve into it.
A licence that is not recorded is not provenance — `PROJECT.md` D4 names all three for that reason.

### 5.4 Invariants

| ID | Invariant | Checked by |
|---|---|---|
| I-1 | `Σ assigned == on-hand` per SKU | `INV-01/02/03` |
| I-2 | One SKU per bin unless co-storage is enabled | `AS-01` |
| I-3 | Four independent structural limits, each against its own field | `LD-01`, `SL-02`, `SL-01`, `RK-01` |
| I-4 | Stored volume per bin ≤ usable volume | `VD-01` |
| I-5 | SKU fits in all three axes | `SP-01` |
| I-6 | Hazard class and handling type allowed in the bin's zone | `HZ-01`, `HD-01` |
| I-7 | Heavy handling only at or below the heavy shelf cap | `ER-01` |
| I-8 | No duplicate (SKU, bin) record | `DU-01` |
| I-9 | Both layouts validated by the same engine; both violation counts published | evaluation artifacts |
| I-10 | Every metric computed from artifacts, never in the view layer | registry + dashboard contract |
| I-11 | Decision determinism (not byte-identity) | determinism test (§16) |
| I-12 | Every synthetic column states its rule and seed | dataset validator + manifest |

### 5.5 Spines and split trees

| Spine | Demand | Physical data | Warehouse |
|---|---|---|---|
| `synthetic-v1` | generated, 3 scenarios | class rules | generated 9-zone grid |
| `olist` | real orders | real W/H/D/kg | generated |
| `instacart` | real baskets | class synthesis | generated |
| `spr` | real pick history | real dimensions, hazmat | real bin addresses |

A spine is loadable when `validate --processed <spine>/processed` reports zero hard errors; consuming one
requires no code change, only a path.

A **time split** is also a dataset: `split-dataset` writes
`outputs/splits/<name>/{fit,holdout}/processed/` containing **every table**, with `scenario_id` rewritten to
`A_FIT` / `A_HOLDOUT`. Orders-only slices are forbidden — `demand_summary` and `sku_affinity` are keyed by
scenario, so an orders-only split would leave analytics summarising the whole history.

---

## 6. Components

| Component | Responsibility | Must not |
|---|---|---|
| `data_processing/generate` | topology, products, orders, inventory, baseline, four limits | know about optimisation |
| `data_processing/validate` | schema, referential integrity, capacity sanity, provenance resolution | judge layout feasibility |
| `data_processing/split` | full-tree fit/holdout views with rewritten scenario ids | re-derive demand |
| `analytics/*` | demand, ABC, affinity, volume profiles | mutate data or place SKUs |
| `validation/validator` | rule catalogue, four verdicts | optimise or rank |
| `optimization/optimizer` | greedy, repair, annealing, merge/split | define legality |
| `optimization/objective` | normalised cost + per-term contributions | relax a hard rule |
| `routing/graph` | Dijkstra travel distance | be used for separation |
| `routing/geometry` | 3-D Euclidean separation | be used for travel |
| `simulation/simulator` | batches, routes, cycle time | invent timings |
| `evaluation/metrics` | registry, comparison, decomposition, segment rows | hide a non-moving metric |
| `app/dashboard*` | presentation | compute a metric |

---

## 7. Pipeline stages

Nine stages plus one preprocessing step. `run-all` composes them; it is not a second implementation.

| Stage | Command | Input | Output | Contract | Re-runnable alone |
|---|---|---|---|---|---|
| S0 Config | — | `configs/*.json` | `Config` | unknown keys rejected; no silent defaults for physical limits | yes |
| S1 Build dataset | `build-dataset` | config + vectors | `dataset/<spine>/processed/*` + metadata | schema registry obeyed; every row resolves to a manifest entry | yes |
| S1b Split dataset | `split-dataset` | a processed tree + fraction | `outputs/splits/<n>/{fit,holdout}/processed` | complete tree, every table re-keyed | yes |
| S2 Dataset validation | inside S1/S1b | processed CSVs | validation report | zero hard errors before S3 | no — inside a build |
| S3 EDA / analytics | `run-analysis` | processed CSVs | `outputs/analysis/*` | ABC, affinity and volume rules documented and reproducible | yes |
| S4 Baseline audit | `validate` | baseline assignments | `constraint_audit.csv`, `validation_checks_baseline.csv` | baseline validated by the same engine | yes |
| S5 Optimize | `optimize` | S3 + S4 + distance oracle | `optimized_assignments.csv`, `optimization_summary.json`, `run_history.json` | every candidate validated; output feasible or `INFEASIBLE` | yes |
| S6 Simulate | `simulate` | both layouts + graph + orders | `pick_routes.csv`, `pick_route_stops_*.csv` | identical batches, geometry, routing for both | shared with S7 |
| S7 Evaluate | `simulate` | S6 + validator | `optimization_metrics.csv`, `evaluation_summary.json` | refuses an infeasible **optimized** layout; ratio components stored | shared with S6 |
| S8 Present | `streamlit run app/dashboard.py` | artifacts | — | read-only; missing artifact ⇒ "unavailable", never zero | yes |

**S5's distance oracle.** The affinity term needs pairwise travel distances between bins holding inventory —
up to ~408k pairs on the `instacart` spine. The oracle is built once as an S5 precondition and reused by S6:
not inside S6 (too late) and not per candidate (too slow).

**ABC boundary, exact.** SKUs sorted by demand frequency descending; Class A is cumulative share ≤ 0.80, B is
(0.80, 0.95], C otherwise. The SKU crossing a boundary is not split — it falls into the lower class, so Class
A holds slightly less than 80% of demand. Stated wherever the split is reported, because "A = 384 SKUs" and
"A = 80% of demand" are different quantities.

**Affinity, exact.** `support = co_count/orders`, `confidence(a→b) = co_count/orders_with_a`,
`lift = support/(share_a·share_b)`. **One threshold set, in configuration**, consumed by clustering, by the
optimizer's penalty and by the reported metric — three consumers, one filter, so the pairs the report
measures are the pairs the optimizer pursued.

---

## 8. Constraint engine

### 8.1 Rule catalogue — 17 families, 20 IDs, all blocking

| Rule | Meaning | Axis |
|---|---|---|
| `SP-01` | dimensional fit, per axis | structural |
| `VD-01` | per-bin cumulative volume | structural |
| `LD-01` | per-bin cumulative weight | structural |
| `SL-02` | beam load, `(rack, bay, level)` | structural |
| `SL-01` | level load, `(rack, level)` | structural |
| `RK-01` | rack-frame load, `rack` | structural |
| `HZ-01` | hazard class allowed in the bin's zone | safety |
| `HD-01` | handling type allowed in the bin's zone (`standard`, `fragile`, `heavy`, `temperature_controlled`) | safety |
| `ER-01` | heavy handling not above the heavy shelf cap | safety |
| `CAT-01` | forbidden category pair not co-located in 3-D | safety |
| `CP-01` | co-stored category pair permitted (co-storage mode only) | safety |
| `AS-01` | one SKU per bin | policy |
| `REF-01/02` | SKU and location exist | integrity |
| `QTY-01` | assigned quantity > 0 | integrity |
| `COMP-01` | every SKU with inventory has a home | integrity |
| `INV-01/02/03` | conservation: over / under / match | integrity |
| `DU-01` | no duplicate (SKU, bin) | integrity |

**17 rules and 20 IDs**, all blocking. (A "rule" is one catalogue row; `SL-01` and `SL-02` are two rules on one
physical object.) The current code declares 15 rules (the 14 base checks plus `DU-01`); the target adds
`CAT-01` and `SL-02`. `REF` contributes 2 IDs and `INV` contributes 3. No other section restates a count —
they point here, and the checker parses this sentence against the table.

**`CAT-01`, defined.** For every pair in `compatibility_rules` with `allowed = false` (13 of 55 in v1), the
two categories must be at least `R` metres apart, measured as **3-D Euclidean distance between bin
coordinates** — the physical proximity a hazard cares about, not the walk a picker takes. Bins on opposite
sides of a rack are ~1 m apart in space and tens of metres apart by path, so an aisle-path radius would permit
exactly the adjacency the rule exists to prevent. `R` is configuration (`separation_radius_m`, default 10 m,
with sensitivity reported over {2, 5, 10, 20}).

**Hazard taxonomy and what each rule keys on.** Six hazard classes: `NONE`, `UNKNOWN`, `flammable`,
`corrosive`, `toxic`, `compressed_gas`. Two mechanisms use them and they are not interchangeable:

- `HZ-01` checks a bin's **hazard-class allow-list** (zone-level), which is how "hazardous isolated from
  standard inventory" is enforced.
- `CAT-01` checks the **category-pair matrix**, which is how "separation matrix" is enforced. Categories
  aggregate hazard classes, so a flammable SKU and an oxidiser can be in different categories and still be a
  forbidden pair. Heat sources are **not** modelled — the §8.2 example is illustrative, not a rule.
- `bulky` is a **size class**, not a handling type: it is covered by `SP-01`/`VD-01` (does it fit, does the
  volume fit) and by `ER-01` only when the SKU is also `heavy`. The PS's "heavy, bulky items on upper tiers"
  therefore maps to two rules, not one.

**Structural scopes are cumulative.** The PS names "structural weight overload on rack beams" as the failure,
so the beam check gates *in addition to* the level and rack aggregates: a layout can pass `SL-01` on average
while overloading one beam. Four scopes, four independently supplied limits (§5.2), four checks.

### 8.2 Four verdicts, not one boolean

| Axis | Rules | Verdict | Why separate |
|---|---|---|---|
| Safety | `HZ`, `HD`, `ER`, `CAT`, `CP`, **and the three load checks `LD`, `SL-01`, `SL-02`, `RK`** | `safety_compliant` | R3.3 demands a zero-tolerance safety claim, and the PS lists **beam and rack overload** as a safety risk alongside hazard proximity. A layout with an overloaded beam is not safe, so the structural *load* checks gate the safety verdict as well as the structural one |
| Policy | `AS` | `bin_policy_ok` | one SKU per bin is our modelling choice, not a PS rule; it must not fail a safety claim |
| Structural | `SP`, `VD`, `LD`, `SL-01`, `SL-02`, `RK` | `structurally_feasible` | capacity and load at four scopes; the load rules appear here **and** in safety, deliberately — a rule can bear on two claims |
| Integrity | `REF`, `QTY`, `COMP`, `INV`, `DU` | `data_complete` | conservation failure means the answer is about different stock |

`is_feasible` = all four. A safety-clean layout can under-store 4,000 units; a fully conserved layout can put
a flammable SKU beside a heat source. One boolean cannot say both.

### 8.3 One engine

Baseline, every candidate, the final answer and the dashboard audit call the same `validate()`. There is no
"optimizer-checks" variant, so a gain can never be manufactured by relaxing a rule between stages.

---

## 9. Optimizer

### 9.1 Symbols

| Symbol | Meaning |
|---|---|
| `T`, `Φ`, `Γ`, `Ψ` | travel, affinity, ergonomics, utilisation terms |
| `d(s)` | demand weight of SKU `s` = distinct orders containing it |
| `N_S`, `N_B`, `N_R`, `N_P`, `N_I`, `N_E`, `N_V`, `N_K` | SKUs, bins, records, affinity pairs, iterations, edges, vertices, batches |

### 9.2 Objective

```
minimise  α·(T/T₀) + β·(Φ/Φ₀) + γ·(Γ/Γ₀) + δ·(Ψ/Ψ₀) + ε·(Ψ_R/Ψ_R₀)     all normalisers > 0
```

Normalisation fixes *scale*, not *range*: a term that can move 2% now weighs the same per unit as one that can
move 60%. The weights remain exchange rates whose meaning is established by the sweep in §11.6.

| Term | Definition | Metric it moves |
|---|---|---|
| `T` travel | `Σ over order lines ℓ of dist(depot → bin serving ℓ)`, the bin being the nearest holding **at least that line's quantity** — the same rule the simulator applies | `demand_weighted_depot_distance` + route travel |
| `Φ` affinity | `Σ_pairs co_count · travel_dist(bin_a, bin_b) / L`, one threshold set (§7) | affinity co-order travel distance |
| `Γ` ergonomics | `Σ_s d(s) · units(s) outside the golden band` | golden-zone demand share, computed by the same function |
| `Ψ` utilisation | `Σ` over **occupied** bins of `(1 − fill)` | active-bin fill |
| `Ψ_R` replenishment | `Σ_s Σ_b∈bins(s) trips(s,b) · 2 · dist(depot → b)` (§11.4) | replenishment travel |

**`d(s)` is a visit weight**, not units. Where a metric weights by `d(s) × units`, it says so and is not
called `d(s)`.

**Alignment rule.** Every term has a registry metric; every published metric traces to a term or a hard
invariant. Per-term contributions for baseline and optimized are published, so the weights can be audited
rather than asserted.

### 9.3 Search

1. **Distance oracle** built once (§7 S5).
2. **Greedy starter.** SKUs in velocity order, each placed in the nearest feasible bin(s) with residual
   capacity tracked for bin, beam, level and rack. Best-fit on residual volume breaks distance ties, so
   consolidation is pursued rather than accidental.
3. **Phase A — repair.** If the starter is infeasible (under-storage is the realistic failure), place the
   short SKU in any feasible free bin; if none exists, evict a lower-priority SKU and re-place it, chaining
   with a cycle guard and depth cap. The objective is not evaluated here; infeasible states are visited by
   design.
4. **Phase B — annealing over feasible states only.** Moves: swap two records' bins; move one record to
   another feasible bin; **merge** two records of the same SKU into one bin; **split** a record across two
   bins. The last two change bins-occupied, which the first two cannot.
5. **Selection.** `argmin` over the feasible candidates {refined, starter, baseline}, ties to refined. If none
   is feasible, write `INFEASIBLE` with the violation list and **refuse to evaluate** — an infeasibility
   report is not a result.

### 9.4 Complexity

| Phase | Time | Space |
|---|---|---|
| Feasible-bin pre-filter | O(N_S·N_B) once, cached | O(N_S·N_B) |
| Greedy + repair | O(N_S·N_B log N_B) | O(N_R) |
| Distance oracle | O(N_B·(N_E log N_V)) | O(N_B²) dense |
| Validation | O(N_R + N_B) + `CAT-01` | O(N_R) |
| `CAT-01` per candidate | O(N_R²) unindexed → O(N_R·k) with a 3-D grid | O(N_R·k) |
| Objective | O(N_R + N_P) | O(N_R + N_P) |
| Annealing | O(N_I·(N_R + N_B + N_P)) | O(N_R) per candidate |

Validation and scoring are incrementally updated (only the two touched bins and their beam/level/rack
aggregates); without that, a longer schedule is unaffordable and `CAT-01` makes it worse. The dense oracle
caps `N_B` at 5,000; above that the run **fails fast** with a named error rather than swapping.

### 9.5 What the search can claim

Greedy is strong on `T` because `T` is near-separable. Annealing's contribution must be *measured*: a
rejection-cause breakdown (infeasible / worse-and-rejected / equal) precedes any claim that the search
contributes. A relaxation bound on `T` is published alongside the greedy value, giving an optimality gap for
the travel term only — the bound does not certify `Φ`, `Γ` or `Ψ`.

---

## 10. Geometry

**Travel** is Dijkstra over `location_graph.csv`. `locations.distance_to_dispatch_m` is a denormalised cache
of `dijkstra(depot → location)`, recomputed at load and asserted equal to the graph within 0.5 m or 1%.

**Separation** is 3-D Euclidean between bin coordinates, used only by `CAT-01`. They are separate functions
(`travel_distance`, `separation_distance`); neither may be substituted for the other, because one answers
"how far must someone walk" and the other "how close are these physically".

Routing is nearest-neighbour with a return-to-depot leg, applied identically to both layouts. Cycle time =
travel (`d / 1.3 m/s`) + pick + setup. The simulator supports two pick-time bases: **`order_line`** (default;
one charge per order line, preserving Phase 2/3 comparability) and **`stop`** (one charge per distinct bin
visited by the batch, the §10 target). Phase 5 measured both on the frozen layouts: travel is identical,
while cycle time and throughput move because stops differ from lines (D37). Both nearest-neighbour and
S-shape are implemented (`src/routing/heuristics.py`); Phase 2/3 reported nearest-neighbour, and Phase 4
evaluates both in a layout × policy 2×2. S-shape is a documented node-order serpentine simplification, not a
full aisle-grid S-shape.

### 10.1 Assumptions

| ID | Assumption | Cancels? |
|---|---|---|
| A-1 | Pick time per event, independent of quantity; the event is an order line (default) or a distinct stop (sensitivity) | Yes |
| A-2 | A picker visits every bin holding a SKU **until the pick-rule change lands**; target is quantity-aware nearest bin | **No** — layout-dependent, measured by the 2×2 (§11.5) |
| A-3 | Shortest-path travel, constant speed, no congestion | Yes |
| A-4 | Fixed batch size 5, sorted composition | Yes — held constant so it cannot explain the delta |
| A-5 | Bounding-box volume, no 3-D packing | Yes |
| A-6 | Demand stationary within a scenario | Yes for single-scenario claims; regime shifts are §11.5's job |
| A-7 | **Stock is not depleted during the picked workload** (20,000 pick lines vs 6,375 units on hand) | Yes between layouts, but it suppresses replenishment effects — hence the separate replenishment metric (§11.4) |

---

## 11. Evaluation

### 11.1 Contract

Both layouts share the order workload, batches, routing, speeds, timings, distance oracle and inventory
totals. The contract is asserted in code and restated in every artifact. Identical conditions make the two
layouts comparable; they do **not** make the number out-of-sample — that is §11.5.

### 11.2 Registry

| Metric | Unit | Class | Authoritative? |
|---|---|---|---|
| total travel distance | m | movable | **yes — primary claim** |
| avg distance per order | m | movable | yes |
| `demand_weighted_depot_distance` | m·lines | movable | **yes** — the quantity the optimizer minimises |
| affinity co-order travel distance | m | movable | yes |
| golden-zone demand share | % | movable | yes |
| bins occupied (= assignment records under `AS-01`) | count | movable | yes |
| active-bin fill | % | movable | **yes** — depends on *which* bins are occupied, not only how many, because bin classes differ in volume |
| whole-warehouse cube utilisation | % | **immovable** | no — numerator fixed by inventory, denominator is the whole warehouse |
| charged pick stops | count | diagnostic | no — an input to travel |
| multi-bin SKUs | count | diagnostic | no |
| total pick-cycle time | s | **layout-dependent** | yes — pick time is charged per line (default) or per stop (sensitivity); stop counts differ by layout |
| throughput | orders/h | **layout-dependent** | yes — `orders / cycle` |
| replenishment travel | m | movable | yes |
| violations / verdicts | count, bool | status | yes |

**Cycle time carries its own information under either cost model.** Under the **line** basis both layouts pick
the same 5,997 lines, so the identity "cycle Δ = travel Δ ÷ 1.3" holds and cycle time is a rescaled distance.
Under the **stop** basis pick time is layout-dependent: Phase 5 measured 7,712 stops for the baseline and
5,963 for the optimized layout. The stop model therefore strengthens the cycle/throughput result (baseline
pays more stops; the optimized layout pays fewer) while leaving travel unchanged. The line basis remains the
default for Phase 2/3/4 comparability; the stop basis is a published sensitivity, not a silent redefinition.

**Immovable metrics are labelled.** Cube utilisation cannot move when inventory is fixed; publishing it alone
would look like a non-result. That is why `bins occupied` and replenishment travel sit beside it.

**Every claim carries numerator and denominator**, and every ratio is stored as
`(numerator, denominator, value)` so segment selections aggregate rather than average.

### 11.3 Segment rows

`optimization_metrics.csv` is keyed `(run_id, metric, zone_id, abc_class, layout)` with
`numerator, denominator, value`. A tour is decomposed into legs; each leg is charged to every SKU picked at
its destination stop, split by that stop's line quantity. Zone comes from the bin, class from the SKU. The
parts sum to the tour, so a filtered view is a lookup rather than a re-computation — which is what keeps I-10
true for a read-only dashboard. `abc_class` is the fit-time class the layout was built on;
`abc_class_holdout` carries the recomputed class, so drift is visible rather than conflated.

### 11.4 Replenishment (R2.5)

The PS asks how replenishment interacts with the layout, not for a full replenishment model. The design
answers with a measurable proxy: the restock trips implied by each SKU's assigned bins, and the depot→bin
travel they require under the same routing graph.

```
replenishment_travel = Σ_s Σ_b∈bins(s) trips(s,b) · 2 · travel_dist(depot → b)
trips(s,b)           = ceil(on_hand(s,b) / restock_lot(s))
```

Trips are counted **per assigned bin**, not per SKU, because fragmentation is the effect the metric exists to
expose: a SKU split across four bins generates four restock destinations, and that cost rises exactly when a
layout scatters stock to win pick distance. `restock_lot` is configuration (default: 14 days of demand).
`bins(s)` is the set of bins holding SKU `s` — the same set the simulator visits.

The metric is reported for both layouts and enters the trade-off discussion: a layout that pushes fast movers
into many small remote bins can win on pick travel and lose on restock travel. That trade-off **is** the R2.5
deliverable; a full replenishment simulation is explicitly out of scope. Because the alignment rule (§9.2)
requires every published metric to trace to a term or an invariant, replenishment enters the objective as a
fifth term `Ψ_R` with weight `ε` (`Objective.epsilon`, default **0.0**, which reproduces the Phase 2 objective
exactly). The Phase 3 result is a measured, near-neutral trade-off: `ε = 0.5` moves 0.025 % of restock travel
against 0.107 % of held-out pick travel, so the default stays at 0 until a phase chooses otherwise. Zero-demand
SKUs make zero trips — inventing a trip for stocked-but-undemanded stock biases the proxy.

### 11.5 Comparability, generalization, fragmentation

| Experiment | Construction | Claim |
|---|---|---|
| **In-sample** | fit and evaluate on scenario A | descriptive only |
| **Held-out window** | `split-dataset --fraction f`; fit `A_FIT`, evaluate `A_HOLDOUT` | generalization within a demand process |
| **Regime shift** | fit on A, evaluate on B or C | robustness to a different demand regime (A head-heavy, B flat, C clustered — different generators, not resamples) |

**Fragmentation vs placement (2×2).** Two designs, two questions. **Primary:** factor A is placement
(`baseline_repaired` vs `optimized_fit`), factor B is a real fragmentation **policy** (`as_is` vs `min_bins`,
which re-packs each SKU into as few of its own bins as capacity allows and is distance-blind). Under
quantity-aware picking the placement effect is −245,161 m (−48.88 %) and the fragmentation effect is
+2,893 m (+0.58 %): the gain is placement, not consolidation. The interaction is the
difference-in-differences of the four cell means. **Secondary (§11.5 sensitivity):** the same two
layouts under both pick rules (all-bins, quantity-aware). The layout effect is −331,758 m, the rule effect
+103,481 m, and the interaction −179,052 m; this measures how much a raw comparison depends on charging every
bin, and is not a fragmentation treatment. The all-bins outcome of the primary four cells is published beside
the quantity-aware one (−12.59 % fragmentation effect), which is where a bin-count effect legitimately appears.

**Layout × picking policy (Phase 4).** Two policies are implemented: nearest-neighbour and the node-order
S-shape. On the frozen A holdout (1,625 orders / 5,997 lines) the layout effect is −273,686 m (−53.86 %),
the policy effect is +462 m (+0.09 %, S-shape slightly worse), and the interaction is +562 m: the optimized
layout's advantage is 562 m smaller under S-shape but remains −53.78 % against its own baseline. Cycle time
falls 47.62 % and throughput rises 90.85 % by layout; the policy changes them by 0.08 %. The conclusion is
therefore about placement, not routing. B/C regime shifts preserve the gain (−33.37 % / −42.19 %); the
optimized layout has almost no structural headroom (bin weight 100 %, volume 99.93 %, level 98.06 %, beam
98.76 %).

**Optimizer neighbourhood (Phase 7).** The default relocation operator samples every feasible bin for a SKU,
including bins already occupied by another SKU. On A_FIT that yields 270/600 feasible proposals (45 %) and
only 2 improving proposals, best −0.0704 objective units; the final incumbent equals the greedy starter.
An opt-in `neighborhood="targeted"` proposal restricts relocation to empty bins and biases the draw to the
nearest 20: 426/600 feasible (71 %), 4 improving, best −0.8128, but the final layout and objective are
unchanged. The default remains `legacy`; targeted is a measured efficiency experiment, not a claimed
operational improvement. The canonical search is locally saturated, not broken.

### 11.6 Weight sweep

α/β/γ/δ are swept over a documented grid; each run publishes its per-term contributions and metric table. The
sweep turns the weights from arbitrary multipliers into a stated trade-off and is the evidence
`PROJECT.md D-3 (documentation)` asks for. Normalisation alone does not achieve this — it fixes scale, not
range.

### 11.7 Current measurements (reproduced in Phase 6)

**Source:** `outputs/baseline_assignments.csv` and `outputs/optimized/optimized_assignments.csv` (one
artifact set), `pick_route_stops_*.csv`, `evaluation_summary.json`. Phase 6's clean-clone `run-all`
regenerated this chain end to end; the figures below are reproduced from this checkout, not copied from
another machine (D13 closed).

| Metric | Baseline | Optimized | Change |
|---|---|---|---|
| total travel distance | 1,691,478.6 m | 750,119.5 m | −55.65% |
| charged pick stops | 25,767 | 20,388 | −5,379 (−20.9%) |
| assignment records | 1,425 | 1,288 | −137 |
| multi-bin SKUs | 208 | 88 | −120 |
| whole-warehouse cube utilisation | 15.42% | 15.42% | 0.00 pp (immovable) |
| hard violations | 0 | 0 | only for the rules implemented today (D5, D34) |

**With `CAT-01` live, the committed baseline is no longer feasible.** Re-validating it with the new rule
gives 1,071 violations at `R = 10 m`, 169 at `R = 5 m`, 0 at `R = 2 m` (3,594 pair checks). The previous
"0 violations" was true only because the rule did not exist. Consequences: the layout must be re-solved with
`CAT-01` active, and `R` is now a real design parameter with a measured sensitivity rather than a default.

The −20.9% stop reduction is **not** evidence of a −55.65% travel gain: pricing removed stops at the average
14.85 m/stop is biased by tour concavity and circular by construction. §11.5's 2×2 is what separates the
fragmentation effect from the placement effect (D22).

### 11.8 EDA deliverables (PROJECT §5)

EDA is a pipeline stage (S3) and a documentation obligation, not a chart dump. Three analyses, each shipped as
a **finding with a consequence for the design**:

| Analysis | Artifact | Finding it must state |
|---|---|---|
| **Demand velocity (Pareto/ABC)** | `abc_classification.csv`, cumulative-share curve | what share of orders the A class carries, and therefore how much travel the top decile can influence |
| **Affinity (market basket)** | `affinity_matrix.csv`, `affinity_clusters.csv` | how many pairs clear the threshold, cluster sizes, and whether the chosen threshold set (§7) yields clusters worth placing adjacently — if it yields none, `β·Φ` is inert and must be reported as such |
| **Volumetric density vs capacity classes** | `volume_profiles.csv`, distribution plot | which SKU classes cannot fit which bin classes, how much capacity is structurally unusable, and whether the instance is slack (which determines whether the constraint tests mean anything — D24) |

Each finding names its consequence for slotting or for the evaluation design. A finding with no consequence
is an observation, and the report must say so rather than dress it as insight.

---

## 12. Dashboard

Six tabs: **Overview** (baseline vs optimized, verdicts, solver status, metric definitions), **Warehouse
Layout** (plan + rack elevation by ABC class), **Pick Routes** (batch browser, ordered stops, leg distances),
**Ergonomics** (golden-band share, Class-A placement), **Exports** (CSV/JSON), **Inventory Mgmt** (session
"what-if", validated through the same engine or labelled unvalidated).

**Global controls** sit above the tabs: **run**, **zone**, **ABC class**. All three select pre-computed rows
(§11.3); the view computes no metric, which is what keeps it read-only and keeps I-10 true. A missing artifact
renders "unavailable" with the command that would produce it — never a zero. Demand/ABC, Affinity, Constraints
and Optimizer controls live inside Overview and the Layout tab; the earlier nine-tab claim is withdrawn.

---

## 13. Configuration and CLI

```
app/main.py build-dataset  --config configs/dataset.json [--out dataset]
app/main.py split-dataset  --processed <tree> --scenario A --fraction 0.7 [--out outputs/splits/A70]
app/main.py run-analysis   --processed <tree> --scenario A [--output outputs/analysis]
app/main.py validate       --processed <tree> [--output outputs]
app/main.py optimize       --processed <tree> --fit-scenario A [--affinity-scenario A]
app/main.py simulate       --processed <tree> (--eval-scenario A | <split view>) [--optimized <csv>]
app/main.py run-all        --processed <tree> (--eval-scenario B | <split view>)
```

`--fit-scenario` and `--eval-scenario` have no defaults: defaulting both to A would reproduce the in-sample
defect. `split-dataset` is the **only** entry point that splits — no other command takes a fraction, because
splitting inside `optimize` would let it read analytics computed over the full history. `simulate` takes
either `--eval-scenario` or a split tree, never both.

Physical limits, the golden band, `separation_radius_m`, speeds and timings are configuration; a constant in a
module is a second source of truth.

**Runtime:** Python ≥ 3.11; pandas, numpy, plotly, streamlit (the 3-D grid index for `CAT-01` is implemented in
numpy — no extra dependency). Filesystem only: no database, no service, no network at run time, so results
reproduce offline.

---

## 14. Cross-cutting

| Concern | Rule |
|---|---|
| Determinism | sorted iteration, seeded RNG, no hash-order dependence; summaries carry runtime and paths by design, so decision determinism is the claim, not byte-identity |
| Failure honesty | infeasible ⇒ `INFEASIBLE` + refusal to evaluate; missing artifact ⇒ "unavailable" |
| Provenance | every row resolves to a manifest entry with licence and retrieval date |
| Schema drift | one registry read by generator, dictionary and validator |
| Tests | one suite per stage plus integration, **and a seeded-bad-layout test**: a deliberately invalid layout (oversized SKU, overloaded beam, hazard in a general zone) must be rejected with the offending rule named. `PROJECT.md` Definition of Done #2 requires the validator to demonstrably fail, not merely to pass good layouts |

---

## 15. Conformance — PS requirement → mechanism → status

**Status vocabulary — three different claims, deliberately separated:**

| Status | Means | Evidence required |
|---|---|---|
| `verified` | executed on **this checkout**, with output from this session | a command and its output |
| `implemented` | source exists and a committed artifact shows it ran somewhere | code path + artifact, **not** reproduced here |
| `partial` | mechanism partly exists; a named gap remains | gap row in §16 |
| `specified` | designed here, no code | §16 row |

**Headline count: 8 implemented · 5 partial · 0 specified · 7 verified.** R1.3 and R1.4 moved to *verified* on the canonical benchmark in Phase 2; the eight implemented rows remain source-plus-artifact claims. Phase 6 executed the whole chain end-to-end in a clean clone (`run-all`, 10/10 stages, 294 tests, 27/27 verifier checks), so the checkout is no longer an unexecuted source snapshot; the status labels below remain conservative classifications of requirement coverage, not of whether the code ran.

| PS requirement | Mechanism | Section | Status |
|---|---|---|---|
| R1.1 volumetric & spatial bounds | `SP-01`, `VD-01` per bin | §8.1 | implemented |
| R1.2 structural load bin/shelf/rack | four scopes × four independent limits | §5.2, §8.1 | implemented — 2,304 bins carry `beam_`/`level_`/`rack_max_weight_kg`; SL-02/SL-01/RK-01 execute (max load 55.6% / 34.7% / 29.2%) |
| R1.3 hazard & category separation | `HZ-01`, `HD-01` incl. `fragile`, `ER-01`, `CAT-01` | §8.1 | verified — `CAT-01` gates in the greedy (3-D grid) and the validator; optimized layout 0 violations at 10 m |
| R1.4 hard vs soft separation | one engine, four verdicts, no tradeable rule | §8.2–8.3 | verified — `execution_status` / `feasibility_status` / `completeness` / `objective` are separate fields; gate blocks infeasible layouts |
| R2.1 ABC velocity | cumulative-share classification 80/95 | §7 | implemented |
| R2.2 proximity to I/O | `T`, per line, published as `demand_weighted_depot_distance` | §9.2, §11.2 | verified — Phase 3 computed it per order line on a held-out workload |
| R2.3 affinity | one threshold set, graph distance, co-order metric | §7, §9.2 | **partial** — threshold sets disagree (D18) |
| R2.4 golden-zone ergonomics | `Γ` and the share computed by one function | §9.2 | **partial** — two weightings (D33) |
| R2.5 replenishment | replenishment travel metric + stated trade-off | §11.4 | **partial** — metric implemented and measured (−33.66 %); the objective term is not wired |
| R2.6 inventory conservation | `INV-01/02/03`, `COMP-01` | §8.1 | implemented |
| R3.1 baseline artifact | `storage_assignments_baseline.csv` | §5.1 | implemented |
| R3.2 identical conditions | one workload, one graph, one routing | §11.1 | implemented |
| R3.3 required metrics | registry with classes and ratio components | §11.2–11.3 | verified — 2×2 decomposition measured; 54.0 % of the raw gain is fragmentation |
| R3.4 honesty of claims | class column, numerator/denominator, derived labels | §11.2 | **partial** — classes exist (`METRIC_SPECS`); numerator/denominator and derived labels are absent from the artifact |
| `PROJECT.md` D1–D3 data vectors | generator + schema registry + spines | §5.1, §5.5 | implemented |
| provenance: source, licence, date | `phase3/provenance.json` with per-table hashes | §5.3 | verified — every artifact traceable; licence marked not-applicable for synthetic data |
| EDA mandate | ABC, affinity, volume with finding + consequence | §7, §11.6 | verified — four findings with consequences and limitations |
| `PROJECT.md` D-1 prototype | `run-all` end-to-end | §7 | implemented — code path exists; **not executed here** |
| `PROJECT.md` D-2 dashboard | data contract for Phase 3 metrics; view wiring deferred | §12 | **partial** — contract delivered (`app/phase3_contract.py`); dashboard not wired |
| `PROJECT.md` D-3 documentation | architecture + EDA findings + trade-off sweep | §11.6 | verified — four-vector sweep run, findings written, trade-offs stated |

**Reading the table.** All twenty requirements have a mechanism in this document. Two are verified end-to-end,
eight are implemented, six are partial, four are specified. Phase 2 ran the full pipeline locally and the
independent verifier reproduced R1.3 and R1.4; the rest have not been exercised end-to-end on this checkout.
That is the sense in which the architecture meets the PS: nothing in the brief is unanswered *by the
design*, and the residue is code with acceptance criteria in §16.

---

## 16. Implementation backlog

Design is settled; these are the code changes that make §15 read `implemented` everywhere, and `verified`
once they have been run here. 48 registered items.

### 16.1 P0 — blocks every claim

None open. D13 (clean-checkout reproduction) closed in Phase 6; see §16.4.

### 16.2 P1 — makes the verdicts and metrics honest

| ID | Gap | Change |
|---|---|---|
| D1 | golden band defined at seven sites | one config value threaded to every consumer |
| D2 | two travel distances | graph canonical; attribute recomputed and asserted |
| D11 | `n_pick_lines` hard-codes 8 s | read from config |
| D12 | analysis hard-codes the dataset path | thread `--processed` everywhere |
| D14 | dense oracle unbounded | fail fast above 5,000 bins |
| D18 | two affinity threshold sets | one config-driven set for clustering, penalty and metric |
| D23 | derived metrics presented as wins | enforce the class column in report generation |
| D24 | local slack unmeasured | per-rule slack report; stress the capacity that binds |
| D28 | no scenario/zone/class controls | global filters over segment rows |
| D30 | infeasible starter unrecoverable | Phase A repair with eviction chains |
| D31 | search cannot change occupancy | merge/split moves + best-fit greedy |
| D33 | `Γ` and share use different weights | one function for both |
| D8 | cube utilisation is the only fill metric | publish occupancy count and active-bin fill (the movable fill metric R3.4 needs) |
| D39 | "near-optimal" unbounded | publish relaxation bound and gap |
| D42 | annealing diagnosis unsupported | rejection-cause instrumentation first |
| D44 | dashboard computes metrics | segment rows + run registry |

### 16.3 P2 — hygiene and fidelity

| ID | Gap | Change |
|---|---|---|
| D3 | 3×3 fixture builder: zero distances, permissive zones | delete the branch or generate real geometry |
| D4 | fixture omits `UNKNOWN` | include it in one zone, or forbid at generation |
| D6 | slotting config keys unused | implement or delete |
| D9 | `Ψ` over all bins is distribution-invariant | restrict to occupied bins |
| D10 | affinity uses Manhattan, weight unbounded | graph distance; normalise the weight |
| D15 | README claims nine tabs | six |
| D16 | ergonomic metrics diverge | explain the composition effect or fix the weighting (D33) |
| D17 | config misstates location count | derive from the zone layout |
| D19 | neighbourhood is feasibility-blind | capacity-aware sampling, justified by D42 |
| D20 | dashboard allocations unvalidated | validate, or label the tab a sandbox |
| D32 | mixed scenario contract | one scenario end-to-end per run |
| D41 | stock never depleted | document as A-7; optional depletion model |
| D43 | no scenario stresses all terms | term-coverage matrix |
| D45 | oracle built too late | move to the S5 precondition |

### 16.4 Closed

| ID | Item | Closed by |
|---|---|---|
| D26 | a non-blocking severity class whose membership was empty | document fix: severity removed; four verdicts (§8.2) |
| D7 | one boolean verdict for four different guarantees | closed in Phase 2: `execution_status`, `feasibility_status`, `assignment_completeness`, `objective` are separate fields; the gate consumes `feasibility_status` only |
| D38 | no gate before evaluation — infeasible layouts were scored | closed in Phase 2: `evaluation_status: BLOCKED_INFEASIBLE_LAYOUT`, `comparison_valid: false`, `run-all` exits 1; verified live before the baseline repair |
| D40 | `CAT-01` unindexed, radius unset, greedy blind to it | closed in Phase 2: `src/optimization/separation.py` grid (cell = R), `separation_radius_m` in `configs/benchmark.json`, greedy and repair consult it; 1,293 queries on the canonical run |
| D29 | travel summed per assignment record, not per order line | closed in Phase 3: `src/experiments/travel.py` computes travel per order line under two pick rules; the optimizer's internal accounting is kept separate from the published metric |
| D35 | `T` never published | closed in Phase 3: `demand_weighted_depot_distance` published with numerator (metres) and denominator (lines) plus a per-line audit CSV |
| D22 | fragmentation vs placement unmeasured | closed in Phase 3: primary 2×2 placement × fragmentation **policy** (`as_is` vs `min_bins`) — placement −245,161 m (−48.88 %), fragmentation +2,893 m (+0.58 %); the all-bins outcome (−87,475 m, −12.59 %) shows the bin-count effect is an accounting-rule effect. Pick-rule sensitivity reported separately |
| D46 | split sliced orders only, so analytics leaked holdout demand | closed in Phase 3: every view is a complete tree with `demand_summary` and `sku_affinity` recomputed per view; `run_phase5` takes `fit_scenario`; ten leakage checks pass, including line-union completeness |
| D36 | no weight sweep / trade-off artifact | closed in Phase 3: five weight vectors fitted on `A_FIT`, all feasible; four produce one identical layout, `ε = 0.5` produces a second that trades 0.025 % restock travel for 0.107 % held-out pick travel. Selection uses fit line travel; default retained |
| D48 | provenance manifest absent | closed in Phase 3: `outputs/phase3/provenance.json` records 12 input hashes, config hash + weights, seeds, split manifest, evaluation protocol, origin evidence and 33 output hashes; unknowns are marked, not invented |
| D47 | replenishment unstated | closed in Phase 3: `src/optimization/replenishment.py` implements §11.4 (per-bin trips, zero-demand SKUs excluded), the metric is reported for every cell, and `Objective.epsilon` adds the `ε·Ψ_R` term (default 0.0 reproduces Phase 2). Tests cover the term and the infeasibility guarantee |
| D21 | fitness and evaluation in-sample | closed in Phase 3/4: temporal order-level fit/holdout split with 10 integrity checks; Phase 4 evaluates the frozen layout on the holdout and on regimes B/C without refitting |
| D25 | objective undecomposed | closed in Phase 3/4: `Objective.components` publishes `D/A/E/U/R`, weighted contributions and the total in every optimization summary and Phase 4 cell artifact |
| D27 | determinism untested | closed: `tests/test_determinism.py` plus the byte-identical split rebuild and frozen layout hashes; Phase 4 route sums are deterministic across repeated runs |
| D37 | travel per stop, pick time per line | closed in Phase 5 with a compatibility default: `SimulationConfig.pick_time_basis` supports `order_line` (default; historical series) and `stop` (distinct bins per batch; §10 target). Controlled comparison: travel identical (508,174.8 / 234,208.0 m), baseline stop charging **+13,720 s (+3.10 %)** because 7,712 stops > 5,997 lines, optimized **−272 s (−0.12 %)** because 5,963 stops < 5,997 lines; stop basis strengthens cycle **−49.30 %** and throughput **+97.27 %** vs line **−47.67 %** / **+91.08 %**. Default retained for Phase 2/3/4 comparability |
| D13 | artifacts generated elsewhere; no reproduction entry point | closed in Phase 6: root `run-all` orchestrates base pipeline → Phase 3 → Phase 4 → Phase 5 → verifiers → optimizer audit → capacity audit → full suite → Phase 6 verifier. A fresh Git clone of the source snapshot (`8df87d5`, clean worktree) with a fresh venv and no `outputs/` completed **10/10 stages**, **294 tests** and **27/27** Phase 6 checks in 35 min 50 s; `outputs/phase6/runs/clean-01/` holds the manifest and logs |
| D34 | structural limits had no defined unit; beam/level/rack were not separate fields | four explicit limits emitted by `apply_structural_limits`; validator compares each aggregate to its own field. 8 unit tests; 960 beam / 550 level / 144 rack checks execute on the v1 dataset |
| D5 | category matrix inert — `CAT-01` did not exist | 3-D Euclidean radius with a uniform grid index, `separation_radius_m` configurable. 8 unit tests; 3,594 pair checks run on the baseline — which reveals **1,071 violations at R=10 m** |

**Backlog status:** 30 open (0 P0, 16 P1, 14 P2), 18 closed. Closing the P0 set is required before any
improvement figure is published as reproduced; the P0 set is currently empty (D13 closed in Phase 6), so the
gate is satisfied. Any new P0 reopens the reproduction gate.

---

## 17. Decisions

| ID | Decision | Rejected | Why |
|---|---|---|---|
| ADR-1 | aisle graph is the only **travel** distance; separation is a separate 3-D function | one distance for everything | they answer different questions; a single rule is wrong for one of them |
| ADR-2 | golden band is data, loaded once | per-module constants | seven competing definitions is what constants produce |
| ADR-3 | four verdicts, every rule blocking | one boolean; severity tiers | R3.3 needs a safety claim independent of completeness and policy |
| ADR-4 | category separation by 3-D radius | co-storage; face-adjacency; aisle radius | co-storage explodes the rule set; adjacency misses bays; aisle radius measures walking, not risk |
| ADR-5 | fill reported as occupancy count + active-bin fill + immovable whole-warehouse share | whole-warehouse only | one number cannot show consolidation and reads as failure |
| ADR-6 | greedy + repair + annealing, with a bound on `T` only | MILP/CP-SAT; greedy alone | exactness unaffordable; accountability affordable |
| ADR-7 | batch pipeline + read-only dashboard | service with a database | the PS asks for a prototype and a view, not an operations platform |
| ADR-8 | spines share one schema, selected by path | per-source schemas | one engine must consume all three or provenance is untestable |
| ADR-9 | four structural scopes, four independent limits, all gating | aggregate-only; beam-only | R1.2 is a floor; the PS names beam overload as the failure |
| ADR-10 | split is a dataset tree with rewritten scenario ids | flag on the evaluator; orders-only slice | analytics keys on scenario; anything less leaks the holdout |

---

## 18. Open questions

| ID | Question | Why it remains open |
|---|---|---|
| Q1 | exact replenishment policy (`restock_lot`, trip batching) | §11.4 fixes a measurable proxy and a term; a full policy is out of scope and must be stated as such in the report |
| Q2 | whether to fund a depletion model (A-7) | affects pick realism; not required by the PS |
| Q3 | scale beyond 5,000 bins | requires the sparse oracle; the ceiling is enforced meanwhile |
| Q4 | golden-band levels for this warehouse | fixed in `configs/dataset.json` as `[1,2]`, but not justified against picker anthropometry — needs a one-line rationale in the report, not a design decision |
| Q5 | target runtime | the envelope is measured (§13), not promised; a SLA would be a guess |

**Constants that must be pinned before coding can finish** — specified as configuration, not yet given values
in this document: α/β/γ/δ/ε, the normalisers `T₀…Ψ_R₀`, `L` in `Φ`, `restock_lot`, `separation_radius_m`, pick
speed, pick and setup times, batch size. They live in `configs/*.json`; the document specifies what they mean
and where they enter, not what they should be — the sweep (§11.6) is what picks them.

Two of the seven `PROJECT.md` §9 items are decided here: the hazard taxonomy (§8.1, six classes) and shelf
semantics (§5.2: level 0 is the floor, heavy capped at level ≤ 2). Scenario count is fixed at three (§11.5).
The remaining items — replenishment policy, scale target, and the exact trade-off weights — are the questions
above.

---

## 19. History

| Pass | What changed |
|---|---|
| 1–4 | draft, then contradiction hunt: gaps registered and corrected |
| 5 | checks moved into `tools/check_architecture.py`; symbol table; charged-stop accounting |
| 6–7 | claims narrowed to what the artifacts support; safety verdict and separation geometry corrected |
| 8 | distance doctrine scoped to travel; ID namespaces; five design gaps registered |
| 9 | checked against `PROJECT.md`: structural keys, replenishment, provenance, dashboard filters, split leak |
| 10 | beam check restored to blocking; structural units; single split entry point; per-segment attribution |
| **11** | **restructured as a design-complete document**: every PS requirement now resolves to a mechanism (§15); the deviation register became an implementation backlog (§16); replenishment metric, ratio components, weight sweep and the 2×2 experiment are specified rather than deferred |

---

*End of document. §15 is the conformance claim; §16 is what remains to be built. D13, D22, D29 and D37 are
closed: Phase 6 reproduced §11.7 end-to-end in a clean clone, and Phase 3/5 measured the
placement/fragmentation decomposition, order-line travel and the pick-time basis. Re-run `run-all` after any
change that touches the data, constraints, objective or simulation constants.*
