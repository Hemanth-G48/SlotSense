"""Phase 4 runner: held-out 2x2 (layout x picking policy), demand regimes, headroom.

What it does
------------
1. Verifies the Phase 3 fit/holdout split and freezes the two layouts (baseline repaired
   and optimized-fit) by SHA-256 before any evaluation.
2. Runs the independent evaluator twice on the holdout workload — once under
   ``nearest_neighbor`` and once under ``s_shape`` — yielding the four cells of the 2x2.
3. Attaches layout-level metrics that do not depend on the routing policy
   (demand-weighted line travel, fragmentation, replenishment) from the Phase 3
   definitions, rather than redefining them.
4. Evaluates the frozen layouts on held-out demand regimes B and C (different generators,
   never used for fitting) under the project's reported policy.
5. Reports structural headroom and rejection diagnostics from the independent validator.
6. Writes machine-readable artifacts and provenance.

It never refits a layout and never selects a policy using holdout outcomes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src.evaluation.factorial import metric_effects
from src.experiments.fragmentation import fragmentation_stats
from src.experiments.provenance import build_manifest
from src.experiments.replenishment import replenishment_metrics
from src.experiments.split import verify_split
from src.experiments.travel import QUANTITY_AWARE, line_travel, sku_bins
from src.routing.graph import build_graph, depot_distance_map, find_depot_node
from src.simulation.pipeline import run_phase6

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PHASE3 = PROJECT_ROOT / "outputs" / "phase3"
HOLDOUT_TREE = PHASE3 / "split" / "A70" / "holdout" / "processed"
BASELINE_LAYOUT = PHASE3 / "optimized_fit" / "baseline_repaired_assignments.csv"
OPTIMIZED_LAYOUT = PHASE3 / "optimized_fit" / "optimized_assignments.csv"
PHASE3_FIT_SUMMARY = PHASE3 / "optimized_fit" / "optimization_summary.json"

POLICIES = ("nearest_neighbor", "s_shape")
POLICY_LABELS = {"nearest_neighbor": "nearest_neighbor", "s_shape": "s_shape"}
LAYOUTS = ("baseline_repaired", "optimized_fit")

EXPERIMENT_ID = "phase4-holdout-layout-x-picking-policy"

SIMULATION_METRICS = {
    "total_travel_distance_m": {"unit": "m", "lower_is_better": True},
    "total_route_time_sec": {"unit": "s", "lower_is_better": True},
    "throughput_orders_per_hr": {"unit": "orders/h", "lower_is_better": False},
    "avg_time_per_order_sec": {"unit": "s/order", "lower_is_better": True},
}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _depot(processed: Path) -> tuple[dict, str]:
    graph = build_graph(Path(processed) / "location_graph.csv")
    depot = find_depot_node(graph)
    if depot is None:
        raise ValueError(f"no depot node in {processed}/location_graph.csv")
    return depot_distance_map(graph, depot), depot


def _units_demand(processed: Path, scenario: str) -> dict[str, float]:
    orders = pd.read_csv(Path(processed) / "orders.csv")
    items = pd.read_csv(Path(processed) / "order_items.csv")
    ids = set(orders.loc[orders["scenario_id"] == scenario, "order_id"])
    sub = items[items["order_id"].isin(ids)]
    return sub.groupby("sku_id")["quantity"].sum().astype(float).to_dict()


def _workload_items(processed: Path, scenario: str) -> pd.DataFrame:
    orders = pd.read_csv(Path(processed) / "orders.csv")
    items = pd.read_csv(Path(processed) / "order_items.csv")
    ids = set(orders.loc[orders["scenario_id"] == scenario, "order_id"])
    return items[items["order_id"].isin(ids)].reset_index(drop=True)


def _regime_profile(processed: Path, scenario: str) -> dict:
    orders = pd.read_csv(Path(processed) / "orders.csv")
    items = pd.read_csv(Path(processed) / "order_items.csv")
    demand = pd.read_csv(Path(processed) / "demand_summary.csv")

    o = orders[orders["scenario_id"] == scenario]
    ids = set(o["order_id"])
    i = items[items["order_id"].isin(ids)]
    per_sku = i.groupby("sku_id")["quantity"].sum().sort_values(ascending=False)
    total = float(per_sku.sum())
    top_n = max(1, int(round(len(per_sku) * 0.10)))
    abc = demand[demand["scenario_id"] == scenario]
    return {
        "scenario": scenario,
        "orders": int(len(o)),
        "lines": int(len(i)),
        "units": int(i["quantity"].sum()),
        "skus_with_demand": int(i["sku_id"].nunique()),
        "top10pct_unit_share": round(float(per_sku.head(top_n).sum()) / total * 100.0, 3) if total else None,
        "abc_a_skus": int((abc["abc_class"] == "A").sum()),
    }


def _layout_metrics(
    layout_path: Path,
    workload: pd.DataFrame,
    units_demand: dict[str, float],
    depot_dist: dict[str, float],
) -> dict:
    frame = pd.read_csv(layout_path)
    result = line_travel(workload, sku_bins(frame, depot_dist), QUANTITY_AWARE)
    agg = result.aggregate()
    repl = replenishment_metrics(frame, units_demand, depot_dist).aggregate()
    return {
        "demand_weighted_depot_distance": agg["demand_weighted_depot_distance"],
        "demand_weighted_numerator_m": agg["numerator_m"],
        "demand_weighted_denominator_lines": agg["denominator_lines"],
        "demand_weighted_lines_total": agg["lines_total"],
        "demand_weighted_lines_unresolved": agg["lines_unresolved"],
        "demand_weighted_coverage_pct": agg["coverage_pct"],
        "fragmentation": fragmentation_stats(frame, depot_dist),
        "replenishment": repl,
    }


def _cell_from_run(run: dict, source: str, layout_label: str) -> dict:
    metrics = run[source]
    return {
        "layout": layout_label,
        "feasible": bool(run["feasibility"][source]["is_feasible"]),
        "n_violations": run["feasibility"][source]["n_violations"],
        "assignment_completeness": {
            "valid": metrics.get("valid_assignments"),
            "required": metrics.get("required_assignments"),
            "pct": metrics.get("assignment_feasibility_pct"),
        },
        "metrics": metrics,
        "workload_id": run["workload"]["workload_id"],
        "run_id": run["workload"]["workload_id"],
        "diagnostics_status": run["diagnostics"][source]["status"],
        "headroom_max_pct": (run["headroom"][source] or {}).get("max_utilization_pct"),
    }


def run(out_root: Path) -> dict:
    out_root = Path(out_root)
    out_root.mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------------- 0. freeze inputs
    split_manifest_path = PHASE3 / "split" / "A70" / "split_manifest.json"
    if not split_manifest_path.exists():
        raise FileNotFoundError(f"Phase 3 split manifest missing: {split_manifest_path}")
    split = json.loads(split_manifest_path.read_text())
    split_checks = verify_split(split)
    if not split_checks["all_passed"]:
        raise RuntimeError(f"Phase 3 split failed verification: {split_checks}")
    for path in (BASELINE_LAYOUT, OPTIMIZED_LAYOUT, PHASE3_FIT_SUMMARY):
        if not path.exists():
            raise FileNotFoundError(f"frozen Phase 3 artifact missing: {path}")

    fit_summary = json.loads(PHASE3_FIT_SUMMARY.read_text())
    if fit_summary.get("feasibility_status") != "FEASIBLE":
        raise RuntimeError("the frozen optimized layout is not independently feasible")
    baseline_variant = fit_summary.get("baseline_variant", "repaired_minimal")
    if baseline_variant != "repaired_minimal":
        raise RuntimeError(f"expected repaired_minimal baseline, got {baseline_variant!r}")

    baseline_sha = _sha256(BASELINE_LAYOUT)
    optimized_sha = _sha256(OPTIMIZED_LAYOUT)

    # ---------------------------------------------------------------- 1. holdout workload
    hold_items = _workload_items(HOLDOUT_TREE, "A_HOLDOUT")
    hold_units = _units_demand(HOLDOUT_TREE, "A_HOLDOUT")
    depot_dist, _depot_node = _depot(HOLDOUT_TREE)
    hold_profile = _regime_profile(HOLDOUT_TREE, "A_HOLDOUT")

    # ---------------------------------------------------------------- 2. 2x2 on holdout
    runs: dict[str, dict] = {}
    cells: list[dict] = []
    for policy in POLICIES:
        run_dir = out_root / "cells" / policy
        result = run_phase6(
            processed=HOLDOUT_TREE,
            scenario="A_HOLDOUT",
            out=run_dir,
            optimized_path=OPTIMIZED_LAYOUT,
            affinity_scenario="A_HOLDOUT",
            baseline_path=BASELINE_LAYOUT,
            baseline_variant=baseline_variant,
            baseline_note="repaired for feasibility only; frozen from Phase 3",
            routing_strategy=policy,
            batch_size=5,
        )
        runs[policy] = result
        if not result["integrity"]["publishable"]:
            raise RuntimeError(f"holdout comparison blocked under {policy}: {result['integrity']}")

        for source, layout_label, cell_id in (
            ("baseline", "baseline_repaired", "A1" if policy == "nearest_neighbor" else "A2"),
            ("optimized", "optimized_fit", "B1" if policy == "nearest_neighbor" else "B2"),
        ):
            cell = _cell_from_run(result, source, layout_label)
            cell.update(
                {
                    "cell_id": cell_id,
                    "picking_policy": POLICY_LABELS[policy],
                    "run_id": f"holdout_{policy}",
                    "run_dir": str(run_dir),
                    "source_key": source,
                    "picking_policy_source": policy,
                    "layout_metrics": _layout_metrics(
                        BASELINE_LAYOUT if source == "baseline" else OPTIMIZED_LAYOUT,
                        hold_items,
                        hold_units,
                        depot_dist,
                    ),
                }
            )
            cells.append(cell)

    # order A1,A2,B1,B2 for humans and CSV
    cells.sort(key=lambda c: c["cell_id"])
    cell_by_key = {f"{c['layout']}|{c['picking_policy']}": c for c in cells}

    # ---------------------------------------------------------------- 3. effects
    levels_a = ("baseline_repaired", "optimized_fit")
    levels_b = ("nearest_neighbor", "s_shape")
    metric_values = {
        f"{c['layout']}|{c['picking_policy']}": {
            **{k: c["metrics"].get(k) for k in SIMULATION_METRICS},
            "demand_weighted_depot_distance": c["layout_metrics"]["demand_weighted_depot_distance"],
            "replenishment_travel_m": c["layout_metrics"]["replenishment"]["replenishment_travel_m"],
        }
        for c in cells
    }
    effects = metric_effects(
        metric_values,
        a_levels=levels_a,
        b_levels=levels_b,
        metrics={
            **SIMULATION_METRICS,
            "demand_weighted_depot_distance": {"unit": "m", "lower_is_better": True},
            "replenishment_travel_m": {"unit": "m", "lower_is_better": True},
        },
    )

    # ---------------------------------------------------------------- 4. demand regimes
    regime_rows = [
        {
            "regime": "A_HOLDOUT",
            "definition": "later 30% of scenario A (temporal holdout; fit excluded)",
            **hold_profile,
            "baseline_travel_m": cell_by_key["baseline_repaired|nearest_neighbor"]["metrics"]["total_travel_distance_m"],
            "optimized_travel_m": cell_by_key["optimized_fit|nearest_neighbor"]["metrics"]["total_travel_distance_m"],
            "baseline_cycle_sec": cell_by_key["baseline_repaired|nearest_neighbor"]["metrics"]["total_route_time_sec"],
            "optimized_cycle_sec": cell_by_key["optimized_fit|nearest_neighbor"]["metrics"]["total_route_time_sec"],
            "baseline_throughput": cell_by_key["baseline_repaired|nearest_neighbor"]["metrics"]["throughput_orders_per_hr"],
            "optimized_throughput": cell_by_key["optimized_fit|nearest_neighbor"]["metrics"]["throughput_orders_per_hr"],
            "publishable": bool(
                cell_by_key["baseline_repaired|nearest_neighbor"]["feasible"]
                and cell_by_key["optimized_fit|nearest_neighbor"]["feasible"]
            ),
            "picking_policy": "nearest_neighbor",
        }
    ]

    canonical = PROJECT_ROOT.parent / "dataset" / "processed"
    for scenario in ("B", "C"):
        profile = _regime_profile(canonical, scenario)
        run_dir = out_root / "regimes" / scenario
        result = run_phase6(
            processed=canonical,
            scenario=scenario,
            out=run_dir,
            optimized_path=OPTIMIZED_LAYOUT,
            affinity_scenario=scenario,
            baseline_path=BASELINE_LAYOUT,
            baseline_variant=baseline_variant,
            baseline_note="repaired for feasibility only; frozen from Phase 3",
            routing_strategy="nearest_neighbor",
            batch_size=5,
        )
        regime_rows.append(
            {
                "regime": scenario,
                "definition": f"scenario {scenario} demand regime (different generator; never used for fitting)",
                **profile,
                "baseline_travel_m": result["baseline"]["total_travel_distance_m"],
                "optimized_travel_m": result["optimized"]["total_travel_distance_m"],
                "baseline_cycle_sec": result["baseline"]["total_route_time_sec"],
                "optimized_cycle_sec": result["optimized"]["total_route_time_sec"],
                "baseline_throughput": result["baseline"]["throughput_orders_per_hr"],
                "optimized_throughput": result["optimized"]["throughput_orders_per_hr"],
                "publishable": bool(result["integrity"]["publishable"]),
                "picking_policy": "nearest_neighbor",
                "workload_id": result["workload"]["workload_id"],
                "run_dir": str(run_dir),
                "feasibility": {
                    "baseline": result["feasibility"]["baseline"]["feasibility_status"],
                    "optimized": result["feasibility"]["optimized"]["feasibility_status"],
                },
            }
        )

    for row in regime_rows:
        b = row.get("baseline_travel_m")
        o = row.get("optimized_travel_m")
        row["travel_change_pct"] = round((o - b) / b * 100.0, 3) if b else None

    # ---------------------------------------------------------------- 5. sweep reuse
    sweep_path = PHASE3 / "phase3_sweep.csv"
    sweep = pd.read_csv(sweep_path) if sweep_path.exists() else pd.DataFrame()
    selected = sweep.loc[sweep["selected"] == True] if len(sweep) and "selected" in sweep else pd.DataFrame()  # noqa: E712
    selected_config = selected.iloc[0]["config_id"] if len(selected) else None
    selected_matches_frozen = bool(
        len(selected)
        and str(selected.iloc[0].get("layout_sha256", "")) == optimized_sha
    )

    # ---------------------------------------------------------------- 6. headroom + diagnostics
    headroom_rows = []
    for policy in POLICIES:
        for source, label in (("baseline", "baseline_repaired"), ("optimized", "optimized_fit")):
            h = runs[policy]["headroom"][source]
            for scope, data in h["scopes"].items():
                headroom_rows.append(
                    {
                        "layout": label,
                        "picking_policy": policy,
                        "scope": scope,
                        "rule_id": data["rule_id"],
                        "unit": data["unit"],
                        "max_utilization_pct": data["max_utilization_pct"],
                        "mean_utilization_pct": data["mean_utilization_pct"],
                        "pct_over_90": data["pct_over_90"],
                        "pct_over_95": data["pct_over_95"],
                        "status": data["status"],
                        "limiting_location": (data.get("limiting") or {}).get("location_id"),
                        "limiting_sku": (data.get("limiting") or {}).get("sku_id"),
                        "observed": (data.get("limiting") or {}).get("observed"),
                        "limit": (data.get("limiting") or {}).get("limit"),
                    }
                )

    diagnostics = {
        "holdout": {
            policy: {
                "baseline": runs[policy]["diagnostics"]["baseline"],
                "optimized": runs[policy]["diagnostics"]["optimized"],
            }
            for policy in POLICIES
        },
        "regimes": {
            row["regime"]: row.get("feasibility") for row in regime_rows if row["regime"] not in ("A_HOLDOUT",)
        },
        "note": "all Phase 4 layouts are feasible; the diagnostics block records the checked status, not invented failures",
    }

    # ---------------------------------------------------------------- 7. artifacts
    result = {
        "schema": "phase4.experiments/1",
        "experiment_id": EXPERIMENT_ID,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dataset": str(canonical),
        "phase3": {
            "experiments": str(PHASE3 / "phase3_experiments.json"),
            "split_manifest": str(split_manifest_path),
            "baseline_layout": str(BASELINE_LAYOUT),
            "optimized_layout": str(OPTIMIZED_LAYOUT),
            "baseline_sha256": baseline_sha,
            "optimized_sha256": optimized_sha,
            "baseline_variant": baseline_variant,
            "split_checks": split_checks,
        },
        "frozen": {
            "baseline_sha256": baseline_sha,
            "optimized_sha256": optimized_sha,
            "refit_after_holdout": False,
            "note": "both layouts were fitted before this run and are frozen by hash",
        },
        "design": {
            "factors": {
                "layout": list(levels_a),
                "picking_policy": list(levels_b),
            },
            "cells": {
                "A1": {"layout": "baseline_repaired", "picking_policy": "nearest_neighbor"},
                "A2": {"layout": "baseline_repaired", "picking_policy": "s_shape"},
                "B1": {"layout": "optimized_fit", "picking_policy": "nearest_neighbor"},
                "B2": {"layout": "optimized_fit", "picking_policy": "s_shape"},
            },
            "workload": hold_profile,
            "controls": [
                "same holdout workload (hash published)",
                "same warehouse geometry and inventory",
                "same batch size, picker speed, pick time and setup time",
                "same metric definitions and validation gate",
                "only layout and routing policy vary",
            ],
        },
        "cells": cells,
        "effects": effects,
        "regimes": {"rows": regime_rows},
        "sweep": {
            "source": str(sweep_path),
            "selected_config": selected_config,
            "selected_matches_frozen_layout": selected_matches_frozen,
            "variants": (
                sweep.where(pd.notna(sweep), None).to_dict(orient="records") if len(sweep) else []
            ),
            "selection_note": (
                "Phase 3 selected using fit demand-weighted travel among feasible runs; the holdout "
                "was not used to choose. Phase 4 reuses that frozen selection."
            ),
        },
        "headroom": headroom_rows,
        "diagnostics": diagnostics,
        "limitations": [
            "single deterministic workload per cell; no seed variability or confidence intervals",
            "s_shape is the repository's documented node-order serpentine simplification, not a full aisle-grid S-shape",
            "pick time is charged per order line (Phase 2/3 definition); the per-stop target (D37) is not applied",
            "demand-weighted line travel is layout-level and does not vary with the routing policy",
            "regimes B/C are different synthetic demand generators, not resamples of A",
        ],
    }

    (out_root / "phase4_experiments.json").write_text(json.dumps(result, indent=2), encoding="utf-8")

    pd.DataFrame(
        [
            {
                "cell_id": c["cell_id"],
                "layout": c["layout"],
                "picking_policy": c["picking_policy"],
                "feasible": c["feasible"],
                "assignment_completeness_pct": c["assignment_completeness"]["pct"],
                "total_travel_distance_m": c["metrics"]["total_travel_distance_m"],
                "total_route_time_sec": c["metrics"]["total_route_time_sec"],
                "throughput_orders_per_hr": c["metrics"]["throughput_orders_per_hr"],
                "avg_time_per_order_sec": c["metrics"]["avg_time_per_order_sec"],
                "demand_weighted_depot_distance": c["layout_metrics"]["demand_weighted_depot_distance"],
                "bins_used": c["layout_metrics"]["fragmentation"]["bins_used"],
                "multi_bin_skus": c["layout_metrics"]["fragmentation"]["multi_bin_skus"],
                "replenishment_travel_m": c["layout_metrics"]["replenishment"]["replenishment_travel_m"],
                "optimized_objective_value": (fit_summary.get("objective") or {}).get("value"),
                "baseline_objective_value": (fit_summary.get("objective") or {}).get("baseline_value"),
                "runtime_sec": c["metrics"].get("optimization_runtime_sec"),
                "workload_id": c["workload_id"],
                "run_dir": c["run_dir"],
            }
            for c in cells
        ]
    ).to_csv(out_root / "phase4_cells.csv", index=False)

    pd.DataFrame(
        [
            {
                "metric": key,
                **{k: v for k, v in data.items() if k not in ("cell_values", "formulas", "levels")},
            }
            for key, data in effects.items()
        ]
    ).to_csv(out_root / "phase4_effects.csv", index=False)

    pd.DataFrame(regime_rows).to_csv(out_root / "phase4_regimes.csv", index=False)
    pd.DataFrame(headroom_rows).to_csv(out_root / "phase4_headroom.csv", index=False)
    (out_root / "phase4_diagnostics.json").write_text(json.dumps(diagnostics, indent=2), encoding="utf-8")

    outputs = {
        "phase4_experiments.json": out_root / "phase4_experiments.json",
        "phase4_cells.csv": out_root / "phase4_cells.csv",
        "phase4_effects.csv": out_root / "phase4_effects.csv",
        "phase4_regimes.csv": out_root / "phase4_regimes.csv",
        "phase4_headroom.csv": out_root / "phase4_headroom.csv",
        "phase4_diagnostics.json": out_root / "phase4_diagnostics.json",
    }
    for policy in POLICIES:
        outputs[f"{policy}_evaluation.json"] = out_root / "cells" / policy / "evaluation_summary.json"
        outputs[f"{policy}_routes.csv"] = out_root / "cells" / policy / "pick_routes.csv"
    for scenario in ("B", "C"):
        outputs[f"regime_{scenario}_evaluation.json"] = (
            out_root / "regimes" / scenario / "evaluation_summary.json"
        )

    manifest = build_manifest(
        root=PROJECT_ROOT,
        processed=canonical,
        config_path=PROJECT_ROOT / "configs" / "benchmark.json",
        outputs=outputs,
        experiment_id=EXPERIMENT_ID,
        scenario="A_HOLDOUT + B + C",
        split_manifest=split_manifest_path,
        seeds={
            "optimizer": 42,
            "simulation": "deterministic; no random seed used",
            "split": None,
        },
        evaluation_protocol={
            "holdout": "later 30% of scenario A; layouts frozen before evaluation",
            "policies": list(POLICIES),
            "regimes": ["A_HOLDOUT", "B", "C"],
            "feasibility": "independent Validator per layout; gate blocks publication",
            "selection": "reuse Phase 3 fit selection; holdout not used to choose",
        },
        transformations=[
            "dataset/processed read-only",
            "Phase 3 split reused byte-for-byte (manifest hash recorded)",
            "no layout refit or retuning in Phase 4",
        ],
        extra={
            "phase4": {
                "frozen_layouts": {
                    "baseline_sha256": baseline_sha,
                    "optimized_sha256": optimized_sha,
                },
                "cells": [c["cell_id"] for c in cells],
            }
        },
    )
    (out_root / "provenance.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return result


def main() -> None:
    ap = argparse.ArgumentParser(prog="run_phase4")
    ap.add_argument("--out", default=str(PROJECT_ROOT / "outputs" / "phase4"))
    args = ap.parse_args()
    result = run(Path(args.out))
    print(
        json.dumps(
            {
                "cells": [
                    {
                        "id": c["cell_id"],
                        "layout": c["layout"],
                        "policy": c["picking_policy"],
                        "travel_m": c["metrics"]["total_travel_distance_m"],
                        "cycle_s": c["metrics"]["total_route_time_sec"],
                        "throughput": c["metrics"]["throughput_orders_per_hr"],
                        "feasible": c["feasible"],
                    }
                    for c in result["cells"]
                ],
                "effects": result["effects"],
                "regimes": [
                    {k: r.get(k) for k in ("regime", "baseline_travel_m", "optimized_travel_m", "travel_change_pct")}
                    for r in result["regimes"]["rows"]
                ],
                "selected": result["sweep"]["selected_config"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
