"""CLI entry point for the Smart Warehouse Slotting & Optimization Engine.

Phase 1: builds a small warehouse + SKUs + feasible baseline fixture and writes outputs.
Later phases extend this pipeline (analysis -> validate -> optimize -> simulate -> evaluate).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Canonical dataset (single source of truth): ../dataset/processed
CANONICAL_PROCESSED = Path(
    os.environ.get("DATASET_DIR", PROJECT_ROOT.parent / "dataset" / "processed")
).resolve()

from src.analytics.pipeline import run_phase3
from src.data_processing.pipeline import DEFAULT_OUTPUT, build_dataset
from src.data_processing.validate import run_validation
from src.models.config import Config
from src.models.io import write_assignments_csv
from src.models.synthetic import build_phase1_fixture
from src.optimization.baseline import BaselineVariant, prepare_baseline_variant
from src.optimization.pipeline import run_phase5
from src.simulation.pipeline import run_phase6
from src.evaluation.metrics import assignment_feasibility
from src.validation.audit import write_constraint_audit, write_validation_checks
from src.validation.loader import load_shipping
from src.validation.validator import validate_assignment

# Canonical output root: the repaired baseline lives beside the other delivery artifacts.
# OUTPUT_ROOT lets the Phase 6 clean-room run write into an isolated directory instead of
# overwriting the canonical evidence.
OUTPUT_ROOT = Path(os.environ.get("OUTPUT_ROOT", PROJECT_ROOT / "outputs")).resolve()


def build_phase1(args: argparse.Namespace) -> None:
    config = Config.from_json(Path(args.config))
    out = PROJECT_ROOT / args.output
    counts = build_phase1_fixture(config, out, seed=args.seed)
    print(json.dumps(counts, indent=2))
    summary = PROJECT_ROOT / "outputs" / "phase1_summary.json"
    summary.parent.mkdir(parents=True, exist_ok=True)
    summary.write_text(json.dumps(counts, indent=2), encoding="utf-8")


def build_dataset_cmd(args: argparse.Namespace) -> None:
    summary = build_dataset(args.config, DEFAULT_OUTPUT, seed=args.seed)
    print(json.dumps(summary, indent=2))
    out = PROJECT_ROOT / "outputs" / "dataset_summary.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2), encoding="utf-8")


def run_analysis(args: argparse.Namespace) -> None:
    cfg = Config.from_json(Path(args.config))
    processed = CANONICAL_PROCESSED
    out = PROJECT_ROOT / args.output
    summary = run_phase3(
        processed,
        out,
        config_abc={
            "a_share": cfg.demand.abc_a_cumulative_share,
            "b_share": cfg.demand.abc_b_cumulative_share,
            "scenario": "A",
            "affinity_scenario": "C",
        },
    )
    print(json.dumps(summary, indent=2))


def _write_dataset_validation(processed: Path, out: Path) -> None:
    """Run the dataset-level validator and persist its machine-readable report."""
    result = run_validation(processed.parent)
    out.mkdir(parents=True, exist_ok=True)
    payload = {"ok": result.ok, "hard_errors": result.hard_errors, "stats": result.stats, "errors": result.errors}
    (out / "dataset_validation.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")


def run_validate(args: argparse.Namespace) -> None:
    """Phase 4: validate the baseline and export the constraint audit."""
    processed = Path(args.processed)
    out = PROJECT_ROOT / args.output
    config = Config.from_json(Path(args.config))
    wh, skus, comp, assignments, inventory = load_shipping(processed)
    res = validate_assignment(
        assignments, skus, wh, comp, inventory,
        separation_radius_m=config.separation_radius_m,
    )
    write_constraint_audit(assignments, res, out / "constraint_audit.csv")
    write_validation_checks(res, out / "validation_checks_baseline.csv")
    write_assignments_csv(assignments, out / "baseline_assignments.csv")
    _write_dataset_validation(processed, out)
    slotting: dict[str, list[tuple[str, int]]] = {}
    for a in assignments:
        slotting.setdefault(a.sku_id, []).append((a.location_id, a.assigned_quantity))
    feasibility = assignment_feasibility(slotting, inventory, res)
    summary = {
        "dataset": str(processed),
        "separation_radius_m": config.separation_radius_m,
        "n_assignments": len(assignments),
        "n_violations": len(res.violations),
        "n_hard_violations": len(res.hard_violations),
        "checks_run": res.checks_run,
        "feasibility_pct": feasibility["assignment_feasibility_pct"],
        "rule_check_pass_pct": round(100.0 - 100.0 * len(res.violations) / max(1, res.checks_run), 2),
        "valid_assignments": feasibility["valid_assignments"],
        "required_assignments": feasibility["required_assignments"],
        "feasible": res.is_feasible,
        "safety_compliant": len(res.hard_violations) == 0,
    }
    (out / "validation_status.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    if not res.is_feasible:
        for v in res.violations[:8]:
            print(f"  [{v.rule_id}] {v.reason}")


def run_optimize(args: argparse.Namespace) -> None:
    """Phase 5: run the allocation optimizer and write outputs."""
    config = Config.from_json(Path(args.config))
    processed = Path(args.processed)
    out = PROJECT_ROOT / args.output
    variant = _prepare_baseline(processed, config)
    summary = run_phase5(processed, config, out, baseline_variant=variant)
    print(json.dumps(summary, indent=2))
    if summary.get("feasibility_status") != "FEASIBLE":
        print(
            "WARNING: the optimizer returned an INFEASIBLE layout "
            f"({summary.get('n_violations')} violations, rules "
            f"{summary.get('violations_by_rule')}); it is not a valid answer.",
            file=sys.stderr,
        )


def _exit_if_evaluation_blocked(result: dict) -> None:
    """Fail loudly when the evaluation gate refuses to publish a comparison."""
    if result.get("evaluation_status") == "BLOCKED_INFEASIBLE_LAYOUT":
        raise SystemExit(
            "BLOCKED by the feasibility gate: evaluation_status="
            f"{result['evaluation_status']}, infeasible layout(s)="
            f"{', '.join(result.get('blocked_layouts') or [])}. "
            "The diagnostic metrics are not valid evidence; fix the layouts and re-run."
        )


def _prepare_baseline(processed: Path, config: Config) -> BaselineVariant:
    """Repair the baseline to feasibility (objective disabled) and report what it did.

    The as-supplied baseline is infeasible, so it cannot be compared against. This produces
    ``outputs/baseline_repaired_assignments.csv`` and never touches the canonical input.
    """
    variant = prepare_baseline_variant(processed, config, OUTPUT_ROOT)
    repair = variant.repair or {}
    source = variant.repaired_path if variant.is_repaired else variant.source
    print(f"   baseline_variant={variant.variant} source={source}")
    if repair.get("attempted"):
        print(
            "   repair: "
            f"{repair.get('initial_violations')} -> {repair.get('final_violations')} violations "
            f"({repair.get('initial_violations_by_rule')} -> {repair.get('final_violations_by_rule')}), "
            f"moves attempted={repair.get('moves_attempted')} accepted={repair.get('moves_accepted')} "
            f"rejected={repair.get('moves_rejected')}, terminated={repair.get('termination_reason')} "
            f"in {repair.get('runtime_sec')}s"
        )
        movement = repair.get("movement") or {}
        if movement.get("comparable"):
            print(
                f"   movement: {movement.get('records_relocated')}/{movement.get('records_total')} "
                f"records relocated, {movement.get('total_displacement_m')} m total, "
                f"median {movement.get('median_displacement_m')} m"
            )
    conservation = variant.conservation or {}
    print(
        "   conservation: units "
        f"{conservation.get('units_assigned')}/{conservation.get('units_required')} "
        f"exact={conservation.get('exact')} duplicate_pins={conservation.get('duplicate_sku_bin_pairs')}"
    )
    return variant


def _baseline_evaluation_kwargs(variant: BaselineVariant) -> dict:
    return {
        "baseline_path": variant.repaired_path if variant.is_repaired else None,
        "baseline_variant": variant.variant,
        "baseline_repair": variant.repair,
        "baseline_note": variant.note,
    }


def run_simulate(args: argparse.Namespace) -> None:
    """Phase 6: baseline vs optimized route simulation + evaluation."""
    config = Config.from_json(Path(args.config))
    processed = Path(args.processed)
    out = PROJECT_ROOT / args.output
    variant = _prepare_baseline(processed, config)
    result = run_phase6(
        processed,
        scenario=args.scenario,
        out=out,
        optimized_path=PROJECT_ROOT / args.optimized if args.optimized else None,
        separation_radius_m=config.separation_radius_m,
        **_baseline_evaluation_kwargs(variant),
    )
    print(json.dumps(result, indent=2))
    _exit_if_evaluation_blocked(result)


def run_all(args: argparse.Namespace) -> None:
    """Phase 8: run the full pipeline end-to-end from the canonical dataset."""
    config = Config.from_json(Path(args.config))
    processed = Path(args.processed)
    out_root = OUTPUT_ROOT

    print("== validate ==")
    wh, skus, comp, baseline, inventory = load_shipping(processed)
    res = validate_assignment(
        baseline, skus, wh, comp, inventory,
        separation_radius_m=config.separation_radius_m,
    )
    write_constraint_audit(baseline, res, out_root / "constraint_audit.csv")
    write_validation_checks(res, out_root / "validation_checks_baseline.csv")
    write_assignments_csv(baseline, out_root / "baseline_assignments.csv")
    _write_dataset_validation(processed, out_root)
    print(f"   baseline feasible={res.is_feasible} violations={len(res.violations)} checks={res.checks_run}")
    print("== baseline repair ==")
    variant = _prepare_baseline(processed, config)
    print("== analysis ==")
    run_phase3(
        processed,
        out_root / "analysis",
        config_abc={
            "a_share": config.demand.abc_a_cumulative_share,
            "b_share": config.demand.abc_b_cumulative_share,
            "scenario": "A",
            "affinity_scenario": "C",
        },
    )
    print("== optimize ==")
    opt_summary = run_phase5(processed, config, out_root / "optimized", baseline_variant=variant)
    print(
        f"   execution={opt_summary.get('execution_status')} "
        f"feasibility={opt_summary.get('feasibility_status')} "
        f"violations={opt_summary.get('n_violations')} "
        f"rules={opt_summary.get('violations_by_rule')}"
    )
    print("== simulate ==")
    evaluation = run_phase6(
        processed,
        scenario=args.scenario,
        out=out_root / "evaluation",
        optimized_path=out_root / "optimized" / "optimized_assignments.csv",
        separation_radius_m=config.separation_radius_m,
        **_baseline_evaluation_kwargs(variant),
    )
    print(
        f"   evaluation_status={evaluation.get('evaluation_status')} "
        f"comparison_valid={evaluation.get('comparison_valid')} "
        f"blocked_layouts={evaluation.get('blocked_layouts')} "
        f"baseline_variant={evaluation.get('baseline_variant')}"
    )
    _exit_if_evaluation_blocked(evaluation)
    print("== done ==")


def main() -> None:
    parser = argparse.ArgumentParser(prog="smart-warehouse-slotting")
    sub = parser.add_subparsers(dest="command", required=True)

    p1 = sub.add_parser("build-phase1")
    p1.add_argument("--config", default="configs/small_warehouse.json")
    p1.add_argument("--output", default="outputs/phase1")
    p1.add_argument("--seed", type=int, default=None)
    p1.set_defaults(func=build_phase1)

    p2 = sub.add_parser("build-dataset")
    p2.add_argument("--config", default="configs/dataset.json")
    p2.add_argument("--seed", type=int, default=None)
    p2.set_defaults(func=build_dataset_cmd)

    p3 = sub.add_parser("run-analysis")
    p3.add_argument("--config", default="configs/benchmark.json")
    p3.add_argument("--output", default="outputs/analysis")
    p3.set_defaults(func=run_analysis)

    p4 = sub.add_parser("validate")
    p4.add_argument("--config", default="configs/benchmark.json")
    p4.add_argument("--processed", default=str(CANONICAL_PROCESSED))
    p4.add_argument("--output", default="outputs")
    p4.set_defaults(func=run_validate)

    p5 = sub.add_parser("optimize")
    p5.add_argument("--config", default="configs/benchmark.json")
    p5.add_argument("--processed", default=str(CANONICAL_PROCESSED))
    p5.add_argument("--output", default="outputs/optimized")
    p5.set_defaults(func=run_optimize)

    p6 = sub.add_parser("simulate")
    p6.add_argument("--config", default="configs/benchmark.json")
    p6.add_argument("--processed", default=str(CANONICAL_PROCESSED))
    p6.add_argument("--scenario", default="A")
    p6.add_argument("--optimized", default=None, help="path to optimized_assignments.csv")
    p6.add_argument("--output", default="outputs/evaluation")
    p6.set_defaults(func=run_simulate)

    pall = sub.add_parser("run-all")
    pall.add_argument("--config", default="configs/benchmark.json")
    pall.add_argument("--processed", default=str(CANONICAL_PROCESSED))
    pall.add_argument("--seed", type=int, default=None)
    pall.add_argument("--scenario", default="A")
    pall.set_defaults(func=run_all)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()