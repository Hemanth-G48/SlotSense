"""Phase 6 optimizer audit: is the annealer capable of improving a layout?

Two independent probes:

1. **Hand fixture** — a one-SKU, two-bin warehouse where the only improving move is
   obvious (move from a 100 m bin to a 10 m bin). ``_refine`` must find it. This proves the
   move generator, validator gate and score comparison can improve a layout when an
   improving move exists.
2. **Canonical probe** — start from the greedy starter on the A_FIT tree and sample the same
   random-neighbour distribution the annealer uses. Count feasible candidates, improving
   candidates, and the best delta. Then run ``_refine`` and compare its result with the
   starter. This distinguishes "move operator cannot improve" from "greedy is already the
   best layout this neighbourhood finds".

It does not change optimizer behaviour. Output: ``outputs/phase6/optimizer_audit.json``.
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

from src.models.config import Config
from src.models.entities import (
    AccessibilityZone,
    AssignmentType,
    HandlingType,
    HazardClass,
    Location,
    SKU,
    StorageAssignment,
    Warehouse,
)
from src.optimization.objective import Objective, build_affinity_penalty
from src.optimization.optimizer import OptimizerConfig, SlottingOptimizer
from src.validation.loader import (
    load_assignments,
    load_compatibility_rules,
    load_inventory,
    load_skus,
    load_warehouse_from_locations,
)
from src.validation.validator import Validator

FIT_TREE = PROJECT_ROOT / "outputs" / "phase3" / "split" / "A70" / "fit" / "processed"


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _loc(loc_id: str, distance: float) -> Location:
    return Location(
        location_id=loc_id,
        zone_id="Z1",
        aisle_id="A1",
        rack_id="R1",
        bay=0,
        shelf_level=2,
        x=distance,
        y=distance,
        z=0.0,
        width_cm=60.0,
        height_cm=40.0,
        depth_cm=45.0,
        max_weight_kg=100.0,
        usable_volume_cm3=108_000.0,
        ergonomic_zone=AccessibilityZone.GOLDEN,
        allowed_handling=(HandlingType.STANDARD.value,),
        allowed_hazard=(HazardClass.NONE.value,),
        distance_to_dispatch_m=distance,
        beam_max_weight_kg=1000.0,
        level_max_weight_kg=1000.0,
        shelf_max_weight_kg=1000.0,
        rack_max_weight_kg=1000.0,
    )


def _sku(sku_id: str) -> SKU:
    return SKU(
        sku_id=sku_id,
        product_name=sku_id,
        category_id="CAT001",
        width_cm=10.0,
        height_cm=10.0,
        depth_cm=10.0,
        unit_weight_kg=1.0,
        handling_type=HandlingType.STANDARD,
        hazard_class=HazardClass.NONE,
    )


def hand_fixture() -> dict:
    wh = Warehouse("WH", "fixture", "1")
    wh.locations = {"L_FAR": _loc("L_FAR", 100.0), "L_NEAR": _loc("L_NEAR", 10.0)}
    skus = {"S1": _sku("S1")}
    inventory = {"S1": 1}
    validator = Validator(skus, wh, [], inventory=inventory, separation_radius_m=10.0)
    opt = SlottingOptimizer(
        warehouse=wh,
        skus=skus,
        abc_classes={"S1": "A"},
        validator=validator,
        inventory=inventory,
        objective=Objective(),
        demand={"S1": 10.0},
        cfg=OptimizerConfig(seed=7, max_iterations=200),
        separation_radius_m=10.0,
        compatibility_rules=[],
    )
    start = [StorageAssignment("S1", "L_FAR", 1, AssignmentType.BASELINE)]
    start_score = opt._score(start)
    refined = opt._refine(start)
    refined_score = opt._score(refined)
    return {
        "start_location": start[0].location_id,
        "start_score": start_score,
        "refined_location": refined[0].location_id,
        "refined_score": refined_score,
        "improved": refined_score < start_score,
        "expected_best_score": 100.0,
        "feasible": validator.validate(refined, record_checks=False).is_feasible,
    }


def build_canonical(seed: int):
    cfg = Config.from_json(PROJECT_ROOT / "configs" / "benchmark.json")
    cfg.dataset.seed = seed
    locations = pd.read_csv(FIT_TREE / "locations.csv")
    products = pd.read_csv(FIT_TREE / "products.csv")
    rules = pd.read_csv(FIT_TREE / "compatibility_rules.csv")
    inventory = pd.read_csv(FIT_TREE / "inventory.csv")
    baseline_rows = pd.read_csv(FIT_TREE / "storage_assignments_baseline.csv")
    demand = pd.read_csv(FIT_TREE / "demand_summary.csv")
    affinity = pd.read_csv(FIT_TREE / "sku_affinity.csv")

    wh = load_warehouse_from_locations(locations)
    skus = load_skus(products)
    comp = load_compatibility_rules(rules)
    inv = load_inventory(inventory)
    baseline = load_assignments(baseline_rows)

    d = demand[demand["scenario_id"] == "A_FIT"]
    demand_map = dict(zip(d["sku_id"], d["demand_frequency"].astype(float)))
    abc = dict(zip(d["sku_id"], d["abc_class"]))
    aff = affinity[affinity["scenario_id"] == "A_FIT"]
    validator = Validator(skus, wh, comp, inventory=inv, separation_radius_m=cfg.separation_radius_m)
    opt = SlottingOptimizer(
        warehouse=wh,
        skus=skus,
        abc_classes=abc,
        validator=validator,
        inventory=inv,
        affinity_penalty=build_affinity_penalty(aff),
        objective=Objective(
            alpha=cfg.optimization.alpha,
            beta=cfg.optimization.beta,
            gamma=cfg.optimization.gamma,
            delta=cfg.optimization.delta,
            epsilon=cfg.optimization.epsilon,
        ),
        demand=demand_map,
        cfg=OptimizerConfig(seed=seed, max_iterations=600),
        initial_assignments=baseline,
        separation_radius_m=cfg.separation_radius_m,
        compatibility_rules=comp,
    )
    return opt, demand_map, wh, cfg


def canonical_probe(seed: int, samples: int) -> dict:
    opt, demand_map, wh, cfg = build_canonical(seed)
    starter = opt.greedy_starter()
    starter_result = opt.validator.validate(starter, record_checks=False)
    starter_score = opt._score(starter)

    # Independent recomputation of the demand-weighted distance term, not via Objective.
    independent_d = 0.0
    for a in starter:
        loc = wh.locations[a.location_id]
        independent_d += demand_map.get(a.sku_id, 1.0) * loc.distance_to_dispatch_m

    feasible = improving = invalid = 0
    best_delta = 0.0
    for _ in range(samples):
        cand = opt._random_neighbor(starter)
        if cand is None:
            invalid += 1
            continue
        result = opt.validator.validate(cand, record_checks=False)
        if not result.is_feasible:
            invalid += 1
            continue
        feasible += 1
        score = opt._score(cand)
        delta = score - starter_score
        if delta < -1e-9:
            improving += 1
            best_delta = min(best_delta, delta)

    refined = opt._refine(starter)
    refined_result = opt.validator.validate(refined, record_checks=False)
    refined_score = opt._score(refined)
    components = opt._components(starter)

    return {
        "seed": seed,
        "fit_tree": str(FIT_TREE),
        "samples": samples,
        "starter": {
            "feasible": starter_result.is_feasible,
            "objective": starter_score,
            "n_assignment_records": len(starter),
            "n_bins_used": len({a.location_id for a in starter}),
            "D_travel": components["D_travel"],
            "independent_D_travel": round(independent_d, 6),
            "D_matches_independent": abs(components["D_travel"] - independent_d) < 1e-6,
        },
        "sampled_neighbours": {
            "feasible": feasible,
            "invalid_or_infeasible": invalid,
            "improving": improving,
            "best_delta": round(best_delta, 6),
        },
        "refine": {
            "objective": refined_score,
            "delta_vs_starter": round(refined_score - starter_score, 6),
            "feasible": refined_result.is_feasible,
            "layout_changed": sorted((a.sku_id, a.location_id, a.assigned_quantity) for a in refined)
            != sorted((a.sku_id, a.location_id, a.assigned_quantity) for a in starter),
        },
        "config": {
            "alpha": cfg.optimization.alpha,
            "beta": cfg.optimization.beta,
            "gamma": cfg.optimization.gamma,
            "delta": cfg.optimization.delta,
            "epsilon": cfg.optimization.epsilon,
            "separation_radius_m": cfg.separation_radius_m,
        },
    }


def main() -> None:
    global FIT_TREE
    ap = argparse.ArgumentParser(prog="audit_optimizer")
    ap.add_argument("--out", default=str(PROJECT_ROOT / "outputs" / "phase6" / "optimizer_audit.json"))
    ap.add_argument("--fit-tree", default=str(FIT_TREE))
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--samples", type=int, default=600)
    args = ap.parse_args()

    FIT_TREE = Path(args.fit_tree).resolve()

    fixture = hand_fixture()
    canonical = canonical_probe(args.seed, args.samples)
    payload = {
        "schema": "phase6.optimizer_audit/1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "hand_fixture": fixture,
        "canonical": canonical,
        "inputs": {
            "config_sha256": _sha(PROJECT_ROOT / "configs" / "benchmark.json"),
            "fit_tree": str(FIT_TREE),
            "fit_assignments_sha256": _sha(FIT_TREE / "storage_assignments_baseline.csv"),
        },
        "interpretation": {
            "fixture": (
                "If hand_fixture.improved is true, the move generator, validator gate and "
                "score comparison can improve a layout when an improving move exists."
            ),
            "canonical": (
                "improving == 0 means the sampled neighbourhood found no layout better than the "
                "greedy starter; it does not prove global optimality. refine.delta_vs_starter == 0 "
                "means the annealer returned the starter on this instance."
            ),
        },
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
