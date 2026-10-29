"""Hand-calculated tests for the Phase 3 metric layer (travel + replenishment)."""

from __future__ import annotations

import pandas as pd
import pytest

from src.experiments.replenishment import lot_size, replenishment_metrics, replenishment_term
from src.experiments.travel import (
    ALL_BINS,
    QUANTITY_AWARE,
    REASON_MISSING_DISTANCE,
    REASON_NO_ASSIGNMENT,
    line_travel,
    line_travel_table,
)
from src.models.entities import AssignmentType, StorageAssignment
from src.optimization.objective import Objective
from src.validation.loader import (
    load_assignments,
    load_compatibility_rules,
    load_inventory,
    load_skus,
    load_warehouse_from_locations,
)
from src.validation.validator import Validator
from tests.phase2_fixtures import write_tiny_dataset


def items(rows):
    return pd.DataFrame(rows, columns=["order_id", "sku_id", "quantity"])


def assigned(rows):
    return pd.DataFrame(rows, columns=["sku_id", "location_id", "assigned_quantity"])


# ---------------------------------------------------------------- travel

def test_single_sku_single_line_uses_its_one_bin():
    res = line_travel(items([("O1", "S1", 1)]), {"S1": [("L1", 10, 10.0)]}, QUANTITY_AWARE)
    assert res.numerator_m == pytest.approx(10.0)
    assert res.denominator_lines == 1
    assert res.mean_per_line_m == pytest.approx(10.0)


def test_demand_weighting_is_line_count_not_equal_sku_weight():
    """S1 appears 3 times, S2 once: 3*10 + 1*30 = 60, mean 15."""
    bins = {"S1": [("L1", 99, 10.0)], "S2": [("L2", 99, 30.0)]}
    work = items([("O1", "S1", 1), ("O2", "S1", 1), ("O3", "S1", 1), ("O4", "S2", 1)])
    res = line_travel(work, bins, QUANTITY_AWARE)
    assert res.numerator_m == pytest.approx(60.0)
    assert res.denominator_lines == 4
    assert res.mean_per_line_m == pytest.approx(15.0)


def test_quantity_aware_stops_when_the_line_is_covered():
    """b1 holds 5 units at 10 m, b2 holds 10 at 50 m. A 3-unit line needs only b1."""
    bins = {"S1": [("L1", 5, 10.0), ("L2", 10, 50.0)]}
    res = line_travel(items([("O1", "S1", 3)]), bins, QUANTITY_AWARE)
    assert res.numerator_m == pytest.approx(10.0)
    assert res.lines[0].stops == ("L1",)


def test_quantity_aware_spills_to_the_next_bin():
    """A 12-unit line exceeds b1 (5) and must visit b2 as well: 10 + 50."""
    bins = {"S1": [("L1", 5, 10.0), ("L2", 10, 50.0)]}
    res = line_travel(items([("O1", "S1", 12)]), bins, QUANTITY_AWARE)
    assert res.numerator_m == pytest.approx(60.0)
    assert res.lines[0].stops == ("L1", "L2")


def test_all_bins_charges_every_bin_regardless_of_quantity():
    bins = {"S1": [("L1", 5, 10.0), ("L2", 10, 50.0)]}
    res = line_travel(items([("O1", "S1", 3)]), bins, ALL_BINS)
    assert res.numerator_m == pytest.approx(60.0)
    assert res.lines[0].n_stops == 2


def test_multiple_units_on_one_line_are_not_multiplied_twice():
    """The unit of account is the line; quantity only decides how many bins are visited."""
    bins = {"S1": [("L1", 100, 10.0)]}
    one = line_travel(items([("O1", "S1", 1)]), bins, QUANTITY_AWARE)
    many = line_travel(items([("O1", "S1", 50)]), bins, QUANTITY_AWARE)
    assert one.numerator_m == many.numerator_m == pytest.approx(10.0)


def test_missing_assignment_is_reported_not_dropped():
    bins = {"S1": [("L1", 10, 10.0)]}
    work = items([("O1", "S1", 1), ("O2", "GHOST", 1)])
    res = line_travel(work, bins, QUANTITY_AWARE)
    assert res.denominator_lines == 1
    assert res.unresolved == ("GHOST",)
    agg = res.aggregate()
    assert agg["lines_unresolved"] == 1
    assert agg["lines_total"] == 2
    assert agg["coverage_pct"] == pytest.approx(50.0)
    assert res.unresolved_lines[0].reason == REASON_NO_ASSIGNMENT


