# Strongest against any strong opponent, not just the benchmark (2026-10-02)

**The owner's goal:** the strongest bot against any strong opponent, bot or
human.

**The concern:** using the heuristic as the benchmark may fit the bot to
exploit that heuristic rather than to play well in general. The RAMI
finding (docs/RAMI_ANALYSIS.md) is a concrete case.

## Where the heuristic enters the bot

| # | Place | How it fits the bot to the heuristic | Size of the risk |
| --- | --- | --- | --- |
| 1 | **The opponent model in every search** | Rollouts play the opponents with the clone of `partner_aware_lead_v2` (`best.ROLLOUT`). Each searched value answers "what is best if the opponents play like v2?" | **Large.** It drives every bid and card. The RAMI over-bidding (-0.0025 against bot defence) is one symptom |
| 2 | **Every selection test** | All live changes were accepted by paired games against the heuristic, so selection favours what beats it | **Large**, because it compounds: each accepted change was chosen on the same opponent |
| 3 | **Explicit choices made against strong-opponent models** | In the rollout-role grid, modelling the opponents as SP1 was rejected because it was "too cautious" against the incumbent (-0.0029). The keep-margin grid and the W=1024 confirmations were all against v2 | **Medium.** These are exactly the decisions that may reverse against strong play |
| 4 | **The equity table** (`models/equity_incumbent.json`) | Match-win probabilities fitted from incumbent self-play deal outcomes | **Small.** It mainly encodes the score rules; deal win rates are symmetric |
| 5 | **Sooli heuristics** | Hand-written, inside both the bot and its rollouts | **Small.** Sooli is rare (under 1-5% of deals) |
| 6 | **Self-play training** (SP1, VRPO) | Trained against itself, not against the heuristic | **None by construction**; these are the robust components |

## How big can the problem be?

**The evidence so far:**
- **Bidding:** a change that is neutral or slightly negative against the
  heuristic gained +0.0025 per deal against bot-strength defence.
- **The opponent model** has never been tested against strong opponents.
  Against the heuristic, modelling the opponents as the heuristic was
  +0.003 better than modelling them as SP1, the expected direction.
  Against strong opponents the sign may flip.
- **Bot against bot,** a heuristic-fitted choice cost about 0.002-0.003 per
  deal (RAMI). Several such choices could add up to roughly 0.005 per deal:
  a sizable fraction of all the gains since 2026-09-29, but not a reversal.

**The estimate:** the bot is probably strong in general, because its policies
come from self-play. Against strong opponents it is likely 0.003-0.008 per
deal below what the same components could give, mostly through #1 and #3.
This is unmeasured, so the first fix is to measure.

## The fixes

1. **A panel of strong opponents as the primary benchmark** (the
   measurement fix).
   - Every candidate is played against a panel of strong opponents: the
     live bot itself (bot-vs-bot), earlier live versions, and VRPO3 without
     search (strong, with a different style).
   - The heuristic stays in the panel only as a guard against regressions.
   - The headline is the panel score; a change must also not lose against
     the heuristic.
2. **A robust opponent model in the search** (the main fix). The rollouts'
   opponents are played by a strong policy, or a mixture, instead of the v2
   clone. Candidates:
   - VRPO1 for all seats (a 256x2 net, same cost);
   - the v3 clone (`models/clone_v3_small.pt`, as a control);
   - a mixture, with the opponents' model chosen per world.
