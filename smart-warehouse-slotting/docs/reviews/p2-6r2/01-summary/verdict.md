# P2-6R2 verdict — REQUEST CHANGES (one clause)

**Task:** `t_833a749e` (kanban; assignee `reviewer`, run 21)
**Date:** 2026-10-29
**Artifact under review:** `docs/PHASE_2_CONSTRAINT_ENGINE.md` (291 lines, sha256 `fb517fe6…09c871`)
**Scope of this pass:** the two items my second pass returned (item 3, objective base; item 6, tolerance
direction), plus a regression check over everything already passing.
**Predecessor:** `docs/reviews/p2-6r/` (task `t_ac784eda`, REQUEST CHANGES on R1/R2).

## Verdict

**REQUEST CHANGES.** Item 3 is fixed and passes. Item 6's *direction* is fixed and passes — the document now
says plainly that the placer is not uniformly stricter, and gets every rule's direction right. But the same
bullet states the placer's `LD-01` divergence as `1e-6 kg`, which the code does not support: the placer's
weight tolerance is `1e-9 kg` in every path (`optimizer.py:788`, `:1208`, `:561`), and the project's own test
pins that contract (`tests/test_phase2_greedy_constraints.py:206` asserts `n * per_unit <= residual + 1e-9`).
One clause, one edit. Nothing else regressed.

This is not a new standard: the previous version of the same sentence said "the placer compares with `1e-9`",
so `1e-6` is an inaccuracy introduced by the R2 fix — exactly the question this re-review was asked to answer.

## Per-item status

| # | Required change | Status | Where it stands |
|---|---|---|---|
| 3 | §11 objective row on the repaired baseline, `−61.13 %` | **PASS** | §11:178 = `2,321,711 → 902,393 (−61.13 %)`. Re-derived from the artifact: `(2321711.3822095753 − 902392.9055567493) / 2321711.3822095753 = 61.132425 %` → `61.13`. The summary's own `objective_improvement_pct` is `61.132`. Neither `2,336,184` nor `2336184` nor `61.4` occurs anywhere in the document (`03-dossiers/d03-doc-greps.txt`). Rounding to whole kg is correct in both columns: 2,321,711 and 902,393. |
| 6 | §5 tolerance paragraph exact per scope, including the LD/VD direction | **PARTIAL — direction fixed, one magnitude wrong** | Direction **PASS**: §5:82 now says "the **validator is stricter** (no tolerance)" for `LD-01`/`VD-01`, and §5:79 drops the false generalisation ("the placer is **not** uniformly stricter"). `CAT-01` ✓ identical inclusive boundary; `SL-01`/`SL-02`/`RK-01` ✓ cannot disagree. Magnitude **FAIL**: §5:82-83 says "the placer allows `+1e-6` over … up to 1e-6 kg/cm³". The code allows `+1e-9 kg` for `LD-01` and `+1e-6 cm³` for `VD-01` — see R1. |
| — | Nothing else regressed | **PASS** | 24 numeric claims outside §5:79-86 and §11:178 re-checked against the run summaries and the evidence file; all unchanged and still correct. The suite also re-ran green: **181 passed** twice (238.07 s / 239.59 s), matching §10's count. One pre-existing stale figure surfaced (§11:179 "32.5 s" vs the artifact's `runtime_sec: 33.858`) — advisory A5, not a regression. `02-analysis/regression-check.md` |

## Required before approval

**R1 — `docs/PHASE_2_CONSTRAINT_ENGINE.md:82-83`, state the placer's tolerance per rule, not as one number.**

Current text:

> `LD-01`/`VD-01`: the **validator is stricter** (no tolerance) while the placer allows `+1e-6` over. The
> placer could therefore accept a placement the validator rejects by up to 1e-6 kg/cm³ …

What the code does, per rule and per path:

| Rule | Validator | Placer affordability | Placer guard | Placer repair filter | Real divergence |
|---|---|---|---|---|---|
| `LD-01` bin weight | `total <= max_weight_kg`, none (`validator.py:406`) | `n*unit <= residual + 1e-9` (`optimizer.py:1208`) | `residual < -1e-9` fails (`:561`) | `weight > max_weight_kg + 1e-9` (`:788`) | **≤ 1e-9 kg** |
| `VD-01` bin volume | `total <= usable_volume_cm3`, none (`validator.py:428`) | `n*unit <= residual + 1e-9` (`:1208`) | `residual < -1e-6` fails (`:564`) | `volume > usable_volume_cm3 + 1e-6` (`:790`) | **≤ 1e-6 cm³** |

