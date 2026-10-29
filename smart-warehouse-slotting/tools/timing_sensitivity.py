"""Phase 7 pick-time sensitivity.

Runs the frozen layouts on A_HOLDOUT at explicitly hypothetical pick-time constants
(6, 8, 10 s) under both bases. Travel must remain identical; only cycle and throughput
may move. This is a sensitivity analysis, not a calibration claim.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.simulation.pipeline import run_phase6

HOLDOUT = ROOT / "outputs" / "phase3" / "split" / "A70" / "holdout" / "processed"
BASELINE = ROOT / "outputs" / "phase3" / "optimized_fit" / "baseline_repaired_assignments.csv"
OPTIMIZED = ROOT / "outputs" / "phase3" / "optimized_fit" / "optimized_assignments.csv"


def main() -> None:
    ap = argparse.ArgumentParser(prog="timing_sensitivity")
    ap.add_argument("--out", default=str(ROOT / "outputs" / "phase7" / "timing_sensitivity.json"))
    args = ap.parse_args()

    rows = []
    travel_reference = {}
    for basis in ("order_line", "stop"):
        for pick_s in (6.0, 8.0, 10.0):
            out = ROOT / "outputs" / "phase7" / "timing" / f"{basis}_{int(pick_s)}"
            run = run_phase6(
                processed=HOLDOUT,
                scenario="A_HOLDOUT",
                out=out,
                optimized_path=OPTIMIZED,
                affinity_scenario="A_HOLDOUT",
                baseline_path=BASELINE,
                baseline_variant="repaired_minimal",
                baseline_note="repaired for feasibility only; frozen from Phase 3",
                routing_strategy="nearest_neighbor",
                batch_size=5,
                pick_time_basis=basis,
                pick_time_sec=pick_s,
                pick_time_stop_sec=pick_s,
            )
            b, o = run["baseline"], run["optimized"]
            travel_reference.setdefault((basis, "baseline"), b["total_travel_distance_m"])
            travel_reference.setdefault((basis, "optimized"), o["total_travel_distance_m"])
            rows.append(
                {
                    "basis": basis,
                    "pick_time_sec": pick_s,
                    "workload_id": run["workload"]["workload_id"],
                    "baseline_travel_m": b["total_travel_distance_m"],
                    "optimized_travel_m": o["total_travel_distance_m"],
                    "baseline_cycle_s": b["total_route_time_sec"],
                    "optimized_cycle_s": o["total_route_time_sec"],
                    "baseline_throughput": b["throughput_orders_per_hr"],
                    "optimized_throughput": o["throughput_orders_per_hr"],
                    "cycle_change_pct": round(
                        (o["total_route_time_sec"] - b["total_route_time_sec"])
                        / b["total_route_time_sec"]
                        * 100.0,
                        4,
                    ),
                    "throughput_change_pct": round(
                        (o["throughput_orders_per_hr"] - b["throughput_orders_per_hr"])
                        / b["throughput_orders_per_hr"]
                        * 100.0,
                        4,
                    ),
                    "feasible": run["feasibility"]["baseline"]["is_feasible"]
                    and run["feasibility"]["optimized"]["is_feasible"],
                }
            )

    payload = {
        "schema": "phase7.timing_sensitivity/1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "constants": [6.0, 8.0, 10.0],
        "status": "hypothetical sensitivity; not physically calibrated",
        "rows": rows,
        "travel_unchanged_within_basis": all(
            abs(r["baseline_travel_m"] - travel_reference[(r["basis"], "baseline")]) <= 0.01
            and abs(r["optimized_travel_m"] - travel_reference[(r["basis"], "optimized")]) <= 0.01
            for r in rows
        ),
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
