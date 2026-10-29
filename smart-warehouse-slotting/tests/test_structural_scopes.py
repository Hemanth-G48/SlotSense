"""Structural load rules: four scopes, each against its own limit.

The validator aggregates weight three ways (``_check_structural_limits``):

    LD-01  per bin                                   max_weight_kg
    SL-02  per (rack_id, bay, shelf_level)            beam_max_weight_kg
    SL-01  per (rack_id, shelf_level)                 level_max_weight_kg (shelf_ max alias)
    RK-01  per rack_id                                rack_max_weight_kg

These tests pin the *aggregation keys* and the *limits*, because getting either wrong is how
a warehouse passes a check it should fail. The last test is the repair contract: a relocation
that fixes a beam overload by breaking CAT-01 must be rejected.

Fixtures are built here; nothing reads or writes the shared ``outputs/`` tree.
"""

from __future__ import annotations

from collections import Counter, defaultdict

import pytest

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
from src.optimization.optimizer import OptimizerConfig, SlottingOptimizer, _split_quantity
from src.validation.validator import Validator

BIN_LIMIT_KG = 100.0
BEAM_LIMIT_KG = 180.0
LEVEL_LIMIT_KG = 300.0
RACK_LIMIT_KG = 500.0
BIN_VOLUME_CM3 = 108_000.0


# -- fixtures -------------------------------------------------------------------------
def structural_warehouse(
    *,
    n_levels: int = 3,
    bin_limit_kg: float = BIN_LIMIT_KG,
    beam_limit_kg: float | None = BEAM_LIMIT_KG,
    level_limit_kg: float = LEVEL_LIMIT_KG,
    rack_limit_kg: float = RACK_LIMIT_KG,
    rack_id: str = "R1",
) -> Warehouse:
    """One rack, 2 bays, ``n_levels`` levels, 2 bins per (bay, level)."""
    wh = Warehouse("WH1", "structural", "1")
    for bay in (0, 1):
        for level in range(n_levels):
            for k in (0, 1):
                lid = bin_id(bay, level, k, rack_id)
                wh.locations[lid] = Location(
                    location_id=lid,
                    zone_id="Z1",
                    aisle_id="A1",
                    rack_id=rack_id,
                    bay=bay,
                    shelf_level=level,
                    x=bay * 2.0 + k * 0.5,
                    y=level * 1.0,
                    z=level * 0.5,
                    width_cm=60.0,
                    height_cm=40.0,
                    depth_cm=45.0,
                    max_weight_kg=bin_limit_kg,
                    usable_volume_cm3=BIN_VOLUME_CM3,
                    ergonomic_zone=AccessibilityZone.GOLDEN,
                    allowed_handling=("standard", "fragile", "heavy"),
                    allowed_hazard=("NONE",),
                    distance_to_dispatch_m=1.0 + bay * 2.0 + level,
                    beam_max_weight_kg=beam_limit_kg,
                    level_max_weight_kg=level_limit_kg,
                    shelf_max_weight_kg=level_limit_kg,
                    rack_max_weight_kg=rack_limit_kg,
                )
    return wh


def bin_id(bay: int, level: int, k: int, rack_id: str = "R1") -> str:
    return f"{rack_id}-bay{bay}-lvl{level}-bin{k}"


def unit_sku(sku_id: str, category_id: str = "CAT001", unit_weight_kg: float = 1.0) -> SKU:
    """1 kg per unit unless stated: quantities then read directly as kilograms."""
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


def assign(sku_id: str, location_id: str, quantity: int) -> StorageAssignment:
    return StorageAssignment(sku_id, location_id, quantity, AssignmentType.OPTIMIZED)


def validate(warehouse: Warehouse, skus: dict, assignments: list, rules=None, inventory=None,
             radius=10.0):
    return Validator(
        skus, warehouse, rules or [], inventory=inventory, separation_radius_m=radius
    ).validate(assignments)


def checks_of(result, rule_id: str) -> list:
    return [c for c in result.checks if c.rule_id == rule_id]


def violation_rules(result) -> Counter:
    return Counter(v.rule_id for v in result.violations)


