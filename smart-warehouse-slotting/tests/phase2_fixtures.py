"""Deterministic, tiny canonical-shaped dataset used by the Phase-2 regression suites.

Why this module exists
----------------------
Every test that needs a *pipeline* (not just a validator call) must be able to run it against
a fixture it owns: small enough to finish in seconds, deterministic, and written under the
caller's ``tmp_path``.  No test using this module reads or writes the repository's shared
``outputs/`` tree, and none of them depends on ``dataset/processed`` (that dataset stays
read-only for the benchmark-level suites).

The warehouse geometry is deliberately simple so that every rule has an unambiguous
expectation:

  * ``n_racks=2`` racks, 10 m apart in x  ->  a bin in rack 0 is >= 10 m from a bin in rack 1,
    i.e. exactly on the CAT-01 radius at the default 10 m (the rule is inclusive), so a
    forbidden pair can be legal only by being split across racks.
  * 2 bays per rack (2 m apart in y), 3 shelf levels (1 m apart in z), 2 bins per shelf
    (0.5 m apart in y) -> the validator's three structural scopes are all non-trivial:
        beam  = (rack, bay, shelf_level)   2 bins
        level = (rack, shelf_level)        4 bins
        rack  = rack                       12 bins
  * limits: bin 100 kg < beam 180 kg < level 300 kg < rack 500 kg, so each scope can be made
    to bind on its own without crossing another one first.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from src.models.config import Config
from src.models.io import write_assignments_csv
from src.optimization.pipeline import run_phase5
from src.simulation.pipeline import run_phase6
from src.validation.audit import write_constraint_audit, write_validation_checks
from src.validation.loader import load_shipping
from src.validation.validator import validate_assignment

# -- geometry / limits ---------------------------------------------------------------
RACK_PITCH_M = 10.0
BAY_PITCH_M = 2.0
BIN_PITCH_M = 0.5
LEVEL_HEIGHT_M = 1.0

N_RACKS = 2
N_BAYS = 2
N_LEVELS = 3
BINS_PER_SHELF = 2

BIN_LIMIT_KG = 100.0
BEAM_LIMIT_KG = 180.0
LEVEL_LIMIT_KG = 300.0
RACK_LIMIT_KG = 500.0

UNIT_DIMS_CM = (10.0, 10.0, 10.0)
BIN_DIMS_CM = (60.0, 40.0, 45.0)
BIN_VOLUME_CM3 = BIN_DIMS_CM[0] * BIN_DIMS_CM[1] * BIN_DIMS_CM[2]

# -- catalogue -----------------------------------------------------------------------
# category, unit weight (kg), on-hand units per baseline variant
SKU_SPECS: tuple[tuple[str, str, float, int], ...] = (
    # sku_id, category_id, unit_weight_kg, units in the feasible baseline
    ("SKU001", "CAT001", 1.0, 8),
    ("SKU002", "CAT001", 1.0, 5),
    ("SKU003", "CAT002", 1.0, 4),
    ("SKU004", "CAT003", 1.0, 3),
)

# CAT001 <-> CAT003 is forbidden (drives CAT-01); the other pairs are compatible.
COMPAT_RULES: tuple[tuple[str, str, str, bool], ...] = (
    ("CR001", "CAT001", "CAT003", False),
    ("CR002", "CAT001", "CAT002", True),
    ("CR003", "CAT002", "CAT003", True),
)

# (sku, location, units) for the baseline variants; quantities come from the variant below.
FEASIBLE_BASELINE_LAYOUT: tuple[tuple[str, str], ...] = (
    ("SKU001", "L0020"),  # rack 0, bay 0, level 2
    ("SKU002", "L0021"),  # rack 0, bay 0, level 2 (same beam as SKU001: 13 kg)
    ("SKU003", "L0100"),  # rack 0, bay 1, level 0
    ("SKU004", "L1000"),  # rack 1 -> 10.2 m from rack 0, legal at a 10 m radius
)
# 95 + 95 kg on the SAME beam (rack 0, bay 0, level 2) = 190 kg > 180 kg, while the bin
# (95 <= 100), the level (190 <= 300), the rack (194 <= 500) and CAT-01 (0 violations)
# all stay legal: exactly one SL-02 violation and nothing else.
BEAM_OVERLOADED_BASELINE_LAYOUT: tuple[tuple[str, str, int], ...] = (
    ("SKU001", "L0020", 95),
    ("SKU002", "L0021", 95),
    ("SKU003", "L0100", 4),
    ("SKU004", "L1000", 3),
)
# Same high stock (95/95/4/3) spread so that EVERY beam is legal: the feasible partner of
# BEAM_OVERLOADED, used to prove the gate can block the optimized layout alone.
FEASIBLE_HIGH_STOCK_LAYOUT: tuple[tuple[str, str, int], ...] = (
    ("SKU001", "L0020", 95),  # rack 0, bay 0, level 2 -> beam 95
    ("SKU002", "L0100", 95),  # rack 0, bay 1, level 0 -> beam 95 (different beam)
    ("SKU003", "L0110", 4),  # rack 0, bay 1, level 1
    ("SKU004", "L1000", 3),  # rack 1 -> CAT-01 satisfied
)

BASELINE_VARIANTS = ("feasible", "beam_overloaded", "feasible_high_stock")


def location_position(rack: int, bay: int, level: int, k: int) -> tuple[float, float, float]:
    """Physical (x, y, z) of a bin in metres — the geometry CAT-01 measures."""
    return (
        rack * RACK_PITCH_M,
        bay * BAY_PITCH_M + k * BIN_PITCH_M,
        level * LEVEL_HEIGHT_M,
    )


def location_id(rack: int, bay: int, level: int, k: int) -> str:
    return f"L{rack}{bay}{level}{k}"


@dataclass(frozen=True)
class TinyDataset:
    """Paths and expectations of one generated fixture directory."""

    root: Path
    baseline: str
    units_by_sku: dict[str, int]

    @property
    def total_units(self) -> int:
        return sum(self.units_by_sku.values())

    @property
    def inventory_total(self) -> int:
        return sum(self.units_by_sku.values())


def _expected_units(baseline: str) -> dict[str, int]:
    if baseline == "feasible":
        return {sku: units for sku, _cat, _w, units in SKU_SPECS}
    if baseline == "beam_overloaded":
        return {sku: qty for sku, _loc, qty in BEAM_OVERLOADED_BASELINE_LAYOUT}
    if baseline == "feasible_high_stock":
        return {sku: qty for sku, _loc, qty in FEASIBLE_HIGH_STOCK_LAYOUT}
    raise ValueError(f"unknown baseline variant: {baseline!r}")


def baseline_rows(baseline: str) -> list[dict]:
    """Assignment rows of a baseline variant (the canonical loader's column set)."""
    if baseline == "feasible":
        units = _expected_units(baseline)
        return [
            {
                "sku_id": sku,
                "location_id": loc,
                "assigned_quantity": units[sku],
                "assignment_type": "baseline",
            }
            for sku, loc in FEASIBLE_BASELINE_LAYOUT
        ]
    layout = (
        BEAM_OVERLOADED_BASELINE_LAYOUT
        if baseline == "beam_overloaded"
        else FEASIBLE_HIGH_STOCK_LAYOUT
    )
    return [
        {
            "sku_id": sku,
            "location_id": loc,
            "assigned_quantity": qty,
            "assignment_type": "baseline",
        }
        for sku, loc, qty in layout
    ]


def write_tiny_dataset(
    root: Path, baseline: str = "feasible", extra_unplaceable_sku: bool = False
) -> TinyDataset:
    """Write the canonical-shaped CSV set into ``root`` and return its expectations.

    ``extra_unplaceable_sku`` adds one product that fits no bin at all (200 cm cube) with
    two on-hand units. It exists so a test can assert the pipeline *reports* a SKU it cannot
    place instead of dropping it silently.
    """
    if baseline not in BASELINE_VARIANTS:
        raise ValueError(f"baseline must be one of {BASELINE_VARIANTS}, got {baseline!r}")
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)

    # -- locations ------------------------------------------------------------
    locations = []
    for rack in range(N_RACKS):
        for bay in range(N_BAYS):
            for level in range(N_LEVELS):
                for k in range(BINS_PER_SHELF):
                    x, y, z = location_position(rack, bay, level, k)
                    locations.append(
                        {
                            "location_id": location_id(rack, bay, level, k),
                            "warehouse_id": "WH_TINY",
                            "zone_id": f"Z{rack}",
                            "aisle_id": f"A{rack}",
                            "rack_id": f"R{rack}",
                            "bay": bay,
                            "shelf_level": level,
                            "x_m": x,
                            "y_m": y,
                            "z_m": z,
                            "width_cm": BIN_DIMS_CM[0],
                            "height_cm": BIN_DIMS_CM[1],
                            "depth_cm": BIN_DIMS_CM[2],
                            "max_weight_kg": BIN_LIMIT_KG,
                            "usable_volume_cm3": BIN_VOLUME_CM3,
                            "ergonomic_zone": "golden" if level == 2 else "secondary",
                            "allowed_handling": "standard|fragile|heavy",
                            "allowed_hazard": "NONE",
                            "distance_to_dispatch_m": round(1.0 + x + y + z, 3),
                            "zone_type": "general",
                            "beam_max_weight_kg": BEAM_LIMIT_KG,
                            "level_max_weight_kg": LEVEL_LIMIT_KG,
                            "shelf_max_weight_kg": LEVEL_LIMIT_KG,
                            "rack_max_weight_kg": RACK_LIMIT_KG,
                        }
                    )
    pd.DataFrame(locations).to_csv(root / "locations.csv", index=False)

    # -- catalogue ------------------------------------------------------------
    product_rows = [
        {
            "sku_id": sku,
            "product_name": sku,
            "category_id": category,
            "width_cm": UNIT_DIMS_CM[0],
            "height_cm": UNIT_DIMS_CM[1],
            "depth_cm": UNIT_DIMS_CM[2],
            "unit_weight_kg": weight,
            "handling_type": "standard",
            "hazard_class": "NONE",
            "data_source": "fixture",
        }
        for sku, category, weight, _units in SKU_SPECS
    ]
    if extra_unplaceable_sku:
        product_rows.append(
            {
                "sku_id": "SKU005",
                "product_name": "oversized",
                "category_id": "CAT001",
                "width_cm": 200.0,
                "height_cm": 200.0,
                "depth_cm": 200.0,
                "unit_weight_kg": 1.0,
                "handling_type": "standard",
                "hazard_class": "NONE",
                "data_source": "fixture",
            }
        )
    pd.DataFrame(product_rows).to_csv(root / "products.csv", index=False)

    pd.DataFrame(
        [
            {
                "rule_id": rule_id,
                "category_a": cat_a,
                "category_b": cat_b,
                "allowed": allowed,
                "severity": "high",
                "rule_reason": "fixture rule",
            }
            for rule_id, cat_a, cat_b, allowed in COMPAT_RULES
        ]
    ).to_csv(root / "compatibility_rules.csv", index=False)

    # -- baseline + inventory (inventory is derived from the baseline, so the
    #    conservation rule has an unambiguous expectation) ---------------------
    rows = baseline_rows(baseline)
    units = _expected_units(baseline)

    pd.DataFrame(rows).to_csv(root / "storage_assignments_baseline.csv", index=False)
    inventory_rows = [
        {"sku_id": r["sku_id"], "location_id": r["location_id"], "quantity_on_hand": r["assigned_quantity"]}
        for r in rows
    ]
    if extra_unplaceable_sku:
        # On-hand stock that no bin can hold: the pipeline must report it, not drop it.
        inventory_rows.append({"sku_id": "SKU005", "location_id": "L0000", "quantity_on_hand": 2})
        units = {**units, "SKU005": 2}
    pd.DataFrame(inventory_rows).to_csv(root / "inventory.csv", index=False)

    # -- demand / affinity ----------------------------------------------------
    demand_rows = []
    affinity_rows = []
    for scenario, abc in (("A", "A"), ("B", "B"), ("C", "C")):
        for rank, (sku, _cat, _w, _units) in enumerate(SKU_SPECS):
            demand_rows.append(
                {
                    "scenario_id": scenario,
                    "sku_id": sku,
                    "abc_class": abc if rank < 2 else ("B" if rank == 2 else "C"),
                    "demand_frequency": float(len(SKU_SPECS) - rank),
                }
            )
    affinity_rows.append(
        {"scenario_id": "C", "sku_a": "SKU001", "sku_b": "SKU003", "co_count": 3, "lift": 1.5}
    )
    affinity_rows.append(
        {"scenario_id": "C", "sku_a": "SKU002", "sku_b": "SKU003", "co_count": 2, "lift": 1.2}
    )
    pd.DataFrame(demand_rows).to_csv(root / "demand_summary.csv", index=False)
    pd.DataFrame(affinity_rows).to_csv(root / "sku_affinity.csv", index=False)

    # -- workload -------------------------------------------------------------
    orders = [
        {"order_id": "O1", "scenario_id": "A"},
        {"order_id": "O2", "scenario_id": "A"},
        {"order_id": "O3", "scenario_id": "A"},
        {"order_id": "O4", "scenario_id": "A"},
    ]
    order_items = [
        {"order_id": "O1", "sku_id": "SKU001", "quantity": 1},
        {"order_id": "O2", "sku_id": "SKU002", "quantity": 2},
        {"order_id": "O3", "sku_id": "SKU003", "quantity": 1},
        {"order_id": "O4", "sku_id": "SKU004", "quantity": 1},
    ]
    pd.DataFrame(orders).to_csv(root / "orders.csv", index=False)
    pd.DataFrame(order_items).to_csv(root / "order_items.csv", index=False)

    # -- aisle network: depot connected to every bin (all bins reachable) ------
    edges = []
    for row in locations:
        edges.append(
            {
                "from_node_id": "DEPOT",
                "to_node_id": row["location_id"],
                "distance_m": round(5.0 + row["x_m"] + row["y_m"] + row["z_m"], 3),
            }
        )
    pd.DataFrame(edges).to_csv(root / "location_graph.csv", index=False)

    return TinyDataset(root=root, baseline=baseline, units_by_sku=units)


