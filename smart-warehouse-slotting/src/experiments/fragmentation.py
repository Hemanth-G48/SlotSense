"""Fragmentation policy as a manipulable experimental factor (Phase 3, D22).

Why this module exists
----------------------
"Fragmentation" is the number of bins a SKU occupies. The v1 pick model charges a stop
per (batch, bin), so a layout can look faster simply because it scatters or consolidates
stock rather than because it placed stock better. To separate the two effects, the 2x2
needs fragmentation to be a **policy applied to a layout**, not just a different way of
scoring one.

Policies
--------
``as_is``
    The layout exactly as produced (reference level).
``min_bins``
    Re-pack each SKU's on-hand into as few of *its own* assigned bins as capacity
    allows (alternative level). Bins that end up empty are released. No new bin is
    ever introduced, so the set of candidate locations a SKU was placed in is
    preserved; only the multiplicity changes.

How the retained bins are chosen
--------------------------------
Bins are filled in **descending static unit capacity** (how many units of that SKU fit
given the bin's weight and volume limits), tie-broken by ``location_id``. Depot
distance is deliberately **not** consulted: if retention were nearest-first, the
fragmentation factor would also move stock closer to dispatch and the two factors would
be confounded. The appended statistics report the mean depot distance of the used bins
before and after, so a reviewer can see how much proximity changed anyway.

Safety
------
The packer reuses the optimizer's own ledger logic (``_split_quantity`` over bin,
beam, level and rack limits), then calls the **independent validator** on the result.
If a SKU cannot be fully re-packed it is kept exactly as supplied and the whole layout
is rebuilt with that SKU seeded in, so inventory conservation and structural limits
are preserved by construction. If the layout is still infeasible after the bounded
retries, the original layout is returned with ``feasible=False`` — never a partial or
silently truncated one.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Mapping

import pandas as pd

from src.models.entities import AssignmentType, SKU, StorageAssignment
from src.optimization.optimizer import SlottingOptimizer, _split_quantity

POLICY_AS_IS = "as_is"
POLICY_MIN_BINS = "min_bins"
FRAGMENTATION_POLICIES = (POLICY_AS_IS, POLICY_MIN_BINS)

DEFAULT_MAX_RETRIES = 8


def fragmentation_stats(
    assignments: pd.DataFrame,
    location_distance_m: Mapping[str, float] | None = None,
) -> dict:
    """Descriptive fragmentation for one layout.

    ``fragmentation_index`` = bins used / SKUs stocked. 1.0 is perfectly consolidated;
    every extra bin is one more destination a pick (and a restock) may have to visit.
    """
    per_sku = assignments.groupby("sku_id")["location_id"].nunique()
    n_skus = int(per_sku.size)
    bins = int(assignments["location_id"].nunique())
    stats = {
        "bins_used": bins,
        "rows": int(len(assignments)),
        "n_skus": n_skus,
        "multi_bin_skus": int((per_sku > 1).sum()),
        "max_bins_per_sku": int(per_sku.max()) if n_skus else 0,
        "mean_bins_per_sku": round(float(per_sku.mean()), 6) if n_skus else None,
        "fragmentation_index": round(bins / n_skus, 6) if n_skus else None,
        "units": int(assignments["assigned_quantity"].sum()),
    }
    if location_distance_m is not None:
        d = assignments["location_id"].map(location_distance_m)
        stats["mean_bin_distance_m"] = round(float(d.mean()), 4) if len(d) else None
        stats["missing_distances"] = int(d.isna().sum())
    return stats


def consolidate_min_bins(
    assignments: pd.DataFrame,
    *,
    skus: Mapping[str, SKU],
    warehouse,
    validator,
    location_distance_m: Mapping[str, float] | None = None,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> tuple[pd.DataFrame, dict]:
    """Apply the ``min_bins`` fragmentation policy to one layout.

    Returns ``(layout, stats)``. The returned layout is always inventory-conserving
    with respect to its input; ``stats["feasible"]`` is the independent validator's
    verdict, and when it is False the input layout is returned unchanged.
    """
    before = fragmentation_stats(assignments, location_distance_m)
    keep: set[str] = set()
    result = assignments.copy()
    feasible = False
    iterations = 0

    for iterations in range(1, max_retries + 1):
        previous_keep = set(keep)
        candidate, unplaced = _build(assignments, previous_keep, skus, warehouse)

        verdict = validator.validate(_to_records(candidate))
        violators = sorted({v.sku_id for v in verdict.violations if getattr(v, "sku_id", None)})
        if verdict.is_feasible and not unplaced and _conserves(candidate, assignments):
            result, feasible = candidate, True
            break

        # Retry with the offending SKUs pinned to their original rows. If nothing is
        # named (an aggregate rule) the loop would not converge, so keep everything:
        # the original layout is the only layout this policy can guarantee.
        new_keep = set(unplaced) | set(violators)
        if not new_keep or new_keep <= previous_keep:
            keep |= set(assignments["sku_id"].unique())
            result = assignments.copy()
            feasible = bool(validator.validate(_to_records(result)).is_feasible)
            break
        keep |= new_keep

    after = fragmentation_stats(result, location_distance_m)
    stats = {
        "policy": POLICY_MIN_BINS,
        "feasible": feasible,
        "iterations": iterations,
        "fallback_skus": len(keep),
        "before": before,
        "after": after,
        "bins_released": before["bins_used"] - after["bins_used"],
        "units_conserved": int(result["assigned_quantity"].sum())
        == int(assignments["assigned_quantity"].sum()),
        "distance_blind_retention": True,
    }
    return result, stats


def _conserves(candidate: pd.DataFrame, source: pd.DataFrame) -> bool:
    a = candidate.groupby("sku_id")["assigned_quantity"].sum()
    b = source.groupby("sku_id")["assigned_quantity"].sum()
    return bool(a.equals(b) and int(candidate["assigned_quantity"].sum()) == int(source["assigned_quantity"].sum()))


def _to_records(frame: pd.DataFrame) -> list[StorageAssignment]:
    return [
        StorageAssignment(r.sku_id, r.location_id, int(r.assigned_quantity), AssignmentType.OPTIMIZED)
        for r in frame.itertuples(index=False)
    ]


def _build(
    assignments: pd.DataFrame,
    keep: set[str],
    skus: Mapping[str, SKU],
    warehouse,
) -> tuple[pd.DataFrame, list[str]]:
    """One deterministic packing pass; returns (layout, SKUs that could not be packed)."""
    rows: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for r in assignments.itertuples(index=False):
        rows[r.sku_id].append((r.location_id, int(r.assigned_quantity)))

    residual_bin_weight = {l.location_id: l.max_weight_kg for l in warehouse.locations.values()}
    residual_volume = {l.location_id: l.usable_volume_cm3 for l in warehouse.locations.values()}
    beam_cap, level_cap, rack_cap = SlottingOptimizer._structural_caps(warehouse.locations.values())
    beam_load: dict[tuple, float] = defaultdict(float)
    level_load: dict[tuple, float] = defaultdict(float)
    rack_load: dict[str, float] = defaultdict(float)
    out: list[tuple[str, str, int]] = []
    failed: list[str] = []

    def place(sku_id: str, location_id: str, qty: int) -> None:
        sku = skus[sku_id]
        loc = warehouse.locations[location_id]
        beam_key = (loc.rack_id, loc.bay, loc.shelf_level)
        level_key = (loc.rack_id, loc.shelf_level)
        residual_bin_weight[location_id] -= sku.unit_weight_kg * qty
        residual_volume[location_id] -= sku.unit_volume_cm3 * qty
        beam_load[beam_key] += sku.unit_weight_kg * qty
        level_load[level_key] += sku.unit_weight_kg * qty
        rack_load[loc.rack_id] += sku.unit_weight_kg * qty
        out.append((sku_id, location_id, qty))

    # Pinned SKUs seed the ledger first so the packer cannot take capacity they need.
    for sku_id in sorted(keep):
        for location_id, qty in rows[sku_id]:
            place(sku_id, location_id, qty)

    for sku_id, bins in sorted(
        rows.items(), key=lambda kv: (-sum(q for _, q in kv[1]), kv[0])
    ):
        if sku_id in keep:
            continue
        sku = skus[sku_id]
        remaining = sum(q for _, q in bins)
        scored = []
        for location_id, _qty in bins:
            loc = warehouse.locations[location_id]
            by_weight = loc.max_weight_kg / sku.unit_weight_kg if sku.unit_weight_kg > 0 else 1e9
            by_volume = (
                loc.usable_volume_cm3 / sku.unit_volume_cm3 if sku.unit_volume_cm3 > 0 else 1e9
            )
            scored.append((-min(by_weight, by_volume), location_id))
        scored.sort()

        for _neg_capacity, location_id in scored:
            if remaining <= 0:
                break
            loc = warehouse.locations[location_id]
            beam_key = (loc.rack_id, loc.bay, loc.shelf_level)
            level_key = (loc.rack_id, loc.shelf_level)
            qty = _split_quantity(
                sku,
                loc,
                remaining,
                residual_bin_weight=residual_bin_weight[location_id],
                residual_volume=residual_volume[location_id],
                residual_shelf_weight=level_cap.get(level_key, float("inf")) - level_load[level_key],
                residual_rack_weight=rack_cap.get(loc.rack_id, float("inf")) - rack_load[loc.rack_id],
                residual_beam_weight=beam_cap.get(beam_key, float("inf")) - beam_load[beam_key],
            )
            if qty <= 0:
                continue
            place(sku_id, location_id, qty)
            remaining -= qty

        if remaining > 0:
            failed.append(sku_id)

    frame = pd.DataFrame(out, columns=["sku_id", "location_id", "assigned_quantity"])
    return frame, failed
