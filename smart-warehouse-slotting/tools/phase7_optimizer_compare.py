"""Phase 7 controlled optimizer comparison: legacy vs targeted neighbourhood.

Same A_FIT workload, weights, seed, budget, baseline variant and independent validator.
The only changed factor is how `_random_neighbor` proposes a relocation.

Output: outputs/phase7/optimizer_compare.json
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

FIT_TREE = PROJECT_ROOT / "outputs" / "phase3" / "split" / "A70" / "fit" / "processed"
HOLDOUT_TREE = PROJECT_ROOT / "outputs" / "phase3" / "split" / "A70" / "holdout" / "processed"
BASELINE_LAYOUT = PROJECT_ROOT / "outputs" / "phase3" / "optimized_fit" / "baseline_repaired_assignments.csv"


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _validator():
    locations = pd.read_csv(FIT_TREE / "locations.csv")
    products = pd.read_csv(FIT_TREE / "products.csv")
    rules = pd.read_csv(FIT_TREE / "compatibility_rules.csv")
    inventory = pd.read_csv(FIT_TREE / "inventory.csv")
    return Validator(
        load_skus(products),
        load_warehouse_from_locations(locations),
        load_compatibility_rules(rules),
        inventory=load_inventory(inventory),
        separation_radius_m=10.0,
    ), load_inventory(inventory)


def _validate(path: Path, validator, inventory: dict) -> dict:
    from src.models.entities import AssignmentType, StorageAssignment

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
        "rows": int(frame.shape[0]),
    }


def _probe(seed: int, neighborhood: str, samples: int) -> dict:
    # Imported lazily so the audit module's own CLI remains independent.
    from tools.audit_optimizer import build_canonical

    opt, _demand, _wh, _cfg = build_canonical(seed)
    opt.cfg.neighborhood = neighborhood
    starter = opt.greedy_starter()
    starter_score = opt._score(starter)
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
        delta = opt._score(cand) - starter_score
        if delta < -1e-9:
            improving += 1
            best_delta = min(best_delta, delta)
    return {
        "seed": seed,
        "samples": samples,
        "feasible": feasible,
        "invalid_or_infeasible": invalid,
        "improving": improving,
        "best_delta": round(best_delta, 6),
        "feasible_rate_pct": round(100.0 * feasible / samples, 2),
    }


def run(seed: int, samples: int) -> dict:
    cfg = Config.from_json(PROJECT_ROOT / "configs" / "benchmark.json")
    cfg.dataset.seed = seed
    variant = prepare_baseline_variant(FIT_TREE, cfg, PROJECT_ROOT / "outputs" / "phase7" / "baseline")
    validator, inventory = _validator()

    results = {}
    for neighborhood in ("legacy", "targeted"):
        out = PROJECT_ROOT / "outputs" / "phase7" / "optimizer" / neighborhood
        summary = run_phase5(
            FIT_TREE,
            cfg,
            out,
            baseline_variant=variant,
            fit_scenario="A_FIT",
            affinity_scenario="A_FIT",
            optimizer_neighborhood=neighborhood,
        )
        layout = out / "optimized_assignments.csv"
        results[neighborhood] = {
            "summary": {
                "objective": summary.get("objective"),
                "final_objective": summary.get("final_objective"),
                "starter_objective": summary.get("starter_objective"),
                "objective_improvement_pct": summary.get("objective_improvement_pct"),
                "moves_evaluated": summary.get("moves_evaluated"),
                "moves_accepted": summary.get("moves_accepted"),
                "feasibility": summary.get("feasibility_status"),
                "runtime_sec": summary.get("runtime_sec"),
                "n_assignments": summary.get("n_assignments"),
            },
            "layout_sha256": _sha(layout),
            "validation": _validate(layout, validator, inventory),
            "proposal_probe": _probe(seed, neighborhood, samples),
        }

    same_layout = results["legacy"]["layout_sha256"] == results["targeted"]["layout_sha256"]
    result = {
        "schema": "phase7.optimizer_compare/1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "design": {
            "workload": "A_FIT",
            "seed": seed,
            "budget": 600,
            "objective_weights": {
                "alpha": cfg.optimization.alpha,
                "beta": cfg.optimization.beta,
                "gamma": cfg.optimization.gamma,
                "delta": cfg.optimization.delta,
                "epsilon": cfg.optimization.epsilon,
            },
            "changed_factor": "relocation proposal: legacy uniform feasible bin vs targeted empty nearest-20",
            "validator": "independent Validator, CAT-01 10 m",
        },
        "results": results,
        "same_layout": same_layout,
        "objective_delta_targeted_minus_legacy": round(
            results["targeted"]["summary"]["final_objective"]
            - results["legacy"]["summary"]["final_objective"],
            6,
        ),
        "holdout_evaluated": False,
        "limitations": [
            "one seed and 600 evaluations per arm; this is a controlled deterministic comparison, not a significance test",
            "targeted proposals are still subject to the full validator",
        ],
    }
    out_dir = PROJECT_ROOT / "outputs" / "phase7"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "optimizer_compare.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main() -> None:
    ap = argparse.ArgumentParser(prog="phase7_optimizer_compare")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--samples", type=int, default=600)
    args = ap.parse_args()
    result = run(args.seed, args.samples)
    print(json.dumps({
        "same_layout": result["same_layout"],
        "delta": result["objective_delta_targeted_minus_legacy"],
        "legacy": result["results"]["legacy"]["proposal_probe"],
        "targeted": result["results"]["targeted"]["proposal_probe"],
    }, indent=2))


if __name__ == "__main__":
    main()
