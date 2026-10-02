# Why the bots bid RAMI so often (2026-10-02)

**The owner's question:** in human play RAMI is played in about 1/3 of
deals, but against the bot about 5/6. RAMI looks risky because of the
doubled stolen-RAMI penalty. Why do the bots prefer it, and is the
defenders' play optimised?

## How often RAMI is bid and played (v3 rules)

All four players bid blind. The bids are revealed from the forehand, and
the first RAMI declares, so a deal is RAMI unless all four bid NOLO.
Measured with `tools/rami_rates.py` (each seat asked in the engine state in
which it is asked).

| Who bids | One hand bids RAMI | RAMI deals (4 alike) |
| --- | --- | --- |
| Human tables (owner's estimate) | about 9-10% | about 1/3 |
| `partner_aware_lead_v3` (bids as v2) | 22.5%, in every position and at every score | 78% |
| Live bot (W=1024) | 39-41% | 97-98% |

**The live bot's rate by position and score:**
- by position: forehand 30-35%, 2nd 24-27%, 3rd 51-59%, dealer 46-47%.
  Being asked at all tells a seat that every earlier bid was NOLO.
- by score: 34% at 0-0 or when behind, 45% when ahead.

The heuristic's bids correspond to a RAMI-score threshold of 15; human
tables bid like a threshold of about 18 (9.4% of hands, 37% of deals).

**A human with three live bots:** roughly 0.9 x 0.6^3, so about 20% of
deals are all-NOLO and about 80% are RAMI. Hands are not independent (three
weak hands imply a strong fourth), which pushes this towards the observed
5/6.

## Reason 1: with a strong hand, NOLO is not the safe bid

`tools/rami_vs_nolo.py`: the same forehand hand, played once with each bid
by the v3 heuristic, 20,000 hands, uniform scores.

| RAMI score | Win with RAMI | Win with NOLO | Points, RAMI / NOLO | Equity, RAMI - NOLO |
| --- | --- | --- | --- | --- |
| 9-12 | 43% | 48% | -7.0 / +0.1 | -0.034 |
| 12-15 | 53% | 50% | -2.9 / +1.1 | -0.017 |
| 15-18 | 66% | 48% | +1.5 / +0.6 | +0.022 |
| 18-21 | 76% | 39% | +5.3 / -2.2 | +0.077 |
| 21-24 | 88% | 29% | +9.5 / -5.5 | +0.134 |

High cards win tricks, which is fatal in NOLO. So with a strong hand,
passing on RAMI does not avoid risk: it swaps a 66-88% RAMI for a 29-48%
NOLO. At 12-15 RAMI still wins more often, but the doubled stolen penalty
makes it the worse bid for the heuristic.

## Reason 2: the rising score often makes the penalty's size irrelevant

Match-equity change for the deal (`models/equity_incumbent.json`, dealer 0):

| Score (us-them) | Win 8 pts | Win 4 pts | Lose 8 pts | Lose 16 (stolen) | Lose 24 (stolen) |
| --- | --- | --- | --- | --- | --- |
| 0-0 | +0.031 | +0.025 | -0.031 | -0.049 | -0.075 |
| we lead 12-0 | +0.022 | +0.009 | -0.039 | -0.039 | -0.039 |
| we lead 24-0 | +0.042 | +0.020 | -0.075 | -0.075 | -0.075 |
| we lead 40-0 | +0.068 | +0.042 | -0.184 | -0.184 | -0.184 |
| they lead 0-12 | +0.039 | +0.039 | -0.022 | -0.058 | -0.115 |
| they lead 0-24 | +0.075 | +0.075 | -0.044 | -0.109 | -0.173 |

- When ahead, any lost deal erases our score, so a stolen RAMI costs exactly
  as much as a lost NOLO.
- When behind, any won deal only resets to 0-0, so a small win counts as
  much as a big one.
- The doubled penalty matters only at 0-0 and when the opponents are
  already ahead. The bot bids RAMI less when behind (34%) than when ahead
  (45%).
- Thinking in raw points over-weights the penalty in most score states.

## Reason 3: strong card play makes more hands worth a RAMI

**Outcomes** from evaluation records and `tools/rami_outcomes.py`:

| Declarer, defenders | RAMI made | Stolen | Declaring team tricks |
| --- | --- | --- | --- |
| heuristic, heuristic | 73% | 27% | 7.8 |
| live bot, heuristic | 86% | 14% | 8.6 |
| live bot, live bot | 70% | 30% | 7.7 |
| heuristic, live bot | 55% | 45% | 7.0 |

**The bot's own valuation at its bids** (W=1024; searched value of the best
RAMI minus the best NOLO):

