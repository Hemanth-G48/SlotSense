# Phase 6 — Reproducibility and Clean-Room Execution

**Repo:** `/home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting`
**Dataset:** `/home/hemanth/hackathon/epoch_hackathon/dataset/processed` (read-only)
**Entry point:** `./run-all`
**Artifacts:** `outputs/phase6/runs/<run_id>/`

---

## 1. Baseline finding

The checkout is **not a Git repository** (`git rev-parse --is-inside-work-tree` fails at the mount
boundary), and no `run-all` entry point existed before Phase 6. D13 was therefore open for two reasons:
no single orchestrator existed, and there was no reproducible staging procedure. The canonical
`outputs/phase2`–`outputs/phase5` trees were produced by earlier runs and could not be regenerated from
the checkout with one documented command.

Because there is no project Git history, the clean-room test creates a throwaway Git repository from the
current source snapshot and clones it. This exercises the mechanics of a fresh checkout without pretending
the project has an official commit history. The limitation is recorded in the run manifest.

## 2. Prerequisites

Tested on Linux, Python **3.14.4**, `uv` **0.11.14**.

```bash
cd /home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting
uv venv .venv
uv pip install --python .venv/bin/python -r requirements.txt
```

Required inputs:

- `../dataset/processed/` with the ten canonical tables listed in `tools/run_all.py`
  (`locations`, `products`, `compatibility_rules`, `inventory`, `orders`, `order_items`,
  `demand_summary`, `sku_affinity`, `storage_assignments_baseline`, `location_graph`);
- `configs/benchmark.json`;
- no external services, no network at run time, no environment variables beyond those documented below.

The dataset is opened read-only. `run-all` computes a SHA-256 manifest of every file before running and the
Phase 6 verifier recomputes it afterwards; a changed dataset fails the run.

## 3. Single entry point

```bash
./run-all [--dataset PATH] [--run-id ID] [--out-base DIR] [--python PATH] [--force] [--timeout SECONDS]
```

Defaults:

| Variable | Default |
|---|---|
| dataset | `../dataset/processed` |
| run id | UTC timestamp `YYYYMMDDTHHMMSSZ` |
| output base | `outputs/phase6/runs` |
| python | `.venv/bin/python` |
| stage timeout | 1800 s |

A run directory is **never reused** unless `--force` is passed. If a stage fails, the remaining stages do
not run, the process exits nonzero, and `latest.json` points at the failed run — an older PASS cannot
masquerade as the current result.

### Stages

| # | Stage | What it proves |
|---|---|---|
| 1 | `base_pipeline` | `app/main.py run-all` builds analysis, optimized, evaluation and dashboard inputs |
| 2 | `phase3` | split, fit, placement × fragmentation, replenishment, sweep, provenance |
| 3 | `phase4` | held-out layout × policy, regimes, headroom, diagnostics |
| 4 | `phase5` | D37 timing comparison and five paired seeds |
| 5 | `verify_phase4` | independent Phase 4 recomputation |
| 6 | `verify_phase5` | independent Phase 5 recomputation (50 checks) |
| 7 | `optimizer_audit` | hand fixture + canonical 600-sample probe |
| 8 | `capacity_perturbation` | one-unit inventory/capacity failures on the frozen layout |
| 9 | `pytest` | full suite against the generated run artifacts |
| 10 | `verify_phase6` | dataset/output hashes, stage status, cross-phase invariants |

Stage order matters: the base pipeline creates `outputs/evaluation` and `outputs/analysis`; tests then read
the run's artifacts through `OUTPUTS_DIR` / `PHASE3_DIR` / `PHASE4_DIR` / `PHASE5_DIR` instead of the
canonical trees.

### Isolation

The run sets:

```
PHASE3_DIR=<run>/artifacts/phase3
PHASE4_DIR=<run>/artifacts/phase4
PHASE5_DIR=<run>/artifacts/phase5
OUTPUTS_DIR=<run>/artifacts
OUTPUT_ROOT=<run>/artifacts
```

