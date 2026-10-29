"""Replenishment workload as a measurable proxy (Phase 3, D47).

The arithmetic lives in :mod:`src.optimization.replenishment` because the optimizer's
objective needs the same function; this module wraps it for a layout DataFrame and
reports the auditable counts.

Definitions
-----------
``daily_units(s) = units_demanded(s) / window_days`` (window = 180 days)
``lot(s)        = ceil(daily_units(s) * cover_days)`` (cover_days = 14, an assumption)
``trips(s, b)   = ceil(on_hand(s, b) / lot(s))``, **zero when demand(s) is zero**
``travel        = sum_(s,b) 2 * trips(s, b) * depot_distance(b)``

The factor 2 is the round trip depot -> bin -> depot. A SKU with no demand in the
evaluation window contributes no trips: it is stocked, but it is not restocked during
the window the demand came from.

What it is NOT: no schedule, no trip batching, no vehicle capacity, no labour cost.
``cover_days`` is an assumption, not a modelled policy. It is a proxy for restock
*travel*, not an operational plan.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping

import pandas as pd

from src.optimization.replenishment import (
    DEFAULT_COVER_DAYS,
    DEFAULT_WINDOW_DAYS,
    lot_size,
    trips_for,
)

__all__ = [
    "DEFAULT_COVER_DAYS",
    "DEFAULT_WINDOW_DAYS",
    "ReplenishmentResult",
    "lot_size",
    "replenishment_metrics",
    "replenishment_term",
    "trips_for",
]


@dataclass(frozen=True)
class ReplenishmentResult:
    trips: int
    travel_m: float
    n_skus_stocked: int
    n_skus_replenished: int
    n_bins: int
    cover_days: float
    window_days: float
    units_in_skus_without_demand: int = 0

    @property
    def n_skus(self) -> int:
        """Back-compat alias: stocked SKUs (the denominator for mean-per-SKU)."""
        return self.n_skus_stocked

    def aggregate(self) -> dict:
        return {
            "replenishment_trips": self.trips,
            "replenishment_travel_m": round(self.travel_m, 3),
            "numerator_m": round(self.travel_m, 3),
            "denominator_skus": self.n_skus_stocked,
            "n_skus_stocked": self.n_skus_stocked,
            "n_skus_replenished": self.n_skus_replenished,
            "mean_travel_per_stocked_sku_m": (
                round(self.travel_m / self.n_skus_stocked, 3) if self.n_skus_stocked else None
            ),
            # Back-compat alias; the denominator is stocked SKUs (see above).
            "mean_travel_per_sku_m": (
                round(self.travel_m / self.n_skus_stocked, 3) if self.n_skus_stocked else None
            ),
            "mean_travel_per_replenished_sku_m": (
                round(self.travel_m / self.n_skus_replenished, 3)
                if self.n_skus_replenished
                else None
            ),
            "n_bins": self.n_bins,
            "units_in_skus_without_demand": self.units_in_skus_without_demand,
            "cover_days": self.cover_days,
            "window_days": self.window_days,
            "unit": "m",
            "model": "trips(s,b)=ceil(on_hand/lot(s)); travel=sum 2*trips*depot_distance",
            "zero_demand_rule": "a SKU with no demand in the window makes no replenishment trips",
            "assumptions": [
                "no schedule, timing or vehicle capacity modelled",
                "cover_days is an assumption, not a policy decision",
                "travel is a round trip depot->bin->depot",
                "zero-demand SKUs contribute no trips; their stock is reported separately",
            ],
        }


def replenishment_metrics(
    assignments: pd.DataFrame,
    units_demand: Mapping[str, float],
    location_distance_m: Mapping[str, float],
    window_days: float = DEFAULT_WINDOW_DAYS,
    cover_days: float = DEFAULT_COVER_DAYS,
) -> ReplenishmentResult:
    """Restock trips and travel for one layout.

    ``assignments``: sku_id, location_id, assigned_quantity (the on-hand placed there).
    ``units_demand``: sku_id -> units demanded over ``window_days``.
    ``location_distance_m``: location_id -> depot distance in metres.
    """
    if window_days <= 0:
        raise ValueError("window_days must be positive")
    if cover_days < 0:
        raise ValueError("cover_days must be non-negative")

    trips_total = 0
    travel_total = 0.0
    stocked: set[str] = set()
    replenished: set[str] = set()
    bins = 0
    units_without_demand = 0

    for row in assignments.itertuples(index=False):
        qty = int(row.assigned_quantity)
        if qty <= 0:
            continue
        dist = location_distance_m.get(row.location_id)
        if dist is None:
            continue
        daily = float(units_demand.get(row.sku_id, 0.0)) / window_days
        trips = trips_for(qty, daily, cover_days)
        stocked.add(row.sku_id)
        bins += 1
        if trips <= 0:
            units_without_demand += qty
            continue
        trips_total += trips
        travel_total += 2.0 * trips * float(dist)
        replenished.add(row.sku_id)

    return ReplenishmentResult(
        trips=trips_total,
        travel_m=travel_total,
        n_skus_stocked=len(stocked),
        n_skus_replenished=len(replenished),
        n_bins=bins,
        cover_days=cover_days,
        window_days=window_days,
        units_in_skus_without_demand=units_without_demand,
    )


def replenishment_term(
    assignments: pd.DataFrame,
    units_demand: Mapping[str, float],
    location_distance_m: Mapping[str, float],
    window_days: float = DEFAULT_WINDOW_DAYS,
    cover_days: float = DEFAULT_COVER_DAYS,
) -> float:
    """The objective's Psi_R term: restock travel in metres."""
    return replenishment_metrics(
        assignments,
        units_demand,
        location_distance_m,
        window_days=window_days,
        cover_days=cover_days,
    ).travel_m
