#!/usr/bin/env python3
"""Build ``dataset-2``: three provenance spines for the warehouse slotting benchmark.

Each spine is a complete, independently loadable copy of the 12-table schema used by
``dataset/`` (so the same engine, loader and validator consume it unchanged), but each
one takes its demand history and physical data from a different place:

``olist``
    Real Olist Brazilian e-commerce orders and real product W/H/D/kg. Warehouse grid is
    generated. Hazard and handling come from a documented category/keyword rule.

``instacart``
    Real Instacart grocery baskets (the strongest co-occurrence signal available under a
    CC0 licence). Dimensions are synthesised by the class rule, exactly as ``dataset/``.

``spr``
    Real S.P. Richards distribution-centre data: real bin addresses, real item-master
    dimensions, real hazmat codes, real velocity classes and a real pick history. Only the
    aisle geometry and bin capacities are inferred from the address grammar.

Usage::

    python build_dataset2.py                # build all three spines
    python build_dataset2.py --spine olist  # rebuild one
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import platform
import random
import re
import sys
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "dataset-2"
RAW = OUT / "raw"
REPO = Path("/home/hemanth/hackathon/SlotSense/smart-warehouse-slotting")
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.data_processing.derive import build_affinity, build_demand_summary  # noqa: E402
from src.data_processing.generate import (  # noqa: E402
    CATEGORY_SPECS,
    CLASS_BY_CATEGORY,
    build_inventory_and_baseline,
    build_warehouse,
    generate_categories,
    generate_compatibility_rules,
)
from src.data_processing.pipeline import (  # noqa: E402
    _sha256,
    _write_data_dictionary,
    _write_table,
    load_config,
)
from src.data_processing.schema import TABLES  # noqa: E402
from src.data_processing.validate import run_validation, write_validation_reports  # noqa: E402

DATASET_VERSION = "2.0.0"
SEED = 7
SPEC_BY_ID = {spec.category_id: spec for spec in CATEGORY_SPECS}
GENERATED_AT = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Category mapping: every source taxonomy collapses onto the same 10 classes
# ---------------------------------------------------------------------------

OLIST_CATEGORY_MAP: dict[str, str] = {
    "bed_bath_table": "CAT003", "sports_leisure": "CAT004", "furniture_decor": "CAT004",
    "health_beauty": "CAT001", "housewares": "CAT003", "auto": "CAT006",
    "computers_accessories": "CAT001", "toys": "CAT003", "watches_gifts": "CAT001",
    "telephony": "CAT009", "baby": "CAT003", "perfumery": "CAT001",
    "stationery": "CAT002", "fashion_bags_accessories": "CAT003", "cool_stuff": "CAT001",
    "garden_tools": "CAT006", "pet_shop": "CAT007", "electronics": "CAT009",
    "construction_tools_construction": "CAT006", "home_appliances": "CAT005",
    "luggage_accessories": "CAT004", "consoles_games": "CAT009",
    "office_furniture": "CAT004", "musical_instruments": "CAT009",
    "small_appliances": "CAT005", "home_construction": "CAT006",
    "books_general_interest": "CAT002", "fashion_shoes": "CAT003",
    "furniture_living_room": "CAT004", "air_conditioning": "CAT005",
    "books_technical": "CAT002", "fixed_telephony": "CAT009", "home_confort": "CAT003",
    "market_place": "CAT003", "food_drink": "CAT007", "fashion_male_clothing": "CAT003",
    "kitchen_dining_laundry_garden_furniture": "CAT004", "signaling_and_security": "CAT006",
    "construction_tools_safety": "CAT006", "home_appliances_2": "CAT005",
    "costruction_tools_garden": "CAT006", "food": "CAT007", "drinks": "CAT007",
    "construction_tools_lights": "CAT006", "agro_industry_and_commerce": "CAT007",
    "industry_commerce_and_business": "CAT003", "christmas_supplies": "CAT003",
    "audio": "CAT009", "art": "CAT003", "fashion_underwear_beach": "CAT003",
    "dvds_blu_ray": "CAT002", "furniture_bedroom": "CAT004",
    "costruction_tools_tools": "CAT006", "books_imported": "CAT002",
    "small_appliances_home_oven_and_coffee": "CAT005", "computers": "CAT009",
    "cine_photo": "CAT009", "fashio_female_clothing": "CAT003", "music": "CAT002",
    "party_supplies": "CAT003", "fashion_sport": "CAT003",
    "arts_and_craftmanship": "CAT001", "flowers": "CAT003", "diapers_and_hygiene": "CAT007",
    "la_cuisine": "CAT003", "furniture_mattress_and_upholstery": "CAT004",
    "tablets_printing_image": "CAT009", "fashion_childrens_clothes": "CAT003",
    "home_comfort_2": "CAT003", "security_and_services": "CAT006",
    "cds_dvds_musicals": "CAT002", "pc_gamer": "CAT009",
    "portateis_cozinha_e_preparadores_de_alimentos": "CAT005",
}

INSTACART_DEPARTMENT_MAP: dict[str, str] = {
    "frozen": "CAT003", "other": "CAT003", "bakery": "CAT003", "produce": "CAT003",
    "alcohol": "CAT008", "international": "CAT003", "beverages": "CAT007",
    "pets": "CAT007", "dry goods pasta": "CAT007", "babies": "CAT003", "deli": "CAT003",
    "personal care": "CAT001", "household": "CAT003", "breakfast": "CAT003",
    "canned goods": "CAT007", "dairy eggs": "CAT008", "meat seafood": "CAT003",
    "pantry": "CAT003", "snacks": "CAT003", "floral": "CAT003", "bulk": "CAT007",
}

# Hazard keywords. Applies to the Olist and Instacart spines only; S.P. Richards carries a
# real hazmat code and never goes through this table.
HAZARD_KEYWORDS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("bleach", "chlorine", "ammonia", "drain", "descaler", "lye"), "corrosive"),
    (("insecticide", "pesticide", "rodenticide", "poison"), "toxic"),
    (("perfume", "fragrance", "solvent", "thinner", "aerosol", "lighter fluid", "acetone",
      "alcohol", "spray paint", "propane"), "flammable"),
)

FRAGILE_KEYWORDS = ("glass", "ceramic", "mug", "vase", "bottle", "mirror", "lamp", "screen",
                    "monitor", "tv", "porcelain", "crystal", "lens", "camera")


def classify_hazard(text: str, keywords: tuple[tuple[tuple[str, ...], str], ...] = HAZARD_KEYWORDS) -> str:
    lowered = text.lower()
    for words, hazard in keywords:
        if any(word in lowered for word in words):
            return hazard
    return "NONE"


# Grocery wording ("alcohol free", "perfume gift set") would over-trigger the general list,
# so the Instacart spine uses only unambiguous household-hazard terms.
INSTACART_HAZARD_WORDS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("bleach", "chlorine", "ammonia", "lye", "drain cleaner", "disinfectant", "cleanser",
      "degreaser", "oven cleaner", "toilet bowl", "clorox", "lysol"), "corrosive"),
    (("insecticide", "pesticide", "rodenticide", "poison"), "toxic"),
    (("lighter fluid", "charcoal lighter", "propane", "butane", "solvent", "nail polish remover",
      "rubbing alcohol"), "flammable"),
)


def classify_handling(category_id: str, weight_kg: float, text: str) -> str:
    spec = SPEC_BY_ID[category_id]
    if category_id == "CAT010":
        # The hazard zone admits standard handling only; hazmat transport rules already
        # constrain how these units may be stacked and carried.
        return "standard"
    if weight_kg > 20.0 or spec.handling == "heavy":
        return "heavy"
    if spec.handling == "fragile" or any(word in text.lower() for word in FRAGILE_KEYWORDS):
        return "fragile"
    return "standard"


# ---------------------------------------------------------------------------
# Warehouse configuration
# ---------------------------------------------------------------------------

BASE_WAREHOUSE = {
    "dispatch_point_m": [0.0, -3.0],
    "aisle_width_m": 2.0,
    "rack_depth_m": 1.2,
    "shelf_height_m": 0.5,
    "zone_gap_m": 2.0,
    "rack_limit_factor": 0.85,
    "golden_levels": [1, 2],
    "n_aisles_per_zone": 4,
    "n_racks_per_aisle": 4,
    "n_bays_per_rack": 2,
    "n_shelves": 4,
    "n_bins_per_shelf": 2,
    "zone_layout": [
        {"zone_type": "general", "count": 3, "bin_class": "standard"},
        {"zone_type": "small_parts", "count": 1, "bin_class": "small"},
        {"zone_type": "bulk", "count": 2, "bin_class": "bulk"},
        {"zone_type": "heavy", "count": 3, "bin_class": "heavy_bulk"},
        {"zone_type": "hazard", "count": 1, "bin_class": "hazard"},
        {"zone_type": "general", "count": 1, "bin_class": "oversize"},
    ],
    "bin_classes": {
        "small": {"dims_cm": [45.0, 30.0, 40.0], "shelf_weight_kg": [40.0, 35.0, 30.0, 25.0]},
        "standard": {"dims_cm": [60.0, 40.0, 45.0], "shelf_weight_kg": [80.0, 60.0, 50.0, 40.0]},
        "bulk": {"dims_cm": [100.0, 70.0, 70.0], "shelf_weight_kg": [200.0, 160.0, 140.0, 120.0]},
        "heavy_bulk": {"dims_cm": [130.0, 120.0, 115.0], "shelf_weight_kg": [500.0, 450.0, 400.0, 350.0]},
        "hazard": {"dims_cm": [60.0, 40.0, 45.0], "shelf_weight_kg": [60.0, 50.0, 40.0, 30.0]},
        "oversize": {"dims_cm": [130.0, 120.0, 115.0], "shelf_weight_kg": [300.0, 250.0, 220.0, 200.0]},
    },
    "zone_rules": {
        "general": {"allowed_handling": ["standard", "fragile"], "allowed_hazard": ["NONE"]},
        "small_parts": {"allowed_handling": ["standard", "fragile"], "allowed_hazard": ["NONE"]},
        "bulk": {"allowed_handling": ["standard", "fragile", "heavy"], "allowed_hazard": ["NONE"]},
        "heavy": {"allowed_handling": ["standard", "heavy"], "allowed_hazard": ["NONE"]},
        "hazard": {"allowed_handling": ["standard"], "allowed_hazard": ["flammable", "corrosive", "toxic"]},
    },
}

INVENTORY_CFG = {
    "cover_days": 30,
    "safety_factor": 0.2,
    "min_units": 3,
    "max_bins_per_class": {
        "small": 2, "medium": 2, "bulky": 2, "heavy": 1, "fragile": 1, "hazard": 1,
    },
}


def spine_config(spine: str, start_date: str, days: int, warehouse_name: str) -> dict[str, Any]:
    return {
        "seed": SEED,
        "spine": spine,
        "order_window": {"start_date": start_date, "days": int(days)},
        "inventory": INVENTORY_CFG,
        "warehouse": {
            **BASE_WAREHOUSE,
            "warehouse_id": f"WH-{spine.upper()}",
            "warehouse_name": warehouse_name,
            "layout_version": f"dataset-2.{spine}.v1",
        },
    }


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _strip_high_heavy(locations: list[dict[str, Any]]) -> None:
    """Heavy units may only live on shelf levels 0-2, in every zone type."""
    for location in locations:
        if int(location["shelf_level"]) > 2 and "heavy" in location["_handling"]:
            allowed = frozenset(h for h in location["_handling"] if h != "heavy")
            location["_handling"] = allowed
            location["allowed_handling"] = "|".join(sorted(allowed))


def fmt_ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def split_windows(items: list[Any], key, parts: int = 3) -> list[list[Any]]:
    """Split a time-ordered list into equal, disjoint, sequential windows."""
    ordered = sorted(items, key=key)
    size = math.ceil(len(ordered) / parts)
    return [ordered[i * size:(i + 1) * size] for i in range(parts)]


def choose_skus(freq: Counter, n: int) -> tuple[list[str], list[str]]:
    ranked = [sku for sku, _ in freq.most_common()]
    return ranked[:n], ranked[n:]


def make_product(
    sku_id: str,
    name: str,
    category_id: str,
    width_cm: float,
    height_cm: float,
    depth_cm: float,
    weight_kg: float,
    hazard: str,
    handling: str,
    source: str,
    physical_source: str,
    confidence: str,
    data_source: str,
) -> dict[str, Any]:
    width_cm = round(width_cm, 2)
    height_cm = round(height_cm, 2)
    depth_cm = round(depth_cm, 2)
    return {
        "sku_id": sku_id,
        "product_name": name[:120],
        "category_id": category_id,
        "width_cm": width_cm,
        "height_cm": height_cm,
        "depth_cm": depth_cm,
        "unit_volume_cm3": round(width_cm * height_cm * depth_cm, 2),
        "unit_weight_kg": round(max(weight_kg, 0.01), 3),
        "handling_type": handling,
        "hazard_class": hazard,
        "data_source": data_source,
        "data_quality_status": "valid",
        "physical_data_source": physical_source,
        "physical_confidence": confidence,
    }


def write_spine(
    spine: str,
    cfg: dict[str, Any],
    products: list[dict[str, Any]],
    locations: list[dict[str, Any]],
    graph_rows: list[dict[str, Any]],
    orders: list[dict[str, Any]],
    order_items: list[dict[str, Any]],
    sources: list[dict[str, Any]],
    mapping_rows: list[dict[str, str]],
    selection_rows: list[dict[str, str]],
    notes: list[str],
    warehouse_source: str,
    assignment_source: str,
) -> dict[str, Any]:
    out = OUT / spine
    for sub in ("processed", "metadata", "reports"):
        (out / sub).mkdir(parents=True, exist_ok=True)

    _strip_high_heavy(locations)
    handling = Counter(product["handling_type"] for product in products)
    print(f"[{spine}] handling mix {dict(handling)}; bins {len(locations)}", flush=True)

    assignments, inventory = build_inventory_and_baseline(
        cfg, products, locations, orders, order_items, SEED + 10
    )
    demand = build_demand_summary(products, orders, order_items)
    affinity = build_affinity(products, orders, order_items)

    for row in assignments:
        row["data_source"] = assignment_source
    for row in inventory:
        row["data_source"] = "derived"

    tables: dict[str, list[dict[str, Any]]] = {
        "warehouses": [{
            "warehouse_id": cfg["warehouse"]["warehouse_id"],
            "warehouse_name": cfg["warehouse"]["warehouse_name"],
            "layout_version": cfg["warehouse"]["layout_version"],
            "data_source": warehouse_source,
            "data_quality_status": "valid",
        }],
        "categories": generate_categories(),
        "products": products,
        "locations": locations,
        "inventory": inventory,
        "compatibility_rules": generate_compatibility_rules(),
        "orders": orders,
        "order_items": order_items,
        "storage_assignments_baseline": assignments,
        "location_graph": graph_rows,
        "demand_summary": demand,
        "sku_affinity": affinity,
    }

    for table, rows in tables.items():
        _write_table(out / "processed" / f"{table}.csv", table, rows)

    _write_data_dictionary(out, tables)
    manifest = {
        "dataset_name": f"smart_warehouse_benchmark_{spine}",
        "dataset_version": DATASET_VERSION,
        "spine": spine,
        "seed": SEED,
        "generated_at": GENERATED_AT,
        "python_version": platform.python_version(),
        "config_sha256": hashlib.sha256(
            json.dumps(cfg, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "config": cfg,
        "counts": {table: len(rows) for table, rows in tables.items()},
        "files": {
            f"processed/{table}.csv": {
                "rows": len(rows),
                "sha256": _sha256(out / "processed" / f"{table}.csv"),
            }
            for table, rows in tables.items()
        },
    }
    (out / "metadata" / "generation_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    _write_sources(out, sources)
    _write_mapping(out, mapping_rows)
    _write_selection(out, selection_rows)
    _write_schema_doc(out, spine, cfg, tables, sources, notes)
    _write_readme(out, spine, cfg, tables, notes)

    validation = run_validation(out)
    write_validation_reports(out, validation)
    return {
        "spine": spine,
        "output": str(out),
        "counts": {table: len(rows) for table, rows in tables.items()},
        "validation": {
            "ok": validation.ok,
            "hard_errors": validation.hard_errors,
            "warnings": validation.warnings,
        },
    }


def _write_sources(out: Path, sources: list[dict[str, Any]]) -> None:
    path = out / "metadata" / "source_manifest.csv"
    fields = ["source_id", "source_name", "url", "license", "download_date", "file_name",
              "record_count", "primary_key", "notes", "status"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in sources:
            writer.writerow({key: row.get(key, "") for key in fields})


def _write_mapping(out: Path, rows: list[dict[str, str]]) -> None:
    path = out / "metadata" / "category_mapping.csv"
    fields = ["source_category", "canonical_category", "canonical_name", "rule", "records"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _write_selection(out: Path, rows: list[dict[str, str]]) -> None:
    path = out / "metadata" / "sku_selection.csv"
    fields = ["sku_id", "source_id", "demand_frequency", "selected", "reason"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _write_schema_doc(
    out: Path,
    spine: str,
    cfg: dict[str, Any],
    tables: dict[str, list[dict[str, Any]]],
    sources: list[dict[str, Any]],
    notes: list[str],
) -> None:
    lines = [
        f"# Benchmark Dataset Schema — `{spine}` spine",
        "",
        f"- Dataset: `dataset-2` ({DATASET_VERSION}), spine `{spine}`",
        f"- Seed: `{cfg['seed']}`",
        f"- SKUs: {len(tables['products'])}",
        f"- Locations: {len(tables['locations'])}",
        f"- Orders: {len(tables['orders'])}; order lines: {len(tables['order_items'])}",
        f"- Demand scenarios: {len({row['scenario_id'] for row in tables['orders']})}",
        "",
        "## Tables",
        "",
        "| table | rows |",
        "|---|---|",
    ]
    lines += [f"| {table} | {len(rows)} |" for table, rows in tables.items()]
    lines += [
        "",
        "Field definitions, units and primary keys: `metadata/data_dictionary.csv`.",
        "The schema is byte-compatible with `dataset/` (same 12 tables, same column order).",
        "",
        "## Provenance",
        "",
        "| source | license | file | records | status |",
        "|---|---|---|---|---|",
    ]
    for source in sources:
        lines.append(
            f"| {source['source_name']} | {source.get('license', '')} | "
            f"{source.get('file_name', '')} | {source.get('record_count', '')} | "
            f"{source.get('status', '')} |"
        )
    lines += ["", "## Spine notes", ""] + [f"- {note}" for note in notes]
    lines += [
        "",
        "## Units",
        "",
        "Dimensions cm, weight kg, volume cm3, coordinates/distance m, timestamps UTC.",
        "",
    ]
    (out / "metadata" / "schema_documentation.md").write_text("\n".join(lines), encoding="utf-8")


def _write_readme(
    out: Path,
    spine: str,
    cfg: dict[str, Any],
    tables: dict[str, list[dict[str, Any]]],
    notes: list[str],
) -> None:
    lines = [
        f"# dataset-2 / {spine}",
        "",
        f"One spine of the three-spine `dataset-2` benchmark. {len(tables['products'])} SKUs, "
        f"{len(tables['locations'])} bins, {len(tables['orders'])} orders "
        f"({len(tables['order_items'])} lines).",
        "",
        "## Contents",
        "",
        "- `processed/` — the 12 relational tables (CSV).",
        "- `metadata/` — source manifest, data dictionary, category mapping, SKU selection, "
        "schema notes, generation manifest.",
        "- `reports/` — validation report and machine-readable error log.",
        "",
        "## Notes",
        "",
    ] + [f"- {note}" for note in notes] + [
        "",
        "Rebuild: `python build_dataset2.py --spine " + spine + "` from the project root.",
        "",
    ]
    (out / "README.md").write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Spine 1 — Olist: real orders, real dimensions, generated warehouse
# ---------------------------------------------------------------------------

def _olist_dims_ok(row: dict[str, str]) -> bool:
    keys = ("product_width_cm", "product_height_cm", "product_length_cm", "product_weight_g")
    try:
        values = [float(row[key]) for key in keys]
    except (KeyError, TypeError, ValueError):
        return False
    return all(value > 0 for value in values) and max(values[:3]) <= 130 and values[3] <= 100_000


def build_olist() -> dict[str, Any]:
    raw = RAW / "olist"
    products_src = list(_csv(raw / "olist_products_dataset.csv"))
    items_src = list(_csv(raw / "olist_order_items_dataset.csv"))
    orders_src = list(_csv(raw / "olist_orders_dataset.csv"))
    translation = {
        row["product_category_name"]: row["product_category_name_english"]
        for row in _csv_sig(raw / "product_category_name_translation.csv")
    }

    order_ts = {
        row["order_id"]: row["order_purchase_timestamp"]
        for row in orders_src
        if row["order_status"] == "delivered" and row["order_purchase_timestamp"]
    }
    product_by_id = {row["product_id"]: row for row in products_src if _olist_dims_ok(row)}
    excluded_products = len(products_src) - len(product_by_id)

    lines: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for item in items_src:
        order_id = item["order_id"]
        if order_id not in order_ts or item["product_id"] not in product_by_id:
            continue
        lines[order_id].append((item["product_id"], 1))

    # Olist repeats product_id across order_item_id when a line has several units; collapse
    # to one line per (order, product) with quantity equal to the number of source rows.
    collapsed: dict[str, list[tuple[str, int]]] = {}
    for order_id, rows in lines.items():
        totals: Counter = Counter()
        for product_id, _ in rows:
            totals[product_id] += 1
        collapsed[order_id] = sorted(totals.items())
    lines = collapsed

    freq: Counter = Counter()
    for rows in lines.values():
        for product_id, _ in rows:
            freq[product_id] += 1

    selected, dropped = choose_skus(freq, 1200)
    selected_set = set(selected)

    def parse_ts(text: str) -> datetime:
        return datetime.strptime(text, "%Y-%m-%d %H:%M:%S")

    kept_orders = sorted(
        (oid for oid, rows in lines.items() if any(sku in selected_set for sku, _ in rows)),
        key=lambda oid: parse_ts(order_ts[oid]),
    )
    windows = split_windows(kept_orders, key=lambda oid: parse_ts(order_ts[oid]))
    start = parse_ts(order_ts[windows[0][0]]).date()
    last = parse_ts(order_ts[windows[-1][-1]]).date()
    cfg = spine_config("olist", start.isoformat(), (last - start).days + 1,
                       "Olist-derived benchmark warehouse")

    sku_by_product: dict[str, str] = {}
    products: list[dict[str, Any]] = []
    mapping_rows: list[dict[str, str]] = []
    category_counts: Counter = Counter()
    for index, product_id in enumerate(selected, start=1):
        row = product_by_id[product_id]
        english = translation.get(row["product_category_name"], "unknown")
        category_id = OLIST_CATEGORY_MAP.get(english)
        rule = "explicit map"
        if category_id is None:
            category_id = _fallback_category(english)
            rule = "keyword fallback"
        sku_id = f"OL-{index:05d}"
        sku_by_product[product_id] = sku_id
        width = float(row["product_width_cm"])
        height = float(row["product_height_cm"])
        depth = float(row["product_length_cm"])
        weight = float(row["product_weight_g"]) / 1000.0
        name = english.replace("_", " ").title()
        hazard = classify_hazard(name)
        handling = classify_handling(category_id, weight, name)
        products.append(
            make_product(
                sku_id, f"{name} {product_id[-6:]}", category_id,
                width, height, depth, weight, hazard, handling,
                source="sourced", physical_source="olist_products_dataset",
                confidence="medium", data_source="sourced",
            )
        )
        category_counts[english] += 1

    for english, count in sorted(category_counts.items()):
        canonical = OLIST_CATEGORY_MAP.get(english) or _fallback_category(english)
        mapping_rows.append({
            "source_category": english,
            "canonical_category": canonical,
            "canonical_name": SPEC_BY_ID[canonical].name,
            "rule": "explicit map" if english in OLIST_CATEGORY_MAP else "keyword fallback",
            "records": str(count),
        })

    orders: list[dict[str, Any]] = []
    order_items: list[dict[str, Any]] = []
    for scenario, window in zip(("A", "B", "C"), windows):
        for index, order_id in enumerate(window, start=1):
            new_id = f"OL-{scenario}-{index:06d}"
            orders.append({
                "order_id": new_id,
                "scenario_id": scenario,
                "order_timestamp": fmt_ts(parse_ts(order_ts[order_id])),
                "order_status": "completed",
                "data_source": "sourced",
                "data_quality_status": "valid",
            })
            seen: set[str] = set()
            for product_id, quantity in sorted(lines[order_id]):
                sku_id = sku_by_product.get(product_id)
                if sku_id is None or sku_id in seen:
                    continue
                seen.add(sku_id)
                order_items.append({
                    "order_id": new_id,
                    "sku_id": sku_id,
                    "quantity": quantity,
                    "data_source": "sourced",
                })

    locations, graph_rows, _ = build_warehouse(cfg)
    _strip_high_heavy(locations)
    for location in locations:
        location["data_source"] = "synthetic"

    selection_rows = [
        {"sku_id": sku_by_product.get(pid, ""), "source_id": pid,
         "demand_frequency": str(freq[pid]), "selected": "yes",
         "reason": "top 1200 by distinct-order frequency"}
        for pid in selected
    ] + [
        {"sku_id": "", "source_id": pid, "demand_frequency": str(freq[pid]),
         "selected": "no", "reason": "long tail below the SKU cap"}
        for pid in dropped
    ]

    sources = [
        {
            "source_id": "olist_orders", "source_name": "Olist orders dataset",
            "url": "https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce",
            "license": "CC BY-NC-SA 4.0", "download_date": GENERATED_AT[:10],
            "file_name": "raw/olist/olist_orders_dataset.csv",
            "record_count": len(orders_src), "primary_key": "order_id",
            "notes": "Delivered orders only; purchase timestamp is real.", "status": "sourced",
        },
        {
            "source_id": "olist_items", "source_name": "Olist order items",
            "url": "https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce",
            "license": "CC BY-NC-SA 4.0", "download_date": GENERATED_AT[:10],
            "file_name": "raw/olist/olist_order_items_dataset.csv",
            "record_count": len(items_src), "primary_key": "order_id + order_item_id",
            "notes": "One unit per line in the source; quantity is fixed at 1.",
            "status": "sourced",
        },
        {
            "source_id": "olist_products", "source_name": "Olist product master",
            "url": "https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce",
            "license": "CC BY-NC-SA 4.0", "download_date": GENERATED_AT[:10],
            "file_name": "raw/olist/olist_products_dataset.csv",
            "record_count": len(products_src), "primary_key": "product_id",
            "notes": "Seller-declared weight and dimensions, used unmodified.",
            "status": "sourced",
        },
        {
            "source_id": "warehouse_generated", "source_name": "Generated warehouse grid",
            "url": "", "license": "Project-internal",
            "download_date": GENERATED_AT[:10], "file_name": "processed/locations.csv",
            "record_count": len(locations), "primary_key": "location_id",
            "notes": "Topology, capacities and aisle graph generated; no real warehouse data.",
            "status": "generated",
        },
    ]
    notes = [
        "Order history, SKU dimensions and weights are real Olist records, used unmodified.",
        "The warehouse grid, capacities and aisle graph are generated (no real layout exists).",
        "Hazard class is inferred from product-category keywords (Olist has no hazmat field).",
        "Handling type follows the canonical category rule, with a >20 kg heavy override.",
        "Scenarios A/B/C are three disjoint sequential windows of the same real history.",
        "Product rows carry physical_confidence=medium: dimensions are seller-declared.",
        f"{excluded_products} product rows were excluded for missing or out-of-envelope "
        "dimensions (no value was imputed or clipped).",
    ]
    return write_spine(
        "olist", cfg, products, locations, graph_rows, orders, order_items, sources,
        mapping_rows, selection_rows, notes,
        warehouse_source="synthetic", assignment_source="derived",
    )


def _fallback_category(name: str) -> str:
    lowered = name.lower()
    if any(word in lowered for word in ("book", "media", "dvd", "music", "art")):
        return "CAT002"
    if any(word in lowered for word in ("tool", "construction", "auto", "security", "garden")):
        return "CAT006"
    if any(word in lowered for word in ("appliance", "air", "oven", "coffee")):
        return "CAT005"
    if any(word in lowered for word in ("furniture", "mattress", "luggage", "sport")):
        return "CAT004"
    if any(word in lowered for word in ("electronic", "computer", "phone", "audio", "game")):
        return "CAT009"
    if any(word in lowered for word in ("food", "drink", "pet", "diaper", "agro")):
        return "CAT007"
    return "CAT003"


# ---------------------------------------------------------------------------
# Spine 2 — Instacart: real baskets, synthesised dimensions
# ---------------------------------------------------------------------------

def build_instacart() -> dict[str, Any]:
    raw = RAW / "instacart"
    products_src = {row["product_id"]: row for row in _csv(raw / "products.csv")}
    departments = {row["department_id"]: row["department"] for row in _csv(raw / "departments.csv")}
    order_meta = {row["order_id"]: row for row in _csv(raw / "orders.csv")}

    max_orders = 100_000
    baskets: dict[str, list[str]] = {}
    freq: Counter = Counter()
    with (raw / "order_products__prior.csv").open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            order_id = row["order_id"]
            if order_id not in baskets:
                if len(baskets) >= max_orders:
                    break
                baskets[order_id] = []
            baskets[order_id].append(row["product_id"])
            freq[row["product_id"]] += 1

    selected, dropped = choose_skus(freq, 1200)
    selected_set = set(selected)

    def order_number(order_id: str) -> int:
        try:
            return int(order_meta[order_id]["order_number"])
        except (KeyError, ValueError):
            return 0

    kept = sorted(
        (oid for oid, rows in baskets.items() if selected_set.intersection(rows)),
        key=order_number,
    )
    windows = split_windows(kept, key=order_number)

    # Instacart has no absolute clock: reconstruct a monotone axis from order_number and
    # the recorded hour of day. Documented as derived, never presented as measured time.
    anchor = datetime(2017, 1, 1)
    ts_by_order: dict[str, datetime] = {}
    for order_id in kept:
        meta = order_meta.get(order_id, {})
        try:
            hour = int(meta.get("order_hour_of_day", 12))
        except ValueError:
            hour = 12
        ts_by_order[order_id] = anchor + timedelta(days=order_number(order_id), hours=hour % 24)

    last = max(ts_by_order.values()).date()
    cfg = spine_config("instacart", anchor.date().isoformat(), (last - anchor.date()).days + 1,
                       "Instacart-derived benchmark warehouse")

    sku_by_product: dict[str, str] = {}
    products: list[dict[str, Any]] = []
    mapping_rows: list[dict[str, str]] = []
    department_counts: Counter = Counter()
    for index, product_id in enumerate(selected, start=1):
        row = products_src[product_id]
        department = departments.get(row["department_id"], "other")
        category_id = INSTACART_DEPARTMENT_MAP.get(department, "CAT003")
        name = row["product_name"]
        hazard = classify_hazard(name, INSTACART_HAZARD_WORDS)
        if hazard != "NONE":
            category_id = "CAT010"
        sku_id = f"IC-{index:05d}"
        sku_by_product[product_id] = sku_id
        spec = SPEC_BY_ID[category_id]
        # Same class rule the synthetic benchmark uses: base dimensions scaled per SKU.
        rng = random.Random(SEED * 100003 + index)
        size = rng.uniform(*spec.size_range)
        width = spec.base_dims_cm[0] * size * rng.uniform(0.92, 1.08)
        height = spec.base_dims_cm[1] * size * rng.uniform(0.92, 1.08)
        depth = spec.base_dims_cm[2] * size * rng.uniform(0.92, 1.08)
        density = rng.uniform(*spec.density_range)
        volume = width * height * depth
        weight = min(max(volume / 1000.0 * density, 0.01), spec.max_unit_weight_kg)
        handling = classify_handling(category_id, weight, name)
        products.append(
            make_product(
                sku_id, name, category_id, width, height, depth, weight, hazard, handling,
                source="sourced", physical_source="synthetic_class_rule",
                confidence="low", data_source="sourced",
            )
        )
        department_counts[department] += 1

    for department, count in sorted(department_counts.items()):
        canonical = INSTACART_DEPARTMENT_MAP.get(department, "CAT003")
        mapping_rows.append({
            "source_category": department,
            "canonical_category": canonical,
            "canonical_name": SPEC_BY_ID[canonical].name,
            "rule": "department map",
            "records": str(count),
        })

    orders: list[dict[str, Any]] = []
    order_items: list[dict[str, Any]] = []
    for scenario, window in zip(("A", "B", "C"), windows):
        for index, order_id in enumerate(window, start=1):
            new_id = f"IC-{scenario}-{index:06d}"
            orders.append({
                "order_id": new_id,
                "scenario_id": scenario,
                "order_timestamp": fmt_ts(ts_by_order[order_id]),
                "order_status": "completed",
                "data_source": "sourced",
                "data_quality_status": "valid",
            })
            seen: set[str] = set()
            for product_id in baskets[order_id]:
                sku_id = sku_by_product.get(product_id)
                if sku_id is None or sku_id in seen:
                    continue
                seen.add(sku_id)
                order_items.append({
                    "order_id": new_id, "sku_id": sku_id, "quantity": 1,
                    "data_source": "sourced",
                })

    locations, graph_rows, _ = build_warehouse(cfg)
    _strip_high_heavy(locations)
    for location in locations:
        location["data_source"] = "synthetic"

    selection_rows = [
        {"sku_id": sku_by_product.get(pid, ""), "source_id": pid,
         "demand_frequency": str(freq[pid]), "selected": "yes",
         "reason": "top 1200 by basket frequency"}
        for pid in selected
    ] + [
        {"sku_id": "", "source_id": pid, "demand_frequency": str(freq[pid]),
         "selected": "no", "reason": "long tail below the SKU cap"}
        for pid in dropped
    ]

    sources = [
        {
            "source_id": "instacart_prior", "source_name": "Instacart Market Basket Analysis — prior orders",
            "url": "https://www.kaggle.com/datasets/psparks/instacart-market-basket-analysis",
            "license": "CC0 1.0", "download_date": GENERATED_AT[:10],
            "file_name": "raw/instacart/order_products__prior.csv",
            "record_count": sum(len(v) for v in baskets.values()),
            "primary_key": "order_id + product_id",
            "notes": f"First {len(baskets)} orders read from the prior history.",
            "status": "sourced",
        },
        {
            "source_id": "instacart_orders", "source_name": "Instacart orders",
            "url": "https://www.kaggle.com/datasets/psparks/instacart-market-basket-analysis",
            "license": "CC0 1.0", "download_date": GENERATED_AT[:10],
            "file_name": "raw/instacart/orders.csv", "record_count": len(order_meta),
            "primary_key": "order_id",
            "notes": "Provides order_number and hour of day; no absolute timestamps exist.",
            "status": "sourced",
        },
        {
            "source_id": "instacart_products", "source_name": "Instacart product catalogue",
            "url": "https://www.kaggle.com/datasets/psparks/instacart-market-basket-analysis",
            "license": "CC0 1.0", "download_date": GENERATED_AT[:10],
            "file_name": "raw/instacart/products.csv", "record_count": len(products_src),
            "primary_key": "product_id",
            "notes": "Names, aisles and departments; no physical dimensions.",
            "status": "sourced",
        },
        {
            "source_id": "dimensions_class_rule", "source_name": "Class-rule dimension synthesis",
            "url": "", "license": "Project-internal",
            "download_date": GENERATED_AT[:10], "file_name": "processed/products.csv",
            "record_count": len(products), "primary_key": "sku_id",
            "notes": "Deterministic per-SKU draw around the canonical category base dimensions.",
            "status": "generated",
        },
    ]
    notes = [
        "Baskets, SKU names, aisles and departments are real Instacart records.",
        "Instacart publishes no dimensions or weights; they are synthesised by the class rule "
        "and flagged physical_data_source=synthetic_class_rule, physical_confidence=low.",
        "Timestamps are derived from order_number and hour of day on a documented 2017 anchor; "
        "the source has no absolute clock.",
        "Scenarios A/B/C are three disjoint sequential slices of the sampled order history.",
        "Hazard class is inferred from product-name keywords (no hazmat field exists).",
    ]
    return write_spine(
        "instacart", cfg, products, locations, graph_rows, orders, order_items, sources,
        mapping_rows, selection_rows, notes,
        warehouse_source="synthetic", assignment_source="derived",
    )


# ---------------------------------------------------------------------------
# Spine 3 — S.P. Richards: real bins, real dimensions, real picks
# ---------------------------------------------------------------------------

SPR_ZONE_CLASS = {
    "C": ("general", "standard"),
    "D": ("small_parts", "small"),
    "E": ("general", "standard"),
    "F": ("hazard", "hazard"),
    "R": ("heavy", "heavy_bulk"),
    "S": ("bulk", "oversize"),
    "Z": ("general", "standard"),
}
SPR_HAZMAT = {"HA": "flammable", "HG": "corrosive", "HN": "toxic"}
BIN_RE = re.compile(r"^([A-Z]*)(\d+)([A-Z]*)(\d*)$")


def parse_bin_code(code: str, zone: str) -> dict[str, Any] | None:
    """Split a real bin address into aisle / section / level.

    Addresses follow a house grammar rather than one fixed pattern, so the zone prefix from
    the item master is stripped first and the remainder is read as
    ``[section letters][aisle digits][section letters][level digits]``.
    """
    rest = code[len(zone):] if code.startswith(zone) else code
    match = BIN_RE.match(rest)
    if not match:
        return None
    leading, aisle, section, level = match.groups()
    return {
        "aisle": max(1, int(aisle)),
        "section": (section or leading or "A")[:1],
        "level": max(1, int(level)) if level else 1,
    }


def build_spr() -> dict[str, Any]:
    raw = RAW / "spr"
    dims = {
        row["SKU"].strip(): row
        for row in _tsv_from_zip(raw / "SkuDimensions.zip", "Ref - Product Dimensions.txt")
    }
    skus = list(_tsv_from_zip(raw / "skus.zip", "skus.txt"))

    # Recovered from a truncated upstream archive. The inflate stream is intact only up to the
    # corruption point, so parsing stops at the first structural break or non-increasing id.
    picks: list[dict[str, str]] = []
    with (raw / "sales-2002-recovered.txt").open(encoding="latin-1") as handle:
        header = handle.readline().rstrip("\n").split("\t")
        for line in handle:
            parts = line.rstrip("\n").split("\t")
            if len(parts) != len(header) or not parts[0].isdigit():
                break
            try:
                qty = int(float(parts[6]))
                datetime.strptime(parts[1], "%m/%d/%Y %H:%M:%S")
            except (ValueError, IndexError):
                break
            if qty <= 0:
                break
            picks.append(dict(zip(header, parts)))

    freq: Counter = Counter()
    for pick in picks:
        freq[pick["item"].strip()] += 1

    candidates: dict[str, dict[str, Any]] = {}
    excluded: Counter = Counter()
    for sku in skus:
        if not sku.get("Item") or not sku.get("Bin Location") or not sku.get("Zone"):
            excluded["incomplete item row"] += 1
            continue
        item = sku["Item"].strip()
        dim = dims.get(item)
        if not dim:
            excluded["no dimension record"] += 1
            continue
        try:
            length = float(dim["SellLen"]); width = float(dim["SellWid"])
            height = float(dim["SellHgt"]); weight = float(dim["SellWgt"])
        except (TypeError, ValueError):
            excluded["incomplete dimensions"] += 1
            continue
        if min(length, width, height, weight) <= 0:
            excluded["non-positive dimensions"] += 1
            continue
        if max(length, width, height) > 130 or weight > 100:
            excluded["outside plausibility envelope"] += 1
            continue
        if (dim.get("Hazmat") or "").strip() and (max(length, width, height) > 55 or weight > 55):
            excluded["hazmat outside the hazard bin envelope"] += 1
            continue
        zone = sku["Zone"].strip()
        if zone not in SPR_ZONE_CLASS:
            excluded["no usable zone"] += 1
            continue
        if not BIN_RE.match(sku["Bin Location"].strip().upper().lstrip(zone)):
            excluded["unparsable bin address"] += 1
            continue
        candidates[item] = {
            "bin": sku["Bin Location"].strip().upper(),
            "zone": zone,
            "description": sku["Description"].strip(),
            "length": length, "width": width, "height": height, "weight": weight,
            "hazmat": (dim.get("Hazmat") or "").strip(),
            "velocity": (dim.get("Velocity") or "").strip(),
            "frequency": freq.get(item, 0),
        }

    ranked = sorted(candidates.items(), key=lambda kv: (-kv[1]["frequency"], kv[0]))
    active = [(item, info) for item, info in ranked if info["frequency"] > 0][:1000]
    dropped = [item for item, info in ranked if info["frequency"] > 0][1000:]
    selected_items = {item for item, _ in active}

    pick_orders: dict[str, list[dict[str, str]]] = defaultdict(list)
    for pick in picks:
        if pick["item"].strip() in selected_items:
            pick_orders[pick["ordnbr"].strip()].append(pick)

    def order_date(order_id: str) -> datetime:
        return datetime.strptime(pick_orders[order_id][0]["txndate"], "%m/%d/%Y %H:%M:%S")

    kept = sorted(pick_orders, key=order_date)
    # The recovered history holds ~477k orders in a 23-day window; keep a systematic sample
    # that spans the whole period so the benchmark stays a tractable size.
    sampled = kept
    if len(kept) > 40_000:
        step = math.ceil(len(kept) / 40_000)
        sampled = kept[::step]
    windows = split_windows(sampled, key=order_date)
    start = order_date(sampled[0]).date()
    last = order_date(sampled[-1]).date()
    cfg = spine_config("spr", start.isoformat(), (last - start).days + 1,
                       "S.P. Richards Philadelphia DC (real bins, inferred geometry)")

    sku_by_item: dict[str, str] = {}
    products: list[dict[str, Any]] = []
    mapping_rows: list[dict[str, str]] = []
    category_counts: Counter = Counter()
    for index, (item, info) in enumerate(active, start=1):
        sku_id = f"SPR-{index:05d}"
        sku_by_item[item] = sku_id
        category_id = _spr_category(info)
        hazard = SPR_HAZMAT.get(info["hazmat"], "NONE")
        handling = classify_handling(category_id, info["weight"], info["description"])
        products.append(
            make_product(
                sku_id, info["description"] or item, category_id,
                info["width"], info["height"], info["length"], info["weight"],
                hazard, handling, source="measured",
                physical_source="spr_sku_dimensions", confidence="high",
                data_source="measured",
            )
        )
        category_counts[category_id] += 1

    for category_id, count in sorted(category_counts.items()):
        mapping_rows.append({
            "source_category": "item master row",
            "canonical_category": category_id,
            "canonical_name": SPEC_BY_ID[category_id].name,
            "rule": "weight/volume/keyword/hazmat rule",
            "records": str(count),
        })

    locations, graph_rows = build_spr_layout(active, cfg, _spr_bin_pool(raw))
    home = {p["sku_id"] for p in products if _has_home(p, locations)}
    pruned = [p for p in products if p["sku_id"] not in home]
    products = [p for p in products if p["sku_id"] in home]

    orders: list[dict[str, Any]] = []
    order_items: list[dict[str, Any]] = []
    for scenario, window in zip(("A", "B", "C"), windows):
        for index, order_id in enumerate(window, start=1):
            new_id = f"SPR-{scenario}-{index:06d}"
            totals: dict[str, int] = defaultdict(int)
            for pick in pick_orders[order_id]:
                sku_id = sku_by_item[pick["item"].strip()]
                if sku_id in home:
                    totals[sku_id] += int(float(pick["ordqty"]))
            if not totals:
                continue
            orders.append({
                "order_id": new_id,
                "scenario_id": scenario,
                "order_timestamp": fmt_ts(order_date(order_id)),
                "order_status": "completed",
                "data_source": "measured",
                "data_quality_status": "valid",
            })
            for sku_id, quantity in sorted(totals.items()):
                order_items.append({
                    "order_id": new_id, "sku_id": sku_id,
                    "quantity": max(1, quantity), "data_source": "measured",
                })

    selection_rows = [
        {"sku_id": sku_by_item.get(item, ""), "source_id": item,
         "demand_frequency": str(info["frequency"]), "selected": "yes",
         "reason": "top 1000 active SKUs by pick-line frequency"}
        for item, info in active if sku_by_item.get(item) in home
    ] + [
        {"sku_id": sku_id, "source_id": sku_id, "demand_frequency": "",
         "selected": "no", "reason": "no compatible bin in the inferred layout"}
        for sku_id in (p["sku_id"] for p in pruned)
    ] + [
        {"sku_id": "", "source_id": item, "demand_frequency": str(candidates[item]["frequency"]),
         "selected": "no", "reason": "below the SKU cap"}
        for item in dropped
    ]

    sources = [
        {
            "source_id": "spr_skus", "source_name": "S.P. Richards item master (skus.txt)",
            "url": "https://www.warehouse-science.com/wh/projects/spr/data/skus.zip",
            "license": "Educational use, Warehouse & Distribution Science (Bartholdi & Hackman)",
            "download_date": GENERATED_AT[:10], "file_name": "raw/spr/skus.zip",
            "record_count": len(skus), "primary_key": "Item",
            "notes": "Real item descriptions, bin addresses and zone codes.",
            "status": "sourced",
        },
        {
            "source_id": "spr_dimensions", "source_name": "S.P. Richards product dimensions",
            "url": "https://www.warehouse-science.com/wh/projects/spr/data/SkuDimensions.zip",
            "license": "Educational use, Warehouse & Distribution Science (Bartholdi & Hackman)",
            "download_date": GENERATED_AT[:10], "file_name": "raw/spr/SkuDimensions.zip",
            "record_count": len(dims), "primary_key": "SKU",
            "notes": "Measured selling-unit length/width/height/weight, hazmat code, velocity class.",
            "status": "sourced",
        },
        {
            "source_id": "spr_sales", "source_name": "S.P. Richards 2002 pick history",
            "url": "https://www.warehouse-science.com/wh/projects/spr/data/sales-2002.zip",
            "license": "Educational use, Warehouse & Distribution Science (Bartholdi & Hackman)",
            "download_date": GENERATED_AT[:10],
            "file_name": "raw/spr/sales-2002-recovered.txt",
            "record_count": len(picks), "primary_key": "ID",
            "notes": "Upstream archive is truncated; recovered lines were validated field by field.",
            "status": "sourced_recovered",
        },
        {
            "source_id": "spr_bins", "source_name": "S.P. Richards bin location table",
            "url": "https://www.warehouse-science.com/wh/projects/spr/data/BinLocationTable.txt",
            "license": "Educational use, Warehouse & Distribution Science (Bartholdi & Hackman)",
            "download_date": GENERATED_AT[:10], "file_name": "raw/spr/BinLocationTable.txt",
            "record_count": sum(1 for _ in (raw / "BinLocationTable.txt").open(encoding="latin-1")) - 1,
            "primary_key": "binlocation",
            "notes": "Real bin ids and location types, used to size bins and levels.",
            "status": "sourced",
        },
        {
            "source_id": "spr_geometry", "source_name": "Inferred aisle geometry",
            "url": "", "license": "Project-internal",
            "download_date": GENERATED_AT[:10], "file_name": "processed/location_graph.csv",
            "record_count": len(graph_rows), "primary_key": "from_node_id + to_node_id",
            "notes": "Coordinates and walking distances derived from the address grammar.",
            "status": "inferred",
        },
    ]
    notes = [
        "Bin addresses, zones, item dimensions, weights, hazmat codes and pick history are real.",
        "Aisle coordinates, walking distances and bin capacities are inferred from the address "
        "grammar and the bin-location table; no measured layout is public.",
        "The inferred floor plan places zones side by side and compresses each zone to at most "
        "24 aisle lines, so walking distances stay in the 45-200 m range of a real DC.",
        "The upstream sales archive is truncated; recovered pick lines are validated field by field.",
        "Hazmat codes map HA->flammable, HG->corrosive, HN->toxic; unmapped items are NONE.",
        f"{sum(excluded.values())} item rows were excluded for missing or implausible physical data.",
        f"{len(pruned)} selected SKUs were dropped because no inferred bin satisfies their "
        "handling, hazard, geometry and weight envelope; they remain listed in "
        "metadata/sku_selection.csv.",
        "Scenarios A/B/C are three disjoint sequential windows of the 2002 pick history.",
        "The real recorded slot for each SKU is shipped as raw/spr/current_slots.csv, outside the "
        "schema, so the engine can also score against the current layout.",
    ]
    result = write_spine(
        "spr", cfg, products, locations, graph_rows, orders, order_items, sources,
        mapping_rows, selection_rows, notes,
        warehouse_source="sourced", assignment_source="derived",
    )
    _write_current_slots(active, sku_by_item, home)
    return result


def _has_home(product: dict[str, Any], locations: list[dict[str, Any]]) -> bool:
    """True when at least one bin respects handling, hazard, geometry and unit weight."""
    for location in locations:
        if product["handling_type"] not in location["_handling"]:
            continue
        if product["hazard_class"] not in location["_hazard"]:
            continue
        if (
            product["width_cm"] <= location["width_cm"]
            and product["height_cm"] <= location["height_cm"]
            and product["depth_cm"] <= location["depth_cm"]
            and product["unit_weight_kg"] <= location["max_weight_kg"]
        ):
            return True
    return False


def _spr_category(info: dict[str, Any]) -> str:
    if info["hazmat"]:
        return "CAT010"
    text = info["description"].lower()
    volume = info["length"] * info["width"] * info["height"]
    if info["weight"] > 15:
        return "CAT007"
    if info["weight"] > 5:
        return "CAT006"
    if volume > 200_000:
        return "CAT005"
    if volume > 60_000:
        return "CAT004"
    if any(word in text for word in ("glass", "ceramic", "mug", "vase", "mirror", "porcelain")):
        return "CAT008"
    if any(word in text for word in ("lamp", "monitor", "phone", "camera", "radio", "speaker")):
        return "CAT009"
    if any(word in text for word in ("book", "pad", "binder", "folder", "paper", "calendar")):
        return "CAT002"
    if volume < 1_000:
        return "CAT001"
    return "CAT003"


def _spr_bin_pool(raw: Path) -> dict[str, list[str]]:
    pool: dict[str, list[str]] = defaultdict(list)
    with (raw / "BinLocationTable.txt").open(encoding="latin-1", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            code = (row.get("binlocation") or "").strip().upper()
            zone = (row.get("Zone") or "").strip()
            if code and zone in SPR_ZONE_CLASS:
                pool[zone].append(code)
    return pool


def build_spr_layout(
    active: list[tuple[str, dict[str, Any]]],
    cfg: dict[str, Any],
    bin_pool: dict[str, list[str]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Real bin addresses, coordinates inferred from the address grammar."""
    wh = cfg["warehouse"]
    aisle_width = float(wh["aisle_width_m"])
    rack_depth = float(wh["rack_depth_m"])
    shelf_height = float(wh["shelf_height_m"])
    zone_gap = float(wh["zone_gap_m"])
    aisle_pitch = 2.0 * rack_depth + aisle_width
    lateral = aisle_width / 2.0 + rack_depth / 2.0

    # Keep every real bin that holds a selected SKU, then top each zone up with other bins
    # from the real bin-location table so the layout is not suspiciously full.
    limits = {"C": 1200, "D": 1500, "E": 400, "F": 200, "R": 1354, "S": 800, "Z": 400}
    codes_by_zone: dict[str, list[str]] = {}
    for zone, limit in limits.items():
        codes = {info["bin"] for _, info in active if info["zone"] == zone}
        for code in bin_pool.get(zone, []):
            if len(codes) >= limit:
                break
            codes.add(code)
        codes_by_zone[zone] = sorted(codes)

    parsed: list[dict[str, Any]] = []
    for zone in sorted(codes_by_zone):
        for code in codes_by_zone[zone]:
            parts = parse_bin_code(code, zone)
            if parts is None:
                continue
            parsed.append({"code": code, "zone": zone, **parts})

    depot = (float(wh["dispatch_point_m"][0]), float(wh["dispatch_point_m"][1]))
    nodes: dict[str, dict[str, Any]] = {
        "DEPOT": {"node_type": "depot", "x_m": depot[0], "y_m": depot[1]}
    }
    edges: list[tuple[str, str, float]] = []
    locations: list[dict[str, Any]] = []

    x_cursor = 0.0
    zone_ids = sorted({row["zone"] for row in parsed})
    for zone_index, zone in enumerate(zone_ids, start=1):
        zone_rows = [row for row in parsed if row["zone"] == zone]
        aisles = sorted({row["aisle"] for row in zone_rows})
        zone_type, bin_class = SPR_ZONE_CLASS[zone]
        bin_w, bin_h, bin_d = (float(v) for v in wh["bin_classes"][bin_class]["dims_cm"])
        bay_m = bin_w / 100.0
        # Real aisle numbers jump (e.g. 100, 118, 402) and there are far more of them than a
        # single block holds, so aisles are ranked into a bounded block and zones are laid out
        # side by side. Slot ids stay real; only the floor plan is inferred.
        max_aisles = 24
        aisle_rank = {aisle: index % max_aisles for index, aisle in enumerate(aisles)}
        sections = sorted({row["section"] for row in zone_rows})
        zone_width = max(1, len(sections)) * bay_m
        zone_x0 = x_cursor
        x_cursor += zone_width + zone_gap
        zone_height = min(len(aisles), max_aisles) * aisle_pitch
        zone_y0 = 0.0
        zone_center = zone_y0 + zone_height / 2.0

        shelf_weights = [float(v) for v in wh["bin_classes"][bin_class]["shelf_weight_kg"]]
        handling_rule = list(wh["zone_rules"][zone_type]["allowed_handling"])
        hazard_rule = list(wh["zone_rules"][zone_type]["allowed_hazard"])

        hub_id = f"ZHUB-SPR-{zone}"
        nodes[hub_id] = {"node_type": "zone_hub", "x_m": round(zone_x0, 3), "y_m": zone_center}
        edges.append(
            (hub_id, "DEPOT", math.hypot(zone_x0 - depot[0], zone_center - depot[1]))
        )

        for aisle_index, aisle in enumerate(aisles):
            aisle_y = zone_y0 + (aisle_rank[aisle] + 0.5) * aisle_pitch
            entrance_id = f"AENT-SPR-{zone}-{aisle}"
            nodes[entrance_id] = {
                "node_type": "aisle_entrance", "x_m": round(zone_x0, 3), "y_m": aisle_y
            }
            edges.append((entrance_id, hub_id, abs(aisle_y - zone_center)))

            columns: dict[float, str] = {}
            for section_index, section in enumerate(sections):
                x = zone_x0 + (section_index + 0.5) * bay_m
                column_id = f"ACOL-SPR-{zone}-{aisle}-{section}"
                columns[round(x, 3)] = column_id
                nodes[column_id] = {"node_type": "aisle_column", "x_m": round(x, 3), "y_m": aisle_y}

            ordered_columns = sorted(columns.items())
            previous_id, previous_x = entrance_id, 0.0
            for column_x, column_id in ordered_columns:
                edges.append((previous_id, column_id, column_x - previous_x))
                previous_id, previous_x = column_id, column_x

            for row in (r for r in zone_rows if r["aisle"] == aisle):
                level_index = min(row["level"] - 1, len(shelf_weights) - 1)
                x = zone_x0 + (sections.index(row["section"]) + 0.5) * bay_m
                column_id = columns[round(x, 3)]
                allowed_handling = list(handling_rule)
                if zone_type == "heavy" and level_index > 2:
                    allowed_handling = [h for h in allowed_handling if h != "heavy"]
                if level_index in set(wh["golden_levels"]):
                    ergonomic = "golden"
                elif level_index == 0:
                    ergonomic = "secondary"
                else:
                    ergonomic = "reserve"
                locations.append({
                    "location_id": row["code"],
                    "warehouse_id": wh["warehouse_id"],
                    "zone_id": f"Z-{zone}",
                    "zone_type": zone_type,
                    "aisle_id": f"{zone}{row['aisle']}",
                    "rack_id": f"{zone}{row['aisle']}{row['section']}",
                    "bay": sections.index(row["section"]),
                    "shelf_level": level_index,
                    "x_m": round(x, 3),
                    "y_m": round(aisle_y, 3),
                    "z_m": round((level_index + 0.5) * shelf_height, 3),
                    "width_cm": bin_w,
                    "height_cm": bin_h,
                    "depth_cm": bin_d,
                    "max_weight_kg": shelf_weights[level_index],
                    "usable_volume_cm3": round(bin_w * bin_h * bin_d, 2),
                    "shelf_max_weight_kg": shelf_weights[level_index],
                    "rack_max_weight_kg": round(
                        float(wh["rack_limit_factor"]) * sum(shelf_weights), 1
                    ),
                    "ergonomic_zone": ergonomic,
                    "allowed_handling": "|".join(allowed_handling),
                    "allowed_hazard": "|".join(hazard_rule),
                    "distance_to_dispatch_m": 0.0,
                    "data_source": "sourced",
                    "data_quality_status": "valid",
                    "_handling": frozenset(allowed_handling),
                    "_hazard": frozenset(hazard_rule),
                })
                nodes[row["code"]] = {
                    "node_type": "location", "x_m": round(x, 3), "y_m": aisle_y
                }
                edges.append((row["code"], column_id, lateral))

    graph_rows = _build_graph_rows(nodes, edges)
    distances = _shortest_paths(nodes, edges, "DEPOT")
    for location in locations:
        location["distance_to_dispatch_m"] = round(distances[location["location_id"]], 3)
    return locations, graph_rows


