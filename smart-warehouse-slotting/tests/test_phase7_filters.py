"""Phase 7 dashboard filter tests: recorded rows only, no synthesized segments."""

from __future__ import annotations

import pandas as pd

from app.phase5_views import filter_frame


def test_filter_all_returns_original_rows():
    df = pd.DataFrame({"Regime": ["A", "B", "C"], "Value": [1, 2, 3]})
    assert len(filter_frame(df, "Regime", "All")) == 3


def test_filter_selects_only_the_recorded_segment():
    df = pd.DataFrame({"Regime": ["A", "B", "C"], "Value": [1, 2, 3]})
    out = filter_frame(df, "Regime", "B")
    assert out["Value"].tolist() == [2]


def test_unknown_segment_returns_empty_not_a_fabricated_row():
    df = pd.DataFrame({"Regime": ["A", "B"], "Value": [1, 2]})
    assert filter_frame(df, "Regime", "D").empty


def test_missing_column_returns_empty():
    df = pd.DataFrame({"Regime": ["A"]})
    assert filter_frame(df, "status", "PASS").empty
