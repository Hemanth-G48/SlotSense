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
| inventory | 1509 |
| location_graph | 6446 |
| locations | 2816 |
| order_items | 575749 |
| orders | 93248 |
| products | 1200 |
| sku_affinity | 407979 |
| storage_assignments_baseline | 1509 |
| warehouses | 1 |

## Capacity

- Locations: 2816 (1509 used, 1307 empty)
- Volume utilization: 4.05%
- Weight utilization: 10.95%
- Occupied volume: 89,693,411 cm3 of 2,212,352,000 cm3
- Stored weight: 58,215.0 kg of 531,840.0 kg

## Demand scenarios

| scenario | orders | lines |
|---|---|---|
| A | 31083 | 185336 |
| B | 31083 | 189635 |
| C | 31082 | 200778 |

## ABC classification

| scenario | SKUs | A | B | C |
|---|---|---|---|---|
| A | 1200 | 607 | 400 | 193 |
| B | 1200 | 600 | 408 | 192 |
| C | 1200 | 567 | 416 | 217 |

## Checks

| check | severity | count |
|---|---|---|

## Assumptions

- All rows are synthetic or derived; no measured warehouse data is present.
- Volume is the full bounding-box volume; packing clearance is not modelled.
- One SKU per bin; a SKU may occupy several bins.
- Demand scenarios are alternative histories, not additive.
