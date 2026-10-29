"""Structured rejection diagnostics for the evaluation gate (Phase 4).

When a layout cannot be published, the reason must be inspectable: which rule failed, on
which SKU or bin, what the observed value was against its limit, and whether the failure
blocked publication. The independent validator remains the authority; this module only
reshapes its verdict.

Nothing here can turn a hard violation into a warning. ``blocks_publication`` is always the
negation of ``result.is_feasible``.
"""

from __future__ import annotations

RULE_CATEGORY = {
    "CAT-01": "category_separation",
    "LD-01": "bin_weight",
    "VD-01": "bin_volume",
    "SL-01": "level_load",
    "SL-02": "beam_load",
    "RK-01": "rack_load",
    "INV-01": "inventory_conservation",
    "INV-02": "inventory_conservation",
    "INV-03": "inventory_conservation",
    "SP-01": "dimensional_fit",
    "HZ-01": "hazard",
    "HD-01": "handling",
    "ER-01": "ergonomics",
}

NEXT_STEP = {
    "category_separation": "move one side of the forbidden pair beyond the configured radius",
    "bin_weight": "reduce the quantity in the overloaded bin or split it across bins",
    "bin_volume": "reduce the quantity or use a larger bin class",
    "level_load": "spread load across shelf levels in the rack",
    "beam_load": "spread load across beams/bays in the rack",
    "rack_load": "spread load across racks",
    "inventory_conservation": "restore the SKU's full on-hand quantity exactly once",
    "dimensional_fit": "choose a bin whose dimensions accept the SKU",
    "hazard": "choose a bin whose allowed-hazard set includes the SKU",
    "handling": "choose a bin whose allowed-handling set includes the SKU",
    "ergonomics": "place the SKU within the allowed shelf-level band",
}

MAX_ROWS = 200


def _category(rule_id: str) -> str:
    return RULE_CATEGORY.get(rule_id, "other")


def _check_index(result) -> dict[tuple[str, str, str], object]:
    index = {}
    for check in getattr(result, "checks", None) or []:
        if check.passed:
            continue
        key = (check.rule_id, str(check.sku_id or ""), str(check.location_id or ""))
        index.setdefault(key, check)
    return index


def diagnose_validation(result, layout_id: str) -> dict:
    """Turn one ``ValidationResult`` into a structured, publication-aware diagnosis."""
    violations = list(getattr(result, "violations", None) or [])
    failed_checks = _check_index(result)

    rows = []
    for v in violations[:MAX_ROWS]:
        check = failed_checks.get((v.rule_id, str(v.sku_id or ""), str(v.location_id or "")))
        category = _category(v.rule_id)
        rows.append(
            {
                "rule_id": v.rule_id,
                "rule_name": v.rule_name,
                "category": category,
                "severity": v.severity,
                "sku_id": v.sku_id,
                "location_id": v.location_id,
                "pair": list(v.pair) if getattr(v, "pair", None) else None,
                "observed": getattr(check, "observed", None) if check is not None else None,
                "limit": getattr(check, "limit", None) if check is not None else None,
                "unit": getattr(check, "unit", "") if check is not None else "",
                "reason": v.reason,
                "blocks_publication": True,
                "next_step": NEXT_STEP.get(category, "inspect the rule check and correct the placement"),
            }
        )

    categories: dict[str, int] = {}
    for row in rows:
        categories[row["category"]] = categories.get(row["category"], 0) + 1

    return {
        "layout": layout_id,
        "status": "feasible" if not violations else "rejected",
        "publishable": not violations,
        "blocks_publication": bool(violations),
        "n_violations": len(violations),
        "n_violations_reported": len(rows),
        "truncated": len(violations) > len(rows),
        "failure_categories": dict(sorted(categories.items())),
        "affected_skus": sorted({v.sku_id for v in violations if v.sku_id}),
        "affected_bins": sorted({v.location_id for v in violations if v.location_id}),
        "violations": rows,
        "note": (
            "hard violations are never downgraded to warnings; a rejected layout is excluded "
            "from every publishable comparison"
        ),
    }
