"""Factorial experiments for the slotting benchmark (Phase 3, D22).

Two designs live here, and they answer different questions:

``run_factorial_2x2`` — the **primary** placement x fragmentation experiment.
    Factor A is the placement/layout policy (reference vs alternative). Factor B is
    the **fragmentation policy** applied to that layout (``as_is`` vs ``min_bins``,
    see :mod:`src.experiments.fragmentation`). This is a real manipulation of the
    layout, so its interaction measures whether the placement gain depends on how
    many bins each SKU occupies.

``run_2x2`` — the architecture's **pick-rule sensitivity** design (§11.5).
    Factor A is placement, factor B is the evaluation rule (``all_bins`` vs
    ``quantity_aware``). The layout is held fixed while the rule changes, so this
    isolates how much of a gain is an artefact of charging every bin a SKU occupies.
    It is *not* a fragmentation treatment: the rule changes the accounting, not the
    layout. Kept separate so the two questions are never conflated.

Effect definitions (both designs, outcome Y):
    factor A effect = mean over B of (Y(a1,b) - Y(a0,b))
    factor B effect = mean over A of (Y(a,b1) - Y(a,b0))
    interaction     = (Y(a1,b1) - Y(a0,b1)) - (Y(a1,b0) - Y(a0,b0))   [difference-in-differences]

Sign convention: Y is travel in metres, so a **negative** effect is a reduction. The
interaction is the amount by which the alternative placement's advantage changes when
the other factor moves; it is not a share of anything unless a reference denominator is
stated explicitly.
"""

from __future__ import annotations

import pandas as pd

from .travel import ALL_BINS, QUANTITY_AWARE, line_travel, sku_bins

CELL_IDS = ("A1", "A2", "B1", "B2")


def _measure(
    assignments: pd.DataFrame,
    workload: pd.DataFrame,
    location_distance_m: dict[str, float],
    rule: str,
    demand_weighted_field: str,
) -> dict:
    result = line_travel(workload, sku_bins(assignments, location_distance_m), rule)
    agg = result.aggregate()
    return {
        "pick_rule": rule,
        "demand_weighted_depot_distance": agg[demand_weighted_field],
        "numerator_m": agg["numerator_m"],
        "denominator_lines": agg["denominator_lines"],
        "lines_total": agg["lines_total"],
        "lines_unresolved": agg["lines_unresolved"],
        "coverage_pct": agg["coverage_pct"],
        "mean_per_line_m": agg["mean_per_line_m"],
        "stops": agg["stops"],
        "lines_quantity_short": agg["lines_quantity_short"],
        "units_short": agg["units_short"],
    }


def _effects(
    values: dict[tuple[str, str], float],
    a_levels: tuple[str, str],
    b_levels: tuple[str, str],
) -> dict:
    a0, a1 = a_levels
    b0, b1 = b_levels
    y = lambda a, b: values[(a, b)]  # noqa: E731 - local shorthand

    effect_a = 0.5 * ((y(a1, b0) - y(a0, b0)) + (y(a1, b1) - y(a0, b1)))
    effect_b = 0.5 * ((y(a0, b1) - y(a0, b0)) + (y(a1, b1) - y(a1, b0)))
    interaction = (y(a1, b1) - y(a0, b1)) - (y(a1, b0) - y(a0, b0))

    def pct(value: float, denominator: float) -> float | None:
        return round(value / denominator * 100.0, 4) if denominator else None

    reference = y(a0, b0)
    return {
        "reference_cell": "A1",
        "reference_value_m": round(reference, 3),
        "factor_a_effect_m": round(effect_a, 3),
        "factor_a_effect_pct_of_reference": pct(effect_a, reference),
        "factor_b_effect_m": round(effect_b, 3),
        "factor_b_effect_pct_of_reference": pct(effect_b, reference),
        "interaction_m": round(interaction, 3),
        "interaction_pct_of_reference": pct(interaction, reference),
        "formulas": {
            "factor_a": "mean over B of (Y(a1,b) - Y(a0,b))",
            "factor_b": "mean over A of (Y(a,b1) - Y(a,b0))",
            "interaction": "(Y(a1,b1) - Y(a0,b1)) - (Y(a1,b0) - Y(a0,b0))",
        },
        "sign_convention": "Y is metres of travel; negative = fewer metres",
    }


