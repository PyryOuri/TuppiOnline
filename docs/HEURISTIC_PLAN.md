# Improving partner_aware_lead_v2 (owner-assigned 2026-10-01)

**The goal:** a stronger successor to the incumbent heuristic
`partner_aware_lead_v2`, found with the strong self-play policy as a teacher.
v2 itself stays unchanged, because it is the benchmark opponent. A rule that
passes becomes a new registered profile in TuppiProject (on its own branch).

## Method

1. **Mining** (`tools/heuristic_mining.py`): v2 plays all four seats in the
   authoritative engine (v3 rules, random dealer and score).
   - At every showing and trick-play decision, the heuristic's action and
     reason codes are recorded, with VRPO3's action.
   - Each disagreement is priced from the exact full state: every legal
     action is played out with v2's clone on all seats.
   - **Report:** `tools/heuristic_report.py`.
2. **Variants** (`tuppi_ai/heuristic_variants.py`, `evaluate --checkpoint
   heur:<param>=<value>`): the incumbent's own policy class with profile
   parameters overridden. A variant with unchanged values scores exactly 0
   (sd 0) against the incumbent.
3. **Tests:**
   - paired duplicate games against v2 in the authoritative engine (v3);
   - pre-registered criteria: a screen on one seed, a confirmation on a fresh
     seed;
   - the owner's review test: the rule must change decisions the cards leave
     open, and match existing human practice.

## Mining run 1 (2026-10-01; `runs/heuristic/mine1_report.md`)

**The data:** 20,000 deals, 865k decisions.
- The teacher disagrees on 49%, but 60-90% of disagreements change
  nothing.
- The clone picks the heuristic's action 97.8% of the time.

**The largest losses:**
- RAMI opening leads (`rami_lead_best_suit`, the highest card of the best
  suit; about +0.03 per deal summed);
- **NOLO declared where the teacher declares RAMI**: +0.03 to +0.06 per
  case, about +0.007 per deal. The reverse switch prices slightly negative;
- NOLO leads and discards (about +0.001-0.004 each).

## H1: the RAMI declaration threshold (pre-registered 2026-10-01)

**The hypothesis:** `simple_rami_threshold` (15) is too high.

**The screen:**
- Arms: thresholds 9, 11, 12, 13 and 14, everything else unchanged.
- Each arm against v2 on 2,048 base deals (seed heur-h1-screen, v3,
  score 0-0).

**Selection:** among the arms with a lower bound above 0, the highest point
estimate. If none has, H1 fails.

**Confirmation:** the selected threshold on 4,096 fresh base deals (seed
heur-h1-confirm). It **passes** if the lower bound is above 0.