def test_missing_distance_is_unresolved_not_priced_at_zero():
    bins = {"S1": [("L1", 5, float("inf"))]}
    res = line_travel(items([("O1", "S1", 1)]), bins, QUANTITY_AWARE)
    assert res.denominator_lines == 0
    assert res.numerator_m == 0.0
    assert res.unresolved_lines[0].reason == REASON_MISSING_DISTANCE
    assert res.aggregate()["mean_per_line_m"] is None


def test_quantity_short_is_reported_when_stock_cannot_cover_the_line():
    bins = {"S1": [("L1", 2, 10.0)]}
    res = line_travel(items([("O1", "S1", 5)]), bins, QUANTITY_AWARE)
    assert res.lines[0].quantity_short == 3
    assert res.aggregate()["units_short"] == 3


def test_all_bins_also_reports_quantity_short():
    bins = {"S1": [("L1", 2, 10.0), ("L2", 1, 20.0)]}
    res = line_travel(items([("O1", "S1", 5)]), bins, ALL_BINS)
    assert res.lines[0].quantity_short == 2
    assert res.aggregate()["units_short"] == 2


def test_empty_workload_has_no_denominator():
    res = line_travel(items([]), {}, QUANTITY_AWARE)
    agg = res.aggregate()
    assert agg["denominator_lines"] == 0
    assert agg["mean_per_line_m"] is None
    assert agg["numerator_m"] == 0


def test_line_table_sums_to_the_aggregate():
    bins = {"S1": [("L1", 5, 10.0), ("L2", 10, 50.0)], "S2": [("L3", 9, 7.5)]}
    work = items([("O1", "S1", 12), ("O2", "S2", 1), ("O3", "S1", 2)])
    res = line_travel(work, bins, QUANTITY_AWARE)
    table = line_travel_table(res)
    assert table["distance_m"].sum() == pytest.approx(res.numerator_m)
    assert len(table) == res.denominator_lines


def test_unknown_rule_is_rejected():
    with pytest.raises(ValueError):
        line_travel(items([("O1", "S1", 1)]), {"S1": [("L1", 1, 1.0)]}, "nearest")


# ---------------------------------------------------------------- replenishment

def test_lot_size_covers_the_window_and_never_reaches_zero():
    assert lot_size(10.0, 14.0) == 140
    assert lot_size(0.0, 14.0) == 1
    assert lot_size(0.01, 14.0) == 1


def test_replenishment_trips_and_travel_are_hand_checkable():
    """1800 units/year -> 10/day -> lot 140.
    qty 100 -> 1 trip; qty 300 -> 3 trips. Travel = 2 * trips * 50 m."""
    assignments = assigned([("S1", "L1", 100), ("S2", "L2", 300)])
    units = {"S1": 1800.0, "S2": 1800.0}
    dist = {"L1": 50.0, "L2": 50.0}
    res = replenishment_metrics(assignments, units, dist)
    assert res.trips == 1 + 3
    assert res.travel_m == pytest.approx(2 * (1 * 50.0) + 2 * (3 * 50.0))
    agg = res.aggregate()
    assert agg["mean_travel_per_sku_m"] == pytest.approx(res.travel_m / 2, abs=1e-3)


def test_replenishment_grows_when_a_sku_is_split_across_bins():
    one_bin = replenishment_metrics(assigned([("S1", "L1", 300)]), {"S1": 1800.0}, {"L1": 50.0})
    two_bins = replenishment_metrics(
        assigned([("S1", "L1", 150), ("S1", "L2", 150)]), {"S1": 1800.0}, {"L1": 50.0, "L2": 50.0}
    )
    assert two_bins.trips > one_bin.trips
    assert two_bins.travel_m > one_bin.travel_m


def test_replenishment_term_matches_the_metric():
    a = assigned([("S1", "L1", 100)])
    units, dist = {"S1": 1800.0}, {"L1": 40.0}
    assert replenishment_term(a, units, dist) == pytest.approx(
        replenishment_metrics(a, units, dist).travel_m
    )


