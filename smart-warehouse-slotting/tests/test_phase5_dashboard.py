"""Phase 5 dashboard-contract tests: pass-through, labels, missing/blocked states."""

from __future__ import annotations

import copy

import pandas as pd
import pytest

from app.dashboard_data import load_all
from app.phase5_views import phase3_view, phase4_view


@pytest.fixture(scope="module")
def contracts():
    data = load_all()
    return data.get("phase3") or {}, data.get("phase4") or {}


def test_phase3_contract_loads_and_publishes_required_fields(contracts):
    p3, _ = contracts
    assert p3.get("status") == "ok"
    for key in ("cells", "effects", "split", "replenishment", "sweep", "feasibility"):
        assert key in p3


def test_phase3_view_passes_values_through_without_recomputing(contracts):
    p3, _ = contracts
    view = phase3_view(p3)
    assert view["available"] is True
    a1 = view["cells"][view["cells"]["Cell"] == "A1"].iloc[0]
    assert a1["Travel (m, line metric)"] == p3["cells"][0]["demand_weighted_depot_distance"]
    assert a1["Lines priced"] == p3["cells"][0]["denominator_lines"]
    placement = view["effects"][view["effects"]["Effect"] == "Placement"].iloc[0]
    assert placement["Value (m)"] == p3["effects"]["factor_a_effect_m"]
    assert placement["Percent of A1"] == p3["effects"]["factor_a_effect_pct_of_reference"]


def test_phase3_view_reflects_mutated_contract_instead_of_recomputing(contracts):
    p3, _ = contracts
    mutated = copy.deepcopy(p3)
    mutated["cells"][0]["demand_weighted_depot_distance"] = 123456.789
    view = phase3_view(mutated)
    assert view["cells"].iloc[0]["Travel (m, line metric)"] == 123456.789


def test_phase4_contract_loads_and_view_passes_values_through(contracts):
    _, p4 = contracts
    assert p4.get("status") == "ok"
    view = phase4_view(p4)
    b1 = view["cells"][view["cells"]["Cell"] == "B1"].iloc[0]
    source = next(c for c in p4["cells"] if c["cell_id"] == "B1")
    assert b1["Travel (m)"] == source["total_travel_distance_m"]
    assert b1["Cycle (s)"] == source["total_route_time_sec"]
    assert b1["Throughput (orders/h)"] == source["throughput_orders_per_hr"]
    assert view["verification"]["all_passed"] is True
    assert view["workload_id"].startswith("wl_")


def test_phase4_view_reflects_mutated_contract(contracts):
    _, p4 = contracts
    mutated = copy.deepcopy(p4)
    mutated["cells"][0]["total_travel_distance_m"] = 999999.0
    view = phase4_view(mutated)
    assert view["cells"].iloc[0]["Travel (m)"] == 999999.0


def test_units_and_metric_definitions_are_explicit(contracts):
    p3, p4 = contracts
    v3, v4 = phase3_view(p3), phase4_view(p4)
    assert "Travel (m, line metric)" in v3["cells"].columns
    assert "Coverage (%)" in v3["cells"].columns
    assert "Travel (m)" in v4["cells"].columns
    assert "Cycle (s)" in v4["cells"].columns
    assert "Throughput (orders/h)" in v4["cells"].columns
    assert "Change (%)" in v4["regimes"].columns


def test_missing_contracts_render_as_unavailable_not_zero():
    for view_fn in (phase3_view, phase4_view):
        view = view_fn(None)
        assert view["available"] is False
        assert view["cells"].empty


def test_blocked_comparison_is_flagged(contracts):
    p3, p4 = contracts
    b3 = copy.deepcopy(p3)
    b3["feasibility"]["publishable_comparison"] = False
    assert phase3_view(b3)["blocked"] is True
    b4 = copy.deepcopy(p4)
    b4["cells"][0]["feasible"] = False
    assert phase4_view(b4)["blocked"] is True


def test_headroom_rows_are_not_duplicated_per_policy(contracts):
    _, p4 = contracts
    view = phase4_view(p4)
    if not view["headroom"].empty:
        keys = list(zip(view["headroom"]["Layout"], view["headroom"]["Scope"]))
        assert len(keys) == len(set(keys))


def test_phase3_secondary_pick_rule_is_separate_from_primary_effects(contracts):
    p3, _ = contracts
    view = phase3_view(p3)
    assert not view["effects"].empty
    assert not view["pick_rule"].empty
    assert set(view["effects"]["Effect"]) == {"Placement", "Fragmentation policy", "Interaction (DiD)"}
    assert set(view["pick_rule"]["Effect"]) == {"Layout effect", "Pick-rule effect", "Interaction (DiD)"}


def test_streamlit_app_renders_experiment_tabs_without_exception():
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    root = Path(__file__).resolve().parents[1]
    app = AppTest.from_file(root / "app" / "dashboard.py", default_timeout=120).run()
    assert len(app.exception) == 0, [e.message for e in app.exception]
    labels = [t.label for t in app.tabs]
    assert "Experiments" in labels
    assert "Phase 3 — demand metrics" in labels
    assert "Phase 4 — simulation" in labels
