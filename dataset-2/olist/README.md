# dataset-2 / olist

One spine of the three-spine `dataset-2` benchmark. 1200 SKUs, 2816 bins, 37042 orders (37642 lines).

## Contents

- `processed/` — the 12 relational tables (CSV).
- `metadata/` — source manifest, data dictionary, category mapping, SKU selection, schema notes, generation manifest.
- `reports/` — validation report and machine-readable error log.

## Notes

- Order history, SKU dimensions and weights are real Olist records, used unmodified.
- The warehouse grid, capacities and aisle graph are generated (no real layout exists).
- Hazard class is inferred from product-category keywords (Olist has no hazmat field).
- Handling type follows the canonical category rule, with a >20 kg heavy override.
- Scenarios A/B/C are three disjoint sequential windows of the same real history.
- Product rows carry physical_confidence=medium: dimensions are seller-declared.
- 6 product rows were excluded for missing or out-of-envelope dimensions (no value was imputed or clipped).

Rebuild: `python build_dataset2.py --spine olist` from the project root.
