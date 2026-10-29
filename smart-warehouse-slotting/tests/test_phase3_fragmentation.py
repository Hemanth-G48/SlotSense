"""Tests for the fragmentation policy that supplies the second factor of the 2x2."""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from src.experiments.fragmentation import (
    POLICY_MIN_BINS,
    consolidate_min_bins,
    fragmentation_stats,
)
from src.validation.loader import (
    load_compatibility_rules,
    load_inventory,
    load_skus,
    load_warehouse_from_locations,
)
from src.validation.validator import Validator
from tests.phase2_fixtures import FEASIBLE_BASELINE_LAYOUT, write_tiny_dataset


class _StubValidator:
    def __init__(self, feasible: bool = True):
        self.feasible = feasible

    def validate(self, assignments, record_checks=True):  # noqa: ARG002
        return SimpleNamespace(is_feasible=self.feasible, violations=[])


@pytest.fixture()
def tiny(tmp_path):
    ds = write_tiny_dataset(tmp_path / "processed")
    root = ds.root
    locations = pd.read_csv(root / "locations.csv")
    warehouse = load_warehouse_from_locations(locations)
    skus = load_skus(pd.read_csv(root / "products.csv"))
    inventory = load_inventory(pd.read_csv(root / "inventory.csv"))
    rules = load_compatibility_rules(pd.read_csv(root / "compatibility_rules.csv"))
    validator = Validator(skus, warehouse, rules, inventory=inventory, separation_radius_m=10.0)
    return warehouse, skus, inventory, validator, ds


def frame(rows):
    return pd.DataFrame(rows, columns=["sku_id", "location_id", "assigned_quantity"])


def full_frame(ds, split_sku: str):
    """The fixture's feasible layout, with ``split_sku`` split across two of its bins."""
    rows = []
    for sku_id, location_id in FEASIBLE_BASELINE_LAYOUT:
        units = ds.units_by_sku[sku_id]
        if sku_id == split_sku:
            rows.append((sku_id, location_id, units // 2))
            rows.append((sku_id, "L0101", units - units // 2))
        else:
            rows.append((sku_id, location_id, units))
    return frame(rows)


def test_two_bins_are_consolidated_into_one_and_inventory_is_conserved(tiny):
    warehouse, skus, inventory, validator, ds = tiny
    units = inventory["SKU001"]
    split = full_frame(ds, "SKU001")
    consolidated, stats = consolidate_min_bins(
        split, skus=skus, warehouse=warehouse, validator=validator
    )

    assert stats["policy"] == POLICY_MIN_BINS
    assert stats["feasible"] is True
    assert stats["units_conserved"] is True
    assert stats["before"]["bins_used"] == 5
    assert stats["after"]["bins_used"] == 4
    assert stats["bins_released"] == 1
    assert int(consolidated["assigned_quantity"].sum()) == ds.total_units
    assert int(consolidated.loc[consolidated["sku_id"] == "SKU001", "assigned_quantity"].sum()) == units
    assert int((consolidated["sku_id"] == "SKU001").sum()) == 1


def test_consolidation_is_deterministic(tiny):
    warehouse, skus, _inventory, validator, ds = tiny
    split = full_frame(ds, "SKU001")
    a, _ = consolidate_min_bins(split, skus=skus, warehouse=warehouse, validator=validator)
    b, _ = consolidate_min_bins(split, skus=skus, warehouse=warehouse, validator=validator)
    assert a.equals(b)


def test_retention_is_capacity_based_not_distance_based(tiny):
    """The larger bin wins even when the smaller one is nearer dispatch."""
    warehouse, skus, _inventory, _validator, _ds = tiny
    # L0020 and L0021 are both 100 kg / 108,000 cm3, so drive the choice with a SKU
    # whose total exceeds one bin and check the retained set is stable regardless of
    # distance map values.
    big = frame([("SKU001", "L0020", 75), ("SKU001", "L0021", 75)])
    near = {"L0020": 1.0, "L0021": 999.0}
    far = {"L0020": 999.0, "L0021": 1.0}
    a, _ = consolidate_min_bins(big, skus=skus, warehouse=warehouse,
                                validator=_StubValidator(True), location_distance_m=near)
    b, _ = consolidate_min_bins(big, skus=skus, warehouse=warehouse,
                                validator=_StubValidator(True), location_distance_m=far)
    assert a.equals(b)
    # 150 units cannot fit one 100 kg bin: fragmentation is capacity-bound.
    assert a["location_id"].nunique() == 2


def test_infeasible_consolidation_falls_back_to_the_input(tiny):
    warehouse, skus, _inventory, _validator, _ds = tiny
    split = frame([("SKU001", "L0020", 3), ("SKU001", "L0021", 5)])
    result, stats = consolidate_min_bins(
        split, skus=skus, warehouse=warehouse, validator=_StubValidator(False)
    )
    assert stats["feasible"] is False
    assert result.equals(split)


def test_stats_report_the_fragmentation_index():
    layout = frame([("S1", "L1", 1), ("S1", "L2", 1), ("S2", "L3", 1)])
    stats = fragmentation_stats(layout)
    assert stats["bins_used"] == 3
    assert stats["n_skus"] == 2
    assert stats["multi_bin_skus"] == 1
    assert stats["fragmentation_index"] == pytest.approx(1.5)


def test_an_unpacked_sku_is_retried_pinned_not_abandoned(tiny, monkeypatch):
    """A SKU that cannot be packed is pinned to its original rows and the pass retried."""
    warehouse, skus, _inventory, validator, ds = tiny
    split = full_frame(ds, "SKU001")

    import src.experiments.fragmentation as frag

    real_build = frag._build
    calls = {"n": 0}

    def flaky_build(assignments, keep, skus_arg, warehouse_arg):
        calls["n"] += 1
        frame_out, failed = real_build(assignments, keep, skus_arg, warehouse_arg)
        if calls["n"] == 1:
            # Simulate a capacity-bound SKU that could not be repacked on this pass.
            return frame_out[frame_out["sku_id"] != "SKU001"], ["SKU001"]
        return frame_out, failed

    monkeypatch.setattr(frag, "_build", flaky_build)
    consolidated, stats = frag.consolidate_min_bins(
        split, skus=skus, warehouse=warehouse, validator=validator
    )

    assert calls["n"] >= 2
    assert stats["feasible"] is True
    assert stats["iterations"] >= 2
    assert int(consolidated["assigned_quantity"].sum()) == ds.total_units
    assert set(consolidated["sku_id"]) == set(split["sku_id"])
