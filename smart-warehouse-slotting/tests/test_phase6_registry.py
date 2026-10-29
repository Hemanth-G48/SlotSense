"""Phase 6 run-registry tests: reads recorded status, never invents PASS."""

from __future__ import annotations

import json
from pathlib import Path

from app.phase6_registry import latest_run, load_runs


def _run(base: Path, run_id: str, status: str, stages: list[dict]) -> None:
    run = base / run_id
    run.mkdir(parents=True)
    (run / "run_summary.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "status": status,
                "started_at_utc": "2026-01-01T00:00:00+00:00",
                "finished_at_utc": "2026-01-01T00:01:00+00:00",
                "stages": stages,
                "failed_stage": next((s["name"] for s in stages if s["exit_code"] != 0), None),
                "dataset_manifest": {"sha256": "d" * 64},
                "config_sha256": "c" * 64,
            }
        )
    )
    (base / "latest.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "status": status,
                "run_dir": str(run),
                "summary": str(run / "run_summary.json"),
                "finished_at_utc": "2026-01-01T00:01:00+00:00",
            }
        )
    )


def test_registry_lists_runs_and_latest(tmp_path):
    _run(tmp_path, "r1", "PASS", [{"name": "pytest", "status": "PASS", "exit_code": 0}])
    _run(tmp_path, "r2", "FAILED", [{"name": "pytest", "status": "FAIL", "exit_code": 1}])
    table = load_runs(tmp_path)
    assert list(table["run_id"]) == ["r1", "r2"]
    assert list(table["status"]) == ["PASS", "FAILED"]
    latest = latest_run(tmp_path)
    assert latest["available"] is True
    assert latest["run_id"] == "r2"
    assert latest["n_failed_stages"] == 1
    assert latest["failed_stage"] == "pytest"


def test_missing_registry_is_unavailable_not_zero(tmp_path):
    assert load_runs(tmp_path / "absent").empty
    latest = latest_run(tmp_path / "absent")
    assert latest["available"] is False
    assert "reason" in latest


def test_invalid_summary_is_marked_invalid(tmp_path):
    run = tmp_path / "broken"
    run.mkdir()
    (run / "run_summary.json").write_text("{not json")
    table = load_runs(tmp_path)
    assert list(table["status"]) == ["INVALID"]