| RAMI score | Bot bids RAMI | Heuristic bids RAMI | Bot's RAMI - NOLO |
| --- | --- | --- | --- |
| 9-12 | 25% | 0% | -0.015 |
| 12-15 | 55% | 0% | +0.018 |
| 15-18 | 91% | 97% | +0.058 |
| 18-21 | 100% | 97% | +0.121 |

The bot bids RAMI on many hands the heuristic passes. For its own play,
RAMI on 12-15 hands is worth +0.018; for the heuristic's play it is worth
-0.017.

## Is the defenders' play optimised?

**The live bot as defender: yes, by construction.** Its search maximises
match equity, which already weighs the doubled stolen points. It steals 45%
of the heuristic's RAMIs and 30% of its own.

**The heuristic as defender: no.** It steals only 14% of the bot's RAMIs
and 27% of its own.

**The open point:** the bot's bid search models the opponents as the clone
of v2, which defends roughly like the heuristic. Against stronger defence
(other bots, and probably good human players) its RAMI bids are made less
often (86% falls to 70%), so its marginal RAMI bids may be over-optimistic.
E-R1 tests that directly.

## Exploratory test E-R1 (pre-registered 2026-10-02, before its run)

**The question:** does the live bot over-bid RAMI against strong defence?
Its bid search models the opponents as the clone of v2, which defends worse
than the bot.

**The candidate:** the live configuration at W=128 with `rb=-0.02`. RAMI is
declared only when its searched value beats the best NOLO by more than 0.02.

**The opponent:** the same bot without the penalty, so bots defend on both
sides.

**The test:** 512 base deals, uniform scores, seed bvb-rami-v1, rs=1.

**Reading:**
- a lower bound above 0 means the bot over-bids against bot-strength
  defence;
- an upper bound below 0 means its bidding holds up against strong
  defence;
- otherwise the test is inconclusive.

This is a diagnosis, not a deployment test.

**E-R1 result:** cautious-RAMI bot minus the live bot, with bots defending on
both sides, is **+0.00214 [+0.00062, +0.00366]**.
- The lower bound is above 0: **the live bot over-bids RAMI against
  bot-strength defence**.
- The cautious bot declared RAMI in 36.5% of games, the normal bot in
  54.3%.

**E-R1b** (added 2026-10-02, after E-R1): the same cautious bot against the
heuristic benchmark (`partner_aware_lead_v3`), paired with the normal bot on
the same 512 deals (seed bvb-rami-v1, uniform scores, W=128). This shows what
the caution costs against weak defence.

**E-R1b result:** against `partner_aware_lead_v3`, the cautious bot minus the
normal bot is **+0.00170 [-0.00002, +0.00343]**, on 512 paired deals (280
identical).
- RAMI declared: 42.2% against 55.2%; stolen 21.9% against 23.4%.
- Caution costs nothing even against weak defence; if anything it gains.
- **A likely cause:** with own-team policy rollouts, the bot imagines its
  own team playing strongly and the opponents defending like the clone.
  That optimism raised its RAMI declarations from 47% to 56% when SP1
  rollouts were introduced.

## C-R1: cautious RAMI at W=1024 (pre-registered 2026-10-02, before its run)

**The code change:** the RAMI penalty (`rb`) is now applied after E7's
adaptive bid search instead of disabling it. With `rb` 0 the moves are
unchanged (move fingerprint identical at W=1024).

**The test:**
- The live configuration (W=1024, E7, VRPO1 own-team rollouts, keep 0.003 on
  VRPO3) with `rb=-0.02`.
- Against v2, 512 deals, seed perf-e7-v1, rs=1, paired with the stored live
  arm (`b_keep_v3.json`, +0.01978). Neither arm uses the sampler fix.
- CPU reported.

**Reading:** a candidate for deployment if the lower bound is above -0.0010
and the point estimate is above 0. **Deployment is the owner's decision**,
since it changes how often the live bot bids RAMI.

**C-R1 result:** **-0.00116 [-0.00204, -0.00028]** against the live arm
(W=1024, v2 defending, score 0-0).
- RAMI declared: 31.6% against 52.2%.
- CPU: 65,752 s against 59,398 s.
- **It fails the pass rule and is not deployed**; `best.RAMI_MARGIN` stays 0.

## Conclusion so far

| Test | Setting | Cautious minus normal |
| --- | --- | --- |
| E-R1 | W=128, bot defenders, uniform scores | +0.00214 [+0.00062, +0.00366] |
| E-R1b | W=128, v3 heuristic defenders, uniform scores | +0.00170 [-0.00002, +0.00343] |
| C-R1 | W=1024, v2 heuristic defenders, 0-0 | -0.00116 [-0.00204, -0.00028] |

