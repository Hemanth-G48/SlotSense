"""Phase-5 allocation optimizer (inventory-conserving).

Greedy feasible starter + simulated-annealing local search. Key correctness properties:

1. INVENTORY CONSERVATION: each SKU's real on-hand quantity must be placed across its bins —
   never fabricated, never dropped. If one on-hand exceeds a single bin's capacity/volume, the
   SKU spans multiple bins until the whole quantity is stored. A SKU that cannot be fully
   placed is reported with the constraint that bound it (never silently truncated).
2. The starter is CONSTRAINT-AWARE: it honours the same four structural scopes the validator
   checks (bin / beam / level / rack), aggregated exactly as the validator aggregates them,
   and it refuses a bin whose category would break CAT-01 separation. Its output is therefore
   not merely "probably feasible" — every placement is bounded by the same limits the
   validator will later re-check independently.
3. Every candidate (starter and each neighbour) is re-validated with the full Phase-4 validator
   (which enforces zone/hazard/handling/heavy-height/structural/inventory/completeness), so a
   local-search move can never leave a hard violation behind.
4. REPAIR IS CONSTRAINT-SAFE: if the chosen starter is infeasible (e.g. a caller supplied an
   infeasible baseline as the start), a bounded, deterministic repair loop proposes relocate and
   swap moves, screens each one with the FULL validator, and only accepts a move that removes
   violations without creating any new one elsewhere. If it cannot reach feasibility within its
   bounds the best layout found is returned and the run is reported INFEASIBLE — never as success.
5. Objective is demand-weighted travel + proximity-based affinity + ergonomics + utilization.
"""

from __future__ import annotations

import logging
import math
import random
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Callable

from src.models.config import DEFAULT_SEPARATION_RADIUS_M
from src.models.entities import AssignmentType, SKU, StorageAssignment, Warehouse
from src.validation.validator import HEAVY_MAX_SHELF_LEVEL, Validator

from .objective import Objective
from .separation import SeparationGrid, forbidden_pairs_from_rules

logger = logging.getLogger(__name__)

GOLDEN_SHELF_LEVELS = {2}

# Float slack when comparing weights against a structural limit. The validator's own
# tolerance is 1e-6; being an order of magnitude tighter here means the starter can never
# land on the "just over the line" side of a beam/level/rack comparison.
WEIGHT_EPSILON_KG = 1e-9

# Binding reasons reported for a SKU that could not be fully placed (see greedy_starter).
BINDING_FIT = "fit"
BINDING_HAZARD = "hazard"
BINDING_HANDLING = "handling"
BINDING_CAPACITY = "capacity"
BINDING_SEPARATION = "separation"

# Severity ranking used ONLY by the repair loop to compare two layouts with the same number
# of violations. Feasibility itself is never decided here — the independent validator decides.
REPAIR_SEVERITY_WEIGHT = {"high": 1000, "medium": 100, "low": 10, "info": 1}

# Candidate generations the repair loop can use.
#   ``objective``   — the Phase-2 neighbourhood: relocate toward dispatch, then swap. Moves are
#                     ordered by a travel proxy, which is right for *improving* a layout.
#   ``feasibility`` — the baseline-repair neighbourhood: relocate to the nearest bin that the
#                     placer predicts is already legal, and swap only as a last resort. Nothing
#                     in it consults the objective, so a repair driven this way cannot optimise
#                     travel, affinity, ergonomics or utilisation; it can only remove hard
#                     violations with the smallest move it can find.
CANDIDATE_MODE_OBJECTIVE = "objective"
CANDIDATE_MODE_FEASIBILITY = "feasibility"
CANDIDATE_MODES = (CANDIDATE_MODE_OBJECTIVE, CANDIDATE_MODE_FEASIBILITY)


@dataclass
class RepairConfig:
    """Bounds for the deterministic repair loop.

    ``max_moves`` counts full-validator candidate evaluations (the expensive unit of work);
    ``max_seconds`` is the wall-clock backstop. ``max_candidates_per_record`` keeps the
    neighbourhood of a single record finite and sorted, so the same input always yields the
    same sequence of moves. ``candidate_mode`` selects the neighbourhood (see
    ``CANDIDATE_MODES``); it changes only *which* candidates are proposed, never the rule that
    accepts them — every candidate is still judged by the full validator.
    """

    max_moves: int = 400
    max_seconds: float = 20.0
    max_candidates_per_record: int = 40
    max_problem_records: int = 80
    candidate_mode: str = CANDIDATE_MODE_OBJECTIVE

    def __post_init__(self) -> None:
        if self.candidate_mode not in CANDIDATE_MODES:
            raise ValueError(
                f"candidate_mode must be one of {CANDIDATE_MODES}, got {self.candidate_mode!r}"
            )
        if self.max_moves < 0 or self.max_seconds < 0:
            raise ValueError("repair bounds must be >= 0")



@dataclass
class RepairStats:
    """Everything the repair loop did, reported verbatim in the optimization summary."""

    enabled: bool = True
    initial_violations: int = 0
    final_violations: int = 0
    initial_violations_by_rule: dict[str, int] = field(default_factory=dict)
    final_violations_by_rule: dict[str, int] = field(default_factory=dict)
    initial_severity_score: int = 0
    final_severity_score: int = 0
    moves_attempted: int = 0
    moves_accepted: int = 0
    moves_rejected: int = 0
    cycles_detected: int = 0
    unresolved_violations: int = 0
    termination_reason: str = "not_run"
    feasible: bool = False
    runtime_sec: float = 0.0
    max_moves: int = 0
    max_seconds: float = 0.0
    candidate_mode: str = CANDIDATE_MODE_OBJECTIVE

    def to_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "candidate_mode": self.candidate_mode,
            "initial_violations": self.initial_violations,
            "final_violations": self.final_violations,
            "initial_violations_by_rule": self.initial_violations_by_rule,
            "final_violations_by_rule": self.final_violations_by_rule,
            "initial_severity_score": self.initial_severity_score,
            "final_severity_score": self.final_severity_score,
            "moves_attempted": self.moves_attempted,
            "moves_accepted": self.moves_accepted,
            "moves_rejected": self.moves_rejected,
            "cycles_detected": self.cycles_detected,
            "unresolved_violations": self.unresolved_violations,
            "termination_reason": self.termination_reason,
            "feasible": self.feasible,
            "runtime_sec": round(self.runtime_sec, 3),
            "max_moves": self.max_moves,
            "max_seconds": self.max_seconds,
        }


@dataclass
class UnplacedSku:
    """A SKU (or the remainder of one) the starter could not place, with its binding reason."""

    sku_id: str
    units_required: int
    units_unplaced: int
    binding_reason: str
    detail: str

    def to_dict(self) -> dict:
        return {
            "sku_id": self.sku_id,
            "units_required": self.units_required,
            "units_unplaced": self.units_unplaced,
            "binding_reason": self.binding_reason,
            "detail": self.detail,
        }


