"""Phase-4 validator tests: adversarial invalid assignments must be rejected; a clean
assignment must pass. Also verifies the canonical baseline's verdict is reported correctly
and the audit exporter runs."""

import math
from collections import defaultdict

import pandas as pd
import pytest

from src.models.config import Config
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
from src.simulation.pipeline import _layout_feasibility
from src.validation import audit
from src.validation.loader import load_shipping
from src.validation.validator import Validator, validate_assignment

PROJECT_ROOT = pytest.importorskip("pathlib").Path(__file__).resolve().parent.parent


def _independent_cat01_count(warehouse, skus, assignments, rules, radius_m) -> int:
    """Count forbidden category pairs closer than ``radius_m`` without using the validator.

    The gate has to be independently checkable: this walks the category pairs the
    compatibility matrix forbids and measures every stored bin pair with ``math.dist``.
    """
    forbidden = {
        frozenset((r.category_a, r.category_b))
        for r in rules
        if not r.allowed and r.category_a != r.category_b
    }
    by_category: dict[str, list] = defaultdict(list)
    for a in assignments:
        sku = skus.get(a.sku_id)
        loc = warehouse.locations.get(a.location_id)
        if sku is not None and loc is not None:
            by_category[sku.category_id].append(loc)

    count = 0
    for pair in forbidden:
        categories = sorted(pair)
        if len(categories) < 2:
            continue
        seen = set()
        for loc_a in by_category.get(categories[0], []):
            for loc_b in by_category.get(categories[1], []):
                key = tuple(sorted((loc_a.location_id, loc_b.location_id)))
                if key in seen:
                    continue
                seen.add(key)
                if math.dist((loc_a.x, loc_a.y, loc_a.z), (loc_b.x, loc_b.y, loc_b.z)) + 1e-9 < radius_m:
                    count += 1
    return count


def _fixtures():
    """Return (warehouse, skus, rules) with a few well-known locations/SKUs."""
    loc_small = Location(
        location_id="L1", zone_id="Z1", aisle_id="A1", rack_id="R1", bay=0, shelf_level=2,
        x=1.0, y=1.0, z=1.0, width_cm=20, height_cm=10, depth_cm=20,
        max_weight_kg=10.0, usable_volume_cm3=4000, ergonomic_zone=AccessibilityZone.GOLDEN,
        allowed_handling=("standard", "fragile", "heavy", "temperature_controlled"),
        distance_to_dispatch_m=1.0,
    )
    wh = Warehouse("WH1", "wh", "1.0", locations={"L1": loc_small}, dispatch_point=(0, 0, 0))
    small = SKU(
        "S1", "small", "C1", width_cm=5, height_cm=5, depth_cm=5,
        unit_weight_kg=1.0, handling_type=HandlingType.STANDARD, hazard_class=HazardClass.NONE,
    )
    big = SKU(
        "S2", "big", "C1", width_cm=30, height_cm=30, depth_cm=30,
        unit_weight_kg=5.0, handling_type=HandlingType.STANDARD, hazard_class=HazardClass.NONE,
    )
    heavy = SKU(
        "S3", "heavy", "C2", width_cm=5, height_cm=5, depth_cm=5,
        unit_weight_kg=8.0, handling_type=HandlingType.HEAVY, hazard_class=HazardClass.NONE,
    )
    flam = SKU(
        "S4", "flam", "C3", width_cm=5, height_cm=5, depth_cm=5,
        unit_weight_kg=1.0, handling_type=HandlingType.STANDARD, hazard_class=HazardClass.FLAMMABLE,
    )
    skus = {s.sku_id: s for s in (small, big, heavy, flam)}
    # L1 hazard allowed = NONE only
    loc_small.allowed_hazard = ("NONE",)
    rules = [
        CompatibilityRule("CR1", "C1", "C3", False, "high", "incompatible")
    ]
    return wh, skus, rules


def test_dimension_overflow_rejected():
    wh, skus, rules = _fixtures()
    asg = [StorageAssignment("S2", "L1", 1, AssignmentType.OPTIMIZED)]  # big SKU in small bin
    res = validate_assignment(asg, skus, wh, rules)
    assert any(v.rule_id == "SP-01" for v in res.violations)