def run_factorial_2x2(
    cells: dict[tuple[str, str], pd.DataFrame],
    workload: pd.DataFrame,
    location_distance_m: dict[str, float],
    *,
    factor_a_name: str = "placement",
    factor_b_name: str = "fragmentation_policy",
    rule: str = QUANTITY_AWARE,
    feasibility: dict[tuple[str, str], bool] | None = None,
    fragmentation: dict[tuple[str, str], dict] | None = None,
    demand_weighted_field: str = "demand_weighted_depot_distance",
    caveat: str | None = None,
) -> dict:
    """Run the four cells of a 2x2 and compute main effects plus interaction.

    ``cells`` must contain exactly the four ``(a_level, b_level)`` combinations; the
    insertion order fixes which level is reference (first) and alternative (second).
    """
    if len(cells) != 4:
        raise ValueError(f"a 2x2 needs exactly four cells, got {len(cells)}")

    a_levels = tuple(dict.fromkeys(a for a, _b in cells))
    b_levels = tuple(dict.fromkeys(b for _a, b in cells))
    if len(a_levels) != 2 or len(b_levels) != 2:
        raise ValueError(f"expected two levels per factor, got A={a_levels} B={b_levels}")
    missing = {(a, b) for a in a_levels for b in b_levels} - set(cells)
    if missing:
        raise ValueError(f"missing cells: {sorted(missing)}")

    rows: list[dict] = []
    values: dict[tuple[str, str], float] = {}
    for idx, (a, b) in enumerate(
        ((a_levels[0], b_levels[0]), (a_levels[0], b_levels[1]),
         (a_levels[1], b_levels[0]), (a_levels[1], b_levels[1]))
    ):
        measured = _measure(cells[(a, b)], workload, location_distance_m, rule, demand_weighted_field)
        values[(a, b)] = float(measured[demand_weighted_field])
        rows.append(
            {
                "cell_id": CELL_IDS[idx],
                factor_a_name: a,
                factor_b_name: b,
                "feasible": (feasibility or {}).get((a, b)),
                **measured,
                "fragmentation": (fragmentation or {}).get((a, b)),
            }
        )

    effects = _effects(values, (a_levels[0], a_levels[1]), (b_levels[0], b_levels[1]))
    effects["factor_a"] = factor_a_name
    effects["factor_b"] = factor_b_name
    effects["interaction_note"] = (
        "difference-in-differences; a non-zero value means the effect of factor A depends on the "
        "level of factor B (and vice versa). It is a property of this workload, not a significance test."
    )

    return {
        "design": {
            "id": f"2x2_{factor_a_name}_x_{factor_b_name}",
            "factor_a": {"name": factor_a_name, "levels": list(a_levels)},
            "factor_b": {"name": factor_b_name, "levels": list(b_levels)},
            "cell_ids": list(CELL_IDS),
            "outcome": demand_weighted_field,
            "pick_rule": rule,
            "unit": "m",
            "controls": [
                "same warehouse geometry, products and inventory",
                "same hard constraints and separation radius",
                "same distance model (depot -> bin, Dijkstra graph)",
                "same evaluation workload",
                "same batching and order-processing assumptions",
                "same fit/holdout boundary",
            ],
        },
        "cells": rows,
        "effects": effects,
        "caveat": caveat or (
            "single deterministic workload; the effects are a decomposition, not a significance test"
        ),
    }


