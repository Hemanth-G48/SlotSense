"""Phase 4 tests: fairness identity, factorial effects, headroom, diagnostics, routing."""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from src.evaluation.diagnostics import diagnose_validation
from src.evaluation.factorial import effect_table, metric_effects
from src.evaluation.fairness import fairness_checks, workload_identity
from src.evaluation.headroom import structural_headroom
from src.routing.heuristics import ROUTING_STRATEGIES, route_legs
from src.simulation.pipeline import run_phase6
from src.simulation.simulator import SimulationConfig, build_batches, simulate_layout
from tests.phase2_fixtures import write_tiny_dataset


# ---------------------------------------------------------------- workload identity

def test_workload_identity_is_deterministic_and_order_independent():
    frame = pd.DataFrame(
        [("O1", "S1", 2), ("O2", "S2", 1)], columns=["order_id", "sku_id", "quantity"]
    )
    shuffled = frame.iloc[::-1].reset_index(drop=True)
    a = workload_identity(frame, "A")
    b = workload_identity(shuffled, "A")
    assert a["sha256"] == b["sha256"]
    assert a["n_orders"] == 2
    assert a["n_lines"] == 2
    assert a["n_units"] == 3
    assert a["n_skus"] == 2


def test_workload_identity_changes_when_a_quantity_changes():
    frame = pd.DataFrame([("O1", "S1", 2)], columns=["order_id", "sku_id", "quantity"])
    changed = frame.copy()
    changed.loc[0, "quantity"] = 3
    assert workload_identity(frame)["sha256"] != workload_identity(changed)["sha256"]


# ---------------------------------------------------------------- fairness

def _metrics(**overrides):
    base = {
        "total_travel_distance_m": 100.0,
        "total_route_time_sec": 50.0,
        "total_orders": 10,
        "valid_assignments": 4,
        "required_assignments": 4,
        "assignment_feasibility_pct": 100.0,
    }
    base.update(overrides)
    return base


def _fair(**overrides):
    kwargs = dict(
        workload={"workload_id": "wl_x"},
        baseline_metrics=_metrics(),
        optimized_metrics=_metrics(total_travel_distance_m=80.0, total_route_time_sec=40.0),
        baseline_feasible=True,
        optimized_feasible=True,
        inventory_units=100,
        routing_strategy="nearest_neighbor",
        batch_size=5,
        gate_blocked=False,
        blocked_layouts=[],
    )
    kwargs.update(overrides)
    return fairness_checks(**kwargs)


def test_fair_comparison_is_publishable_when_all_conditions_hold():
    checks = _fair()
    assert checks["publishable"] is True
    assert checks["same_workload"] is True
    assert all(checks["denominators"].values())


def test_zero_travel_denominator_blocks_publication():
    checks = _fair(baseline_metrics=_metrics(total_travel_distance_m=0.0))
    assert checks["publishable"] is False
    assert checks["denominators"]["baseline_travel_positive"] is False


def test_incomplete_assignment_blocks_publication():
    checks = _fair(optimized_metrics=_metrics(valid_assignments=3, required_assignments=4))
    assert checks["publishable"] is False
    assert checks["optimized_assignment_complete"] is False


def test_infeasible_layout_blocks_publication():
    checks = _fair(optimized_feasible=False)
    assert checks["publishable"] is False


# ---------------------------------------------------------------- factorial

def test_factorial_effects_are_hand_calculated():
    """10/20/30/60: A effect 30, B effect 20, interaction 20."""
    values = {
        ("base", "p1"): 10.0,
        ("base", "p2"): 20.0,
        ("opt", "p1"): 30.0,
        ("opt", "p2"): 60.0,
    }
    out = effect_table(values, ("base", "opt"), ("p1", "p2"))
    assert out["factor_a_effect"] == pytest.approx(30.0)
    assert out["factor_b_effect"] == pytest.approx(20.0)
    assert out["interaction"] == pytest.approx(20.0)
    assert out["factor_a_effect_pct"] == pytest.approx(300.0)


def test_factorial_rejects_a_missing_cell():
    with pytest.raises(ValueError):
        effect_table({("a0", "b0"): 1.0}, ("a0", "a1"), ("b0", "b1"))


