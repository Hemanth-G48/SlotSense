# Dataset Validation Report

- Status: **PASS**
- Hard errors: **0**
- Warnings: **0**

## Row counts

| table | rows |
|---|---|
| categories | 10 |
| compatibility_rules | 55 |
| demand_summary | 3000 |
| inventory | 1026 |
| location_graph | 28820 |
| locations | 3420 |
| order_items | 66497 |
| orders | 36035 |
| products | 1000 |
| sku_affinity | 15391 |
| storage_assignments_baseline | 1026 |
| warehouses | 1 |

## Capacity

- Locations: 3420 (1026 used, 2394 empty)
- Volume utilization: 0.12%
- Weight utilization: 3.56%
- Occupied volume: 1,152,916 cm3 of 928,218,000 cm3
- Stored weight: 11,342.5 kg of 318,755.0 kg

## Demand scenarios

| scenario | orders | lines |
|---|---|---|
| A | 12012 | 22959 |
| B | 12012 | 22406 |
| C | 12011 | 21132 |

## ABC classification

| scenario | SKUs | A | B | C |
|---|---|---|---|---|
| A | 1000 | 599 | 258 | 143 |
| B | 1000 | 605 | 258 | 137 |
| C | 1000 | 595 | 256 | 149 |

## Checks

| check | severity | count |
|---|---|---|

## Assumptions

- All rows are synthetic or derived; no measured warehouse data is present.
- Volume is the full bounding-box volume; packing clearance is not modelled.
- One SKU per bin; a SKU may occupy several bins.
- Demand scenarios are alternative histories, not additive.
