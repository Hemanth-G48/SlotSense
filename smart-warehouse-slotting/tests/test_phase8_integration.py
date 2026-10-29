"""Phase-8 integration / hardening tests: end-to-end pipeline, edge cases, malformed input,
and the delivery acceptance checks.

Every artifact assertion here runs the real pipeline into ``tmp_path`` and inspects *its own*
output. Nothing reads or writes the shared ``outputs/`` tree: an assertion against that tree
tests whichever run happened to write it last (that is how the old audit test became
run-order dependent).
"""

import json
import os
from pathlib import Path

import pandas as pd
import pytest

from src.validation.audit import write_constraint_audit, write_validation_checks
from src.validation.loader import load_shipping
from src.validation.validator import validate_assignment
from tests.phase2_fixtures import (
    REQUIRED_ARTIFACTS,
    produce_delivery_artifacts,
    write_tiny_dataset,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROCESSED = Path(
    os.environ.get("DATASET_DIR", PROJECT_ROOT.parent / "dataset" / "processed")
).resolve()


def test_required_artifacts_are_produced_by_the_pipeline(tmp_path):
    """The four delivery artifacts must be reproducible from an owned run."""
    processed = tmp_path / "processed"
    write_tiny_dataset(processed, baseline="feasible")
    root = tmp_path / "outputs"

    produce_delivery_artifacts(processed, root)

    for relative in REQUIRED_ARTIFACTS:
        assert (root / relative).is_file(), f"missing required artifact: {relative}"
        assert (root / relative).stat().st_size > 0, f"empty required artifact: {relative}"


def test_constraint_audit_is_not_header_only(tmp_path):
    """The audit export carries rows — PASS rows when clean, one row per violation when not.

    Regenerated in ``tmp_path`` from a real validation, so the result cannot depend on which
    pipeline run last wrote ``outputs/constraint_audit.csv``.
    """
    processed = tmp_path / "processed"
    write_tiny_dataset(processed, baseline="feasible")
    wh, skus, comp, baseline, inventory = load_shipping(processed)

    clean = validate_assignment(baseline, skus, wh, comp, inventory, separation_radius_m=10.0)
    assert clean.is_feasible
    clean_audit = tmp_path / "constraint_audit_clean.csv"
    write_constraint_audit(baseline, clean, clean_audit)
    written = pd.read_csv(clean_audit)
    assert len(written) == len(baseline) > 0
    assert set(written["passed"].astype(str).str.lower()) == {"true"}
    assert (written["rule_id"].astype(str).str.len() > 0).all()

    # A layout that fails a hard rule still produces a non-empty, rule-identified audit.
    write_tiny_dataset(processed, baseline="beam_overloaded")
    wh, skus, comp, baseline, inventory = load_shipping(processed)
    failing = validate_assignment(baseline, skus, wh, comp, inventory, separation_radius_m=10.0)
    assert not failing.is_feasible
    failing_audit = tmp_path / "constraint_audit_failing.csv"
    checks_path = tmp_path / "validation_checks_failing.csv"
    write_constraint_audit(baseline, failing, failing_audit)
    write_validation_checks(failing, checks_path)

    audit = pd.read_csv(failing_audit)
    assert len(audit) == len(failing.violations) > 0
    assert set(audit["passed"].astype(str).str.lower()) == {"false"}
    assert set(audit["rule_id"].astype(str)) == {"SL-02"}

    checks = pd.read_csv(checks_path)
    assert {"rule_id", "observed", "limit"}.issubset(checks.columns)
    assert len(checks) == failing.checks_run
    assert (~checks["passed"].astype(bool)).sum() == len(failing.violations)


def test_optimized_output_is_consistent_with_its_summary(tmp_path):
    """The summary's verdict and the assignments it describes must agree — on an owned run."""
    processed = tmp_path / "processed"
    write_tiny_dataset(processed, baseline="feasible")
    root = tmp_path / "outputs"

    produced = produce_delivery_artifacts(processed, root)
    summary = produced["optimization"]
    written = json.loads((root / "optimized" / "optimization_summary.json").read_text())

    assert written["globally_optimal"] is False
    assert written["execution_status"] == "OK"
    assert written["units_placed"] == written["inventory_units"]
    assert written["final_objective"] <= written["baseline_objective"]
    assert written["assignment_completeness"]["complete"] is True
    if written["feasibility_status"] == "FEASIBLE":
        assert written["n_violations"] == 0
        assert written["violations_by_rule"] == {}
    else:
        assert written["n_violations"] > 0
        assert written["violations_by_rule"]
    assert summary["feasibility_status"] == written["feasibility_status"]


def test_malformed_config_rejected(tmp_path):
    from src.models.config import Config

    bad = tmp_path / "bad.json"
    bad.write_text("{not valid json")
    with pytest.raises(ValueError):
        Config.from_json(bad)


def test_validator_rejects_referential_junk():
    from src.models.entities import AssignmentType, StorageAssignment
    from src.validation.loader import load_skus, load_warehouse_from_locations

    if not PROCESSED.exists():
        pytest.skip("canonical dataset not generated")
    locations = pd.read_csv(PROCESSED / "locations.csv")
    products = pd.read_csv(PROCESSED / "products.csv")
    wh = load_warehouse_from_locations(locations)
    skus = load_skus(products)
    # Assignment referencing a nonexistent location and SKU must be flagged.
    bad = [
        StorageAssignment("SKU000001", "NONEXISTENT", 1, AssignmentType.OPTIMIZED),
        StorageAssignment("UNKNOWN_SKU", "LOC000001", 1, AssignmentType.OPTIMIZED),
    ]
    res = validate_assignment(bad, skus, wh)
    assert any(v.rule_id == "REF-02" for v in res.violations)
    assert any(v.rule_id == "REF-01" for v in res.violations)


def test_end_to_end_pipeline_is_reproducible(tmp_path):
    """Re-running the optimizer with the same seed reproduces the final objective."""
    from src.models.config import Config
    from src.optimization.pipeline import run_phase5

    if not PROCESSED.exists():
        pytest.skip("canonical dataset not generated")
    cfg = Config.from_json(PROJECT_ROOT / "configs" / "benchmark.json")
    s1 = run_phase5(PROCESSED, cfg, tmp_path / "run1")
    s2 = run_phase5(PROCESSED, cfg, tmp_path / "run2")
    assert s1["final_objective"] == s2["final_objective"]
