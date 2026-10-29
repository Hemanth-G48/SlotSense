"""Pick-order batching and pick-cycle-time simulation.

Given a fixed order workload, a slotting layout (sku -> list of (location, quantity)), and the
aisle route graph, simulates travel distance and completion time. Cycle time = travel time +
pick time + setup time.

Deterministic: batches/orders/SKUs are sorted before iteration so results do not depend on
hash order across processes.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


PICK_TIME_BASES = ("order_line", "stop")


@dataclass
class SimulationConfig:
    batch_size: int = 5
    routing_strategy: str = "nearest_neighbor"
    picker_speed_mps: float = 1.3
    pick_time_sec: float = 8.0
    setup_time_sec: float = 10.0
    # D37: pick time can be charged per order line (the Phase 2/3 definition) or per
    # distinct physical stop. The per-event constant is explicit for each basis so a
    # comparison changes the unit, not a hidden multiplier.
    pick_time_basis: str = "order_line"
    pick_time_stop_sec: float = 8.0

    def __post_init__(self) -> None:
        if self.pick_time_basis not in PICK_TIME_BASES:
            raise ValueError(
                f"pick_time_basis must be one of {PICK_TIME_BASES}, got {self.pick_time_basis!r}"
            )
        if self.pick_time_sec < 0 or self.pick_time_stop_sec < 0:
            raise ValueError("pick-time constants must be non-negative")


@dataclass
class RouteResult:
    batch_id: int
    n_orders: int
    n_locations: int
    distance_m: float
    travel_time_sec: float
    pick_time_sec: float
    cycle_time_sec: float
    route: tuple[str, ...] = ()
    legs: tuple[float, ...] = ()
    n_pick_lines: int = 0
    n_pick_stops: int = 0


def build_batches(order_items: pd.DataFrame, batch_size: int) -> list[pd.DataFrame]:
    """Group orders into batches of up to batch_size orders (sorted for determinism)."""
    orders = sorted(order_items["order_id"].unique())
    batches = []
    for i in range(0, len(orders), batch_size):
        ids = orders[i : i + batch_size]
        batches.append(order_items[order_items["order_id"].isin(ids)])
    return batches


def simulate_layout(
    order_items: pd.DataFrame,
    slotting: dict[str, list[str]],  # sku -> locations where its inventory is stored
    location_dist: dict,
    depot_dist: dict[str, float],
    cfg: SimulationConfig,
    depot: str,
) -> list[RouteResult]:
    """Simulate picking over all orders for one slotting layout.

    A batcher visits the distinct bins holding the SKUs of its orders. Slotting maps each
    SKU to the bin(s) where its stock is placed. The ordered stop sequence and each leg's
    distance are kept so routes can be drawn and audited.
    """
    batches = build_batches(order_items, cfg.batch_size)
    results: list[RouteResult] = []
    from ..routing.heuristics import ROUTING_STRATEGIES, route_legs

    route_fn = ROUTING_STRATEGIES[cfg.routing_strategy]
    for bi, batch in enumerate(batches):
        skus = sorted(set(batch["sku_id"]))
        pick_locations = []
        for s in skus:
            for loc in slotting.get(s, []):
                if loc not in pick_locations:
                    pick_locations.append(loc)
        n_pick_lines = len(batch)
        n_pick_stops = len(pick_locations)
        pick_units = n_pick_lines if cfg.pick_time_basis == "order_line" else n_pick_stops
        pick_constant = (
            cfg.pick_time_sec if cfg.pick_time_basis == "order_line" else cfg.pick_time_stop_sec
        )
        route, distance = route_fn(pick_locations, location_dist, depot_dist, depot)
        legs = route_legs(route, location_dist, depot_dist, depot)
        travel_time = distance / cfg.picker_speed_mps
        pick_time = pick_units * pick_constant
        cycle_time = travel_time + pick_time + cfg.setup_time_sec
        results.append(
            RouteResult(
                batch_id=bi,
                n_orders=len(batch["order_id"].unique()),
                n_locations=len(pick_locations),
                distance_m=distance,
                travel_time_sec=travel_time,
                pick_time_sec=pick_time,
                cycle_time_sec=cycle_time,
                route=tuple(route),
                legs=tuple(legs),
                n_pick_lines=n_pick_lines,
                n_pick_stops=n_pick_stops,
            )
        )
    return results


def summarize(results: list[RouteResult], cfg: SimulationConfig | None = None) -> dict:
    if not results:
        return {
            "n_batches": 0,
            "total_orders": 0,
            "total_pick_lines": 0,
            "total_pick_stops": 0,
            "total_distance_m": 0.0,
            "avg_distance_m": 0.0,
            "total_route_time_sec": 0.0,
            "avg_cycle_time_sec": 0.0,
            "avg_time_per_order_sec": 0.0,
            "total_travel_time_sec": 0.0,
            "total_pick_time_sec": 0.0,
            "total_setup_time_sec": 0.0,
            "throughput_orders_per_hr": 0.0,
            "pick_time_basis": cfg.pick_time_basis if cfg is not None else "order_line",
        }
    setup_time_sec = cfg.setup_time_sec if cfg is not None else 10.0
    total_dist = sum(r.distance_m for r in results)
    total_cycle = sum(r.cycle_time_sec for r in results)
    total_orders = sum(r.n_orders for r in results)
    total_travel = sum(r.travel_time_sec for r in results)
    total_pick = sum(r.pick_time_sec for r in results)
    total_pick_lines = sum(r.n_pick_lines for r in results)
    total_pick_stops = sum(r.n_pick_stops for r in results)
    return {
        "n_batches": len(results),
        "total_orders": total_orders,
        "total_pick_lines": total_pick_lines,
        "total_pick_stops": total_pick_stops,
        "total_distance_m": round(total_dist, 2),
        "avg_distance_m": round(total_dist / len(results), 2),
        "total_route_time_sec": round(total_cycle, 2),
        "avg_cycle_time_sec": round(total_cycle / len(results), 2),
        "avg_time_per_order_sec": round(total_cycle / total_orders, 2) if total_orders else 0.0,
        "total_travel_time_sec": round(total_travel, 2),
        "total_pick_time_sec": round(total_pick, 2),
        "total_setup_time_sec": round(len(results) * setup_time_sec, 2),
        "throughput_orders_per_hr": round(total_orders / (total_cycle / 3600), 2) if total_cycle > 0 else 0.0,
        "pick_time_basis": cfg.pick_time_basis if cfg is not None else "order_line",
    }
