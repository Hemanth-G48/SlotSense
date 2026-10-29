"""Tests for the Phase 3 dashboard data contract: present values pass through, missing ones never become 0."""

from __future__ import annotations

import json
from pathlib import Path

from app.phase3_contract import UNAVAILABLE, load_phase3


def test_missing_artifacts_are_unavailable_not_zero(tmp_path):
    view = load_phase3(tmp_path)
    assert view["status"] == UNAVAILABLE
    assert view["cells"] == UNAVAILABLE
    assert view["replenishment"] == UNAVAILABLE
    assert "run " in view["caveat"]


def test_contract_passes_through_artifacts_and_flags_held_out(tmp_path):
    payload = {
        "schema": "phase3.experiments/1",
        "split": {
            "method": "temporal_order_level",
            "fraction_fit": 0.7,
            "fit": {"orders": 3, "lines": 6},
            "holdout": {"orders": 2, "lines": 4},
            "checks": {"all_passed": True},
        },
        "fit_run": {"scenario": "A_FIT", "feasibility_status": "FEASIBLE",
                    "n_violations": 0, "baseline_variant": "repaired_minimal"},
        "two_by_two": {
            "cells": [
                {"layout": "baseline_repaired", "pick_rule": "all_bins", "feasible": True,
                 "demand_weighted_depot_distance": 100.0, "numerator_m": 100.0,
                 "denominator_lines": 4, "mean_per_line_m": 25.0, "stops": 8},
                {"layout": "optimized_fit", "pick_rule": "quantity_aware", "feasible": True,
                 "demand_weighted_depot_distance": 50.0, "numerator_m": 50.0,
                 "denominator_lines": 4, "mean_per_line_m": 12.5, "stops": 4},
            ],
            "effects": {"layout_effect_m": -50.0, "interaction_m": -10.0},
            "interpretation": {"caveat": "single deterministic workload"},
        },
        "replenishment": {"baseline_repaired": {"replenishment_travel_m": 10.0}},
        "sweep": {"selected_by_fit_objective": "default"},
        "methodology_caveat": "not a held-out result",
    }
    (tmp_path / "phase3_experiments.json").write_text(json.dumps(payload))

    view = load_phase3(tmp_path)
    assert view["status"] == "ok"
    assert view["evaluation_status"] == "held_out"
    assert view["leakage_checked"] is True
    assert view["baseline_variant"] == "repaired_minimal"
    assert len(view["cells"]) == 2
    assert view["cells"][1]["mean_per_line_m"] == 12.5
    assert view["feasibility"]["cell_feasibility"] == {
        "baseline_repaired": True, "optimized_fit": True
    }
    assert view["sweep"]["selected_by_fit_objective"] == "default"
    assert view["caveat"] == "not a held-out result"


def test_failed_leakage_checks_downgrade_the_status(tmp_path):
    payload = {
        "split": {"checks": {"all_passed": False}},
        "fit_run": {},
        "two_by_two": {"cells": []},
    }
    (tmp_path / "phase3_experiments.json").write_text(json.dumps(payload))
    view = load_phase3(tmp_path)
    assert view["evaluation_status"] == "in_sample_or_unverified"
    assert view["leakage_checked"] is False