# -- beam (SL-02) ---------------------------------------------------------------------
def test_beam_capacity_exceeded_is_rejected():
    wh = structural_warehouse()
    skus = {"S1": unit_sku("S1"), "S2": unit_sku("S2")}
    # 95 + 95 kg on one beam (limit 180); bin limit 100 and level limit 300 are both fine.
    result = validate(wh, skus, [
        assign("S1", bin_id(0, 0, 0), 95),
        assign("S2", bin_id(0, 0, 1), 95),
    ])

    assert violation_rules(result) == Counter({"SL-02": 1}), [v.reason for v in result.violations]
    beam = checks_of(result, "SL-02")
    assert len(beam) == 1
    assert beam[0].passed is False
    assert beam[0].observed == pytest.approx(190.0)
    assert beam[0].limit == BEAM_LIMIT_KG
    assert beam[0].location_id == "R1 bay 0 shelf 0"
    # The other scopes really are legal — this is a beam-only failure.
    assert all(c.passed for c in checks_of(result, "LD-01"))
    assert all(c.passed for c in checks_of(result, "SL-01"))
    assert all(c.passed for c in checks_of(result, "RK-01"))


def test_beam_key_is_rack_bay_and_shelf_level_only():
    """Same rack and bay but a different shelf level is a DIFFERENT beam."""
    wh = structural_warehouse()
    skus = {"S1": unit_sku("S1")}
    result = validate(wh, skus, [
        assign("S1", bin_id(0, 0, 0), 95),
        assign("S1", bin_id(0, 1, 0), 95),
    ])

    assert violation_rules(result) == Counter(), [v.reason for v in result.violations]
    assert {c.location_id for c in checks_of(result, "SL-02")} == {
        "R1 bay 0 shelf 0",
        "R1 bay 0 shelf 1",
    }
    assert all(c.passed for c in checks_of(result, "SL-02"))


def test_same_level_across_bays_shares_the_level_scope_but_not_the_beam_scope():
    wh = structural_warehouse()
    skus = {"S1": unit_sku("S1"), "S2": unit_sku("S2")}
    result = validate(wh, skus, [
        assign("S1", bin_id(0, 0, 0), 95),
        assign("S2", bin_id(1, 0, 0), 95),
    ])

    assert violation_rules(result) == Counter(), [v.reason for v in result.violations]
    # Two beams (bay is part of the key), one level carrying both.
    assert {c.location_id for c in checks_of(result, "SL-02")} == {
        "R1 bay 0 shelf 0",
        "R1 bay 1 shelf 0",
    }
    level = checks_of(result, "SL-01")
    assert len(level) == 1
    assert level[0].location_id == "R1 shelf 0"
    assert level[0].observed == pytest.approx(190.0)


def test_beam_observed_values_equal_independent_sums_over_the_whole_layout():
    """Every beam check's observed value is the independent per-scope sum, not a per-bin load."""
    wh = structural_warehouse()
    skus = {"S1": unit_sku("S1"), "S2": unit_sku("S2"), "S3": unit_sku("S3")}
    placements = [
        ("S1", bin_id(0, 0, 0), 40),
        ("S2", bin_id(0, 0, 1), 35),  # beam (0,0) = 75
        ("S3", bin_id(1, 0, 0), 20),
        ("S1", bin_id(1, 0, 1), 10),  # beam (1,0) = 30
        ("S2", bin_id(0, 1, 0), 50),  # beam (0,1) = 50
        ("S3", bin_id(0, 2, 1), 15),  # beam (0,2) = 15
    ]
    expected: dict[tuple[str, int, int], float] = defaultdict(float)
    for sku_id, loc_id, qty in placements:
        loc = wh.locations[loc_id]
        expected[(loc.rack_id, loc.bay, loc.shelf_level)] += skus[sku_id].unit_weight_kg * qty

    result = validate(wh, skus, [assign(*p) for p in placements])
    observed = {
        c.location_id: c.observed for c in checks_of(result, "SL-02")
    }
    assert observed == {
        f"{rack} bay {bay} shelf {level}": pytest.approx(load)
        for (rack, bay, level), load in expected.items()
    }
    assert violation_rules(result) == Counter()