def test_clean_assignment_passes():
    wh, skus, rules = _fixtures()
    asg = [StorageAssignment("S1", "L1", 1, AssignmentType.OPTIMIZED)]
    res = validate_assignment(asg, skus, wh, rules, inventory={"S1": 1})
    assert res.is_feasible, res.violations


def test_location_weight_overflow_rejected():
    wh, skus, rules = _fixtures()
    asg = [StorageAssignment("S3", "L1", 2, AssignmentType.OPTIMIZED)]  # 2x8=16kg > 10kg
    # dims fine (5<=20) but weight overflow
    res = validate_assignment(asg, skus, wh, rules)
    assert any(v.rule_id == "LD-01" for v in res.violations)


def test_hazard_rejected():
    wh, skus, rules = _fixtures()
    asg = [StorageAssignment("S4", "L1", 1, AssignmentType.OPTIMIZED)]  # flammable at NONE-only loc
    res = validate_assignment(asg, skus, wh, rules)
    assert any(v.rule_id == "HZ-01" for v in res.violations)


def test_co_storage_conflict_rejected():
    wh, skus, rules = _fixtures()
    # C1 (S1) and C3 (S4) incompatible; same location but also single-SKU... use mixed policy:
    asg = [StorageAssignment("S1", "L1", 1, AssignmentType.OPTIMIZED),
           StorageAssignment("S4", "L1", 1, AssignmentType.OPTIMIZED)]
    res = validate_assignment(asg, skus, wh, rules)
    assert any(v.rule_id == "CP-01" for v in res.violations)


def test_single_sku_policy_rejected():
    wh, skus, rules = _fixtures()
    # two different compatible SKUs in one location => single-SKU policy violation
    s5 = SKU("S5", "other", "C1", 5, 5, 5, 1.0, HandlingType.STANDARD, HazardClass.NONE)
    skus["S5"] = s5
    asg = [StorageAssignment("S1", "L1", 1, AssignmentType.OPTIMIZED),
           StorageAssignment("S5", "L1", 1, AssignmentType.OPTIMIZED)]
    res = validate_assignment(asg, skus, wh, rules)
    assert any(v.rule_id == "AS-01" for v in res.violations)


def test_referential_integrity():
    wh, skus, rules = _fixtures()
    asg = [StorageAssignment("S1", "DOESNOTEXIST", 1, AssignmentType.OPTIMIZED)]
    res = validate_assignment(asg, skus, wh, rules)
    assert any(v.rule_id == "REF-02" for v in res.violations)


def test_baseline_feasibility_is_reported_correctly_on_benchmark():
    """The canonical baseline's verdict must be computed and REPORTED, not assumed.

    Phase 1 established that the baseline is infeasible at the configured 10 m radius
    (1,071 CAT-01 violations), so "the baseline passes" is not a contract — it is a claim
    that happens to be false. What this test pins instead:

      * the validator's CAT-01 count equals an independent, pair-by-pair distance count
        computed here from the same geometry and rule matrix;
      * a feasible verdict means zero violations, and an infeasible verdict means violations
        are reported (with rule ids and reasons) and the evaluation gate marks the layout
        INFEASIBLE — i.e. it cannot be scored.
    """
    processed = PROJECT_ROOT.parent / "dataset" / "processed"
    if not processed.exists():
        pytest.skip("benchmark data not generated")
    wh, skus, comp, assignments, inventory = load_shipping(processed)
    radius = Config.from_json(PROJECT_ROOT / "configs" / "benchmark.json").separation_radius_m

    res = validate_assignment(
        assignments, skus, wh, comp, inventory, separation_radius_m=radius
    )

    expected_cat01 = _independent_cat01_count(wh, skus, assignments, comp, radius)
    reported = [v for v in res.violations if v.rule_id == "CAT-01"]
    assert len(reported) == expected_cat01, (
        f"validator reported {len(reported)} CAT-01 violations, "
        f"independent pair count is {expected_cat01} at radius {radius} m"
    )
    assert res.checks_run > 0, "the validator must actually have run"
    assert all(v.rule_id and v.reason for v in res.violations)

    if res.is_feasible:
        assert res.violations == []
    else:
        assert res.hard_violations, "an infeasible layout must report at least one hard violation"
        gate = _layout_feasibility(res)
        assert gate["feasibility_status"] == "INFEASIBLE"
        assert gate["is_feasible"] is False
        assert gate["n_violations"] == len(res.violations)
        assert gate["violations_by_rule"].get("CAT-01", 0) == len(reported)


