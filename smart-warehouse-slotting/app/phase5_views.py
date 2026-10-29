"""Presentation helpers for the Phase 3 and Phase 4 contracts (Phase 5).

These functions **select columns and attach human labels only**. They never recompute a
metric, average a denominator, or infer a missing value. If a contract is unavailable or a
comparison is blocked, the view says so and returns no comparison table.

Keeping the transforms here (rather than inside the Streamlit callbacks) makes them
unit-testable without starting the app.
"""

from __future__ import annotations

import pandas as pd

UNAVAILABLE = "unavailable"


def _is_ok(contract: dict | None) -> bool:
    return isinstance(contract, dict) and contract.get("status") == "ok"


def filter_frame(df: pd.DataFrame, column: str, value: str) -> pd.DataFrame:
    """Select recorded rows; never recompute or synthesize a segment."""
    if df.empty or value in (None, "", "All"):
        return df
    if column not in df.columns:
        return df.iloc[0:0]
    return df[df[column] == value]


def phase3_view(contract: dict | None) -> dict:
    """Shape the Phase 3 contract for display, without recalculating anything."""
    if not _is_ok(contract):
        return {
            "available": False,
            "reason": (contract or {}).get("reason", "Phase 3 contract unavailable"),
            "caveat": (contract or {}).get("caveat", ""),
            "cells": pd.DataFrame(),
            "effects": pd.DataFrame(),
            "split": pd.DataFrame(),
            "replenishment": pd.DataFrame(),
            "sweep": pd.DataFrame(),
            "pick_rule": pd.DataFrame(),
        }

    feasibility = contract.get("feasibility") or {}
    publishable = feasibility.get("publishable_comparison")
    blocked = publishable is False

    cell_rows = []
    for c in contract.get("cells") or []:
        frag = c.get("fragmentation") or {}
        after = frag.get("after") or {}
        cell_rows.append(
            {
                "Cell": c.get("cell_id"),
                "Placement": c.get("placement"),
                "Fragmentation": c.get("fragmentation_policy"),
                "Feasible": c.get("feasible"),
                "Bins": after.get("bins_used"),
                "Travel (m, line metric)": c.get("demand_weighted_depot_distance"),
                "Lines priced": c.get("denominator_lines"),
                "Coverage (%)": c.get("coverage_pct"),
                "Mean per line (m)": c.get("mean_per_line_m"),
            }
        )

    effects = contract.get("effects") or {}
    effect_rows = []
    for key, label in (
        ("factor_a_effect", "Placement"),
        ("factor_b_effect", "Fragmentation policy"),
        ("interaction", "Interaction (DiD)"),
    ):
        if key == "factor_a_effect":
            value, pct = effects.get("factor_a_effect_m"), effects.get("factor_a_effect_pct_of_reference")
        elif key == "factor_b_effect":
            value, pct = effects.get("factor_b_effect_m"), effects.get("factor_b_effect_pct_of_reference")
        else:
            value, pct = effects.get("interaction_m"), effects.get("interaction_pct_of_reference")
        if value is not None:
            effect_rows.append({"Effect": label, "Value (m)": value, "Percent of A1": pct})

    split = contract.get("split") or {}
    split_rows = [
        {"View": view, **{k: (split.get(view) or {}).get(k) for k in ("orders", "lines", "skus_with_demand")}}
        for view in ("fit", "holdout")
        if split.get(view)
    ]

    replenishment = []
    for label, payload in ((contract.get("replenishment") or {}).get("cells") or {}).items():
        replenishment.append(
            {
                "Cell": label,
                "Trips": payload.get("replenishment_trips"),
                "Travel (m)": payload.get("replenishment_travel_m"),
                "Bins": payload.get("n_bins"),
                "SKUs replenished": payload.get("n_skus_replenished"),
                "Denominator SKUs": payload.get("denominator_skus"),
            }
        )

    sweep = contract.get("sweep") or {}
    sweep_rows = []
    for v in sweep.get("variants") or []:
        sweep_rows.append(
            {
                "Config": v.get("config_id"),
                "α": v.get("alpha"),
                "β": v.get("beta"),
                "γ": v.get("gamma"),
                "δ": v.get("delta"),
                "ε": v.get("epsilon"),
                "Feasible": v.get("fit_feasible"),
                "Fit T (m)": v.get("fit_demand_weighted_depot_distance"),
                "Holdout T (m)": v.get("holdout_demand_weighted_depot_distance"),
                "Selected": v.get("selected"),
            }
        )

    pick = contract.get("pick_rule_sensitivity") or {}
    pick_effects = pick.get("effects") or {}
    pick_rows = [
        {"Effect": label, "Value": pick_effects.get(key), "Unit": "m"}
        for key, label in (
            ("layout_effect_m", "Layout effect"),
            ("rule_effect_m", "Pick-rule effect"),
            ("interaction_m", "Interaction (DiD)"),
        )
        if pick_effects.get(key) is not None
    ]

    return {
        "available": True,
        "blocked": blocked,
        "evaluation_status": contract.get("evaluation_status"),
        "publishable": publishable,
        "experiment_id": contract.get("experiment_id"),
        "baseline_variant": contract.get("baseline_variant"),
        "scenario": contract.get("scenario"),
        "leakage_checked": contract.get("leakage_checked"),
        "caveat": contract.get("caveat", ""),
        "cells": pd.DataFrame(cell_rows),
        "effects": pd.DataFrame(effect_rows),
        "split": pd.DataFrame(split_rows),
        "replenishment": pd.DataFrame(replenishment),
        "sweep": pd.DataFrame(sweep_rows),
        "pick_rule": pd.DataFrame(pick_rows),
        "split_checks": split.get("checks") or {},
        "sweep_selected": sweep.get("selected_by_fit_travel"),
        "sweep_note": sweep.get("selection_note"),
    }


