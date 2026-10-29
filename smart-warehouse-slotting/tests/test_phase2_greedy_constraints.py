"""Phase-2 P2-1 tests: constraint-aware starter (beam capacity + CAT-01) and the explicit
separation radius.

These are the guarantees the greedy now claims, each exercised on a fixture small enough to
reason about by hand:

* a placement is never accepted that would push a beam over ``beam_max_weight_kg`` (SL-02),
  even when both bins of the beam could individually take more;
* a candidate bin inside the CAT-01 radius of a forbidden category is refused, the refusal
  mutates nothing, and the layout the validator later sees has no CAT-01 violation;
* the radius comes from one place (``Config``), defaults to the documented 10 m, and a
  negative radius is rejected rather than clamped;
* a SKU that cannot be fully placed is reported with the constraint that bound it.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from src.models.config import (
    DEFAULT_SEPARATION_RADIUS_M,
    Config,
    coerce_separation_radius_m,
)
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
from src.optimization.objective import Objective
from src.optimization.optimizer import (
    BINDING_CAPACITY,
    BINDING_SEPARATION,
    SlottingOptimizer,
    _split_quantity,
    _units_affordable,
)
from src.optimization.separation import SeparationGrid, forbidden_pairs_from_rules
from src.validation.validator import Validator

PROJECT_ROOT = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------- fixtures
def make_loc(
    loc_id: str,
    *,
    rack: str = "R1",
    bay: int = 0,
    level: int = 0,
    x: float = 0.0,
    y: float = 0.0,
    z: float = 0.0,
    bin_cap: float = 100.0,
    beam_cap: float | None = 180.0,
    level_cap: float | None = 288.0,
    rack_cap: float | None = 1000.0,
    allowed_handling=("standard", "fragile", "heavy"),
    allowed_hazard=("NONE", "flammable"),
    volume: float = 108_000.0,
) -> Location:
    return Location(
        location_id=loc_id,
        zone_id="Z1",
        aisle_id="A1",
        rack_id=rack,
        bay=bay,
        shelf_level=level,
        x=x,
        y=y,
        z=z,
        width_cm=60.0,
        height_cm=40.0,
        depth_cm=45.0,
        max_weight_kg=bin_cap,
        usable_volume_cm3=volume,
        ergonomic_zone=AccessibilityZone.GOLDEN,
        allowed_handling=tuple(allowed_handling),
        allowed_hazard=tuple(allowed_hazard),
        distance_to_dispatch_m=y,
        beam_max_weight_kg=beam_cap,
        level_max_weight_kg=level_cap,
        shelf_max_weight_kg=level_cap,
        rack_max_weight_kg=rack_cap,
    )


def make_sku(sku_id: str, *, category: str = "CAT001", weight: float = 1.0,
             handling: HandlingType = HandlingType.STANDARD,
             hazard: HazardClass = HazardClass.NONE) -> SKU:
    return SKU(
        sku_id=sku_id,
        product_name=sku_id,
        category_id=category,
        width_cm=10.0,
        height_cm=10.0,
        depth_cm=10.0,
        unit_weight_kg=weight,
        handling_type=handling,
        hazard_class=hazard,
    )


def build_optimizer(warehouse, skus, inventory, rules=None, *, radius=None, demand=None):
    validator = Validator(
        skus, warehouse, rules or [], inventory=inventory,
        separation_radius_m=DEFAULT_SEPARATION_RADIUS_M if radius is None else radius,
    )
    return SlottingOptimizer(
        warehouse=warehouse,
        skus=skus,
        abc_classes={sid: "A" for sid in skus},
        validator=validator,
        inventory=inventory,
        objective=Objective(),
        demand=demand or {},
        separation_radius_m=radius,
        compatibility_rules=rules or [],
    )


def beam_loads(assignments, warehouse):
    loads: dict[tuple, float] = {}
    for a in assignments:
        loc = warehouse.locations[a.location_id]
        key = (loc.rack_id, loc.bay, loc.shelf_level)
        loads[key] = loads.get(key, 0.0) + a.assigned_quantity * 1.0
    return loads


# --------------------------------------------------------------------------- A. radius
def test_default_radius_is_the_documented_value():
    assert DEFAULT_SEPARATION_RADIUS_M == 10.0
    assert Config().separation_radius_m == 10.0
    assert Config.from_dict({}).separation_radius_m == 10.0


def test_benchmark_config_carries_the_radius():
    cfg = Config.from_json(PROJECT_ROOT / "configs" / "benchmark.json")
    raw = json.loads((PROJECT_ROOT / "configs" / "benchmark.json").read_text(encoding="utf-8"))
    assert "separation_radius_m" in raw, "the radius must be visible in configuration, not implicit"
    assert raw["separation_radius_m"] == cfg.separation_radius_m == 10.0
    assert isinstance(cfg.separation_radius_m, float)


@pytest.mark.parametrize("bad", [-1, -0.5, "-10", True, None, float("nan"), float("inf")])
def test_radius_rejects_non_values(bad):
    with pytest.raises(ValueError):
        coerce_separation_radius_m(bad)


def test_radius_accepts_zero_and_positive():
    assert coerce_separation_radius_m(0) == 0.0
    assert coerce_separation_radius_m(2) == 2.0
    assert coerce_separation_radius_m(3.5) == 3.5


def test_radius_round_trips_through_config_dict():
    cfg = Config.from_dict({"separation_radius_m": 4.25})
    assert cfg.separation_radius_m == 4.25
    assert cfg.to_dict()["separation_radius_m"] == 4.25
    assert Config.from_dict(cfg.to_dict()).separation_radius_m == 4.25


def test_optimizer_refuses_to_disagree_with_its_validator():
    wh = Warehouse("WH", "w", "1", locations={"L1": make_loc("L1")})
    skus = {"S1": make_sku("S1")}
    validator = Validator(skus, wh, [], inventory={"S1": 1}, separation_radius_m=10.0)
    with pytest.raises(ValueError, match="separation_radius_m mismatch"):
        SlottingOptimizer(
            warehouse=wh, skus=skus, abc_classes={}, validator=validator,
            inventory={"S1": 1}, separation_radius_m=2.0,
        )


# --------------------------------------------------------------------------- B. beam
def test_split_quantity_is_bounded_by_the_beam_residual():
    loc = make_loc("L1", bin_cap=100.0, beam_cap=180.0)
    sku = make_sku("S1", weight=30.0)
    # Bin could take 3 units (90 kg) but the beam only has 45 kg left.
    assert _split_quantity(sku, loc, 10, residual_bin_weight=100.0, residual_volume=108_000.0,
                           residual_beam_weight=45.0, residual_shelf_weight=1000.0,
                           residual_rack_weight=1000.0) == 1
    assert _split_quantity(sku, loc, 10, residual_bin_weight=100.0, residual_volume=108_000.0,
                           residual_beam_weight=90.0, residual_shelf_weight=1000.0,
                           residual_rack_weight=1000.0) == 3
    # No beam residual left at all -> nothing may be placed.
    assert _split_quantity(sku, loc, 10, residual_bin_weight=100.0, residual_volume=108_000.0,
                           residual_beam_weight=0.0, residual_shelf_weight=1000.0,
                           residual_rack_weight=1000.0) == 0


def test_units_affordable_never_accepts_a_fraction_of_a_unit_over():
    for residual, per_unit in [(180.0, 20.283), (0.3, 0.1), (100.0, 25.0), (7.5, 2.5)]:
        n = _units_affordable(residual, per_unit)
        assert n * per_unit <= residual + 1e-9, (residual, per_unit, n)
        # and it is the largest such n
        assert (n + 1) * per_unit > residual or n >= 10**9


def test_greedy_never_exceeds_a_beam_when_two_bins_share_it():
    """The defect: two 100 kg bins on a 180 kg beam, a 30 kg SKU spanning both."""
    wh = Warehouse("WH", "w", "1")
    # Level and rack caps are set out of the way so the beam is the only scope that can bind.
    for loc_id, bay, x in (("L1", 0, 0.0), ("L2", 0, 1.0), ("L3", 1, 2.0), ("L4", 1, 3.0)):
        wh.locations[loc_id] = make_loc(
            loc_id, bay=bay, x=x, y=0.0, bin_cap=100.0, beam_cap=180.0,
            level_cap=1000.0, rack_cap=1000.0,
        )
    skus = {"S1": make_sku("S1", weight=30.0)}
    opt = build_optimizer(wh, skus, {"S1": 10})

    assignments = opt.greedy_starter()

    per_beam: dict[tuple, float] = {}
    for a in assignments:
        loc = wh.locations[a.location_id]
        key = (loc.rack_id, loc.bay, loc.shelf_level)
        per_beam[key] = per_beam.get(key, 0.0) + a.assigned_quantity * 30.0
    assert per_beam, "the starter placed nothing"
    assert all(load <= 180.0 + 1e-9 for load in per_beam.values()), per_beam
    assert sum(a.assigned_quantity for a in assignments) == 10
    # 10 units x 30 kg = 300 kg cannot fit on one 180 kg beam; both beams must be used.
    assert len(per_beam) == 2, per_beam

    res = opt.validator.validate(assignments)
    assert not [v for v in res.violations if v.rule_id == "SL-02"], [v.reason for v in res.violations]


def test_greedy_survives_bins_with_no_declared_structural_limits():
    """A layout with no beam/level/rack caps must place normally, not crash the invariant check."""
    wh = Warehouse("WH", "w", "1")
    for i in range(3):
        wh.locations[f"L{i}"] = make_loc(
            f"L{i}", rack=f"R{i}", x=float(i), y=float(i * 5),
            beam_cap=None, level_cap=None, rack_cap=None,
        )
    skus = {"S1": make_sku("S1", weight=5.0)}
    opt = build_optimizer(wh, skus, {"S1": 12})

    assignments = opt.greedy_starter()

    assert sum(a.assigned_quantity for a in assignments) == 12
    assert opt._unplaced == []
    res = opt.validator.validate(assignments)
    assert not [v for v in res.violations if v.rule_id in {"SL-01", "SL-02", "RK-01"}]


def test_greedy_respects_every_structural_scope_on_a_random_fixture():
    rng = random.Random(11)
    wh = Warehouse("WH", "w", "1")
    for rack in range(4):
        for bay in range(2):
            for level in range(2):
                for b in range(2):
                    loc_id = f"L{rack}{bay}{level}{b}"
                    wh.locations[loc_id] = make_loc(
                        loc_id, rack=f"R{rack}", bay=bay, level=level,
                        x=float(b), y=float(rack * 40 + bay * 2 + level), z=level * 0.5,
                        bin_cap=100.0, beam_cap=180.0, level_cap=288.0, rack_cap=306.0,
                    )
    skus, inventory = {}, {}
    for i in range(24):
        sid = f"S{i:02d}"
        skus[sid] = make_sku(sid, category=f"CAT{i % 3:03d}", weight=rng.uniform(1.0, 40.0))
        inventory[sid] = rng.randint(1, 12)
    opt = build_optimizer(wh, skus, inventory)
    assignments = opt.greedy_starter()

    loads_by_scope = {"beam": {}, "level": {}, "rack": {}, "bin": {}}
    for a in assignments:
        loc = wh.locations[a.location_id]
        w = a.assigned_quantity * skus[a.sku_id].unit_weight_kg
        for scope, key in (
            ("beam", (loc.rack_id, loc.bay, loc.shelf_level)),
            ("level", (loc.rack_id, loc.shelf_level)),
            ("rack", loc.rack_id),
            ("bin", loc.location_id),
        ):
            loads_by_scope[scope][key] = loads_by_scope[scope].get(key, 0.0) + w

    for key, load in loads_by_scope["beam"].items():
        assert load <= 180.0 + 1e-6, f"beam {key} overloaded: {load}"
    for key, load in loads_by_scope["level"].items():
        assert load <= 288.0 + 1e-6, f"level {key} overloaded: {load}"
    for key, load in loads_by_scope["rack"].items():
        assert load <= 306.0 + 1e-6, f"rack {key} overloaded: {load}"
    for key, load in loads_by_scope["bin"].items():
        assert load <= 100.0 + 1e-6, f"bin {key} overloaded: {load}"

    res = opt.validator.validate(assignments)
    structural = [v for v in res.violations if v.rule_id in {"LD-01", "SL-01", "SL-02", "RK-01"}]
    assert not structural, [v.reason for v in structural]


# --------------------------------------------------------------------------- C. CAT-01
def test_separation_grid_rejects_a_forbidden_neighbour():
    wh = Warehouse("WH", "w", "1")
    grid = SeparationGrid(10.0, forbidden_pairs_from_rules(
        [CompatibilityRule("R1", "C1", "C2", allowed=False)]
    ))
    here = make_loc("L1", x=0.0, y=0.0, z=0.0)
    near = make_loc("L2", x=9.0, y=0.0, z=0.0)
    far = make_loc("L3", x=10.5, y=0.0, z=0.0)

    assert grid.allows(here, "C1") is True
    grid.add(here, "C1")

    assert grid.allows(near, "C2") is False, "9 m < 10 m radius must be refused"
    assert grid.allows(far, "C2") is True, "10.5 m >= 10 m radius must be allowed"
    assert grid.allows(near, "C1") is True, "a category is never separated from itself"
    assert grid.allows(near, "C3") is True, "unrelated categories are not separated"


def test_rejected_candidate_does_not_mutate_the_grid():
    grid = SeparationGrid(10.0, forbidden_pairs_from_rules(
        [CompatibilityRule("R1", "C1", "C2", allowed=False)]
    ))
    here = make_loc("L1", x=0.0, y=0.0, z=0.0)
    grid.add(here, "C1")
    before = (grid.n_placed_bins, grid.n_cells, dict(grid.diagnostics()))

    assert grid.allows(make_loc("L2", x=1.0), "C2") is False
    assert grid.allows(make_loc("L3", x=2.0), "C2") is False

    after = (grid.n_placed_bins, grid.n_cells, dict(grid.diagnostics()))
    assert after[0] == before[0] and after[1] == before[1]
    assert after[2]["bins_indexed"] == before[2]["bins_indexed"]
    assert after[2]["rejections"] == before[2]["rejections"] + 2


def test_radius_zero_disables_the_grid():
    grid = SeparationGrid(0.0, forbidden_pairs_from_rules(
        [CompatibilityRule("R1", "C1", "C2", allowed=False)]
    ))
    here = make_loc("L1")
    grid.add(here, "C1")
    assert grid.allows(make_loc("L2", x=0.0), "C2") is True


def test_greedy_places_around_the_radius():
    """Two forbidden categories competing for the same near bins.

    C1 takes the near bin; every near candidate for C2 is inside the 10 m radius, so C2 must
    land in the far bin. The validator then confirms the separation holds.
    """
    wh = Warehouse("WH", "w", "1")
    wh.locations["B1"] = make_loc("B1", x=0.0, y=1.0)
    wh.locations["B2"] = make_loc("B2", x=0.0, y=5.0)
    wh.locations["B3"] = make_loc("B3", x=0.0, y=100.0)
    rules = [CompatibilityRule("R1", "C1", "C2", allowed=False)]
    skus = {"S1": make_sku("S1", category="C1"), "S2": make_sku("S2", category="C2")}
    opt = build_optimizer(wh, skus, {"S1": 1, "S2": 1}, rules, radius=10.0,
                          demand={"S1": 100.0, "S2": 1.0})

    assignments = opt.greedy_starter()

    placed = {a.sku_id: a.location_id for a in assignments}
    near_bin = placed["S1"]
    assert near_bin in {"B1", "B2"}, placed
    assert placed["S2"] == "B3", f"S2 must clear the 10 m radius, got {placed}"

    res = opt.validator.validate(assignments)
    assert not [v for v in res.violations if v.rule_id == "CAT-01"], [v.reason for v in res.violations]


def test_greedy_reports_separation_as_the_binding_reason():
    """The only free bins left are inside the radius: CAT-01 is what stops the second SKU."""
    wh = Warehouse("WH", "w", "1")
    wh.locations["B1"] = make_loc("B1", x=0.0, y=1.0)   # taken by the C1 SKU
    wh.locations["B2"] = make_loc("B2", x=0.0, y=5.0)   # free, 4 m from B1
    wh.locations["B3"] = make_loc("B3", x=0.0, y=9.0)   # free, 8 m from B1
    rules = [CompatibilityRule("R1", "C1", "C2", allowed=False)]
    skus = {"S1": make_sku("S1", category="C1"), "S2": make_sku("S2", category="C2")}
    opt = build_optimizer(wh, skus, {"S1": 1, "S2": 1}, rules, radius=10.0,
                          demand={"S1": 100.0, "S2": 1.0})

    opt.greedy_starter()

    assert len(opt._unplaced) == 1
    unplaced = opt._unplaced[0]
    assert unplaced.sku_id == "S2"
    assert unplaced.binding_reason == BINDING_SEPARATION
    assert unplaced.units_unplaced == 1
    assert "CAT-01" in unplaced.detail


# --------------------------------------------------------------------------- D. diagnostics
def test_capacity_is_reported_when_stock_exceeds_the_warehouse():
    wh = Warehouse("WH", "w", "1")
    wh.locations["L1"] = make_loc("L1", bin_cap=50.0, beam_cap=90.0, volume=1_000.0)
    skus = {"S1": make_sku("S1", weight=10.0)}
    opt = build_optimizer(wh, skus, {"S1": 100})

    assignments = opt.greedy_starter()

    placed = sum(a.assigned_quantity for a in assignments)
    assert placed < 100
    assert len(opt._unplaced) == 1
    assert opt._unplaced[0].binding_reason == BINDING_CAPACITY
    assert opt._unplaced[0].units_unplaced == 100 - placed


def test_fit_is_reported_when_no_bin_is_large_enough():
    wh = Warehouse("WH", "w", "1")
    wh.locations["L1"] = make_loc("L1")
    skus = {"S1": make_sku("S1")}
    skus["S1"].width_cm = 10_000.0
    opt = build_optimizer(wh, skus, {"S1": 1})

    assignments = opt.greedy_starter()

    assert assignments == []
    assert opt._unplaced[0].binding_reason == "fit"
    assert "no bin is at least" in opt._unplaced[0].detail


def test_hazard_is_reported_when_no_zone_accepts_the_class():
    wh = Warehouse("WH", "w", "1")
    wh.locations["L1"] = make_loc("L1", allowed_hazard=("NONE",))
    skus = {"S1": make_sku("S1", hazard=HazardClass.FLAMMABLE)}
    opt = build_optimizer(wh, skus, {"S1": 1})

    opt.greedy_starter()

    assert opt._unplaced[0].binding_reason == "hazard"
    assert "flammable" in opt._unplaced[0].detail


def test_every_sku_is_either_placed_or_reported():
    """No silent drops: placed + unplaced units always equal the inventory."""
    rng = random.Random(3)
    wh = Warehouse("WH", "w", "1")
    for i in range(6):
        wh.locations[f"L{i}"] = make_loc(
            f"L{i}", rack=f"R{i // 2}", bay=i % 2, level=0, x=float(i),
            y=float(i * 20), bin_cap=40.0, beam_cap=70.0, level_cap=200.0, rack_cap=200.0,
        )
    skus, inventory = {}, {}
    for i in range(10):
        sid = f"S{i:02d}"
        skus[sid] = make_sku(sid, category=f"CAT{i % 4:03d}", weight=rng.uniform(5.0, 30.0))
        inventory[sid] = rng.randint(1, 10)
    opt = build_optimizer(wh, skus, inventory)

    assignments = opt.greedy_starter()

    placed = sum(a.assigned_quantity for a in assignments)
    unplaced = sum(u.units_unplaced for u in opt._unplaced)
    assert placed + unplaced == sum(inventory.values())
    for u in opt._unplaced:
        assert u.binding_reason in {"fit", "hazard", "handling", "capacity", "separation"}
        assert u.units_unplaced > 0 and u.detail


# --------------------------------------------------------------------------- determinism
def test_starter_is_deterministic():
    wh = Warehouse("WH", "w", "1")
    for i in range(8):
        wh.locations[f"L{i}"] = make_loc(f"L{i}", rack=f"R{i // 4}", bay=i % 2, x=float(i),
                                         y=float(i * 15))
    skus, inventory = {}, {}
    for i in range(12):
        sid = f"S{i:02d}"
        skus[sid] = make_sku(sid, category=f"CAT{i % 3:03d}", weight=float(i + 1))
        inventory[sid] = i + 1

    runs = []
    for _ in range(2):
        opt = build_optimizer(wh, skus, inventory)
        runs.append([(a.sku_id, a.location_id, a.assigned_quantity) for a in opt.greedy_starter()])
    assert runs[0] == runs[1]
