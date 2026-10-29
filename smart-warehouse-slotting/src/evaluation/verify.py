"""Independent verification of Phase 4 artifacts (Phase 4, Step 10).

This module deliberately recomputes headline numbers from the raw route tables and layout
CSVs instead of trusting the summary JSON. It is invoked by ``tools/verify_phase4.py`` and
its report is written beside the artifacts as ``verification.json``.

Checks
------
1  four cells exist with the documented factor levels
2  every cell is feasible and assignment-complete
3  route sums reproduce travel and cycle time; cycle identity holds per batch
4  throughput equals orders / cycle hours
5  percentage changes and 2x2 effects recompute from the cell values
6  layouts conserve inventory and contain no duplicate (SKU, bin) pairs
7  the Phase 3 split is disjoint, complete and reproducible
8  regime row counts reconcile with the canonical scenario populations
9  structural headroom recomputes from the validator check CSV
10 provenance hashes match the files on disk
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

from src.evaluation.factorial import effect_table
from src.experiments.split import verify_split

TOLERANCE = 0.05  # metres/seconds; sums are rounded to 2 dp by the simulator


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_phase4_artifacts(
    phase4_dir: Path,
    *,
    phase3_dir: Path | None = None,
    dataset_dir: Path | None = None,
) -> dict:
    phase4_dir = Path(phase4_dir)
    root = phase4_dir.parent.parent
    phase3_dir = Path(phase3_dir) if phase3_dir else root / "outputs" / "phase3"
    dataset_dir = Path(dataset_dir) if dataset_dir else root.parent / "dataset" / "processed"

    exp = json.loads((phase4_dir / "phase4_experiments.json").read_text())
    cells = pd.read_csv(phase4_dir / "phase4_cells.csv")
    headroom = pd.read_csv(phase4_dir / "phase4_headroom.csv")
    checks: list[dict] = []

    def record(name: str, passed: bool, detail: str = "") -> None:
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    # 1. cells
    expected = {"A1": ("baseline_repaired", "nearest_neighbor"),
                "A2": ("baseline_repaired", "s_shape"),
                "B1": ("optimized_fit", "nearest_neighbor"),
                "B2": ("optimized_fit", "s_shape")}
    found = {row.cell_id: (row.layout, row.picking_policy) for row in cells.itertuples()}
    record("four_cells_present", set(found) == set(expected), f"found={found}")
    record("factor_levels_match", found == expected, f"expected={expected}")

    # 2. feasibility / completeness
    record(
        "all_cells_feasible",
        bool(cells["feasible"].all()),
        f"infeasible={cells.loc[~cells['feasible'], 'cell_id'].tolist()}",
    )
    record(
        "assignment_complete",
        bool((cells["assignment_completeness_pct"] == 100.0).all()),
        f"values={cells['assignment_completeness_pct'].tolist()}",
    )

    # 3/4. route sums and cycle identity
    route_failures = []
    cycle_failures = []
    throughput_failures = []
    for row in cells.itertuples():
        layout = "baseline" if row.layout == "baseline_repaired" else "optimized"
        routes_path = Path(row.run_dir) / "pick_routes.csv"
        if not routes_path.exists():
            route_failures.append(f"{row.cell_id}: missing {routes_path}")
            continue
        routes = pd.read_csv(routes_path)
        routes = routes[routes["layout"] == layout]
        if routes.empty:
            route_failures.append(f"{row.cell_id}: no rows for layout {layout}")
            continue
        distance = float(routes["distance_m"].sum())
        cycle = float(routes["cycle_time_sec"].sum())
        orders = int(routes["n_orders"].sum())

        if abs(distance - float(row.total_travel_distance_m)) > TOLERANCE:
            route_failures.append(
                f"{row.cell_id}: routes {distance:.2f} != summary {row.total_travel_distance_m:.2f}"
            )
        if abs(cycle - float(row.total_route_time_sec)) > TOLERANCE:
            cycle_failures.append(
                f"{row.cell_id}: routes {cycle:.2f} != summary {row.total_route_time_sec:.2f}"
            )

        leg_error = (routes["travel_time_sec"] - routes["distance_m"] / 1.3).abs().max()
        identity_error = (
            routes["cycle_time_sec"]
            - routes["travel_time_sec"]
            - routes["pick_time_sec"]
            - 10.0
        ).abs().max()
        if leg_error > 1e-6 or identity_error > 1e-6:
            cycle_failures.append(
                f"{row.cell_id}: leg_error={leg_error:.2e}, identity_error={identity_error:.2e}"
            )

        expected_throughput = orders / (cycle / 3600.0) if cycle else 0.0
        if abs(expected_throughput - float(row.throughput_orders_per_hr)) > 0.01:
            throughput_failures.append(
                f"{row.cell_id}: {expected_throughput:.4f} != {row.throughput_orders_per_hr}"
            )

    record("route_sums_match_summary", not route_failures, "; ".join(route_failures[:3]))
    record("cycle_identity_holds", not cycle_failures, "; ".join(cycle_failures[:3]))
    record("throughput_recomputes", not throughput_failures, "; ".join(throughput_failures[:3]))

    # 5. effects
    values = {
        (row.layout, row.picking_policy): float(row.total_travel_distance_m)
        for row in cells.itertuples()
    }
    travel_effect = effect_table(
        values,
        ("baseline_repaired", "optimized_fit"),
        ("nearest_neighbor", "s_shape"),
        a_name="layout",
        b_name="picking_policy",
    )
    reported = exp["effects"]["total_travel_distance_m"]
    record(
        "travel_effects_recompute",
        abs(travel_effect["factor_a_effect"] - reported["factor_a_effect"]) < 1e-6
        and abs(travel_effect["factor_b_effect"] - reported["factor_b_effect"]) < 1e-6
        and abs(travel_effect["interaction"] - reported["interaction"]) < 1e-6,
        f"recomputed={travel_effect['factor_a_effect']}, {travel_effect['factor_b_effect']}, "
        f"{travel_effect['interaction']}",
    )

    direct = (
        (values[("optimized_fit", "nearest_neighbor")] - values[("baseline_repaired", "nearest_neighbor")])
        / values[("baseline_repaired", "nearest_neighbor")]
        * 100.0
    )
    reported_regime = next(
        (r for r in exp["regimes"]["rows"] if r["regime"] == "A_HOLDOUT"), None
    )
    record(
        "direct_holdout_change_recomputes",
        reported_regime is not None
        and abs(direct - float(reported_regime["travel_change_pct"])) < 0.001,
        f"recomputed={direct:.4f}, reported={reported_regime['travel_change_pct'] if reported_regime else None}",
    )

    # 6. inventory conservation and duplicate pairs
    inventory = (
        pd.read_csv(dataset_dir / "inventory.csv")
        .groupby("sku_id")["quantity_on_hand"]
        .sum()
        .astype(int)
    )
    layout_failures = []
    for label, path in (
        ("baseline", phase3_dir / "optimized_fit" / "baseline_repaired_assignments.csv"),
        ("optimized", phase3_dir / "optimized_fit" / "optimized_assignments.csv"),
    ):
        layout = pd.read_csv(path)
        placed = layout.groupby("sku_id")["assigned_quantity"].sum().astype(int)
        joined = pd.concat([inventory.rename("required"), placed.rename("placed")], axis=1).fillna(0)
        mismatched = joined[joined["required"].astype(int) != joined["placed"].astype(int)]
        duplicates = int(layout.duplicated(["sku_id", "location_id"]).sum())
        if len(mismatched) or duplicates:
            layout_failures.append(
                f"{label}: {len(mismatched)} SKU mismatches, {duplicates} duplicate pairs"
            )
    record("inventory_conserved", not layout_failures, "; ".join(layout_failures))

    # 7. split
    split_path = phase3_dir / "split" / "A70" / "split_manifest.json"
    split = json.loads(split_path.read_text())
    split_checks = verify_split(split)
    record("split_checks_pass", bool(split_checks["all_passed"]), str(split_checks))

    # 8. regimes
    regimes = pd.read_csv(phase4_dir / "phase4_regimes.csv")
    orders = pd.read_csv(dataset_dir / "orders.csv")
    regime_failures = []
    for scenario in ("B", "C"):
        row = regimes[regimes["regime"] == scenario]
        if row.empty:
            regime_failures.append(f"{scenario}: missing row")
            continue
        expected_orders = int((orders["scenario_id"] == scenario).sum())
        if int(row.iloc[0]["orders"]) != expected_orders:
            regime_failures.append(f"{scenario}: {row.iloc[0]['orders']} != {expected_orders}")
    record("regime_counts_reconcile", not regime_failures, "; ".join(regime_failures))

    # 9. headroom from validation checks
    head_failures = []
    for layout, filename in (
        ("baseline_repaired", "validation_checks_baseline.csv"),
        ("optimized_fit", "validation_checks_optimized.csv"),
    ):
        check_path = phase4_dir / "cells" / "nearest_neighbor" / filename
        if not check_path.exists():
            head_failures.append(f"missing {check_path}")
            continue
        checks_df = pd.read_csv(check_path)
        ld = checks_df[(checks_df["rule_id"] == "LD-01") & (checks_df["limit"].notna())].copy()
        if ld.empty:
            head_failures.append(f"{layout}: no LD-01 checks")
            continue
        ld["util"] = pd.to_numeric(ld["observed"], errors="coerce") / pd.to_numeric(
            ld["limit"], errors="coerce"
        ) * 100.0
        recomputed = float(ld["util"].max())
        reported = headroom[
            (headroom["layout"] == layout)
            & (headroom["picking_policy"] == "nearest_neighbor")
            & (headroom["scope"] == "bin_weight")
        ]
        if reported.empty or abs(recomputed - float(reported.iloc[0]["max_utilization_pct"])) > 1e-6:
            head_failures.append(
                f"{layout}: recomputed {recomputed:.4f} vs {reported.iloc[0]['max_utilization_pct'] if len(reported) else 'missing'}"
            )
    record("headroom_recomputes", not head_failures, "; ".join(head_failures))

    # 10. provenance hashes
    provenance_path = phase4_dir / "provenance.json"
    provenance_failures = []
    if not provenance_path.exists():
        provenance_failures.append("missing provenance.json")
    else:
        provenance = json.loads(provenance_path.read_text())
        for name, meta in provenance.get("outputs", {}).items():
            path = Path(meta["path"])
            if not path.exists():
                provenance_failures.append(f"{name}: missing file")
            elif meta.get("sha256") not in (None, "missing") and _sha256(path) != meta["sha256"]:
                provenance_failures.append(f"{name}: hash mismatch")
    record("provenance_hashes_match", not provenance_failures, "; ".join(provenance_failures[:3]))

    return {
        "schema": "phase4.verification/1",
        "phase4_dir": str(phase4_dir),
        "tolerance": TOLERANCE,
        "checks": checks,
        "all_passed": all(c["passed"] for c in checks),
        "n_checks": len(checks),
        "n_failed": sum(1 for c in checks if not c["passed"]),
    }
