"""Replenishment workload core (Phase 3, D47).

The dataset has no replenishment events, no supplier data and no restock policy. What
it does have is per-bin on-hand quantity, per-SKU demand over a known window, and a
depot distance for every bin. From those, one replenishment quantity is defensible:

    daily_units(s)  = units demanded of s over the window / window_days
    lot(s)          = ceil(daily_units(s) * cover_days)
    trips(s, b)     = ceil(on_hand(s, b) / lot(s))
    travel          = sum over (s, b) of 2 * trips(s, b) * depot_distance(b)

The factor 2 is the round trip depot -> bin -> depot.

**Zero-demand SKUs make zero trips.** A SKU with no demand inside the evaluation
window is not replenished during that window; charging ``ceil(on_hand / 1)`` trips
would invent work the demand data does not support. Those SKUs are counted and their
stock is reported, but they contribute no trips and no travel.

What this is NOT
----------------
- Not a schedule: no timing, no batching of trips, no vehicle capacity.
- Not a cost: no labour rate, no currency.
- Not a policy: ``cover_days`` is an assumption (14 days by default), not a modelled
  decision.

It is a **proxy for restock travel**, and the reason it exists is that fragmentation
raises it: a SKU spread over four bins needs four destinations.
"""

from __future__ import annotations

import math
from typing import Iterable, Mapping

DEFAULT_WINDOW_DAYS = 180.0   # `configs/dataset.json` order window
DEFAULT_COVER_DAYS = 14.0     # assumption: one restock lot covers two weeks


def lot_size(daily_units: float, cover_days: float) -> int:
    """Units in one restock lot; at least 1 so any positive demand needs a trip."""
    return max(1, int(math.ceil(daily_units * cover_days)))


def trips_for(on_hand: int, daily_units: float, cover_days: float) -> int:
    """Restock trips for one bin over the window.

    Zero when the bin holds nothing or the SKU has no demand in the window: a
    zero-demand SKU is not replenished, and inventing a trip for it would bias the
    proxy upward for every stocked-but-not-demanded SKU.
    """
    if on_hand <= 0 or daily_units <= 0:
        return 0
    return max(1, int(math.ceil(on_hand / lot_size(daily_units, cover_days))))


def replenishment_travel(
    rows: Iterable[tuple[str, str, int]],
    units_demand: Mapping[str, float],
    location_distance_m: Mapping[str, float],
    window_days: float = DEFAULT_WINDOW_DAYS,
    cover_days: float = DEFAULT_COVER_DAYS,
) -> float:
    """Total restock travel for ``(sku_id, location_id, on_hand)`` rows."""
    if window_days <= 0:
        raise ValueError("window_days must be positive")
    if cover_days < 0:
        raise ValueError("cover_days must be non-negative")

    total = 0.0
    for sku_id, location_id, on_hand in rows:
        qty = int(on_hand)
        if qty <= 0:
            continue
        dist = location_distance_m.get(location_id)
        if dist is None:
            continue
        daily = float(units_demand.get(sku_id, 0.0)) / window_days
        trips = trips_for(qty, daily, cover_days)
        if trips:
            total += 2.0 * trips * float(dist)
    return total
