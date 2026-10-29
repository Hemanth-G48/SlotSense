"""Phase 5 runner: D37 timing-model comparison and paired-seed robustness.

Workstreams
-----------
D37
    The same frozen layouts and holdout workload are simulated under two pick-time
    definitions: ``order_line`` (the Phase 2/3 default) and ``stop`` (distinct physical
    picking stops per batch). Travel must be identical; only cycle time and throughput
    may move.

Paired seeds
    The optimizer's only random source is simulated annealing. Each predeclared seed
    produces a fit layout on ``A_FIT``; the layout is validated, hashed and evaluated on
    the same ``A_HOLDOUT`` workload. The repaired baseline is fixed across pairs.
    The study measures optimizer variability, not simulation variability (the simulator
    is deterministic).

Everything lands in ``outputs/phase5/``; Phase 3/4 artifacts are read-only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from src.evaluation.fairness import workload_identity
from src.experiments.provenance import build_manifest
from src.experiments.split import verify_split
from src.models.config import Config
from src.models.entities import AssignmentType, StorageAssignment
from src.optimization.baseline import prepare_baseline_variant
from src.optimization.pipeline import run_phase5
from src.simulation.pipeline import run_phase6
from src.validation.loader import (
    load_compatibility_rules,
    load_inventory,
    load_skus,
    load_warehouse_from_locations,
)
from src.validation.validator import Validator

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PHASE3 = Path(os.environ.get("PHASE3_DIR", PROJECT_ROOT / "outputs" / "phase3")).resolve()
PHASE4 = Path(os.environ.get("PHASE4_DIR", PROJECT_ROOT / "outputs" / "phase4")).resolve()
FIT_TREE = PHASE3 / "split" / "A70" / "fit" / "processed"
HOLDOUT_TREE = PHASE3 / "split" / "A70" / "holdout" / "processed"
BASELINE_LAYOUT = PHASE3 / "optimized_fit" / "baseline_repaired_assignments.csv"
OPTIMIZED_LAYOUT = PHASE3 / "optimized_fit" / "optimized_assignments.csv"
SPLIT_MANIFEST = PHASE3 / "split" / "A70" / "split_manifest.json"

SEEDS = (42, 43, 44, 45, 46)
PICK_TIME_BASES = ("order_line", "stop")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _validator(processed: Path):
    locations = pd.read_csv(processed / "locations.csv")
    products = pd.read_csv(processed / "products.csv")
    rules = pd.read_csv(processed / "compatibility_rules.csv")
    inventory_rows = pd.read_csv(processed / "inventory.csv")
    warehouse = load_warehouse_from_locations(locations)
    skus = load_skus(products)
    compatibility = load_compatibility_rules(rules)
    inventory = load_inventory(inventory_rows)
    validator = Validator(
        skus, warehouse, compatibility, inventory=inventory, separation_radius_m=10.0
    )
    return validator, inventory


def _validate_layout(path: Path, validator, inventory: dict) -> dict:
    frame = pd.read_csv(path)
    assignments = [
        StorageAssignment(r.sku_id, r.location_id, int(r.assigned_quantity), AssignmentType.OPTIMIZED)
        for r in frame.itertuples(index=False)
    ]
    result = validator.validate(assignments)
    placed = frame.groupby("sku_id")["assigned_quantity"].sum().astype(int)
    required = pd.Series(inventory, dtype="int64")
    joined = pd.concat([required.rename("required"), placed.rename("placed")], axis=1).fillna(0)
    mismatches = int(
        (joined["required"].astype("int64") != joined["placed"].astype("int64")).sum()
    )
    return {
        "feasible": bool(result.is_feasible),
        "feasibility_status": "FEASIBLE" if result.is_feasible else "INFEASIBLE",
        "n_violations": len(result.violations),
        "units_placed": int(frame["assigned_quantity"].sum()),
        "units_required": int(required.sum()),
        "inventory_conserved": mismatches == 0
        and int(frame["assigned_quantity"].sum()) == int(required.sum()),
        "skus_mismatched": mismatches,
        "duplicate_pairs": int(frame.duplicated(["sku_id", "location_id"]).sum()),
    }


def _basis_metrics(run: dict, side: str) -> dict:
    m = run[side]
    return {
        "total_travel_distance_m": m["total_travel_distance_m"],
        "total_route_time_sec": m["total_route_time_sec"],
        "throughput_orders_per_hr": m["throughput_orders_per_hr"],
        "avg_time_per_order_sec": m["avg_time_per_order_sec"],
        "total_pick_lines": m.get("total_pick_lines"),
        "total_pick_stops": m.get("total_pick_stops"),
        "total_travel_time_sec": m.get("total_travel_time_sec"),
        "total_pick_time_sec": m.get("total_pick_time_sec"),
        "total_setup_time_sec": m.get("total_setup_time_sec"),
    }


def _describe(values: list[float]) -> dict:
    if not values:
        return {"n": 0}
    arr = np.asarray(values, dtype=float)
    return {
        "n": int(arr.size),
        "mean": round(float(arr.mean()), 4),
        "sd": round(float(arr.std(ddof=1)), 4) if arr.size > 1 else None,
        "median": round(float(np.median(arr)), 4),
        "q1": round(float(np.percentile(arr, 25)), 4),
        "q3": round(float(np.percentile(arr, 75)), 4),
        "iqr": round(float(np.percentile(arr, 75) - np.percentile(arr, 25)), 4),
        "min": round(float(arr.min()), 4),
        "max": round(float(arr.max()), 4),
    }


def _d37(out_root: Path, baseline_variant, baseline_sha: str, optimized_sha: str) -> dict:
    rows = []
    runs: dict[str, dict] = {}
    for basis in PICK_TIME_BASES:
        run = run_phase6(
            processed=HOLDOUT_TREE,
            scenario="A_HOLDOUT",
            out=out_root / "d37" / basis,
            optimized_path=OPTIMIZED_LAYOUT,
            affinity_scenario="A_HOLDOUT",
            baseline_path=BASELINE_LAYOUT,
            baseline_variant="repaired_minimal",
            baseline_note="repaired for feasibility only; frozen from Phase 3",
            routing_strategy="nearest_neighbor",
            batch_size=5,
            pick_time_basis=basis,
        )
        runs[basis] = run
        for side in ("baseline", "optimized"):
            rows.append(
                {
                    "basis": basis,
                    "layout": side,
                    "workload_id": run["workload"]["workload_id"],
                    "feasible": run["feasibility"][side]["is_feasible"],
                    **_basis_metrics(run, side),
                }
            )

    order_line = {r["layout"]: r for r in rows if r["basis"] == "order_line"}
    stop = {r["layout"]: r for r in rows if r["basis"] == "stop"}
    travel_unchanged = all(
        abs(order_line[side]["total_travel_distance_m"] - stop[side]["total_travel_distance_m"])
        <= 0.01
        for side in ("baseline", "optimized")
    )

    def impact(side: str) -> dict:
        line = order_line[side]
        st = stop[side]
        return {
            "layout": side,
            "cycle_line_s": line["total_route_time_sec"],
            "cycle_stop_s": st["total_route_time_sec"],
            "cycle_delta_s": round(st["total_route_time_sec"] - line["total_route_time_sec"], 3),
            "cycle_delta_pct": round(
                (st["total_route_time_sec"] - line["total_route_time_sec"])
                / line["total_route_time_sec"]
                * 100.0,
                3,
            )
            if line["total_route_time_sec"]
            else None,
            "throughput_line": line["throughput_orders_per_hr"],
            "throughput_stop": st["throughput_orders_per_hr"],
            "time_per_order_line_s": line["avg_time_per_order_sec"],
            "time_per_order_stop_s": st["avg_time_per_order_sec"],
        }

    result = {
        "schema": "phase5.d37/1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "workload": runs["order_line"]["workload"],
        "layouts": {
            "baseline_sha256": baseline_sha,
            "optimized_sha256": optimized_sha,
        },
        "definitions": {
            "order_line": "pick time = order lines in the batch × 8.0 s",
            "stop": "pick time = distinct physical bins visited by the batch × 8.0 s",
            "stop_model": "one stop per distinct bin holding any SKU in the batch; multi-line picks at one bin share a stop",
            "cycle": "travel_time + pick_time + setup_time",
        },
        "rows": rows,
        "travel_unchanged": travel_unchanged,
        "impact": {side: impact(side) for side in ("baseline", "optimized")},
        "decision": {
            "authoritative_default": "order_line",
            "stop_status": "configurable sensitivity model",
            "reason": (
                "PROJECT.md defines pick-cycle time as travel + pick + setup but does not define the "
                "pick-time unit. The line model is retained as the compatibility default because every "
                "Phase 2/3/4 figure uses it; the stop model is published as a sensitivity analysis "
                "because ARCHITECTURE §10 describes per-stop charging as the target."
            ),
            "consequence": (
                "Travel is unchanged; cycle time and throughput move because stops differ from lines. "
                "Historical cycle/throughput figures remain line-based and must not be mixed with stop-based values."
            ),
        },
    }
    (out_root / "d37_timing_models.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    pd.DataFrame(rows).to_csv(out_root / "d37_timing_models.csv", index=False)
    return result


def _paired_seeds(out_root: Path, baseline_variant, validator, inventory) -> dict:
    records = []
    for seed in SEEDS:
        seed_dir = out_root / "seeds" / f"seed_{seed}"
        cfg = Config.from_json(PROJECT_ROOT / "configs" / "benchmark.json")
        cfg.dataset.seed = seed
        try:
            summary = run_phase5(
                FIT_TREE,
                cfg,
                seed_dir,
                baseline_variant=baseline_variant,
                fit_scenario="A_FIT",
                affinity_scenario="A_FIT",
            )
            layout_path = seed_dir / "optimized_assignments.csv"
            validation = _validate_layout(layout_path, validator, inventory)
            layout_sha = _sha256(layout_path)
            if not (validation["feasible"] and validation["inventory_conserved"]):
                records.append(
                    {
                        "seed": seed,
                        "status": "failed",
                        "reason": "infeasible or inventory not conserved",
                        "validation": validation,
                        "layout_sha256": layout_sha,
                        "fit_runtime_sec": summary.get("runtime_sec"),
                    }
                )
                continue
            run = run_phase6(
                processed=HOLDOUT_TREE,
                scenario="A_HOLDOUT",
                out=seed_dir / "holdout_eval",
                optimized_path=layout_path,
                affinity_scenario="A_HOLDOUT",
                baseline_path=BASELINE_LAYOUT,
                baseline_variant="repaired_minimal",
                baseline_note="repaired for feasibility only; frozen from Phase 3",
                routing_strategy="nearest_neighbor",
                batch_size=5,
                pick_time_basis="order_line",
            )
            base = run["baseline"]
            opt = run["optimized"]
            records.append(
                {
                    "seed": seed,
                    "status": "ok" if run["integrity"]["publishable"] else "blocked",
                    "layout_sha256": layout_sha,
                    "validation": validation,
                    "fit_feasible": summary.get("feasibility"),
                    "fit_objective": summary.get("final_objective"),
                    "fit_runtime_sec": summary.get("runtime_sec"),
                    "n_assignments": summary.get("n_assignments"),
                    "n_bins_used": summary.get("n_bins_used"),
                    "baseline": _basis_metrics(run, "baseline"),
                    "optimized": _basis_metrics(run, "optimized"),
                    "travel_delta_m": round(
                        opt["total_travel_distance_m"] - base["total_travel_distance_m"], 3
                    ),
                    "travel_delta_pct": round(
                        (opt["total_travel_distance_m"] - base["total_travel_distance_m"])
                        / base["total_travel_distance_m"]
                        * 100.0,
                        4,
                    ),
                    "cycle_delta_s": round(
                        opt["total_route_time_sec"] - base["total_route_time_sec"], 3
                    ),
                    "throughput_delta": round(
                        opt["throughput_orders_per_hr"] - base["throughput_orders_per_hr"], 4
                    ),
                    "publishable": bool(run["integrity"]["publishable"]),
                }
            )
        except Exception as exc:  # noqa: BLE001 - a failed seed is evidence, not a crash
            records.append({"seed": seed, "status": "failed", "reason": f"{type(exc).__name__}: {exc}"})

    ok = [r for r in records if r["status"] == "ok"]
    metrics = ("total_travel_distance_m", "total_route_time_sec", "throughput_orders_per_hr")
    summary = {
        "n_declared": len(SEEDS),
        "n_successful": len(ok),
        "n_failed": len(records) - len(ok),
        "unique_layouts": len({r["layout_sha256"] for r in ok}),
        "optimized": {key: _describe([r["optimized"][key] for r in ok]) for key in metrics},
        "paired_delta": {
            "travel_m": _describe([r["travel_delta_m"] for r in ok]),
            "travel_pct": _describe([r["travel_delta_pct"] for r in ok]),
            "cycle_s": _describe([r["cycle_delta_s"] for r in ok]),
            "throughput_orders_per_hr": _describe([r["throughput_delta"] for r in ok]),
        },
        "feasible_runs": sum(1 for r in ok if r["validation"]["feasible"]),
        "inventory_conserved_runs": sum(1 for r in ok if r["validation"]["inventory_conserved"]),
        "interpretation": (
            "exploratory: five predeclared seeds, one deterministic holdout workload per seed. "
            "The simulator has no randomness, so this measures optimizer variability only. "
            "No significance test is applied."
        ),
    }

    result = {
        "schema": "phase5.paired_seeds/1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "workload": workload_identity(pd.read_csv(HOLDOUT_TREE / "order_items.csv"), "A_HOLDOUT"),
        "seeds": list(SEEDS),
        "design": {
            "paired_unit": "seed",
            "baseline": "fixed repaired_minimal layout",
            "optimized": "layout fitted on A_FIT with the seed",
            "evaluation": "same A_HOLDOUT workload, nearest_neighbor, line-based pick time",
            "random_source": "simulated annealing (optimizer); simulator is deterministic",
        },
        "records": records,
        "summary": summary,
    }
    (out_root / "paired_seeds.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    pd.DataFrame(records).to_csv(out_root / "paired_seeds.csv", index=False)
    return result


def run(out_root: Path) -> dict:
    out_root = Path(out_root)
    out_root.mkdir(parents=True, exist_ok=True)

    split = json.loads(SPLIT_MANIFEST.read_text())
    split_checks = verify_split(split)
    if not split_checks["all_passed"]:
        raise RuntimeError(f"Phase 3 split failed verification: {split_checks}")
    for path in (BASELINE_LAYOUT, OPTIMIZED_LAYOUT, PHASE4 / "phase4_experiments.json"):
        if not path.exists():
            raise FileNotFoundError(f"required prior artifact missing: {path}")

    baseline_sha = _sha256(BASELINE_LAYOUT)
    optimized_sha = _sha256(OPTIMIZED_LAYOUT)
    validator, inventory = _validator(FIT_TREE)

    # Baseline is repaired once and reused for every pair; it is not seed-dependent.
    cfg42 = Config.from_json(PROJECT_ROOT / "configs" / "benchmark.json")
    baseline_variant = prepare_baseline_variant(FIT_TREE, cfg42, out_root / "baseline")

    d37 = _d37(out_root, baseline_variant, baseline_sha, optimized_sha)
    seeds = _paired_seeds(out_root, baseline_variant, validator, inventory)

    result = {
        "schema": "phase5.experiments/1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "phase3": {
            "split_manifest": str(SPLIT_MANIFEST),
            "split_checks": split_checks,
            "baseline_layout": str(BASELINE_LAYOUT),
            "optimized_layout": str(OPTIMIZED_LAYOUT),
            "baseline_sha256": baseline_sha,
            "optimized_sha256": optimized_sha,
        },
        "d37": d37,
        "paired_seeds": seeds,
    }
    (out_root / "phase5_experiments.json").write_text(json.dumps(result, indent=2), encoding="utf-8")

    outputs = {
        "phase5_experiments.json": out_root / "phase5_experiments.json",
        "d37_timing_models.json": out_root / "d37_timing_models.json",
        "d37_timing_models.csv": out_root / "d37_timing_models.csv",
        "paired_seeds.json": out_root / "paired_seeds.json",
        "paired_seeds.csv": out_root / "paired_seeds.csv",
    }
    for basis in PICK_TIME_BASES:
        outputs[f"d37_{basis}_evaluation.json"] = out_root / "d37" / basis / "evaluation_summary.json"
        outputs[f"d37_{basis}_routes.csv"] = out_root / "d37" / basis / "pick_routes.csv"
    for record in seeds["records"]:
        if record.get("status") == "ok":
            seed_dir = out_root / "seeds" / f"seed_{record['seed']}"
            outputs[f"seed_{record['seed']}_layout.csv"] = seed_dir / "optimized_assignments.csv"
            outputs[f"seed_{record['seed']}_evaluation.json"] = seed_dir / "holdout_eval" / "evaluation_summary.json"

    manifest = build_manifest(
        root=PROJECT_ROOT,
        processed=Path(
            os.environ.get("DATASET_DIR", PROJECT_ROOT.parent / "dataset" / "processed")
        ),
        config_path=PROJECT_ROOT / "configs" / "benchmark.json",
        outputs=outputs,
        experiment_id="phase5-d37-and-paired-seeds",
        scenario="A_HOLDOUT",
        split_manifest=SPLIT_MANIFEST,
        seeds={
            "optimizer_seeds": list(SEEDS),
            "simulation": "deterministic; no random seed used",
            "split": None,
        },
        evaluation_protocol={
            "d37": "same frozen layouts/workload/policy; only pick-time basis varies",
            "paired_seeds": "fit on A_FIT per seed; evaluate on A_HOLDOUT; no refit after holdout",
            "feasibility": "independent Validator per layout; blocked layouts are not evaluated",
            "selection": "seeds are predeclared; no seed is selected by holdout performance",
        },
        transformations=[
            "Phase 3/4 artifacts read-only",
            "no holdout refit or retuning",
        ],
        extra={
            "phase5": {
                "d37_default": d37["decision"]["authoritative_default"],
                "seeds": list(SEEDS),
                "baseline_sha256": baseline_sha,
                "optimized_sha256": optimized_sha,
            }
        },
    )
    (out_root / "provenance.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return result


def main() -> None:
    ap = argparse.ArgumentParser(prog="run_phase5")
    ap.add_argument("--out", default=str(PROJECT_ROOT / "outputs" / "phase5"))
    args = ap.parse_args()
    result = run(Path(args.out))
    print(
        json.dumps(
            {
                "d37": {
                    "travel_unchanged": result["d37"]["travel_unchanged"],
                    "impact": result["d37"]["impact"],
                    "decision": result["d37"]["decision"]["authoritative_default"],
                },
                "seeds": {
                    "declared": result["paired_seeds"]["summary"]["n_declared"],
                    "successful": result["paired_seeds"]["summary"]["n_successful"],
                    "unique_layouts": result["paired_seeds"]["summary"]["unique_layouts"],
                    "travel_pct": result["paired_seeds"]["summary"]["paired_delta"]["travel_pct"],
                },
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
