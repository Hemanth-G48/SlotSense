"""Tests for the two rules that make "feasible" and "safe" mean something.

Covers ARCHITECTURE.md §8.1:
  * four structural scopes, each against its own limit (LD-01 / SL-02 / SL-01 / RK-01)
  * CAT-01 — forbidden category pairs separated by a 3-D radius

Runs without pandas: `python -m unittest tests.test_structural_and_separation -v`
"""

from __future__ import annotations

import unittest

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
from src.validation.validator import Validator

# Limits produced by generate.apply_structural_limits for bin capacity 100 kg,
# two bins per beam, two bays per level:
#   beam  = 100 * 2 * 0.90 = 180
#   level = 180 * 2 * 0.80 = 288
#   rack  = 180 * 2 * 0.85 = 306
BEAM_LIMIT = 180.0
LEVEL_LIMIT = 288.0
RACK_LIMIT = 306.0


def make_warehouse(rack_limit: float = RACK_LIMIT) -> Warehouse:
    wh = Warehouse(warehouse_id="WH1", warehouse_name="test", layout_version="1")
    loc_id = 0
    for bay in (0, 1):
        for level in (0,):
            for b in range(2):
                loc_id += 1
                wh.locations[f"L{loc_id:02d}"] = Location(
                    location_id=f"L{loc_id:02d}",
                    zone_id="Z1",
                    aisle_id="A1",
                    rack_id="R1",
                    bay=bay,
                    shelf_level=level,
                    x=float(bay * 2 + b),  # 1 m pitch, used by CAT-01
                    y=0.0,
                    z=level * 0.5,
                    width_cm=60.0,
                    height_cm=40.0,
                    depth_cm=45.0,
                    max_weight_kg=100.0,
                    usable_volume_cm3=108_000.0,
                    beam_max_weight_kg=BEAM_LIMIT,
                    level_max_weight_kg=LEVEL_LIMIT,
                    shelf_max_weight_kg=LEVEL_LIMIT,
                    rack_max_weight_kg=rack_limit,
                    allowed_handling=("standard", "fragile", "heavy"),
                    allowed_hazard=("NONE", "flammable"),
                    ergonomic_zone=AccessibilityZone.GOLDEN,
                )
    return wh


def make_sku(sku_id: str, category: str, unit_weight: float = 1.0,
             hazard: HazardClass = HazardClass.NONE) -> SKU:
    return SKU(
        sku_id=sku_id,
        product_name=sku_id,
        category_id=category,
        width_cm=10.0,
        height_cm=10.0,
        depth_cm=10.0,
        unit_weight_kg=unit_weight,
        handling_type=HandlingType.STANDARD,
        hazard_class=hazard,
    )


def assign(sku: str, loc: str, qty: int) -> StorageAssignment:
    return StorageAssignment(sku, loc, qty, AssignmentType.OPTIMIZED)


def run(wh: Warehouse, skus: dict, assignments: list, rules: list | None = None,
        inventory: dict | None = None, radius: float = 10.0):
    v = Validator(skus, wh, rules, inventory=inventory, separation_radius_m=radius)
    result = v.validate(assignments)
    return result, {c.rule_id: c for c in result.checks}


