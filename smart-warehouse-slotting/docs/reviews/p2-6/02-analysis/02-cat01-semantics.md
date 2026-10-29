# Item 2 — CAT-01 semantics, and whether the placer's check can disagree with the validator's

**Verdict: PASS**

## What the checklist asked

3-D Euclidean; forbidden pairs from `compatibility_rules` where `allowed == False` **and**
`category_a != category_b`; boundary inclusive (`d + 1e-9 >= R`); no self-comparison; no double counting;
and — if the optimizer re-implements the rule — proof that it cannot disagree.

## The validator's rule (the authority)

`src/validation/validator.py:493-556`:

| Requirement | Line | Implementation |
|---|---|---|
| 3-D Euclidean over bin coordinates | `532-534` | `math.dist((loc_a.x, loc_a.y, loc_a.z), (loc_b.x, loc_b.y, loc_b.z))` |
| Boundary inclusive | `534` | `ok = d + 1e-9 >= radius` — a pair at exactly R passes |
| Forbidden pairs from the matrix, not self-pairs | `219-223` | `{frozenset((r.category_a, r.category_b)) for r in rules if not r.allowed and r.category_a != r.category_b}` |
| No self-comparison | `523-524` | `if cat_a == cat_b: continue` |
| Only forbidden category pairs are checked at all | `525-527` | `if pair not in self.forbidden_pairs: continue` |
| No double counting | `528-531` | `key = tuple(sorted((loc_a.location_id, loc_b.location_id)))`; `if key in seen: continue` |
| Order-independent identity for repair | `75-89` (and `544` `pair=`) | `Violation.identity` uses the sorted bin pair, so the same physical pair keeps one identity whichever side is visited first |

## The placer's re-implementation

`src/optimization/separation.py` builds a uniform grid of cell size R and answers "may I put category X
here?" before committing a bin. It is a genuine second implementation — same rule *data*, different
algorithm — so agreement has to be argued, not assumed.

| Property | Placer | Validator |
|---|---|---|
| Rule data | `separation.py:37-50` — skips `allowed`, skips `a == b`, `frozenset` dedupe | `validator.py:219-223` — identical predicate, identical `frozenset` |
| Decision predicate | `separation.py:109` `if math.dist(...) + DISTANCE_TOLERANCE_M < radius: return False` | `validator.py:534` `ok = d + 1e-9 >= radius` |
| Tolerance | `separation.py:30` `DISTANCE_TOLERANCE_M = 1e-9` | literal `1e-9` |

**The two predicates are exact logical negations of each other** (`not (d + 1e-9 >= R)` ⇔
`d + 1e-9 < R`), over the same `d`, the same `R` and the same `1e-9`.

The only remaining way to disagree is the *search*: the placer looks at 27 cells, the validator at 27 cells
(`validator.py:515-518` vs `separation.py:32-34,100-103`), both with cell size R
(`validator.py:554-556` vs `separation.py:79-82`). With cell size R, two points at distance `d < R` can
differ by at most one cell on each axis (if any axis differed by ≥ 2 the coordinate difference on that axis
alone would be ≥ R). So the 27-cell neighbourhood is *complete* for every pair the rule can reject — neither
side can miss a violation the other reports.

## Empirical confirmation

Dossier `03-dossiers/d04-cat01-agreement-probe.txt`. Eleven hand-built geometries, each compared three ways
— validator, brute-force O(n²) with no grid at all, and the placer's incremental `SeparationGrid`:

| Case | Result |
|---|---|
| exactly R apart | 0 violations / 0 — inclusive, both agree |
| R − 1e-6 apart | 1 / 1 — rejected by both |
| R + 1e-6 apart | 0 / 0 |
| 3-D diagonal 9.9 m × 9.9 m | 0 — a 1-D check would have called this illegal |
| straddling a cell boundary, d just under R | 1 / 1 — the ±1 neighbourhood found it |
| negative coordinates, d just under R | 1 / 1 — `floor` agrees on negatives |
| chain A–C–A in 10 m steps | 2 violations for 3 bins, not 3 — no double counting |
| two bins of the self-paired category (`C`,`C` forbidden in the matrix) | 0 — self-pairs are not a constraint |
| co-located forbidden pair (d = 0) | 1 / 1 |
| 24 bins, alternating forbidden partners | 8 violations, 12 checks evaluated — matches brute force exactly |
| radius 0 | 0 / 0 — the rule is disabled on both sides |

`all cases agree: True (11/11)`, and in every case "duplicate/self rows beyond one-per-pair" was `0`.

## Observations

1. The dedupe key is the **location pair**, not the category pair. Two *different* forbidden category pairs
   sharing one unordered bin pair would collapse into one check. This is unreachable while AS-01 holds
   (`validator.py:445-461`, one SKU per bin) and the canonical run reports `multi_sku_bins: 0`, so it is a
   latent edge case, not a live under-count.
2. `docs/PHASE_2_CONSTRAINT_ENGINE.md:58` says "one check per unordered bin pair". That is imprecise: a check
   is only recorded for pairs whose categories are a forbidden pair and which land in the same or adjacent
   cell — 3,594 CAT-01 checks for 1,425 bins, not ~1 M. See item 9 finding F5.

SOURCES (LAYER 3 NAVIGATION)
/home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting/docs/reviews/p2-6/03-dossiers/d04-cat01-agreement-probe.txt
 -> The 11-case three-oracle comparison, verbatim
/home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting/docs/reviews/p2-6/03-dossiers/d05-artifact-numbers.txt
 -> Canonical-run CAT-01 diagnostics: 13 forbidden pairs, 1,293 queries, 0 rejections
