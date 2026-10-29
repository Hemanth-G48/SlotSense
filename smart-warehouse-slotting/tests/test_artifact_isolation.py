"""Artifact isolation: a test run owns its output tree.

The repository's ``outputs/`` directory is shared, mutable, and produced by real pipeline
runs. A test that asserts against it is not testing code — it is testing whatever the last
run happened to leave behind (that is exactly how the old
``test_constraint_audit_is_not_header_only`` became run-order dependent).

Every pipeline test in this suite therefore writes into ``tmp_path``. This module makes that
contract explicit in two ways:

  * it runs the real phases end-to-end into a temporary root and asserts the required
    delivery artifacts are produced *there* (the deliverable contract, not a snapshot of
    someone's last run);
  * it takes a checksum snapshot of the shared ``outputs/`` tree before and after the run and
    asserts nothing changed. The snapshot is a guard — it is never a source of expected
    values, so the assertion does not depend on what the tree contains.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

from src.validation.audit import write_constraint_audit, write_validation_checks
from src.validation.loader import load_shipping
from src.validation.validator import validate_assignment
from tests.phase2_fixtures import (
    REQUIRED_ARTIFACTS,
    produce_delivery_artifacts,
    write_tiny_dataset,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SHARED_OUTPUTS = PROJECT_ROOT / "outputs"


def tree_fingerprint(root: Path) -> dict[str, tuple[int, int, str]]:
    """Relative path -> (size, mtime_ns, sha256) for every file under ``root``."""
    if not root.exists():
        return {}
    fingerprint = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        stat = path.stat()
        fingerprint[str(path.relative_to(root))] = (stat.st_size, stat.st_mtime_ns, digest)
    return fingerprint


def test_required_delivery_artifacts_are_produced_by_the_real_pipeline(tmp_path):
    processed = tmp_path / "processed"
    write_tiny_dataset(processed, baseline="feasible")
    root = tmp_path / "outputs"

    produce_delivery_artifacts(processed, root)

    for relative in REQUIRED_ARTIFACTS:
        path = root / relative
        assert path.is_file(), f"missing required artifact: {relative}"
        assert path.stat().st_size > 0, f"empty required artifact: {relative}"
    summary = json.loads((root / "optimized" / "optimization_summary.json").read_text())
    assert summary["execution_status"] == "OK"
    assert summary["feasibility_status"] == "FEASIBLE"


def test_pipeline_run_does_not_touch_the_shared_outputs_tree(tmp_path):
    processed = tmp_path / "processed"
    write_tiny_dataset(processed, baseline="feasible")

    before = tree_fingerprint(SHARED_OUTPUTS)
    root = tmp_path / "outputs"
    produce_delivery_artifacts(processed, root)
    after = tree_fingerprint(SHARED_OUTPUTS)

    assert before == after, (
        "the pipeline wrote into the shared outputs/ tree while running with an explicit "
        f"output root; added/changed: {sorted(set(after) - set(before))}"
    )


def test_every_produced_file_lives_under_the_given_output_root(tmp_path):
    processed = tmp_path / "processed"
    write_tiny_dataset(processed, baseline="feasible")
    root = tmp_path / "outputs"

    produce_delivery_artifacts(processed, root)

    produced = sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())
    assert produced, "the run must produce artifacts"
    assert all((root / relative).is_file() for relative in produced)
    # Nothing was written next to the fixture or in the current working directory.
    assert not [p for p in processed.rglob("*") if p.is_file() and p.suffix == ".json"]


def test_the_audit_written_for_an_infeasible_layout_is_row_per_violation(tmp_path):
    """Artifact content follows the verdict, in an owned directory."""
    processed = tmp_path / "processed"
    write_tiny_dataset(processed, baseline="beam_overloaded")
    root = tmp_path / "outputs"
    root.mkdir()

    wh, skus, comp, baseline, inventory = load_shipping(processed)
    result = validate_assignment(baseline, skus, wh, comp, inventory)
    assert not result.is_feasible
    write_constraint_audit(baseline, result, root / "constraint_audit.csv")
    write_validation_checks(result, root / "validation_checks_baseline.csv")

    audit = pd.read_csv(root / "constraint_audit.csv")
    assert len(audit) == len(result.violations) > 0
    assert set(audit["passed"].astype(str).str.lower()) == {"false"}
    assert (audit["rule_id"].astype(str).str.len() > 0).all()

    checks = pd.read_csv(root / "validation_checks_baseline.csv")
    assert {"rule_id", "observed", "limit"}.issubset(checks.columns)
    assert len(checks) == result.checks_run
    failed = checks[~checks["passed"].astype(bool)]
    assert len(failed) == len(result.violations)