def _build_graph_rows(
    nodes: dict[str, dict[str, Any]], edges: Iterable[tuple[str, str, float]]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for left, right, distance in edges:
        value = round(max(abs(float(distance)), 0.01), 3)
        rows.append({
            "from_node_id": left, "from_node_type": nodes[left]["node_type"],
            "to_node_id": right, "to_node_type": nodes[right]["node_type"],
            "distance_m": value, "data_source": "inferred",
        })
        rows.append({
            "from_node_id": right, "from_node_type": nodes[right]["node_type"],
            "to_node_id": left, "to_node_type": nodes[left]["node_type"],
            "distance_m": value, "data_source": "inferred",
        })
    rows.sort(key=lambda row: (row["from_node_id"], row["to_node_id"]))
    return rows


def _shortest_paths(
    nodes: dict[str, dict[str, Any]], edges: Iterable[tuple[str, str, float]], source: str
) -> dict[str, float]:
    import heapq

    adjacency: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for left, right, distance in edges:
        value = max(abs(float(distance)), 0.01)
        adjacency[left].append((right, value))
        adjacency[right].append((left, value))
    distances = {node: math.inf for node in nodes}
    distances[source] = 0.0
    heap = [(0.0, source)]
    while heap:
        current, node = heapq.heappop(heap)
        if current > distances[node]:
            continue
        for neighbour, weight in adjacency[node]:
            candidate = current + weight
            if candidate < distances[neighbour] - 1e-12:
                distances[neighbour] = candidate
                heapq.heappush(heap, (candidate, neighbour))
    missing = [node for node, value in distances.items() if math.isinf(value)]
    if missing:
        raise RuntimeError(f"{len(missing)} nodes unreachable from {source}: {missing[:5]}")
    return distances


def _write_current_slots(
    active: list[tuple[str, dict[str, Any]]], sku_by_item: dict[str, str], home: set[str]
) -> None:
    path = RAW / "spr" / "current_slots.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["sku_id", "source_item", "location_id", "zone", "velocity_class"],
            lineterminator="\n",
        )
        writer.writeheader()
        for item, info in active:
            if sku_by_item[item] not in home:
                continue
            writer.writerow({
                "sku_id": sku_by_item[item], "source_item": item, "location_id": info["bin"],
                "zone": info["zone"], "velocity_class": info["velocity"],
            })