Phase 4/5 runners and `app/main.py` honor these variables, so the canonical `outputs/` trees are untouched.

## 4. Run directory

```
outputs/phase6/runs/<run_id>/
├── artifacts/
│   ├── analysis/                     # base pipeline
│   ├── optimized/                    # base pipeline
│   ├── evaluation/                   # base pipeline
│   ├── phase3/                       # experiment
│   ├── phase4/
│   └── phase5/
├── logs/01_base_pipeline.log … 10_verify_phase6.log
├── optimizer_audit.json
├── capacity_perturbation.json
├── verification.json                 # Phase 6 verifier
├── run_summary.json                  # manifest: stages, hashes, versions, exit codes
└── latest.json                       # pointer to the newest run (PASS or FAILED)
```

`run_summary.json` records: run id, status, start/finish, Python and package versions, platform, dataset
file hashes and aggregate hash, config hash, Git state (or `is_repo: false`), every stage command/exit
code/log path, and SHA-256 for every output artifact.

## 5. Failure behaviour

- Preflight failure (missing dataset, missing config, missing dependency) → `status: FAILED`, zero stages,
  nonzero exit.
- Stage failure → `failed_stage` recorded, later stages skipped, nonzero exit.
- Verifier failure → the run stays `FAILED` even if every experiment completed.
- `latest.json` always points at the newest run, not the newest successful one.

Tests cover: missing dataset, existing run directory, failed preflight, and an old PASS not masking a new
failure (`tests/test_phase6_repro.py`).

## 6. Clean-room execution

```bash
SOURCE=/home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting
CLEAN=/path/to/clean

rsync -a --exclude .venv --exclude outputs --exclude outputs.foreign-backup \
      --exclude .pytest_cache --exclude '__pycache__' "$SOURCE"/ "$CLEAN"/
cd "$CLEAN"
git init -q && git add -A && git -c user.email=phase6@local -c user.name=phase6 commit -qm snapshot
cd ..
git clone -q "$CLEAN" "${CLEAN}_clone"
cd "${CLEAN}_clone"
uv venv .venv
uv pip install --python .venv/bin/python -r requirements.txt
./run-all --dataset "$SOURCE/../dataset/processed" --run-id clean-01
```

The clone has no `.venv`, no `outputs/`, no caches, and no parent artifacts. The result is recorded in
§7; the run manifest is the evidence.

## 7. Recorded results

| Run | Environment | Status | Stages | Duration | Tests | Phase 6 verifier |
|---|---|---|---|---|---|---|
| `phase6-dev-05` | development checkout, isolated artifacts | **PASS** | 10/10 | 15 min 34 s | **294 passed** | **27/27** |
| `clean-01` | fresh Git clone + fresh venv | **PASS** | 10/10 | 35 min 50 s | **294 passed** | **27/27** |

Clean clone commit: `8df87d5581b5c8e37d2c6da37752ca1021511ead`, dirty: **false**. Dataset manifest
`28abd23eb798c8f8…` over 13 files. The copied run is `outputs/phase6/runs/clean-01/`; its
`run_summary.json`, `verification.json` (27/27) and all stage logs are the evidence.

The exact commands, exit codes and hashes are in each run's `run_summary.json` and `logs/`. Do not treat
this table as a substitute for those files.

## 8. Limitations

1. **No official Git history.** The clean-room clone is of a Phase 6 source snapshot, not an original
   project commit. D13 can be verified mechanically but cannot restore a history that does not exist.
2. **Dataset is external.** Reproducibility assumes the read-only canonical dataset is available at the
   documented path; it is not regenerated by `run-all` because it is the fixed benchmark input.
3. **Time.** A full run executes Phase 3 (~4 min), Phase 5 (~5 min), the base pipeline, audits and the
   entire test suite. Stage logs and the manifest make partial failures diagnosable.
4. **Pick-time constants remain assumptions.** Reproducibility does not validate 8 s/line or 8 s/stop.