So the single `1e-6 kg/cm³` is right for volume and 1,000× too loose for weight. Suggested replacement for the
first two sentences (the rest of the bullet can stand):

> `LD-01`/`VD-01`: the **validator is stricter** (no tolerance); the placer is looser by at most **1e-9 kg**
> for `LD-01` (split arithmetic and repair filter, `optimizer.py:1208`, `:788`; ledger guard `:561`) and by at
> most **1e-6 cm³** for `VD-01` (volume ledger guard `:564`, repair filter `:790`; the split arithmetic itself
> is 1e-9). The placer could therefore accept a placement the validator rejects by those margins — real, but
> unreachable in practice for the reason already given …

Two supporting points, both optional to state:

1. The repair and annealing paths cannot accept a validator-rejected layout at all: every candidate is
   re-validated and only `cand_result.is_feasible` is ever taken (`optimizer.py:936`, `:996-997`). The only
   unscreened path is the greedy's own `_split_quantity`, whose weight margin is 1e-9.
2. The probe sentence (§5:85-86) is accurate but under-described: it covered 1,027 unit **weights** and 1,194
   unit **volumes** × 400 random residuals, and the window searched was `0 < overdraft <= 1e-9`. Measured worst
   accepted overdraft: `9.09e-13 kg`, `1.86e-9 cm³`. If the bullet keeps a 1e-6 volume claim, say that the
   probe covered the weight band and that the volume margin is the guard's, since the guard's 1e-6 window is
   never reachable through the screened paths.

## Advisories (non-blocking)

- **A2 — §4:58** *(carried forward from the previous pass)*. "3,594 checks for 1,425 occupied bins" is the
  *as-supplied* count; the repaired baseline records 1,039 CAT-01 checks and the optimized layout 0 (its
  closest forbidden pair is 27.2 m). Naming the layout would remove the ambiguity.
- **A3 — §11.2:221** *(carried forward)*. "a 0.6 % increase in stock on one beam … would flip the layout
  infeasible" is slightly tight: headroom is 1.364 kg on 214.636 kg = 0.6354 %, so a 0.64 % increase is the
  flip point (a 0.6 % increase still fits). "well under 1 %" would be exact enough.
- **A4 — §4:69-71** *(new, pre-existing text)*. "the canonical run reaches 55.6 % of the tightest beam limit
  and only 34.7 % of the level limit" uses the *as-supplied baseline's* figures (evidence: 55.56 / 34.72).
  The optimized layout is at 99.37 / 99.56. Correct as written, but the same unnamed-layout ambiguity as A2.
- **A5 — §11:179** *(new, pre-existing text; not a regression)*. "32.5 s for 600 moves (16 accepted)" — the
  move counts match `moves_evaluated: 600` / `moves_accepted: 16`, but the delivered summary records
  `runtime_sec: 33.858`. Changing "32.5 s" to "33.9 s" or "≈34 s" would close it; worth doing in the same
  edit as R1.

## Implication

Phase 2's engine, gate, evidence and numbers are untouched by this finding and remain sound; this is one clause
of documentation prose about a tolerance that is unreachable in every published layout. Apply R1 and the
document can be signed off — items 1, 2, 4, 5 and item 3 need no further work.

SOURCES (LAYER 1 NAVIGATION)
/home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting/docs/reviews/p2-6r2/02-analysis/objective-base.md
 -> The §11 objective re-derivation, field by field, and the grep proving the as-supplied value is gone

/home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting/docs/reviews/p2-6r2/02-analysis/tolerance-direction.md
 -> Per-scope, per-path tolerance table with line references and the measured probe that decides R1

/home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting/docs/reviews/p2-6r2/02-analysis/regression-check.md
 -> The 24 untouched numeric claims re-verified against the artifacts since the last pass

/home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting/docs/reviews/p2-6r2/03-dossiers/
 -> Raw probe output, code citations, doc greps and artifact fields behind every number above