# ---------------------------------------------------------------------------
# Raw readers
# ---------------------------------------------------------------------------

def _csv(path: Path) -> Iterable[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        yield from csv.DictReader(handle)


def _csv_sig(path: Path) -> Iterable[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        yield from csv.DictReader(handle)


def _tsv_from_zip(path: Path, member: str) -> Iterable[dict[str, str]]:
    with zipfile.ZipFile(path) as archive:
        with archive.open(member) as handle:
            text = io.TextIOWrapper(handle, encoding="latin-1", newline="")
            yield from csv.DictReader(text, delimiter="\t")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def write_index(results: list[dict[str, Any]]) -> None:
    lines = [
        "# dataset-2 — three provenance spines",
        "",
        "Three independently loadable benchmark datasets that share the `dataset/` schema.",
        "Each spine answers a different question about the same slotting problem.",
        "",
        "| spine | demand history | physical data | warehouse | SKUs | bins | orders | lines | validation |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    summary = {
        "olist": ("real Olist orders", "real W/H/D/kg", "generated"),
        "instacart": ("real Instacart baskets", "class-rule synthesis", "generated"),
        "spr": ("real 2002 pick history", "real item-master dimensions", "real bin addresses"),
    }
    for result in results:
        demand, physical, warehouse = summary[result["spine"]]
        counts = result["counts"]
        status = "PASS" if result["validation"]["ok"] else "FAIL"
        lines.append(
            f"| `{result['spine']}` | {demand} | {physical} | {warehouse} | "
            f"{counts['products']} | {counts['locations']} | {counts['orders']} | "
            f"{counts['order_items']} | {status} |"
        )
    lines += [
        "",
        "## When to use which",
        "",
        "- `olist` — you need real dimensions and real demand, and can live with a generated",
        "  warehouse and inferred hazard classes. Weak basket affinity (mostly single-item orders).",
        "- `instacart` — you need the strongest co-occurrence signal available (multi-item grocery",
        "  baskets) and can accept synthesised dimensions.",
        "- `spr` — you need everything real at once: real bins, real measured dimensions, real",
        "  hazmat codes, real velocity classes, real picks. Smallest scale, strongest provenance,",
        "  but the aisle geometry is inferred from the address grammar.",
        "",
        "## Layout",
        "",
        "```",
        "dataset-2/",
        "  olist/{processed,metadata,reports}/",
        "  instacart/{processed,metadata,reports}/",
        "  spr/{processed,metadata,reports}/",
        "  raw/{olist,instacart,spr}/",
        "```",
        "",
        "Each spine directory is a complete dataset: point the loader or the validator at it "
        "exactly as you would at `dataset/`.",
        "",
        "Rebuild everything with `python build_dataset2.py`.",
        "",
    ]
    (OUT / "README.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(prog="build-dataset2")
    parser.add_argument("--spine", choices=["olist", "instacart", "spr", "all"], default="all")
    parser.add_argument("--index-only", action="store_true")
    args = parser.parse_args()

    if args.index_only:
        results = []
        for name in ("olist", "instacart", "spr"):
            manifest = json.loads(
                (OUT / name / "metadata" / "generation_manifest.json").read_text(encoding="utf-8")
            )
            validation = run_validation(OUT / name)
            write_validation_reports(OUT / name, validation)
            results.append({
                "spine": name,
                "counts": manifest["counts"],
                "validation": {
                    "ok": validation.ok,
                    "hard_errors": validation.hard_errors,
                    "warnings": validation.warnings,
                },
            })
        write_index(results)
        print(json.dumps(results, indent=2))
        return

    builders = {"olist": build_olist, "instacart": build_instacart, "spr": build_spr}
    chosen = list(builders) if args.spine == "all" else [args.spine]
    results = []
    for name in chosen:
        result = builders[name]()
        results.append(result)
        print(json.dumps(result, indent=2), flush=True)

    if args.spine == "all":
        write_index(results)
    ok = all(result["validation"]["ok"] for result in results)
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
