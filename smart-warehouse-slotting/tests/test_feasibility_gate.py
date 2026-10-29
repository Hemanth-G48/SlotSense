"""Feasibility, the evaluation gate, and the difference between *ran* and *valid*.

Three separate statements are asserted here:

1. A layout can be infeasible for a reason that has nothing to do with CAT-01 (e.g. one
   overloaded beam). Zero CAT-01 violations do not make a layout feasible.
2. The evaluation gate refuses to publish a comparison when either layout is infeasible:
   ``evaluation_status == "BLOCKED_INFEASIBLE_LAYOUT"``, ``comparison == []``, and the
   metrics table is labelled diagnostic-only. A blocked run is still an execution that
   completed (``execution_status == "OK"``).
3. Missing metrics are reported as ``None`` — never silently coerced to ``0``.

The pipelines run on the owned tiny fixture under ``tmp_path``; the shared ``outputs/`` tree
is never read or written.
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from src.evaluation.metrics import (
    affinity_separation,
    compare_baseline_vs_optimized,
    summarize_layout,
)
from src.models.entities import AssignmentType, StorageAssignment
from src.optimization.pipeline import run_phase5
from src.simulation.pipeline import EVAL_BLOCKED_INFEASIBLE, EVAL_OK, run_phase6
from src.validation.loader import load_shipping
from src.validation.validator import validate_assignment
from tests.phase2_fixtures import tiny_config, write_tiny_dataset

EVAL_FIELDS = ("execution_status", "evaluation_status", "comparison_valid", "blocked_layouts")


def write_optimized_csv(path, rows) -> None:
    """Write an assignments CSV in the canonical column order (a hand-built layout)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "sku_id": sku,
                "location_id": loc,
                "assigned_quantity": qty,
                "assignment_type": "optimized",
            }
            for sku, loc, qty in rows
        ]
    ).to_csv(path, index=False)


# -- feasibility is not the same question as CAT-01 ------------------------------------
def test_zero_cat01_violations_but_one_beam_violation_is_infeasible(tmp_path):
    processed = tmp_path / "processed"
    write_tiny_dataset(processed, baseline="beam_overloaded")
    wh, skus, comp, baseline, inventory = load_shipping(processed)

    result = validate_assignment(baseline, skus, wh, comp, inventory, separation_radius_m=10.0)

    rules = [v.rule_id for v in result.violations]
    assert "CAT-01" not in rules, "the fixture is meant to fail on structure only"
    assert rules == ["SL-02"], rules
    assert result.is_feasible is False


# -- the gate -------------------------------------------------------------------------
def test_gate_blocks_an_infeasible_baseline(tmp_path):
    processed = tmp_path / "processed"
    write_tiny_dataset(processed, baseline="beam_overloaded")
    optimized = tmp_path / "optimized"
    summary = run_phase5(processed, tiny_config(), optimized)
    assert summary["feasibility_status"] == "FEASIBLE"  # the optimized side is genuinely valid

    result = run_phase6(
        processed,
        scenario="A",
        out=tmp_path / "evaluation",
        optimized_path=optimized / "optimized_assignments.csv",
    )

    assert set(EVAL_FIELDS).issubset(result)
    assert result["execution_status"] == "OK", "the run completed; the layout is what failed"
    assert result["evaluation_status"] == EVAL_BLOCKED_INFEASIBLE
    assert result["comparison_valid"] is False
    assert result["blocked_layouts"] == ["baseline"]
    assert result["comparison"] == [], "no comparison may be published for an invalid layout"
    assert result["feasibility"]["baseline"]["feasibility_status"] == "INFEASIBLE"
    assert result["feasibility"]["baseline"]["violations_by_rule"] == {"SL-02": 1}
    assert result["feasibility"]["optimized"]["feasibility_status"] == "FEASIBLE"
    assert "baseline" in result["blocked_reason"]


