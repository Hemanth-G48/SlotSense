# Benchmark Dataset Schema — `instacart` spine

- Dataset: `dataset-2` (2.0.0), spine `instacart`
- Seed: `7`
- SKUs: 1200
- Locations: 2816
- Orders: 93248; order lines: 575749
- Demand scenarios: 3

## Tables

| table | rows |
|---|---|
| warehouses | 1 |
| categories | 10 |
| products | 1200 |
| locations | 2816 |
| inventory | 1509 |
| compatibility_rules | 55 |
| orders | 93248 |
| order_items | 575749 |
| storage_assignments_baseline | 1509 |
| location_graph | 6446 |
| demand_summary | 3600 |
| sku_affinity | 407979 |

Field definitions, units and primary keys: `metadata/data_dictionary.csv`.
The schema is byte-compatible with `dataset/` (same 12 tables, same column order).

## Provenance

| source | license | file | records | status |
|---|---|---|---|---|
| Instacart Market Basket Analysis — prior orders | CC0 1.0 | raw/instacart/order_products__prior.csv | 1007672 | sourced |
| Instacart orders | CC0 1.0 | raw/instacart/orders.csv | 3421083 | sourced |
| Instacart product catalogue | CC0 1.0 | raw/instacart/products.csv | 49688 | sourced |
| Class-rule dimension synthesis | Project-internal | processed/products.csv | 1200 | generated |

## Spine notes

- Baskets, SKU names, aisles and departments are real Instacart records.
- Instacart publishes no dimensions or weights; they are synthesised by the class rule and flagged physical_data_source=synthetic_class_rule, physical_confidence=low.
- Timestamps are derived from order_number and hour of day on a documented 2017 anchor; the source has no absolute clock.
- Scenarios A/B/C are three disjoint sequential slices of the sampled order history.
- Hazard class is inferred from product-name keywords (no hazmat field exists).

## Units

Dimensions cm, weight kg, volume cm3, coordinates/distance m, timestamps UTC.
