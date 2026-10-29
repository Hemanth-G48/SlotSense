"""Independent verification of Phase 5 artifacts.

Recomputes, from the recorded CSV/JSON outputs rather than from the runner's summary:

* D37 travel invariance and per-batch cycle identity under both timing bases.
* Pick-time units: line basis pays lines, stop basis pays distinct stops.
* Paired-seed layout hashes, inventory conservation, feasibility, paired deltas.
* Descriptive statistics (mean, sample SD, median, IQR) and unique-layout count.
* Provenance output hashes.

The validator is rebuilt from the fit dataset, not trusted from the runner's record.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
from pathlib import Path

import numpy as np
import pandas as pd

from src.models.entities import AssignmentType, StorageAssignment
from src.validation.loader import (
    load_compatibility_rules,
    load_inventory,
    load_skus,
    load_warehouse_from_locations,
)
from src.validation.validator import Validator

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FIT_TREE = (
    Path(os.environ.get("PHASE3_DIR", PROJECT_ROOT / "outputs" / "phase3"))
    / "split" / "A70" / "fit" / "processed"
)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _validator():
    locations = pd.read_csv(FIT_TREE / "locations.csv")
    products = pd.read_csv(FIT_TREE / "products.csv")
    rules = pd.read_csv(FIT_TREE / "compatibility_rules.csv")
    inventory_rows = pd.read_csv(FIT_TREE / "inventory.csv")
    return (
        Validator(
            load_skus(products),
            load_warehouse_from_locations(locations),
            load_compatibility_rules(rules),
            inventory=load_inventory(inventory_rows),
            separation_radius_m=10.0,
        ),
        load_inventory(inventory_rows),
    )


def _check_layout(path: Path, validator, inventory: dict) -> dict:
    frame = pd.read_csv(path)
    assignments = [
        StorageAssignment(r.sku_id, r.location_id, int(r.assigned_quantity), AssignmentType.OPTIMIZED)
        for r in frame.itertuples(index=False)
    ]
    result = validator.validate(assignments)
    placed = frame.groupby("sku_id")["assigned_quantity"].sum().astype(int)
    required = pd.Series(inventory, dtype="int64")
    joined = pd.concat([required.rename("required"), placed.rename("placed")], axis=1).fillna(0)
    return {
        "feasible": bool(result.is_feasible),
        "n_violations": len(result.violations),
        "units": int(frame["assigned_quantity"].sum()),
        "units_required": int(required.sum()),
        "inventory_conserved": bool(
            (joined["required"].astype("int64") == joined["placed"].astype("int64")).all()
            and int(frame["assigned_quantity"].sum()) == int(required.sum())
        ),
        "duplicate_pairs": int(frame.duplicated(["sku_id", "location_id"]).sum()),
    }


def _describe(values: list[float]) -> dict:
    arr = np.asarray(values, dtype=float)
    return {
        "n": int(arr.size),
        "mean": round(float(arr.mean()), 4),
        "sd": round(float(arr.std(ddof=1)), 4) if arr.size > 1 else None,
        "median": round(float(np.median(arr)), 4),
        "iqr": round(float(np.percentile(arr, 75) - np.percentile(arr, 25)), 4),
        "min": round(float(arr.min()), 4),
        "max": round(float(arr.max()), 4),
    }


def verify(out_root: Path) -> dict:
    out_root = Path(out_root)
    p = json.loads((out_root / "phase5_experiments.json").read_text())
    checks: list[dict] = []

    def add(name: str, passed: bool, detail: str = "") -> None:
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    # ---------------------------------------------------------------- D37
    d37 = p["d37"]
    summaries: dict[tuple[str, str], dict] = {}
    for basis in ("order_line", "stop"):
        routes = pd.read_csv(out_root / "d37" / basis / "pick_routes.csv")
        summary = json.loads((out_root / "d37" / basis / "evaluation_summary.json").read_text())
        for layout in ("baseline", "optimized"):
            sub = routes[routes["layout"] == layout]
            recomputed_distance = round(float(sub["distance_m"].sum()), 2)
            recomputed_cycle = round(float(sub["cycle_time_sec"].sum()), 2)
            reported = summary[layout]
            summaries[(basis, layout)] = reported
            add(
                f"d37_{basis}_{layout}_route_sums",
                abs(recomputed_distance - reported["total_travel_distance_m"]) <= 0.01
                and abs(recomputed_cycle - reported["total_route_time_sec"]) <= 0.01
                and int(sub["n_orders"].sum()) == int(reported["total_orders"]),
                f"{recomputed_distance} m, {recomputed_cycle} s",
            )
            identity = np.allclose(
                sub["cycle_time_sec"],
                sub["travel_time_sec"] + sub["pick_time_sec"] + 10.0,
                atol=1e-6,
            )
            add(f"d37_{basis}_{layout}_cycle_identity", bool(identity))

        # The pick-time unit must be exactly the published line or stop count.
        basis_total = (
            summaries[(basis, "baseline")]["total_pick_lines"]
            if basis == "order_line"
            else summaries[(basis, "baseline")]["total_pick_stops"]
        )
        pick_units = summaries[(basis, "baseline")]["total_pick_time_sec"] / 8.0
        add(
            f"d37_{basis}_pick_units",
            abs(pick_units - basis_total) < 1e-6,
            f"pick_units={pick_units}, published={basis_total}",
        )

    add("d37_travel_unchanged", d37["travel_unchanged"] is True)
    for layout in ("baseline", "optimized"):
        add(
            f"d37_{layout}_travel_identical",
            abs(
                summaries[("order_line", layout)]["total_travel_distance_m"]
                - summaries[("stop", layout)]["total_travel_distance_m"]
            )
            <= 0.01,
        )
        add(
            f"d37_{layout}_setup_identical",
            abs(
                summaries[("order_line", layout)]["total_setup_time_sec"]
                - summaries[("stop", layout)]["total_setup_time_sec"]
            )
            <= 0.01,
        )

    # ---------------------------------------------------------------- seeds
    seeds = p["paired_seeds"]
    validator, inventory = _validator()
    validated: dict[str, dict] = {}
    ok = [r for r in seeds["records"] if r["status"] == "ok"]
    for record in ok:
        seed_dir = out_root / "seeds" / f"seed_{record['seed']}"
        layout_path = seed_dir / "optimized_assignments.csv"
        actual_hash = _sha256(layout_path)
        add(
            f"seed_{record['seed']}_layout_hash",
            actual_hash == record["layout_sha256"],
            actual_hash[:12],
        )
        if actual_hash not in validated:
            validated[actual_hash] = _check_layout(layout_path, validator, inventory)
        check = validated[actual_hash]
        add(
            f"seed_{record['seed']}_feasible",
            check["feasible"] and check["n_violations"] == 0,
            f"violations={check['n_violations']}",
        )
        add(
            f"seed_{record['seed']}_inventory",
            check["inventory_conserved"] and check["duplicate_pairs"] == 0,
            f"units={check['units']}, duplicates={check['duplicate_pairs']}",
        )
        add(
            f"seed_{record['seed']}_fit_matches_layout",
            record["n_assignments"] == int(pd.read_csv(layout_path).shape[0]),
        )

    add("seed_count", seeds["summary"]["n_declared"] == len(seeds["seeds"]) == 5)
    add("seed_all_successful", len(ok) == 5 and seeds["summary"]["n_failed"] == 0)
    unique = len({r["layout_sha256"] for r in ok})
    add("seed_unique_layouts", unique == seeds["summary"]["unique_layouts"])
    add("seed_all_feasible", all(r["validation"]["feasible"] for r in ok))
    add("seed_all_inventory_conserved", all(r["validation"]["inventory_conserved"] for r in ok))

    for record in ok:
        base, opt = record["baseline"], record["optimized"]
        recomputed_travel = round(opt["total_travel_distance_m"] - base["total_travel_distance_m"], 3)
        recomputed_pct = round(recomputed_travel / base["total_travel_distance_m"] * 100.0, 4)
        add(
            f"seed_{record['seed']}_paired_delta",
            abs(recomputed_travel - record["travel_delta_m"]) <= 1e-6
            and abs(recomputed_pct - record["travel_delta_pct"]) <= 1e-6,
            f"{recomputed_pct}%",
        )

    for key, values in (
        ("travel_pct", [r["travel_delta_pct"] for r in ok]),
        ("cycle_s", [r["cycle_delta_s"] for r in ok]),
        ("throughput", [r["throughput_delta"] for r in ok]),
    ):
        recomputed = _describe(values)
        reported = seeds["summary"]["paired_delta"][
            "throughput_orders_per_hr" if key == "throughput" else key
        ]
        add(
            f"seed_stats_{key}",
            recomputed["mean"] == reported["mean"]
            and recomputed["sd"] == reported["sd"]
            and recomputed["median"] == reported["median"],
            f"mean={recomputed['mean']}, sd={recomputed['sd']}",
        )

    # ---------------------------------------------------------------- provenance
    manifest = json.loads((out_root / "provenance.json").read_text())
    outputs = manifest.get("outputs") or {}
    bad = []
    for name, meta in outputs.items():
        path = Path(meta["path"] if isinstance(meta, dict) else meta)
        expected = meta.get("sha256") if isinstance(meta, dict) else None
        if not path.exists() or (expected and _sha256(path) != expected):
            bad.append(name)
    add("provenance_output_hashes", not bad, f"bad={bad[:5]}")
    add(
        "provenance_phase3_layouts",
        _sha256(Path(os.environ.get("PHASE3_DIR", PROJECT_ROOT / "outputs" / "phase3")) / "optimized_fit" / "optimized_assignments.csv")
        == p["phase3"]["optimized_sha256"]
        and _sha256(Path(os.environ.get("PHASE3_DIR", PROJECT_ROOT / "outputs" / "phase3")) / "optimized_fit" / "baseline_repaired_assignments.csv")
        == p["phase3"]["baseline_sha256"],
    )

    result = {
        "schema": "phase5.verification/1",
        "all_passed": all(c["passed"] for c in checks),
        "n_checks": len(checks),
        "n_failed": sum(1 for c in checks if not c["passed"]),
        "checks": checks,
    }
    (out_root / "verification.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main() -> None:
    ap = argparse.ArgumentParser(prog="verify_phase5")
    ap.add_argument("--out", default=str(PROJECT_ROOT / "outputs" / "phase5"))
    args = ap.parse_args()
    result = verify(Path(args.out))
    print(json.dumps({k: result[k] for k in ("all_passed", "n_checks", "n_failed")}, indent=2))
    for c in result["checks"]:
        if not c["passed"]:
            print(f"FAIL {c['name']}: {c['detail']}")
    raise SystemExit(0 if result["all_passed"] else 1)


if __name__ == "__main__":
    main()
