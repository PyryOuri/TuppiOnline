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

**H1 result (seed heur-h1-screen, 2,048 base deals per arm), against v2:**

| Threshold | Difference | RAMI declared |
| --- | --- | --- |
| 9 | -0.00575 [-0.00643, -0.00506] | 75% |
| 11 | -0.00376 [-0.00444, -0.00308] | 68% |
| 12 | -0.00195 [-0.00261, -0.00130] | 63% |
| 13 | -0.00085 [-0.00145, -0.00025] | 56% |
| 14 | -0.00013 [-0.00059, +0.00032] | 47% |

**H1 fails**: no arm has its lower bound above 0, and the losses grow as the
threshold falls.

**The lesson for the method.** The teacher's RAMI-over-NOLO choices pay off
for the hands it picks. A lower threshold instead flips the hands just below
the threshold on the heuristic's own RAMI score, and those are poor RAMI
hands. The mining points at the right decision; what needs to change is the
hand evaluation, not its cut-off.

## H2: a learned RAMI hand evaluation (design, 2026-10-01)

**The data:** mining run 3 (100,000 deals, seed mine-v3) prices every show
decision, recording the best RAMI and the best NOLO declaration. v2's
clone plays the rest. The heuristic's hand descriptors and scores are
logged, with extra candidate features: queens, jacks, tens, top sequences,
honours in long suits, position and score.

**The fit** (first half of the deals): a linear model of q(RAMI) - q(NOLO)
on those features, kept to a few readable terms. The rule declares RAMI
when the predicted difference is above 0.

**The check** (second half): is the fitted rule's priced gain against v2's
rule positive on held-out deals?

**The game test** is pre-registered before it runs.

**Calibration failure of the offline showing screen (2026-10-02).**
- Scored the same way on mining run 3's held-out half, the H1 thresholds
  11-14 come out at +0.003 to +0.006 per deal; the games gave -0.004 to
  -0.0001.
- **Likely cause:** each contract was priced by its best show card in the
  actual deal. That clairvoyant choice flatters the contract with more
  variable outcomes, which is RAMI.
- **Consequence:** the fitted H2 rule's +0.0055 is not usable.
- **Fix:** price the card the heuristic itself would show for each contract,
  then re-check the H1 calibration before any new fit.

## H3: RAMI lead rules (pre-registered 2026-10-02)

