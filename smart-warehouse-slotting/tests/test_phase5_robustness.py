"""Phase 5 robustness tests: D37 artifacts, paired seeds, provenance, verifier."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(os.environ.get("PHASE5_DIR", ROOT / "outputs" / "phase5")).resolve()

pytestmark = pytest.mark.skipif(
    not (OUT / "phase5_experiments.json").exists(),
    reason="Phase 5 artifacts not generated in this checkout",
)


@pytest.fixture(scope="module")
def phase5():
    return json.loads((OUT / "phase5_experiments.json").read_text())


def test_d37_travel_is_identical_across_timing_bases(phase5):
    rows = {(r["basis"], r["layout"]): r for r in phase5["d37"]["rows"]}
    for layout in ("baseline", "optimized"):
        assert rows[("order_line", layout)]["total_travel_distance_m"] == pytest.approx(
            rows[("stop", layout)]["total_travel_distance_m"], abs=0.01
        )
        assert rows[("order_line", layout)]["total_pick_lines"] == 5997
        assert rows[("order_line", layout)]["total_pick_stops"] == rows[
            ("stop", layout)
        ]["total_pick_stops"]


def test_d37_stop_model_moves_cycle_time_in_both_directions(phase5):
    rows = {(r["basis"], r["layout"]): r for r in phase5["d37"]["rows"]}
    # Baseline has more stops than lines, so stop charging is more expensive.
    assert rows[("stop", "baseline")]["total_route_time_sec"] > rows[
        ("order_line", "baseline")
    ]["total_route_time_sec"]
    # The optimized layout has fewer stops than lines, so stop charging slightly reduces it.
    assert rows[("stop", "optimized")]["total_route_time_sec"] < rows[
        ("order_line", "optimized")
    ]["total_route_time_sec"]
    assert phase5["d37"]["decision"]["authoritative_default"] == "order_line"


def test_paired_seed_design_and_records(phase5):
    seeds = phase5["paired_seeds"]
    assert seeds["seeds"] == [42, 43, 44, 45, 46]
    assert seeds["design"]["paired_unit"] == "seed"
    assert seeds["summary"]["n_declared"] == 5
    assert seeds["summary"]["n_successful"] == 5
    assert seeds["summary"]["n_failed"] == 0
    assert len({r["layout_sha256"] for r in seeds["records"]}) == 1
    assert seeds["summary"]["unique_layouts"] == 1


def test_paired_seed_metrics_are_feasible_and_identical(phase5):
    records = phase5["paired_seeds"]["records"]
    assert all(r["validation"]["feasible"] for r in records)
    assert all(r["validation"]["inventory_conserved"] for r in records)
    assert all(r["publishable"] for r in records)
    assert {r["optimized"]["total_travel_distance_m"] for r in records} == {234208.0}
    assert phase5["paired_seeds"]["summary"]["paired_delta"]["travel_pct"]["sd"] == 0.0


def test_provenance_records_inputs_configuration_and_outputs(phase5):
    manifest = json.loads((OUT / "provenance.json").read_text())
    for key in ("dataset", "configuration", "run", "outputs", "software"):
        assert key in manifest
    assert manifest["run"]["seeds"]["optimizer_seeds"] == [42, 43, 44, 45, 46]
    assert "deterministic" in manifest["run"]["seeds"]["simulation"]
    assert manifest["phase5"]["d37_default"] == "order_line"
    assert len(manifest["outputs"]) >= 10


def test_independent_verifier_passes():
    from src.evaluation.verify_phase5 import verify

    result = verify(OUT)
    assert result["all_passed"] is True
    assert result["n_failed"] == 0
    assert result["n_checks"] >= 40


def test_no_holdout_refit_or_selection(phase5):
    design = phase5["paired_seeds"]["design"]
    assert design["evaluation"].startswith("same A_HOLDOUT")
    assert "A_FIT" in design["optimized"]
    manifest = json.loads((OUT / "provenance.json").read_text())
    assert "no refit" in " ".join(manifest["run"]["evaluation_protocol"].values())
