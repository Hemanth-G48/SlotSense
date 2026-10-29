# Dataset Validation Report

- Status: **PASS**
- Hard errors: **0**
- Warnings: **0**

## Row counts

| table | rows |
|---|---|
| categories | 10 |
| compatibility_rules | 55 |
| demand_summary | 3600 |
| inventory | 1208 |
| location_graph | 6446 |
| locations | 2816 |
| order_items | 37642 |
| orders | 37042 |
| products | 1200 |
| sku_affinity | 88 |
| storage_assignments_baseline | 1208 |
| warehouses | 1 |

## Capacity

- Locations: 2816 (1208 used, 1608 empty)
- Volume utilization: 2.35%
- Weight utilization: 1.37%
- Occupied volume: 51,956,255 cm3 of 2,212,352,000 cm3
- Stored weight: 7,291.2 kg of 531,840.0 kg

## Demand scenarios

| scenario | orders | lines |
|---|---|---|
| A | 12348 | 12539 |
| B | 12348 | 12573 |
| C | 12346 | 12530 |

## ABC classification

| scenario | SKUs | A | B | C |
|---|---|---|---|---|
| A | 1200 | 384 | 240 | 576 |
| B | 1200 | 438 | 307 | 455 |
| C | 1200 | 398 | 279 | 523 |

## Checks

| check | severity | count |
|---|---|---|

## Assumptions

- All rows are synthetic or derived; no measured warehouse data is present.
- Volume is the full bounding-box volume; packing clearance is not modelled.
- One SKU per bin; a SKU may occupy several bins.
- Demand scenarios are alternative histories, not additive.