def test_metric_effects_marks_a_missing_metric_unavailable():
    cells = {
        "a0|b0": {"travel": 10.0},
        "a0|b1": {"travel": 20.0},
        "a1|b0": {"travel": 30.0},
        "a1|b1": {"travel": 60.0},
    }
    out = metric_effects(
        cells, a_levels=("a0", "a1"), b_levels=("b0", "b1"),
        metrics={"travel": {"unit": "m"}, "missing": {"unit": "m"}},
    )
    assert out["travel"]["factor_a_effect"] == pytest.approx(30.0)
    assert out["missing"]["status"] == "unavailable"


# ---------------------------------------------------------------- headroom

class _Check:
    def __init__(self, rule_id, observed, limit, location_id="L1", sku_id="S1", passed=False):
        self.rule_id = rule_id
        self.observed = observed
        self.limit = limit
        self.location_id = location_id
        self.sku_id = sku_id
        self.passed = passed
        self.explanation = "fixture"


def test_headroom_reports_max_and_near_limit_share():
    result = SimpleNamespace(
        checks=[
            _Check("LD-01", 80, 100, "L1"),
            _Check("LD-01", 95, 100, "L2"),
            _Check("LD-01", 100, 100, "L3"),
            _Check("VD-01", 50, 200, "L1"),
        ]
    )
    out = structural_headroom(result)
    weight = out["scopes"]["bin_weight"]
    assert weight["max_utilization_pct"] == pytest.approx(100.0)
    assert weight["pct_over_95"] == pytest.approx(100.0 * 2 / 3, rel=1e-3)
    assert weight["limiting"]["location_id"] == "L3"
    assert out["scopes"]["bin_volume"]["max_utilization_pct"] == pytest.approx(25.0)
    assert out["limiting_scope"]["rule_id"] == "LD-01"


def test_headroom_does_not_invent_a_scope_with_no_checks():
    out = structural_headroom(SimpleNamespace(checks=[]))
    assert out["scopes"]["beam_load"]["status"] == "unavailable"
    assert out["max_utilization_pct"] is None


# ---------------------------------------------------------------- diagnostics

class _Violation:
    def __init__(self, rule_id="SL-02", sku_id="S1", location_id="R5-3-1", severity="high"):
        self.rule_id = rule_id
        self.rule_name = "beam capacity"
        self.sku_id = sku_id
        self.location_id = location_id
        self.severity = severity
        self.reason = "beam 190 kg > 180 kg"
        self.pair = None


def test_diagnose_validation_maps_category_and_observed_limit():
    result = SimpleNamespace(
        violations=[_Violation()],
        checks=[_Check("SL-02", 190, 180, "R5-3-1")],
    )
    out = diagnose_validation(result, "optimized")
    assert out["publishable"] is False
    assert out["blocks_publication"] is True
    assert out["failure_categories"] == {"beam_load": 1}
    row = out["violations"][0]
    assert row["observed"] == 190
    assert row["limit"] == 180
    assert row["category"] == "beam_load"


def test_diagnose_feasible_layout_is_publishable_with_no_failures():
    out = diagnose_validation(SimpleNamespace(violations=[], checks=[]), "baseline")
    assert out["publishable"] is True
    assert out["failure_categories"] == {}
    assert out["n_violations"] == 0


# ---------------------------------------------------------------- routing policies

def test_both_supported_policies_return_a_depot_tour_over_the_same_stops():
    dist = {("L1", "L2"): 10.0, ("L1", "L3"): 20.0, ("L2", "L3"): 5.0}
    depot_dist = {"L1": 7.0, "L2": 8.0, "L3": 9.0}
    stops = ["L2", "L1", "L3"]
    for name in ROUTING_STRATEGIES:
        route, distance = ROUTING_STRATEGIES[name](stops, dist, depot_dist, "DEPOT")
        assert route[0] == "DEPOT" and route[-1] == "DEPOT"
        assert set(route[1:-1]) == set(stops)
        assert distance == pytest.approx(sum(route_legs(route, dist, depot_dist, "DEPOT")))