# -- level (SL-01) and rack (RK-01) ----------------------------------------------------
def test_level_limit_binds_while_every_beam_passes():
    wh = structural_warehouse()
    skus = {"S1": unit_sku("S1"), "S2": unit_sku("S2")}
    # 4 bins x 80 kg on ONE level: beams 160 (limit 180), level 320 (limit 300).
    result = validate(wh, skus, [
        assign("S1", bin_id(0, 0, 0), 80),
        assign("S1", bin_id(0, 0, 1), 80),
        assign("S2", bin_id(1, 0, 0), 80),
        assign("S2", bin_id(1, 0, 1), 80),
    ])

    assert violation_rules(result) == Counter({"SL-01": 1}), [v.reason for v in result.violations]
    assert all(c.passed for c in checks_of(result, "SL-02"))
    level = checks_of(result, "SL-01")
    assert level[0].observed == pytest.approx(320.0)
    assert level[0].limit == LEVEL_LIMIT_KG
    assert all(c.passed for c in checks_of(result, "RK-01"))


def test_rack_limit_binds_while_levels_and_beams_pass():
    wh = structural_warehouse()
    skus = {"S1": unit_sku("S1")}
    # One bay, three levels, two bins each: beam 178, level 178, rack 534 (limit 500).
    assignments = []
    for level in range(3):
        assignments.append(assign("S1", bin_id(0, level, 0), 89))
        assignments.append(assign("S1", bin_id(0, level, 1), 89))
    result = validate(wh, skus, assignments)

    assert violation_rules(result) == Counter({"RK-01": 1}), [v.reason for v in result.violations]
    assert all(c.passed for c in checks_of(result, "SL-02"))
    assert all(c.passed for c in checks_of(result, "SL-01"))
    rack = checks_of(result, "RK-01")
    assert rack[0].observed == pytest.approx(534.0)
    assert rack[0].limit == RACK_LIMIT_KG


def test_bin_limit_binds_before_any_aggregate():
    wh = structural_warehouse()
    skus = {"S1": unit_sku("S1")}
    result = validate(wh, skus, [assign("S1", bin_id(0, 0, 0), 101)])

    assert violation_rules(result) == Counter({"LD-01": 1}), [v.reason for v in result.violations]
    assert all(c.passed for c in checks_of(result, "SL-02"))
    assert all(c.passed for c in checks_of(result, "SL-01"))
    assert all(c.passed for c in checks_of(result, "RK-01"))


# -- the placer's share of the same rule -----------------------------------------------
@pytest.mark.parametrize(
    ("unit_weight", "beam_residual", "wanted", "expected"),
    [
        (2.0, 50.0, 100, 25),  # beam binds at 25 units
        (7.0, 50.0, 100, 7),  # 8 x 7 kg would exceed 50 kg
        (1.0, 10.0, 100, 10),  # beam binds, bin (100 kg) does not
        (1.0, 0.0, 100, 0),  # no beam capacity left at all
        (1.0, 500.0, 12, 12),  # wanted is the binding limit
    ],
)
def test_placer_never_allocates_more_than_the_beam_residual(
    unit_weight, beam_residual, wanted, expected
):
    wh = structural_warehouse()
    loc = wh.locations[bin_id(0, 0, 0)]
    sku = unit_sku("S1", unit_weight_kg=unit_weight)

    quantity = _split_quantity(sku, loc, wanted, residual_beam_weight=beam_residual)

    assert quantity == expected
    assert quantity * unit_weight <= beam_residual + 1e-9


