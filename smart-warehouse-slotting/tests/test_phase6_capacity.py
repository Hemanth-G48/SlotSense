"""Phase 6 capacity-perturbation test: the frozen layout is feasible, one unit is not."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = Path(
    os.environ.get("PHASE6_CAPACITY", ROOT / "outputs" / "phase6" / "capacity_perturbation.json")
).resolve()


pytestmark = pytest.mark.skipif(not ARTIFACT.exists(), reason="capacity audit not generated")


def test_capacity_audit_records_a_feasible_baseline():
    data = json.loads(ARTIFACT.read_text())
    assert data["baseline"]["feasible"] is True
    assert data["baseline"]["n_violations"] == 0
    assert data["baseline"]["units"] == 6375


def test_one_unit_perturbations_are_rejected():
    data = json.loads(ARTIFACT.read_text())
    cases = {c["scope"]: c for c in data["perturbations"]}
    assert set(cases) == {"bin_weight", "bin_volume"}
    for scope, case in cases.items():
        assert case["inventory_only"]["feasible"] is False, scope
        assert case["inventory_plus_layout"]["feasible"] is False, scope
        assert case["inventory_plus_layout"]["rules"], scope
    assert "LD-01" in cases["bin_weight"]["inventory_plus_layout"]["rules"]
    assert "VD-01" in cases["bin_volume"]["inventory_plus_layout"]["rules"]


def test_capacity_artifact_pins_the_frozen_layout_hash():
    data = json.loads(ARTIFACT.read_text())
    assert data["inputs"]["optimized_layout_sha256"].startswith("cafa55e805e8")