def test_replenishment_rejects_a_bad_window():
    with pytest.raises(ValueError):
        replenishment_metrics(assigned([]), {}, {}, window_days=0)
    with pytest.raises(ValueError):
        replenishment_metrics(assigned([]), {}, {}, cover_days=-1)


def test_zero_demand_sku_makes_no_replenishment_trips():
    """A stocked SKU with no demand in the window is not restocked by invention."""
    assignments = assigned([("S1", "L1", 100), ("S2", "L2", 300)])
    res = replenishment_metrics(assignments, {"S1": 1800.0}, {"L1": 50.0, "L2": 50.0})
    assert res.n_skus_stocked == 2
    assert res.n_skus_replenished == 1
    assert res.trips == 1
    assert res.travel_m == pytest.approx(2 * 50.0)
    assert res.units_in_skus_without_demand == 300
    assert res.aggregate()["denominator_skus"] == 2


# ---------------------------------------------------------------- objective weights

@pytest.fixture()
def tiny_physical(tmp_path):
    ds = write_tiny_dataset(tmp_path / "processed")
    root = ds.root
    warehouse = load_warehouse_from_locations(pd.read_csv(root / "locations.csv"))
    skus = load_skus(pd.read_csv(root / "products.csv"))
    inventory = load_inventory(pd.read_csv(root / "inventory.csv"))
    rules = load_compatibility_rules(pd.read_csv(root / "compatibility_rules.csv"))
    validator = Validator(skus, warehouse, rules, inventory=inventory, separation_radius_m=10.0)
    baseline = load_assignments(pd.read_csv(root / "storage_assignments_baseline.csv"))
    return warehouse, skus, inventory, validator, baseline, ds


def test_epsilon_zero_reproduces_the_phase2_objective(tiny_physical):
    warehouse, skus, _inventory, _validator, baseline, _ds = tiny_physical
    demand = {"SKU001": 5.0}
    without = Objective().components(baseline, skus, warehouse, demand, None, None)
    with_r = Objective().components(baseline, skus, warehouse, demand, None, 10_000.0)
    assert with_r["R_replenishment"] == pytest.approx(10_000.0)
    assert with_r["epsilon_R"] == 0.0
    assert with_r["total"] == pytest.approx(without["total"])


def test_epsilon_adds_a_replenishment_component(tiny_physical):
    warehouse, skus, _inventory, _validator, baseline, _ds = tiny_physical
    demand = {"SKU001": 5.0}
    base = Objective().components(baseline, skus, warehouse, demand, None, 1_000.0)
    weighted = Objective(epsilon=0.5).components(baseline, skus, warehouse, demand, None, 1_000.0)
    assert weighted["epsilon_R"] == pytest.approx(500.0)
    assert weighted["total"] == pytest.approx(base["total"] + 500.0)
    assert Objective(epsilon=0.5).evaluate(
        baseline, skus, warehouse, demand, None, 1_000.0
    ) == pytest.approx(weighted["total"])


def test_a_replenishment_weight_cannot_make_an_infeasible_layout_acceptable(tmp_path):
    """The objective always returns a number; feasibility is the validator's verdict."""
    ds = write_tiny_dataset(tmp_path / "processed", baseline="beam_overloaded")
    root = ds.root
    warehouse = load_warehouse_from_locations(pd.read_csv(root / "locations.csv"))
    skus = load_skus(pd.read_csv(root / "products.csv"))
    inventory = load_inventory(pd.read_csv(root / "inventory.csv"))
    rules = load_compatibility_rules(pd.read_csv(root / "compatibility_rules.csv"))
    validator = Validator(skus, warehouse, rules, inventory=inventory, separation_radius_m=10.0)
    layout = load_assignments(pd.read_csv(root / "storage_assignments_baseline.csv"))

    verdict = validator.validate(layout)
    assert verdict.is_feasible is False  # beam overload is a hard rule
    score = Objective(epsilon=1e9).evaluate(layout, skus, warehouse, {}, None, 1.0)
    assert score == pytest.approx(score)  # finite, but irrelevant to feasibility
    assert validator.validate(layout).is_feasible is False
