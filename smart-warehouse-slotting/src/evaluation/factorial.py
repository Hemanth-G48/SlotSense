"""Factorial effect calculations for Phase 4's layout x picking-policy experiment.

The arithmetic is the standard 2x2 decomposition, kept independent of any simulation
details so it can be hand-checked on a fixture:

    factor A effect = mean over B of (Y(a1,b) - Y(a0,b))
    factor B effect = mean over A of (Y(a,b1) - Y(a,b0))
    interaction     = (Y(a1,b1) - Y(a0,b1)) - (Y(a1,b0) - Y(a0,b0))

Sign convention: the effect is in the metric's own units. For travel/cycle time, negative
is fewer metres/seconds (better); for throughput, positive is more orders/hour.
"""

from __future__ import annotations


def effect_table(
    values: dict[tuple[str, str], float],
    a_levels: tuple[str, str],
    b_levels: tuple[str, str],
    *,
    a_name: str = "layout",
    b_name: str = "picking_policy",
    unit: str = "",
    lower_is_better: bool = True,
    reference_denominator: float | None = None,
) -> dict:
    """Return main effects, interaction and a reference-relative percentage."""
    a0, a1 = a_levels
    b0, b1 = b_levels
    missing = [(a, b) for a in a_levels for b in b_levels if (a, b) not in values]
    if missing:
        raise ValueError(f"missing 2x2 cells: {missing}")

    y = lambda a, b: float(values[(a, b)])  # noqa: E731 - local shorthand

    effect_a = 0.5 * ((y(a1, b0) - y(a0, b0)) + (y(a1, b1) - y(a0, b1)))
    effect_b = 0.5 * ((y(a0, b1) - y(a0, b0)) + (y(a1, b1) - y(a1, b0)))
    interaction = (y(a1, b1) - y(a0, b1)) - (y(a1, b0) - y(a0, b0))

    reference = y(a0, b0)
    denominator = reference if reference_denominator is None else float(reference_denominator)

    def pct(value: float) -> float | None:
        return round(value / denominator * 100.0, 4) if denominator else None

    return {
        "factor_a": a_name,
        "factor_b": b_name,
        "levels": {a_name: [a0, a1], b_name: [b0, b1]},
        "unit": unit,
        "lower_is_better": lower_is_better,
        "reference_cell": "A1",
        "cell_values": {f"{a}|{b}": y(a, b) for a in a_levels for b in b_levels},
        "reference_value": reference,
        "factor_a_effect": round(effect_a, 4),
        "factor_a_effect_pct": pct(effect_a),
        "factor_b_effect": round(effect_b, 4),
        "factor_b_effect_pct": pct(effect_b),
        "interaction": round(interaction, 4),
        "interaction_pct": pct(interaction),
        "formulas": {
            "factor_a": "mean over B of (Y(a1,b) - Y(a0,b))",
            "factor_b": "mean over A of (Y(a,b1) - Y(a,b0))",
            "interaction": "(Y(a1,b1) - Y(a0,b1)) - (Y(a1,b0) - Y(a0,b0))",
        },
        "note": "single deterministic run; effects are a decomposition, not a significance test",
    }


def metric_effects(
    cells: dict[str, dict],
    *,
    a_levels: tuple[str, str],
    b_levels: tuple[str, str],
    metrics: dict[str, dict],
) -> dict:
    """Compute effects for several metrics.

    ``cells`` maps ``"<a>|<b>"`` to a metric dict. ``metrics`` maps metric key to
    ``{"unit": ..., "lower_is_better": ...}``.
    """
    out = {}
    for key, spec in metrics.items():
        values = {}
        for a in a_levels:
            for b in b_levels:
                value = cells[f"{a}|{b}"].get(key)
                if value is None:
                    values = {}
                    break
                values[(a, b)] = float(value)
            if not values:
                break
        if not values:
            out[key] = {"status": "unavailable", "reason": "metric missing in at least one cell"}
            continue
        out[key] = effect_table(
            values,
            a_levels,
            b_levels,
            unit=spec.get("unit", ""),
            lower_is_better=bool(spec.get("lower_is_better", True)),
        )
    return out
