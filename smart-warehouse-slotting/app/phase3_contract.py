"""Read-only data contract for Phase 3 artifacts (dashboard side, D28/D44 precursor).

The dashboard is not redesigned in Phase 3. This module is the **contract** it would
consume: a single function that turns ``outputs/phase3/`` into the shape a view needs,
with one rule enforced — *a missing value is reported as unavailable, never as zero*.

Fields exposed
--------------
- split: method, fraction, fit/holdout counts, leakage checks, evaluation status
- baseline variant (``repaired_minimal``) and the fit scenario
- the primary 2x2 (placement x fragmentation) with cell ids, numerator/denominator,
  feasibility and fragmentation statistics per cell
- the secondary pick-rule sensitivity design
- main effects and interaction
- replenishment metrics per cell, with assumptions
- the weight sweep, objective components, and which configuration was selected
  (and on what data)
- hard-feasibility status per cell, assignment completeness, and the evaluation
  caveat that forbids quoting the Phase 2 figure as held-out
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


def load_phase3(phase3_dir: Path) -> dict:
    """Return the dashboard-facing view of a Phase 3 run.

    Every value is either present or explicitly ``"unavailable"`` with a reason.
    Nothing is defaulted to 0.
    """
    phase3_dir = Path(phase3_dir)
    exp = _load(phase3_dir / "phase3_experiments.json")

    if exp is None:
        return {
            "status": UNAVAILABLE,
            "reason": f"no phase3_experiments.json under {phase3_dir}",
            "split": UNAVAILABLE,
            "cells": UNAVAILABLE,
            "effects": UNAVAILABLE,
            "replenishment": UNAVAILABLE,
            "sweep": UNAVAILABLE,
            "feasibility": UNAVAILABLE,
            "caveat": "run `python -m src.experiments.run_phase3` to produce the artifacts",
        }

    split = exp.get("split", {})
    two_by_two = exp.get("two_by_two", {})
    fit_run = exp.get("fit_run", {})
    leakage_ok = bool(split.get("checks", {}).get("all_passed", False))

    cells = []
    for c in two_by_two.get("cells", []):
        cells.append(
            {
                "cell_id": c.get("cell_id"),
                "layout": c.get("layout"),
                "pick_rule": c.get("pick_rule"),
                "placement": c.get("placement"),
                "fragmentation_policy": c.get("fragmentation_policy"),
                "feasible": c.get("feasible"),
                "demand_weighted_depot_distance": c.get("demand_weighted_depot_distance"),
                "numerator_m": c.get("numerator_m"),
                "denominator_lines": c.get("denominator_lines"),
                "lines_total": c.get("lines_total"),
                "lines_unresolved": c.get("lines_unresolved"),
                "coverage_pct": c.get("coverage_pct"),
                "mean_per_line_m": c.get("mean_per_line_m"),
                "stops": c.get("stops"),
                "lines_quantity_short": c.get("lines_quantity_short"),
                "units_short": c.get("units_short"),
                "fragmentation": c.get("fragmentation"),
            }
        )

    def _cell_key(cell: dict) -> str:
        return str(cell.get("cell_id") or cell.get("layout") or "unknown")

    completeness = fit_run.get("assignment_completeness") or UNAVAILABLE

    return {
        "status": "ok",
        "experiment_id": exp.get("experiment_id", UNAVAILABLE),
        "generated_at_utc": exp.get("generated_at_utc", UNAVAILABLE),
        "leakage_checked": leakage_ok,
        "split": {
            "method": split.get("method", UNAVAILABLE),
            "split_unit": split.get("split_unit", UNAVAILABLE),
            "fraction_fit": split.get("fraction_fit"),
            "seed": split.get("seed", "unknown"),
            "fit": split.get("fit", UNAVAILABLE),
            "holdout": split.get("holdout", UNAVAILABLE),
            "checks": split.get("checks", UNAVAILABLE),
            "leakage_checked": leakage_ok,
        },
        "baseline_variant": fit_run.get("baseline_variant", UNAVAILABLE),
        "scenario": fit_run.get("scenario", UNAVAILABLE),
        "design": two_by_two.get("design", UNAVAILABLE),
        "cells": cells,
        "effects": two_by_two.get("effects", UNAVAILABLE),
        "interpretation": two_by_two.get("interpretation", UNAVAILABLE),
        "pick_rule_sensitivity": exp.get("pick_rule_sensitivity", UNAVAILABLE),
        "all_bins": {
            "design": (exp.get("two_by_two_all_bins") or {}).get("design", UNAVAILABLE),
            "cells": (exp.get("two_by_two_all_bins") or {}).get("cells", UNAVAILABLE),
            "effects": (exp.get("two_by_two_all_bins") or {}).get("effects", UNAVAILABLE),
        },
        "replenishment": exp.get("replenishment", UNAVAILABLE),
        "sweep": exp.get("sweep", UNAVAILABLE),
        "assignment_completeness": completeness,
        "objective_components": fit_run.get("objective_components", UNAVAILABLE),
        "feasibility": {
            "fit_layout": fit_run.get("feasibility_status", UNAVAILABLE),
            "fit_violations": fit_run.get("n_violations", UNAVAILABLE),
            "cell_feasibility": {_cell_key(c): c.get("feasible") for c in two_by_two.get("cells", [])},
            "publishable_comparison": (exp.get("integrity") or {}).get(
                "publishable_comparison", UNAVAILABLE
            ),
        },
        "evaluation_status": (
            "held_out" if leakage_ok else "in_sample_or_unverified"
        ),
        "caveat": exp.get(
            "methodology_caveat",
            "no methodology note recorded — treat every number as unreproduced",
        ),
    }