@dataclass
class OptimizationLog:
    initial_score: float | None = None
    final_score: float | None = None
    n_moves_evaluated: int = 0
    n_moves_accepted: int = 0
    runtime_sec: float = 0.0
    starter_score: float | None = None
    feasibility_status: str = "not_run"
    stopping_reason: str = ""
    n_assigned: int = 0
    inventory_units: int = 0
    separation_radius_m: float = DEFAULT_SEPARATION_RADIUS_M
    units_placed: int = 0
    n_bins_used: int = 0
    unplaced_skus: list[UnplacedSku] = field(default_factory=list)
    separation_stats: dict | None = None
    starter_beam_violations: int | None = None
    starter_feasible: bool | None = None
    repair: dict | None = None
    objective_components: dict | None = None

    @property
    def units_unplaced(self) -> int:
        return sum(u.units_unplaced for u in self.unplaced_skus)

    def to_dict(self) -> dict:
        return {
            "initial_objective": self.initial_score,
            "starter_objective": self.starter_score,
            "final_objective": self.final_score,
            "moves_evaluated": self.n_moves_evaluated,
            "moves_accepted": self.n_moves_accepted,
            "runtime_sec": round(self.runtime_sec, 3),
            "feasibility_status": self.feasibility_status,
            "stopping_reason": self.stopping_reason,
            "n_assigned": self.n_assigned,
            "inventory_units": self.inventory_units,
            "units_placed": self.units_placed,
            "units_unplaced": self.units_unplaced,
            "n_bins_used": self.n_bins_used,
            "separation_radius_m": self.separation_radius_m,
            "separation_grid": self.separation_stats,
            "unplaced_skus": [u.to_dict() for u in self.unplaced_skus],
            "starter_feasible": self.starter_feasible,
            "repair": self.repair,
            "objective_components": self.objective_components,
            "globally_optimal": False,
        }



@dataclass
class OptimizerConfig:
    seed: int = 7
    max_iterations: int = 600
    anneal_start: float = 5.0
    anneal_end: float = 0.01
    # "legacy" preserves Phase 2-6 behaviour exactly. "targeted" proposes relocation
    # only into currently empty bins, biased to the nearest feasible distances.
    neighborhood: str = "legacy"
    repair: RepairConfig = field(default_factory=RepairConfig)

    def __post_init__(self) -> None:
        if self.neighborhood not in ("legacy", "targeted"):
            raise ValueError(
                f"neighborhood must be 'legacy' or 'targeted', got {self.neighborhood!r}"
            )


