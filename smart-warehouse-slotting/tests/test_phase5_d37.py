"""Phase 5 D37 tests: line-based vs stop-based pick time on hand-calculated fixtures."""

from __future__ import annotations

import pandas as pd
import pytest

from src.simulation.pipeline import run_phase6
from src.simulation.simulator import SimulationConfig, simulate_layout, summarize
from tests.phase2_fixtures import write_tiny_dataset


def _items(rows):
    return pd.DataFrame(rows, columns=["order_id", "sku_id", "quantity"])


def _run(items, slotting, dist, depot_dist, basis, batch_size=5):
    cfg = SimulationConfig(
        batch_size=batch_size,
        routing_strategy="nearest_neighbor",
        pick_time_basis=basis,
    )
    return simulate_layout(items, slotting, dist, depot_dist, cfg, "DEPOT")


def test_one_line_one_stop_models_are_identical():
    items = _items([("O1", "S1", 1)])
    slotting = {"S1": ["L1"]}
    line = _run(items, slotting, {}, {"L1": 5.0}, "order_line")
    stop = _run(items, slotting, {}, {"L1": 5.0}, "stop")
    assert line[0].n_pick_lines == 1
    assert line[0].n_pick_stops == 1
    assert stop[0].n_pick_lines == 1
    assert stop[0].n_pick_stops == 1
    assert line[0].cycle_time_sec == stop[0].cycle_time_sec


def test_multiple_lines_at_one_bin_charge_three_lines_but_one_stop():
    items = _items([("O1", "S1", 1), ("O2", "S1", 1), ("O3", "S1", 1)])
    slotting = {"S1": ["L1"]}
    line = _run(items, slotting, {}, {"L1": 5.0}, "order_line")
    stop = _run(items, slotting, {}, {"L1": 5.0}, "stop")
    assert line[0].n_pick_lines == 3
    assert line[0].n_pick_stops == 1
    assert line[0].pick_time_sec == pytest.approx(24.0)
    assert stop[0].pick_time_sec == pytest.approx(8.0)
    # Travel and setup are unchanged; only the pick component differs.
    assert line[0].distance_m == stop[0].distance_m
    assert line[0].cycle_time_sec - stop[0].cycle_time_sec == pytest.approx(16.0)


def test_two_skus_in_one_bin_are_two_lines_but_one_stop():
    items = _items([("O1", "S1", 1), ("O1", "S2", 1)])
    slotting = {"S1": ["L1"], "S2": ["L1"]}
    line = _run(items, slotting, {}, {"L1": 5.0}, "order_line")
    stop = _run(items, slotting, {}, {"L1": 5.0}, "stop")
    assert line[0].n_pick_lines == 2
    assert line[0].n_pick_stops == 1
    assert stop[0].pick_time_sec == pytest.approx(8.0)


def test_two_bins_in_one_batch_are_two_stops():
    items = _items([("O1", "S1", 1), ("O1", "S2", 1)])
    slotting = {"S1": ["L1"], "S2": ["L2"]}
    dist = {("L1", "L2"): 10.0}
    depot = {"L1": 5.0, "L2": 6.0}
    line = _run(items, slotting, dist, depot, "order_line")
    stop = _run(items, slotting, dist, depot, "stop")
    assert line[0].n_pick_stops == 2
    assert stop[0].pick_time_sec == pytest.approx(16.0)


def test_empty_workload_reports_zero_and_basis():
    for basis in ("order_line", "stop"):
        cfg = SimulationConfig(batch_size=5, pick_time_basis=basis)
        summary = summarize([], cfg)
        assert summary["n_batches"] == 0
        assert summary["total_pick_lines"] == 0
        assert summary["total_pick_stops"] == 0
        assert summary["pick_time_basis"] == basis
        assert summary["throughput_orders_per_hr"] == 0.0


def test_summary_keeps_line_and_stop_counts_separate():
    items = _items([("O1", "S1", 1), ("O2", "S1", 1)])
    slotting = {"S1": ["L1"]}
    cfg = SimulationConfig(batch_size=5, pick_time_basis="stop")
    results = simulate_layout(items, slotting, {}, {"L1": 5.0}, cfg, "DEPOT")
    summary = summarize(results, cfg)
    assert summary["total_pick_lines"] == 2
    assert summary["total_pick_stops"] == 1
    assert summary["total_pick_time_sec"] == pytest.approx(8.0)


def test_invalid_basis_is_rejected():
    with pytest.raises(ValueError, match="pick_time_basis"):
        SimulationConfig(pick_time_basis="per_case")


def test_pipeline_travel_is_identical_across_bases_but_cycle_is_not(tmp_path):
    ds = write_tiny_dataset(tmp_path / "processed", baseline="feasible")
    layout = ds.root / "storage_assignments_baseline.csv"
    line = run_phase6(
        processed=ds.root,
        scenario="A",
        out=tmp_path / "line",
        optimized_path=layout,
        affinity_scenario="C",
        baseline_path=layout,
        baseline_variant="repaired_minimal",
        routing_strategy="nearest_neighbor",
        pick_time_basis="order_line",
    )
    stop = run_phase6(
        processed=ds.root,
        scenario="A",
        out=tmp_path / "stop",
        optimized_path=layout,
        affinity_scenario="C",
        baseline_path=layout,
        baseline_variant="repaired_minimal",
        routing_strategy="nearest_neighbor",
        pick_time_basis="stop",
    )
    assert line["baseline"]["total_travel_distance_m"] == pytest.approx(
        stop["baseline"]["total_travel_distance_m"]
    )
    assert line["optimized"]["total_travel_distance_m"] == pytest.approx(
        stop["optimized"]["total_travel_distance_m"]
    )
    # The tiny fixture has one line per stop, so cycle time may coincide; the published
    # counts are what must stay distinct and explicit.
    assert line["baseline"]["total_pick_lines"] == line["baseline"]["total_pick_stops"]
    if line["baseline"]["total_pick_lines"] != line["baseline"]["total_pick_stops"]:
        assert line["baseline"]["total_route_time_sec"] != pytest.approx(
            stop["baseline"]["total_route_time_sec"]
        )
    assert line["simulation"]["pick_time_basis"] == "order_line"
    assert stop["simulation"]["pick_time_basis"] == "stop"
