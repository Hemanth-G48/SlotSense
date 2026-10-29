"""Independent Phase 7 verification.

Checks the controlled optimizer comparison, timing-sensitivity artifact, capacity audit and
dashboard registry evidence without importing the optimizer/simulator to recompute them.

Usage: python tools/verify_phase7.py [outputs/phase7]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify(out: Path) -> dict:
    out = Path(out)
    checks: list[dict] = []

    def add(name: str, passed: bool, detail: str = "") -> None:
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    comp = json.loads((out / "optimizer_compare.json").read_text())
    legacy = comp["results"]["legacy"]
    targeted = comp["results"]["targeted"]
    add("comparison_has_two_arms", set(comp["results"]) == {"legacy", "targeted"})
    add("comparison_same_seed_budget", comp["design"]["seed"] == 42 and comp["design"]["budget"] == 600)
    add("legacy_feasible", legacy["validation"]["feasible"] and legacy["validation"]["n_violations"] == 0)
    add("targeted_feasible", targeted["validation"]["feasible"] and targeted["validation"]["n_violations"] == 0)
    add(
        "both_inventory_conserved",
        legacy["validation"]["inventory_conserved"]
        and targeted["validation"]["inventory_conserved"]
        and legacy["validation"]["units"] == 6375
        and targeted["validation"]["units"] == 6375,
    )
    add(
        "targeted_proposal_yield_improved",
        targeted["proposal_probe"]["feasible"] > legacy["proposal_probe"]["feasible"]
        and targeted["proposal_probe"]["improving"] >= legacy["proposal_probe"]["improving"],
        f"legacy={legacy['proposal_probe']} targeted={targeted['proposal_probe']}",
    )
    add("same_layout_not_forced", comp["same_layout"] is True)
    add(
        "objective_delta_consistent",
        abs(
            comp["objective_delta_targeted_minus_legacy"]
            - (targeted["summary"]["final_objective"] - legacy["summary"]["final_objective"])
        )
        < 1e-6,
    )
    add(
        "targeted_layout_hash",
        targeted["layout_sha256"] == _sha(out / "optimizer" / "targeted" / "optimized_assignments.csv"),
    )
    add(
        "legacy_layout_hash",
        legacy["layout_sha256"] == _sha(out / "optimizer" / "legacy" / "optimized_assignments.csv"),
    )

    timing = json.loads((out / "timing_sensitivity.json").read_text())
    rows = timing["rows"]
    add("timing_six_runs", len(rows) == 6)
    add("timing_constants", {r["pick_time_sec"] for r in rows} == {6.0, 8.0, 10.0})
    add("timing_travel_fixed", timing["travel_unchanged_within_basis"] is True)
    add("timing_all_feasible", all(r["feasible"] for r in rows))
    add(
        "timing_line_default_matches_phase6",
        any(
            r["basis"] == "order_line"
            and r["pick_time_sec"] == 8.0
            and abs(r["baseline_cycle_s"] - 442129.69) < 0.01
            and abs(r["optimized_cycle_s"] - 231386.0) < 0.01
            for r in rows
        ),
    )

    capacity = json.loads((ROOT / "outputs" / "phase6" / "capacity_perturbation.json").read_text())
    add("capacity_baseline_feasible", capacity["baseline"]["feasible"] is True)
    add(
        "capacity_perturbations_rejected",
        all(not p["inventory_plus_layout"]["feasible"] for p in capacity["perturbations"]),
    )

    clean = ROOT / "outputs" / "phase6" / "runs" / "clean-01" / "verification.json"
    if clean.is_file():
        v = json.loads(clean.read_text())
        add("phase6_clean_verifier_present", v.get("all_passed") is True, f"{v.get('n_checks')} checks")
    else:
        add("phase6_clean_verifier_present", False, "clean-01 verification missing")

    result = {
        "schema": "phase7.verification/1",
        "all_passed": all(c["passed"] for c in checks),
        "n_checks": len(checks),
        "n_failed": sum(1 for c in checks if not c["passed"]),
        "checks": checks,
    }
    (out / "verification.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main() -> None:
    ap = argparse.ArgumentParser(prog="verify_phase7")
    ap.add_argument("out", nargs="?", default=str(ROOT / "outputs" / "phase7"))
    args = ap.parse_args()
    result = verify(Path(args.out))
    print(json.dumps({k: result[k] for k in ("all_passed", "n_checks", "n_failed")}, indent=2))
    for c in result["checks"]:
        if not c["passed"]:
            print(f"FAIL {c['name']}: {c['detail']}")
    raise SystemExit(0 if result["all_passed"] else 1)


if __name__ == "__main__":
    sys.exit(main())
