"""Order-line travel for the slotting benchmark (Phase 3, D29 + D35).

Why this module exists
----------------------
The Phase 2 optimizer measured travel as ``sum over assignment records`` of
``demand x distance``. That counts a SKU once per *bin* it occupies, so deleting a
record looked like an improvement whether or not any pick got shorter. The
authoritative quantity is per **order line**: how far a picker walks to serve one
line, aggregated over the workload.

Two pick rules are implemented because the simulator's rule is a modelling choice,
not a law:

``all_bins``
    The picker visits every bin holding the SKU (the v1 simulator's behaviour).
    Distance = sum of depot->bin distances for all of that SKU's bins.

``quantity_aware``
    The picker visits the nearest bins until the line's quantity is covered.
    Distance = sum of depot->bin distances of the bins actually used. If one bin
    cannot cover the line, the next nearest is added.

Definitions (also in docs/PHASE_3_EXPERIMENTS_AND_DEMAND_METRICS.md)
-------------------------------------------------------------------
``T`` per line      = sum of depot->bin distances for the stops that line causes
``demand_weighted_depot_distance``
                    = sum of ``T`` over the **resolved** order lines in the workload
                      numerator: total metres
                      denominator: number of resolved lines
                      ``mean_per_line_m = numerator / denominator``

The aggregate is demand-weighted by construction: a SKU ordered in 200 lines
contributes 200 distances, a SKU ordered once contributes one. No second
multiplication by quantity is applied — the unit of account is the line, and a
line's quantity only decides how many bins are visited under ``quantity_aware``.

Unresolved lines are **accounted for, not dropped silently**
-----------------------------------------------------------
A line whose SKU has no assigned bin, or whose selected bin has no distance, cannot
be priced. It is excluded from the numerator *and* the denominator, but it is
returned in ``unresolved_lines`` and reported as ``lines_unresolved`` with
``lines_total`` and ``coverage_pct``. A consumer can therefore see how much of the
workload the aggregate actually covers; a coverage below 100 % downgrades the
result rather than quietly shrinking it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

import pandas as pd

ALL_BINS = "all_bins"
QUANTITY_AWARE = "quantity_aware"
RULES = (ALL_BINS, QUANTITY_AWARE)

REASON_NO_ASSIGNMENT = "no_assignment"
REASON_MISSING_DISTANCE = "missing_distance"


@dataclass(frozen=True)
class LineTravel:
    """Travel caused by one resolved order line."""

    order_id: str
    sku_id: str
    quantity: int
    stops: tuple[str, ...]
    distance_m: float
    quantity_short: int = 0

    @property
    def n_stops(self) -> int:
        return len(self.stops)


@dataclass(frozen=True)
class UnresolvedLine:
    """An order line that cannot be priced, with the reason it cannot."""

    order_id: str
    sku_id: str
    quantity: int
    reason: str


@dataclass(frozen=True)
class TravelResult:
    rule: str
    lines: tuple[LineTravel, ...]
    unresolved_lines: tuple[UnresolvedLine, ...]

    # -- back-compat accessor: unique SKU ids with an unresolved line -----------
    @property
    def unresolved(self) -> tuple[str, ...]:
        return tuple(sorted({u.sku_id for u in self.unresolved_lines}))

    @property
    def numerator_m(self) -> float:
        return sum(l.distance_m for l in self.lines)

    @property
    def denominator_lines(self) -> int:
        """Lines actually priced (the denominator of ``mean_per_line_m``)."""
        return len(self.lines)

    @property
    def lines_total(self) -> int:
        return len(self.lines) + len(self.unresolved_lines)

    @property
    def coverage_pct(self) -> float | None:
        if not self.lines_total:
            return None
        return 100.0 * self.denominator_lines / self.lines_total

    @property
    def mean_per_line_m(self) -> float | None:
        return (self.numerator_m / self.denominator_lines) if self.denominator_lines else None

    @property
    def units_short(self) -> int:
        return sum(l.quantity_short for l in self.lines)

    def aggregate(self) -> dict:
        return {
            "rule": self.rule,
            "demand_weighted_depot_distance": round(self.numerator_m, 3),
            "numerator_m": round(self.numerator_m, 3),
            "denominator_lines": self.denominator_lines,
            "lines_total": self.lines_total,
            "lines_unresolved": len(self.unresolved_lines),
            "unresolved_skus": len(self.unresolved),
            "coverage_pct": round(self.coverage_pct, 4) if self.coverage_pct is not None else None,
            "mean_per_line_m": (
                round(self.mean_per_line_m, 4) if self.mean_per_line_m is not None else None
            ),
            "stops": sum(l.n_stops for l in self.lines),
            "lines_quantity_short": sum(1 for l in self.lines if l.quantity_short > 0),
            "units_short": self.units_short,
            "unit": "m",
            "priced_lines_only": True,
        }


def sku_bins(
    assignments: pd.DataFrame,
    location_distance_m: Mapping[str, float],
) -> dict[str, list[tuple[str, int, float]]]:
    """sku -> [(location_id, qty, depot_distance_m)] sorted nearest first.

    ``assignments`` needs ``sku_id``, ``location_id``, ``assigned_quantity``.
    Bins whose distance is missing are kept with ``inf`` so they can be reported
    rather than silently dropped.
    """
    out: dict[str, list[tuple[str, int, float]]] = {}
    for row in assignments.itertuples(index=False):
        dist = location_distance_m.get(row.location_id)
        out.setdefault(row.sku_id, []).append(
            (row.location_id, int(row.assigned_quantity), float(dist) if dist is not None else float("inf"))
        )
    for sku in out:
        out[sku].sort(key=lambda t: (t[2], t[0]))
    return out


def line_travel(
    order_items: pd.DataFrame,
    bins: Mapping[str, Sequence[tuple[str, int, float]]],
    rule: str,
) -> TravelResult:
    """Compute per-line travel for one workload and one pick rule."""
    if rule not in RULES:
        raise ValueError(f"unknown pick rule {rule!r}; expected one of {RULES}")

    lines: list[LineTravel] = []
    unresolved: list[UnresolvedLine] = []

    ordered = order_items.sort_values(
        ["order_id", "sku_id", "quantity"], kind="mergesort"
    )
    for row in ordered.itertuples(index=False):
        quantity = int(row.quantity)
        sku_bins_for = bins.get(row.sku_id)
        if not sku_bins_for:
            unresolved.append(
                UnresolvedLine(str(row.order_id), str(row.sku_id), quantity, REASON_NO_ASSIGNMENT)
            )
            continue

        if rule == ALL_BINS:
            stops = tuple(loc for loc, _q, _d in sku_bins_for)
            distance = sum(d for _l, _q, d in sku_bins_for)
            short = max(0, quantity - sum(max(q, 0) for _l, q, _d in sku_bins_for))
        else:  # quantity_aware
            remaining = quantity
            used: list[tuple[str, float]] = []
            for loc, qty, dist in sku_bins_for:
                if remaining <= 0:
                    break
                used.append((loc, dist))
                remaining -= max(qty, 0)
            stops = tuple(loc for loc, _d in used)
            distance = sum(d for _l, d in used)
            short = max(0, remaining)

        # An unreachable bin makes the distance unknown. Report the line as
        # unresolved instead of charging infinity or pretending it costs zero.
        if not _finite(distance):
            unresolved.append(
                UnresolvedLine(str(row.order_id), str(row.sku_id), quantity, REASON_MISSING_DISTANCE)
            )
            continue

        lines.append(
            LineTravel(
                order_id=str(row.order_id),
                sku_id=str(row.sku_id),
                quantity=quantity,
                stops=stops,
                distance_m=float(distance),
                quantity_short=short,
            )
        )

    return TravelResult(rule=rule, lines=tuple(lines), unresolved_lines=tuple(unresolved))


def _finite(value: float) -> bool:
    return value == value and value not in (float("inf"), float("-inf"))


def line_travel_table(result: TravelResult) -> pd.DataFrame:
    """Auditable per-line artifact: one row per priced order line with its stops."""
    return pd.DataFrame(
        [
            {
                "order_id": l.order_id,
                "sku_id": l.sku_id,
                "quantity": l.quantity,
                "n_stops": l.n_stops,
                "stops": ";".join(l.stops),
                "distance_m": round(l.distance_m, 6),
                "quantity_short": l.quantity_short,
            }
            for l in result.lines
        ]
    )


def unresolved_travel_table(result: TravelResult) -> pd.DataFrame:
    """The lines the aggregate could not price, with the reason for each."""
    return pd.DataFrame(
        [
            {
                "order_id": u.order_id,
                "sku_id": u.sku_id,
                "quantity": u.quantity,
                "reason": u.reason,
            }
            for u in result.unresolved_lines
        ],
        columns=["order_id", "sku_id", "quantity", "reason"],
    )


def compare_rules(order_items: pd.DataFrame, bins: Mapping[str, Sequence[tuple[str, int, float]]]) -> dict:
    """Both rules over the same workload — the pick-rule sensitivity experiment."""
    out = {}
    for rule in RULES:
        res = line_travel(order_items, bins, rule)
        out[rule] = res.aggregate()
        out[rule]["_result"] = res
    return out
