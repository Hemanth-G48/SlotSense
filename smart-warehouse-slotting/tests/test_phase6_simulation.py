"""Phase 6 simulation-validity tests with hand-calculated expected values.

These deliberately do not call the production routing or metric functions to derive the
expected answer. Each fixture states the expected distance, pick count and cycle time, then
checks the simulator against that arithmetic.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.simulation.simulator import SimulationConfig, simulate_layout, summarize


def _items(rows):
    return pd.DataFrame(rows, columns=["order_id", "sku_id", "quantity"])


def test_two_stops_route_cycle_is_hand_calculated():
    # depot->L1 = 5, L1->L2 = 10, L2->depot = 6, so the tour is 21 m.
    items = _items([("O1", "S1", 1), ("O1", "S2", 1)])
    slotting = {"S1": ["L1"], "S2": ["L2"]}
    dist = {("L1", "L2"): 10.0, ("L2", "L1"): 10.0}
    depot = {"L1": 5.0, "L2": 6.0}
    cfg = SimulationConfig(batch_size=5, routing_strategy="nearest_neighbor", pick_time_basis="order_line")
    result = simulate_layout(items, slotting, dist, depot, cfg, "DEPOT")[0]

    expected_distance = 5.0 + 10.0 + 6.0
    expected_travel_time = expected_distance / 1.3
    expected_cycle = expected_travel_time + 2 * 8.0 + 10.0

    assert result.distance_m == pytest.approx(expected_distance)
    assert sum(result.legs) == pytest.approx(expected_distance)
    assert result.travel_time_sec == pytest.approx(expected_travel_time)
    assert result.pick_time_sec == pytest.approx(16.0)
    assert result.cycle_time_sec == pytest.approx(expected_cycle)
    assert result.n_pick_lines == 2
    assert result.n_pick_stops == 2


def test_three_lines_at_one_bin_hand_calculated():
    items = _items([("O1", "S1", 1), ("O2", "S1", 1), ("O3", "S1", 1)])
    slotting = {"S1": ["L1"]}
    depot = {"L1": 5.0}

    line = simulate_layout(
        items, slotting, {}, depot,
        SimulationConfig(pick_time_basis="order_line"), "DEPOT",
    )[0]
    stop = simulate_layout(
        items, slotting, {}, depot,
        SimulationConfig(pick_time_basis="stop"), "DEPOT",
    )[0]

    # One stop, so the tour is depot->L1->depot = 10 m.
    assert line.distance_m == stop.distance_m == pytest.approx(10.0)
    assert line.pick_time_sec == pytest.approx(24.0)
    assert stop.pick_time_sec == pytest.approx(8.0)
    assert line.n_pick_lines == stop.n_pick_lines == 3
    assert line.n_pick_stops == stop.n_pick_stops == 1
    assert line.cycle_time_sec - stop.cycle_time_sec == pytest.approx(16.0)


def test_summary_throughput_is_orders_over_cycle_hours():
    items = _items([("O1", "S1", 1), ("O2", "S2", 1)])
    slotting = {"S1": ["L1"], "S2": ["L2"]}
    dist = {("L1", "L2"): 10.0, ("L2", "L1"): 10.0}
    depot = {"L1": 5.0, "L2": 6.0}
    cfg = SimulationConfig(batch_size=5, pick_time_basis="order_line")
    results = simulate_layout(items, slotting, dist, depot, cfg, "DEPOT")
    summary = summarize(results, cfg)

    expected_cycle = (21.0 / 1.3) + 16.0 + 10.0
    assert summary["total_route_time_sec"] == pytest.approx(round(expected_cycle, 2))
    assert summary["throughput_orders_per_hr"] == pytest.approx(
        round(2 / (expected_cycle / 3600), 2)
    )
    assert summary["avg_time_per_order_sec"] == pytest.approx(round(expected_cycle / 2, 2))


def test_missing_assignment_is_not_silently_priced_as_travel():
    # S2 has no bin. The batch still has two order lines, but only one stop.
    items = _items([("O1", "S1", 1), ("O1", "S2", 1)])
    slotting = {"S1": ["L1"]}
    cfg = SimulationConfig(batch_size=5, pick_time_basis="order_line")
    result = simulate_layout(items, slotting, {}, {"L1": 5.0}, cfg, "DEPOT")[0]
    assert result.n_pick_lines == 2
    assert result.n_pick_stops == 1
    assert result.distance_m == pytest.approx(10.0)
    # This is why the pipeline's assignment-completeness gate must run before publication:
    # a missing assignment produces a pick line with no corresponding stop/travel.
    assert result.n_pick_lines > result.n_pick_stops


def test_empty_workload_has_zero_totals_and_a_basis():
    cfg = SimulationConfig(pick_time_basis="stop")
    summary = summarize([], cfg)
    assert summary["n_batches"] == 0
    assert summary["total_distance_m"] == 0.0
    assert summary["total_route_time_sec"] == 0.0
    assert summary["throughput_orders_per_hr"] == 0.0
    assert summary["pick_time_basis"] == "stop"