def test_gate_blocks_an_infeasible_optimized_layout(tmp_path):
    """The gate is symmetric: a valid baseline does not license an invalid optimized layout."""
    processed = tmp_path / "processed"
    write_tiny_dataset(processed, baseline="feasible_high_stock")
    # Same inventory, deliberately re-packed onto one beam: 95 + 95 = 190 kg.
    optimized = tmp_path / "optimized"
    write_optimized_csv(
        optimized / "optimized_assignments.csv",
        [
            ("SKU001", "L0020", 95),
            ("SKU002", "L0021", 95),
            ("SKU003", "L0100", 4),
            ("SKU004", "L1000", 3),
        ],
    )

    result = run_phase6(
        processed,
        scenario="A",
        out=tmp_path / "evaluation",
        optimized_path=optimized / "optimized_assignments.csv",
    )

    assert result["evaluation_status"] == EVAL_BLOCKED_INFEASIBLE
    assert result["blocked_layouts"] == ["optimized"]
    assert result["feasibility"]["baseline"]["is_feasible"] is True
    assert result["feasibility"]["optimized"]["violations_by_rule"] == {"SL-02": 1}
    assert result["comparison"] == []


def test_gate_publishes_the_comparison_when_both_layouts_are_feasible(tmp_path):
    """Positive control: the gate is not a permanent block."""
    processed = tmp_path / "processed"
    write_tiny_dataset(processed, baseline="feasible")
    optimized = tmp_path / "optimized"
    run_phase5(processed, tiny_config(), optimized)

    result = run_phase6(
        processed,
        scenario="A",
        out=tmp_path / "evaluation",
        optimized_path=optimized / "optimized_assignments.csv",
    )

    assert result["execution_status"] == "OK"
    assert result["evaluation_status"] == EVAL_OK
    assert result["comparison_valid"] is True
    assert result["blocked_layouts"] == []
    assert result["diagnostic_only"] is False
    assert result["comparison"], "a valid comparison must publish its rows"
    assert result["diagnostic_comparison"] is None
    assert all(row["diagnostic_only"] is False for row in result["comparison"])
    assert result["feasibility"]["baseline"]["is_feasible"] is True
    assert result["feasibility"]["optimized"]["is_feasible"] is True


def test_blocked_run_writes_diagnostic_only_artifacts(tmp_path):
    processed = tmp_path / "processed"
    write_tiny_dataset(processed, baseline="beam_overloaded")
    optimized = tmp_path / "optimized"
    run_phase5(processed, tiny_config(), optimized)
    out = tmp_path / "evaluation"

    run_phase6(
        processed, scenario="A", out=out,
        optimized_path=optimized / "optimized_assignments.csv",
    )

    summary = json.loads((out / "evaluation_summary.json").read_text())
    assert summary["evaluation_status"] == EVAL_BLOCKED_INFEASIBLE
    assert summary["comparison"] == []
    assert summary["blocked_layouts"] == ["baseline"]
    assert all(row["diagnostic_only"] is True for row in summary["diagnostic_comparison"])

    metrics = pd.read_csv(out / "optimization_metrics.csv")
    assert len(metrics) > 0, "the diagnostic table is still written, clearly labelled"
    assert set(metrics["diagnostic_only"].astype(str).str.lower()) == {"true"}

    # The per-layout audits are still produced, so the block can be diagnosed.
    for name in ("constraint_audit_baseline.csv", "constraint_audit_optimized.csv",
                 "validation_checks_baseline.csv", "validation_checks_optimized.csv"):
        assert (out / name).exists(), name


# -- execution status vs feasibility status -------------------------------------------
def test_execution_status_is_distinct_from_feasibility_status(tmp_path):
    processed = tmp_path / "processed"
    write_tiny_dataset(processed, baseline="feasible", extra_unplaceable_sku=True)

    summary = run_phase5(processed, tiny_config(), tmp_path / "optimized")

    assert summary["execution_status"] == "OK"
    assert summary["feasibility_status"] == "INFEASIBLE"
    # The two vocabularies never overlap: a run can execute perfectly and still be invalid.
    assert summary["execution_status"] not in {"FEASIBLE", "INFEASIBLE"}
    assert summary["feasibility_status"] not in {"OK", "ERROR"}
    assert summary["feasibility"] is False


def test_a_crashed_run_is_not_reported_as_infeasible(tmp_path):
    """A process that died validated nothing, so feasibility stays undetermined (None)."""
    processed = tmp_path / "processed"
    write_tiny_dataset(processed, baseline="feasible")
    (processed / "products.csv").unlink()
    out = tmp_path / "optimized"

    with pytest.raises(FileNotFoundError):
        run_phase5(processed, tiny_config(), out)

    summary = json.loads((out / "optimization_summary.json").read_text())
    assert summary["execution_status"] == "ERROR"
    assert summary["feasibility"] is None
    assert summary["feasibility_status"] is None
    assert summary["feasibility_evaluated"] is False
    assert summary["error"].startswith("FileNotFoundError")


