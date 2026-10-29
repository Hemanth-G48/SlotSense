"""Workload identity and fair-comparison checks (Phase 4).

A comparison is only evidence when both layouts are scored on the *same* workload. This
module turns that statement into a hash and a small set of explicit integrity flags, so a
result artifact can prove what it compared instead of asserting it in prose.

The workload identity hashes the canonical (order_id, sku_id, quantity) triples, sorted.
Two runs with the same identity consumed exactly the same order lines; a run that changed
the workload cannot silently reuse a previous result.
"""

from __future__ import annotations

import hashlib

import pandas as pd

REQUIRED_COLUMNS = ("order_id", "sku_id", "quantity")


def workload_identity(order_items: pd.DataFrame, scenario: str | None = None) -> dict:
    """Deterministic identity and size of an evaluation workload."""
    missing = [c for c in REQUIRED_COLUMNS if c not in order_items.columns]
    if missing:
        raise ValueError(f"workload is missing required columns: {missing}")

    canonical = (
        order_items.loc[:, list(REQUIRED_COLUMNS)]
        .assign(
            order_id=lambda d: d["order_id"].astype(str),
            sku_id=lambda d: d["sku_id"].astype(str),
            quantity=lambda d: d["quantity"].astype(int),
        )
        .sort_values(["order_id", "sku_id", "quantity"], kind="mergesort")
    )
    payload = canonical.to_csv(index=False).encode("utf-8")
    sha = hashlib.sha256(payload).hexdigest()
    return {
        "workload_id": f"wl_{sha[:16]}",
        "sha256": sha,
        "scenario": scenario,
        "n_orders": int(canonical["order_id"].nunique()),
        "n_lines": int(len(canonical)),
        "n_units": int(canonical["quantity"].sum()),
        "n_skus": int(canonical["sku_id"].nunique()),
    }


def fairness_checks(
    *,
    workload: dict,
    baseline_metrics: dict,
    optimized_metrics: dict,
    baseline_feasible: bool,
    optimized_feasible: bool,
    inventory_units: int,
    routing_strategy: str,
    batch_size: int,
    gate_blocked: bool,
    blocked_layouts: list[str],
) -> dict:
    """Explicit conditions a publishable comparison must satisfy.

    ``same_workload`` is true by construction here (one DataFrame is simulated twice), but
    it is recorded so a consumer can see that rather than infer it. Each denominator check
    is separate: a zero travel total cannot produce a travel percentage.
    """
    def _complete(metrics: dict) -> dict:
        required = int(metrics.get("required_assignments") or 0)
        valid = int(metrics.get("valid_assignments") or 0)
        return {
            "valid": valid,
            "required": required,
            "complete": required > 0 and valid == required,
            "pct": metrics.get("assignment_feasibility_pct"),
        }

    baseline_complete = _complete(baseline_metrics)
    optimized_complete = _complete(optimized_metrics)
    denominators = {
        "baseline_travel_positive": float(baseline_metrics.get("total_travel_distance_m") or 0) > 0,
        "optimized_travel_positive": float(optimized_metrics.get("total_travel_distance_m") or 0) > 0,
        "baseline_cycle_positive": float(baseline_metrics.get("total_route_time_sec") or 0) > 0,
        "optimized_cycle_positive": float(optimized_metrics.get("total_route_time_sec") or 0) > 0,
        "baseline_orders_positive": int(baseline_metrics.get("total_orders") or 0) > 0,
        "optimized_orders_positive": int(optimized_metrics.get("total_orders") or 0) > 0,
    }
    checks = {
        "same_workload": True,  # one frame simulated twice; identity is published beside it
        "workload_id": workload["workload_id"],
        "same_geometry": True,
        "same_inventory_units": inventory_units,
        "same_routing_strategy": routing_strategy,
        "same_batch_size": batch_size,
        "baseline_feasible": bool(baseline_feasible),
        "optimized_feasible": bool(optimized_feasible),
        "baseline_assignment_complete": baseline_complete["complete"],
        "optimized_assignment_complete": optimized_complete["complete"],
        "baseline_assignment": baseline_complete,
        "optimized_assignment": optimized_complete,
        "denominators": denominators,
        "gate_blocked": bool(gate_blocked),
        "blocked_layouts": list(blocked_layouts),
    }
    checks["publishable"] = bool(
        not gate_blocked
        and checks["baseline_feasible"]
        and checks["optimized_feasible"]
        and checks["baseline_assignment_complete"]
        and checks["optimized_assignment_complete"]
        and all(denominators.values())
    )
    return checks
