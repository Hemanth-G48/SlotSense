# Item 6 — the tolerance direction is fixed; the `LD-01` magnitude is not

**Question.** The previous version claimed "the placer is stricter than the validator", which is false for two
of the five rules. Does §5 now state the tolerances correctly, per scope, including the `LD-01`/`VD-01`
direction?

**Answer: direction PASS, one magnitude FAIL (`LD-01`).** The document is now right about *who* is stricter
everywhere, and right about *how much* for four of the five rules. It states the fifth (`LD-01`) as `1e-6 kg`
where the code allows `1e-9 kg`.

## What the document now says (`docs/PHASE_2_CONSTRAINT_ENGINE.md:79-86`)

```
- Precedence matches the validator: bin → beam → level → rack. **The tolerances are not uniform, and the
  placer is not uniformly stricter:**
  - `CAT-01`: identical inclusive boundary in both (`d + 1e-9 >= R`).
  - `SL-01`/`SL-02`/`RK-01`: both allow `+1e-6`, so they cannot disagree.
  - `LD-01`/`VD-01`: the **validator is stricter** (no tolerance) while the placer allows `+1e-6` over. The
    placer could therefore accept a placement the validator rejects by up to 1e-6 kg/cm³ — a real but
    unreachable divergence in practice, because the placer sizes quantities in whole units (`WEIGHT_EPSILON_KG
    = 1e-9` only rounds the split arithmetic). An adversarial probe across 1,027 unit weights × 400 residual
    levels plus exact-boundary cases found no reachable overdraft.
```

The two prior falsehoods are gone: the document no longer claims the placer is stricter, and it no longer
presents `LD-01`/`VD-01` as a case where the placer protects the validator. That was the substance of R2.

## Per-scope verification against the code

| Rule | Validator | Placer — split arithmetic | Placer — ledger guard | Placer — repair filter | Verdict |
|---|---|---|---|---|---|
| `CAT-01` | `d + 1e-9 >= radius` (`validator.py:534`) | `dist + 1e-9 < radius` rejects (`separation.py:109`, `DISTANCE_TOLERANCE_M = 1e-9` at `:30`) | — | same grid (`optimizer.py:485`) | **identical inclusive boundary** — doc ✓ |
| `SL-02` beam | `load <= limit + 1e-6` (`:602`) | `n*unit <= residual + 1e-9` (`optimizer.py:1208`) | `load > cap + 1e-9` fails (`:550`) | `post_beam > cap + 1e-6` rejects (`:797`) | placer never looser → **cannot disagree** — doc ✓ |
| `SL-01` level | `load <= limit + 1e-6` (`:615`) | 1e-9 (`:1208`) | `:554` 1e-9 | `:799` 1e-6 | **cannot disagree** — doc ✓ |
| `RK-01` rack | `load <= limit + 1e-6` (`:628`) | 1e-9 (`:1208`) | `:558` 1e-9 | `:801` 1e-6 | **cannot disagree** — doc ✓ |
| `LD-01` bin weight | `total <= max_weight_kg`, **none** (`:406`) | `n*unit <= residual + 1e-9` (`:1208`) | `residual < -1e-9` fails, i.e. `-WEIGHT_EPSILON_KG` (`:561`, constant at `:48`) | `weight > max_weight_kg + 1e-9` (`:788`) | validator stricter — **direction ✓, but the margin is 1e-9 kg, not 1e-6 kg** |
| `VD-01` bin volume | `total <= usable_volume_cm3`, **none** (`:428`) | `n*unit <= residual + 1e-9` (`:1208`) | `residual < -1e-6` (`:564`) | `volume > usable_volume_cm3 + 1e-6` (`:790`) | validator stricter — margin 1e-6 cm³ — doc ✓ |

Reading the last two rows together: the placer's *weight* margin is `1e-9` in all three places it appears
(split arithmetic, guard, repair filter). The only `1e-6` in the `LD-01`/`VD-01` pair belongs to *volume*.
`§5:82-83` merges the two into "`+1e-6` over … up to 1e-6 kg/cm³", which is correct for `cm³` and 1,000× too
loose for `kg`.

## This is not a judgment call — three independent witnesses agree on 1e-9 kg

