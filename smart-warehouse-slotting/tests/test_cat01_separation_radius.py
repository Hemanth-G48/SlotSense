"""CAT-01 category separation: the radius contract, on fixtures this test owns.

The rule (ARCHITECTURE.md §8.1, validator ``_check_category_separation``):

    two bins holding a forbidden category pair must be at least R metres apart in 3-D,
    where a pair at exactly R is ALLOWED — the comparison is ``distance + 1e-9 >= radius``.

Everything here is deterministic geometry: two bins, a known distance, one rule. No test in
this file reads or writes the shared ``outputs/`` tree.

The last two tests are the cross-component contract: the *same* configured radius must reach
both the placer (``SlottingOptimizer``) and the judge (``Validator``), through the real
``run_phase5`` pipeline on a tiny owned dataset.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd
import pytest

from src.models.config import DEFAULT_SEPARATION_RADIUS_M, Config
from src.models.entities import (
    AccessibilityZone,
    AssignmentType,
    CompatibilityRule,
    HandlingType,
    HazardClass,
    Location,
    SKU,
    StorageAssignment,
    Warehouse,
)
from src.optimization.optimizer import OptimizerConfig, SlottingOptimizer
from src.optimization.pipeline import run_phase5
from src.validation.loader import load_shipping
from src.validation.validator import Validator
from tests.phase2_fixtures import tiny_config, write_tiny_dataset

PROJECT_ROOT = Path(__file__).resolve().parent.parent

CAT_A = "CAT001"
CAT_B = "CAT010"  # forbidden partner of CAT_A in the fixtures below
CAT_C = "CAT002"  # compatible with CAT_A


# -- fixtures -------------------------------------------------------------------------
def make_sku(sku_id: str, category_id: str, unit_weight_kg: float = 1.0) -> SKU:
    return SKU(
        sku_id=sku_id,
        product_name=sku_id,
        category_id=category_id,
        width_cm=10.0,
        height_cm=10.0,
        depth_cm=10.0,
        unit_weight_kg=unit_weight_kg,
        handling_type=HandlingType.STANDARD,
        hazard_class=HazardClass.NONE,
    )


def make_bin(location_id: str, x: float) -> Location:
    """A bin whose only meaningful property is its x coordinate (CAT-01 geometry)."""
    return Location(
        location_id=location_id,
        zone_id="Z1",
        aisle_id="A1",
        rack_id=f"R{location_id}",
        bay=0,
        shelf_level=0,
        x=x,
        y=0.0,
        z=0.0,
        width_cm=60.0,
        height_cm=40.0,
        depth_cm=45.0,
        max_weight_kg=1000.0,
        usable_volume_cm3=1_000_000.0,
        ergonomic_zone=AccessibilityZone.GOLDEN,
        allowed_handling=("standard", "fragile", "heavy"),
        allowed_hazard=("NONE",),
        distance_to_dispatch_m=1.0 + x,
        # Structural limits are left unset so a CAT-01 fixture cannot also trip SL/RK.
    )


def pair_warehouse(distance_m: float) -> Warehouse:
    """Two bins, exactly ``distance_m`` apart along x."""
    wh = Warehouse("WH1", "cat01", "1")
    wh.locations["L0"] = make_bin("L0", 0.0)
    wh.locations["L1"] = make_bin("L1", float(distance_m))
    return wh


def pair_skus() -> dict[str, SKU]:
    return {"S1": make_sku("S1", CAT_A), "S2": make_sku("S2", CAT_B)}


def pair_assignments() -> list[StorageAssignment]:
    return [
        StorageAssignment("S1", "L0", 1, AssignmentType.OPTIMIZED),
        StorageAssignment("S2", "L1", 1, AssignmentType.OPTIMIZED),
    ]


FORBIDDEN_RULES = [CompatibilityRule("CR1", CAT_A, CAT_B, allowed=False, severity="high")]


def run_pair(distance_m: float, radius_m: float, rules=None):
    """Validate the same two-SKU layout at a given physical distance and radius."""
    wh = pair_warehouse(distance_m)
    skus = pair_skus()
    result = Validator(
        skus, wh, rules if rules is not None else FORBIDDEN_RULES, separation_radius_m=radius_m
    ).validate(pair_assignments())
    cat_checks = [c for c in result.checks if c.rule_id == "CAT-01"]
    return result, cat_checks


# -- the rule itself ------------------------------------------------------------------
def test_forbidden_pair_closer_than_radius_is_rejected():
    result, cat_checks = run_pair(distance_m=5.0, radius_m=10.0)

    assert not result.is_feasible
    violations = [v for v in result.violations if v.rule_id == "CAT-01"]
    assert len(violations) == 1, [v.reason for v in result.violations]
    assert "< 10 m" in violations[0].reason

    assert len(cat_checks) == 1
    assert cat_checks[0].passed is False
    assert cat_checks[0].observed == pytest.approx(5.0)
    assert cat_checks[0].limit == 10.0
    assert cat_checks[0].unit == "m (3-D)"


def test_forbidden_pair_beyond_radius_is_allowed():
    # 15 m with R = 10: still inside the validator's neighbour cells, so the pair is
    # actually compared (and passes) rather than skipped.
    result, cat_checks = run_pair(distance_m=15.0, radius_m=10.0)

    assert result.is_feasible, [v.reason for v in result.violations]
    assert len(cat_checks) == 1
    assert cat_checks[0].passed is True
    assert cat_checks[0].observed == pytest.approx(15.0)


@pytest.mark.parametrize(
    ("distance_m", "expected_passed"),
    [
        (9.999, False),  # strictly inside the radius
        (10.0, True),  # exactly on the radius: inclusive, by documented semantics
        (10.001, True),  # just outside
    ],
)
def test_radius_boundary_is_inclusive(distance_m, expected_passed):
    """The rule is ``distance + 1e-9 >= radius`` — a pair at exactly R is legal."""
    result, cat_checks = run_pair(distance_m=distance_m, radius_m=10.0)

    assert len(cat_checks) == 1
    assert cat_checks[0].passed is expected_passed
    assert cat_checks[0].observed == pytest.approx(distance_m)
    assert result.is_feasible is expected_passed
    # The same comparison, restated in the test: this is the documented contract.
    assert bool(distance_m + 1e-9 >= 10.0) is expected_passed


def test_float_tolerance_absorbs_representation_noise_at_the_boundary():
    """A distance that is R only up to float noise is still treated as legal."""
    distance_m = 10.0 - 5e-10
    assert distance_m < 10.0  # the raw float really is below the radius
    result, cat_checks = run_pair(distance_m=distance_m, radius_m=10.0)

    assert len(cat_checks) == 1
    assert cat_checks[0].passed is True
    assert result.is_feasible


def test_compatible_pair_close_together_is_not_flagged():
    """A permitted category pair is not a separation constraint at all."""
    rules = [CompatibilityRule("CR1", CAT_A, CAT_C, allowed=True)]
    wh = pair_warehouse(1.0)
    skus = {"S1": make_sku("S1", CAT_A), "S2": make_sku("S2", CAT_C)}
    assignments = [
        StorageAssignment("S1", "L0", 1, AssignmentType.OPTIMIZED),
        StorageAssignment("S2", "L1", 1, AssignmentType.OPTIMIZED),
    ]
    result = Validator(skus, wh, rules, separation_radius_m=10.0).validate(assignments)

    assert result.is_feasible
    assert not [c for c in result.checks if c.rule_id == "CAT-01"], (
        "a compatible pair must not even be evaluated against CAT-01"
    )
    assert not [v for v in result.violations if v.rule_id == "CAT-01"]


def test_self_pair_is_not_a_separation_constraint():
    """Two SKUs of the SAME category are never a forbidden pair, whatever the matrix says."""
    rules = [CompatibilityRule("CR1", CAT_A, CAT_A, allowed=False)]
    wh = pair_warehouse(1.0)
    skus = {"S1": make_sku("S1", CAT_A), "S2": make_sku("S2", CAT_A)}
    assignments = [
        StorageAssignment("S1", "L0", 1, AssignmentType.OPTIMIZED),
        StorageAssignment("S2", "L1", 1, AssignmentType.OPTIMIZED),
    ]
    result = Validator(skus, wh, rules, separation_radius_m=10.0).validate(assignments)

    assert result.is_feasible
    assert not [v for v in result.violations if v.rule_id == "CAT-01"]


def test_zero_radius_disables_the_rule():
    result, cat_checks = run_pair(distance_m=1.0, radius_m=0.0)

    assert result.is_feasible
    assert cat_checks == []


# -- the configured radius, not a default ----------------------------------------------
def test_validator_uses_the_configured_radius_not_the_default():
    assert DEFAULT_SEPARATION_RADIUS_M == 10.0  # the documented default

    tight, _ = run_pair(distance_m=5.0, radius_m=DEFAULT_SEPARATION_RADIUS_M)
    assert not tight.is_feasible, "5 m is inside the 10 m default"

    loose, _ = run_pair(distance_m=5.0, radius_m=4.0)
    assert loose.is_feasible, "5 m is outside a configured 4 m radius"


def test_optimizer_refuses_to_use_a_different_radius_than_its_validator():
    """One radius, one source: an explicit mismatch is a bug, not something to guess around."""
    wh = pair_warehouse(5.0)
    skus = pair_skus()
    validator = Validator(skus, wh, FORBIDDEN_RULES, separation_radius_m=10.0)

    with pytest.raises(ValueError, match="separation_radius_m mismatch"):
        SlottingOptimizer(
            warehouse=wh,
            skus=skus,
            abc_classes={"S1": "A", "S2": "B"},
            validator=validator,
            inventory={"S1": 1, "S2": 1},
            cfg=OptimizerConfig(seed=7),
            separation_radius_m=4.0,
        )


def test_pipeline_honours_one_configured_radius_in_both_placer_and_validator(tmp_path):
    """End-to-end: the radius in ``Config`` decides both the placement and the verdict.

    At R = 10 m the tiny fixture is placeable (rack 0 and rack 1 are 10 m apart, which the
    inclusive rule allows). At R = 11 m it is not: no two bins are 11 m apart, so the
    CAT-003 SKU cannot be placed anywhere without breaking the rule. If the optimizer used a
    hard-coded radius instead of the configured one, these two runs could not differ.
    """
    processed = tmp_path / "processed"
    dataset = write_tiny_dataset(processed, baseline="feasible")

    at_10 = run_phase5(processed, tiny_config(10.0), tmp_path / "opt_r10")
    at_11 = run_phase5(processed, tiny_config(11.0), tmp_path / "opt_r11")

    # -- radius is reported, not guessed ---------------------------------------
    assert at_10["separation_radius_m"] == 10.0
    assert at_11["separation_radius_m"] == 11.0
    assert at_10["separation_grid"]["radius_m"] == 10.0
    assert at_11["separation_grid"]["radius_m"] == 11.0

    # -- placer (optimizer) honours it ----------------------------------------
    assert at_10["feasibility_status"] == "FEASIBLE"
    assert at_10["units_placed"] == dataset.total_units
    assert at_11["feasibility_status"] == "INFEASIBLE"
    blocked = {u["sku_id"]: u for u in at_11["unplaced_skus"]}
    assert "SKU004" in blocked, at_11["unplaced_skus"]
    assert blocked["SKU004"]["binding_reason"] == "separation"
    assert at_11["separation_grid"]["rejections"] > at_10["separation_grid"]["rejections"]

    # -- judge (validator) honours it, independently of the optimizer ---------
    assignments = pd.read_csv(tmp_path / "opt_r10" / "optimized_assignments.csv")
    wh, skus, comp, _baseline, _inventory = load_shipping(processed)
    objects = [
        StorageAssignment(r.sku_id, r.location_id, int(r.assigned_quantity), AssignmentType.OPTIMIZED)
        for r in assignments.itertuples(index=False)
    ]

    assert Validator(skus, wh, comp, separation_radius_m=10.0).validate(objects).is_feasible
    violations_11 = Validator(skus, wh, comp, separation_radius_m=11.0).validate(objects).violations
    assert [v for v in violations_11 if v.rule_id == "CAT-01"], (
        "the layout that is legal at 10 m must violate the rule at 11 m"
    )

    # -- and the geometric claim behind those verdicts ------------------------
    locations = pd.read_csv(processed / "locations.csv").set_index("location_id")
    cat_a_bins = set(assignments.loc[assignments.sku_id.isin(["SKU001", "SKU002"]), "location_id"])
    cat_b_bins = set(assignments.loc[assignments.sku_id == "SKU004", "location_id"])
    for a in cat_a_bins:
        for b in cat_b_bins:
            distance = math.dist(
                tuple(float(locations.loc[a][k]) for k in ("x_m", "y_m", "z_m")),
                tuple(float(locations.loc[b][k]) for k in ("x_m", "y_m", "z_m")),
            )
            assert distance + 1e-9 >= 10.0, (a, b, distance)


def test_benchmark_configuration_carries_the_radius_explicitly():
    """The radius in force is a configured value, not an invisible constructor default."""
    raw = json.loads((PROJECT_ROOT / "configs" / "benchmark.json").read_text())
    assert "separation_radius_m" in raw
    assert Config.from_json(PROJECT_ROOT / "configs" / "benchmark.json").separation_radius_m == 10.0
