"""Phase-5 orchestration over the canonical dataset (dataset/processed).

The summary this module writes separates three things that used to be conflated:

``execution_status``        OK | ERROR          — did the process complete?
``feasibility_status``      FEASIBLE | INFEASIBLE — the INDEPENDENT validator's verdict on the
                            returned layout (``feasibility`` is kept as a boolean alias so
                            existing callers keep working).
``assignment_completeness`` units placed / units required, with the SKUs still unresolved.

Repair statistics and the per-rule violation breakdown are reported alongside them, so a run
that could not reach feasibility says so instead of presenting itself as an answer.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src.models.config import Config
from src.models.io import write_assignments_csv
from src.validation.loader import (
    load_assignments,
    load_compatibility_rules,
    load_inventory,
    load_skus,
    load_warehouse_from_locations,
)
from src.validation.validator import Validator

from .baseline import (
    BASELINE_SOURCE_FILENAME,
    BASELINE_VARIANT_AS_SUPPLIED,
    BaselineVariant,
)
from .objective import Objective, build_affinity_penalty
from .optimizer import REPAIR_SEVERITY_WEIGHT, OptimizerConfig, SlottingOptimizer
from .replenishment import DEFAULT_COVER_DAYS, DEFAULT_WINDOW_DAYS, replenishment_travel

EXECUTION_OK = "OK"
EXECUTION_ERROR = "ERROR"


def run_phase5(
    processed: Path,
    config: Config,
    out: Path,
    baseline_variant: BaselineVariant | None = None,
    fit_scenario: str = "A",
    affinity_scenario: str | None = None,
    optimizer_neighborhood: str = "legacy",
) -> dict:
    """Optimise a layout from a processed tree.

    ``fit_scenario`` selects which demand history drives placement (default ``"A"``,
    the pre-Phase-3 behaviour). For a fit/holdout tree, pass the view's scenario
    (``"A_FIT"``) so the optimizer cannot see holdout demand (D46).
    ``affinity_scenario`` defaults to the fit scenario, so affinity is also mined
    on fit data only.
    """
    out.mkdir(parents=True, exist_ok=True)
    try:
        return _run_phase5(processed, config, out, baseline_variant,
                           fit_scenario=fit_scenario,
                           affinity_scenario=affinity_scenario or fit_scenario,
                           optimizer_neighborhood=optimizer_neighborhood)
    except Exception as exc:  # noqa: BLE001 - the summary must exist even when the run died
        # A crash is not an infeasible layout: nothing was validated, so feasibility is left
        # undetermined (``None``) rather than being reported as INFEASIBLE.
        payload = {
            "dataset": str(processed),
            "algorithm": _algorithm_label(),
            "execution_status": EXECUTION_ERROR,
            "error": f"{type(exc).__name__}: {exc}",
            "feasibility": None,
            "feasibility_status": None,
            "feasibility_evaluated": False,
            "assignment_completeness": None,
            "objective": None,
            "repair": None,
            "globally_optimal": False,
        }
        if baseline_variant is not None:
            payload.update(baseline_variant.to_summary())
        (out / "optimization_summary.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        raise


def _algorithm_label() -> str:
    return (
        "greedy (velocity-ordered, inventory-conserving, beam/CAT-01-aware) "
        "+ constraint-safe repair + simulated annealing"
    )


def _replenishment_function(processed: Path, scenario: str, warehouse):
    """Build Psi_R from the view's own demand, or return None when demand is absent.

    The window is the dataset's order history, and the demand used is the *fit*
    scenario only — the same rule the layout itself is fitted under, so the objective
    cannot see holdout demand.
    """
    orders_path = processed / "orders.csv"
    items_path = processed / "order_items.csv"
    if not (orders_path.exists() and items_path.exists()):
        return None

    orders = pd.read_csv(orders_path)
    if "scenario_id" not in orders.columns:
        return None
    ids = set(orders.loc[orders["scenario_id"] == scenario, "order_id"])
    if not ids:
        return None
    items = pd.read_csv(items_path)
    scoped = items[items["order_id"].isin(ids)]
    units = scoped.groupby("sku_id")["quantity"].sum().astype(float).to_dict()
    distance = {
        location_id: float(loc.distance_to_dispatch_m)
        for location_id, loc in warehouse.locations.items()
    }

    def fn(assignments) -> float:
        return replenishment_travel(
            ((a.sku_id, a.location_id, a.assigned_quantity) for a in assignments),
            units,
            distance,
        )

    return fn


def _run_phase5(
    processed: Path,
    config: Config,
    out: Path,
    baseline_variant: BaselineVariant | None = None,
    fit_scenario: str = "A",
    affinity_scenario: str = "A",
    optimizer_neighborhood: str = "legacy",
) -> dict:
    locations = pd.read_csv(processed / "locations.csv")
    products = pd.read_csv(processed / "products.csv")
    rules = pd.read_csv(processed / "compatibility_rules.csv")
    inventory = pd.read_csv(processed / "inventory.csv")
    baseline_rows = pd.read_csv(processed / "storage_assignments_baseline.csv")
    demand = pd.read_csv(processed / "demand_summary.csv")
    affinity = pd.read_csv(processed / "sku_affinity.csv")

    wh = load_warehouse_from_locations(locations)
    skus = load_skus(products)
    comp = load_compatibility_rules(rules)
    inv = load_inventory(inventory)
    baseline = load_assignments(baseline_rows)

    # ABC + demand from the canonical demand_summary (scenario A)
    dA = demand[demand["scenario_id"] == fit_scenario]
    abc_classes = dict(zip(dA["sku_id"], dA["abc_class"]))
    demand_map = dict(zip(dA["sku_id"], dA["demand_frequency"].astype(float)))

    # Affinity penalty from canonical sku_affinity (scenario C)
    affC = affinity[affinity["scenario_id"] == affinity_scenario]
    affinity_penalty = build_affinity_penalty(affC)

    # Replenishment inputs (D47): units demanded in the fit view and depot distances.
    # The callable is evaluated only when epsilon != 0, so the Phase 2 objective is
    # unchanged at the default weight.
    replenishment_fn = _replenishment_function(processed, fit_scenario, wh)
    if config.optimization.epsilon > 0 and replenishment_fn is None:
        raise ValueError(
            "epsilon > 0 requires orders.csv and order_items.csv in the processed tree "
            f"({processed}); replenishment cannot be scored without demand"
        )

    # One radius, threaded to both sides of the problem: the placer that must respect CAT-01
    # and the independent validator that judges it.
    radius = config.separation_radius_m
    validator = Validator(
        skus, wh, comp, inventory=inv,
        separation_radius_m=radius,
    )
    objective = Objective(
        alpha=config.optimization.alpha,
        beta=config.optimization.beta,
        gamma=config.optimization.gamma,
        delta=config.optimization.delta,
        epsilon=config.optimization.epsilon,
    )
    opt_cfg = OptimizerConfig(
        seed=config.dataset.seed,
        neighborhood=optimizer_neighborhood,
    )

    optimizer = SlottingOptimizer(
        warehouse=wh,
        skus=skus,
        abc_classes=abc_classes,
        validator=validator,
        inventory=inv,
        affinity_penalty=affinity_penalty,
        objective=objective,
        demand=demand_map,
        cfg=opt_cfg,
        initial_assignments=baseline,
        separation_radius_m=radius,
        compatibility_rules=comp,
        replenishment_fn=replenishment_fn,
    )
    optimized, log = optimizer.optimize()

    # Feasibility is derived ONLY from the independent validator, never from the optimizer's
    # own bookkeeping. This is the single source of truth for the status fields below.
    result = validator.validate(optimized)

    write_assignments_csv(optimized, out / "optimized_assignments.csv")

    baseline_result = validator.validate(baseline)
    # The comparison baseline is the *variant* (repaired to feasibility when the as-supplied
    # one is illegal). The optimizer above still starts from the as-supplied baseline because
    # its starter selection is part of the optimized layout this card may not change.
    repaired_variant = baseline_variant is not None and baseline_variant.is_repaired
    reference = baseline_variant.assignments if repaired_variant else baseline
    reference_result = validator.validate(reference) if repaired_variant else baseline_result
    as_supplied_score = (
        objective.evaluate(baseline, skus, wh, demand_map, affinity_penalty) if baseline else None
    )
    reference_score = (
        objective.evaluate(reference, skus, wh, demand_map, affinity_penalty)
        if repaired_variant
        else as_supplied_score
    )
    # Components are reported for both layouts regardless of epsilon: a metric nobody
    # weights is still a metric, and the trade-off needs its value visible.
    rep_final = replenishment_fn(optimized) if replenishment_fn is not None else None
    rep_reference = replenishment_fn(reference) if replenishment_fn is not None else None
    final_components = objective.components(
        optimized, skus, wh, demand_map, affinity_penalty, rep_final
    )
    reference_components = objective.components(
        reference, skus, wh, demand_map, affinity_penalty, rep_reference
    )
    if baseline_variant is not None:
        variant_summary = baseline_variant.to_summary()
    else:
        variant_summary = {
            "baseline_variant": BASELINE_VARIANT_AS_SUPPLIED,
            "baseline_source": str(processed / BASELINE_SOURCE_FILENAME),
            "baseline_as_supplied_source": str(processed / BASELINE_SOURCE_FILENAME),
            "baseline_repair": None,
            "baseline_note": "Baseline used exactly as supplied; no repair was requested.",
        }

    placed_by_sku: dict[str, int] = defaultdict(int)
    for a in optimized:
        placed_by_sku[a.sku_id] += a.assigned_quantity
    completeness = _assignment_completeness(inv, placed_by_sku)
    by_rule = _violations_by_rule(result)

    summary = {
        "dataset": str(processed),
        "algorithm": _algorithm_label(),
        # -- which baseline this run is measured against ------------------------
        **variant_summary,
        # -- status vocabulary -------------------------------------------------
        "execution_status": EXECUTION_OK,
        "feasibility_status": "FEASIBLE" if result.is_feasible else "INFEASIBLE",
        "feasibility": result.is_feasible,  # back-compat boolean alias
        "assignment_completeness": completeness,
        "objective": {
            "value": log.final_score,
            "baseline_value": reference_score,
            "baseline_value_as_supplied": as_supplied_score,
            "starter_value": log.starter_score,
            "per_rule_violations": by_rule,
            "violation_severity_score": _violation_severity_score(result),
            "components": final_components,
            "baseline_components": reference_components,
            "globally_optimal": False,
        },
        "repair": log.repair,
        # -- existing keys (kept for callers and dashboards) --------------------
        "objective_weights": {
            "alpha": objective.alpha,
            "beta": objective.beta,
            "gamma": objective.gamma,
            "delta": objective.delta,
            "epsilon": objective.epsilon,
        },
        "replenishment": (
            {
                "travel_m": round(rep_final, 3) if rep_final is not None else None,
                "baseline_travel_m": (
                    round(rep_reference, 3) if rep_reference is not None else None
                ),
                "weight_epsilon": objective.epsilon,
                "cover_days": DEFAULT_COVER_DAYS,
                "window_days": DEFAULT_WINDOW_DAYS,
                "demand_view": fit_scenario,
                "model": "trips(s,b)=ceil(on_hand/lot(s)); travel=sum 2*trips*depot_distance; "
                         "zero-demand SKUs make no trips",
            }
            if replenishment_fn is not None
            else {"status": "unavailable", "reason": "no orders.csv/order_items.csv in the processed tree"}
        ),
        "separation_radius_m": log.separation_radius_m,
        "n_assignments": len(optimized),
        "n_bins_used": log.n_bins_used,
        "n_skus_with_inventory": len(inv),
        "inventory_units": log.inventory_units,
        "units_placed": sum(a.assigned_quantity for a in optimized),
        "units_unplaced": log.units_unplaced,
        "unplaced_skus": [u.to_dict() for u in log.unplaced_skus],
        "n_violations": len(result.violations),
        "violations_by_rule": by_rule,
        # -- baseline feasibility (the variant this run is compared against) ----
        "baseline_feasibility": reference_result.is_feasible,
        "baseline_feasibility_status": "FEASIBLE" if reference_result.is_feasible else "INFEASIBLE",
        "baseline_violations_by_rule": _violations_by_rule(reference_result),
        "baseline_n_violations": len(reference_result.violations),
        "baseline_checks_run": reference_result.checks_run,
        # -- as-supplied baseline, kept so the difference is visible ------------
        "baseline_objective": reference_score,
        "baseline_objective_as_supplied": as_supplied_score,
        "baseline_feasibility_as_supplied": baseline_result.is_feasible,
        "baseline_feasibility_status_as_supplied": (
            "FEASIBLE" if baseline_result.is_feasible else "INFEASIBLE"
        ),
        "baseline_violations_by_rule_as_supplied": _violations_by_rule(baseline_result),
        "baseline_n_violations_as_supplied": len(baseline_result.violations),
        "starter_objective": log.starter_score,
        "starter_feasible": log.starter_feasible,
        "final_objective": log.final_score,
        "objective_improvement_pct": (
            round((reference_score - log.final_score) / reference_score * 100, 3)
            if reference_score
            else None
        ),
        "objective_improvement_pct_vs_as_supplied": (
            round((as_supplied_score - log.final_score) / as_supplied_score * 100, 3)
            if as_supplied_score
            else None
        ),
        "starter_beam_violations": log.starter_beam_violations,
        "separation_grid": log.separation_stats,
        "moves_evaluated": log.n_moves_evaluated,
        "moves_accepted": log.n_moves_accepted,
        "runtime_sec": round(log.runtime_sec, 3),
        "stopping_reason": log.stopping_reason,
        "globally_optimal": False,
    }
    if not result.is_feasible:
        summary["top_violations"] = [v.reason for v in result.violations[:8]]
    (out / "optimization_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    _append_run_history(out, summary, config)
    return summary


def _assignment_completeness(inventory: dict[str, int], placed: dict[str, int]) -> dict:
    """Units placed / units required, naming every SKU whose quantity does not match.

    ``units_placed`` counts assignment rows (the validator separately rejects duplicate
    (SKU, bin) pairs), so over-storing shows up here as well as in INV-01.
    """
    required = int(sum(inventory.values()))
    units_placed = int(sum(placed.values()))
    unresolved = sorted(
        sku
        for sku in set(inventory) | set(placed)
        if placed.get(sku, 0) != inventory.get(sku, 0)
    )
    return {
        "units_required": required,
        "units_placed": units_placed,
        "units_unplaced": max(0, required - units_placed),
        "complete": units_placed == required and not unresolved,
        "completeness_pct": round(100.0 * units_placed / required, 2) if required else 100.0,
        "unresolved_skus": unresolved,
    }


def _violation_severity_score(result) -> int:
    return sum(REPAIR_SEVERITY_WEIGHT.get(v.severity, 10) for v in result.violations)


def _violations_by_rule(result) -> dict[str, int]:
    """Per-rule violation counts, so a run reports *which* constraint bound it."""
    counts: dict[str, int] = {}
    for v in result.violations:
        counts[v.rule_id] = counts.get(v.rule_id, 0) + 1
    return dict(sorted(counts.items()))


def _append_run_history(out: Path, summary: dict, config: Config, keep: int = 20) -> None:
    """Record real completed runs so the dashboard can compare them (newest last)."""
    path = out / "run_history.json"
    history: list[dict] = []
    if path.exists():
        try:
            history = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(history, list):
                history = []
        except (json.JSONDecodeError, ValueError):
            history = []
    entry = {
        "run_id": len(history) + 1,
        "completed_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "algorithm": summary.get("algorithm"),
        "objective_weights": summary.get("objective_weights"),
        "seed": config.dataset.seed,
        "separation_radius_m": summary.get("separation_radius_m"),
        "baseline_variant": summary.get("baseline_variant"),
        "baseline_repair_termination": (summary.get("baseline_repair") or {}).get("termination_reason"),
        "execution_status": summary.get("execution_status"),
        "feasibility_status": summary.get("feasibility_status"),
        "feasibility": summary.get("feasibility"),
        "n_violations": summary.get("n_violations"),
        "violations_by_rule": summary.get("violations_by_rule"),
        "repair_termination": (summary.get("repair") or {}).get("termination_reason"),
        "repair_moves_accepted": (summary.get("repair") or {}).get("moves_accepted"),
        "units_placed": summary.get("units_placed"),
        "inventory_units": summary.get("inventory_units"),
        "units_unplaced": summary.get("units_unplaced"),
        "final_objective": summary.get("final_objective"),
        "objective_improvement_pct": summary.get("objective_improvement_pct"),
        "moves_evaluated": summary.get("moves_evaluated"),
        "moves_accepted": summary.get("moves_accepted"),
        "runtime_sec": summary.get("runtime_sec"),
        "stopping_reason": summary.get("stopping_reason"),
        "globally_optimal": summary.get("globally_optimal"),
    }
    history.append(entry)
    out.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(history[-keep:], indent=2), encoding="utf-8")