class SlottingOptimizer:
    def __init__(
        self,
        warehouse: Warehouse,
        skus: dict[str, SKU],
        abc_classes: dict[str, str],
        validator: Validator,
        inventory: dict[str, int],
        affinity_penalty: dict[frozenset[str], float] | None = None,
        objective: Objective | None = None,
        demand: dict[str, float] | None = None,
        cfg: OptimizerConfig | None = None,
        initial_assignments: list[StorageAssignment] | None = None,
        separation_radius_m: float | None = None,
        compatibility_rules: list | None = None,
        replenishment_fn: Callable[[list[StorageAssignment]], float] | None = None,
    ):
        self.warehouse = warehouse
        self.skus = skus
        self.abc = abc_classes
        self.validator = validator
        self.inventory = inventory
        self.affinity = affinity_penalty or {}
        self.objective = objective or Objective()
        self.demand = demand or {}
        self.cfg = cfg or OptimizerConfig()
        self.initial_assignments = initial_assignments or []
        self.replenishment_fn = replenishment_fn
        self.rng = random.Random(self.cfg.seed)
        self.log = OptimizationLog()
        self._feasible_cache: dict[str, list] = {}

        # One radius, one source. Defaulting to the validator's value keeps callers that
        # construct an optimizer by hand consistent; an explicit disagreement is a bug, not
        # something to paper over, because the placer would then predict a different rule
        # than the one that judges it.
        validator_radius = float(getattr(validator, "separation_radius_m", DEFAULT_SEPARATION_RADIUS_M))
        if separation_radius_m is None:
            self.separation_radius_m = validator_radius
        else:
            self.separation_radius_m = float(separation_radius_m)
            if abs(self.separation_radius_m - validator_radius) > 1e-12:
                raise ValueError(
                    "separation_radius_m mismatch: optimizer got "
                    f"{self.separation_radius_m} m but its validator uses {validator_radius} m; "
                    "thread both from the same config value"
                )

        rules = compatibility_rules if compatibility_rules is not None else getattr(validator, "rules", [])
        self.separation = SeparationGrid(
            self.separation_radius_m, forbidden_pairs_from_rules(rules)
        )
        self._unplaced: list[UnplacedSku] = []


    def _velocity(self, sku_id: str) -> float:
        return self.demand.get(sku_id, 0.0)

    def _replenishment(self, assignments: list[StorageAssignment]) -> float | None:
        """Psi_R for a candidate, computed only when the weight is non-zero.

        Keeping the short-circuit here means epsilon=0.0 costs exactly nothing, so the
        Phase 2 objective is reproduced bit-for-bit until a caller enables the term.
        """
        if self.replenishment_fn is None or self.objective.epsilon == 0.0:
            return None
        return float(self.replenishment_fn(assignments))

    def _score(self, assignments: list[StorageAssignment]) -> float:
        return self.objective.evaluate(
            assignments,
            self.skus,
            self.warehouse,
            self.demand,
            self.affinity,
            self._replenishment(assignments),
        )

    def _components(self, assignments: list[StorageAssignment]) -> dict:
        return self.objective.components(
            assignments,
            self.skus,
            self.warehouse,
            self.demand,
            self.affinity,
            self._replenishment(assignments),
        )

    def _feasible_bins_for(self, sku: SKU) -> list:
        """Bins a SKU's unit can be placed in (per-dimension fit + zone/hazard/handling + heavy height)."""
        cached = self._feasible_cache.get(sku.sku_id)
        if cached is not None:
            return cached
        out = []
        for loc in self.warehouse.locations.values():
            if not _dims_fit(sku, loc):
                continue
            if sku.hazard_class.value not in loc.allowed_hazard:
                continue
            if sku.handling_type.value not in loc.allowed_handling:
                continue
            if sku.handling_type.value == "heavy" and loc.shelf_level > HEAVY_MAX_SHELF_LEVEL:
                continue
            out.append(loc)
        self._feasible_cache[sku.sku_id] = out
        return out

    def _nearest_feasible(self, sku: SKU, prefer_golden: bool = True):
        """Shortlist feasible bins near dispatch, golden shelves first, with zone edge preference."""
        feasible = self._feasible_bins_for(sku)
        # Prefer zone edges (bins at the outer boundaries of zones)
        # Zone edges are at the extremes of each zone's y-coordinate range
        def _zone_edge_priority(loc):
            # Determine which zone this bin belongs to
            zone_idx = None
            for i in range(len(self.warehouse.zones)):
                # Zone y-bands are spaced at regular intervals
                zone_y_offset = i * (self.warehouse.cfg.aisles_per_zone * 2 * self.warehouse.cfg.aisle_spacing_m + 2 * self.warehouse.cfg.rack_depth_m)
                # Check if loc.y is within this zone's band
                zone_width = self.warehouse.cfg.aisles_per_zone * 2 * self.warehouse.cfg.aisle_spacing_m + 2 * self.warehouse.cfg.rack_depth_m
                if abs(loc.y - zone_y_offset) < zone_width / 2:
                    zone_idx = i
                    break
            # Edge bins are those near the outer boundaries of their zone
            if zone_idx is not None:
                zone_y_offset = zone_idx * (self.warehouse.cfg.aisles_per_zone * 2 * self.warehouse.cfg.aisle_spacing_m + 2 * self.warehouse.cfg.rack_depth_m)
                zone_width = self.warehouse.cfg.aisles_per_zone * 2 * self.warehouse.cfg.aisle_spacing_m + 2 * self.warehouse.cfg.rack_depth_m
                distance_from_zone_center = abs(loc.y - zone_y_offset - zone_width / 2)
                # Bins closer to the zone edge (farther from center) get higher priority
            return loc.distance_to_dispatch_m if loc.distance_to_dispatch_m > 0 else (abs(loc.x - 20.4) + abs(loc.y - 0.5))
        # Sort by zone edge priority first, then by distance from dispatch
        def _dist(l):
            return l.distance_to_dispatch_m if l.distance_to_dispatch_m > 0 else (abs(l.x - 20.4) + abs(l.y - 0.5))
        return sorted(feasible, key=lambda l: (_zone_edge_priority(l), _dist(l)))

    # -- structural residual bookkeeping ---------------------------------------
    @staticmethod
    def _structural_caps(locations) -> tuple[dict, dict, dict]:
        """Per-scope structural capacity, aggregated exactly as the validator aggregates it.

        beam  -> (rack_id, bay, shelf_level) against ``beam_max_weight_kg``   (SL-02)
        level -> (rack_id, shelf_level)      against ``level_max_weight_kg``
                                             (falling back to the legacy
                                             ``shelf_max_weight_kg`` alias)   (SL-01)
        rack  -> rack_id                     against ``rack_max_weight_kg``    (RK-01)

        For each scope the binding limit is the *minimum* over the bins in that scope, which
        is how the validator resolves a mixed-capacity beam/level/rack.
        """
        beam_cap: dict[tuple, float] = {}
        level_cap: dict[tuple, float] = {}
        rack_cap: dict[str, float] = {}
        for loc in locations:
            if loc.beam_max_weight_kg is not None:
                key = (loc.rack_id, loc.bay, loc.shelf_level)
                beam_cap[key] = min(beam_cap.get(key, loc.beam_max_weight_kg), loc.beam_max_weight_kg)
            level = (
                loc.level_max_weight_kg
                if loc.level_max_weight_kg is not None
                else loc.shelf_max_weight_kg
            )
            if level is not None:
                key = (loc.rack_id, loc.shelf_level)
                level_cap[key] = min(level_cap.get(key, level), level)
            if loc.rack_max_weight_kg is not None:
                rack_cap[loc.rack_id] = min(
                    rack_cap.get(loc.rack_id, loc.rack_max_weight_kg), loc.rack_max_weight_kg
                )
        return beam_cap, level_cap, rack_cap

    # -- static eligibility (diagnostics only) ---------------------------------
    def _eligibility_stage(self, sku: SKU) -> tuple[str, str]:
        """First static filter that leaves this SKU with no candidate bin at all."""
        locations = list(self.warehouse.locations.values())
        dims = [loc for loc in locations if _dims_fit(sku, loc)]
        if not dims:
            return (
                BINDING_FIT,
                f"no bin is at least {sku.width_cm:g}x{sku.height_cm:g}x{sku.depth_cm:g} cm "
                f"(WxHxD) among {len(locations)} bins",
            )
        hazard_ok = [loc for loc in dims if sku.hazard_class.value in loc.allowed_hazard]
        if not hazard_ok:
            accepted = sorted({h for loc in dims for h in loc.allowed_hazard})
            return (
                BINDING_HAZARD,
                f"no dimensionally-fitting bin accepts hazard class {sku.hazard_class.value} "
                f"(accepted classes: {', '.join(accepted) or 'none'})",
            )
        handling_ok = [loc for loc in hazard_ok if sku.handling_type.value in loc.allowed_handling]
        if not handling_ok:
            accepted = sorted({h for loc in hazard_ok for h in loc.allowed_handling})
            return (
                BINDING_HANDLING,
                f"no bin accepts handling type {sku.handling_type.value} "
                f"(accepted types: {', '.join(accepted) or 'none'})",
            )
        if sku.handling_type.value == "heavy":
            handling_ok = [loc for loc in handling_ok if loc.shelf_level <= HEAVY_MAX_SHELF_LEVEL]
            if not handling_ok:
                return (
                    BINDING_HANDLING,
                    f"heavy SKU has no bin at shelf level <= {HEAVY_MAX_SHELF_LEVEL} (ER-01)",
                )
        return BINDING_CAPACITY, f"{len(handling_ok)} bins pass the static eligibility filters"

    def _unplaced_reason(self, sku: SKU, blockers: Counter, eligible: int, remaining: int) -> tuple[str, str]:
        """Name the constraint that actually bound a SKU, instead of dropping it quietly.

        Blockers are ranked by how many candidate bins each one removed, because that is the
        constraint that would have to change to place the remainder. A bin held by another SKU
        under the single-SKU policy is reported as ``capacity`` (no free bin there); it is the
        only blocker that is not a rule about *this* SKU.
        """
        if eligible == 0:
            return self._eligibility_stage(sku)
        ranked = [("capacity", blockers["capacity"]), ("separation", blockers["separation"]),
                  ("occupancy", blockers["occupancy"])]
        winner, winner_count = ranked[0]
        for name, count in ranked:  # first maximum wins, i.e. capacity outranks on a tie
            if count > winner_count:
                winner, winner_count = name, count
        if winner == "occupancy" and blockers["separation"] == 0 and blockers["capacity"] == 0:
            winner = "capacity"  # every candidate bin is taken: no free bin capacity left
        reason = BINDING_SEPARATION if winner == "separation" else BINDING_CAPACITY
        parts = []
        if blockers["capacity"]:
            parts.append(
                f"{blockers['capacity']} eligible bins had no residual bin/volume/beam/level/rack capacity"
            )
        if blockers["occupancy"]:
            parts.append(f"{blockers['occupancy']} eligible bins already held another SKU")
        if blockers["separation"]:
            parts.append(
                f"{blockers['separation']} eligible bins violated CAT-01 "
                f"({self.separation_radius_m:g} m from a forbidden category)"
            )
        detail = f"{remaining} of {self.inventory[sku.sku_id]} units unplaced across {eligible} eligible bins"
        if parts:
            detail += ": " + "; ".join(parts)
        return reason, detail

    # -- greedy inventory-conserving starter ----------------------------------
    def greedy_starter(self) -> list[StorageAssignment]:
        """Place each SKU's real on-hand quantity, splitting across bins as needed.

        SKUs are processed in velocity-descending order so fast movers grab golden near-dock
        bins first. Every accepted placement is bounded by the same four load scopes the
        validator checks (bin, beam, level, rack) and by CAT-01 category separation, so the
        starter does not propose a layout its own validator will reject. If a SKU cannot be
        fully placed it is reported with the binding reason; nothing is fabricated or dropped
        silently.
        """
        locations = list(self.warehouse.locations.values())
        residual_bin_weight = {loc.location_id: loc.max_weight_kg for loc in locations}
        residual_volume = {loc.location_id: loc.usable_volume_cm3 for loc in locations}
        beam_cap, level_cap, rack_cap = self._structural_caps(locations)
        beam_load: dict[tuple, float] = defaultdict(float)
        level_load: dict[tuple, float] = defaultdict(float)
        rack_load: dict[str, float] = defaultdict(float)
        occupied_by_bin: dict[str, str] = {}  # bin -> sku_id (single-SKU policy)
        assignments: list[StorageAssignment] = []
        self._unplaced = []

        # The separation grid is per starter run: a second call must not inherit placements
        # from the first.
        self.separation = SeparationGrid(
            self.separation_radius_m, self.separation.forbidden_pairs
        )

        sku_order = sorted(
            [s for s in self.skus.values() if self.inventory.get(s.sku_id, 0) > 0],
            key=lambda s: (-self._velocity(s.sku_id), s.sku_id),
        )

        for sku in sku_order:
            required = self.inventory[sku.sku_id]
            remaining = required
            blockers: Counter = Counter()
            candidates = self._nearest_feasible(sku)
            for loc in candidates:
                if remaining <= 0:
                    break
                holder = occupied_by_bin.get(loc.location_id)
                if holder is not None and holder != sku.sku_id:
                    blockers["occupancy"] += 1
                    continue
                # CAT-01: never commit a bin that comes within the radius of a forbidden
                # category. Querying the grid does not mutate it, so a rejected candidate
                # leaves the ledger exactly as it was.
                if not self.separation.allows(loc, sku.category_id):
                    blockers["separation"] += 1
                    continue
                beam_key = (loc.rack_id, loc.bay, loc.shelf_level)
                level_key = (loc.rack_id, loc.shelf_level)
                qty = _split_quantity(
                    sku,
                    loc,
                    remaining,
                    residual_bin_weight=residual_bin_weight[loc.location_id],
                    residual_volume=residual_volume[loc.location_id],
                    residual_shelf_weight=level_cap.get(level_key, math.inf) - level_load[level_key],
                    residual_rack_weight=rack_cap.get(loc.rack_id, math.inf) - rack_load[loc.rack_id],
                    residual_beam_weight=beam_cap.get(beam_key, math.inf) - beam_load[beam_key],
                )
                if qty <= 0:
                    blockers["capacity"] += 1
                    continue
                occupied_by_bin[loc.location_id] = sku.sku_id
                weight = sku.unit_weight_kg * qty
                residual_bin_weight[loc.location_id] -= weight
                residual_volume[loc.location_id] -= sku.unit_volume_cm3 * qty
                beam_load[beam_key] += weight
                level_load[level_key] += weight
                rack_load[loc.rack_id] += weight
                self.separation.add(loc, sku.category_id)
                assignments.append(
                    StorageAssignment(sku.sku_id, loc.location_id, qty, AssignmentType.OPTIMIZED)
                )
                remaining -= qty
            if remaining > 0:
                reason, detail = self._unplaced_reason(sku, blockers, len(candidates), remaining)
                self._unplaced.append(
                    UnplacedSku(sku.sku_id, required, remaining, reason, detail)
                )
                logger.warning(
                    "SKU %s could not be fully placed: %d/%d units unplaced, binding reason=%s (%s)",
                    sku.sku_id,
                    remaining,
                    required,
                    reason,
                    detail,
                )

        self._assert_never_over_limit(
            residual_bin_weight, residual_volume, beam_cap, beam_load, level_cap, level_load,
            rack_cap, rack_load,
        )
        return assignments

    @staticmethod
    def _assert_never_over_limit(
        residual_bin_weight, residual_volume, beam_cap, beam_load,
        level_cap, level_load, rack_cap, rack_load,
    ) -> None:
        """Prove the placement ledger never crossed a limit it claims to respect.

        This is the runtime half of the guarantee: a quantity is only ever accepted when
        ``qty * unit_weight <= residual`` for every scope, so any scope where the resulting
        load exceeds its capacity by more than the float tolerance is a ledger bug, not a
        data condition, and it must fail loudly rather than hand an infeasible layout on.
        """
        breaches = []
        for key, load in beam_load.items():
            cap = beam_cap.get(key)
            if cap is not None and load > cap + WEIGHT_EPSILON_KG:
                breaches.append(f"beam {key}: {load:.6f} kg > {cap:.6f} kg")
        for key, load in level_load.items():
            cap = level_cap.get(key)
            if cap is not None and load > cap + WEIGHT_EPSILON_KG:
                breaches.append(f"level {key}: {load:.6f} kg > {cap:.6f} kg")
        for key, load in rack_load.items():
            cap = rack_cap.get(key)
            if cap is not None and load > cap + WEIGHT_EPSILON_KG:
                breaches.append(f"rack {key}: {load:.6f} kg > {cap:.6f} kg")
        for key, residual in residual_bin_weight.items():
            if residual < -WEIGHT_EPSILON_KG:
                breaches.append(f"bin {key}: residual {residual:.6f} kg < 0")
        for key, residual in residual_volume.items():
            if residual < -1e-6:
                breaches.append(f"bin {key}: residual volume {residual:.3f} cm3 < 0")
        if breaches:
            raise RuntimeError(
                "greedy_starter exceeded a structural limit it tracks (ledger invariant broken): "
                + "; ".join(breaches[:5])
            )


    # -- constraint-safe repair ---------------------------------------------------
    def _problem_bins(self, assignments, result) -> set[str]:
        """Bins implicated by the validator's violations (targeting only, not judgement).

        Bin-level rules already name the bin. Aggregate rules name a scope (rack/bay/shelf),
        so the overloaded scopes are recomputed with the same aggregation the validator uses
        and every bin carrying load in that scope is added. CAT-01 names one side of the pair;
        the counterpart bins within the radius are added too, so a swap can move either side.
        """
        locations = self.warehouse.locations
        problem: set[str] = set()
        for v in result.violations:
            if v.location_id in locations:
                problem.add(v.location_id)

        # Aggregate scopes: recompute loads exactly as the validator aggregates them.
        beam_cap, level_cap, rack_cap = self._structural_caps(locations.values())
        beam_load: dict[tuple, float] = defaultdict(float)
        level_load: dict[tuple, float] = defaultdict(float)
        rack_load: dict[str, float] = defaultdict(float)
        per_bin_weight: dict[str, float] = defaultdict(float)
        for a in assignments:
            loc = locations.get(a.location_id)
            sku = self.skus.get(a.sku_id)
            if loc is None or sku is None:
                continue
            weight = sku.unit_weight_kg * a.assigned_quantity
            if weight <= 0:
                continue
            per_bin_weight[a.location_id] += weight
            beam_load[(loc.rack_id, loc.bay, loc.shelf_level)] += weight
            level_load[(loc.rack_id, loc.shelf_level)] += weight
            rack_load[loc.rack_id] += weight
        for loc_id in per_bin_weight:
            loc = locations[loc_id]
            beam_key = (loc.rack_id, loc.bay, loc.shelf_level)
            level_key = (loc.rack_id, loc.shelf_level)
            over = (
                (beam_key in beam_cap and beam_load[beam_key] > beam_cap[beam_key] + 1e-6)
                or (level_key in level_cap and level_load[level_key] > level_cap[level_key] + 1e-6)
                or (loc.rack_id in rack_cap and rack_load[loc.rack_id] > rack_cap[loc.rack_id] + 1e-6)
            )
            if over:
                problem.add(loc_id)

        # CAT-01: add the bins on the other side of a violated forbidden pair.
        radius = self.separation_radius_m
        if radius > 0 and result.violations and any(v.rule_id == "CAT-01" for v in result.violations):
            cats_by_bin: dict[str, str] = {}
            for a in assignments:
                sku = self.skus.get(a.sku_id)
                loc = locations.get(a.location_id)
                if sku is not None and loc is not None:
                    cats_by_bin[a.location_id] = sku.category_id
            for bin_id in sorted(problem):
                loc_a = locations.get(bin_id)
                cat_a = cats_by_bin.get(bin_id)
                if loc_a is None or cat_a is None:
                    continue
                for other_id, cat_b in cats_by_bin.items():
                    if other_id == bin_id or cat_a == cat_b:
                        continue
                    if frozenset((cat_a, cat_b)) not in self.separation.forbidden_pairs:
                        continue
                    loc_b = locations.get(other_id)
                    if loc_b is None:
                        continue
                    if math.dist((loc_a.x, loc_a.y, loc_a.z), (loc_b.x, loc_b.y, loc_b.z)) + 1e-9 < radius:
                        problem.add(other_id)
        return problem

    @staticmethod
    def _record_digest(assignments) -> tuple:
        """Identity of a layout for the cycle guard (order is stable across our moves)."""
        return tuple((a.sku_id, a.location_id, a.assigned_quantity) for a in assignments)

    @staticmethod
    def _violation_breakdown(result) -> dict[str, int]:
        counts: dict[str, int] = {}
        for v in result.violations:
            counts[v.rule_id] = counts.get(v.rule_id, 0) + 1
        return dict(sorted(counts.items()))

    @staticmethod
    def _violation_keys(result) -> frozenset[tuple[str, str, str]]:
        """Identities of the violated constraints, independent of report order.

        ``Violation.identity`` uses the bin pair for CAT-01 (a violation is a property of the
        two bins, not of whichever one was reported first), so moving a bin cannot make the
        *same* pairs reappear under new keys and be misread as newly introduced violation.
        """
        return frozenset(v.identity for v in result.violations)

    @staticmethod
    def _severity_score(result) -> int:
        return sum(REPAIR_SEVERITY_WEIGHT.get(v.severity, 10) for v in result.violations)

    @classmethod
    def _is_strict_improvement(cls, before, after) -> bool:
        """Accept only a move that removes violations and introduces none elsewhere.

        - the candidate must not contain any violation key that the current layout lacks
          (a swap that trades one violation for another is rejected);
        - among candidates that pass that test, fewer violations wins, or an equal count with a
          lower severity-ordered score (a high-severity violation replaced by a medium one).
        """
        n_before = len(before.violations)
        n_after = len(after.violations)
        if not cls._violation_keys(after) <= cls._violation_keys(before):
            return False
        if n_after < n_before:
            return True
        if n_after == n_before and cls._severity_score(after) < cls._severity_score(before):
            return True
        return False

    def _repair_candidates(self, assignments, result):
        """Yield candidate layouts for the violated scopes, deterministically."""
        if self.cfg.repair.candidate_mode == CANDIDATE_MODE_FEASIBILITY:
            # Feasibility-first neighbourhood: propose only moves the placer predicts are
            # already legal, smallest displacement first. The generic neighbourhood is still
            # offered afterwards as a last resort, so a repair is never *narrower* than P2-2's.
            for cand in self._feasibility_relocations(assignments, result):
                yield cand
        for cand in self._objective_candidates(assignments, result):
            yield cand

    def _feasibility_relocations(self, assignments, result):
        """Yield relocations that the placer predicts introduce no hard violation at all.

        The prediction is not a judgement: every candidate is still validated in full before
        it can be accepted. It exists so the repair does not spend its bounded budget on moves
        that a cheap screen already knows will fail — the reason the generic neighbourhood
        needs hundreds of rejected candidates to repair a badly infeasible layout.

        A record is only proposed a bin that is

        * unoccupied and statically eligible (fit / hazard / handling / heavy height),
        * CAT-01-clear against the *current* layout (``SeparationGrid``, same rule data, same
          tolerance as the validator),
        * inside the bin's own weight and volume capacity for the record's quantity, and
        * inside the beam / level / rack residual left by the current layout, counting the
          record's departure from its old scope exactly (no double counting).

        Targets are ordered by 3-D displacement from the record's current bin, so the accepted
        move is the smallest one that clears a constraint. Dispatch distance — the travel proxy
        the objective mode orders by — is deliberately not consulted here.
        """
        locations = self.warehouse.locations
        problem_bins = self._problem_bins(assignments, result)
        if not problem_bins:
            return
        occupied: dict[str, int] = {}
        for i, a in enumerate(assignments):
            occupied.setdefault(a.location_id, i)
        free = [
            loc for loc in locations.values()
            if loc.location_id not in occupied
        ]
        if not free:
            return

        # Current loads, aggregated exactly as the validator aggregates them.
        beam_cap, level_cap, rack_cap = self._structural_caps(locations.values())
        beam_load: dict[tuple, float] = defaultdict(float)
        level_load: dict[tuple, float] = defaultdict(float)
        rack_load: dict[str, float] = defaultdict(float)
        for a in assignments:
            loc = locations.get(a.location_id)
            sku = self.skus.get(a.sku_id)
            if loc is None or sku is None:
                continue
            weight = sku.unit_weight_kg * a.assigned_quantity
            if weight > 0:
                beam_load[(loc.rack_id, loc.bay, loc.shelf_level)] += weight
                level_load[(loc.rack_id, loc.shelf_level)] += weight
                rack_load[loc.rack_id] += weight

        # CAT-01 predictor over the current layout (the validator remains the authority).
        grid = SeparationGrid(self.separation_radius_m, self.separation.forbidden_pairs)
        for a in assignments:
            loc = locations.get(a.location_id)
            sku = self.skus.get(a.sku_id)
            if loc is not None and sku is not None:
                grid.add(loc, sku.category_id)

        clear_for_category: dict[str, list] = {}

        def clear_bins(category_id: str) -> list:
            cached = clear_for_category.get(category_id)
            if cached is None:
                cached = [loc for loc in free if grid.allows(loc, category_id)]
                clear_for_category[category_id] = cached
            return cached

        cap = max(1, self.cfg.repair.max_candidates_per_record)
        indices = sorted(
            (i for i, a in enumerate(assignments) if a.location_id in problem_bins),
            key=lambda i: (assignments[i].sku_id, assignments[i].location_id, i),
        )[: self.cfg.repair.max_problem_records]

        for i in indices:
            a = assignments[i]
            sku = self.skus.get(a.sku_id)
            loc_a = locations.get(a.location_id)
            if sku is None or loc_a is None:
                continue
            weight = sku.unit_weight_kg * a.assigned_quantity
            volume = sku.unit_volume_cm3 * a.assigned_quantity
            beam_a = (loc_a.rack_id, loc_a.bay, loc_a.shelf_level)
            level_a = (loc_a.rack_id, loc_a.shelf_level)
            targets = []
            for loc in clear_bins(sku.category_id):
                if not _static_eligible(sku, loc):
                    continue
                if weight > loc.max_weight_kg + WEIGHT_EPSILON_KG:
                    continue
                if volume > loc.usable_volume_cm3 + 1e-6:
                    continue
                beam_b = (loc.rack_id, loc.bay, loc.shelf_level)
                level_b = (loc.rack_id, loc.shelf_level)
                post_beam = beam_load[beam_b] + (0.0 if beam_b == beam_a else weight)
                post_level = level_load[level_b] + (0.0 if level_b == level_a else weight)
                post_rack = rack_load[loc.rack_id] + (0.0 if loc.rack_id == loc_a.rack_id else weight)
                if beam_cap.get(beam_b) is not None and post_beam > beam_cap[beam_b] + 1e-6:
                    continue
                if level_cap.get(level_b) is not None and post_level > level_cap[level_b] + 1e-6:
                    continue
                if rack_cap.get(loc.rack_id) is not None and post_rack > rack_cap[loc.rack_id] + 1e-6:
                    continue
                targets.append(
                    (math.dist((loc_a.x, loc_a.y, loc_a.z), (loc.x, loc.y, loc.z)), loc)
                )
            targets.sort(key=lambda t: (t[0], t[1].location_id))
            for _distance, loc in targets[:cap]:
                cand = list(assignments)
                cand[i] = StorageAssignment(
                    a.sku_id, loc.location_id, a.assigned_quantity, a.assignment_type
                )
                yield cand

    def _objective_candidates(self, assignments, result):
        """Yield candidate layouts (relocate, then swap) for the violated scopes, deterministically."""
        locations = self.warehouse.locations
        problem_bins = self._problem_bins(assignments, result)
        if not problem_bins:
            return
        occupied: dict[str, int] = {}
        for i, a in enumerate(assignments):
            occupied.setdefault(a.location_id, i)

        record_indices = sorted(
            (i for i, a in enumerate(assignments) if a.location_id in problem_bins),
            key=lambda i: (assignments[i].sku_id, assignments[i].location_id, i),
        )[: self.cfg.repair.max_problem_records]
        cap = max(1, self.cfg.repair.max_candidates_per_record)

        for i in record_indices:
            a = assignments[i]
            sku = self.skus.get(a.sku_id)
            if sku is None:
                continue

            # 1. Relocate the record to an unoccupied bin that statically accepts the SKU.
            targets = []
            for loc in self._feasible_bins_for(sku):
                if loc.location_id == a.location_id:
                    continue
                holder = occupied.get(loc.location_id)
                if holder is not None and holder != i:
                    continue
                targets.append(loc)
            targets.sort(
                key=lambda l: (
                    l.distance_to_dispatch_m if l.distance_to_dispatch_m > 0 else 0.0,
                    l.location_id,
                )
            )
            for loc in targets[:cap]:
                cand = list(assignments)
                cand[i] = StorageAssignment(
                    a.sku_id, loc.location_id, a.assigned_quantity, a.assignment_type
                )
                yield cand

            # 2. Swap bins with another record when both SKUs statically accept the other's bin.
            loc_a = locations.get(a.location_id)
            if loc_a is None:
                continue
            swaps = []
            for j, b in enumerate(assignments):
                if j == i or b.location_id == a.location_id:
                    continue
                other = self.skus.get(b.sku_id)
                loc_b = locations.get(b.location_id)
                if other is None or loc_b is None:
                    continue
                if not _static_eligible(sku, loc_b) or not _static_eligible(other, loc_a):
                    continue
                swaps.append((b.sku_id, b.location_id, j))
            swaps.sort()
            for _sku, _loc, j in swaps[:cap]:
                b = assignments[j]
                cand = list(assignments)
                cand[i] = StorageAssignment(
                    a.sku_id, b.location_id, a.assigned_quantity, a.assignment_type
                )
                cand[j] = StorageAssignment(
                    b.sku_id, a.location_id, b.assigned_quantity, b.assignment_type
                )
                yield cand

    def _repair(self, assignments, result) -> tuple[list[StorageAssignment], RepairStats]:
        """Bounded, deterministic, cycle-guarded repair of an infeasible layout.

        Each accepted move strictly reduces the violation set (see ``_is_strict_improvement``),
        so the loop makes progress or stops; it never oscillates between two layouts. Returns
        the best layout found (feasible or not) plus the statistics of what it did.
        """
        cfg = self.cfg.repair
        stats = RepairStats(
            max_moves=cfg.max_moves,
            max_seconds=cfg.max_seconds,
            candidate_mode=cfg.candidate_mode,
        )
        stats.initial_violations = len(result.violations)
        stats.final_violations = len(result.violations)
        stats.initial_violations_by_rule = self._violation_breakdown(result)
        stats.final_violations_by_rule = dict(stats.initial_violations_by_rule)
        stats.initial_severity_score = self._severity_score(result)
        stats.final_severity_score = stats.initial_severity_score
        t0 = time.perf_counter()

        if result.is_feasible:
            stats.feasible = True
            stats.termination_reason = "already_feasible"
            return assignments, stats

        current, current_result = assignments, result
        seen = {hash(self._record_digest(assignments))}
        termination = "no_improving_move"
        while True:
            if current_result.is_feasible:
                termination = "feasible"
                break
            if stats.moves_attempted >= cfg.max_moves:
                termination = "max_moves"
                break
            if time.perf_counter() - t0 >= cfg.max_seconds:
                termination = "max_time"
                break
            improved = False
            for cand in self._repair_candidates(current, current_result):
                if stats.moves_attempted >= cfg.max_moves:
                    break
                if time.perf_counter() - t0 >= cfg.max_seconds:
                    break
                digest = hash(self._record_digest(cand))
                if digest in seen:
                    stats.cycles_detected += 1
                    stats.moves_rejected += 1
                    continue
                seen.add(digest)
                cand_result = self.validator.validate(cand, record_checks=False)
                stats.moves_attempted += 1
                if self._is_strict_improvement(current_result, cand_result):
                    current, current_result = cand, cand_result
                    stats.moves_accepted += 1
                    improved = True
                    break
                stats.moves_rejected += 1
            if not improved:
                if current_result.is_feasible:
                    termination = "feasible"
                elif stats.moves_attempted >= cfg.max_moves:
                    termination = "max_moves"
                elif time.perf_counter() - t0 >= cfg.max_seconds:
                    termination = "max_time"
                else:
                    termination = "no_improving_move"
                break

        stats.runtime_sec = time.perf_counter() - t0
        stats.final_violations = len(current_result.violations)
        stats.final_violations_by_rule = self._violation_breakdown(current_result)
        stats.final_severity_score = self._severity_score(current_result)
        stats.unresolved_violations = stats.final_violations
        stats.feasible = current_result.is_feasible
        stats.termination_reason = termination
        logger.info(
            "repair: %d -> %d violations (%s) in %.2fs; attempted=%d accepted=%d rejected=%d cycles=%d",
            stats.initial_violations, stats.final_violations, termination, stats.runtime_sec,
            stats.moves_attempted, stats.moves_accepted, stats.moves_rejected, stats.cycles_detected,
        )
        return current, stats

    # -- local search / annealing ------------------------------------------------
    def _refine(self, assignments) -> list[StorageAssignment]:
        """Improve a layout with annealing moves that pass the full validator.

        Only feasible candidates are ever accepted, so a refinement pass can neither create nor
        retain a hard violation. If the input is infeasible and no feasible neighbour is found,
        the input is returned unchanged and the caller reports it as INFEASIBLE.
        """
        current = assignments
        current_result = self.validator.validate(current, record_checks=False)
        current_score = (
            self._score(current)
            if current_result.is_feasible
            else math.inf
        )
        best = current if current_result.is_feasible else None
        best_score = current_score
        T = self.cfg.anneal_start
        n_moves = 0
        accepted = 0

        for _ in range(self.cfg.max_iterations):
            n_moves += 1
            cand = self._random_neighbor(current)
            if cand is None:
                T = max(self.cfg.anneal_end, T * 0.995)
                continue
            cand_result = self.validator.validate(cand, record_checks=False)
            if cand_result.is_feasible:
                score = self._score(cand)
                if (
                    math.isinf(current_score)
                    or score < current_score
                    or self.rng.random() < _anneal_accept(T, score - current_score)
                ):
                    current, current_score = cand, score
                    accepted += 1
                    if best is None or score < best_score:
                        best, best_score = cand, score
            T = max(self.cfg.anneal_end, T * 0.995)

        self.log.n_moves_evaluated = n_moves
        self.log.n_moves_accepted = accepted
        return assignments if best is None else best

    def _random_neighbor(self, assignments):
        """Swap two records' bins, or move one record to another feasible bin.

        Both operations keep per-SKU totals fixed, so inventory conservation is invariantly
        preserved; the validator still checks it.
        """
        if not assignments:
            return None
        cand = [StorageAssignment(x.sku_id, x.location_id, x.assigned_quantity, x.assignment_type) for x in assignments]
        # Swap needs two records; relocation works for one. Keep the RNG call order
        # identical for layouts with >= 2 records so frozen Phase 2-5 layouts remain
        # bit-comparable; only the previously unreachable single-record path is new.
        if len(assignments) >= 2:
            idx_a, idx_b = self.rng.sample(range(len(assignments)), 2)
            a, b = assignments[idx_a], assignments[idx_b]
            if self.rng.random() < 0.5:
                # swap bins between two (SKU, quantity) records
                cand[idx_a] = StorageAssignment(a.sku_id, b.location_id, a.assigned_quantity, a.assignment_type)
                cand[idx_b] = StorageAssignment(b.sku_id, a.location_id, b.assigned_quantity, b.assignment_type)
                return cand
        else:
            idx_a = 0
            a = assignments[0]
        # move record a to a new feasible bin for its SKU
        sku = self.skus.get(a.sku_id)
        if sku is None:
            return None
        feasible = self._feasible_bins_for(sku)
        if not feasible:
            return None
        if self.cfg.neighborhood == "targeted":
            # A relocation into an occupied bin is almost always rejected (single-SKU policy
            # or capacity), and a uniformly random feasible bin ignores distance. Restrict
            # the proposal to empty bins and bias the draw to the nearest 20.
            occupied = {x.location_id for x in assignments}
            empty = [loc for loc in feasible if loc.location_id not in occupied]
            if empty:
                empty.sort(key=lambda loc: (loc.distance_to_dispatch_m, loc.location_id))
                feasible = empty[:20]
        target = self.rng.choice(feasible)
        cand[idx_a] = StorageAssignment(a.sku_id, target.location_id, a.assigned_quantity, a.assignment_type)
        return cand

    # -- public ------------------------------------------------------------------
    def repair_feasibility_only(
        self,
        assignments: list[StorageAssignment],
        repair: RepairConfig | None = None,
    ) -> tuple[list[StorageAssignment], RepairStats]:
        """Repair a caller-supplied layout to feasibility with the objective fully disabled.

        This is the entry point the baseline repair uses. It runs the same bounded,
        cycle-guarded, full-validator-screened loop P2-2 added (``_repair``) but on the layout
        it is given, with:

        * **no scoring** — the objective is never evaluated, so travel, affinity, ergonomics and
          utilisation cannot influence which move is accepted;
        * **no starter selection** — the input layout is the layout being repaired;
        * **no refinement** — annealing is an objective-driven pass and is not run at all;
        * **a feasibility-first neighbourhood** (``RepairConfig.candidate_mode``) that proposes
          the smallest relocation that the placer predicts is legal.

        The returned layout is *not* declared feasible here. Callers must re-validate it with
        the independent validator — the statistics only describe what the loop tried.
        """
        saved = self.cfg.repair
        if repair is not None:
            self.cfg.repair = repair
        try:
            result = self.validator.validate(assignments, record_checks=False)
            return self._repair(assignments, result)
        finally:
            self.cfg.repair = saved

    def optimize(self) -> tuple[list[StorageAssignment], OptimizationLog]:
        self.log = OptimizationLog()
        self.log.separation_radius_m = self.separation_radius_m
        t0 = time.time()

        # Baseline is the reference layout: it is scored, but it is only used as a starter
        # when it is actually feasible (the greedy is the constraint-aware path).
        baseline = self.initial_assignments
        baseline_score = None
        baseline_ok = False
        if baseline:
            baseline_score = self._score(baseline)
            baseline_ok = self.validator.validate(baseline, record_checks=False).is_feasible

        greedy = self.greedy_starter()
        greedy_score = self._score(greedy)
        greedy_result = self.validator.validate(greedy, record_checks=False)
        greedy_ok = greedy_result.is_feasible
        # Diagnostics from the starter survive into the log: how many units it could not
        # place and why, and how often CAT-01 forced it onto a different bin.
        self.log.unplaced_skus = list(self._unplaced)
        self.log.separation_stats = self.separation.diagnostics()
        self.log.starter_beam_violations = sum(
            1 for v in greedy_result.violations if v.rule_id == "SL-02"
        )

        if greedy_ok and (baseline_score is None or greedy_score <= baseline_score):
            starter, starter_score = greedy, greedy_score
        elif baseline_ok:
            starter, starter_score = baseline, baseline_score
        elif greedy_ok:
            starter, starter_score = greedy, greedy_score
        else:
            starter, starter_score = greedy, greedy_score

        self.log.initial_score = baseline_score if baseline_score is not None else starter_score

        # Repair runs on the chosen starter BEFORE refinement. Refinement only accepts feasible
        # neighbours, so starting it from an infeasible layout could never fix the violations;
        # the repair loop is the component that can, and it reports exactly what it achieved.
        starter_result = self.validator.validate(starter, record_checks=False)
        repaired, repair_stats = self._repair(starter, starter_result)
        self.log.repair = repair_stats.to_dict()
        if repair_stats.moves_attempted:
            starter = repaired
            starter_result = self.validator.validate(starter, record_checks=False)
            starter_score = self._score(starter)
        self.log.starter_score = starter_score
        self.log.starter_feasible = starter_result.is_feasible

        refined = self._refine(starter)
        refined_result = self.validator.validate(refined)
        refined_score = self._score(refined)

        # Feasibility dominates the objective: never return an infeasible layout when a feasible
        # candidate exists, whatever its score.
        candidates = [(starter, starter_result, starter_score), (refined, refined_result, refined_score)]
        feasible = [c for c in candidates if c[1].is_feasible]
        if feasible:
            final, final_result, final_score = min(feasible, key=lambda c: c[2])
        else:
            final, final_result, final_score = min(
                candidates, key=lambda c: (len(c[1].violations), c[2])
            )

        self.log.final_score = final_score
        self.log.objective_components = self._components(final)
        self.log.runtime_sec = time.time() - t0
        self.log.n_assigned = len(final)
        self.log.inventory_units = sum(self.inventory.values())
        self.log.units_placed = sum(a.assigned_quantity for a in final)
        self.log.n_bins_used = len({a.location_id for a in final})
        if not final_result.is_feasible:
            self.log.feasibility_status = "INFEASIBLE"
            self.log.stopping_reason = (
                f"{len(final_result.violations)} violations after repair "
                f"({repair_stats.termination_reason}) and refinement"
            )
        else:
            self.log.feasibility_status = "FEASIBLE"
            if final is refined:
                self.log.stopping_reason = "max iterations reached (annealing)"
            elif repair_stats.moves_accepted:
                self.log.stopping_reason = (
                    f"repair reached feasibility in {repair_stats.moves_accepted} moves "
                    "(refinement did not improve)"
                )
            else:
                self.log.stopping_reason = "returned best feasible starter (refinement did not improve)"
        return final, self.log


