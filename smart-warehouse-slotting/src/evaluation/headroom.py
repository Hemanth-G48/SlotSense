"""Structural utilization and headroom from the validator's own checks (Phase 4).

Being feasible is not the same as having spare capacity. This module reads the rule checks
the independent validator already produced (observed vs limit) and reports, per structural
scope, the maximum utilization, the number of near-limit records and the limiting record.

Scopes
------
``LD-01`` bin weight (kg)
``VD-01`` bin volume (cm3)
``SL-01`` shelf/level load (kg)
``SL-02`` beam load (kg)
``RK-01`` rack load (kg)

No new constraint is introduced. The 90 %/95 % counters are *reporting* thresholds; they do
not reject a layout, and the hard verdict remains ``result.is_feasible``.
"""

from __future__ import annotations

SCOPE_RULES = {
    "LD-01": ("bin_weight", "kg"),
    "VD-01": ("bin_volume", "cm3"),
    "SL-01": ("level_load", "kg"),
    "SL-02": ("beam_load", "kg"),
    "RK-01": ("rack_load", "kg"),
}

NEAR_LIMIT_PCT = 90.0
HIGH_LIMIT_PCT = 95.0


def _util(observed, limit) -> float | None:
    try:
        o = float(observed)
        l = float(limit)
    except (TypeError, ValueError):
        return None
    if l <= 0:
        return None
    return 100.0 * o / l


def structural_headroom(result, top: int = 5) -> dict:
    """Per-scope utilization for one validation result.

    ``result`` is the independent validator's ``ValidationResult``; this function does not
    re-validate and cannot change a verdict.
    """
    checks = getattr(result, "checks", None) or []
    by_rule: dict[str, list] = {}
    for check in checks:
        if check.rule_id in SCOPE_RULES and check.limit is not None:
            by_rule.setdefault(check.rule_id, []).append(check)

    scopes: dict[str, dict] = {}
    for rule_id, (name, unit) in SCOPE_RULES.items():
        rows = by_rule.get(rule_id, [])
        values = []
        for check in rows:
            util = _util(check.observed, check.limit)
            if util is None:
                continue
            values.append((util, check))
        if not values:
            scopes[name] = {
                "rule_id": rule_id,
                "unit": unit,
                "checks": len(rows),
                "max_utilization_pct": None,
                "mean_utilization_pct": None,
                "pct_over_90": None,
                "pct_over_95": None,
                "limiting": None,
                "status": "unavailable",
            }
            continue

        values.sort(key=lambda t: (-t[0], str(t[1].location_id or ""), str(t[1].sku_id or "")))
        max_util, limiting = values[0]
        n = len(values)
        scopes[name] = {
            "rule_id": rule_id,
            "unit": unit,
            "checks": n,
            "max_utilization_pct": round(max_util, 4),
            "mean_utilization_pct": round(sum(v for v, _c in values) / n, 4),
            "pct_over_90": round(100.0 * sum(1 for v, _c in values if v >= NEAR_LIMIT_PCT) / n, 3),
            "pct_over_95": round(100.0 * sum(1 for v, _c in values if v >= HIGH_LIMIT_PCT) / n, 3),
            "limiting": {
                "location_id": limiting.location_id,
                "sku_id": limiting.sku_id,
                "observed": limiting.observed,
                "limit": limiting.limit,
                "utilization_pct": round(max_util, 4),
                "explanation": limiting.explanation,
            },
            "status": (
                "at_or_above_95" if max_util >= HIGH_LIMIT_PCT
                else "at_or_above_90" if max_util >= NEAR_LIMIT_PCT
                else "headroom"
            ),
        }

    available = [s["max_utilization_pct"] for s in scopes.values() if s["max_utilization_pct"] is not None]
    return {
        "scopes": scopes,
        "limiting_scope": max(
            (s for s in scopes.values() if s["max_utilization_pct"] is not None),
            key=lambda s: s["max_utilization_pct"],
            default=None,
        ),
        "max_utilization_pct": round(max(available), 4) if available else None,
        "reporting_thresholds": {"near_limit_pct": NEAR_LIMIT_PCT, "high_limit_pct": HIGH_LIMIT_PCT},
        "note": (
            "utilization is observed/limit from the independent validator; the 90/95 % counters are "
            "reporting bands, not feasibility rules"
        ),
    }
