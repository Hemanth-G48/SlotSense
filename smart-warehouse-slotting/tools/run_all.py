"""Phase 6 reproducibility orchestrator.

Runs the full evidence chain in a fresh run directory:

    preflight -> full test suite -> Phase 3 -> Phase 4 -> Phase 5
    -> Phase 4 verifier -> Phase 5 verifier -> optimizer audit
    -> capacity perturbation -> Phase 6 verifier -> manifest

Every stage writes its own log; the first failure stops the chain and is recorded in
``run_summary.json`` with a nonzero process exit. Outputs never overwrite the canonical
``outputs/phase3``–``outputs/phase5`` trees because Phase 3/4/5 are pointed at the run
directory through ``--out`` / ``PHASE3_DIR`` / ``PHASE4_DIR``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import traceback
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = ROOT.parent / "dataset" / "processed"
REQUIRED_DATASET = (
    "locations.csv",
    "products.csv",
    "compatibility_rules.csv",
    "inventory.csv",
    "orders.csv",
    "order_items.csv",
    "demand_summary.csv",
    "sku_affinity.csv",
    "storage_assignments_baseline.csv",
    "location_graph.csv",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _dataset_manifest(dataset: Path) -> dict:
    rows = []
    for path in sorted(p for p in dataset.rglob("*") if p.is_file()):
        rows.append({"path": str(path.relative_to(dataset)), "sha256": _sha(path), "bytes": path.stat().st_size})
    digest = hashlib.sha256(
        "\n".join(f"{r['path']}:{r['sha256']}" for r in rows).encode()
    ).hexdigest()
    return {"root": str(dataset), "sha256": digest, "n_files": len(rows), "files": rows}


def _packages() -> dict:
    out = {}
    for name in ("pandas", "numpy", "streamlit", "plotly", "pytest"):
        try:
            out[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            out[name] = None
    return out


def _preflight(dataset: Path, python: Path) -> dict:
    problems = []
    if not python.exists():
        problems.append(f"python not found: {python}")
    if not dataset.is_dir():
        problems.append(f"dataset not found: {dataset}")
    missing = [name for name in REQUIRED_DATASET if not (dataset / name).is_file()]
    if missing:
        problems.append(f"missing dataset files: {missing}")
    if not (ROOT / "configs" / "benchmark.json").is_file():
        problems.append("missing configs/benchmark.json")

    imported = {}
    code = (
        "import json, pandas, numpy, streamlit, plotly, pytest;"
        "print(json.dumps({'pandas': pandas.__version__, 'numpy': numpy.__version__}))"
    )
    probe = subprocess.run([str(python), "-c", code], capture_output=True, text=True)
    if probe.returncode != 0:
        problems.append(f"dependency import failed: {probe.stderr.strip()[:500]}")
    else:
        imported = json.loads(probe.stdout)

    result = {
        "checked_at_utc": _now(),
        "python": str(python),
        "python_version": platform.python_version(),
        "dataset": str(dataset),
        "dataset_files_present": not missing,
        "config_present": (ROOT / "configs" / "benchmark.json").is_file(),
        "imports": imported,
        "problems": problems,
        "ok": not problems,
    }
    if problems:
        raise RuntimeError("; ".join(problems))
    return result


def _stage(
    name: str,
    command: list[str],
    run_dir: Path,
    log_dir: Path,
    env: dict,
    timeout: int,
) -> dict:
    log_path = log_dir / f"{len(list(log_dir.glob('*.log'))) + 1:02d}_{name}.log"
    started = _now()
    with log_path.open("w", encoding="utf-8") as log:
        log.write(f"$ {' '.join(command)}\n\n")
        log.flush()
        try:
            proc = subprocess.run(
                command,
                cwd=ROOT,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=timeout,
                text=True,
            )
            code = proc.returncode
        except subprocess.TimeoutExpired:
            log.write(f"\nTIMEOUT after {timeout}s\n")
            code = 124
    return {
        "name": name,
        "command": command,
        "exit_code": code,
        "status": "PASS" if code == 0 else "FAIL",
        "started_at_utc": started,
        "finished_at_utc": _now(),
        "log": str(log_path),
    }


def _git_state() -> dict:
    try:
        rev = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=ROOT, capture_output=True, text=True, timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return {"is_repo": False, "detail": "git unavailable or timed out"}
    if rev.returncode != 0 or rev.stdout.strip() != "true":
        return {"is_repo": False, "detail": rev.stderr.strip() or "not a git work tree"}
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True)
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True)
    return {
        "is_repo": True,
        "commit": commit.stdout.strip(),
        "dirty": bool(dirty.stdout.strip()),
        "dirty_files": dirty.stdout.strip().splitlines(),
    }


def _outputs(run_dir: Path) -> dict:
    out = {}
    for path in sorted(p for p in run_dir.rglob("*") if p.is_file()):
        rel = str(path.relative_to(run_dir))
        if rel in {"run_summary.json", "latest.json", "verification.json"}:
            continue
        out[rel] = {"sha256": _sha(path), "bytes": path.stat().st_size}
    return out


def run(dataset: Path, out_base: Path, run_id: str, python: Path, force: bool, timeout: int) -> dict:
    run_dir = out_base / run_id
    if run_dir.exists() and not force:
        raise SystemExit(f"run directory already exists: {run_dir} (set FORCE=1 or use a new run id)")
    run_dir.mkdir(parents=True, exist_ok=True)
    log_dir = run_dir / "logs"
    log_dir.mkdir(exist_ok=True)
    artifacts = run_dir / "artifacts"
    artifacts.mkdir(exist_ok=True)

    started = _now()
    stages: list[dict] = []
    summary = {
        "schema": "phase6.run/1",
        "run_id": run_id,
        "status": "RUNNING",
        "started_at_utc": started,
        "root": str(ROOT),
        "dataset": str(dataset),
        "config_sha256": _sha(ROOT / "configs" / "benchmark.json"),
        "git": _git_state(),
        "software": {
            "python": sys.version,
            "executable": str(python),
            "platform": platform.platform(),
            "packages": _packages(),
        },
        "environment": {
            "PYTHONHASHSEED": "0",
            "TZ": "UTC",
        },
        "stages": stages,
        "limitations": [
            "The project has no Git metadata, so this is a clean directory copy rather than a Git clone.",
            "Pick-time constants are assumptions, not time-study measurements.",
        ],
    }

    env = os.environ.copy()
    env.update({
        "PYTHONHASHSEED": "0",
        "TZ": "UTC",
        "PHASE3_DIR": str(artifacts / "phase3"),
        "PHASE4_DIR": str(artifacts / "phase4"),
        "PHASE5_DIR": str(artifacts / "phase5"),
        "PHASE6_CAPACITY": str(run_dir / "capacity_perturbation.json"),
        "DATASET_DIR": str(dataset),
        "OUTPUTS_DIR": str(artifacts),
        "OUTPUT_ROOT": str(artifacts),
    })

    try:
        pre = _preflight(dataset, python)
        summary["preflight"] = pre
        summary["dataset_manifest"] = _dataset_manifest(dataset)

        commands = [
            (
                "base_pipeline",
                [str(python), str(ROOT / "app" / "main.py"), "run-all", "--processed", str(dataset)],
                timeout,
            ),
            (
                "phase3",
                [str(python), "-m", "src.experiments.run_phase3", "--processed", str(dataset), "--out", str(artifacts / "phase3")],
                timeout,
            ),
            (
                "phase4",
                [str(python), "-m", "src.experiments.run_phase4", "--out", str(artifacts / "phase4")],
                timeout,
            ),
            (
                "phase5",
                [str(python), "-m", "src.experiments.run_phase5", "--out", str(artifacts / "phase5")],
                timeout,
            ),
            (
                "verify_phase4",
                [str(python), str(ROOT / "tools" / "verify_phase4.py"), str(artifacts / "phase4")],
                timeout,
            ),
            (
                "verify_phase5",
                [str(python), "-m", "src.evaluation.verify_phase5", "--out", str(artifacts / "phase5")],
                timeout,
            ),
            (
                "optimizer_audit",
                [
                    str(python),
                    str(ROOT / "tools" / "audit_optimizer.py"),
                    "--fit-tree", str(artifacts / "phase3" / "split" / "A70" / "fit" / "processed"),
                    "--out", str(run_dir / "optimizer_audit.json"),
                ],
                timeout,
            ),
            (
                "capacity_perturbation",
                [
                    str(python),
                    str(ROOT / "tools" / "capacity_perturbation.py"),
                    "--dataset", str(dataset),
                    "--optimized", str(artifacts / "phase3" / "optimized_fit" / "optimized_assignments.csv"),
                    "--headroom", str(artifacts / "phase4" / "phase4_headroom.csv"),
                    "--out", str(run_dir / "capacity_perturbation.json"),
                ],
                timeout,
            ),
            ("pytest", [str(python), "-m", "pytest", "-q"], timeout),
        ]
        for name, command, stage_timeout in commands:
            result = _stage(name, command, run_dir, log_dir, env, stage_timeout)
            stages.append(result)
            if result["exit_code"] != 0:
                summary["status"] = "FAILED"
                summary["failed_stage"] = name
                break
        else:
            summary["status"] = "PASS"
            # The verifier needs the summary it is verifying, so write a provisional one
            # first (with output hashes), then let the verifier judge it.
            summary["outputs"] = _outputs(run_dir)
            (run_dir / "run_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
            verify = _stage(
                "verify_phase6",
                [str(python), str(ROOT / "tools" / "verify_phase6.py"), str(run_dir)],
                run_dir,
                log_dir,
                env,
                timeout,
            )
            stages.append(verify)
            if verify["exit_code"] != 0:
                summary["status"] = "FAILED"
                summary["failed_stage"] = "verify_phase6"
    except Exception as exc:  # noqa: BLE001 - a preflight crash is evidence
        summary["status"] = "FAILED"
        summary["error"] = f"{type(exc).__name__}: {exc}"
        summary["traceback"] = traceback.format_exc()
    finally:
        summary["finished_at_utc"] = _now()
        summary["n_stages"] = len(stages)
        summary["n_failed_stages"] = sum(1 for s in stages if s["exit_code"] != 0)
        summary["outputs"] = _outputs(run_dir)
        (run_dir / "run_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        out_base.mkdir(parents=True, exist_ok=True)
        (out_base / "latest.json").write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "status": summary["status"],
                    "run_dir": str(run_dir),
                    "summary": str(run_dir / "run_summary.json"),
                    "finished_at_utc": summary["finished_at_utc"],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(prog="run_all")
    ap.add_argument("--dataset", default=os.environ.get("DATASET", str(DEFAULT_DATASET)))
    ap.add_argument("--out-base", default=str(ROOT / "outputs" / "phase6" / "runs"))
    ap.add_argument("--run-id", default=os.environ.get("RUN_ID", ""))
    ap.add_argument("--python", default=os.environ.get("PYTHON", str(ROOT / ".venv" / "bin" / "python")))
    ap.add_argument("--timeout", type=int, default=1800)
    ap.add_argument("--force", action="store_true", default=os.environ.get("FORCE") == "1")
    args = ap.parse_args()

    run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    summary = run(Path(args.dataset).resolve(), Path(args.out_base).resolve(), run_id, Path(args.python), args.force, args.timeout)
    print(json.dumps({k: summary[k] for k in ("run_id", "status", "n_stages", "n_failed_stages", "started_at_utc", "finished_at_utc")}, indent=2))
    raise SystemExit(0 if summary["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
