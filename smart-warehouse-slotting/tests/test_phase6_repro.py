"""Phase 6 reproducibility tests: preflight, collision, failure propagation, manifest hash."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools import run_all


def test_dataset_manifest_is_deterministic(tmp_path):
    root = tmp_path / "processed"
    root.mkdir()
    (root / "a.csv").write_text("x\n1\n")
    (root / "b.csv").write_text("y\n2\n")
    first = run_all._dataset_manifest(root)
    second = run_all._dataset_manifest(root)
    assert first["sha256"] == second["sha256"]
    assert first["n_files"] == 2


def test_preflight_rejects_missing_dataset(tmp_path):
    with pytest.raises(RuntimeError, match="dataset not found|missing dataset"):
        run_all._preflight(tmp_path / "absent", Path(run_all.sys.executable))


def test_existing_run_directory_is_not_reused(tmp_path):
    out = tmp_path / "runs"
    (out / "fixed").mkdir(parents=True)
    with pytest.raises(SystemExit, match="already exists"):
        run_all.run(
            dataset=Path(run_all.DEFAULT_DATASET),
            out_base=out,
            run_id="fixed",
            python=Path(run_all.sys.executable),
            force=False,
            timeout=10,
        )


def test_failed_preflight_records_failed_status_and_does_not_run_stages(tmp_path):
    out = tmp_path / "runs"
    summary = run_all.run(
        dataset=tmp_path / "absent",
        out_base=out,
        run_id="failed_run",
        python=Path(run_all.sys.executable),
        force=False,
        timeout=10,
    )
    assert summary["status"] == "FAILED"
    assert summary["stages"] == []
    written = json.loads((out / "failed_run" / "run_summary.json").read_text())
    assert written["status"] == "FAILED"
    latest = json.loads((out / "latest.json").read_text())
    assert latest["status"] == "FAILED"
    assert latest["run_id"] == "failed_run"


def test_failure_is_not_masked_by_an_old_run(tmp_path):
    out = tmp_path / "runs"
    success = {"status": "PASS", "run_id": "old"}
    (out / "old").mkdir(parents=True)
    (out / "old" / "run_summary.json").write_text(json.dumps(success))
    (out / "latest.json").write_text(json.dumps(success))
    run_all.run(
        dataset=tmp_path / "absent",
        out_base=out,
        run_id="new",
        python=Path(run_all.sys.executable),
        force=False,
        timeout=10,
    )
    latest = json.loads((out / "latest.json").read_text())
    assert latest["run_id"] == "new"
    assert latest["status"] == "FAILED"


def test_phase6_verifier_rejects_a_run_without_a_summary(tmp_path):
    from tools.verify_phase6 import verify

    result = verify(tmp_path)
    assert result["all_passed"] is False
    assert result["n_failed"] >= 1
