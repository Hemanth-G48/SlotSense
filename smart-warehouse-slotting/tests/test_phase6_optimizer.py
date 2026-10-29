"""Phase 6 optimizer tests: the single-record relocation path.

The Phase 6 audit found that ``_random_neighbor`` rejected every layout with fewer than two
records, so a one-record layout could never improve even when the only better bin was obvious.
These tests pin the fixed behaviour.
"""

from __future__ import annotations

from src.models.entities import AssignmentType, StorageAssignment, Warehouse
from src.optimization.objective import Objective
from src.optimization.optimizer import OptimizerConfig, SlottingOptimizer
from src.validation.validator import Validator
from tests.test_phase2_greedy_constraints import make_loc, make_sku


def _optimizer():
    wh = Warehouse("WH", "fixture", "1")
    wh.locations = {
        "L_FAR": make_loc("L_FAR", x=100.0, y=100.0),
        "L_NEAR": make_loc("L_NEAR", x=10.0, y=10.0),
    }
    skus = {"S1": make_sku("S1")}
    validator = Validator(skus, wh, [], inventory={"S1": 1}, separation_radius_m=10.0)
    opt = SlottingOptimizer(
        warehouse=wh,
        skus=skus,
        abc_classes={"S1": "A"},
        validator=validator,
        inventory={"S1": 1},
        objective=Objective(),
        demand={"S1": 10.0},
        cfg=OptimizerConfig(seed=7, max_iterations=200),
        separation_radius_m=10.0,
        compatibility_rules=[],
    )
    return opt


def test_single_record_neighbour_is_a_relocation_not_none():
    opt = _optimizer()
    start = [StorageAssignment("S1", "L_FAR", 1, AssignmentType.BASELINE)]
    cand = opt._random_neighbor(start)
    assert cand is not None
    assert len(cand) == 1
    assert cand[0].sku_id == "S1"
    assert cand[0].location_id in {"L_FAR", "L_NEAR"}
    assert cand[0].assigned_quantity == 1


def test_single_record_refine_moves_to_the_near_bin():
    opt = _optimizer()
    start = [StorageAssignment("S1", "L_FAR", 1, AssignmentType.BASELINE)]
    start_score = opt._score(start)
    refined = opt._refine(start)
    assert refined[0].location_id == "L_NEAR"
    assert opt._score(refined) < start_score
    assert opt.validator.validate(refined, record_checks=False).is_feasible


def test_empty_layout_still_returns_none():
    assert _optimizer()._random_neighbor([]) is None


def test_two_record_neighbour_preserves_quantities():
    opt = _optimizer()
    start = [
        StorageAssignment("S1", "L_FAR", 1, AssignmentType.BASELINE),
        StorageAssignment("S1", "L_NEAR", 1, AssignmentType.BASELINE),
    ]
    cand = opt._random_neighbor(start)
    assert cand is not None
    assert sum(a.assigned_quantity for a in cand if a.sku_id == "S1") == 2
