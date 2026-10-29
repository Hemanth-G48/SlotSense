# dataset-2 / spr

One spine of the three-spine `dataset-2` benchmark. 1000 SKUs, 3420 bins, 36035 orders (66497 lines).

## Contents

- `processed/` — the 12 relational tables (CSV).
- `metadata/` — source manifest, data dictionary, category mapping, SKU selection, schema notes, generation manifest.
- `reports/` — validation report and machine-readable error log.

## Notes

- Bin addresses, zones, item dimensions, weights, hazmat codes and pick history are real.
- Aisle coordinates, walking distances and bin capacities are inferred from the address grammar and the bin-location table; no measured layout is public.
- The inferred floor plan places zones side by side and compresses each zone to at most 24 aisle lines, so walking distances stay in the 45-200 m range of a real DC.
- The upstream sales archive is truncated; recovered pick lines are validated field by field.
- Hazmat codes map HA->flammable, HG->corrosive, HN->toxic; unmapped items are NONE.
- 4148 item rows were excluded for missing or implausible physical data.
- 0 selected SKUs were dropped because no inferred bin satisfies their handling, hazard, geometry and weight envelope; they remain listed in metadata/sku_selection.csv.
- Scenarios A/B/C are three disjoint sequential windows of the 2002 pick history.
- The real recorded slot for each SKU is shipped as raw/spr/current_slots.csv, outside the schema, so the engine can also score against the current layout.

Rebuild: `python build_dataset2.py --spine spr` from the project root.
