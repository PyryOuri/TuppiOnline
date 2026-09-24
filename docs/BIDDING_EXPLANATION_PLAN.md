# Plan: the bot's RAMI/NOLO decision in words a player can use

Status: **planned and parked (2026-09-24).** The whole pipeline is built and
tested at toy size (`tests/test_bidding_pipeline.py`); nothing has been run
at scale. Start it with `bash tools/run_bidding_pilot.sh` once the
prerequisites below are settled.

## The question

Can TuppiAI's bidding decision (declare RAMI or bid NOLO) be described in
terms a player can count at the table (high-card points, controls, suit
lengths, low cards, stoppers, seat, score), and how much does a player lose
by bidding with that description instead of the bot's full calculation?

Two questions must be kept apart:

* **What the bot decides** depends only on what it sees when it bids (under
  locked bids: its hand, its seat, how many bid before it, the score), so a
  readable model can plausibly imitate it well. That is what this explains.
* **Whether RAMI was right in a given deal** depends on how the unseen cards
  lie. Hand features cannot capture that (below), and no explanation here
  claims to.

## What earlier work already says (the old bot, the old rules)

All of it measured with `partner_aware_v1` as partner and opponents, bids
visible in order, no sooli (TuppiProject):

* The old bot's rule: RAMI score = HCP + 0.5 per ace + 0.25 per control +
  0.5 per card beyond 4 in the longest suit, RAMI when >= 15 and a NOLO
  score <= 2 (`docs/analysis/rami_nolo_threshold.md` on the archived
  `experiment/rami-nolo-threshold` branch: 15 is too high, ~12.25 better).
* Forehand break-even at **12 HCP**; each low card (2-4) about -0.9 HCP; aces
  and kings add nothing once points are known; hand descriptors explain only
  **R^2 = 0.106** of the value of declaring and the best two-term rule
  captures about a third of the ceiling (`docs/valuation/rami_declaration.md`,
  another author's, uncommitted).
* Seat position matters; one threshold for all seats is probably wrong; not
  settled (`docs/valuation/handoff.md` 1.5).
* Headroom for better showing over the old bot was killed (S1/S1b,
  `docs/showing/`).

Nothing describes TuppiAI, which bids by search (every legal show, 128
worlds), declares RAMI more often (47% of v3 deals against the old bot's
38%), and bids blind under locked bids.

## Prerequisites (decide before the run)

1. **The ruleset-3 sooli-settings leak.** `SearchAgent.choose_action` sets
   the rollouts' sooli options only when `obs.ruleset == 2`; under
   project_target_v3 (ruleset 3) they carry over from the agent's last sooli
   decision: rollout soolis are finished by the exact solver until the agent
   answers a sooli offer, by the heuristics after that, by the solver again
   after a give or a sooli play. The bot's values therefore depend slightly on
   its history within a match, and differ from the measured v2 setup. Fixing
   it (`ruleset >= 2`) changes moves, so it needs a strength check (the v3
   evaluation, ~40 min). **Owner's decision (2026-09-24): not fixed for now**
   (minor). The database describes the bot as it is, with the options reset at
   the start of every game by `gen_game_db.py` (games then depend only on
   their index; checked). If it is fixed later, the database describes the
   previous bot version: regenerate it (the generator refuses to mix
   versions).
2. TuppiAI committed (the generator records the commit and warns when
   `tuppi_ai/` or `native/` has uncommitted changes).
3. The Mac on mains power; the script keeps it awake (`caffeinate -i`); an
   earlier measurement stalled for 1.8 h when the Mac slept.

## Data

`tools/gen_game_db.py` (the game database, reusable beyond this plan): TuppiAI's
best agent on all four seats, project_target_v3, half the deals at 0-0 and
half at a random score. Per game: hands, dealer, score, every action, and the
search's value of every candidate action; plus **shadow bids**: every seat
that did not get to bid (after the first RAMI) is asked what it would have bid
from the observation it would have had (blind), so there are four bids per
deal with no selection by earlier bids. Every 10th deal is held out. About 1
deal/s with 3 workers, 1.5 KB per game compressed; resumable; refuses to mix
bot versions in one database.

Pilot: **5,000 deals** (~1.5 h) -> about 20,000 bid decisions. Full, if the
pilot passes and more precision is wanted: the 50,000-deal database.

## Features (`tuppi_ai/bid_features.py`)

HCP; aces, kings, queens, jacks; controls (A=2, K=1); honours; 10-A cards;
quick tricks (AK 2, AQ 1.5, A 1, KQ 1, Kx 0.5); longest, second longest and
shortest suit; voids, singletons, doubletons; balanced; long-suit points;
low cards (2-4), very low (2-3), middle (5-9); stoppers (A, Kx, Qxx, Jxxx);
NOLO-safe suits (highest card 7 or lower); honours in short suits; short
suits of low cards; a red 3-9 (RAMI without speaking) and a black 3-9 (NOLO
without speaking); seat (0 = forehand); own and opponents' score, the
difference, the distance to 52; the old bot's two scores for reference.

## Models (`tuppi_ai/bid_models.py`, `tools/bid_explain.py`)

Fitted on the training deals, every reported number from the held-out deals:

* the old bot's rule, unfitted (reference);
* one score against a threshold per seat (HCP; the old RAMI score);
* **point counts** of 1-6 features chosen by forward selection on a
  validation split of the training deals, fitted to the bot's own RAMI-minus-
  NOLO value, in HCP-equivalent points rounded to half points, with a
  threshold per seat;
* decision trees of depth 2-4.

## Tests

1. **Agreement** with the bot's choice on held-out bids, overall and by how
   clear the bot's own preference was (|value gap| < 0.002 close, >= 0.01
   clear).
