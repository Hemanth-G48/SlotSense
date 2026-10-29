"""Inventory and assignment integrity.

A layout only *moves* stock; it never creates or destroys units, never loses a SKU, and never
writes the same (SKU, bin) pair twice. Those are the properties this file pins, plus one
negative-space property: a candidate placement that is rejected must not change the state it
was tested against.

All pipelines here run on the owned tiny fixture under ``tmp_path`` — nothing touches the
shared ``outputs/`` tree.
"""

from __future__ import annotations

import copy

import pandas as pd

from src.models.entities import (
    AccessibilityZone,
    AssignmentType,
    Location,
    StorageAssignment,
)
from src.optimization.pipeline import run_phase5
from src.optimization.separation import SeparationGrid
from src.validation.loader import load_shipping
from src.validation.validator import validate_assignment
from tests.phase2_fixtures import tiny_config, write_tiny_dataset


def per_sku_units(path) -> dict[str, int]:
    df = pd.read_csv(path)
    return {
        str(sku): int(qty)
        for sku, qty in df.groupby("sku_id")["assigned_quantity"].sum().items()
    }


def inventory_units(processed) -> dict[str, int]:
    df = pd.read_csv(processed / "inventory.csv")
    return {
        str(sku): int(qty)
        for sku, qty in df.groupby("sku_id")["quantity_on_hand"].sum().items()
    }


# -- conservation ---------------------------------------------------------------------
def test_optimizer_preserves_every_unit_and_sku(tmp_path):
    processed = tmp_path / "processed"
    dataset = write_tiny_dataset(processed, baseline="feasible")

    summary = run_phase5(processed, tiny_config(), tmp_path / "optimized")

    written = per_sku_units(tmp_path / "optimized" / "optimized_assignments.csv")
    before = inventory_units(processed)
    assert written == before, "units before != units after (or a SKU changed quantity)"
    assert set(written) == set(before), "a SKU with on-hand inventory disappeared"
    assert sum(written.values()) == dataset.total_units
    assert summary["units_placed"] == summary["inventory_units"] == dataset.total_units
    assert summary["assignment_completeness"]["complete"] is True
    assert summary["assignment_completeness"]["unresolved_skus"] == []


def test_optimizer_preserves_units_when_the_baseline_is_infeasible(tmp_path):
    """Repair relocates records; it must not drop or invent a single unit."""
    processed = tmp_path / "processed"
    dataset = write_tiny_dataset(processed, baseline="beam_overloaded")

    summary = run_phase5(processed, tiny_config(), tmp_path / "optimized")

    written = per_sku_units(tmp_path / "optimized" / "optimized_assignments.csv")
    assert written == inventory_units(processed)
    assert sum(written.values()) == dataset.total_units == 197
    assert summary["feasibility_status"] == "FEASIBLE"
    assert summary["assignment_completeness"]["complete"] is True


def test_optimizer_output_has_no_duplicate_sku_bin_rows(tmp_path):
    processed = tmp_path / "processed"
    write_tiny_dataset(processed, baseline="feasible")
    run_phase5(processed, tiny_config(), tmp_path / "optimized")

    df = pd.read_csv(tmp_path / "optimized" / "optimized_assignments.csv")
    pairs = list(zip(df["sku_id"], df["location_id"]))
    assert len(pairs) == len(set(pairs)), f"duplicate (sku, bin) rows: {pairs}"

    # And the validator agrees the written layout is clean.
    wh, skus, comp, _baseline, inventory = load_shipping(processed)
    assignments = [
        StorageAssignment(r.sku_id, r.location_id, int(r.assigned_quantity), AssignmentType.OPTIMIZED)
        for r in df.itertuples(index=False)
    ]
    result = validate_assignment(assignments, skus, wh, comp, inventory)
    assert [v for v in result.violations if v.rule_id == "DU-01"] == []