def phase4_view(contract: dict | None) -> dict:
    """Shape the Phase 4 contract for display, without recalculating anything."""
    if not _is_ok(contract):
        return {
            "available": False,
            "reason": (contract or {}).get("reason", "Phase 4 contract unavailable"),
            "caveat": (contract or {}).get("caveat", ""),
            "cells": pd.DataFrame(),
            "effects": pd.DataFrame(),
            "regimes": pd.DataFrame(),
            "headroom": pd.DataFrame(),
        }

    verification = contract.get("verification") or {}
    cells_source = contract.get("cells") or []
    blocked = bool(cells_source) and any(
        c.get("feasible") is False for c in cells_source
    )
    if verification.get("all_passed") is False:
        blocked = True
    if str(contract.get("evaluation_status", "")).lower() in ("blocked", "infeasible"):
        blocked = True
    workload_id = next(
        (c.get("workload_id") for c in cells_source if c.get("workload_id")), None
    )

    cell_rows = []
    for c in contract.get("cells") or []:
        cell_rows.append(
            {
                "Cell": c.get("cell_id"),
                "Layout": c.get("layout"),
                "Picking policy": c.get("picking_policy"),
                "Feasible": c.get("feasible"),
                "Completeness (%)": c.get("assignment_completeness_pct"),
                "Travel (m)": c.get("total_travel_distance_m"),
                "Cycle (s)": c.get("total_route_time_sec"),
                "Throughput (orders/h)": c.get("throughput_orders_per_hr"),
                "Time per order (s)": c.get("avg_time_per_order_sec"),
                "Demand-weighted (m)": c.get("demand_weighted_depot_distance"),
                "Bins": c.get("bins_used"),
                "Replenishment (m)": c.get("replenishment_travel_m"),
            }
        )

    effect_rows = []
    for metric, payload in (contract.get("effects") or {}).items():
        if not isinstance(payload, dict) or "factor_a_effect" not in payload:
            continue
        effect_rows.append(
            {
                "Metric": metric,
                "Unit": payload.get("unit"),
                "Layout effect": payload.get("factor_a_effect"),
                "Layout effect (%)": payload.get("factor_a_effect_pct"),
                "Policy effect": payload.get("factor_b_effect"),
                "Policy effect (%)": payload.get("factor_b_effect_pct"),
                "Interaction": payload.get("interaction"),
                "Interaction (%)": payload.get("interaction_pct"),
            }
        )

    regime_rows = []
    for r in (contract.get("regimes") or {}).get("rows") or []:
        regime_rows.append(
            {
                "Regime": r.get("regime"),
                "Orders": r.get("orders"),
                "Lines": r.get("lines"),
                "Units": r.get("units"),
                "Top-10 % share": r.get("top10pct_unit_share"),
                "Baseline travel (m)": r.get("baseline_travel_m"),
                "Optimized travel (m)": r.get("optimized_travel_m"),
                "Change (%)": r.get("travel_change_pct"),
                "Baseline throughput": r.get("baseline_throughput"),
                "Optimized throughput": r.get("optimized_throughput"),
                "Publishable": r.get("publishable"),
            }
        )

    # The contract carries headroom for both policies (identical layout measurement).
    # Show one row per layout/scope, preferring the reported nearest-neighbour policy.
    headroom_rows = []
    seen = set()
    for h in contract.get("headroom") or []:
        key = (h.get("layout"), h.get("scope"))
        if key in seen:
            continue
        if h.get("picking_policy") not in (None, "nearest_neighbor"):
            continue
        seen.add(key)
        headroom_rows.append(
            {
                "Layout": h.get("layout"),
                "Scope": h.get("scope"),
                "Max utilization (%)": h.get("max_utilization_pct"),
                "≥95 % of checks (%)": h.get("pct_over_95"),
                "Status": h.get("status"),
                "Limiting record": h.get("limiting_location"),
                "Observed": h.get("observed"),
                "Limit": h.get("limit"),
                "Unit": h.get("unit"),
            }
        )

    workload = (contract.get("design") or {}).get("workload") or {}
    return {
        "available": True,
        "blocked": blocked,
        "evaluation_status": contract.get("evaluation_status"),
        "publishable": not blocked,
        "experiment_id": contract.get("experiment_id"),
        "baseline_variant": contract.get("baseline_variant"),
        "frozen_layouts": contract.get("frozen_layouts") or {},
        "workload": workload,
        "workload_id": workload_id,
        "verification": verification,
        "caveat": contract.get("caveat", ""),
        "cells": pd.DataFrame(cell_rows),
        "effects": pd.DataFrame(effect_rows),
        "regimes": pd.DataFrame(regime_rows),
        "headroom": pd.DataFrame(headroom_rows),
        "diagnostics": contract.get("diagnostics") or {},
        "sweep": contract.get("sweep") or {},
    }
