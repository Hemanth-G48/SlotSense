"""Tests for the Phase 3 experiment machinery: 2x2 effects and the fit/holdout split."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from src.experiments.factorial import run_2x2, run_factorial_2x2
from src.experiments.split import build_split, verify_split
from src.experiments.travel import ALL_BINS, QUANTITY_AWARE


def assignments(rows):
    return pd.DataFrame(rows, columns=["sku_id", "location_id", "assigned_quantity"])


def workload(rows):
    return pd.DataFrame(rows, columns=["order_id", "sku_id", "quantity"])


# ---------------------------------------------------------------- 2x2

def test_two_by_two_effects_are_hand_calculated():
    """base has two bins (10 m and 50 m), optimized has one (10 m); 2 lines of qty 3.

    base all_bins : (10+50) x 2 = 120      base qa : 10 x 2 = 20
    opt  all_bins : 10 x 2      = 20       opt  qa : 10 x 2 = 20

    layout effect = mean over rules of (opt - base) = mean(-100, 0)  = -50
    rule effect   = mean over layouts of (all - qa) = mean(100, 0)   =  50
    interaction   = (20 - 120) - (20 - 20)                            = -100
    """
    layouts = {
        "baseline_repaired": assignments([("S1", "L1", 5), ("S1", "L2", 50)]),
        "optimized_fit": assignments([("S1", "L1", 5)]),
    }
    work = workload([("O1", "S1", 3), ("O2", "S1", 3)])
    dist = {"L1": 10.0, "L2": 50.0}

    out = run_2x2(layouts, work, dist, feasibility={"baseline_repaired": True, "optimized_fit": True})

    cells = {(c["layout"], c["pick_rule"]): c["demand_weighted_depot_distance"] for c in out["cells"]}
    assert cells[("baseline_repaired", ALL_BINS)] == pytest.approx(120.0)
    assert cells[("baseline_repaired", QUANTITY_AWARE)] == pytest.approx(20.0)
    assert cells[("optimized_fit", ALL_BINS)] == pytest.approx(20.0)
    assert cells[("optimized_fit", QUANTITY_AWARE)] == pytest.approx(20.0)

    effects = out["effects"]
    assert effects["layout_effect_m"] == pytest.approx(-50.0)
    assert effects["rule_effect_m"] == pytest.approx(50.0)
    assert effects["interaction_m"] == pytest.approx(-100.0)


def test_two_by_two_marks_infeasible_cells_without_dropping_them():
    layouts = {
        "baseline_repaired": assignments([("S1", "L1", 5)]),
        "optimized_fit": assignments([("S1", "L1", 5)]),
    }
    out = run_2x2(
        layouts, workload([("O1", "S1", 1)]), {"L1": 10.0},
        feasibility={"baseline_repaired": True, "optimized_fit": False},
    )
    assert len(out["cells"]) == 4
    assert {c["layout"]: c["feasible"] for c in out["cells"]}["optimized_fit"] is False


def test_two_by_two_requires_exactly_two_layouts():
    with pytest.raises(ValueError):
        run_2x2({"only": assignments([("S1", "L1", 1)])}, workload([]), {})


# ---------------------------------------------------------------- placement x fragmentation

def test_placement_by_fragmentation_effects_are_hand_calculated():
    """Four cells at 10/20/30/60 m.

    A1=(base, as_is)=10  A2=(base, min)=20  B1=(opt, as_is)=30  B2=(opt, min)=60
    factor A = mean(30-10, 60-20) = 30
    factor B = mean(20-10, 60-30) = 20
    interaction = (60-20) - (30-10) = 20
    """
    cells = {
        ("baseline", "as_is"): assignments([("S1", "L1", 10)]),
        ("baseline", "min_bins"): assignments([("S1", "L2", 10)]),
        ("optimized", "as_is"): assignments([("S1", "L3", 10)]),
        ("optimized", "min_bins"): assignments([("S1", "L4", 10)]),
    }
    distances = {"L1": 10.0, "L2": 20.0, "L3": 30.0, "L4": 60.0}
    out = run_factorial_2x2(
        cells,
        workload([("O1", "S1", 5)]),
        distances,
        feasibility={(a, b): True for a, b in cells},
    )

    values = {c["cell_id"]: c["demand_weighted_depot_distance"] for c in out["cells"]}
    assert values == {"A1": 10.0, "A2": 20.0, "B1": 30.0, "B2": 60.0}

    effects = out["effects"]
    assert effects["factor_a_effect_m"] == pytest.approx(30.0)
    assert effects["factor_b_effect_m"] == pytest.approx(20.0)
    assert effects["interaction_m"] == pytest.approx(20.0)
    assert effects["factor_a"] == "placement"
    assert effects["factor_b"] == "fragmentation_policy"


def test_factorial_requires_all_four_cells():
    cells = {
        ("a0", "b0"): assignments([("S1", "L1", 1)]),
        ("a0", "b1"): assignments([("S1", "L1", 1)]),
        ("a1", "b0"): assignments([("S1", "L1", 1)]),
    }
    with pytest.raises(ValueError):
        run_factorial_2x2(cells, workload([("O1", "S1", 1)]), {"L1": 1.0})


def test_factorial_keeps_infeasible_cells_and_flags_them():
    cells = {
        ("a0", "b0"): assignments([("S1", "L1", 1)]),
        ("a0", "b1"): assignments([("S1", "L1", 1)]),
        ("a1", "b0"): assignments([("S1", "L1", 1)]),
        ("a1", "b1"): assignments([("S1", "L1", 1)]),
    }
    feasibility = {("a0", "b0"): True, ("a0", "b1"): True,
                   ("a1", "b0"): False, ("a1", "b1"): True}
    out = run_factorial_2x2(cells, workload([("O1", "S1", 1)]), {"L1": 1.0},
                            feasibility=feasibility)
    assert len(out["cells"]) == 4
    assert {(c["placement"], c["fragmentation_policy"]): c["feasible"] for c in out["cells"]}[
        ("a1", "b0")
    ] is False


# ---------------------------------------------------------------- split

def write_tiny_processed(path: Path, n_orders: int = 10, lines_per_order: int = 2) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    skus = ["S1", "S2", "S3"]
    pd.DataFrame(
        [{"sku_id": s, "product_name": s, "category_id": "C1"} for s in skus]
    ).to_csv(path / "products.csv", index=False)
    orders, items = [], []
    for i in range(n_orders):
        oid = f"O{i:02d}"
        orders.append({
            "order_id": oid, "scenario_id": "A",
            "order_timestamp": f"2025-01-{i + 1:02d}T00:00:00Z",
            "order_status": "completed", "data_source": "synthetic",
            "data_quality_status": "valid",
        })
        for j in range(lines_per_order):
            items.append({"order_id": oid, "sku_id": skus[j % len(skus)],
                          "quantity": 1 + j, "data_source": "synthetic"})
    pd.DataFrame(orders).to_csv(path / "orders.csv", index=False)
    pd.DataFrame(items).to_csv(path / "order_items.csv", index=False)
    return path


def test_split_is_temporal_disjoint_and_reproducible(tmp_path):
    processed = write_tiny_processed(tmp_path / "processed")
    m1 = build_split(processed, tmp_path / "out", name="A70", fraction=0.7)
    checks = verify_split(m1)
    assert checks["all_passed"], checks

    # temporal: every fit order precedes every holdout order
    fit = pd.read_csv(Path(m1["views"]["fit"]["path"]) / "orders.csv")
    hold = pd.read_csv(Path(m1["views"]["holdout"]["path"]) / "orders.csv")
    assert pd.to_datetime(fit["order_timestamp"], utc=True).max() <= pd.to_datetime(
        hold["order_timestamp"], utc=True
    ).min()

    # reproducible: rebuilding yields identical hashes
    m2 = build_split(processed, tmp_path / "out2", name="A70", fraction=0.7)
    assert m1["views"]["fit"]["sha256"] == m2["views"]["fit"]["sha256"]
    assert m1["views"]["holdout"]["sha256"] == m2["views"]["holdout"]["sha256"]


def test_split_recomputes_demand_so_holdout_does_not_leak(tmp_path):
    processed = write_tiny_processed(tmp_path / "processed", n_orders=10)
    m = build_split(processed, tmp_path / "out", name="A70", fraction=0.6)
    fit_demand = pd.read_csv(Path(m["views"]["fit"]["path"]) / "demand_summary.csv")
    hold_demand = pd.read_csv(Path(m["views"]["holdout"]["path"]) / "demand_summary.csv")

    # scenario ids are rewritten per view
    assert set(fit_demand["scenario_id"]) == {"A_FIT"}
    assert set(hold_demand["scenario_id"]) == {"A_HOLDOUT"}

    # fit demand totals equal the fit view's own line quantities, not the whole dataset
    fit_items = pd.read_csv(Path(m["views"]["fit"]["path"]) / "order_items.csv")
    assert int(fit_demand["total_units"].sum()) == int(fit_items["quantity"].sum())
    hold_items = pd.read_csv(Path(m["views"]["holdout"]["path"]) / "order_items.csv")
    assert int(hold_demand["total_units"].sum()) == int(hold_items["quantity"].sum())


def test_split_rejects_degenerate_fractions(tmp_path):
    processed = write_tiny_processed(tmp_path / "processed")
    with pytest.raises(ValueError):
        build_split(processed, tmp_path / "o1", fraction=0.0)
    with pytest.raises(ValueError):
        build_split(processed, tmp_path / "o2", fraction=1.0)


def test_split_manifest_records_method_and_counts(tmp_path):
    processed = write_tiny_processed(tmp_path / "processed")
    m = build_split(processed, tmp_path / "out", name="A70", fraction=0.7)
    on_disk = json.loads(Path(m["manifest_path"]).read_text())
    assert on_disk["method"] == "temporal_order_level"
    assert on_disk["split_unit"] == "order"
    assert on_disk["seed"] is None
    assert on_disk["integrity"]["orders_fit_plus_holdout"] == on_disk["integrity"]["orders_total_input"]
    assert on_disk["integrity"]["lines_fit_plus_holdout"] == on_disk["integrity"]["lines_total_input"]
    assert "line_union_equals_input" in verify_split(m)