def _static_eligible(sku: SKU, loc) -> bool:
    """Static eligibility for a (SKU, bin) pair: fit + hazard + handling + heavy height.

    This is the same filter the starter applies; the validator remains the authority.
    """
    if not _dims_fit(sku, loc):
        return False
    if sku.hazard_class.value not in loc.allowed_hazard:
        return False
    if sku.handling_type.value not in loc.allowed_handling:
        return False
    if sku.handling_type.value == "heavy" and loc.shelf_level > HEAVY_MAX_SHELF_LEVEL:
        return False
    return True


def _dims_fit(sku: SKU, loc) -> bool:
    """SP-01 dimensional fit, per dimension (the validator's rule, evaluated as a filter)."""
    return (
        sku.width_cm <= loc.width_cm
        and sku.height_cm <= loc.height_cm
        and sku.depth_cm <= loc.depth_cm
    )


def _units_affordable(residual: float, per_unit: float) -> int:
    """Largest n with ``n * per_unit <= residual``, float-safe and inf-safe.

    ``int(residual / per_unit)`` can overshoot by one unit when the division rounds up
    (e.g. 0.3 / 0.1 -> 3 with 3 * 0.1 = 0.30000000000000004 > 0.3), which would put a beam
    a hair over its limit. This trims until the comparison holds, using the same epsilon the
    placement ledger is asserted against.
    """
    if per_unit <= 0:
        return 10**9  # weightless/volumeless unit: only other scopes bind
    if math.isinf(residual):
        return 10**9
    if residual <= 0:
        return 0
    n = int(residual / per_unit)
    # Division can round either way: 0.3/0.1 -> 2.99..., while other pairs round up. Correct
    # down until the accepted weight is not over, then up while the next unit still fits, so
    # the ledger never exceeds a limit and never wastes a whole unit on a rounding artefact.
    while n > 0 and n * per_unit > residual + WEIGHT_EPSILON_KG:
        n -= 1
    while (n + 1) * per_unit <= residual:
        n += 1
    return n


