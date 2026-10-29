"""Tests for the Phase 3 provenance manifest: required fields and real hashes."""

from __future__ import annotations

import hashlib
import json

import pandas as pd

from src.experiments.provenance import build_manifest


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_manifest_records_inputs_config_seeds_and_output_hashes(tmp_path):
    root = tmp_path / "repo"
    processed = tmp_path / "dataset" / "processed"
    processed.mkdir(parents=True)
    pd.DataFrame({"a": [1, 2, 3]}).to_csv(processed / "orders.csv", index=False)

    config = root / "configs" / "benchmark.json"
    config.parent.mkdir(parents=True)
    config.write_text(json.dumps({"separation_radius_m": 10.0, "optimization": {"alpha": 1.0}}))

    out = root / "outputs" / "phase3"
    out.mkdir(parents=True)
    artifact = out / "result.csv"
    pd.DataFrame({"x": [1, 2]}).to_csv(artifact, index=False)

    manifest = build_manifest(
        root=root,
        processed=processed,
        config_path=config,
        outputs={"result.csv": artifact},
        experiment_id="test-run",
        scenario="A_FIT->A_HOLDOUT",
        seeds={"optimizer": 42, "split": None},
        evaluation_protocol={"fit": "earlier 70%", "holdout": "later 30%"},
    )

    assert manifest["schema"] == "phase3.provenance/1"
    assert manifest["experiment_id"] == "test-run"
    assert manifest["run"]["seeds"]["optimizer"] == 42
    assert manifest["run"]["evaluation_protocol"]["holdout"] == "later 30%"
    assert manifest["dataset"]["tables"]["orders.csv"]["sha256"] == _sha(processed / "orders.csv")
    assert manifest["dataset"]["tables"]["orders.csv"]["rows"] == 3
    assert manifest["outputs"]["result.csv"]["sha256"] == _sha(artifact)
    assert manifest["outputs"]["result.csv"]["rows"] == 2
    assert manifest["configuration"]["sha256"] == _sha(config)
    assert manifest["configuration"]["separation_radius_m"] == 10.0
    assert manifest["configuration"]["objective_weights"] == {"alpha": 1.0}
    assert manifest["vcs"]["git"] is False
    assert manifest["dataset"]["license"] == "unknown"
    assert manifest["dataset"]["origin"] == "unknown"
    assert manifest["run"]["split"]["path"] == "none"
    assert manifest["limitations"]


def test_generator_script_marks_origin_as_synthetic(tmp_path):
    root = tmp_path / "repo"
    (root / "src" / "data_processing").mkdir(parents=True)
    (root / "src" / "data_processing" / "generate.py").write_text("# generator\n")
    processed = tmp_path / "dataset" / "processed"
    processed.mkdir(parents=True)
    pd.DataFrame({"a": [1]}).to_csv(processed / "orders.csv", index=False)
    config = root / "configs" / "benchmark.json"
    config.parent.mkdir(parents=True)
    config.write_text("{}")

    manifest = build_manifest(
        root=root,
        processed=processed,
        config_path=config,
        outputs={},
        experiment_id="x",
        scenario="A",
    )
    assert manifest["dataset"]["origin"] == "synthetic (generated in-repo)"
    assert manifest["dataset"]["license"].startswith("not applicable")
    assert any(e["exists"] for e in manifest["dataset"]["origin_evidence"])
