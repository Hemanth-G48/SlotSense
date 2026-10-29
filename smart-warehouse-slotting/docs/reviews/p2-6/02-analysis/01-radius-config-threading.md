# Item 1 — Radius comes from config, and the effective value is in the run metadata

**Verdict: PASS** (with two code-level notes and one required test change)

## What the checklist asked

`configs/benchmark.json` contains `separation_radius_m: 10.0`; the optimizer and the validator BOTH obtain it
from config; no module hard-codes `10.0`; the effective value appears in run metadata.

## Configuration is the single source

| Location | Evidence |
|---|---|
| The value itself | `configs/benchmark.json:29` → `"separation_radius_m": 10.0` |
| Parsed once, validated | `src/models/config.py:23-41` `coerce_separation_radius_m` — rejects bool, non-numeric, non-finite and negative; `0` allowed and documented as "rule disabled" |
| Field + `__post_init__` | `src/models/config.py:105-108`, `118-120` |
| Threaded to the **validator** | `src/optimization/pipeline.py:114-120` (`radius = config.separation_radius_m`, `Validator(..., separation_radius_m=radius)`) |
| Threaded to the **optimizer** | `src/optimization/pipeline.py:129-142` (`SlottingOptimizer(..., separation_radius_m=radius, compatibility_rules=comp)`) |
| Contract between the two | `src/optimization/optimizer.py:257-271` — the optimizer takes the validator's radius by default and **raises** `ValueError("separation_radius_m mismatch")` if given a different explicit one |
| Gate side | `src/simulation/pipeline.py:136-140`, `220-225`, `304` — the same radius validates both layouts and the diagnostic baseline |
| CLI | `app/main.py:90`, `102`, `204`, `221`, `254` — all `config.separation_radius_m` |
| Dashboard | `app/dashboard.py:1911` — passes `config.separation_radius_m` into the dashboard-triggered evaluation |

`grep -rn "10\.0" src/ app/ --include=*.py` finds exactly one radius literal:

```
src/models/config.py:20:DEFAULT_SEPARATION_RADIUS_M: float = 10.0
```

The other `10.0` hits are unrelated (`src/data_processing/generate.py` product/box dimensions and a
`1/(rank+10)` ranking term; `src/simulation/simulator.py:24,119` `setup_time_sec`). No module re-declares the
radius, and neither the optimizer nor the validator hard-codes it — both read it from `Config` (`pipeline.py`)
or from each other (`optimizer.py:261-271`).

## The effective value is in the run metadata

| Artifact | Field | Value |
|---|---|---|
| `outputs/optimized/optimization_summary.json` | `separation_radius_m` | `10.0` |
| same | `separation_grid.radius_m` | `10.0` |
| `outputs/evaluation/evaluation_summary.json` | `separation_radius_m` | `10.0` |
| same | `assumptions.separation_radius_m` | `10.0` |
| `outputs/validation_status.json` | `separation_radius_m` | `10.0` |
| `outputs/optimized/run_history.json` | `separation_radius_m` per entry | `10.0` on run_id ≥ 3 (run_id 1–2 predate the field) |

Dossier: `03-dossiers/d05-artifact-numbers.txt`.

## Proof the config value really decides both sides

`tests/test_cat01_separation_radius.py:250-303`
`test_pipeline_honours_one_configured_radius_in_both_placer_and_validator` runs `run_phase5` on the tiny
fixture at R = 10 m and at R = 11 m and asserts: the reported radius and `separation_grid.radius_m` follow
the config; the placer's verdict flips (`FEASIBLE` → `INFEASIBLE`), the unplaceable SKU is reported with
`binding_reason == "separation"`, and the grid records more rejections at 11 m; then the *same* layout is
re-validated at 10 m (feasible) and at 11 m (CAT-01 violations). A hard-coded radius could not produce a
difference. `:232-247` separately asserts the mismatch guard. Both pass.

## Notes (not blockers)

1. `run_phase6(..., separation_radius_m=None)` falls back to `DEFAULT_SEPARATION_RADIUS_M`
   (`src/simulation/pipeline.py:136-140`). This is deliberate and documented
   (`docs/PHASE_2_PART2_REPAIR_AND_GATE.md:121-122`), and every production caller passes the config value.
   But it means a caller that forgets the kwarg silently evaluates at 10 m. A `ValueError` on `None` would
   make the contract unmissable.
2. **Required change (see item 7)** — `tests/test_phase5_optimizer.py:80` calls
   `validate_assignment(assignments, skus, wh, comp, inventory)` with no `separation_radius_m`, so the test
   that is supposed to prove "the optimized output passes the validator" validates at the *default* rather
   than the configured radius. It is correct today only because both happen to be 10.0.

SOURCES (LAYER 3 NAVIGATION)
/home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting/docs/reviews/p2-6/03-dossiers/d05-artifact-numbers.txt
 -> The six artifacts' radius fields, dumped verbatim
/home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting/docs/reviews/p2-6/03-dossiers/d01-pytest-full-suite.txt
 -> The run that proves the radius-threading tests pass