# -- repair must not trade one violation for another -----------------------------------
def adversarial_repair_setup():
    """A beam overload whose only fixes would create a CAT-01 violation.

    Layout (1 kg per unit):
        over-a  (x=0)   S1 CAT001 95 units   } same beam  -> 190 kg > 180 kg
        over-b  (x=1)   S1 CAT001 95 units   }
        free    (x=20)  unoccupied           -> moving either S1 record here puts CAT001
        guard-a (x=25)  S4 CAT003 1 unit       5 m / 9 m from CAT003 bins -> CAT-01
        guard-b (x=29)  S5 CAT003 1 unit     -> swapping S1 into either guard bin puts the
                                                other CAT003 bin 4 m away -> CAT-01
    """
    wh = Warehouse("WH1", "adversarial", "1")

    def add(lid: str, x: float, rack: str, bay: int) -> None:
        wh.locations[lid] = Location(
            location_id=lid, zone_id="Z1", aisle_id="A1", rack_id=rack, bay=bay, shelf_level=0,
            x=x, y=0.0, z=0.0, width_cm=60.0, height_cm=40.0, depth_cm=45.0,
            max_weight_kg=BIN_LIMIT_KG, usable_volume_cm3=BIN_VOLUME_CM3,
            ergonomic_zone=AccessibilityZone.GOLDEN,
            allowed_handling=("standard", "fragile", "heavy"), allowed_hazard=("NONE",),
            distance_to_dispatch_m=1.0 + x,
            beam_max_weight_kg=BEAM_LIMIT_KG, level_max_weight_kg=LEVEL_LIMIT_KG,
            shelf_max_weight_kg=LEVEL_LIMIT_KG, rack_max_weight_kg=RACK_LIMIT_KG,
        )

    add("over-a", 0.0, "R1", 0)
    add("over-b", 1.0, "R1", 0)
    add("free", 20.0, "R2", 0)
    add("guard-a", 25.0, "R2", 0)
    add("guard-b", 29.0, "R2", 1)

    skus = {
        "S1": unit_sku("S1", "CAT001"),
        "S4": unit_sku("S4", "CAT003"),
        "S5": unit_sku("S5", "CAT003"),
    }
    rules = [CompatibilityRule("CR1", "CAT001", "CAT003", allowed=False)]
    inventory = {"S1": 190, "S4": 1, "S5": 1}
    assignments = [
        assign("S1", "over-a", 95),
        assign("S1", "over-b", 95),
        assign("S4", "guard-a", 1),
        assign("S5", "guard-b", 1),
    ]
    validator = Validator(skus, wh, rules, inventory=inventory, separation_radius_m=10.0)
    optimizer = SlottingOptimizer(
        warehouse=wh,
        skus=skus,
        abc_classes={sku: "A" for sku in skus},
        validator=validator,
        inventory=inventory,
        cfg=OptimizerConfig(seed=7),
        separation_radius_m=10.0,
        compatibility_rules=rules,
    )
    return wh, skus, rules, inventory, assignments, validator, optimizer


def test_repair_will_not_fix_a_beam_violation_by_creating_a_cat01_violation():
    wh, skus, rules, inventory, assignments, validator, optimizer = adversarial_repair_setup()
    start = validator.validate(assignments)
    assert violation_rules(start) == Counter({"SL-02": 1}), [v.reason for v in start.violations]

    # Control: the naive relocation really does fix SL-02 and really does create CAT-01,
    # so this fixture is adversarial rather than merely unsatisfiable.
    naive = [
        assign("S1", "free", 95),
        assign("S1", "over-b", 95),
        assign("S4", "guard-a", 1),
        assign("S5", "guard-b", 1),
    ]
    naive_result = validator.validate(naive)
    assert "SL-02" not in violation_rules(naive_result)
    assert violation_rules(naive_result)["CAT-01"] >= 1
    assert not naive_result.is_feasible

    repaired, stats = optimizer._repair(assignments, start)

    assert stats.moves_attempted > 0, "the repair loop must actually screen candidate moves"
    assert stats.moves_accepted == 0
    assert stats.termination_reason in {"no_improving_move", "max_moves"}
    final = validator.validate(repaired)
    assert violation_rules(final) == Counter({"SL-02": 1}), [v.reason for v in final.violations]
    assert "CAT-01" not in violation_rules(final), "repair traded a beam violation for CAT-01"
    assert not final.is_feasible


