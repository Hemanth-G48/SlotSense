# Benchmark Dataset Schema — `olist` spine

- Dataset: `dataset-2` (2.0.0), spine `olist`
- Seed: `7`
- SKUs: 1200
- Locations: 2816
- Orders: 37042; order lines: 37642
- Demand scenarios: 3

## Tables

| table | rows |
|---|---|
| warehouses | 1 |
| categories | 10 |
| products | 1200 |
| locations | 2816 |
| inventory | 1208 |
| compatibility_rules | 55 |
| orders | 37042 |
| order_items | 37642 |
| storage_assignments_baseline | 1208 |
| location_graph | 6446 |
| demand_summary | 3600 |
| sku_affinity | 88 |

Field definitions, units and primary keys: `metadata/data_dictionary.csv`.
The schema is byte-compatible with `dataset/` (same 12 tables, same column order).

## Provenance

| source | license | file | records | status |
|---|---|---|---|---|
| Olist orders dataset | CC BY-NC-SA 4.0 | raw/olist/olist_orders_dataset.csv | 99441 | sourced |
| Olist order items | CC BY-NC-SA 4.0 | raw/olist/olist_order_items_dataset.csv | 112650 | sourced |
| Olist product master | CC BY-NC-SA 4.0 | raw/olist/olist_products_dataset.csv | 32951 | sourced |
| Generated warehouse grid | Project-internal | processed/locations.csv | 2816 | generated |

## Spine notes

- Order history, SKU dimensions and weights are real Olist records, used unmodified.
- The warehouse grid, capacities and aisle graph are generated (no real layout exists).
- Hazard class is inferred from product-category keywords (Olist has no hazmat field).
- Handling type follows the canonical category rule, with a >20 kg heavy override.
- Scenarios A/B/C are three disjoint sequential windows of the same real history.
- Product rows carry physical_confidence=medium: dimensions are seller-declared.
- 6 product rows were excluded for missing or out-of-envelope dimensions (no value was imputed or clipped).

## Units

Dimensions cm, weight kg, volume cm3, coordinates/distance m, timestamps UTC.
