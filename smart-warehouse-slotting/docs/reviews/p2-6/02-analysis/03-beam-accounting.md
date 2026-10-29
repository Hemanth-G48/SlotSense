# Item 3 — Beam accounting in the greedy, and whether it matches the validator's aggregation

**Verdict: PASS** (two advisory findings on tolerance and disclosure)

## What the checklist asked

The greedy tracks `(rack_id, bay, shelf_level)` residual; a placement cannot exceed `beam_max_weight_kg`;
the residual update matches the validator's aggregation; and — specifically — look for the case where a bin
is partially filled and then topped up.

## The two aggregations are the same key, the same limit, the same arithmetic

| Concern | Greedy | Validator |
|---|---|---|
| Beam key | `optimizer.py:488` `(loc.rack_id, loc.bay, loc.shelf_level)` | `validator.py:583` `(loc.rack_id, loc.bay, loc.shelf_level)` |
| Beam limit | `optimizer.py:344-350` `min` of `beam_max_weight_kg` over the scope | `validator.py:588-590` `min` of `beam_max_weight_kg` over the scope |
| Level key / limit | `optimizer.py:351-358`, `(rack_id, shelf_level)`, `level_max_weight_kg` else `shelf_max_weight_kg` | `validator.py:584,591-593`, identical |
| Rack key / limit | `optimizer.py:359-362` | `validator.py:587,594-596` |
| Load accumulation | `optimizer.py:504-509` — per accepted assignment, added to bin, beam, level and rack | `validator.py:572-587` — per bin, added to beam, level and rack |

One asymmetry, in the safe direction: `_structural_caps` (`optimizer.py:347`) minimises the limit over **all**
bins in the scope, while the validator minimises over only the bins that carry load
(`validator.py:572-596` skips `total <= 0`). The greedy therefore always uses a limit ≤ the validator's, so
it can only be more conservative.

## A placement cannot exceed the residual

`optimizer.py:490-499` passes four residual terms into `_split_quantity`:

```
residual_shelf_weight = level_cap.get(level_key, inf) - level_load[level_key]
residual_rack_weight  = rack_cap.get(loc.rack_id, inf) - rack_load[loc.rack_id]
residual_beam_weight  = beam_cap.get(beam_key, inf)  - beam_load[beam_key]
```

`_split_quantity` (`optimizer.py:1215-1248`) returns `min(wanted, affordable_per_scope…)` and
`_units_affordable` (`optimizer.py:1190-1212`) corrects float rounding in both directions — it trims while
`n * per_unit > residual + 1e-9` and grows while `(n+1) * per_unit <= residual`. So the accepted quantity
satisfies `qty * unit_weight <= residual` for bin, beam, level and rack simultaneously.

Belt and braces: `_assert_never_over_limit` (`optimizer.py:529-570`) re-derives every scope from the ledger
at the end of the starter pass and raises `RuntimeError` rather than hand on a layout whose ledger broke its
own invariant.

## The "partially filled, then topped up" case

There is no such path in the starter, and the reason is structural rather than accidental:

* `_nearest_feasible(sku)` returns each location at most once, and the loop
  (`optimizer.py:475-514`) walks that list once per SKU — so a bin is considered exactly once per SKU, and
  the only quantity that can be placed there is the maximum the residual allows. The bin is never left
  partially filled and revisited.
* A *different* SKU cannot top the bin up: `occupied_by_bin` (`optimizer.py:455, 478-481`) skips any bin
  already holding another SKU, which mirrors the validator's AS-01.
* A SKU may legitimately span several bins, and each accepted placement decrements
  `residual_bin_weight`, `residual_volume`, `beam_load`, `level_load`, `rack_load`
  (`optimizer.py:504-509`) *before* the next candidate is scored — so the second bin's quantity already sees
  the reduced beam residual. The ledger is updated in the right order.

Repair never tops up either: `_feasibility_relocations` moves a whole record (`optimizer.py:807-812`), and
`_objective_candidates` relocates or swaps whole records (`optimizer.py:851-856, 873-883`). No quantity is
ever increased.