def test_repair_will_not_fix_a_beam_violation_by_creating_a_level_violation():
    """A beam overload may not be pushed onto the shelf level that the free bins belong to.

    Layout (1 kg per unit, one rack, three bays):
        beam (R1, 0, 0):  95 + 95 = 190 kg          -> SL-02
        beam (R1, 1, 1):  90 + 90 = 180 kg          -> legal (at the limit)
        level (R1, 1):    40 + 90 + 90 = 220 kg     -> legal (limit 300), free bins b1/d0/d1
        moving one 95 kg record into any free bin makes the level 315 kg -> SL-01

    The second SKU is hazard-restricted to level 1, so no swap can move the 95 kg records out
    of the overloaded beam: relocation is the only candidate, and every relocation creates a
    level violation — which the repair loop must refuse.
    """
    wh = Warehouse("WH1", "structural-trade", "1")

    def add(bay: int, level: int, k: int) -> str:
        lid = f"L{bay}{level}{k}"
        wh.locations[lid] = Location(
            location_id=lid, zone_id="Z1", aisle_id="A1", rack_id="R1", bay=bay, shelf_level=level,
            x=bay * 2.0 + k * 0.5, y=level * 1.0, z=level * 0.5,
            width_cm=60.0, height_cm=40.0, depth_cm=45.0,
            max_weight_kg=BIN_LIMIT_KG, usable_volume_cm3=BIN_VOLUME_CM3,
            ergonomic_zone=AccessibilityZone.GOLDEN,
            allowed_handling=("standard", "fragile", "heavy"),
            # Hazardous stock is only accepted on level 1, which removes the swap route out
            # of the overloaded beam and leaves relocation as the only repair move.
            allowed_hazard=("NONE", "flammable") if level == 1 else ("NONE",),
            distance_to_dispatch_m=1.0 + bay + level,
            beam_max_weight_kg=BEAM_LIMIT_KG, level_max_weight_kg=LEVEL_LIMIT_KG,
            shelf_max_weight_kg=LEVEL_LIMIT_KG, rack_max_weight_kg=RACK_LIMIT_KG,
        )
        return lid

    overload_a, overload_b = add(0, 0, 0), add(0, 0, 1)
    level_b0, level_b1 = add(0, 1, 0), add(0, 1, 1)  # level_b1 stays free
    level_c0, level_c1 = add(1, 1, 0), add(1, 1, 1)
    level_d0, level_d1 = add(2, 1, 0), add(2, 1, 1)  # both free

    skus = {
        "S1": unit_sku("S1", "CAT001"),
        "S2": SKU(
            sku_id="S2", product_name="S2", category_id="CAT002",
            width_cm=10.0, height_cm=10.0, depth_cm=10.0, unit_weight_kg=1.0,
            handling_type=HandlingType.STANDARD, hazard_class=HazardClass.FLAMMABLE,
        ),
    }
    inventory = {"S1": 190, "S2": 220}
    assignments = [
        assign("S1", overload_a, 95),
        assign("S1", overload_b, 95),
        assign("S2", level_b0, 40),
        assign("S2", level_c0, 90),
        assign("S2", level_c1, 90),
    ]
    validator = Validator(skus, wh, [], inventory=inventory, separation_radius_m=10.0)
    optimizer = SlottingOptimizer(
        warehouse=wh,
        skus=skus,
        abc_classes={"S1": "A", "S2": "B"},
        validator=validator,
        inventory=inventory,
        cfg=OptimizerConfig(seed=7),
        separation_radius_m=10.0,
        compatibility_rules=[],
    )

    start = validator.validate(assignments)
    assert violation_rules(start) == Counter({"SL-02": 1}), [v.reason for v in start.violations]

    # Control: moving a 95 kg record into a free level-1 bin does clear the beam and does
    # overload the level, so the trade-off really was available to the repair loop.
    naive = [
        assign("S1", level_b1, 95),
        assign("S1", overload_b, 95),
        assign("S2", level_b0, 40),
        assign("S2", level_c0, 90),
        assign("S2", level_c1, 90),
    ]
    naive_result = validator.validate(naive)
    assert violation_rules(naive_result) == Counter({"SL-01": 1}), [
        v.reason for v in naive_result.violations
    ]

    repaired, stats = optimizer._repair(assignments, start)

    assert stats.moves_attempted > 0
    assert stats.moves_accepted == 0
    final = validator.validate(repaired)
    assert violation_rules(final) == Counter({"SL-02": 1}), [v.reason for v in final.violations]
    assert "SL-01" not in violation_rules(final), "repair traded a beam violation for a level one"
    assert set(violation_rules(final)) <= set(violation_rules(start))