**The rules** (`tuppi_ai/heuristic_rules.py`, as layers over v2's choice):
- **underlead:** when leading in RAMI, if v2 leads the top card of a suit
  and that card is not a certain winner, lead the suit's lowest card
  instead.
- **cash_singleton_late:** when leading in RAMI with at most 5 tricks left,
  lead a singleton that is a certain winner.

**Offline screen** (mining run 4, 50,000 deals, every action priced; same
cards compared, no maximum taken):
- underlead +0.0162 ± 0.0012 per deal (summed one-step);
- cash_singleton (any time) +0.0033, but negative early as declarer and
  positive late (+0.0051 combined late).

**The screen:**
- Arms: A = underlead, B = cash_singleton_late, C = both (cash_singleton_late
  first).
- Each against v2 on 2,048 base deals (seed heur-h3-screen, v3, score 0-0).

**Selection:** among the arms with a lower bound above 0, the highest point
estimate. If none has, H3 fails.

**Confirmation:** the selected arm on 4,096 fresh base deals (seed
heur-h3-confirm). It **passes** if the lower bound is above 0.

**Calibration:** the screen's results are also compared with the offline
estimates, to judge whether the offline screen is usable for card-play
rules.

**H3 screen result (seed heur-h3-screen, 2,048 base deals per arm), against
v2:**

| Arm | Difference |
| --- | --- |
| A, underlead | +0.00353 [+0.00287, +0.00420] |
| B, cash_singleton_late | +0.00092 [+0.00066, +0.00117] |
| **C, both** | **+0.00417 [+0.00350, +0.00484]** |

**Selected: C.** Its confirmation (4,096 base deals, seed heur-h3-confirm) is
running.

**Calibration.** The offline screen ranked the rules correctly and got the
signs right, but over-estimates their size by about 4-5x:
- underlead: +0.0162 offline, +0.0035 in games;
- cash_singleton_late: about +0.0051 offline, +0.0009 in games.

About 2x of that is expected: the offline sum counts both teams' decisions,
while in the games only the candidate team uses the rule. For card-play
rules the screen is usable for ranking; the game test gives the size.

**H3 confirmation (seed heur-h3-confirm, 4,096 base deals):**
**+0.00416 [+0.00370, +0.00462]** against v2, with 54.0% of deals won.
**H3 passes.**
- The two RAMI lead rules (cash_singleton_late, then underlead) form a
  confirmed successor candidate.
- For scale: v2's own margin over its predecessor `partner_aware_v1` is
  +0.0054.

**Offline rejects (2026-10-02, mining run 4), not game-tested:**
- nolo_unload (NOLO, partner winning: play the highest card that still
  loses): -0.0020 ± 0.0005 per deal;
- nolo_high_singleton (NOLO, of several singletons lead the highest):
  -0.0001 ± 0.0004.

## H4: second hand low (pre-registered 2026-10-02)

**The rule:** in RAMI, second hand, following suit, if v2 plays a card that
would win the trick now but is not a certain winner, play the lowest card of
the led suit instead.
- Offline: +0.0058 ± 0.0005 per deal, positive in every phase and role.

**The screen:**
- Arm H3 = cash_singleton_late + underlead.
- Arm H4 = H3 + second_hand_low.
- Each is played against v2 on the same 4,096 base deals (seed
  heur-h4-screen), and the arms are paired, H4 minus H3, per base deal.

**Pass the screen:** the paired lower bound is above 0.

**Confirmation:** the same pairing on 4,096 fresh base deals (seed
heur-h4-confirm). It **passes** if the lower bound is above 0.

**H4 screen (seed heur-h4-screen):** H4 minus H3 **+0.00107 [+0.00083,
+0.00131]**, with 3,486 of 4,096 deals identical. It passes.
- The script's automatic check misread its output (it parsed the wrong
  line) and skipped the confirmation; the confirmation was then run as
  pre-registered.

**H4 confirmation (seed heur-h4-confirm):** H4 minus H3 **+0.00099 [+0.00076,
+0.00122]**. **H4 passes.**

## The showing puzzle, solved (2026-10-02)

**The test:** `tools/show_true_price.py` prices show decisions with the real
v2 playing out both branches in the authoritative engine, including
TuppiProject's sooli fallback (40,000 deals).

**The result:** even so, thresholds 12-14 looked positive over all scores
but negative in the games. The games were played at 0-0 only:

| Threshold | 0-0 deals, true continuation | Games (0-0) | Other scores |
| --- | --- | --- | --- |
| 11 | -0.0047 | -0.0038 | -0.0012 |
| 12 | -0.0024 | -0.0020 | +0.0024 |
| 13 | -0.0014 | -0.0009 | +0.0037 |
| 14 | -0.0004 | -0.0001 | +0.0031 |

- **At 0-0 the true-continuation prices match the games.** The best RAMI
  threshold depends on the match score.
- The native clone continuation leans further towards RAMI (about +0.002 at
  0-0), so showing rules are priced only with the true continuation.

**By match state:**
- Hands scoring 12-15 that v2 bids NOLO gain from RAMI when we are at 28 or
  more (+0.005 to +0.03) or they are at 40 or more (+0.013 to +0.048).
- The same hands lose from RAMI when they lead at 4-36 (-0.007 to -0.027).
- v2's RAMI bids above 15 are right in every state.
- In race states, hands scoring 12-15 gain from RAMI; 10-11.5 do not.

