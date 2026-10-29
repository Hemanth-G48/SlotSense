"""Phase 3 runner: split -> fit -> 2x2 -> replenishment -> weight sweep -> provenance.

Everything it writes lands under ``outputs/phase3/`` (never in the canonical dataset):

    phase3/split/A70/...                     fit/holdout trees + split manifest
    phase3/optimized_fit/...                 layout fitted on A_FIT only
    phase3/sweep/<config_id>/...             one directory per weight vector
    phase3/phase3_experiments.json           the whole result, machine-readable
    phase3/phase3_cells.csv                  primary 2x2 cells (placement x fragmentation)
    phase3/phase3_pick_rule_cells.csv        secondary pick-rule sensitivity cells
    phase3/phase3_fragmentation.csv          fragmentation statistics per cell
    phase3/phase3_sweep.csv                  weight-sweep table
    phase3/phase3_replenishment.csv          replenishment metrics per cell
    phase3/line_travel_<cell>.csv            auditable per-line travel
    phase3/unresolved_travel_<cell>.csv      lines that could not be priced
    phase3/provenance.json                   input/config/output hashes

Usage:
    .venv/bin/python -m src.experiments.run_phase3 --processed ../dataset/processed
    .venv/bin/python -m src.experiments.run_phase3 --skip-sweep      # faster
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src.experiments.factorial import run_2x2, run_factorial_2x2
from src.experiments.fragmentation import (
    POLICY_AS_IS,
    POLICY_MIN_BINS,
    consolidate_min_bins,
    fragmentation_stats,
)
from src.experiments.provenance import build_manifest
from src.experiments.replenishment import replenishment_metrics
from src.experiments.split import build_split, verify_split
from src.experiments.travel import (
    ALL_BINS,
    QUANTITY_AWARE,
    line_travel,
    line_travel_table,
    sku_bins,
    unresolved_travel_table,
)
from src.models.config import Config
from src.models.entities import AssignmentType, StorageAssignment
from src.optimization.baseline import prepare_baseline_variant
from src.optimization.pipeline import run_phase5
from src.routing.graph import build_graph, depot_distance_map, find_depot_node
from src.validation.loader import (
    load_compatibility_rules,
    load_inventory,
    load_skus,
    load_warehouse_from_locations,
)
from src.validation.validator import Validator

PROJECT_ROOT = Path(__file__).resolve().parents[2]

EXPERIMENT_ID = "phase3-fit-holdout-2x2-fragmentation"

# Weight vectors are the existing α/β/γ/δ plus the replenishment weight ε. All are
# fitted on A_FIT only; the holdout is scored once per variant and never used to pick.
WEIGHT_VARIANTS = [
    ("default", {"alpha": 1.0, "beta": 0.4, "gamma": 0.3, "delta": 0.2, "epsilon": 0.0}),
    ("travel_only", {"alpha": 1.0, "beta": 0.0, "gamma": 0.0, "delta": 0.0, "epsilon": 0.0}),
    ("affinity_heavy", {"alpha": 1.0, "beta": 1.0, "gamma": 0.3, "delta": 0.2, "epsilon": 0.0}),
    ("ergonomics_heavy", {"alpha": 1.0, "beta": 0.4, "gamma": 1.0, "delta": 0.2, "epsilon": 0.0}),
    ("replenishment_heavy", {"alpha": 1.0, "beta": 0.4, "gamma": 0.3, "delta": 0.2, "epsilon": 0.5}),
]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _depot_distances(processed: Path) -> dict[str, float]:
    graph = build_graph(Path(processed) / "location_graph.csv")
    depot = find_depot_node(graph)
    if depot is None:
        raise ValueError("no depot node in location_graph.csv")
    return depot_distance_map(graph, depot)


def _assignments_frame(assignments) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "sku_id": a.sku_id,
                "location_id": a.location_id,
                "assigned_quantity": int(a.assigned_quantity),
            }
            for a in assignments
        ]
    )


def _to_records(frame: pd.DataFrame) -> list[StorageAssignment]:
    return [
        StorageAssignment(r.sku_id, r.location_id, int(r.assigned_quantity), AssignmentType.OPTIMIZED)
        for r in frame.itertuples(index=False)
    ]


def _validate_frame(validator: Validator, frame: pd.DataFrame, inventory: dict[str, int]) -> dict:
    """Independent verdict plus the conservation audit, for one layout frame."""
    result = validator.validate(_to_records(frame))
    by_rule: dict[str, int] = {}
    for v in result.violations:
        by_rule[v.rule_id] = by_rule.get(v.rule_id, 0) + 1

    placed = frame.groupby("sku_id")["assigned_quantity"].sum()
    required = pd.Series(inventory, dtype="int64")
    joined = pd.concat([required.rename("required"), placed.rename("placed")], axis=1).fillna(0)
    mismatch = joined[joined["required"].astype("int64") != joined["placed"].astype("int64")]
    duplicates = int(frame.duplicated(["sku_id", "location_id"]).sum())
    return {
        "feasibility_status": "FEASIBLE" if result.is_feasible else "INFEASIBLE",
        "feasible": bool(result.is_feasible),
        "n_violations": len(result.violations),
        "violations_by_rule": dict(sorted(by_rule.items())),
        "checks_run": result.checks_run,
        "inventory": {
            "units_required": int(required.sum()),
            "units_placed": int(frame["assigned_quantity"].sum()),
            "conserved": int(required.sum()) == int(frame["assigned_quantity"].sum()),
            "skus_mismatched": int(len(mismatch)),
            "duplicate_sku_bin_pairs": duplicates,
        },
    }


def _units_demand(view: Path, scenario: str) -> dict[str, float]:
    """Units demanded per SKU in a view, from its own order history."""
    orders = pd.read_csv(view / "orders.csv")
    items = pd.read_csv(view / "order_items.csv")
    ids = set(orders.loc[orders["scenario_id"] == scenario, "order_id"])
    sub = items[items["order_id"].isin(ids)]
    return sub.groupby("sku_id")["quantity"].sum().astype(float).to_dict()


def _physical(processed: Path, cfg: Config):
    locations = pd.read_csv(processed / "locations.csv")
    products = pd.read_csv(processed / "products.csv")
    rules = pd.read_csv(processed / "compatibility_rules.csv")
    inventory_rows = pd.read_csv(processed / "inventory.csv")
    warehouse = load_warehouse_from_locations(locations)
    skus = load_skus(products)
    compatibility = load_compatibility_rules(rules)
    inventory = load_inventory(inventory_rows)
    validator = Validator(
        skus, warehouse, compatibility, inventory=inventory,
        separation_radius_m=cfg.separation_radius_m,
    )
    return warehouse, skus, inventory, validator


def _frame_travel(frame: pd.DataFrame, workload: pd.DataFrame, depot: dict[str, float], rule: str) -> dict:
    return line_travel(workload, sku_bins(frame, depot), rule).aggregate()


def run(processed: Path, out_root: Path, fraction: float, skip_sweep: bool) -> dict:
    processed = Path(processed)
    out_root = Path(out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    # The runner owns these per-cell audit files; remove the previous run's set so a
    # layout label that no longer exists cannot linger beside the current results.
    for pattern in ("line_travel_*.csv", "unresolved_travel_*.csv"):
        for stale in out_root.glob(pattern):
            stale.unlink()

    # ---------------------------------------------------------------- 1. split
    split = build_split(processed, out_root / "split", name="A70", fraction=fraction, scenario="A")
    split_checks = verify_split(split)
    if not split_checks["all_passed"]:
        raise RuntimeError(f"split integrity failed: {split_checks}")

    fit_proc = Path(split["views"]["fit"]["path"])
    hold_proc = Path(split["views"]["holdout"]["path"])
    fit_scenario = split["views"]["fit"]["scenario_id"]
    hold_scenario = split["views"]["holdout"]["scenario_id"]

    # ---------------------------------------------------------------- 2. fit on A_FIT
    cfg = Config.from_json(PROJECT_ROOT / "configs" / "benchmark.json")
    warehouse, skus, inventory, validator = _physical(fit_proc, cfg)

    fit_out = out_root / "optimized_fit"
    baseline_variant = prepare_baseline_variant(fit_proc, cfg, fit_out)
    fit_summary = run_phase5(
        fit_proc, cfg, fit_out,
        baseline_variant=baseline_variant,
        fit_scenario=fit_scenario,
        affinity_scenario=fit_scenario,
    )

    # ---------------------------------------------------------------- 3. layouts
    depot = _depot_distances(hold_proc)
    fit_items = pd.read_csv(fit_proc / "order_items.csv")
    hold_items = pd.read_csv(hold_proc / "order_items.csv")
    hold_units = _units_demand(hold_proc, hold_scenario)

    baseline_df = _assignments_frame(baseline_variant.assignments)
    optimized_df = pd.read_csv(fit_out / "optimized_assignments.csv")

    # Fragmentation policy is applied to each placement independently. The packer is
    # distance-blind, so the factor does not smuggle in a proximity improvement.
    baseline_min, baseline_frag = consolidate_min_bins(
        baseline_df, skus=skus, warehouse=warehouse, validator=validator,
        location_distance_m=depot,
    )
    optimized_min, optimized_frag = consolidate_min_bins(
        optimized_df, skus=skus, warehouse=warehouse, validator=validator,
        location_distance_m=depot,
    )

    cells = {
        ("baseline_repaired", POLICY_AS_IS): baseline_df,
        ("baseline_repaired", POLICY_MIN_BINS): baseline_min,
        ("optimized_fit", POLICY_AS_IS): optimized_df,
        ("optimized_fit", POLICY_MIN_BINS): optimized_min,
    }

    def _as_is_stats(frame: pd.DataFrame) -> dict:
        stats = fragmentation_stats(frame, depot)
        return {
            "policy": POLICY_AS_IS,
            "feasible": None,  # filled from the independent verdict below
            "iterations": 0,
            "fallback_skus": 0,
            "before": stats,
            "after": stats,
            "bins_released": 0,
            "units_conserved": True,
            "distance_blind_retention": True,
        }

    frag_stats = {
        ("baseline_repaired", POLICY_AS_IS): _as_is_stats(baseline_df),
        ("baseline_repaired", POLICY_MIN_BINS): baseline_frag,
        ("optimized_fit", POLICY_AS_IS): _as_is_stats(optimized_df),
        ("optimized_fit", POLICY_MIN_BINS): optimized_frag,
    }

    # Independent validation of every cell that enters a comparison.
    cell_validation = {key: _validate_frame(validator, frame, inventory) for key, frame in cells.items()}
    feasibility = {key: v["feasible"] for key, v in cell_validation.items()}
    for key, verdict in cell_validation.items():
        frag_stats[key]["feasible"] = verdict["feasible"]

    # ---------------------------------------------------------------- 4. primary 2x2
    primary = run_factorial_2x2(
        cells,
        hold_items,
        depot,
        factor_a_name="placement",
        factor_b_name="fragmentation_policy",
        rule=QUANTITY_AWARE,
        feasibility=feasibility,
        fragmentation=frag_stats,
        caveat=(
            "single deterministic workload. min_bins changes which of a SKU's own bins are retained; "
            "retention is capacity-based and distance-blind, but it is still a layout change, so the "
            "interaction is a decomposition of this instance, not a structural law."
        ),
    )

    # Secondary: architecture §11.5 pick-rule sensitivity (layout x accounting rule).
    pick_rule = run_2x2(
        {"baseline_repaired": baseline_df, "optimized_fit": optimized_df},
        hold_items,
        depot,
        feasibility={
            "baseline_repaired": feasibility[("baseline_repaired", POLICY_AS_IS)],
            "optimized_fit": feasibility[("optimized_fit", POLICY_AS_IS)],
        },
    )

    # The same four cells under the all-bins rule: this is where a bin-count effect
    # should appear if it exists, because every bin a SKU occupies is charged.
    primary_all_bins = run_factorial_2x2(
        cells,
        hold_items,
        depot,
        factor_a_name="placement",
        factor_b_name="fragmentation_policy",
        rule=ALL_BINS,
        feasibility=feasibility,
        fragmentation=frag_stats,
        caveat=(
            "same four layouts as the primary design, scored under the all-bins rule. "
            "Reported to show how much of the fragmentation effect is a property of the "
            "accounting rule rather than of the layout."
        ),
    )

    # Auditable per-line travel for every primary cell, under both rules.
    line_artifacts: dict[str, str] = {}
    unresolved_artifacts: dict[str, str] = {}
    for (placement, policy), frame in cells.items():
        label = f"{placement}__{policy}"
        for rule in (QUANTITY_AWARE, ALL_BINS):
            suffix = label if rule == QUANTITY_AWARE else f"{label}__all_bins"
            result = line_travel(hold_items, sku_bins(frame, depot), rule)
            line_path = out_root / f"line_travel_{suffix}.csv"
            unresolved_path = out_root / f"unresolved_travel_{suffix}.csv"
            line_travel_table(result).to_csv(line_path, index=False)
            unresolved_travel_table(result).to_csv(unresolved_path, index=False)
            line_artifacts[f"line_{suffix}"] = str(line_path)
            unresolved_artifacts[f"unresolved_{suffix}"] = str(unresolved_path)

    # ---------------------------------------------------------------- 5. replenishment
    replenishment = {}
    for (placement, policy), frame in cells.items():
        label = f"{placement}__{policy}"
        replenishment[label] = replenishment_metrics(frame, hold_units, depot).aggregate()

    # ---------------------------------------------------------------- 6. weight sweep
    sweep_rows: list[dict] = []
    sweep_outputs: dict[str, Path] = {}
    if not skip_sweep:
        for cfg_id, weights in WEIGHT_VARIANTS:
            run_cfg = Config.from_json(PROJECT_ROOT / "configs" / "benchmark.json")
            for name, value in weights.items():
                setattr(run_cfg.optimization, name, value)
            variant_out = out_root / "sweep" / cfg_id
            summary = run_phase5(
                fit_proc, run_cfg, variant_out,
                baseline_variant=baseline_variant,
                fit_scenario=fit_scenario,
                affinity_scenario=fit_scenario,
            )
            layout = pd.read_csv(variant_out / "optimized_assignments.csv")
            sweep_outputs[f"sweep_{cfg_id}_assignments.csv"] = variant_out / "optimized_assignments.csv"
            sweep_outputs[f"sweep_{cfg_id}_summary.json"] = variant_out / "optimization_summary.json"
            fit_qa = _frame_travel(layout, fit_items, depot, QUANTITY_AWARE)
            hold_qa = _frame_travel(layout, hold_items, depot, QUANTITY_AWARE)
            verdict = _validate_frame(validator, layout, inventory)
            components = (summary.get("objective") or {}).get("components") or {}
            sweep_rows.append(
                {
                    "config_id": cfg_id,
                    **weights,
                    "fit_feasible": bool(summary.get("feasibility")),
                    "fit_feasibility_status": summary.get("feasibility_status"),
                    "fit_violations": summary.get("n_violations"),
                    "fit_units_placed": summary.get("units_placed"),
                    "fit_inventory_units": summary.get("inventory_units"),
                    "fit_completeness_pct": (summary.get("assignment_completeness") or {}).get("completeness_pct"),
                    "fit_objective": summary.get("final_objective"),
                    "fit_D_travel": components.get("D_travel"),
                    "fit_A_affinity": components.get("A_affinity"),
                    "fit_E_ergonomics": components.get("E_ergonomics"),
                    "fit_U_utilization": components.get("U_utilization"),
                    "fit_R_replenishment": components.get("R_replenishment"),
                    "fit_runtime_sec": summary.get("runtime_sec"),
                    "fit_stopping_reason": summary.get("stopping_reason"),
                    "fit_demand_weighted_depot_distance": fit_qa["demand_weighted_depot_distance"],
                    "fit_mean_per_line_m": fit_qa["mean_per_line_m"],
                    "holdout_demand_weighted_depot_distance": hold_qa["demand_weighted_depot_distance"],
                    "holdout_mean_per_line_m": hold_qa["mean_per_line_m"],
                    "n_assignments": summary.get("n_assignments"),
                    "n_bins_used": summary.get("n_bins_used"),
                    "layout_sha256": _sha256(variant_out / "optimized_assignments.csv"),
                    "independent_feasible": verdict["feasible"],
                    "selected": False,
                }
            )

        # Selection uses a COMMON metric (fit demand-weighted travel), never the raw
        # objective: objective values with different weight vectors are not comparable,
        # and picking the smallest unnormalised sum would simply prefer the vector that
        # deletes penalty terms. Ties keep the default, which is the frozen config.
        feasible_rows = [r for r in sweep_rows if r["fit_feasible"] and r["independent_feasible"]]
        if feasible_rows:
            best = min(
                feasible_rows,
                key=lambda r: (
                    r["fit_demand_weighted_depot_distance"]
                    if r["fit_demand_weighted_depot_distance"] is not None
                    else float("inf"),
                    0 if r["config_id"] == "default" else 1,
                    r["config_id"],
                ),
            )
            for r in sweep_rows:
                r["selected"] = r is best
            selected_config = best["config_id"]
        else:
            selected_config = None
    else:
        selected_config = None

    # ---------------------------------------------------------------- 7. artifacts
    all_cells_feasible = all(feasibility.values())
    results = {
        "schema": "phase3.experiments/2",
        "experiment_id": EXPERIMENT_ID,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dataset": str(processed),
        "separation_radius_m": cfg.separation_radius_m,
        "split": {
            "manifest": split["manifest_path"],
            "method": split["method"],
            "split_unit": split["split_unit"],
            "fraction_fit": split["fraction_fit"],
            "seed": split["seed"],
            "fit": {k: split["views"]["fit"][k] for k in ("orders", "lines", "skus_with_demand")},
            "holdout": {k: split["views"]["holdout"][k] for k in ("orders", "lines", "skus_with_demand")},
            "checks": split_checks,
        },
        "fit_run": {
            "scenario": fit_scenario,
            "feasibility_status": fit_summary["feasibility_status"],
            "n_violations": fit_summary["n_violations"],
            "units_placed": fit_summary["units_placed"],
            "inventory_units": fit_summary["inventory_units"],
            "assignment_completeness": fit_summary.get("assignment_completeness"),
            "objective": fit_summary["final_objective"],
            "objective_components": (fit_summary.get("objective") or {}).get("components"),
            "objective_weights": fit_summary.get("objective_weights"),
            "runtime_sec": fit_summary["runtime_sec"],
            "baseline_variant": fit_summary.get("baseline_variant"),
            "baseline_repair": fit_summary.get("baseline_repair"),
            "replenishment": fit_summary.get("replenishment"),
        },
        "two_by_two": primary,
        "two_by_two_all_bins": primary_all_bins,
        "pick_rule_sensitivity": pick_rule,
        "cells": [
            {
                "cell_id": cell["cell_id"],
                "placement": cell["placement"],
                "fragmentation_policy": cell["fragmentation_policy"],
                "feasible": cell["feasible"],
                "demand_weighted_depot_distance": cell["demand_weighted_depot_distance"],
                "numerator_m": cell["numerator_m"],
                "denominator_lines": cell["denominator_lines"],
                "lines_total": cell["lines_total"],
                "lines_unresolved": cell["lines_unresolved"],
                "coverage_pct": cell["coverage_pct"],
                "mean_per_line_m": cell["mean_per_line_m"],
                "stops": cell["stops"],
                "lines_quantity_short": cell["lines_quantity_short"],
                "units_short": cell["units_short"],
                "validation": cell_validation[(cell["placement"], cell["fragmentation_policy"])],
                "fragmentation": frag_stats[(cell["placement"], cell["fragmentation_policy"])],
                "line_audit": line_artifacts[
                    f"line_{cell['placement']}__{cell['fragmentation_policy']}"
                ],
            }
            for cell in primary["cells"]
        ],
        "replenishment": {
            "protocol": (
                "holdout demand; cover_days=14; window_days=180; zero-demand SKUs make no trips; "
                "travel is a round trip depot->bin->depot"
            ),
            "cells": replenishment,
        },
        "sweep": {
            "variants": sweep_rows,
            "selected_by_fit_travel": selected_config,
            "selection_note": (
                "selection uses the common FIT demand-weighted travel metric among independently feasible "
                "runs, with the default kept on ties. Raw objective values are never compared across weight "
                "vectors: different weights make them different scales, and minimising the sum would simply "
                "prefer the vector that deletes penalty terms. Holdout values are reported for every variant "
                "and never used to choose."
            ),
        },
        "integrity": {
            "all_cells_feasible": all_cells_feasible,
            "publishable_comparison": all_cells_feasible,
            "evaluation_status": "held_out" if split_checks["all_passed"] else "in_sample_or_unverified",
            "inventory_conserved_every_cell": all(
                v["inventory"]["conserved"] and v["inventory"]["duplicate_sku_bin_pairs"] == 0
                for v in cell_validation.values()
            ),
            "feasibility_gate": "independent Validator per cell; no objective value can override a violation",
        },
        "methodology_caveat": (
            "the Phase 2 -55.65% figure was computed in-sample, before this split existed; it is not a "
            "held-out result and must not be quoted as one. The Phase 3 headline is the direct holdout "
            "comparison of the frozen fit layout against the repaired baseline under one documented rule."
        ),
    }

    (out_root / "phase3_experiments.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    pd.DataFrame(
        [
            {
                "cell_id": c["cell_id"],
                "placement": c["placement"],
                "fragmentation_policy": c["fragmentation_policy"],
                "feasible": c["feasible"],
                "pick_rule": c["pick_rule"],
                "demand_weighted_depot_distance": c["demand_weighted_depot_distance"],
                "numerator_m": c["numerator_m"],
                "denominator_lines": c["denominator_lines"],
                "lines_total": c["lines_total"],
                "lines_unresolved": c["lines_unresolved"],
                "coverage_pct": c["coverage_pct"],
                "mean_per_line_m": c["mean_per_line_m"],
                "stops": c["stops"],
                "lines_quantity_short": c["lines_quantity_short"],
                "units_short": c["units_short"],
                "bins_before": c["fragmentation"]["before"]["bins_used"],
                "bins_after": c["fragmentation"]["after"]["bins_used"],
                "multi_bin_skus_before": c["fragmentation"]["before"]["multi_bin_skus"],
                "multi_bin_skus_after": c["fragmentation"]["after"]["multi_bin_skus"],
                "bins_released": c["fragmentation"]["bins_released"],
                "fallback_skus": c["fragmentation"]["fallback_skus"],
            }
            for c in primary["cells"]
        ]
    ).to_csv(out_root / "phase3_cells.csv", index=False)
    pd.DataFrame(
        [
            {
                "cell_id": c["cell_id"],
                "placement": c["placement"],
                "fragmentation_policy": c["fragmentation_policy"],
                "feasible": c["feasible"],
                "pick_rule": c["pick_rule"],
                "demand_weighted_depot_distance": c["demand_weighted_depot_distance"],
                "numerator_m": c["numerator_m"],
                "denominator_lines": c["denominator_lines"],
                "lines_total": c["lines_total"],
                "mean_per_line_m": c["mean_per_line_m"],
                "stops": c["stops"],
                "lines_quantity_short": c["lines_quantity_short"],
                "units_short": c["units_short"],
            }
            for c in primary_all_bins["cells"]
        ]
    ).to_csv(out_root / "phase3_cells_all_bins.csv", index=False)
    pd.DataFrame(pick_rule["cells"]).to_csv(out_root / "phase3_pick_rule_cells.csv", index=False)
    pd.DataFrame(
        [
            {
                "cell_id": cell["cell_id"],
                "placement": cell["placement"],
                "fragmentation_policy": cell["fragmentation_policy"],
                "feasible": c["feasible"],
                "units_conserved": c["units_conserved"],
                "bins_released": c["bins_released"],
                "fallback_skus": c["fallback_skus"],
                "bins_before": c["before"]["bins_used"],
                "bins_after": c["after"]["bins_used"],
                "multi_bin_skus_before": c["before"]["multi_bin_skus"],
                "multi_bin_skus_after": c["after"]["multi_bin_skus"],
                "mean_bins_per_sku_before": c["before"]["mean_bins_per_sku"],
                "mean_bins_per_sku_after": c["after"]["mean_bins_per_sku"],
                "fragmentation_index_before": c["before"]["fragmentation_index"],
                "fragmentation_index_after": c["after"]["fragmentation_index"],
                "mean_bin_distance_before_m": c["before"].get("mean_bin_distance_m"),
                "mean_bin_distance_after_m": c["after"].get("mean_bin_distance_m"),
            }
            for cell in primary["cells"]
            for c in [frag_stats[(cell["placement"], cell["fragmentation_policy"])]]
        ]
    ).to_csv(out_root / "phase3_fragmentation.csv", index=False)
    if sweep_rows:
        pd.DataFrame(sweep_rows).to_csv(out_root / "phase3_sweep.csv", index=False)
    pd.DataFrame(
        [{"cell": k, **v} for k, v in replenishment.items()]
    ).to_csv(out_root / "phase3_replenishment.csv", index=False)

    outputs = {
        "phase3_experiments.json": out_root / "phase3_experiments.json",
        "phase3_cells.csv": out_root / "phase3_cells.csv",
        "phase3_cells_all_bins.csv": out_root / "phase3_cells_all_bins.csv",
        "phase3_pick_rule_cells.csv": out_root / "phase3_pick_rule_cells.csv",
        "phase3_fragmentation.csv": out_root / "phase3_fragmentation.csv",
        "phase3_replenishment.csv": out_root / "phase3_replenishment.csv",
    }
    if sweep_rows:
        outputs["phase3_sweep.csv"] = out_root / "phase3_sweep.csv"
    outputs.update(line_artifacts)
    outputs.update(unresolved_artifacts)
    outputs.update(sweep_outputs)

    manifest = build_manifest(
        root=PROJECT_ROOT,
        processed=processed,
        config_path=PROJECT_ROOT / "configs" / "benchmark.json",
        outputs=outputs,
        experiment_id=EXPERIMENT_ID,
        scenario=f"{fit_scenario}->{hold_scenario}",
        split_manifest=Path(split["manifest_path"]),
        seeds={
            "optimizer": cfg.dataset.seed,
            "split": None,
            "split_note": "temporal order-level split is deterministic; no random seed is used",
            "annealing": "seeded from the same dataset seed",
        },
        evaluation_protocol={
            "fit": "earlier 70% of scenario-A orders (temporal, order-level)",
            "holdout": "later 30% of scenario-A orders; never passed to fitting or tuning",
            "outcome": "demand_weighted_depot_distance (metres) under quantity_aware picking",
            "feasibility": "independent Validator per layout; gate blocks publishable comparison",
            "selection": "fit demand-weighted travel; holdout scored once and not used to choose",
        },
        transformations=[
            "dataset/processed read-only",
            "scenario A split into A_FIT / A_HOLDOUT; demand_summary and sku_affinity recomputed per view",
            "no constraint, geometry or inventory table is altered by the split",
        ],
    )
    (out_root / "provenance.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return results


def main() -> None:
    ap = argparse.ArgumentParser(prog="run_phase3")
    ap.add_argument("--processed", default=str(PROJECT_ROOT.parent / "dataset" / "processed"))
    ap.add_argument("--out", default=str(PROJECT_ROOT / "outputs" / "phase3"))
    ap.add_argument("--fraction", type=float, default=0.7)
    ap.add_argument("--skip-sweep", action="store_true")
    args = ap.parse_args()

    results = run(Path(args.processed), Path(args.out), args.fraction, args.skip_sweep)
    print(json.dumps(
        {
            "split": results["split"]["checks"],
            "fit_feasibility": results["fit_run"]["feasibility_status"],
            "cells": results["two_by_two"]["cells"],
            "effects": results["two_by_two"]["effects"],
            "replenishment": results["replenishment"]["cells"],
            "selected": results["sweep"]["selected_by_fit_travel"],
        },
        indent=2,
    ))


if __name__ == "__main__":
    main()