- The right amount of RAMI depends on how well the opponents defend:
  against weak heuristic defence from 0-0, aggressive RAMI pays, and against
  bot-strength defence it over-reaches.
- A fixed margin is not right everywhere.
- **Against good human defence** the live bot probably bids RAMI somewhat
  too often. That cannot be measured without human games.

**Options:**
- the owner's own games (bot RAMIs made or stolen against humans);
- a bid search whose opponent model defends well, for example VRPO for the
  opponents in bid searches only, tested against both heuristic and bot
  defenders.

The earlier grid showed the cost of modelling the opponents as SP1 against
the incumbent (-0.0029), which is the same trade-off.

## Option 1: let the VRPO policy decide more bids (owner-approved 2026-10-02)

**VRPO3's own bidding** (greedy, no search; `tools/rami_rates.py --agent
policy:models/vrpo3_final.pt`, 4,000 deals):
- one hand bids RAMI 24.1% of the time from 0-0 and 27.4% with uniform
  scores;
- by position: forehand 19-21%, 2nd 19-22%, 3rd 23-28%, dealer 36-39%;
- RAMI is played in 81-86% of deals;
- it learned to bid against its own strong defence. The live bot bids RAMI
  on 39-41% of hands.

**The lever:** `keep_show` (evaluate `ks=`), a separate anchor margin for bids.
The live bot keeps VRPO3's bid unless the search beats it by more than that
margin; card play keeps 0.003. Unset, moves are unchanged (fingerprint
identical at W=128).

### Screen O1 (pre-registered 2026-10-02, before its run)

**Arms:** ks = 0.01 and 0.03, otherwise the live configuration at W=128
(VRPO1 own-team rollouts, keep 0.003, VRPO3 anchor, sampler fix).

**Conditions** (512 base deals each, rs=1; fresh seeds):

| Condition | Opponent | Scores | Seed | Pairing |
| --- | --- | --- | --- | --- |
| S1 | the live bot itself, W=128 (bot-strength defence) | uniform | o1-bvb | the value is the difference |
| S2 | `partner_aware_lead_v3` | uniform | o1-heur-u | against the live arm on the same deals |
| S3 | `partner_aware_lead_v3` | 0-0 | o1-heur-z | against the live arm on the same deals |

**Selection:** among the arms with S1 lower bound above 0 and S2 and S3
lower bounds above -0.0010, the one with the highest S1 point estimate. If
none qualifies, option 1 fails at this margin grid.

**Confirmation** (separate, pre-registered with this screen): W=1024 against
v2 at 0-0, paired with `b_keep_v3.json` (512 deals, seed perf-e7-v1).
- **Non-inferior:** the lower bound is above -0.0010 and the point estimate
  is at least 0.
- A W=1024 bot-vs-bot check follows if time allows.
- **Deployment remains the owner's decision.**

**Screen O1 result** (paired differences against the live arm, 512 base
deals each):

| ks | S1 bot defenders | S2 v3 heuristic, uniform | S3 v3 heuristic, 0-0 |
| --- | --- | --- | --- |
| 0.01 | -0.00034 [-0.00227, +0.00160] | -0.00041 [-0.00216, +0.00135] | +0.00044 [-0.00017, +0.00106] |
| 0.03 | +0.00222 [-0.00052, +0.00495] | +0.00039 [-0.00183, +0.00261] | +0.00042 [-0.00042, +0.00125] |

- **O1 fails by its rule:** no arm has S1's lower bound above 0.
- ks=0.03 has the point estimate of the earlier caution gain (+0.002 against
  bot defence; RAMI declared 40.7% against 53.4%) and positive estimates
  against the heuristic in both conditions.
- Bot-vs-bot pairs are noisier than expected (about ±0.0027 at 512 deals).

### O2: ks=0.03, powered (pre-registered 2026-10-02 13:50, after O1)

**The test:**
- S1: ks=0.03 against the live bot at W=128, uniform scores, **2,048 base
  deals**, fresh seed o2-bvb.
- S3: against `partner_aware_lead_v3` at 0-0, 1,024 base deals, seed
  o2-heur-z, paired with the live arm.

**Pass:** S1's lower bound above 0, and S3's lower bound above -0.0010.

**Then:** the W=1024 confirmations of C-R1's form (against v2 at 0-0 paired
with `b_keep_v3.json`: non-inferior, with the point estimate at least 0),
and, if time allows, a W=1024 bot-vs-bot check.