**Consequence:** showing rules must be tested over realistic starting
scores (`evaluate --scores uniform`, the mining's 25-state distribution),
not only at 0-0.

## H5: race threshold (pre-registered 2026-10-02)

**The rule** (`race_threshold`): in a race (our score at 28 or more, or
theirs at 40 or more), declare RAMI from a RAMI score of 12 instead of 15,
with v2's own RAMI card. The NOLO-suitability veto is unchanged. Outside a
race nothing changes; at 0-0 the arm is identical to v2 (checked: exactly 0).

**The screen:** against v2, 4,096 base deals, `--scores uniform`, seed
heur-h5-screen. It passes if the lower bound is above 0.

**Confirmation:** 4,096 fresh base deals (seed heur-h5-confirm), uniform
scores. It **passes** if the lower bound is above 0.

## Final package test (pre-registered 2026-10-02, after H5)

**The candidate** `partner_aware_lead_v3`: the H4 layers (cash_singleton_late,
underlead, second_hand_low) plus race_threshold if H5 passes.

**The test:** against v2 on 4,096 fresh base deals each at 0-0 (seed
heur-final-zero) and with uniform scores (seed heur-final-uniform).

**The record:** both results are recorded. The package is adopted for
implementation in TuppiProject if both lower bounds are above 0.

**H5 result (seed heur-h5-screen, uniform scores):** +0.00035 [-0.00074,
+0.00144]. The screen is not passed, so **H5 fails** and no confirmation
was run.
- The true-continuation data predicts +0.00026 ± 0.00044 per deal for one
  team (the rule fires about 0.1 times per deal per team).
- So the effect is real but too small to matter, and race_threshold is left
  out of the package.
- The score dependence of showing remains a lead: larger per-case gains in
  extreme states, but rare.

**Final package result** (cash_singleton_late + underlead + second_hand_low,
against v2, 4,096 base deals each):

| Starting scores | Difference | Won | Points per deal |
| --- | --- | --- | --- |
| 0-0 (seed heur-final-zero) | **+0.00502 [+0.00456, +0.00549]** | 54.7% | +1.59 |
| Uniform (seed heur-final-uniform) | **+0.01225 [+0.01075, +0.01374]** | 54.5% | +1.62 |

- Both lower bounds are above 0, so the package is **adopted** for
  implementation as `partner_aware_lead_v3` in TuppiProject.
- The equity gain is larger with realistic scores. The card-play gain is
  the same, but mid-match deals move the match more than deals from 0-0.

## Implemented: partner_aware_lead_v3 (2026-10-02)

**Where:** TuppiProject branch `heur/partner-aware-lead-v3`, worktree
`~/Developer/TuppiProject-heur`, commit dc554c4, not merged.

**The implementation:**
- `src/tuppi_agents/refined_play.py`: `RefinedPartnerAwarePolicy`
  subclasses v2's policy class and re-ranks with v2's own `_prefer`, so the
  diagnostics carry the new reason codes and keep the inherited ranking.
- `improved_registry.py` declares three new layers and the profile, with
  identity `agent:sha256:0b7b8f939ea1...`. The v2 and discard_v3 identities
  are unchanged.

**Checks:**
- Against the TuppiAI rule layers it is identical on all 1,024 deals (8,192
  games) at 0-0 and with uniform scores.
- TuppiProject agent tests: 334 pass.
- Full suite: 1,850 pass and 6 fail, the same 6 pre-existing failures as on
  the base branch.

**Use:** with `PYTHONPATH=~/Developer/TuppiProject-heur/src`,
`evaluate --opponent partner_aware_lead_v3` or `--checkpoint
profile:partner_aware_lead_v3`.

**Not changed:**
- v2 remains the benchmark and the live server's reference.
- Merging the branch, and switching the benchmark or any live use to v3,
  is the owner's decision.

## A clone of partner_aware_lead_v3 (2026-10-02)

- **Data:** `tools/gen_bc.py --ruleset v3 --profile partner_aware_lead_v3`,
  150,000 deals (seed tuppi-ai-bc-v3, 3% deviations), 6.49M decisions.
- **Training:** `tuppi_ai.bc` 256x2, 10 epochs.
- **Result** (`models/clone_v3_small.pt`):
  - held-out agreement 97.66% (the v2 clone `runs/bc_small.pt`: 97.9%);
  - against v3 without search, 1,024 base deals: -0.00024 [-0.00068,
    +0.00019], at parity. The v2 clone scores -0.0051 against v3.
- **Uses:**
  - the continuation for the next mining round with v3 as the base
    (`heuristic_mining.py --base partner_aware_lead_v3 --clone
    models/clone_v3_small.pt`);
  - a candidate model of the opponents in the bot's rollouts. Not changed;
    that would alter the live bot.