class StructuralScopes(unittest.TestCase):
    """Each aggregate is compared against its own limit, and each can fail alone."""

    def test_bin_limit_fails(self):
        wh = make_warehouse()
        skus = {"S1": make_sku("S1", "CAT001")}
        res, checks = run(wh, skus, [assign("S1", "L01", 101)])  # 101 kg > 100 kg bin limit
        self.assertFalse(checks["LD-01"].passed)

    def test_beam_overload_while_level_legal(self):
        """The case the PS names: one beam overloaded, the level average fine."""
        wh = make_warehouse()
        skus = {"S1": make_sku("S1", "CAT001"), "S2": make_sku("S2", "CAT001")}
        # Bay 0 gets 95 + 95 = 190 kg on one beam (limit 180); level total 190 < 288.
        res, checks = run(wh, skus, [assign("S1", "L01", 95), assign("S2", "L02", 95)])
        self.assertFalse(checks["SL-02"].passed, "beam should be overloaded")
        self.assertTrue(checks["SL-01"].passed, "level average is still legal")
        self.assertIn("SL-02", {v.rule_id for v in res.violations})

    def test_level_overload_while_beams_legal(self):
        wh = make_warehouse()
        skus = {"S1": make_sku("S1", "CAT001"), "S2": make_sku("S2", "CAT001")}
        # 150 kg on each bay = 150 per beam (< 180), 300 total (> 288 level).
        res, checks = run(wh, skus, [assign("S1", "L01", 150), assign("S1", "L03", 150)])
        self.assertTrue(checks["SL-02"].passed, "each beam is legal")
        self.assertFalse(checks["SL-01"].passed, "level total exceeds its limit")
        self.assertTrue(checks["RK-01"].passed, "rack total is still under its limit")

    def test_rack_limit_is_its_own_field(self):
        """A derated rack binds while every beam and the level are legal."""
        wh = make_warehouse(rack_limit=250.0)
        skus = {"S1": make_sku("S1", "CAT001"), "S2": make_sku("S2", "CAT001")}
        res, checks = run(wh, skus, [assign("S1", "L01", 130), assign("S1", "L03", 130)])
        self.assertTrue(checks["SL-02"].passed)
        self.assertTrue(checks["SL-01"].passed)
        self.assertFalse(checks["RK-01"].passed, "rack limit 250 < load 260")


class CategorySeparation(unittest.TestCase):
    RULES = [CompatibilityRule("r1", "CAT001", "CAT010", allowed=False)]

    def test_forbidden_pair_too_close_fails(self):
        wh = make_warehouse()
        skus = {"S1": make_sku("S1", "CAT001"), "X": make_sku("X", "CAT010")}
        # L01 at x=0, L02 at x=1 -> 1 m apart, below the 10 m radius.
        res, checks = run(wh, skus, [assign("S1", "L01", 1), assign("X", "L02", 1)],
                          rules=self.RULES)
        self.assertFalse(checks["CAT-01"].passed)
        self.assertAlmostEqual(float(checks["CAT-01"].observed), 1.0, places=3)

    def test_forbidden_pair_far_enough_passes(self):
        wh = make_warehouse()
        # Widen the fixture: move L02 20 m away.
        wh.locations["L02"].x = 20.0
        skus = {"S1": make_sku("S1", "CAT001"), "X": make_sku("X", "CAT010")}
        res, checks = run(wh, skus, [assign("S1", "L01", 1), assign("X", "L02", 1)],
                          rules=self.RULES)
        self.assertNotIn("CAT-01", {v.rule_id for v in res.violations})

    def test_allowed_pair_close_is_fine(self):
        wh = make_warehouse()
        skus = {"S1": make_sku("S1", "CAT001"), "Y": make_sku("Y", "CAT002")}
        res, checks = run(wh, skus, [assign("S1", "L01", 1), assign("Y", "L02", 1)],
                          rules=self.RULES)
        # PCAT002 is not a forbidden partner, so no CAT-01 check is recorded at all.
        self.assertNotIn("CAT-01", checks)

    def test_radius_is_configurable(self):
        wh = make_warehouse()
        # L01 x=0, L02 x=1 -> 1 m apart. With R=2 it must fail, with R=0.5 pass.
        skus = {"S1": make_sku("S1", "CAT001"), "X": make_sku("X", "CAT010")}
        tight, checks_tight = run(wh, skus, [assign("S1", "L01", 1), assign("X", "L02", 1)],
                                  rules=self.RULES, radius=2.0)
        self.assertFalse(checks_tight["CAT-01"].passed)
        loose, checks_loose = run(wh, skus, [assign("S1", "L01", 1), assign("X", "L02", 1)],
                                  rules=self.RULES, radius=0.5)
        self.assertNotIn("CAT-01", {v.rule_id for v in loose.violations})


if __name__ == "__main__":
    unittest.main(verbosity=2)