3. **Re-check the heuristic-fitted choices** (#3) on the panel: the
   rollout-role grid, the anchor margins, and RAMI_MARGIN.
4. **Longer term:**
   - a belief model of opponents' hands learned from strong play (the
     search's uniform sampler is opponent-agnostic but ignores inference);
   - human data when it is available.

## Plan

- **P0, the tool:** `tools/panel_eval.py`, a candidate against several
  opponents on the same deals, paired with a reference agent.
- **P1, the first experiment** (pre-registered below before it runs): the
  opponent model in rollouts, on the panel.

## P1: the opponent model in the rollouts (pre-registered 2026-10-02, before its run)

**Reference:** the live configuration at W=128 (bids keep 0.03, card play
keep 0.003 on VRPO3, VRPO1 own-team rollouts, the v2 clone for the
opponents, sampler fix).

**Candidates:** the same, except for the opponents' rollout model:
- **A:** VRPO1 (the same policy as the own team: both teams strong);
- **B:** the v3 clone (`models/clone_v3_small.pt`), the benchmark-matched
  control.

**The panel** (`tools/panel_eval.py`, 512 base deals per opponent, uniform
scores, seed panel-p1|<opponent>):
- **strong:** the reference itself (bot-vs-bot), and VRPO3 without search;
- **guard:** `partner_aware_lead_v3`.

**The screen passes** if the strong-panel mean's lower bound is above 0 and
the guard's lower bound is above -0.0015.

**Next:** a passing candidate goes to a W=1024 check against strong
opposition (bot-vs-bot at W=1024 against the live configuration) before
live use.

**The bias it tests:** A removes the heuristic from the bot's view of its
opponents entirely; B keeps it, matched to the new benchmark.

**P1 result** (W=128, 512 base deals per opponent, uniform scores; candidate
minus reference):

| Candidate | vs live bot | vs VRPO3 | Strong-panel mean | Guard: v3 heuristic |
| --- | --- | --- | --- | --- |
| A, VRPO1 opponent model | +0.00401 ± 0.00360 | +0.01001 ± 0.00406 | **+0.00701 ± 0.00271** | -0.00092 ± 0.00402 |
| B, v3-clone opponent model | -0.00235 ± 0.00294 | +0.00069 ± 0.00344 | -0.00083 ± 0.00226 | +0.00395 ± 0.00308 |

- **This quantifies the concern.** Modelling the opponents as the
  heuristic (B) helps against the heuristic (+0.004) but not against
  strong players. Modelling them as a strong policy (A) gains +0.007
  against strong players and is about neutral against the heuristic.
- **A fails by the rule only through the guard's width.** The strong
  panel's lower bound is +0.0043, but the guard's is -0.0049 against a
  required -0.0015.

### P1b and P1c (pre-registered 2026-10-02 20:55)

**P1b, the guard with power:**
- A against `partner_aware_lead_v3`, 2,048 base deals (seed
  panel-p1b|heur, uniform scores), paired with the reference on the same
  deals.
- It passes if the lower bound is above -0.0015.

**P1c, live strength against strong opposition:**
- A at W=1024 (with E7) against the live configuration at W=1024,
  bot-vs-bot, 512 base deals, uniform scores, seed p1c-bvb.
- It passes if the lower bound is above 0.

**Deployment** (if both pass) is put to the owner. The owner's stated goal
(the strongest bot against strong opponents) favours it, but it changes how
the bot models every opponent.

**P1b result** (A against `partner_aware_lead_v3`, 2,048 base deals, paired):
**-0.00224 ± 0.00196**. The lower bound, -0.0042, is below -0.0015, so the
guard fails: a real cost against the heuristic, the expected price of no
longer fitting it.

**P1c** (W=1024 bot-vs-bot) was **stopped by the owner** after 35 minutes,
before any result.

**Deployed 2026-10-02 (owner's decision: "the improvement against strong
players is something we want right now"):**
- `best.OPPONENT_ROLLOUT = models/vrpo1_actor_0504.pt` (TuppiAI 14a5e25):
  the live bot's searches now imagine strong opponents.
- The review prices with the same model.
- `best_agents(team_rollout=False)` (the research B0) keeps the clone.
- The live server was restarted (pid 69333).

**Expected effect:** about +0.007 per deal against strong opponents (W=128
evidence) and about -0.002 against the heuristic. The W=1024 strength
against strong opposition is unconfirmed.

**Next leads:**
- a mixture opponent model (some worlds with strong opponents, some with
  the clone), to win back the heuristic loss;
- re-checking the rollout-role and anchor choices on the panel;
- P1c at a quiet time, to record the W=1024 effect.
