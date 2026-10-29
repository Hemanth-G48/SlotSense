"""Determinism: the same seed and configuration must reproduce the same layout.

Why it matters for this project: every published number is tied to a specific layout. If two
runs with identical inputs produced different assignments, a reported improvement could not be
reproduced — and a regression could not be told apart from noise.

The pipeline is exercised on the owned tiny fixture under ``tmp_path`` (the canonical
benchmark determinism test remains in ``test_phase5_optimizer``).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.optimization.objective import Objective, build_affinity_penalty
from src.optimization.optimizer import OptimizerConfig, SlottingOptimizer
from src.optimization.pipeline import run_phase5
from src.validation.loader import (
    load_assignments,
    load_compatibility_rules,
    load_inventory,
    load_skus,
    load_warehouse_from_locations,
)
from src.validation.validator import Validator
from tests.phase2_fixtures import (
    assignment_digest,
    assignment_rows,
    tiny_config,
    write_tiny_dataset,
)


def build_optimizer(processed: Path, radius: float = 10.0, seed: int = 42) -> SlottingOptimizer:
    """The same wiring ``run_phase5`` performs, built by hand so two instances can be compared."""
    import pandas as pd

    locations = pd.read_csv(processed / "locations.csv")
    products = pd.read_csv(processed / "products.csv")
    rules = pd.read_csv(processed / "compatibility_rules.csv")
    inventory = pd.read_csv(processed / "inventory.csv")
    baseline = pd.read_csv(processed / "storage_assignments_baseline.csv")
    demand = pd.read_csv(processed / "demand_summary.csv")
    affinity = pd.read_csv(processed / "sku_affinity.csv")

    wh = load_warehouse_from_locations(locations)
    skus = load_skus(products)
    comp = load_compatibility_rules(rules)
    inv = load_inventory(inventory)
    demand_a = demand[demand["scenario_id"] == "A"]
    validator = Validator(skus, wh, comp, inventory=inv, separation_radius_m=radius)
    return SlottingOptimizer(
        warehouse=wh,
        skus=skus,
        abc_classes=dict(zip(demand_a["sku_id"], demand_a["abc_class"])),
        validator=validator,
        inventory=inv,
        affinity_penalty=build_affinity_penalty(affinity[affinity["scenario_id"] == "C"]),
        objective=Objective(),
        demand=dict(zip(demand_a["sku_id"], demand_a["demand_frequency"].astype(float))),
        cfg=OptimizerConfig(seed=seed),
        initial_assignments=load_assignments(baseline),
        separation_radius_m=radius,
        compatibility_rules=comp,
    )


@pytest.mark.parametrize("baseline", ["feasible", "beam_overloaded", "feasible_high_stock"])
def test_same_seed_and_config_produce_the_same_layout(tmp_path, baseline):
    processed = tmp_path / "processed"
    write_tiny_dataset(processed, baseline=baseline)
    config = tiny_config(10.0, seed=42)

    first = run_phase5(processed, config, tmp_path / "run1")
    second = run_phase5(processed, config, tmp_path / "run2")

    rows1 = assignment_rows(tmp_path / "run1" / "optimized_assignments.csv")
    rows2 = assignment_rows(tmp_path / "run2" / "optimized_assignments.csv")
    assert assignment_digest(rows1) == assignment_digest(rows2)

    assert first["final_objective"] == second["final_objective"]
    assert first["n_assignments"] == second["n_assignments"]
    assert first["feasibility_status"] == second["feasibility_status"]
    assert first["violations_by_rule"] == second["violations_by_rule"]
    assert first["repair"]["moves_accepted"] == second["repair"]["moves_accepted"]


def test_two_optimizer_instances_are_independent_and_reproducible(tmp_path):
    """No module-level RNG state: a second instance starts from the same seeded stream."""
    processed = tmp_path / "processed"
    write_tiny_dataset(processed, baseline="beam_overloaded")

    greedy_one = build_optimizer(processed).greedy_starter()
    greedy_two = build_optimizer(processed).greedy_starter()
    g1 = assignment_digest([(a.sku_id, a.location_id, a.assigned_quantity) for a in greedy_one])
    g2 = assignment_digest([(a.sku_id, a.location_id, a.assigned_quantity) for a in greedy_two])
    assert g1 == g2

    layout_one, _log_one = build_optimizer(processed).optimize()
    layout_two, _log_two = build_optimizer(processed).optimize()
    r1 = assignment_digest([(a.sku_id, a.location_id, a.assigned_quantity) for a in layout_one])
    r2 = assignment_digest([(a.sku_id, a.location_id, a.assigned_quantity) for a in layout_two])
    assert r1 == r2


def test_repeated_runs_into_the_same_output_directory_are_identical(tmp_path):
    processed = tmp_path / "processed"
    write_tiny_dataset(processed, baseline="feasible")
    out = tmp_path / "optimized"

    run_phase5(processed, tiny_config(), out)
    first = assignment_digest(assignment_rows(out / "optimized_assignments.csv"))
    run_phase5(processed, tiny_config(), out)
    second = assignment_digest(assignment_rows(out / "optimized_assignments.csv"))

    assert first == second


def test_config_radius_is_part_of_the_identity_of_a_run(tmp_path):
    """Different configured radii are different runs; the same radius reproduces."""
    processed = tmp_path / "processed"
    write_tiny_dataset(processed, baseline="feasible")

    a = run_phase5(processed, tiny_config(10.0), tmp_path / "r10a")
    b = run_phase5(processed, tiny_config(10.0), tmp_path / "r10b")
    c = run_phase5(processed, tiny_config(11.0), tmp_path / "r11")

    assert a["separation_radius_m"] == b["separation_radius_m"] == 10.0
    assert c["separation_radius_m"] == 11.0
    assert a["feasibility_status"] == b["feasibility_status"] == "FEASIBLE"
    assert c["feasibility_status"] == "INFEASIBLE"
