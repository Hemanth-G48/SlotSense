# Phase 6 evidence runs

| Run | Status | Environment | Tests | Verifier |
|---|---|---|---|---|
| `phase6-dev-05` | PASS | development checkout, isolated artifacts | 294 passed | 27/27 |
| `clean-01` | PASS | fresh Git clone `8df87d5`, fresh venv, no outputs | 294 passed | 27/27 |

Each run contains:

- `artifacts/` — base pipeline, Phase 3, Phase 4, Phase 5 outputs for that run only
- `logs/` — one log per stage, in execution order
- `run_summary.json` — dataset/config/output hashes, versions, stage exit codes
- `optimizer_audit.json`, `capacity_perturbation.json`
- `verification.json` — 27 independent Phase 6 checks

`clean-01` was executed in
`/home/hemanth/.hermes/profiles/orchestrator/cache/scratch/phase6-clean8/checkout`
and copied here. The clone's worktree was clean at commit
`8df87d5581b5c8e37d2c6da37752ca1021511ead`.

Reproduce:

```bash
cd /home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting
./run-all --run-id <new-id>
```
