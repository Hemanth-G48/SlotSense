"""Phase-6 orchestration: baseline-vs-optimized route simulation + evaluation (canonical)."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from src.evaluation.metrics import (
    affinity_separation,
    compare_baseline_vs_optimized,
    summarize_layout,
)
from src.evaluation.fairness import fairness_checks, workload_identity
from src.evaluation.headroom import structural_headroom
from src.evaluation.diagnostics import diagnose_validation
from src.models.config import DEFAULT_SEPARATION_RADIUS_M
from src.models.entities import AssignmentType, SKU, StorageAssignment
from src.optimization.baseline import BASELINE_VARIANT_AS_SUPPLIED, BASELINE_VARIANTS
from src.routing.graph import build_graph, depot_distance_map, find_depot_node, location_distance_map
from src.routing.heuristics import ROUTING_STRATEGIES
from src.simulation.simulator import RouteResult, SimulationConfig, build_batches, simulate_layout, summarize
from src.validation.audit import write_constraint_audit, write_validation_checks
from src.validation.loader import load_compatibility_rules, load_skus, load_warehouse_from_locations
from src.validation.validator import validate_assignment

AS_SUPPLIED_VARIANT = BASELINE_VARIANT_AS_SUPPLIED


def _slotting_map(df: pd.DataFrame) -> dict[str, list[tuple[str, int]]]:
    """sku -> list of (location_id, qty) — preserves multi-bin inventory placement."""
    out: dict[str, list[tuple[str, int]]] = {}
    for _, r in df.iterrows():
        out.setdefault(r["sku_id"], []).append((r["location_id"], int(r["assigned_quantity"])))
    return out


def _to_assignments(slotting: dict[str, list[tuple[str, int]]]) -> list[StorageAssignment]:
    return [
        StorageAssignment(sku_id=s, location_id=loc, assigned_quantity=q, assignment_type=AssignmentType.OPTIMIZED)
        for s, spans in slotting.items()
        for loc, q in spans
    ]


def _primary_bins(slotting: dict[str, list[tuple[str, int]]]) -> dict[str, str]:
    return {sku: sorted({loc for loc, _q in spans})[0] for sku, spans in slotting.items() if spans}


def _pair_distance(location_dist, a: str, b: str) -> float:
    key = (a, b) if a <= b else (b, a)
    value = location_dist.get(key)
    return float("inf") if value is None else float(value)


def _write_route_stops(
    order_items: pd.DataFrame,
    slotting: dict[str, list[tuple[str, int]]],
    results: list[RouteResult],
    cfg: SimulationConfig,
    depot: str,
    path: Path,
    layout: str,
) -> None:
    """Write the ordered stop sequence and leg distances used by the simulator."""
    batches = build_batches(order_items, cfg.batch_size)
    sku_locations = {sku: {loc for loc, _q in spans} for sku, spans in slotting.items()}
    rows = []
    for result, batch in zip(results, batches):
        batch_skus = sorted(set(batch["sku_id"]))
        cumulative = 0.0
        for seq, (node, leg) in enumerate(zip(result.route, (0.0, *result.legs))):
            cumulative += leg
            if node == depot:
                skus = ""
            else:
                skus = ";".join(s for s in batch_skus if node in sku_locations.get(s, set()))
            rows.append({
                "batch_id": result.batch_id,
                "layout": layout,
                "sequence": seq,
                "location_id": node,
                "skus": skus,
                "leg_distance_m": round(leg, 3),
                "cumulative_distance_m": round(cumulative, 3),
            })
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)


EXECUTION_OK = "OK"
EVAL_OK = "OK"
EVAL_BLOCKED_INFEASIBLE = "BLOCKED_INFEASIBLE_LAYOUT"


def _violations_by_rule(result) -> dict[str, int]:
    counts: dict[str, int] = {}
    for v in result.violations:
        counts[v.rule_id] = counts.get(v.rule_id, 0) + 1
    return dict(sorted(counts.items()))


def _layout_feasibility(result) -> dict:
    """Independent validator verdict for one layout, with the evidence behind it."""
    return {
        "feasibility_status": "FEASIBLE" if result.is_feasible else "INFEASIBLE",
        "is_feasible": result.is_feasible,
        "n_violations": len(result.violations),
        "violations_by_rule": _violations_by_rule(result),
        "checks_run": result.checks_run,
        "top_violations": [v.reason for v in result.violations[:8]],
    }


def run_phase6(
    processed: Path,
    scenario: str = "A",
    out: Path | None = None,
    optimized_path: Path | None = None,
    affinity_scenario: str = "C",
    separation_radius_m: float | None = None,
    baseline_path: Path | None = None,
    baseline_variant: str = "as_supplied",
    baseline_repair: dict | None = None,
    baseline_note: str | None = None,
    routing_strategy: str = "nearest_neighbor",
    batch_size: int = 5,
    pick_time_basis: str = "order_line",
) -> dict:
    """Baseline-vs-optimized simulation + evaluation.

    ``baseline_path`` selects the baseline layout being evaluated; it defaults to the canonical
    ``storage_assignments_baseline.csv``, i.e. exactly the pre-existing behaviour. A caller that
    has repaired the baseline for feasibility (``src.optimization.baseline``) passes that file
    here and labels it with ``baseline_variant``; the gate is unchanged and still validates both
    layouts independently before any comparison is published.

    When a repaired baseline is evaluated, the as-supplied baseline's metrics are computed too
    and published under ``diagnostic_baseline`` (``diagnostic_only: true``), so the cost of
    repairing — and the difference between the two baselines — stays visible.
    """
    radius = (
        DEFAULT_SEPARATION_RADIUS_M
        if separation_radius_m is None
        else float(separation_radius_m)
    )
    if baseline_variant not in BASELINE_VARIANTS:
        raise ValueError(
            f"baseline_variant must be one of {BASELINE_VARIANTS}, got {baseline_variant!r}"
        )
    if routing_strategy not in ROUTING_STRATEGIES:
        raise ValueError(
            f"routing_strategy must be one of {sorted(ROUTING_STRATEGIES)}, got {routing_strategy!r}"
        )
    if int(batch_size) <= 0:
        raise ValueError(f"batch_size must be positive, got {batch_size}")
    if pick_time_basis not in ("order_line", "stop"):
        raise ValueError(
            f"pick_time_basis must be 'order_line' or 'stop', got {pick_time_basis!r}"
        )
    if baseline_variant != AS_SUPPLIED_VARIANT and baseline_path is None:
        raise ValueError(
            "a repaired baseline_variant requires baseline_path: the as-supplied file is not "
            "the layout that variant names"
        )
    locations_df = pd.read_csv(processed / "locations.csv")
    products_df = pd.read_csv(processed / "products.csv")
    rules_df = pd.read_csv(processed / "compatibility_rules.csv")
    inventory_df = pd.read_csv(processed / "inventory.csv")
    demand_df = pd.read_csv(processed / "demand_summary.csv")
    affinity_df = pd.read_csv(processed / "sku_affinity.csv")

    skus: dict[str, SKU] = load_skus(products_df)
    wh = load_warehouse_from_locations(locations_df)
    comp = load_compatibility_rules(rules_df)
    inventory = inventory_df.groupby("sku_id")["quantity_on_hand"].sum().to_dict()

    # Demand / ABC for the evaluated scenario (the workload scenario), affinity for the
    # association scenario the optimizer actually used.
    demand_rows = demand_df[demand_df["scenario_id"] == scenario]
    demand = dict(zip(demand_rows["sku_id"], demand_rows["demand_frequency"].astype(float)))
    abc_classes = dict(zip(demand_rows["sku_id"], demand_rows["abc_class"]))

    # Golden band comes from the topology's ergonomic labels, not a UI constant.
    golden_levels = tuple(sorted({
        loc.shelf_level for loc in wh.locations.values()
        if getattr(loc.ergonomic_zone, "value", "") == "golden"
    })) or (1, 2)

    aff = affinity_df[affinity_df["scenario_id"] == affinity_scenario]
    pair_weights: dict[tuple[str, str], float] = {}
    for _, r in aff.iterrows():
        if r["co_count"] < 2 or r["lift"] < 1:
            continue
        key = tuple(sorted((str(r["sku_a"]), str(r["sku_b"]))))
        pair_weights[key] = max(pair_weights.get(key, 0.0), float(r["co_count"]))

    # Build aisle network graph + depot distances (deterministic).
    graph = build_graph(processed / "location_graph.csv")
    depot = find_depot_node(graph)
    if depot is None:
        raise ValueError("no depot node found in location_graph.csv")
    depot_dist = depot_distance_map(graph, depot)

    # Slottings
    as_supplied_path = processed / "storage_assignments_baseline.csv"
    baseline_source = Path(baseline_path) if baseline_path is not None else as_supplied_path
    baseline_df = pd.read_csv(baseline_source)
    project_root = Path(__file__).resolve().parent.parent.parent
    opt_path = (
        Path(optimized_path)
        if optimized_path is not None
        else project_root / "outputs" / "optimized" / "optimized_assignments.csv"
    )
    if not opt_path.exists():
        raise FileNotFoundError(f"optimized assignments not found: {opt_path}")
    optimized_df = pd.read_csv(opt_path)

    # The as-supplied baseline is only re-simulated when it is NOT the layout under evaluation;
    # its metrics are published as a labelled diagnostic so the two baselines are comparable.
    compare_as_supplied = (
        baseline_variant != AS_SUPPLIED_VARIANT and baseline_source != as_supplied_path
    )
    as_supplied_df = pd.read_csv(as_supplied_path) if compare_as_supplied else None

    baseline_slot = _slotting_map(baseline_df)
    optimized_slot = _slotting_map(optimized_df)
    as_supplied_slot = _slotting_map(as_supplied_df) if as_supplied_df is not None else None

    # -- FEASIBILITY GATE ------------------------------------------------------
    # Both layouts are validated by the independent validator BEFORE anything is scored. A
    # layout with any hard violation cannot be compared against another one: the comparison
    # would mix "this layout is invalid" with "this layout is better", which is not evidence.
    base_assign = _to_assignments(baseline_slot)
    opt_assign = _to_assignments(optimized_slot)
    base_val = validate_assignment(
        base_assign, skus, wh, comp, inventory, separation_radius_m=radius
    )
    opt_val = validate_assignment(
        opt_assign, skus, wh, comp, inventory, separation_radius_m=radius
    )
    blocked_layouts = []
    if not base_val.is_feasible:
        blocked_layouts.append("baseline")
    if not opt_val.is_feasible:
        blocked_layouts.append("optimized")
    gate_blocked = bool(blocked_layouts)
    feasibility = {
        "baseline": _layout_feasibility(base_val),
        "optimized": _layout_feasibility(opt_val),
    }

    # Same real inventory totals are assumed for BOTH layouts (conservation is validator-checked).
    order_items = pd.read_csv(processed / "order_items.csv")
    orders = pd.read_csv(processed / "orders.csv")
    sc_orders = set(orders[orders["scenario_id"] == scenario]["order_id"])
    order_items = order_items[order_items["order_id"].isin(sc_orders)].reset_index(drop=True)
    workload = workload_identity(order_items, scenario=scenario)

    cfg = SimulationConfig(
        routing_strategy=routing_strategy,
        batch_size=int(batch_size),
        pick_time_basis=pick_time_basis,
    )

    # Precompute pairwise location distances for the involved bins (deterministic, sorted).
    slot_sets = list(baseline_slot.values()) + list(optimized_slot.values())
    if as_supplied_slot is not None:
        slot_sets += list(as_supplied_slot.values())
    all_bins = sorted({loc for spans in slot_sets for loc, _ in spans})
    location_dist = location_distance_map(graph, all_bins)

    base_slot_locs = {sku: [l for l, _q in spans] for sku, spans in baseline_slot.items()}
    opt_slot_locs = {sku: [l for l, _q in spans] for sku, spans in optimized_slot.items()}

    base_results = simulate_layout(order_items, base_slot_locs, location_dist, depot_dist, cfg, depot)
    opt_results = simulate_layout(order_items, opt_slot_locs, location_dist, depot_dist, cfg, depot)
    base_sum = summarize(base_results, cfg)
    opt_sum = summarize(opt_results, cfg)

    base_affinity = affinity_separation(pair_weights, _primary_bins(baseline_slot), lambda a, b: _pair_distance(location_dist, a, b))
    opt_affinity = affinity_separation(pair_weights, _primary_bins(optimized_slot), lambda a, b: _pair_distance(location_dist, a, b))

    runtime = 0.0
    sum_path = opt_path.parent / "optimization_summary.json"
    if sum_path.exists():
        runtime = json.loads(sum_path.read_text()).get("runtime_sec", 0.0)

    base_metrics = summarize_layout(
        baseline_slot,
        skus,
        wh.locations,
        base_sum,
        base_val,
        runtime_sec=None,
        inventory=inventory,
        demand=demand,
        abc_classes=abc_classes,
        golden_levels=golden_levels,
        extra={**base_affinity, "diagnostic_only": gate_blocked},
    )
    opt_metrics = summarize_layout(
        optimized_slot,
        skus,
        wh.locations,
        opt_sum,
        opt_val,
        runtime_sec=runtime,
        inventory=inventory,
        demand=demand,
        abc_classes=abc_classes,
        golden_levels=golden_levels,
        extra={**opt_affinity, "diagnostic_only": gate_blocked},
    )
    table = compare_baseline_vs_optimized(base_metrics, opt_metrics)
    for row in table:
        row["diagnostic_only"] = gate_blocked

    # -- the as-supplied baseline, when a repaired one is what we evaluated -------
    # This is not part of the comparison. It exists so a reader can see what repairing cost
    # (e.g. how much of the travel delta it consumed) and what the illegal layout scored.
    diagnostic_baseline = None
    if as_supplied_slot is not None:
        as_assign = _to_assignments(as_supplied_slot)
        as_val = validate_assignment(
            as_assign, skus, wh, comp, inventory, separation_radius_m=radius
        )
        as_location_dist = location_dist  # superset of both layouts' bins
        as_results = simulate_layout(
            order_items,
            {sku: [l for l, _q in spans] for sku, spans in as_supplied_slot.items()},
            as_location_dist,
            depot_dist,
            cfg,
            depot,
        )
        as_sum = summarize(as_results, cfg)
        as_affinity = affinity_separation(
            pair_weights,
            _primary_bins(as_supplied_slot),
            lambda a, b: _pair_distance(as_location_dist, a, b),
        )
        as_metrics = summarize_layout(
            as_supplied_slot,
            skus,
            wh.locations,
            as_sum,
            as_val,
            runtime_sec=None,
            inventory=inventory,
            demand=demand,
            abc_classes=abc_classes,
            golden_levels=golden_levels,
            extra={**as_affinity, "diagnostic_only": True},
        )
        diagnostic_baseline = {
            "baseline_variant": AS_SUPPLIED_VARIANT,
            "diagnostic_only": True,
            "source": str(as_supplied_path),
            "feasibility": _layout_feasibility(as_val),
            "metrics": as_metrics,
            "note": (
                "As-supplied baseline: NOT part of the published comparison. Kept so the "
                "difference between the illegal input layout and the repaired feasible "
                "baseline stays visible."
            ),
            "delta_vs_evaluated_baseline": {
                "total_travel_distance_m": round(
                    base_metrics["total_travel_distance_m"] - as_metrics["total_travel_distance_m"], 3
                ),
                "total_route_time_sec": round(
                    base_metrics["total_route_time_sec"] - as_metrics["total_route_time_sec"], 3
                ),
                "throughput_orders_per_hr": round(
                    base_metrics["throughput_orders_per_hr"] - as_metrics["throughput_orders_per_hr"], 3
                ),
                "constraint_violations": (
                    base_metrics["constraint_violations"] - as_metrics["constraint_violations"]
                ),
            },
        }

    # -- Phase 4 evidence: headroom, rejection diagnostics, fair-comparison identity ----
    headroom = {
        "baseline": structural_headroom(base_val),
        "optimized": structural_headroom(opt_val),
    }
    feasibility["baseline"]["headroom"] = headroom["baseline"]
    feasibility["optimized"]["headroom"] = headroom["optimized"]
    diagnostics = {
        "baseline": diagnose_validation(base_val, "baseline"),
        "optimized": diagnose_validation(opt_val, "optimized"),
    }
    integrity = fairness_checks(
        workload=workload,
        baseline_metrics=base_metrics,
        optimized_metrics=opt_metrics,
        baseline_feasible=base_val.is_feasible,
        optimized_feasible=opt_val.is_feasible,
        inventory_units=sum(inventory.values()),
        routing_strategy=cfg.routing_strategy,
        batch_size=cfg.batch_size,
        gate_blocked=gate_blocked,
        blocked_layouts=blocked_layouts,
    )

    result = {
        "dataset": str(processed),
        "scenario": scenario,
        "affinity_scenario": affinity_scenario,
        "execution_status": EXECUTION_OK,
        "evaluation_status": EVAL_BLOCKED_INFEASIBLE if gate_blocked else EVAL_OK,
        "separation_radius_m": radius,
        # -- baseline provenance ------------------------------------------------
        "baseline_variant": baseline_variant,
        "baseline_source": str(baseline_source),
        "baseline_repair": baseline_repair,
        # One line saying how the baseline got to be legal (objective disabled), so a reader of
        # this file alone never has to infer whether the baseline was optimised.
        "baseline_note": baseline_note or (baseline_repair or {}).get("note"),
        # -- gate ---------------------------------------------------------------
        "feasibility": feasibility,
        "comparison_valid": not gate_blocked,
        "diagnostic_only": gate_blocked,
        "blocked_layouts": blocked_layouts,
        "inventory_units": sum(inventory.values()),
        "skus_with_inventory": len(inventory),
        "baseline": base_metrics,
        "optimized": opt_metrics,
        # A blocked run publishes no comparison: the table still exists for diagnosis, under an
        # explicit key, and every row is labelled diagnostic_only.
        "comparison": [] if gate_blocked else table,
        "diagnostic_comparison": table if gate_blocked else None,
        "diagnostic_baseline": diagnostic_baseline,
        "assumptions": {
            "routing_strategy": cfg.routing_strategy,
            "batch_size_orders": cfg.batch_size,
            "picker_speed_mps": cfg.picker_speed_mps,
            "pick_time_sec_per_line": cfg.pick_time_sec,
            "setup_time_sec_per_batch": cfg.setup_time_sec,
            "golden_shelf_levels": list(golden_levels),
            "cube_utilization_basis": "on-hand assigned quantity x SKU bounding-box volume / usable bin volume (volume approximation, not 3-D packing)",
            "throughput_definition": "orders completed / total pick-cycle hours (travel + pick + setup)",
            "affinity_weighting": "co-occurrence count for pairs with co_count >= 2 and lift >= 1",
            "depot_node": depot,
            "separation_radius_m": radius,
        },
        "route_breakdown": {"baseline": base_sum, "optimized": opt_sum},
        "workload": workload,
        "simulation": {
            "routing_strategy": cfg.routing_strategy,
            "batch_size_orders": cfg.batch_size,
            "picker_speed_mps": cfg.picker_speed_mps,
            "pick_time_sec_per_line": cfg.pick_time_sec,
            "pick_time_sec_per_stop": cfg.pick_time_stop_sec,
            "setup_time_sec_per_batch": cfg.setup_time_sec,
            "pick_time_basis": cfg.pick_time_basis,
        },
        "integrity": integrity,
        "headroom": headroom,
        "diagnostics": diagnostics,
        "notes": {
            "identical_orders_geometry_routing": True,
            "routing_strategy": cfg.routing_strategy,
            "batch_size": cfg.batch_size,
            "baseline_was_validated": True,
            "baseline_constraint_violations": len(base_val.violations),
            "optimized_constraint_violations": len(opt_val.violations),
            "baseline_feasibility_status": feasibility["baseline"]["feasibility_status"],
            "optimized_feasibility_status": feasibility["optimized"]["feasibility_status"],
            "baseline_violations_by_rule": feasibility["baseline"]["violations_by_rule"],
            "optimized_violations_by_rule": feasibility["optimized"]["violations_by_rule"],
            "baseline_rule_checks": base_val.checks_run,
            "optimized_rule_checks": opt_val.checks_run,
            "baseline_inventory_conservation_violations": sum(1 for v in base_val.violations if v.rule_id.startswith("INV")),
            "optimized_inventory_conservation_violations": sum(1 for v in opt_val.violations if v.rule_id.startswith("INV")),
            "same_inventory_units": sum(inventory.values()),
            "comparison_published_as_valid_evidence": not gate_blocked,
            "comparison_is_diagnostic_only": gate_blocked,
            "gate_blocked_layouts": blocked_layouts,
            "baseline_variant": baseline_variant,
            "baseline_source": str(baseline_source),
            "baseline_repaired_for_feasibility": baseline_variant != AS_SUPPLIED_VARIANT,
            "as_supplied_baseline_published_as": (
                "diagnostic_baseline" if diagnostic_baseline is not None else "baseline"
            ),
        },
    }
    if gate_blocked:
        result["blocked_reason"] = (
            "Independent validation found hard violations in "
            + " and ".join(blocked_layouts)
            + "; a baseline-vs-optimized comparison is not valid evidence for an infeasible layout."
        )
    if out is not None:
        out.mkdir(parents=True, exist_ok=True)
        route_cols = ["batch_id", "n_orders", "n_locations", "distance_m", "travel_time_sec", "pick_time_sec", "cycle_time_sec"]
        base_df = pd.DataFrame([{k: getattr(r, k) for k in route_cols} for r in base_results])
        opt_df = pd.DataFrame([{k: getattr(r, k) for k in route_cols} for r in opt_results])
        base_df["layout"] = "baseline"
        opt_df["layout"] = "optimized"
        pd.concat([base_df, opt_df], ignore_index=True).to_csv(out / "pick_routes.csv", index=False)
        _write_route_stops(order_items, baseline_slot, base_results, cfg, depot, out / "pick_route_stops_baseline.csv", "baseline")
        _write_route_stops(order_items, optimized_slot, opt_results, cfg, depot, out / "pick_route_stops_optimized.csv", "optimized")
        metrics_df = pd.DataFrame(table)
        metrics_df["diagnostic_only"] = gate_blocked
        metrics_df.to_csv(out / "optimization_metrics.csv", index=False)
        write_validation_checks(base_val, out / "validation_checks_baseline.csv")
        write_validation_checks(opt_val, out / "validation_checks_optimized.csv")
        write_constraint_audit(base_assign, base_val, out / "constraint_audit_baseline.csv")
        write_constraint_audit(opt_assign, opt_val, out / "constraint_audit_optimized.csv")
        if diagnostic_baseline is not None:
            # The illegal input layout is exported for inspection, never for comparison.
            write_constraint_audit(
                as_assign, as_val, out / "constraint_audit_baseline_as_supplied.csv"
            )
        (out / "evaluation_summary.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result