def tiny_config(separation_radius_m: float = 10.0, seed: int = 42) -> Config:
    """Config for the tiny fixture: only the CAT-01 radius and the seed vary."""
    cfg = Config()
    cfg.separation_radius_m = float(separation_radius_m)
    cfg.dataset.seed = int(seed)
    return cfg


def assignment_rows(path: Path) -> list[tuple[str, str, int]]:
    """(sku, bin, qty) rows of an assignments CSV, sorted — the comparable identity."""
    df = pd.read_csv(path)
    return sorted(
        (str(r.sku_id), str(r.location_id), int(r.assigned_quantity))
        for r in df.itertuples(index=False)
    )


def assignment_digest(rows: list[tuple[str, str, int]]) -> str:
    """Stable digest of a layout (same layout => same digest, regardless of row order)."""
    payload = "\n".join(f"{sku}|{loc}|{qty}" for sku, loc, qty in sorted(rows))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# -- pipeline driver over the tiny fixture -------------------------------------------
# The four artifacts the delivery contract requires (README / Phase-8 acceptance).
REQUIRED_ARTIFACTS = (
    "baseline_assignments.csv",
    "constraint_audit.csv",
    "optimized/optimized_assignments.csv",
    "optimized/optimization_summary.json",
)


def produce_delivery_artifacts(processed: Path, root: Path, radius: float = 10.0) -> dict:
    """Mirror ``app/main.py validate`` + ``optimize`` + ``simulate`` into an owned ``root``.

    Everything the real CLI writes under ``outputs/`` is written here under ``root`` instead,
    so an artifact-contract test never depends on (or disturbs) the shared tree.
    """
    root.mkdir(parents=True, exist_ok=True)
    wh, skus, comp, baseline, inventory = load_shipping(processed)

    result = validate_assignment(
        baseline, skus, wh, comp, inventory, separation_radius_m=radius
    )
    write_constraint_audit(baseline, result, root / "constraint_audit.csv")
    write_validation_checks(result, root / "validation_checks_baseline.csv")
    write_assignments_csv(baseline, root / "baseline_assignments.csv")

    summary = run_phase5(processed, tiny_config(radius), root / "optimized")
    evaluation = run_phase6(
        processed,
        scenario="A",
        out=root / "evaluation",
        optimized_path=root / "optimized" / "optimized_assignments.csv",
        separation_radius_m=radius,
    )
    return {"validation": result, "optimization": summary, "evaluation": evaluation}