def test_s_shape_visits_stops_in_node_order():
    dist = {("L1", "L2"): 1.0, ("L1", "L3"): 1.0, ("L2", "L3"): 1.0}
    depot_dist = {"L1": 1.0, "L2": 1.0, "L3": 1.0}
    route, _ = ROUTING_STRATEGIES["s_shape"](["L3", "L1", "L2"], dist, depot_dist, "DEPOT")
    assert route == ["DEPOT", "L1", "L2", "L3", "DEPOT"]


def test_simulate_layout_is_deterministic_and_batches_every_order():
    items = pd.DataFrame(
        [("O1", "S1", 1), ("O2", "S2", 1), ("O3", "S1", 2)],
        columns=["order_id", "sku_id", "quantity"],
    )
    slotting = {"S1": ["L1"], "S2": ["L2"]}
    dist = {("L1", "L2"): 10.0}
    depot_dist = {"L1": 5.0, "L2": 6.0}
    cfg = SimulationConfig(batch_size=5, routing_strategy="nearest_neighbor")
    a = simulate_layout(items, slotting, dist, depot_dist, cfg, "DEPOT")
    b = simulate_layout(items, slotting, dist, depot_dist, cfg, "DEPOT")
    assert [r.distance_m for r in a] == [r.distance_m for r in b]
    assert sum(r.n_orders for r in a) == 3
    assert len(build_batches(items, 5)) == 1


# ---------------------------------------------------------------- end-to-end gate

def test_pipeline_publishes_a_fair_comparison_on_feasible_layouts(tmp_path):
    ds = write_tiny_dataset(tmp_path / "processed", baseline="feasible")
    layout = ds.root / "storage_assignments_baseline.csv"
    result = run_phase6(
        processed=ds.root,
        scenario="A",
        out=tmp_path / "out",
        optimized_path=layout,
        affinity_scenario="C",
        baseline_path=layout,
        baseline_variant="repaired_minimal",
        routing_strategy="nearest_neighbor",
    )
    assert result["evaluation_status"] == "OK"
    assert result["comparison_valid"] is True
    assert result["integrity"]["publishable"] is True
    assert result["workload"]["n_orders"] == 4
    assert result["workload"]["n_lines"] == 4
    assert result["diagnostics"]["optimized"]["status"] == "feasible"
    assert result["headroom"]["optimized"]["max_utilization_pct"] is not None


def test_pipeline_blocks_an_infeasible_layout_and_reports_the_reason(tmp_path):
    ds = write_tiny_dataset(tmp_path / "processed", baseline="beam_overloaded")
    layout = ds.root / "storage_assignments_baseline.csv"
    result = run_phase6(
        processed=ds.root,
        scenario="A",
        out=tmp_path / "out",
        optimized_path=layout,
        affinity_scenario="C",
        baseline_variant="as_supplied",
    )
    assert result["evaluation_status"] == "BLOCKED_INFEASIBLE_LAYOUT"
    assert result["comparison_valid"] is False
    assert result["integrity"]["publishable"] is False
    assert result["comparison"] == []
    diag = result["diagnostics"]["optimized"]
    assert diag["status"] == "rejected"
    assert diag["blocks_publication"] is True
    assert "beam_load" in diag["failure_categories"]


def test_pipeline_rejects_an_unknown_routing_strategy(tmp_path):
    ds = write_tiny_dataset(tmp_path / "processed", baseline="feasible")
    layout = ds.root / "storage_assignments_baseline.csv"
    with pytest.raises(ValueError):
        run_phase6(
            processed=ds.root, scenario="A", out=tmp_path / "out",
            optimized_path=layout, baseline_path=layout,
            baseline_variant="repaired_minimal", routing_strategy="traveling_salesman",
        )


# ---------------------------------------------------------------- regimes

def test_regime_profile_reconciles_with_the_workload(tmp_path):
    from src.experiments.run_phase4 import _regime_profile

    ds = write_tiny_dataset(tmp_path / "processed", baseline="feasible")
    profile = _regime_profile(ds.root, "A")
    assert profile["scenario"] == "A"
    assert profile["orders"] == 4
    assert profile["lines"] == 4
    assert profile["units"] == 5
    assert profile["skus_with_demand"] == 4
    assert profile["abc_a_skus"] == 2
    assert profile["top10pct_unit_share"] == pytest.approx(40.0)