def test_duplicate_sku_bin_pair_is_flagged(tmp_path):
    """The rule itself is exercised: a duplicate pin is a violation, not a rounding detail."""
    processed = tmp_path / "processed"
    write_tiny_dataset(processed, baseline="feasible")
    wh, skus, comp, baseline, inventory = load_shipping(processed)

    duplicated = list(baseline) + [
        StorageAssignment(baseline[0].sku_id, baseline[0].location_id, 1, AssignmentType.BASELINE)
    ]
    result = validate_assignment(duplicated, skus, wh, comp, inventory)

    assert [v.rule_id for v in result.violations if v.rule_id == "DU-01"]
    assert not result.is_feasible


def test_unplaceable_sku_is_reported_not_dropped(tmp_path):
    """A SKU that fits no bin must surface as an unplaced record with its binding reason."""
    processed = tmp_path / "processed"
    dataset = write_tiny_dataset(processed, baseline="feasible", extra_unplaceable_sku=True)

    summary = run_phase5(processed, tiny_config(), tmp_path / "optimized")

    assert summary["feasibility_status"] == "INFEASIBLE"
    assert summary["units_placed"] == dataset.total_units - 2
    assert summary["inventory_units"] == dataset.total_units
    unplaced = {u["sku_id"]: u for u in summary["unplaced_skus"]}
    assert "SKU005" in unplaced
    assert unplaced["SKU005"]["units_unplaced"] == 2
    assert unplaced["SKU005"]["binding_reason"] == "fit"
    assert summary["violations_by_rule"].get("COMP-01") == 1
    assert summary["violations_by_rule"].get("INV-02") == 1


# -- rejected candidates must not mutate state -----------------------------------------
def grid_bin(location_id: str, x: float) -> Location:
    return Location(
        location_id=location_id, zone_id="Z1", aisle_id="A1", rack_id="R1", bay=0, shelf_level=0,
        x=x, y=0.0, z=0.0, width_cm=60.0, height_cm=40.0, depth_cm=45.0,
        max_weight_kg=100.0, usable_volume_cm3=100_000.0,
        ergonomic_zone=AccessibilityZone.GOLDEN,
        allowed_handling=("standard",), allowed_hazard=("NONE",),
    )


def test_rejected_separation_candidate_does_not_mutate_the_grid():
    grid = SeparationGrid(10.0, [frozenset({"CAT001", "CAT010"})])
    committed = grid_bin("L0", 0.0)
    close = grid_bin("L1", 5.0)
    far = grid_bin("L2", 50.0)

    assert grid.allows(committed, "CAT001") is True
    grid.add(committed, "CAT001")
    cells_before, placed_before = grid.n_cells, grid.n_placed_bins

    # Rejected: within the radius. Asking must not record anything.
    assert grid.allows(close, "CAT010") is False
    assert (grid.n_cells, grid.n_placed_bins) == (cells_before, placed_before)

    # Allowed: also a pure query.
    assert grid.allows(far, "CAT010") is True
    assert (grid.n_cells, grid.n_placed_bins) == (cells_before, placed_before)

    # The same query is answered identically twice: no hidden state carries the answer.
    assert grid.allows(close, "CAT010") is False
    assert (grid.n_cells, grid.n_placed_bins) == (cells_before, placed_before)

    # Committing the previously-rejected bin is what changes state, and only then.
    grid.add(close, "CAT010")
    assert grid.n_placed_bins == placed_before + 1
    assert grid.allows(grid_bin("L3", 1.0), "CAT001") is False


def test_validator_does_not_mutate_the_assignment_list(tmp_path):
    processed = tmp_path / "processed"
    write_tiny_dataset(processed, baseline="feasible")
    wh, skus, comp, baseline, inventory = load_shipping(processed)
    before = copy.deepcopy(baseline)

    validate_assignment(baseline, skus, wh, comp, inventory)

    assert baseline == before, "validation must be a pure read of the layout"
