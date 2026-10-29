# dataset-2 / instacart

One spine of the three-spine `dataset-2` benchmark. 1200 SKUs, 2816 bins, 93248 orders (575749 lines).

## Contents

- `processed/` — the 12 relational tables (CSV).
- `metadata/` — source manifest, data dictionary, category mapping, SKU selection, schema notes, generation manifest.
- `reports/` — validation report and machine-readable error log.

## Notes

- Baskets, SKU names, aisles and departments are real Instacart records.
- Instacart publishes no dimensions or weights; they are synthesised by the class rule and flagged physical_data_source=synthetic_class_rule, physical_confidence=low.
- Timestamps are derived from order_number and hour of day on a documented 2017 anchor; the source has no absolute clock.
- Scenarios A/B/C are three disjoint sequential slices of the sampled order history.
- Hazard class is inferred from product-name keywords (no hazmat field exists).

Rebuild: `python build_dataset2.py --spine instacart` from the project root.