def test_audit_export_writes_csv(tmp_path):
    wh, skus, rules = _fixtures()
    asg = [StorageAssignment("S2", "L1", 1, AssignmentType.OPTIMIZED)]  # triggers SP-01
    res = validate_assignment(asg, skus, wh, rules)
    p = tmp_path / "constraint_audit.csv"
    audit.write_constraint_audit(asg, res, p)
    df = pd.read_csv(p)
    assert "rule_id" in df.columns
    assert len(df) >= 1


def test_audit_export_records_pass_for_clean_layout(tmp_path):
    wh, skus, rules = _fixtures()
    asg = [StorageAssignment("S1", "L1", 1, AssignmentType.OPTIMIZED)]
    res = validate_assignment(asg, skus, wh, rules, inventory={"S1": 1})
    p = tmp_path / "constraint_audit.csv"
    audit.write_constraint_audit(asg, res, p)
    df = pd.read_csv(p)
    assert len(df) == 1
    assert df.iloc[0]["rule_id"] == "PASS"
    assert str(df.iloc[0]["passed"]).lower() == "true"


def test_inventory_conservation_enforced():
    wh, skus, rules = _fixtures()
    under = [StorageAssignment("S1", "L1", 1, AssignmentType.OPTIMIZED)]
    res = validate_assignment(under, skus, wh, rules, inventory={"S1": 2})
    assert any(v.rule_id == "INV-02" for v in res.violations)

    over = [StorageAssignment("S1", "L1", 3, AssignmentType.OPTIMIZED)]
    res = validate_assignment(over, skus, wh, rules, inventory={"S1": 2})
    assert any(v.rule_id == "INV-01" for v in res.violations)


def test_multi_bin_placement_is_allowed():
    wh, skus, rules = _fixtures()
    second = Location(
        location_id="L2", zone_id="Z1", aisle_id="A2", rack_id="R2", bay=0, shelf_level=2,
        x=2.0, y=1.0, z=1.0, width_cm=20, height_cm=10, depth_cm=20,
        max_weight_kg=10.0, usable_volume_cm3=4000, ergonomic_zone=AccessibilityZone.GOLDEN,
        allowed_handling=("standard", "fragile", "heavy", "temperature_controlled"),
        allowed_hazard=("NONE",), distance_to_dispatch_m=2.0,
    )
    wh.locations["L2"] = second
    asg = [
        StorageAssignment("S1", "L1", 1, AssignmentType.OPTIMIZED),
        StorageAssignment("S1", "L2", 1, AssignmentType.OPTIMIZED),
    ]
    res = validate_assignment(asg, skus, wh, rules, inventory={"S1": 2})
    assert res.is_feasible, res.violations


def test_shelf_structural_limit_enforced():
    wh, skus, rules = _fixtures()
    for lid, x in (("L2", 2.0), ("L3", 3.0)):
        wh.locations[lid] = Location(
            location_id=lid, zone_id="Z1", aisle_id="A1", rack_id="R1", bay=0, shelf_level=2,
            x=x, y=1.0, z=1.0, width_cm=20, height_cm=10, depth_cm=20,
            max_weight_kg=10.0, usable_volume_cm3=4000,
            shelf_max_weight_kg=1.0, rack_max_weight_kg=100.0,
            ergonomic_zone=AccessibilityZone.GOLDEN,
            allowed_handling=("standard", "fragile", "heavy", "temperature_controlled"),
            allowed_hazard=("NONE",), distance_to_dispatch_m=2.0,
        )
    asg = [
        StorageAssignment("S1", "L2", 1, AssignmentType.OPTIMIZED),
        StorageAssignment("S1", "L3", 1, AssignmentType.OPTIMIZED),
    ]
    res = validate_assignment(asg, skus, wh, rules, inventory={"S1": 2})
    assert any(v.rule_id == "SL-01" for v in res.violations)