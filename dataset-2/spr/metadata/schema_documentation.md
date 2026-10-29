# Benchmark Dataset Schema — `spr` spine

- Dataset: `dataset-2` (2.0.0), spine `spr`
- Seed: `7`
- SKUs: 1000
- Locations: 3420
- Orders: 36035; order lines: 66497
- Demand scenarios: 3

## Tables

| table | rows |
|---|---|
| warehouses | 1 |
| categories | 10 |
| products | 1000 |
| locations | 3420 |
| inventory | 1026 |
| compatibility_rules | 55 |
| orders | 36035 |
| order_items | 66497 |
| storage_assignments_baseline | 1026 |
| location_graph | 28820 |
| demand_summary | 3000 |
| sku_affinity | 15391 |

Field definitions, units and primary keys: `metadata/data_dictionary.csv`.
The schema is byte-compatible with `dataset/` (same 12 tables, same column order).

## Provenance

| source | license | file | records | status |
|---|---|---|---|---|
| S.P. Richards item master (skus.txt) | Educational use, Warehouse & Distribution Science (Bartholdi & Hackman) | raw/spr/skus.zip | 27713 | sourced |
| S.P. Richards product dimensions | Educational use, Warehouse & Distribution Science (Bartholdi & Hackman) | raw/spr/SkuDimensions.zip | 44389 | sourced |
| S.P. Richards 2002 pick history | Educational use, Warehouse & Distribution Science (Bartholdi & Hackman) | raw/spr/sales-2002-recovered.txt | 1102882 | sourced_recovered |
| S.P. Richards bin location table | Educational use, Warehouse & Distribution Science (Bartholdi & Hackman) | raw/spr/BinLocationTable.txt | 10506 | sourced |
| Inferred aisle geometry | Project-internal | processed/location_graph.csv | 28820 | inferred |

## Spine notes

- Bin addresses, zones, item dimensions, weights, hazmat codes and pick history are real.
- Aisle coordinates, walking distances and bin capacities are inferred from the address grammar and the bin-location table; no measured layout is public.
- The inferred floor plan places zones side by side and compresses each zone to at most 24 aisle lines, so walking distances stay in the 45-200 m range of a real DC.
- The upstream sales archive is truncated; recovered pick lines are validated field by field.
- Hazmat codes map HA->flammable, HG->corrosive, HN->toxic; unmapped items are NONE.
- 4148 item rows were excluded for missing or implausible physical data.
- 0 selected SKUs were dropped because no inferred bin satisfies their handling, hazard, geometry and weight envelope; they remain listed in metadata/sku_selection.csv.
- Scenarios A/B/C are three disjoint sequential windows of the 2002 pick history.
- The real recorded slot for each SKU is shipped as raw/spr/current_slots.csv, outside the schema, so the engine can also score against the current layout.

## Units

Dimensions cm, weight kg, volume cm3, coordinates/distance m, timestamps UTC.
