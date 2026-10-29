# dataset-2 — three provenance spines

Three independently loadable benchmark datasets that share the `dataset/` schema.
Each spine answers a different question about the same slotting problem.

| spine | demand history | physical data | warehouse | SKUs | bins | orders | lines | validation |
|---|---|---|---|---|---|---|---|---|
| `olist` | real Olist orders | real W/H/D/kg | generated | 1200 | 2816 | 37042 | 37642 | PASS |
| `instacart` | real Instacart baskets | class-rule synthesis | generated | 1200 | 2816 | 93248 | 575749 | PASS |
| `spr` | real 2002 pick history | real item-master dimensions | real bin addresses | 1000 | 3420 | 36035 | 66497 | PASS |

## When to use which

- `olist` — you need real dimensions and real demand, and can live with a generated
  warehouse and inferred hazard classes. Weak basket affinity (mostly single-item orders).
- `instacart` — you need the strongest co-occurrence signal available (multi-item grocery
  baskets) and can accept synthesised dimensions.
- `spr` — you need everything real at once: real bins, real measured dimensions, real
  hazmat codes, real velocity classes, real picks. Smallest scale, strongest provenance,
  but the aisle geometry is inferred from the address grammar.

## Layout

```
dataset-2/
  olist/{processed,metadata,reports}/
  instacart/{processed,metadata,reports}/
  spr/{processed,metadata,reports}/
  raw/{olist,instacart,spr}/
```

Each spine directory is a complete dataset: point the loader or the validator at it exactly as you would at `dataset/`.

Rebuild everything with `python build_dataset2.py`.