# -- missing metrics are not zero ------------------------------------------------------
def test_missing_metrics_are_not_coerced_to_zero():
    baseline_metrics = {"total_travel_distance_m": 100.0}
    optimized_metrics = {
        "total_travel_distance_m": 80.0,
        "cube_utilization_pct": 12.0,
        "affinity_separation_m": None,
    }

    rows = {row["metric"]: row for row in compare_baseline_vs_optimized(baseline_metrics, optimized_metrics)}

    # A real comparison still computes normally.
    assert rows["total_travel_distance_m"]["percent_change"] == pytest.approx(-20.0)
    # Present on one side only: unknown, not zero.
    assert rows["cube_utilization_pct"]["baseline"] is None
    assert rows["cube_utilization_pct"]["absolute_diff"] is None
    assert rows["cube_utilization_pct"]["percent_change"] is None
    # Present on both sides but unknown: still unknown.
    assert rows["affinity_separation_m"]["absolute_diff"] is None
    assert rows["affinity_separation_m"]["percent_change"] is None
    # Absent everywhere: no row at all, rather than a fabricated zero.
    assert "throughput_orders_per_hr" not in rows


def test_unmeasured_runtime_and_affinity_stay_none(tmp_path):
    processed = tmp_path / "processed"
    write_tiny_dataset(processed, baseline="feasible")
    wh, skus, _comp, baseline, inventory = load_shipping(processed)
    slotting = {a.sku_id: [(a.location_id, a.assigned_quantity)] for a in baseline}
    result = validate_assignment(baseline, skus, wh, [], inventory)

    metrics = summarize_layout(
        slotting, skus, wh.locations, {"total_distance_m": 10.0}, result, runtime_sec=None
    )

    assert metrics["optimization_runtime_sec"] is None

    no_pairs = affinity_separation({}, {}, lambda a, b: 0.0)
    assert no_pairs["affinity_separation_m"] is None
    assert no_pairs["affinity_pairs_evaluated"] == 0


# -- the gate reads the same verdict the validator produced ----------------------------
def test_gate_verdict_matches_an_independent_validation(tmp_path):
    processed = tmp_path / "processed"
    write_tiny_dataset(processed, baseline="beam_overloaded")
    optimized = tmp_path / "optimized"
    run_phase5(processed, tiny_config(), optimized)

    result = run_phase6(
        processed, scenario="A", out=tmp_path / "evaluation",
        optimized_path=optimized / "optimized_assignments.csv",
    )

    wh, skus, comp, baseline, inventory = load_shipping(processed)
    independent = validate_assignment(baseline, skus, wh, comp, inventory, separation_radius_m=10.0)
    reported = result["feasibility"]["baseline"]

    assert reported["n_violations"] == len(independent.violations)
    assert reported["violations_by_rule"] == {"SL-02": len(independent.violations)}
    assert reported["is_feasible"] is independent.is_feasible
    assert reported["checks_run"] == independent.checks_run


def test_open_optimization_summary_is_consistent_with_the_written_assignments(tmp_path):
    """The summary's status is the validator's verdict on the layout it actually wrote."""
    processed = tmp_path / "processed"
    write_tiny_dataset(processed, baseline="feasible")
    out = tmp_path / "optimized"
    summary = run_phase5(processed, tiny_config(), out)

    wh, skus, comp, _baseline, inventory = load_shipping(processed)
    written = pd.read_csv(out / "optimized_assignments.csv")
    assignments = [
        StorageAssignment(r.sku_id, r.location_id, int(r.assigned_quantity), AssignmentType.OPTIMIZED)
        for r in written.itertuples(index=False)
    ]
    result = validate_assignment(assignments, skus, wh, comp, inventory, separation_radius_m=10.0)

    assert summary["feasibility_status"] == ("FEASIBLE" if result.is_feasible else "INFEASIBLE")
    assert summary["n_violations"] == len(result.violations)
