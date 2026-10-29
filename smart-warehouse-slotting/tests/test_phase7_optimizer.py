"""Phase 7 tests: targeted neighbourhood, comparison artifact, timing sensitivity."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.models.entities import AssignmentType, StorageAssignment, Warehouse
from src.optimization.objective import Objective
from src.optimization.optimizer import OptimizerConfig, SlottingOptimizer
from src.validation.validator import Validator
from tests.test_phase2_greedy_constraints import make_loc, make_sku

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "phase7"


def _opt(neighborhood: str):
    wh = Warehouse("WH", "fixture", "1")
    wh.locations = {
        "L1": make_loc("L1", x=1.0, y=1.0),
        "L2": make_loc("L2", x=2.0, y=2.0),
        "L3": make_loc("L3", x=3.0, y=3.0),
    }
    skus = {"S1": make_sku("S1")}
    validator = Validator(skus, wh, [], inventory={"S1": 1}, separation_radius_m=10.0)
    return SlottingOptimizer(
        warehouse=wh,
        skus=skus,
        abc_classes={"S1": "A"},
        validator=validator,
        inventory={"S1": 1},
        objective=Objective(),
        demand={"S1": 10.0},
        cfg=OptimizerConfig(seed=7, max_iterations=50, neighborhood=neighborhood),
        separation_radius_m=10.0,
        compatibility_rules=[],
    )


def test_invalid_neighborhood_is_rejected():
    with pytest.raises(ValueError, match="neighborhood"):
        OptimizerConfig(neighborhood="random")


def test_targeted_relocation_never_targets_an_occupied_bin():
    opt = _opt("targeted")
    start = [
        StorageAssignment("S1", "L1", 1, AssignmentType.BASELINE),
        StorageAssignment("S1", "L2", 1, AssignmentType.BASELINE),
    ]
    for _ in range(40):
        cand = opt._random_neighbor(start)
        assert cand is not None
        locations = [a.location_id for a in cand]
        assert len(locations) == len(set(locations)), "targeted relocation duplicated a bin"


def test_legacy_and_targeted_both_preserve_quantities():
    for neighborhood in ("legacy", "targeted"):
        opt = _opt(neighborhood)
        start = [StorageAssignment("S1", "L1", 1, AssignmentType.BASELINE)]
        cand = opt._random_neighbor(start)
        assert cand is not None
        assert sum(a.assigned_quantity for a in cand) == 1


@pytest.mark.skipif(not (OUT / "optimizer_compare.json").exists(), reason="Phase 7 comparison not run")
def test_comparison_artifact_shows_better_proposal_yield_without_forcing_layout_change():
    data = json.loads((OUT / "optimizer_compare.json").read_text())
    legacy = data["results"]["legacy"]["proposal_probe"]
    targeted = data["results"]["targeted"]["proposal_probe"]
    assert targeted["feasible"] > legacy["feasible"]
    assert targeted["improving"] >= legacy["improving"]
    assert data["same_layout"] is True
    assert data["objective_delta_targeted_minus_legacy"] == 0.0
    assert data["results"]["targeted"]["validation"]["feasible"] is True


@pytest.mark.skipif(not (OUT / "timing_sensitivity.json").exists(), reason="timing sensitivity not run")
def test_timing_sensitivity_keeps_travel_fixed_and_labels_hypothetical_values():
    data = json.loads((OUT / "timing_sensitivity.json").read_text())
    assert data["travel_unchanged_within_basis"] is True
    assert "not physically calibrated" in data["status"]
    assert {r["pick_time_sec"] for r in data["rows"]} == {6.0, 8.0, 10.0}
    assert all(r["feasible"] for r in data["rows"])
    assert all(r["baseline_travel_m"] == 508174.8 for r in data["rows"])
    assert all(r["optimized_travel_m"] == 234208.0 for r in data["rows"])