2. **Regret**: the bot's own estimate of what following the rule loses per
   bid (|gap| wherever the rule disagrees), with a deal-clustered interval.
3. **Play test** (`tools/bid_rule_eval.py`): one partnership bids by the rule
   (shown card and all play by the bot), the other is the bot; duplicate, 256
   base deals x 8 games, v3, random scores. The bot against itself scores
   zero, so the result is the rule's cost per deal. The script tests the best
   point count (at most 5 features), the depth-3 tree and the old rule.

## Pass criteria (fixed now, before any data)

A rule is **usable** if all hold:

* at most 5 features, weights in whole or half points (the point count) or at
  most 3 questions deep (the tree);
* agreement >= 85% on held-out bids and >= 95% on clear decisions;
* play-test cost no worse than **-0.002 equity per deal**, the interval's
  lower end no worse than -0.004. For scale: TuppiAI beats the old bot by
  +0.015 per deal; 64 -> 128 search worlds was worth +0.0013.

If none passes: report the best trade-off (agreement against cost) and stop;
no guide is published. If one passes: build the outputs below.

## Outputs if it passes (not built yet: they depend on which rule passes)

* **A bidding guide** (Finnish, one page): the point count and the seat
  thresholds, with examples and the honest limits (it imitates TuppiAI at a
  table of TuppiAI bots; close calls are close).
* **One line per bid in the after-deal review**: "the bot would have bid RAMI:
  +4 from HCP, +1 from the long suit, -2 from low cards; a clear choice" or
  "a close call" (`PointCount.explain` already produces it). Needs a field in
  the review envelope (TuppiProject `deal_review.py`) and a line in the app's
  review sheet.

## Run

    bash tools/run_bidding_pilot.sh                  # 5,000 deals, 256-deal play tests
    DEALS=2000 EVAL_DEALS=128 bash tools/run_bidding_pilot.sh

About 3 hours of machine time at the defaults (database ~1.5 h, fitting ~1
min, three play tests ~30-40 min each). Everything is resumable: rerun the
same command after an interruption. Results: `runs/bidding/pilot/report.md`
and `play_*.json`; judge them against the pass criteria above and record the
outcome in `docs/STATUS.md`.

## Risks

* It describes TuppiAI's bidding among TuppiAI bots; human partners and
  opponents change what declaring is worth.
* The prior evidence (R^2 0.1) says hand features predict the value of
  declaring poorly; the bot's *choice* may still be predictable, which is
  exactly what the pilot finds out.
* Many bids are near-ties; agreement on those is expected to be low and does
  not matter (the regret measures that).
* Card play is not covered: the search's reasons there are specific layouts.
