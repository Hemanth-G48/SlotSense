"""Run-registry reader for the Phase 6 reproducibility runs.

The dashboard must not launch or recompute experiments; it reads the orchestrator's
``run_summary.json`` files and shows their recorded status, hashes and stage outcomes.
Missing or malformed runs are reported as unavailable, never as zero or PASS.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


def load_runs(base: Path) -> pd.DataFrame:
    base = Path(base)
    rows = []
    if not base.is_dir():
        return pd.DataFrame(
            columns=[
                "run_id", "status", "started", "finished", "stages", "failed_stage",
                "dataset_sha256", "config_sha256", "summary",
            ]
        )
    for path in sorted(base.glob("*/run_summary.json")):
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            rows.append(
                {
                    "run_id": path.parent.name,
                    "status": "INVALID",
                    "started": None,
                    "finished": None,
                    "stages": None,
                    "failed_stage": None,
                    "dataset_sha256": None,
                    "config_sha256": None,
                    "summary": str(path),
                }
            )
            continue
        stages = data.get("stages") or []
        rows.append(
            {
                "run_id": data.get("run_id", path.parent.name),
                "status": data.get("status", "UNKNOWN"),
                "started": data.get("started_at_utc"),
                "finished": data.get("finished_at_utc"),
                "stages": len(stages),
                "failed_stage": data.get("failed_stage"),
                "dataset_sha256": (data.get("dataset_manifest") or {}).get("sha256"),
                "config_sha256": data.get("config_sha256"),
                "summary": str(path),
            }
        )
    return pd.DataFrame(rows)


def latest_run(base: Path) -> dict:
    base = Path(base)
    path = base / "latest.json"
    if not path.is_file():
        return {"available": False, "reason": "no Phase 6 run registry"}
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return {"available": False, "reason": f"invalid latest.json: {exc}"}
    summary_path = Path(data.get("summary", ""))
    if not summary_path.is_file():
        return {"available": False, "reason": f"run summary missing: {summary_path}"}
    try:
        summary = json.loads(summary_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return {"available": False, "reason": f"invalid run summary: {exc}"}
    stages = summary.get("stages") or []
    return {
        "available": True,
        "run_id": data.get("run_id"),
        "status": data.get("status"),
        "run_dir": data.get("run_dir"),
        "finished_at_utc": data.get("finished_at_utc"),
        "n_stages": len(stages),
        "n_failed_stages": sum(1 for s in stages if s.get("exit_code") != 0),
        "failed_stage": summary.get("failed_stage"),
        "dataset_sha256": (summary.get("dataset_manifest") or {}).get("sha256"),
        "config_sha256": summary.get("config_sha256"),
        "stages_table": pd.DataFrame(
            [
                {
                    "Stage": s.get("name"),
                    "Status": s.get("status"),
                    "Exit": s.get("exit_code"),
                    "Log": s.get("log"),
                }
                for s in stages
            ]
        ),
    }
