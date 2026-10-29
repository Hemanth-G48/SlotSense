"""Phase-6 tests: aisle-network routing, fair comparison, metrics, reproducibility."""

import json
import math
import os
from pathlib import Path

import pandas as pd
import pytest

from src.models.config import Config
from src.optimization.pipeline import run_phase5
from src.routing.graph import (
    NetworkGraph,
    build_graph,
    depot_distance_map,
    find_depot_node,
    location_distance_map,
)
from src.routing.heuristics import nearest_neighbor
from src.simulation.pipeline import run_phase6
from src.simulation.simulator import build_batches

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROCESSED = Path(
    os.environ.get("DATASET_DIR", PROJECT_ROOT.parent / "dataset" / "processed")
).resolve()


@pytest.fixture(scope="module")
def evaluation(tmp_path_factory):
    if not PROCESSED.exists():
        pytest.skip("canonical dataset not generated")
    base = tmp_path_factory.mktemp("eval")
    cfg = Config.from_json(PROJECT_ROOT / "configs" / "benchmark.json")
    run_phase5(PROCESSED, cfg, base / "optimized")
    result = run_phase6(
        PROCESSED,
        scenario="A",
        out=base / "evaluation",
        optimized_path=base / "optimized" / "optimized_assignments.csv",
    )
    return base / "evaluation", result


def test_routing_math_small_graph():
    g = NetworkGraph()
    g.add_undirected("DEPOT", "L1", 5.0)
    g.add_undirected("DEPOT", "L2", 6.0)
    g.add_undirected("L1", "L2", 2.0)
    assert g.shortest("DEPOT", "L2") == pytest.approx(6.0)
    dist = g.distances_from("DEPOT")
    assert dist["L2"] == pytest.approx(6.0)
    location_dist = location_distance_map(g, ["L1", "L2"])
    assert location_dist.get(("L1", "L2")) == pytest.approx(2.0)
    route, dist_sum = nearest_neighbor(["L1", "L2"], location_dist, dist)
    # depot -> L1 (5) -> L2 (2) -> depot (6) = 13
    assert dist_sum == pytest.approx(13.0)
    assert route[0] == "DEPOT" and route[-1] == "DEPOT"


def test_canonical_graph_connected():
    if not PROCESSED.exists():
        pytest.skip("canonical dataset not generated")
    locs = pd.read_csv(PROCESSED / "locations.csv")
    g = build_graph(PROCESSED / "location_graph.csv")
    depot = find_depot_node(g)
    assert depot is not None
    dist = depot_distance_map(g, depot)
    assert all(dist.get(lid, math.inf) != math.inf for lid in locs["location_id"])
    assert any(dist[lid] > 0 for lid in locs["location_id"])


def test_fair_comparison_identical_workload(evaluation):
    out, result = evaluation
    routes = pd.read_csv(out / "pick_routes.csv")
    base_routes = routes[routes["layout"] == "baseline"]
    opt_routes = routes[routes["layout"] == "optimized"]
    # Same number of batches + orders (identical workload)
    assert len(base_routes) == len(opt_routes)
    assert set(base_routes["batch_id"]) == set(opt_routes["batch_id"])
    assert result["notes"]["identical_orders_geometry_routing"] is True
    assert result["notes"]["same_inventory_units"] == result["inventory_units"]


def test_optimized_feasible_and_better(evaluation):
    """The evaluation must be a valid comparison or an explicit block — never both.

    On this dataset the baseline is infeasible (Phase 1: 1,071 CAT-01 violations at the
    configured 10 m radius), so the gate refuses to publish a comparison. What this test pins:

      * ``comparison_valid`` is true exactly when BOTH layouts pass independent validation;
      * a blocked evaluation publishes no comparison and labels every metric diagnostic-only;
      * the optimized layout itself must be valid — a blocked baseline may not be used as
        cover for an invalid answer;
      * when the comparison is valid, the published improvement holds.
    """
    out, result = evaluation
    feasibility = result["feasibility"]
    both_feasible = (
        feasibility["baseline"]["is_feasible"] and feasibility["optimized"]["is_feasible"]
    )

    # -- the gate invariant, asserted unconditionally -------------------------
    assert result["comparison_valid"] is both_feasible
    assert (result["evaluation_status"] == "OK") is both_feasible
    assert (result["evaluation_status"] == "BLOCKED_INFEASIBLE_LAYOUT") is (not both_feasible)
    assert result["blocked_layouts"] == [
        layout for layout in ("baseline", "optimized") if not feasibility[layout]["is_feasible"]
    ]

    # -- the optimized layout must be valid in its own right ------------------
    assert feasibility["optimized"]["is_feasible"] is True, (
        f"optimized layout has violations: {feasibility['optimized']['violations_by_rule']}"
    )
    assert result["optimized"]["constraint_violations"] == 0
    assert result["optimized"]["assignment_feasibility_pct"] == 100.0

    if both_feasible:
        assert result["diagnostic_only"] is False
        assert result["comparison"]
        assert result["baseline"]["constraint_violations"] == 0
        assert (
            result["optimized"]["total_travel_distance_m"]
            < result["baseline"]["total_travel_distance_m"]
        )
        # Both layouts store the same inventory, so cube utilization must match exactly.
        assert (
            result["optimized"]["cube_utilization_pct"]
            == result["baseline"]["cube_utilization_pct"]
        )
    else:
        assert result["comparison"] == []
        assert result["diagnostic_only"] is True
        assert result["diagnostic_comparison"]
        assert all(row["diagnostic_only"] for row in result["diagnostic_comparison"])
        for layout in result["blocked_layouts"]:
            assert feasibility[layout]["n_violations"] > 0
            assert feasibility[layout]["violations_by_rule"]
        # Metrics are still computed for diagnosis, but they are labelled as such.
        diagnostic = {row["metric"]: row for row in result["diagnostic_comparison"]}
        assert "total_travel_distance_m" in diagnostic


def test_metrics_output(evaluation):
    out, result = evaluation
    metrics = pd.read_csv(out / "optimization_metrics.csv")
    assert {"metric", "baseline", "optimized", "absolute_diff", "percent_change"}.issubset(metrics.columns)
    summary = json.loads((out / "evaluation_summary.json").read_text())
    assert summary["notes"]["identical_orders_geometry_routing"] is True


def test_batches_respect_size():
    oi = pd.DataFrame({"order_id": ["O1", "O1", "O2", "O2", "O3", "O3", "O4"], "sku_id": ["a", "b", "c", "d", "e", "f", "g"], "quantity": [1] * 7})
    batches = build_batches(oi, batch_size=2)
    assert len(batches) == 2  # O1,O2 | O3,O4