1. **The constant.** `optimizer.py:44-48`: "Float slack when comparing weights against a structural limit …
   `WEIGHT_EPSILON_KG = 1e-9`", used at `:788` (repair filter), `:1208` (split arithmetic) and `:561` (guard).
   The only literal `1e-6` in a weight comparison in the placer is `:797-801`, which is beam/level/rack.
2. **The project's own test.** `tests/test_phase2_greedy_constraints.py:206` asserts the placer's contract as
   `n * per_unit <= residual + 1e-9`. A document that says `1e-6 kg` contradicts a passing test in the repo.
3. **Measurement.** The probe (1,027 canonical unit weights × 400 random residuals, plus every exact
   `n * unit` boundary and the boundary one ULP below) finds the largest overdraft the placer's split
   arithmetic ever accepts to be **9.09e-13 kg**; the search for any accepted overdraft in `(1e-9, 1e-6]`
   returns **0 hits** (`03-dossiers/d01-probe-output.txt`). Volume: worst case 1.86e-9 cm³.

The document's own parenthetical undercuts it: the same bullet says `WEIGHT_EPSILON_KG = 1e-9`, two sentences
after claiming the weight tolerance is `1e-6`. A reader who checks `:788` finds `1e-9` and cannot tell which
number the author meant.

## The conclusion the paragraph draws is nevertheless sound

Nothing about "unreachable in practice" is wrong. Quantities are integers, so the only way to land in the
window is floating-point rounding in the residual, which the measurements bound at ~1e-12 kg / ~2e-9 cm³:

- the split arithmetic cannot overshoot beyond its own epsilon (`_units_affordable`, `optimizer.py:1190-1212`,
  trims then refills, so the accepted `n` satisfies `n*per_unit <= residual` except for one-ULP rounding);
- the repair path is screened before acceptance — every candidate is re-validated and only
  `cand_result.is_feasible` is taken (`:936`; the annealer at `:996-997`); so the repair filter's `+1e-6 cm³`
  at `:790` and the guard's `-1e-6 cm³` at `:564` can *propose* a candidate the validator would reject but can
  never *accept* one. Only the greedy's own arithmetic is unscreened, and its margin is 1e-9 for both rules;
- all three published layouts record zero `LD-01`/`VD-01` violations (`PHASE_2_EVIDENCE.json`), and the
  delivered optimized layout is at most 100.000 % of a bin limit (`LOC002136`, exactly at its limit — legal).

So R1 is a precision correction to a bound that is conservative, not a rewrite of the finding. The clause
overstates the placer's looseness, which errs toward disclosing more risk than exists; the reason it matters is
that the paragraph exists to state these numbers exactly, and the card's criterion is "matches the code
exactly, per scope".

## Two smaller points, both optional

- `§5:81` — "both allow `+1e-6`" for `SL-01`/`SL-02`/`RK-01` is true of the placer's *repair filter* and
  ledger guard but 1,000× looser than its split arithmetic (1e-9). The conclusion ("cannot disagree") is
  correct either way, because every placer comparison is at or inside the validator's `+1e-6`. Not worth a
  blocking edit; "the placer's loosest comparison is `+1e-6`" would be exact.
- `§5:85-86` — the probe citation is accurate but narrower than the probe: it tested 1,027 **weights** and
  1,194 **volumes**, at a window of `0 < overdraft <= 1e-9`. Saying so would let a reader see that the search
  band matches the 1e-9 claim rather than the 1e-6 one.

SOURCES (LAYER 2 NAVIGATION)
/home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting/docs/reviews/p2-6r2/03-dossiers/d01-probe-output.txt
 -> Measured worst accepted overdraft per rule, the (1e-9, 1e-6] search, and the guard/filter values

/home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting/docs/reviews/p2-6r2/03-dossiers/d02-code-citations.txt
 -> validator.py LD-01/VD-01/structural/CAT-01 excerpts, optimizer.py epsilon + guard + filter + affordability,
    separation.py boundary, and tests/test_phase2_greedy_constraints.py:206

/home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting/docs/reviews/p2-6r2/03-dossiers/d03-doc-greps.txt
 -> The §5 paragraph verbatim, so the quoted text above can be checked against the file
