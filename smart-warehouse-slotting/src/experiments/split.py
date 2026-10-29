"""Leakage-safe fit/holdout split of the demand history (Phase 3, D46).

Design
------
Split unit: **order**, not order line. A basket's lines share one picking trip; if
two lines of the same order landed on opposite sides of the split, the holdout
workload would contain a fragment of a basket the fit side also saw.

Ordering: by ``order_timestamp`` then ``order_id``, so the split is **temporal**
(fit = earlier history, holdout = later history). A random split would leak the
future into the past: a layout fitted on orders from week 20 and evaluated on week
3 is not a forecast, it is interpolation. The split is deterministic without a seed
because time ordering is a total order here.

What is split and what is not
-----------------------------
Split: ``orders`` (scenario rewritten to ``<SCENARIO>_FIT`` / ``<SCENARIO>_HOLDOUT``),
``order_items`` (filtered to the view's orders), and the two derived demand tables
(``demand_summary``, ``sku_affinity``) which are **recomputed per view** so the fit
view cannot contain holdout demand.

Not split (deliberately): ``warehouse``, ``categories``, ``products``, ``locations``,
``inventory``, ``compatibility_rules``, ``storage_assignments_baseline``,
``location_graph``. These describe the physical problem — the warehouse does not
change between the two halves of a year, and splitting them would manufacture two
different warehouses.

Every view is a **complete tree**, not an orders-only slice: analytics key on
``scenario_id``, so a slice would leave ``demand_summary`` describing the whole
history and the optimizer would see holdout demand.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src.data_processing.derive import build_affinity, build_demand_summary

STATIC_TABLES = (
    "warehouses",
    "categories",
    "products",
    "locations",
    "inventory",
    "compatibility_rules",
    "storage_assignments_baseline",
    "location_graph",
)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _rows(df: pd.DataFrame) -> list[dict]:
    return df.to_dict(orient="records")


def build_split(
    processed: Path,
    out_root: Path,
    name: str = "A70",
    fraction: float = 0.7,
    scenario: str = "A",
) -> dict:
    """Write ``<out_root>/<name>/{fit,holdout}/processed`` and a manifest.

    Returns the manifest dict (also written to ``<out_root>/<name>/split_manifest.json``).
    """
    if not (0.0 < fraction < 1.0):
        raise ValueError("fraction must be strictly between 0 and 1")

    processed = Path(processed)
    out_root = Path(out_root)
    scenario = scenario.upper()
    fit_scenario = f"{scenario}_FIT"
    holdout_scenario = f"{scenario}_HOLDOUT"

    orders = pd.read_csv(processed / "orders.csv")
    order_items = pd.read_csv(processed / "order_items.csv")
    products = pd.read_csv(processed / "products.csv")

    scoped = orders[orders["scenario_id"] == scenario].copy()
    if scoped.empty:
        raise ValueError(f"scenario {scenario} has no orders in {processed}")

    # Order-level temporal split.
    scoped["_ts"] = pd.to_datetime(scoped["order_timestamp"], utc=True)
    scoped = scoped.sort_values(["_ts", "order_id"], kind="mergesort").reset_index(drop=True)
    n_orders = len(scoped)
    cut = int(round(n_orders * fraction))
    if cut <= 0 or cut >= n_orders:
        raise ValueError(f"split of {n_orders} orders at {fraction} leaves an empty side")

    fit_orders = scoped.iloc[:cut].drop(columns=["_ts"])
    hold_orders = scoped.iloc[cut:].drop(columns=["_ts"])
    scoped_order_ids = set(scoped["order_id"])
    n_lines_input = int(len(order_items[order_items["order_id"].isin(scoped_order_ids)]))

    views = {
        "fit": (fit_orders, fit_scenario),
        "holdout": (hold_orders, holdout_scenario),
    }

    written: dict[str, dict] = {}
    for view, (view_orders, view_scenario) in views.items():
        view_orders = view_orders.copy()
        view_orders["scenario_id"] = view_scenario
        view_ids = set(view_orders["order_id"])
        view_items = order_items[order_items["order_id"].isin(view_ids)].copy()

        target = out_root / name / view / "processed"
        target.mkdir(parents=True, exist_ok=True)

        for table in STATIC_TABLES:
            src = processed / f"{table}.csv"
            if src.exists():
                pd.read_csv(src).to_csv(target / f"{table}.csv", index=False)

        view_orders.to_csv(target / "orders.csv", index=False)
        view_items.to_csv(target / "order_items.csv", index=False)

        # Recompute demand tables for this view only — this is the leakage fix.
        demand_rows = build_demand_summary(_rows(products), _rows(view_orders), _rows(view_items))
        affinity_rows = build_affinity(_rows(products), _rows(view_orders), _rows(view_items))
        pd.DataFrame(demand_rows).to_csv(target / "demand_summary.csv", index=False)
        pd.DataFrame(affinity_rows).to_csv(target / "sku_affinity.csv", index=False)

        written[view] = {
            "path": str(target),
            "scenario_id": view_scenario,
            "orders": int(len(view_orders)),
            "lines": int(len(view_items)),
            "skus_with_demand": int(view_items["sku_id"].nunique()),
            "first_order_utc": str(pd.to_datetime(view_orders["order_timestamp"], utc=True).min()),
            "last_order_utc": str(pd.to_datetime(view_orders["order_timestamp"], utc=True).max()),
            "sha256": {
                name_: _sha256(target / f"{name_}.csv")
                for name_ in ("orders", "order_items", "demand_summary", "sku_affinity")
            },
        }

    manifest = {
        "schema": "phase3.split_manifest/1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "method": "temporal_order_level",
        "split_unit": "order",
        "scenario": scenario,
        "fraction_fit": fraction,
        "seed": None,
        "seed_note": "temporal split is deterministic; no random seed is used",
        "input": {
            "processed": str(processed),
            "sha256": {
                t: _sha256(processed / f"{t}.csv")
                for t in ("orders", "order_items", "products", "inventory", "locations")
                if (processed / f"{t}.csv").exists()
            },
        },
        "views": written,
        "integrity": {
            "orders_total_input": int(n_orders),
            "orders_fit_plus_holdout": int(written["fit"]["orders"] + written["holdout"]["orders"]),
            "lines_total_input": n_lines_input,
            "lines_fit_plus_holdout": int(written["fit"]["lines"] + written["holdout"]["lines"]),
            "disjoint": True,
            "note": "disjointness is enforced by slicing one ordered frame; verified in verify_split()",
        },
    }

    out_root.joinpath(name).mkdir(parents=True, exist_ok=True)
    manifest_path = out_root / name / "split_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    manifest["manifest_path"] = str(manifest_path)
    return manifest


def verify_split(manifest: dict) -> dict:
    """Re-read the written trees and assert the leakage guarantees.

    Checks: order ids disjoint, union equals the input population, line counts match
    the source, every line's order is present in the same view, and the scenario ids
    are rewritten as expected.
    """
    if "manifest_path" in manifest:
        root = Path(manifest["manifest_path"]).parent
    else:
        # A manifest read from disk does not carry the in-memory path; derive the
        # split root from the fit view it records.
        root = Path(manifest["views"]["fit"]["path"]).parent.parent
    fit = pd.read_csv(root / "fit" / "processed" / "orders.csv")
    hold = pd.read_csv(root / "holdout" / "processed" / "orders.csv")
    fit_items = pd.read_csv(root / "fit" / "processed" / "order_items.csv")
    hold_items = pd.read_csv(root / "holdout" / "processed" / "order_items.csv")

    fit_ids, hold_ids = set(fit["order_id"]), set(hold["order_id"])
    checks = {
        "disjoint_orders": not (fit_ids & hold_ids),
        "union_equals_input": len(fit_ids | hold_ids) == manifest["integrity"]["orders_total_input"],
        "fit_scenario_rewritten": set(fit["scenario_id"]) == {manifest["views"]["fit"]["scenario_id"]},
        "holdout_scenario_rewritten": set(hold["scenario_id"]) == {manifest["views"]["holdout"]["scenario_id"]},
        "fit_lines_belong_to_fit_orders": set(fit_items["order_id"]) <= fit_ids,
        "holdout_lines_belong_to_holdout_orders": set(hold_items["order_id"]) <= hold_ids,
        "no_line_in_both_views": not (set(zip(fit_items["order_id"], fit_items["sku_id"]))
                                      & set(zip(hold_items["order_id"], hold_items["sku_id"]))),
        "line_counts_match_manifest": (
            len(fit_items) == manifest["views"]["fit"]["lines"]
            and len(hold_items) == manifest["views"]["holdout"]["lines"]
        ),
        "line_union_equals_input": (
            len(fit_items) + len(hold_items)
            == manifest["integrity"].get("lines_total_input")
        ),
        "no_duplicate_order_sku_lines": (
            not fit_items.duplicated(["order_id", "sku_id"]).any()
            and not hold_items.duplicated(["order_id", "sku_id"]).any()
        ),
    }
    checks["all_passed"] = all(checks.values())
    return checks
