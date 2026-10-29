"""Independent Phase 6 verification of one run-all directory.

Recomputes dataset hashes, output hashes, feasibility/count invariants, D37 invariance,
seed identity, optimizer-audit claims and capacity-perturbation outcomes from the recorded
artifacts. It does not import the production evaluator or optimizer and does not trust the
run summary's status alone.

Usage: python tools/verify_phase6.py outputs/phase6/runs/<run_id>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _dataset_manifest(root: Path) -> dict:
    rows = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rows.append({"path": str(path.relative_to(root)), "sha256": _sha(path), "bytes": path.stat().st_size})
    digest = hashlib.sha256("\n".join(f"{r['path']}:{r['sha256']}" for r in rows).encode()).hexdigest()
    return {"sha256": digest, "n_files": len(rows), "files": rows}


def verify(run_dir: Path) -> dict:
    run_dir = Path(run_dir)
    artifacts = run_dir / "artifacts"
    checks: list[dict] = []

    def add(name: str, passed: bool, detail: str = "") -> None:
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    summary_path = run_dir / "run_summary.json"
    add("run_summary_exists", summary_path.is_file())
    if not summary_path.is_file():
        result = {"schema": "phase6.verification/1", "all_passed": False, "n_checks": 1, "n_failed": 1, "checks": checks}
        return result
    s = json.loads(summary_path.read_text())

    add("run_status_pass", s.get("status") == "PASS", str(s.get("status")))
    stages = s.get("stages") or []
    add("all_stages_pass", bool(stages) and all(x.get("exit_code") == 0 for x in stages))
    add("stage_logs_exist", all(Path(x["log"]).is_file() for x in stages if x.get("log")))

    dataset = Path(s["dataset"])
    current = _dataset_manifest(dataset)
    recorded = s.get("dataset_manifest") or {}
    add(
        "dataset_manifest_matches",
        current["sha256"] == recorded.get("sha256") and current["n_files"] == recorded.get("n_files"),
        f"{current['sha256'][:12]} vs {str(recorded.get('sha256'))[:12]}",
    )
    add(
        "config_hash_matches",
        _sha(ROOT / "configs" / "benchmark.json") == s.get("config_sha256"),
    )

    p3 = json.loads((artifacts / "phase3" / "phase3_experiments.json").read_text())
    add("phase3_all_cells_feasible", all(c.get("feasible") for c in p3["cells"]))
    add("phase3_all_cells_priced", all(c.get("denominator_lines", 0) > 0 for c in p3["cells"]))
    add("phase3_split_checks", p3["split"]["checks"]["all_passed"] is True)
    p3_layout = pd.read_csv(artifacts / "phase3" / "optimized_fit" / "optimized_assignments.csv")
    add("phase3_inventory_units", int(p3_layout["assigned_quantity"].sum()) == 6375)
    add("phase3_duplicate_pairs", int(p3_layout.duplicated(["sku_id", "location_id"]).sum()) == 0)

    p4v = json.loads((artifacts / "phase4" / "verification.json").read_text())
    add("phase4_verifier_pass", p4v.get("all_passed") is True, f"{p4v.get('n_checks')} checks")
    p5v = json.loads((artifacts / "phase5" / "verification.json").read_text())
    add("phase5_verifier_pass", p5v.get("all_passed") is True, f"{p5v.get('n_checks')} checks")

    p5 = json.loads((artifacts / "phase5" / "phase5_experiments.json").read_text())
    add("d37_travel_unchanged", p5["d37"]["travel_unchanged"] is True)
    seeds = p5["paired_seeds"]
    add("seed_count", seeds["summary"]["n_successful"] == 5 and seeds["summary"]["n_failed"] == 0)
    add("seed_one_layout", seeds["summary"]["unique_layouts"] == 1)
    add("seed_zero_variance", seeds["summary"]["paired_delta"]["travel_pct"]["sd"] == 0.0)

    audit = json.loads((run_dir / "optimizer_audit.json").read_text())
    add("optimizer_fixture_improved", audit["hand_fixture"]["improved"] is True)
    add(
        "optimizer_canonical_D_matches",
        audit["canonical"]["starter"]["D_matches_independent"] is True,
    )
    add(
        "optimizer_no_worse_than_starter",
        audit["canonical"]["refine"]["delta_vs_starter"] <= 1e-9,
    )
    add(
        "optimizer_audit_layout_feasible",
        audit["canonical"]["refine"]["feasible"] is True
        and audit["canonical"]["starter"]["feasible"] is True,
    )

    cap = json.loads((run_dir / "capacity_perturbation.json").read_text())
    add("capacity_baseline_feasible", cap["baseline"]["feasible"] is True)
    add("capacity_baseline_units", cap["baseline"]["units"] == 6375)
    perturbations = cap.get("perturbations") or []
    add("capacity_perturbations_present", len(perturbations) == 2)
    add(
        "capacity_perturbations_fail",
        all(not p.get("inventory_plus_layout", {}).get("feasible", True) for p in perturbations),
    )
    add(
        "capacity_expected_rules",
        {p["scope"]: set(p["inventory_plus_layout"]["rules"]) for p in perturbations}
        == {"bin_weight": {"LD-01", "SL-01"}, "bin_volume": {"VD-01"}},
    )

    # Every declared output in the manifest must still hash to the recorded value.
    bad = []
    for rel, meta in (s.get("outputs") or {}).items():
        path = run_dir / rel
        if not path.exists() or _sha(path) != meta["sha256"]:
            bad.append(rel)
    add("output_hashes_match", not bad, f"bad={bad[:10]}")

    result = {
        "schema": "phase6.verification/1",
        "all_passed": all(c["passed"] for c in checks),
        "n_checks": len(checks),
        "n_failed": sum(1 for c in checks if not c["passed"]),
        "checks": checks,
    }
    (run_dir / "verification.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main() -> None:
    ap = argparse.ArgumentParser(prog="verify_phase6")
    ap.add_argument("run_dir")
    args = ap.parse_args()
    result = verify(Path(args.run_dir))
    print(json.dumps({k: result[k] for k in ("all_passed", "n_checks", "n_failed")}, indent=2))
    for c in result["checks"]:
        if not c["passed"]:
            print(f"FAIL {c['name']}: {c['detail']}")
    raise SystemExit(0 if result["all_passed"] else 1)


if __name__ == "__main__":
    sys.exit(main())
