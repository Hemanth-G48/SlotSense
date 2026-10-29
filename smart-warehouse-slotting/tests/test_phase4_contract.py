"""Tests for the Phase 4 dashboard contract: pass-through, missing values, verification status."""

from __future__ import annotations

import json

from app.phase4_contract import UNAVAILABLE, load_phase4


def test_missing_phase4_artifacts_are_unavailable_not_zero(tmp_path):
    view = load_phase4(tmp_path)
    assert view["status"] == UNAVAILABLE
    assert view["cells"] == UNAVAILABLE
    assert view["effects"] == UNAVAILABLE
    assert view["verification"] == UNAVAILABLE
    assert "run " in view["caveat"]


def test_contract_passes_through_cells_regimes_and_verification(tmp_path):
    payload = {
        "experiment_id": "phase4-test",
        "generated_at_utc": "2026-10-29T00:00:00Z",
        "frozen": {"refit_after_holdout": False, "optimized_sha256": "abc"},
        "phase3": {"baseline_variant": "repaired_minimal"},
        "design": {"factors": {"layout": ["baseline_repaired", "optimized_fit"]}},
        "cells": [
            {
                "cell_id": "A1",
                "layout": "baseline_repaired",
                "picking_policy": "nearest_neighbor",
                "feasible": True,
                "assignment_completeness": {"pct": 100.0},
                "metrics": {
                    "total_travel_distance_m": 100.0,
                    "total_route_time_sec": 50.0,
                    "throughput_orders_per_hr": 10.0,
                    "avg_time_per_order_sec": 5.0,
                },
                "layout_metrics": {
                    "demand_weighted_depot_distance": 90.0,
                    "fragmentation": {"bins_used": 4, "multi_bin_skus": 1},
                    "replenishment": {"replenishment_travel_m": 30.0},
                },
                "workload_id": "wl_x",
            }
        ],
        "effects": {"total_travel_distance_m": {"factor_a_effect": -50.0}},
        "regimes": {"rows": [{"regime": "B", "travel_change_pct": -30.0}]},
        "sweep": {"selected_config": "default"},
        "headroom": [{"layout": "optimized_fit", "scope": "bin_weight"}],
        "diagnostics": {"holdout": {"nearest_neighbor": {"optimized": {"status": "feasible"}}}},
    }
    (tmp_path / "phase4_experiments.json").write_text(json.dumps(payload))
    (tmp_path / "verification.json").write_text(
        json.dumps({"all_passed": True, "n_checks": 14, "n_failed": 0, "checks": []})
    )

    view = load_phase4(tmp_path)
    assert view["status"] == "ok"
    assert view["evaluation_status"] == "held_out"
    assert view["verification"]["all_passed"] is True
    assert view["verification"]["n_checks"] == 14
    assert view["cells"][0]["total_travel_distance_m"] == 100.0
    assert view["cells"][0]["demand_weighted_depot_distance"] == 90.0
    assert view["cells"][0]["replenishment_travel_m"] == 30.0
    assert view["regimes"]["rows"][0]["regime"] == "B"
    assert view["diagnostics"]["holdout"]["nearest_neighbor"]["optimized"] == "feasible"


def test_failed_verification_downgrades_evaluation_status(tmp_path):
    payload = {
        "frozen": {"refit_after_holdout": False},
        "cells": [],
        "effects": {},
    }
    (tmp_path / "phase4_experiments.json").write_text(json.dumps(payload))
    (tmp_path / "verification.json").write_text(
        json.dumps({"all_passed": False, "n_checks": 3, "n_failed": 1, "checks": []})
    )
    view = load_phase4(tmp_path)
    assert view["evaluation_status"] == "unverified_or_in_sample"
    assert view["verification"]["all_passed"] is False
