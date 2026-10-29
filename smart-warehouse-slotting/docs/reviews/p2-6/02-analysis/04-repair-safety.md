# Item 4 — Repair safety: bounded, deterministic, cycle-guarded, strictly improving

**Verdict: PASS**

## What the checklist asked

Bounded; deterministic; cycle-guarded; accepts only strict improvements; re-validates with the FULL rule set;
reports moves attempted / accepted / rejected / unresolved / termination. Show it cannot oscillate.

## The five properties, with line evidence

| Property | Evidence |
|---|---|
| **Bounded** | `optimizer.py:918-923` breaks on `moves_attempted >= cfg.max_moves`; `:921-923` and `:928-929` break on `max_seconds`. `RepairConfig` (`:75-98`) defaults to 400 moves / 20 s for the optimizer and 4,000 / 240 s for the baseline (`baseline.py:74-80`); both bounds are copied into the report (`RepairStats.max_moves`, `max_seconds`). |
| **Deterministic** | Every candidate list is sorted before it is consumed: `:769-772` (records, by `(sku_id, location_id, index)`), `:806` (targets by `(distance, location_id)`), `:824-827` (records again), `:845-850` (dispatch targets), `:873` (`swaps.sort()`). No RNG is touched anywhere in `_repair`. |
| **Cycle-guarded** | `:912` seeds `seen` with the input layout; `:930-935` hashes each candidate's `(sku_id, location_id, qty)` digest and skips one already seen, incrementing `cycles_detected`. |
| **Strict improvement only** | `:670-687` `_is_strict_improvement`. |
| **Full rule set re-validation** | `:936` `cand_result = self.validator.validate(cand, record_checks=False)` — the whole `Validator.validate`, all 16 rule families, not a subset. `repair_feasibility_only` (`:1067`) does the same on entry. |
| **Reporting** | `RepairStats.to_dict` (`:125-145`): `moves_attempted`, `moves_accepted`, `moves_rejected`, `cycles_detected`, `unresolved_violations`, `termination_reason`, `feasible`, plus before/after violation counts and per-rule breakdowns. |

## Why it cannot oscillate

`_is_strict_improvement(before, after)` requires `keys(after) ⊆ keys(before)` and then either
`|after| < |before|`, or `|after| == |before|` **and** `severity_score(after) < severity_score(before)`.

Take the measure

    μ(layout) = ( |violations| , severity_score )

Acceptance forces `keys(after) ⊆ keys(before)`. If `|after| == |before|`, then two key *sets* of equal size
with one contained in the other are equal, so the violation identity set is unchanged and the only way to be
accepted is a strictly lower severity score. Therefore **every accepted move strictly decreases μ
lexicographically**, and μ is bounded below by `(0, 0)` on a finite set of layouts. A strictly decreasing
sequence on a well-ordered finite set terminates. It cannot return to a previous layout, so it cannot
oscillate — the argument does not depend on the `seen` guard, which is a second, cheaper safety net.

The guard can only cause a *false* "already seen" on a hash collision (64-bit tuple hash). That would skip a
legitimate candidate and lower `moves_accepted`; it can never accept a worse layout.

## The one thing the checklist should not be satisfied by

The canonical **optimized** run does not exercise repair: `optimization_summary.json` reports
`initial_violations: 0, moves_attempted: 0, termination_reason: "already_feasible"`. So on the benchmark the
repair loop is proved by tests, not by a hard case — which `docs/PHASE_2_CONSTRAINT_ENGINE.md:220-222`
states openly rather than hiding.

It *is* exercised live on the baseline variant, and I reproduced it (dossier
`03-dossiers/d02-gate-runall-pass.txt`):

```
repair: 1071 -> 0 violations ({'CAT-01': 1071} -> {}) , moves attempted=96 accepted=96 rejected=0,
        terminated=feasible in 7.806s
movement: 96/1425 records relocated, 1471.373 m total, median 12.01 m
conservation: units 6375/6375 exact=True duplicate_pins=0
```

Every one of the 96 proposed moves was accepted and the run terminated on `feasible`, not on a bound — which
is what a correctly-screened feasibility-first neighbourhood should look like.

And a case where it must *stop without succeeding*: in the infeasible-baseline probe
(`03-dossiers/d03-gate-blocked-both-directions.txt`) the same loop reports

```
repair: 1072 -> 1 violations ({'CAT-01': 1071, 'INV-02': 1} -> {'INV-02': 1}),
        moves attempted=96 accepted=96 rejected=0, terminated=no_improving_move
```

— it repaired everything it could reach, could not touch the INV-02 because an INV violation names no bin,
and said `no_improving_move` instead of claiming success. The variant was then refused
(`baseline_variant=as_supplied`, `conservation exact=False`).

SOURCES (LAYER 3 NAVIGATION)
/home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting/docs/reviews/p2-6/03-dossiers/d02-gate-runall-pass.txt
 -> A live repair that reached feasibility in 96 accepted moves
/home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting/docs/reviews/p2-6/03-dossiers/d03-gate-blocked-both-directions.txt
 -> A live repair that terminated on no_improving_move and whose result was refused
