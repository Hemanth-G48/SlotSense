"""Read-only data contract for Phase 4 artifacts (dashboard side).

Exposes the held-out layout x picking-policy experiment, demand regimes, structural
headroom and the independent verification result. Missing artifacts are reported as
``"unavailable"`` with the command that produces them; nothing is defaulted to zero.

The dashboard itself is not redesigned in Phase 4. A view can consume this contract
without recomputing any metric.
"""

from __future__ import annotations

import json
from pathlib import Path

UNAVAILABLE = "unavailable"


def _load(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def load_phase4(phase4_dir: Path) -> dict:
    phase4_dir = Path(phase4_dir)
    exp = _load(phase4_dir / "phase4_experiments.json")

    if exp is None:
        return {
            "status": UNAVAILABLE,
            "reason": f"no phase4_experiments.json under {phase4_dir}",
            "cells": UNAVAILABLE,
            "effects": UNAVAILABLE,
            "regimes": UNAVAILABLE,
            "headroom": UNAVAILABLE,
            "verification": UNAVAILABLE,
            "caveat": "run `python -m src.experiments.run_phase4` to produce the artifacts",
        }

    verification = _load(phase4_dir / "verification.json")
    cells = exp.get("cells", [])
    diagnostics = exp.get("diagnostics", {})

    def cell_summary(cell: dict) -> dict:
        metrics = cell.get("metrics") or {}
        layout_metrics = cell.get("layout_metrics") or {}
        return {
            "cell_id": cell.get("cell_id"),
            "layout": cell.get("layout"),
            "picking_policy": cell.get("picking_policy"),
            "feasible": cell.get("feasible"),
            "assignment_completeness_pct": (cell.get("assignment_completeness") or {}).get("pct"),
            "total_travel_distance_m": metrics.get("total_travel_distance_m"),
            "total_route_time_sec": metrics.get("total_route_time_sec"),
            "throughput_orders_per_hr": metrics.get("throughput_orders_per_hr"),
            "avg_time_per_order_sec": metrics.get("avg_time_per_order_sec"),
            "demand_weighted_depot_distance": layout_metrics.get("demand_weighted_depot_distance"),
            "bins_used": (layout_metrics.get("fragmentation") or {}).get("bins_used"),
            "multi_bin_skus": (layout_metrics.get("fragmentation") or {}).get("multi_bin_skus"),
            "replenishment_travel_m": (layout_metrics.get("replenishment") or {}).get(
                "replenishment_travel_m"
            ),
            "runtime_sec": metrics.get("optimization_runtime_sec"),
            "workload_id": cell.get("workload_id"),
        }

    return {
        "status": "ok",
        "experiment_id": exp.get("experiment_id", UNAVAILABLE),
        "generated_at_utc": exp.get("generated_at_utc", UNAVAILABLE),
        "frozen_layouts": exp.get("frozen", UNAVAILABLE),
        "baseline_variant": (exp.get("phase3") or {}).get("baseline_variant", UNAVAILABLE),
        "design": exp.get("design", UNAVAILABLE),
        "cells": [cell_summary(c) for c in cells],
        "effects": exp.get("effects", UNAVAILABLE),
        "regimes": exp.get("regimes", UNAVAILABLE),
        "sweep": exp.get("sweep", UNAVAILABLE),
        "headroom": exp.get("headroom", UNAVAILABLE),
        "diagnostics": {
            "holdout": {
                policy: {
                    side: (payload or {}).get("status")
                    for side, payload in (sides or {}).items()
                }
                for policy, sides in (diagnostics.get("holdout") or {}).items()
            },
            "regimes": diagnostics.get("regimes", UNAVAILABLE),
            "note": diagnostics.get("note", UNAVAILABLE),
        },
        "verification": (
            {
                "available": True,
                "all_passed": bool(verification.get("all_passed")),
                "n_checks": verification.get("n_checks"),
                "n_failed": verification.get("n_failed"),
                "checks": verification.get("checks", []),
            }
            if verification is not None
            else {"available": False, "reason": "run tools/verify_phase4.py"}
        ),
        "evaluation_status": (
            "held_out"
            if exp.get("frozen", {}).get("refit_after_holdout") is False
            and verification is not None
            and verification.get("all_passed")
            else "unverified_or_in_sample"
        ),
        "caveat": (
            "single deterministic run per cell; effects are a decomposition, not a significance test. "
            "Historical Phase 2/3 figures are not held-out Phase 4 results."
        ),
    }
