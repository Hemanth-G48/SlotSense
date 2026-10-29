"""Configuration model and loader for the warehouse slotting engine.

Configuration is JSON (a dependency-free format that is always available and easy to
generate/consume). A YAML variant is acceptable too, but JSON is used here for testability
without an extra parser dependency.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

# Single source of truth for the CAT-01 separation radius (metres).
#
# The optimiser and the validator both read the effective value from ``Config``; this
# constant only exists so that a caller which has no config (unit tests, library use) gets
# the documented ARCHITECTURE.md §8.1 default instead of a scattered literal.
DEFAULT_SEPARATION_RADIUS_M: float = 10.0


def coerce_separation_radius_m(value: object, *, name: str = "separation_radius_m") -> float:
    """Validate a CAT-01 radius: a finite number of metres, >= 0.

    A radius of 0 disables CAT-01 distance checking (the validator skips the rule), which is
    legitimate for geometry-without-hazards experiments; a negative radius is meaningless
    and is rejected rather than silently clamped.
    """
    if isinstance(value, bool):  # bool is an int subclass; True/False are not radii
        raise ValueError(f"{name} must be a number of metres, got boolean {value!r}")
    if not isinstance(value, (int, float)):
        raise ValueError(
            f"{name} must be a number of metres, got {type(value).__name__} {value!r}"
        )
    radius = float(value)
    if not math.isfinite(radius):
        raise ValueError(f"{name} must be finite, got {value!r}")
    if radius < 0:
        raise ValueError(f"{name} must be >= 0 metres, got {radius}")
    return radius



@dataclass
class TopologyConfig:
    n_zones: int = 3
    aisles_per_zone: int = 4
    racks_per_aisle: int = 3
    bays_per_rack: int = 2
    shelf_levels: int = 4
    bins_per_shelf: int = 2
    # Bin internal dimensions (cm). All bins share the same module footprint.
    bin_width_cm: float = 60.0
    bin_height_cm: float = 40.0
    bin_depth_cm: float = 45.0
    max_weight_kg: float = 60.0
    # Aisle / rack spacing in metres (drives coordinate geometry).
    aisle_spacing_m: float = 2.0
    rack_depth_m: float = 1.2
    shelf_height_m: float = 0.5
    # Shelf levels reachable by a picker are considered "golden" here (chest-to-waist).
    golden_levels: tuple[int, ...] = (2,)  # 0-indexed shelf level(s) near grasping height


@dataclass
class DemandConfig:
    abc_a_cumulative_share: float = 0.80
    abc_b_cumulative_share: float = 0.95  # A + B boundary
    n_scenarios: int = 3


@dataclass
class OptimizationConfig:
    alpha: float = 1.0  # travel cost weight
    beta: float = 0.4   # affinity penalty weight
    gamma: float = 0.3  # ergonomics penalty weight
    delta: float = 0.2  # space utilization penalty weight
    epsilon: float = 0.0  # replenishment-travel weight (0.0 = Phase 2 behaviour)


@dataclass
class SlottingConfig:
    single_sku_per_location: bool = True
    max_quantity_per_location: int = 0  # 0 = unlimited (capacity-bound)


@dataclass
class DatasetConfig:
    n_skus: int = 1200
    n_categories: int = 10
    n_locations: int = 800
    n_order_lines: int = 30000
    seed: int = 42


@dataclass
class Config:
    topology: TopologyConfig = field(default_factory=TopologyConfig)
    demand: DemandConfig = field(default_factory=DemandConfig)
    optimization: OptimizationConfig = field(default_factory=OptimizationConfig)
    slotting: SlottingConfig = field(default_factory=SlottingConfig)
    dataset: DatasetConfig = field(default_factory=DatasetConfig)
    # CAT-01 radius in metres: the minimum 3-D distance between bins holding a forbidden
    # category pair. One value, consumed by both the optimiser and the validator.
    separation_radius_m: float = DEFAULT_SEPARATION_RADIUS_M

    def __post_init__(self) -> None:
        self.separation_radius_m = coerce_separation_radius_m(self.separation_radius_m)

    @classmethod
    def from_dict(cls, d: dict) -> "Config":
        c = cls()
        c.topology = TopologyConfig(**d.get("topology", {}))
        c.demand = DemandConfig(**d.get("demand", {}))
        c.optimization = OptimizationConfig(**d.get("optimization", {}))
        c.slotting = SlottingConfig(**d.get("slotting", {}))
        c.dataset = DatasetConfig(**d.get("dataset", {}))
        c.separation_radius_m = coerce_separation_radius_m(
            d.get("separation_radius_m", DEFAULT_SEPARATION_RADIUS_M)
        )
        return c

    @classmethod
    def from_json(cls, path: Path | str) -> "Config":
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"config file not found: {p}")
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"config file is not valid JSON: {p}: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("config root must be a JSON object")
        return cls.from_dict(data)

    def to_dict(self) -> dict:
        return {
            "topology": {
                k: (list(v) if isinstance(v, tuple) else v)
                for k, v in self.topology.__dict__.items()
            },
            "demand": {k: v for k, v in self.demand.__dict__.items()},
            "optimization": {k: v for k, v in self.optimization.__dict__.items()},
            "slotting": {k: v for k, v in self.slotting.__dict__.items()},
            "dataset": {k: v for k, v in self.dataset.__dict__.items()},
            "separation_radius_m": self.separation_radius_m,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)