def run_2x2(
    layouts: dict[str, pd.DataFrame],
    workload: pd.DataFrame,
    location_distance_m: dict[str, float],
    feasibility: dict[str, bool] | None = None,
    demand_weighted_field: str = "demand_weighted_depot_distance",
) -> dict:
    """Architecture §11.5 pick-rule sensitivity: placement x evaluation rule.

    This design holds the *layout* fixed while the pick rule changes. Its interaction
    measures how much of the raw all-bins gain depends on charging every bin a SKU
    occupies; it does **not** manipulate fragmentation, so it is reported separately
    from the primary placement x fragmentation experiment.
    """
    if len(layouts) != 2:
        raise ValueError("2x2 needs exactly two layouts")

    cells: list[dict] = []
    values: dict[tuple[str, str], float] = {}

    for label, assignments in layouts.items():
        for rule in (ALL_BINS, QUANTITY_AWARE):
            measured = _measure(assignments, workload, location_distance_m, rule, demand_weighted_field)
            values[(label, rule)] = float(measured[demand_weighted_field])
            cells.append(
                {
                    "layout": label,
                    "pick_rule": rule,
                    "feasible": (feasibility or {}).get(label),
                    **{k: v for k, v in measured.items() if k != "pick_rule"},
                }
            )

    (base_label, opt_label) = list(layouts.keys())

    def y(label: str, rule: str) -> float:
        return values[(label, rule)]

    layout_effect = 0.5 * (
        (y(opt_label, ALL_BINS) - y(base_label, ALL_BINS))
        + (y(opt_label, QUANTITY_AWARE) - y(base_label, QUANTITY_AWARE))
    )
    rule_effect = 0.5 * (
        (y(base_label, ALL_BINS) - y(base_label, QUANTITY_AWARE))
        + (y(opt_label, ALL_BINS) - y(opt_label, QUANTITY_AWARE))
    )
    interaction = (y(opt_label, ALL_BINS) - y(base_label, ALL_BINS)) - (
        y(opt_label, QUANTITY_AWARE) - y(base_label, QUANTITY_AWARE)
    )

    def pct(numerator: float, denominator: float) -> float | None:
        return round(numerator / denominator * 100.0, 4) if denominator else None

    return {
        "design": {
            "id": "2x2_placement_x_pick_rule",
            "factors": {
                "placement": [base_label, opt_label],
                "pick_rule": [ALL_BINS, QUANTITY_AWARE],
            },
            "outcome": demand_weighted_field,
            "unit": "m",
            "note": (
                "pick-rule sensitivity, not a fragmentation treatment: the layout is held fixed and "
                "only the evaluation rule changes"
            ),
            "controls": [
                "same warehouse, products, inventory",
                "same hard constraints and separation radius",
                "same distance model (depot -> bin)",
                "same evaluation workload",
            ],
        },
        "cells": cells,
        "effects": {
            "layout_effect_m": round(layout_effect, 3),
            "layout_effect_pct_of_baseline_qa": pct(layout_effect, y(base_label, QUANTITY_AWARE)),
            "rule_effect_m": round(rule_effect, 3),
            "rule_effect_pct_of_baseline_qa": pct(rule_effect, y(base_label, QUANTITY_AWARE)),
            "interaction_m": round(interaction, 3),
            "interaction_note": (
                "difference-in-differences; negative means the optimized layout gains more under the "
                "all-bins rule, i.e. part of its advantage is a fragmentation-sensitive accounting effect"
            ),
        },
        "interpretation": _interpret(interaction, layout_effect),
    }


def _interpret(interaction: float, layout_effect: float) -> dict:
    """Plain-language reading, written so it cannot overstate the evidence."""
    if layout_effect == 0:
        return {"summary": "no layout effect to interpret"}
    share = interaction / layout_effect if layout_effect else 0.0
    return {
        "accounting_sensitive_share_of_raw_gain": round(share * 100.0, 2),
        "summary": (
            "the quantity-aware rule removes the per-bin visit charge, so the interaction measures how "
            "much of the raw gain depended on the fragmentation-sensitive rule"
        ),
        "caveat": "one deterministic workload; this is a decomposition, not a significance test",
    }
