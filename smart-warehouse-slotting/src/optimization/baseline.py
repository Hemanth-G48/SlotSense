"""Baseline variant preparation: make the reference layout feasible without optimising it.

The Phase-1 baseline supplied with the canonical dataset is *infeasible* (1,071 CAT-01
violations at the configured 10 m radius). A comparison against an invalid layout is not
evidence, so the evaluation gate blocks it — correctly. This module produces the missing
piece: a **feasible baseline that is still a baseline**.

Design rules, in priority order:

1. **Feasibility only.** The repair is driven through
   ``SlottingOptimizer.repair_feasibility_only`` with ``CANDIDATE_MODE_FEASIBILITY``: moves are
   accepted only when the independent validator confirms they remove hard violations and add
   none, and no objective term (travel, affinity, ergonomics, utilisation) is ever evaluated.
   No annealing / refinement pass runs. The layout stays unoptimised; it only stops being
   illegal.
2. **Smallest move it can find.** Candidate targets are ordered by 3-D displacement from the
   record's current bin, not by a travel proxy, so the repair moves stock as short a distance
   as the constraints allow.
3. **Never touch the inputs.** ``dataset/processed/storage_assignments_baseline.csv`` (canonical
   input) and ``outputs/baseline_assignments.csv`` (the as-supplied copy) are read-only here.
   The repaired layout goes to ``outputs/baseline_repaired_assignments.csv``.
4. **Never fake a result.** The repaired layout is adopted only when the independent validator
   reports zero violations *and* inventory conservation holds exactly. Otherwise the run keeps
   the as-supplied baseline and the evaluation gate keeps blocking.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from src.models.config import Config
from src.models.entities import StorageAssignment
from src.models.io import write_assignments_csv
from src.validation.loader import (
    load_assignments,
    load_compatibility_rules,
    load_inventory,
    load_skus,
    load_warehouse_from_locations,
)
from src.validation.validator import Validator

from .objective import Objective
from .optimizer import (
    CANDIDATE_MODE_FEASIBILITY,
    OptimizerConfig,
    RepairConfig,
    RepairStats,
    SlottingOptimizer,
)

BASELINE_VARIANT_AS_SUPPLIED = "as_supplied"
BASELINE_VARIANT_REPAIRED_MINIMAL = "repaired_minimal"
BASELINE_VARIANTS = (BASELINE_VARIANT_AS_SUPPLIED, BASELINE_VARIANT_REPAIRED_MINIMAL)

BASELINE_SOURCE_FILENAME = "storage_assignments_baseline.csv"
BASELINE_REPAIRED_FILENAME = "baseline_repaired_assignments.csv"

# Reported verbatim next to ``baseline_variant`` in both summaries.
BASELINE_REPAIR_NOTE = (
    "Baseline repaired for feasibility only with the objective disabled: every accepted move "
    "was confirmed by the independent validator to remove hard violations and introduce none, "
    "no travel/affinity/ergonomics/utilisation term was consulted, and no refinement pass ran."
)

# Bounds large enough for a badly infeasible layout, still finite and reported in the summary.
# With the feasibility-first neighbourhood each accepted move costs one full validation, so
# 4,000 moves is a generous ceiling (the canonical baseline needs well under 200).
DEFAULT_BASELINE_REPAIR = RepairConfig(
    max_moves=4000,
    max_seconds=240.0,
    max_candidates_per_record=12,
    max_problem_records=80,
    candidate_mode=CANDIDATE_MODE_FEASIBILITY,
)


# -- conservation ----------------------------------------------------------------
def check_inventory_conservation(
    assignments: list[StorageAssignment], inventory: dict[str, int]
) -> dict:
    """Check conservation exactly, independently of the validator.

    The three failure modes are counted separately because they mean different things:

    * ``units_conserved`` — the assigned quantity per SKU equals its on-hand quantity;
    * ``duplicate_sku_bin_pairs`` — the same (SKU, bin) pinned twice (double counting);
    * ``unplaced_skus`` — SKUs with stock and no (or a wrong) placed quantity.
    """
    placed: dict[str, int] = defaultdict(int)
    pair_counts: Counter = Counter()
    unknown: set[str] = set()
    for a in assignments:
        placed[a.sku_id] += a.assigned_quantity
        pair_counts[(a.sku_id, a.location_id)] += 1
        if a.sku_id not in inventory:
            unknown.add(a.sku_id)
    duplicates = sorted(pair for pair, n in pair_counts.items() if n > 1)
    unplaced = sorted(sku for sku, qty in inventory.items() if placed.get(sku, 0) != qty)
    required = int(sum(inventory.values()))
    assigned = int(sum(a.assigned_quantity for a in assignments))
    return {
        "units_required": required,
        "units_assigned": assigned,
        "units_conserved": assigned == required,
        "skus_required": len(inventory),
        "skus_placed": len(placed),
        "unplaced_skus": unplaced,
        "unknown_skus": sorted(unknown),
        "duplicate_sku_bin_pairs": len(duplicates),
        "duplicate_examples": duplicates[:5],
        "rows": len(assignments),
        "exact": (
            assigned == required
            and not unplaced
            and not duplicates
            and not unknown
        ),
    }


# -- variant ---------------------------------------------------------------------
@dataclass
class BaselineVariant:
    """The baseline the evaluation should compare against, plus its provenance."""

    variant: str
    assignments: list[StorageAssignment]
    source: Path
    repaired_path: Path | None = None
    repair: dict | None = None
    initial_feasibility: dict = field(default_factory=dict)
    final_feasibility: dict = field(default_factory=dict)
    conservation: dict = field(default_factory=dict)
    _note: str = BASELINE_REPAIR_NOTE

    @property
    def note(self) -> str:
        if self.variant == BASELINE_VARIANT_AS_SUPPLIED:
            return "Baseline used exactly as supplied; no repair was applied."
        return self._note

    @property
    def is_repaired(self) -> bool:
        return self.variant == BASELINE_VARIANT_REPAIRED_MINIMAL

    def to_summary(self) -> dict:
        """The keys every summary records, so the baseline is never ambiguous."""
        return {
            "baseline_variant": self.variant,
            "baseline_source": str(self.repaired_path if self.is_repaired else self.source),
            "baseline_as_supplied_source": str(self.source),
            "baseline_repair": self.repair,
            "baseline_note": self.note,
        }


def _layout_feasibility(result) -> dict:
    counts: dict[str, int] = {}
    for v in result.violations:
        counts[v.rule_id] = counts.get(v.rule_id, 0) + 1
    return {
        "feasibility_status": "FEASIBLE" if result.is_feasible else "INFEASIBLE",
        "is_feasible": result.is_feasible,
        "n_violations": len(result.violations),
        "violations_by_rule": dict(sorted(counts.items())),
        "checks_run": result.checks_run,
        "top_violations": [v.reason for v in result.violations[:8]],
    }


def _movement(original, repaired, warehouse) -> dict:
    """How far the repair moved stock — the evidence that it did not re-slot the warehouse.

    ``_repair`` replaces entries in place, so row ``i`` of the repaired layout is the same
    (SKU, quantity) record as row ``i`` of the input. Comparing by index therefore measures
    the displacement of each record rather than of its bin.
    """
    if len(original) != len(repaired):
        return {"comparable": False}
    distances = []
    moved = 0
    for a, b in zip(original, repaired):
        if a.location_id == b.location_id:
            continue
        moved += 1
        loc_a = warehouse.locations.get(a.location_id)
        loc_b = warehouse.locations.get(b.location_id)
        if loc_a is None or loc_b is None:
            continue
        distances.append(math.dist((loc_a.x, loc_a.y, loc_a.z), (loc_b.x, loc_b.y, loc_b.z)))
    distances.sort()
    n = len(distances)
    return {
        "comparable": True,
        "records_total": len(original),
        "records_relocated": moved,
        "records_unchanged": len(original) - moved,
        "relocations_pct": round(100.0 * moved / len(original), 3) if original else 0.0,
        "total_displacement_m": round(sum(distances), 3),
        "mean_displacement_m": round(sum(distances) / n, 3) if n else 0.0,
        "median_displacement_m": round(distances[n // 2], 3) if n else 0.0,
        "max_displacement_m": round(distances[-1], 3) if n else 0.0,
    }


def _repair_payload(stats: RepairStats, conservation: dict, movement: dict,
                    final_feasibility: dict, path: Path) -> dict:
    payload = stats.to_dict()
    payload.update(
        {
            "attempted": True,
            "objective_enabled": False,
            "scope": "feasibility only",
            "note": BASELINE_REPAIR_NOTE,
            "output_path": str(path),
            "conservation": conservation,
            "movement": movement,
            "final_layout": final_feasibility,
        }
    )
    return payload


def prepare_baseline_variant(
    processed: Path,
    config: Config,
    out_dir: Path,
    *,
    repair_config: RepairConfig | None = None,
    enabled: bool = True,
) -> BaselineVariant:
    """Return the baseline the evaluation should use, repairing it to feasibility if needed.

    ``enabled=False`` disables the repair (the variant is then always ``as_supplied``), which is
    the behaviour every pre-existing caller and test relies on.
    """
    processed = Path(processed)
    source = processed / BASELINE_SOURCE_FILENAME
    locations = pd.read_csv(processed / "locations.csv")
    products = pd.read_csv(processed / "products.csv")
    rules = pd.read_csv(processed / "compatibility_rules.csv")
    inventory_rows = pd.read_csv(processed / "inventory.csv")
    baseline_rows = pd.read_csv(source)

    warehouse = load_warehouse_from_locations(locations)
    skus = load_skus(products)
    compatibility = load_compatibility_rules(rules)
    inventory = load_inventory(inventory_rows)
    baseline = load_assignments(baseline_rows)

    radius = config.separation_radius_m
    validator = Validator(
        skus, warehouse, compatibility, inventory=inventory, separation_radius_m=radius
    )
    initial = validator.validate(baseline)
    initial_feasibility = _layout_feasibility(initial)
    conservation = check_inventory_conservation(baseline, inventory)

    if not enabled:
        return BaselineVariant(
            variant=BASELINE_VARIANT_AS_SUPPLIED,
            assignments=baseline,
            source=source,
            repair={
                "attempted": False,
                "objective_enabled": False,
                "reason": "baseline repair disabled by the caller",
            },
            initial_feasibility=initial_feasibility,
            final_feasibility=initial_feasibility,
            conservation=conservation,
        )

    if initial.is_feasible:
        return BaselineVariant(
            variant=BASELINE_VARIANT_AS_SUPPLIED,
            assignments=baseline,
            source=source,
            repair={
                "attempted": False,
                "objective_enabled": False,
                "feasible": True,
                "reason": "baseline is already feasible; nothing to repair",
            },
            initial_feasibility=initial_feasibility,
            final_feasibility=initial_feasibility,
            conservation=conservation,
        )

    optimizer = SlottingOptimizer(
        warehouse=warehouse,
        skus=skus,
        abc_classes={},
        validator=validator,
        inventory=inventory,
        objective=Objective(),
        cfg=OptimizerConfig(seed=config.dataset.seed),
        separation_radius_m=radius,
        compatibility_rules=compatibility,
    )
    repaired, stats = optimizer.repair_feasibility_only(
        baseline, repair=repair_config or DEFAULT_BASELINE_REPAIR
    )

    # Independent, full re-validation: the repair's own statistics are not a verdict.
    final = validator.validate(repaired)
    final_feasibility = _layout_feasibility(final)
    repaired_conservation = check_inventory_conservation(repaired, inventory)
    movement = _movement(baseline, repaired, warehouse)

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    repaired_path = out_dir / BASELINE_REPAIRED_FILENAME
    write_assignments_csv(repaired, repaired_path)

    feasible = (
        final.is_feasible
        and repaired_conservation["units_conserved"]
        and repaired_conservation["duplicate_sku_bin_pairs"] == 0
    )
    payload = _repair_payload(stats, repaired_conservation, movement, final_feasibility, repaired_path)
    payload["feasible"] = bool(feasible)
    if not feasible:
        payload["rejected_because"] = (
            "the repaired layout did not pass independent validation and exact inventory "
            "conservation, so it is not adopted as the baseline"
        )

    return BaselineVariant(
        variant=BASELINE_VARIANT_REPAIRED_MINIMAL if feasible else BASELINE_VARIANT_AS_SUPPLIED,
        assignments=repaired if feasible else baseline,
        source=source,
        # The artifact is written either way so a failed attempt stays inspectable; it is only
        # *used* when it is feasible.
        repaired_path=repaired_path if feasible else None,
        repair=payload,
        initial_feasibility=initial_feasibility,
        final_feasibility=final_feasibility,
        conservation=repaired_conservation,
    )
