"""CAT-01 (category separation) gate for placement.

The validator answers "is this finished layout legal?". This module answers the cheaper,
forward-direction question the *placer* needs before it commits a bin:

    "may I put a bin of category X at (x, y, z) without coming within R metres of a
     bin that already holds a forbidden partner of X?"

It is a uniform 3-D grid with cell size R. Any point within R of a query point lies in the
query cell or one of its 26 neighbours, so a lookup touches a bounded set of cells instead
of the whole layout: O(27 x |forbidden partners|) dictionary probes per candidate, not
O(N^2) pairwise distance over all placed bins.

The grid only ever stores bins that an assignment has been *committed* to, so asking about a
candidate cannot mutate state; ``add`` is the only mutator and is called after the caller has
decided to place.

The validator keeps its own implementation of the same rule from the same rule data — the
placer predicting the validator is not the same as the validator agreeing with the placer.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Iterable

# The validator accepts a pair when ``distance + 1e-9 >= radius``; the placer must reject
# exactly when the validator would, so the same tolerance is applied here.
DISTANCE_TOLERANCE_M = 1e-9

_NEIGHBOUR_OFFSETS = tuple(
    (dx, dy, dz) for dx in (-1, 0, 1) for dy in (-1, 0, 1) for dz in (-1, 0, 1)
)


def forbidden_pairs_from_rules(rules: Iterable) -> set[frozenset[str]]:
    """Category pairs that must be separated, derived from the compatibility matrix.

    Self-pairs are not separation constraints (a category is always within R of itself).
    """
    pairs: set[frozenset[str]] = set()
    for rule in rules or ():
        if getattr(rule, "allowed", False):
            continue
        a, b = rule.category_a, rule.category_b
        if a == b:
            continue
        pairs.add(frozenset((a, b)))
    return pairs


class SeparationGrid:
    """Occupancy grid of placed bins per category, keyed by R-sized cells."""

    def __init__(self, radius_m: float, forbidden_pairs: Iterable[frozenset[str]] = ()):
        self.radius_m = float(radius_m)
        self.forbidden_pairs = set(forbidden_pairs or ())
        # A radius of 0 means "no distance rule"; the validator skips CAT-01 entirely then.
        self.enabled = self.radius_m > 0 and bool(self.forbidden_pairs)
        self._partners: dict[str, tuple[str, ...]] = {}
        if self.enabled:
            partners: dict[str, set[str]] = defaultdict(set)
            for pair in self.forbidden_pairs:
                a, b = tuple(pair)
                if a == b:
                    continue
                partners[a].add(b)
                partners[b].add(a)
            self._partners = {cat: tuple(sorted(others)) for cat, others in partners.items()}
        self._cells: dict[
            tuple[int, int, int], dict[str, list[tuple[float, float, float]]]
        ] = defaultdict(dict)
        self.n_placed_bins = 0
        self.n_rejections = 0
        self.n_queries = 0

    # -- geometry -------------------------------------------------------------
    def cell(self, loc) -> tuple[int, int, int]:
        """Cell index of a bin; identical arithmetic to the validator's cell mapping."""
        size = self.radius_m
        return (math.floor(loc.x / size), math.floor(loc.y / size), math.floor(loc.z / size))

    @property
    def n_cells(self) -> int:
        return len(self._cells)

    # -- queries --------------------------------------------------------------
    def allows(self, loc, category_id: str) -> bool:
        """True when placing ``category_id`` at ``loc`` keeps every forbidden pair >= R apart."""
        if not self.enabled:
            return True
        partners = self._partners.get(category_id)
        if not partners:
            return True
        self.n_queries += 1
        cx, cy, cz = self.cell(loc)
        x, y, z = loc.x, loc.y, loc.z
        radius = self.radius_m
        for dx, dy, dz in _NEIGHBOUR_OFFSETS:
            bucket = self._cells.get((cx + dx, cy + dy, cz + dz))
            if bucket is None:
                continue
            for partner in partners:
                points = bucket.get(partner)
                if not points:
                    continue
                for px, py, pz in points:
                    if math.dist((x, y, z), (px, py, pz)) + DISTANCE_TOLERANCE_M < radius:
                        self.n_rejections += 1
                        return False
        return True

    def add(self, loc, category_id: str) -> None:
        """Record a committed placement."""
        if not self.enabled:
            return
        bucket = self._cells[self.cell(loc)]
        bucket.setdefault(category_id, []).append((loc.x, loc.y, loc.z))
        self.n_placed_bins += 1

    def diagnostics(self) -> dict:
        return {
            "radius_m": self.radius_m,
            "enabled": self.enabled,
            "forbidden_pairs": len(self.forbidden_pairs),
            "cells": self.n_cells,
            "bins_indexed": self.n_placed_bins,
            "queries": self.n_queries,
            "rejections": self.n_rejections,
        }