def _split_quantity(
    sku: SKU,
    loc,
    wanted: int,
    residual_bin_weight: float | None = None,
    residual_volume: float | None = None,
    residual_shelf_weight: float | None = None,
    residual_rack_weight: float | None = None,
    residual_beam_weight: float | None = None,
) -> int:
    """Max units that fit loc and all of its structural parents, but <= wanted.

    Every scope the validator gates is represented: bin weight (LD-01), bin volume (VD-01),
    beam (SL-02), level (SL-01) and rack (RK-01). The returned quantity therefore satisfies
    ``qty * unit_weight <= residual`` for all of them simultaneously.
    """
    bin_weight = loc.max_weight_kg if residual_bin_weight is None else residual_bin_weight
    volume = loc.usable_volume_cm3 if residual_volume is None else residual_volume
    shelf_weight = math.inf if residual_shelf_weight is None else residual_shelf_weight
    rack_weight = math.inf if residual_rack_weight is None else residual_rack_weight
    beam_weight = math.inf if residual_beam_weight is None else residual_beam_weight
    limits = [int(wanted)]
    if sku.unit_weight_kg > 0:
        limits.extend(
            [
                _units_affordable(bin_weight, sku.unit_weight_kg),
                _units_affordable(beam_weight, sku.unit_weight_kg),
                _units_affordable(shelf_weight, sku.unit_weight_kg),
                _units_affordable(rack_weight, sku.unit_weight_kg),
            ]
        )
    if sku.unit_volume_cm3 > 0:
        limits.append(_units_affordable(volume, sku.unit_volume_cm3))
    return max(0, min(limits))


def _anneal_accept(T: float, delta: float) -> float:
    # accept worsening moves with prob exp(delta/T) where delta > 0
    if delta <= 0:
        return 1.0
    if T <= 0:
        return 0.0
    return min(1.0, 2.718281828459045 ** (-delta / T))