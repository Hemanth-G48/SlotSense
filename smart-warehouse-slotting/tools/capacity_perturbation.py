"""Phase 6 capacity perturbation audit on the frozen optimized layout.

The canonical dataset is never modified. The script:
1. validates the frozen optimized layout against the canonical inventory;
2. identifies the tightest bin-weight and bin-volume bins from the Phase 4 headroom table;
3. applies a one-unit inventory-only perturbation and a one-unit layout+inventory
   perturbation to a copy, re-validating each time.

The expected result is a hard-constraint failure, not a silently accepted layout. Output:
``outputs/phase6/capacity_perturbation.json``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.models.entities import StorageAssignment
from src.validation.loader import (
    load_assignments,
    load_compatibility_rules,
    load_inventory,
    load_skus,
    load_warehouse_from_locations,
)
from src.validation.validator import Validator

DATASET = PROJECT_ROOT.parent / "dataset" / "processed"
OPTIMIZED = PROJECT_ROOT / "outputs" / "phase3" / "optimized_fit" / "optimized_assignments.csv"
HEADROOM = PROJECT_ROOT / "outputs" / "phase4" / "phase4_headroom.csv"


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _build():
    locations = pd.read_csv(DATASET / "locations.csv")
    products = pd.read_csv(DATASET / "products.csv")
    rules = pd.read_csv(DATASET / "compatibility_rules.csv")
    inventory = pd.read_csv(DATASET / "inventory.csv")
    wh = load_warehouse_from_locations(locations)
    skus = load_skus(products)
    comp = load_compatibility_rules(rules)
    inv = load_inventory(inventory)

    def validator_for(overrides: dict[str, int] | None = None) -> Validator:
        return Validator(
            skus,
            wh,
            comp,
            inventory=overrides if overrides is not None else inv,
            separation_radius_m=10.0,
        )

    return validator_for, inv


def _violations(result) -> list[dict]:
    return [
        {
            "rule_id": v.rule_id,
            "reason": v.reason,
            "severity": str(v.severity),
            "location_id": v.location_id,
            "sku_id": v.sku_id,
        }
        for v in result.violations
    ]


def main() -> None:
    global DATASET, OPTIMIZED, HEADROOM
    ap = argparse.ArgumentParser(prog="capacity_perturbation")
    ap.add_argument("--out", default=str(PROJECT_ROOT / "outputs" / "phase6" / "capacity_perturbation.json"))
    ap.add_argument("--dataset", default=str(DATASET))
    ap.add_argument("--optimized", default=str(OPTIMIZED))
    ap.add_argument("--headroom", default=str(HEADROOM))
    args = ap.parse_args()

    DATASET = Path(args.dataset).resolve()
    OPTIMIZED = Path(args.optimized).resolve()
    HEADROOM = Path(args.headroom).resolve()

    validator_for, inventory = _build()
    assignments = load_assignments(pd.read_csv(OPTIMIZED))
    baseline_result = validator_for().validate(assignments)
    headroom = pd.read_csv(HEADROOM)
    opt = headroom[headroom["layout"] == "optimized_fit"]
    tight_weight = opt[opt["scope"] == "bin_weight"].iloc[0]
    tight_volume = opt[opt["scope"] == "bin_volume"].iloc[0]

    cases = []
    for label, row in (("bin_weight", tight_weight), ("bin_volume", tight_volume)):
        loc_id = row["limiting_location"]
        at_bin = [a for a in assignments if a.location_id == loc_id]
        if not at_bin:
            cases.append({"scope": label, "location": loc_id, "error": "no assignment at limiting bin"})
            continue
        sku_id = at_bin[0].sku_id

        # Case 1: more on-hand stock, same layout. The layout can no longer represent the
        # inventory, so the gate must reject it (conservation, even if capacity happened to fit).
        inv_only = dict(inventory)
        inv_only[sku_id] = inv_only.get(sku_id, 0) + 1
        v_inv_only = validator_for(inv_only).validate(assignments)

        # Case 2: add the unit to the tightest bin and to inventory. This isolates a real
        # capacity failure from a pure conservation failure.
        bumped = []
        seen = False
        for a in assignments:
            if not seen and a.location_id == loc_id and a.sku_id == sku_id:
                bumped.append(
                    StorageAssignment(a.sku_id, a.location_id, a.assigned_quantity + 1, a.assignment_type)
                )
                seen = True
            else:
                bumped.append(a)
        inv_and_layout = dict(inv_only)
        v_capacity = validator_for(inv_and_layout).validate(bumped)

        cases.append(
            {
                "scope": label,
                "location": loc_id,
                "sku_id": sku_id,
                "reported_utilization_pct": float(row["max_utilization_pct"]),
                "reported_observed": float(row["observed"]),
                "reported_limit": float(row["limit"]),
                "inventory_only": {
                    "feasible": v_inv_only.is_feasible,
                    "n_violations": len(v_inv_only.violations),
                    "rules": sorted({v.rule_id for v in v_inv_only.violations}),
                },
                "inventory_plus_layout": {
                    "feasible": v_capacity.is_feasible,
                    "n_violations": len(v_capacity.violations),
                    "rules": sorted({v.rule_id for v in v_capacity.violations}),
                    "violations": _violations(v_capacity),
                },
            }
        )

    payload = {
        "schema": "phase6.capacity_perturbation/1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "inputs": {
            "dataset": str(DATASET),
            "optimized_layout": str(OPTIMIZED),
            "optimized_layout_sha256": _sha(OPTIMIZED),
            "headroom_artifact": str(HEADROOM),
            "headroom_sha256": _sha(HEADROOM),
        },
        "baseline": {
            "feasible": baseline_result.is_feasible,
            "n_violations": len(baseline_result.violations),
            "units": sum(a.assigned_quantity for a in assignments),
        },
        "perturbations": cases,
        "interpretation": (
            "A feasible baseline plus infeasible one-unit perturbations means the hard gate, not a "
            "dashboard warning, is what prevents publication. The canonical dataset was not modified."
        ),
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
