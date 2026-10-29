"""Baseline feasibility repair: the baseline must be *legal* before it can be compared.

The canonical baseline is infeasible (1,071 CAT-01 violations), so the evaluation gate blocks
every comparison. This suite pins the repair that closes that gap without weakening anything:

1. the repaired baseline passes the **independent** validator with zero violations and exact
   inventory conservation (same units, no duplicate (SKU, bin), no unplaced SKU);
2. the repair is **feasibility-only**: the objective is never evaluated (proved by making
   ``Objective.evaluate`` explode), no refinement runs, and only the smallest relocations that
   clear a constraint are accepted — it is not a re-slot;
3. the canonical input and the as-supplied copy are **never written**;
4. a repair that cannot reach feasibility within bounds is **not adopted**, and the gate keeps
   blocking — the failure mode is a block, never a fake comparison;
5. when the repaired baseline *is* feasible, the unchanged gate publishes a valid comparison,
   and the as-supplied metrics stay available under a clearly-labelled diagnostic section.

Everything runs on the tiny fixture under ``tmp_path``; the shared ``outputs/`` tree is never
read or written.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from src.models.entities import AssignmentType, StorageAssignment
from src.optimization.baseline import (
    BASELINE_REPAIRED_FILENAME,
    BASELINE_VARIANT_AS_SUPPLIED,
    BASELINE_VARIANT_REPAIRED_MINIMAL,
    check_inventory_conservation,
    prepare_baseline_variant,
)
from src.optimization.objective import Objective
from src.optimization.optimizer import RepairConfig
from src.optimization.pipeline import run_phase5
from src.simulation.pipeline import EVAL_OK, run_phase6
from src.validation.loader import load_shipping
from src.validation.validator import validate_assignment
from tests.phase2_fixtures import assignment_rows, tiny_config, write_tiny_dataset


def _digest(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _layout(processed: Path, variant) -> list[tuple[str, str, int]]:
    return [(a.sku_id, a.location_id, a.assigned_quantity) for a in variant.assignments]


# -- the repair itself ------------------------------------------------------------------
def test_repair_reaches_feasibility_and_preserves_inventory(tmp_path):
    """Legal above all: zero violations under the independent validator, units unchanged."""
    processed = tmp_path / "processed"
    dataset = write_tiny_dataset(processed, baseline="beam_overloaded")
    canonical = processed / "storage_assignments_baseline.csv"
    digest_before = _digest(canonical)
    out = tmp_path / "outputs"

    variant = prepare_baseline_variant(processed, tiny_config(), out)

    assert variant.variant == BASELINE_VARIANT_REPAIRED_MINIMAL
    assert variant.is_repaired is True
    repair = variant.repair
    assert repair["attempted"] is True
    assert repair["objective_enabled"] is False
    assert repair["scope"] == "feasibility only"
    assert repair["initial_violations"] == 1
    assert repair["initial_violations_by_rule"] == {"SL-02": 1}
    assert repair["final_violations"] == 0
    assert repair["final_violations_by_rule"] == {}
    assert repair["moves_attempted"] >= 1
    assert repair["termination_reason"] == "feasible"
    assert repair["feasible"] is True
    assert repair["candidate_mode"] == "feasibility"

    # Inventory conservation is checked independently of the validator, exactly.
    conservation = variant.conservation
    assert conservation["exact"] is True
    assert conservation["units_assigned"] == conservation["units_required"] == dataset.total_units
    assert conservation["skus_placed"] == conservation["skus_required"] == 4
    assert conservation["unplaced_skus"] == []
    assert conservation["duplicate_sku_bin_pairs"] == 0
    assert conservation["unknown_skus"] == []

    # The independent validator — not the repair's own statistics — declares it feasible.
    wh, skus, comp, _baseline, inventory = load_shipping(processed)
    result = validate_assignment(
        variant.assignments, skus, wh, comp, inventory, separation_radius_m=10.0
    )
    assert result.is_feasible is True
    assert result.violations == []

    # The artifact exists, and holds the layout that was validated above.
    path = out / BASELINE_REPAIRED_FILENAME
    assert path.is_file()
    assert assignment_rows(path) == sorted(_layout(processed, variant))

    # The canonical input is untouched.
    assert _digest(canonical) == digest_before


def test_repair_moves_only_what_the_constraint_requires(tmp_path):
    """It is a repair, not a re-slot: untouched records keep their bin, displacement is small."""
    processed = tmp_path / "processed"
    write_tiny_dataset(processed, baseline="beam_overloaded")
    out = tmp_path / "outputs"

    variant = prepare_baseline_variant(processed, tiny_config(), out)
    movement = variant.repair["movement"]

    assert movement["comparable"] is True
    assert movement["records_total"] == 4
    assert 1 <= movement["records_relocated"] <= 2, movement
    assert movement["records_unchanged"] >= 2
    assert movement["total_displacement_m"] > 0
    # The warehouse is 20 m wide and 3 m tall; a minimal repair cannot need more than that.
    assert movement["total_displacement_m"] < 30.0

    original = set(assignment_rows(processed / "storage_assignments_baseline.csv"))
    repaired = set(assignment_rows(out / BASELINE_REPAIRED_FILENAME))
    # Every record that did not move is still present as an identical (SKU, bin, qty) row.
    assert len(original & repaired) == movement["records_total"] - movement["records_relocated"]
    assert len(repaired) == len(original), "no record may be dropped or duplicated"


def test_repair_never_consults_the_objective(tmp_path, monkeypatch):
    """Feasibility-only means: travel / affinity / ergonomics / utilisation are not consulted."""
    processed = tmp_path / "processed"
    write_tiny_dataset(processed, baseline="beam_overloaded")

    def explode(*_args, **_kwargs):
        raise AssertionError("the objective was evaluated during a feasibility-only repair")

    monkeypatch.setattr(Objective, "evaluate", explode)

    variant = prepare_baseline_variant(processed, tiny_config(), tmp_path / "outputs")

    assert variant.variant == BASELINE_VARIANT_REPAIRED_MINIMAL
    assert variant.repair["final_violations"] == 0


def test_repair_is_deterministic(tmp_path):
    processed = tmp_path / "processed"
    write_tiny_dataset(processed, baseline="beam_overloaded")

    first = prepare_baseline_variant(processed, tiny_config(), tmp_path / "a")
    second = prepare_baseline_variant(processed, tiny_config(), tmp_path / "b")

    assert first.repaired_path is not None and second.repaired_path is not None
    assert assignment_rows(first.repaired_path) == assignment_rows(second.repaired_path)
    assert first.repair["moves_accepted"] == second.repair["moves_accepted"]
    assert first.repair["movement"] == second.repair["movement"]


def test_an_already_feasible_baseline_is_left_alone(tmp_path):
    processed = tmp_path / "processed"
    write_tiny_dataset(processed, baseline="feasible")
    out = tmp_path / "outputs"

    variant = prepare_baseline_variant(processed, tiny_config(), out)

    assert variant.variant == BASELINE_VARIANT_AS_SUPPLIED
    assert variant.is_repaired is False
    assert variant.repair["attempted"] is False
    assert variant.repair["reason"].startswith("baseline is already feasible")
    assert not (out / BASELINE_REPAIRED_FILENAME).exists(), (
        "an as-supplied baseline must not produce a repaired artifact"
    )
    assert _layout(processed, variant) == [
        (a.sku_id, a.location_id, a.assigned_quantity)
        for a in load_shipping(processed)[3]
    ]


def test_repair_disabled_by_caller_returns_the_as_supplied_layout(tmp_path):
    processed = tmp_path / "processed"
    write_tiny_dataset(processed, baseline="beam_overloaded")

    variant = prepare_baseline_variant(
        processed, tiny_config(), tmp_path / "outputs", enabled=False
    )

    assert variant.variant == BASELINE_VARIANT_AS_SUPPLIED
    assert variant.repair["attempted"] is False


def test_conservation_check_names_each_failure_mode():
    inventory = {"SKU_A": 3, "SKU_B": 2}
    good = [
        StorageAssignment("SKU_A", "L1", 3, AssignmentType.BASELINE),
        StorageAssignment("SKU_B", "L2", 2, AssignmentType.BASELINE),
    ]
    assert check_inventory_conservation(good, inventory)["exact"] is True

    duplicate_pin = good + [StorageAssignment("SKU_A", "L1", 1, AssignmentType.BASELINE)]
    result = check_inventory_conservation(duplicate_pin, inventory)
    assert result["duplicate_sku_bin_pairs"] == 1
    assert result["duplicate_examples"] == [("SKU_A", "L1")]
    assert result["exact"] is False

    under_stored = [
        StorageAssignment("SKU_A", "L1", 2, AssignmentType.BASELINE),
        StorageAssignment("SKU_B", "L2", 2, AssignmentType.BASELINE),
    ]
    result = check_inventory_conservation(under_stored, inventory)
    assert result["unplaced_skus"] == ["SKU_A"]
    assert result["units_assigned"] == 4 and result["units_required"] == 5
    assert result["exact"] is False


# -- the gate --------------------------------------------------------------------------
def test_repair_that_cannot_reach_feasibility_keeps_the_gate_blocking(tmp_path):
    """A bounded failure is not adopted: the run keeps the illegal baseline and stays blocked."""
    processed = tmp_path / "processed"
    write_tiny_dataset(processed, baseline="beam_overloaded")

    variant = prepare_baseline_variant(
        processed,
        tiny_config(),
        tmp_path / "outputs",
        repair_config=RepairConfig(max_moves=0, max_seconds=60.0, candidate_mode="feasibility"),
    )

    assert variant.variant == BASELINE_VARIANT_AS_SUPPLIED
    assert variant.repaired_path is None
    assert variant.repair["attempted"] is True
    assert variant.repair["feasible"] is False
    assert variant.repair["termination_reason"] == "max_moves"
    assert variant.repair["final_violations"] > 0

    optimized = tmp_path / "optimized"
    run_phase5(processed, tiny_config(), optimized)
    result = run_phase6(
        processed,
        scenario="A",
        out=tmp_path / "evaluation",
        optimized_path=optimized / "optimized_assignments.csv",
        baseline_path=variant.repaired_path,
        baseline_variant=variant.variant,
        baseline_repair=variant.repair,
    )

    assert result["execution_status"] == "OK"
    assert result["comparison_valid"] is False
    assert result["evaluation_status"] == "BLOCKED_INFEASIBLE_LAYOUT"
    assert result["blocked_layouts"] == ["baseline"]
    assert result["comparison"] == []
    assert result["diagnostic_only"] is True


def test_repaired_baseline_lets_the_gate_publish_a_valid_comparison(tmp_path):
    """The whole point: with a feasible baseline the unchanged gate publishes a comparison."""
    processed = tmp_path / "processed"
    write_tiny_dataset(processed, baseline="beam_overloaded")
    out = tmp_path / "outputs"
    variant = prepare_baseline_variant(processed, tiny_config(), out)

    optimized = tmp_path / "optimized"
    optimization = run_phase5(processed, tiny_config(), optimized, baseline_variant=variant)

    # The optimization summary says which baseline it is measured against, and why.
    assert optimization["baseline_variant"] == BASELINE_VARIANT_REPAIRED_MINIMAL
    assert optimization["baseline_source"].endswith(BASELINE_REPAIRED_FILENAME)
    assert optimization["baseline_feasibility"] is True
    assert optimization["baseline_violations_by_rule"] == {}
    assert optimization["baseline_feasibility_as_supplied"] is False
    assert optimization["baseline_violations_by_rule_as_supplied"] == {"SL-02": 1}
    assert optimization["baseline_repair"]["objective_enabled"] is False
    assert "feasibility only" in optimization["baseline_note"]
    assert optimization["objective"]["baseline_value_as_supplied"] is not None

    result = run_phase6(
        processed,
        scenario="A",
        out=tmp_path / "evaluation",
        optimized_path=optimized / "optimized_assignments.csv",
        baseline_path=variant.repaired_path,
        baseline_variant=variant.variant,
        baseline_repair=variant.repair,
    )

    assert result["evaluation_status"] == EVAL_OK
    assert result["comparison_valid"] is True
    assert result["diagnostic_only"] is False
    assert result["blocked_layouts"] == []
    assert result["comparison"], "a valid comparison must publish its rows"
    assert all(row["diagnostic_only"] is False for row in result["comparison"])
    assert result["feasibility"]["baseline"]["is_feasible"] is True
    assert result["feasibility"]["baseline"]["n_violations"] == 0
    assert result["feasibility"]["optimized"]["is_feasible"] is True
    assert result["baseline_variant"] == BASELINE_VARIANT_REPAIRED_MINIMAL
    assert result["baseline_source"].endswith(BASELINE_REPAIRED_FILENAME)
    # The note is recorded at the top level as well as inside baseline_repair, so the
    # evaluation summary alone says the baseline was repaired for feasibility only.
    assert "feasibility only" in result["baseline_note"]
    assert "objective disabled" in result["baseline_note"]
    assert result["baseline_note"] == result["baseline_repair"]["note"]

    # The illegal input layout is still visible, clearly labelled, never part of the comparison.
    diagnostic = result["diagnostic_baseline"]
    assert diagnostic is not None
    assert diagnostic["diagnostic_only"] is True
    assert diagnostic["baseline_variant"] == BASELINE_VARIANT_AS_SUPPLIED
    assert diagnostic["feasibility"]["is_feasible"] is False
    assert diagnostic["feasibility"]["violations_by_rule"] == {"SL-02": 1}
    assert diagnostic["metrics"]["diagnostic_only"] is True
    assert diagnostic["delta_vs_evaluated_baseline"]["constraint_violations"] < 0
    assert (tmp_path / "evaluation" / "constraint_audit_baseline_as_supplied.csv").exists()