## Empirical result on the canonical benchmark

| Layout | SL-02 checks | SL-02 failures |
|---|---|---|
| as-supplied baseline | 960 | 0 |
| repaired baseline | 922 | 0 |
| **optimized** | **662** | **0** |

(Phase 1's optimizer output had 4 SL-02 failures; the delivered one has none.) Dossier
`03-dossiers/d06-doc-claim-crosscheck.txt`.

## Advisory findings

### A. The tolerance is not uniform, and §5 says it is

`docs/PHASE_2_CONSTRAINT_ENGINE.md:79` claims "bin → beam → level → rack, all with the same 1e-6 tolerance".
It is not:

| Rule | Validator tolerance |
|---|---|
| LD-01 bin weight (`validator.py:406`) | **none** — `total <= loc.max_weight_kg` |
| VD-01 bin volume (`validator.py:428`) | **none** — `total <= loc.usable_volume_cm3` |
| SL-02 beam (`validator.py:602`) | `+ 1e-6` |
| SL-01 level (`validator.py:615`) | `+ 1e-6` |
| RK-01 rack (`validator.py:628`) | `+ 1e-6` |

The placer uses `WEIGHT_EPSILON_KG = 1e-9` (`optimizer.py:48`) and its guard tolerates a residual as low as
`-1e-6` cm³ for volume (`optimizer.py:563-565`) — i.e. **looser than VD-01, which tolerates nothing**.

I hunted for a reachable divergence: 1,027 distinct canonical unit weights × 400 random residuals plus every
exact `n * per_unit` boundary and boundaries one ULP below, asked whether `_units_affordable` ever returns an
`n` with `0 < n * per_unit - residual <= 1e-9`. **No case found** (`03-dossiers/d09-tolerance-hunt.txt`), and
the canonical layouts show 0 LD-01/VD-01 violations. So this is a contract/documentation defect, not a live
violation — but the two rules should share a tolerance, and the doc sentence should be corrected.

### B. The delivered layout runs within 0.63 % of a beam limit and 0.44 % of a level limit

Independent aggregation, no pipeline code reused (`03-dossiers/d07-beam-headroom.txt`):

| Scope | Load | Limit | Utilisation | Headroom |
|---|---|---|---|---|
| **optimized** beam `R5-3-1 bay 0 shelf 3` | 214.64 kg | 216.00 kg | **99.369 %** | 1.36 kg |
| optimized beam `R5-1-1 bay 0 shelf 2` | 247.88 kg | 252.00 kg | 98.364 % | 4.12 kg |
| **optimized** level `R5-3-1 shelf 1` | 458.76 kg | 460.80 kg | **99.557 %** | 2.04 kg |
| optimized bin `LOC002136` | 30.00 kg | 30.00 kg | 100.000 % | 0.00 kg |
| repaired baseline (tightest beam) | 130.49 kg | 180.00 kg | 72.493 % | 49.51 kg |

Both layouts are legal. But the *delivered* layout is far tighter than the baseline, and the user-facing
Phase-2 document discusses only the baseline's 55.6 % → 72.5 % and does not mention the 99.4 %/99.6 %
figures that its own evidence file records (`docs/PHASE_2_EVIDENCE.json:212-223`). That is a disclosure gap,
carried as finding F4 in item 9.

SOURCES (LAYER 3 NAVIGATION)
/home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting/docs/reviews/p2-6/03-dossiers/d07-beam-headroom.txt
 -> Top-5 utilisation per scope for both published layouts, recomputed independently
/home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting/docs/reviews/p2-6/03-dossiers/d09-tolerance-hunt.txt
 -> The failed search for a reachable placer/validator tolerance divergence
/home/hemanth/hackathon/epoch_hackathon/smart-warehouse-slotting/docs/reviews/p2-6/03-dossiers/d06-doc-claim-crosscheck.txt
 -> SL-02 check counts per layout
