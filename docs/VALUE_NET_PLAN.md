# Value network for the search (pre-registered 2026-09-29)

The owner asked for work on the parked "value network" idea, to a level where
it improves the project. The criteria below were fixed before any training or
testing.

## Idea

Today every search rollout plays the rest of the deal with the behaviour clone,
up to the exact 6-trick tail. A value network V estimates the outcome of a
deal from a **full-information** trick-play position: all four hands, the
tricks so far, the contract, the declarer, the score and the dealer. Such
positions exist inside the search, because every rollout runs in one sampled
world. A rollout can then stop at a *leaf* and add V instead of playing on.

The leaf is only used in ordinary trick play, at a trick boundary, with more
than `dd_left` tricks left. Below that, the exact tail stays. Sooli deals keep
their current handling.

- **Bid searches.** The leaf is the start of trick play, after the remaining
  bids and any sooli offer. This removes the most expensive part of a bid
  rollout.
- **Card-play searches.** The leaf comes `leaf_tricks` complete tricks after
  the decision.

## Two targets

- **VN1, the rollout value (speed).** V is trained on the outcome of the
  current rollout from that position: clone play plus the exact tail. That is
  the quantity the search already estimates. The data is generated natively,
  in the millions of positions.
- **VN2, the bot's value (strength).** V is trained on the realised outcome of
  games in which the best agent's pair plays the incumbent's pair: the
  evaluation's matchup. An input bit says whether the side to move is the bot
  pair. The clone undervalues contracts that the bot's better play would make
  (STATUS, rami_bonus), so a bid search leaf of V_bot could price bids by the
  bot's own play.

**Caution** (external review, 2026-09-25): a value learned under one
continuation predicts that continuation's outcomes. VN2 therefore learns from
the evaluation's matchup, not from self-play alone. For play against humans,
the opponents are modelled as the incumbent, as the clone rollouts already
assume.

## Criteria (fixed in advance)

Measurement:

- 512 fresh v3 base deals of `tuppi_ai.evaluate`.
- The paired difference against the current agent on the same deals, with the
  same worlds and per-decision reseeding (`rs=1`) in both arms.
- A 95% normal interval over base deals.

**VN1** is adopted if it passes non-inferiority (the lower bound above
-0.0010 equity per deal) **and** saves at least 1.5x in CPU per deal at the
same world count.

**VN2** is adopted if the paired gain is at least +0.0020 with its lower bound
above 0. This is the kill criterion agreed on 2026-09-23. Otherwise it is
killed and recorded.

**Offline screening** comes before any game test. It uses training positions
only, never the test deals. For each candidate it measures:

- the regret of the bid pick against a 4096-world full-rollout reference (VN1);
- the net's held-out error.

Only a screened candidate goes to the game test.

## Data hygiene

- Training deals come from seeds disjoint from every evaluation seed.
- Suit permutations are exact symmetries (there are no trumps), so the 24
  permutations are used for augmentation.

## Results so far (2026-09-29)

- **VN1, not adopted.** The bid leaf at the end of bidding is non-inferior
  (+0.00010 [-0.00067, +0.00088]) but gives only 1.09x less CPU per deal on
  top of E7, below the 1.5x bar. The card-play leaf loses 0.3-1.3e-3 per
  decision. Details are in `docs/STATUS.md`.
- **VN2, killed.** The data is 30,000 bot pair vs incumbent games at W=128
  (`tools/gen_value_games.py`): 206k training rows and 23k held-out rows from
  disjoint games. VN2 was warm-started from VN1 and early-stopped after 300
  steps, because it overfits after that.
  - **Held out,** it predicts the realised outcomes better than VN1 (R^2
    0.481 vs 0.373). VN1 undervalues the bot's side (+0.023 predicted vs
    +0.039 actual); VN2 predicts +0.029.
  - **In search** it declares RAMI far more often: 39% vs 30% of bid
    positions, and 54.6% vs 46.8% of deals in play.
  - **Game test** (512 deals, W=1024, against the live agent):
    **-0.00039 [-0.00126, +0.00048]**. Stolen RAMIs rise from 20.0% to 22.2%,
    and points per deal fall from 4.81 to 4.65. The kill criterion
    (>= +0.0020, lower bound > 0) is not met.
  - The same over-declaration as the earlier RAMI-bonus test: that the bot's
    side does better than the clone expects does not mean it should declare
    more.

**Conclusion.** Neither value net is adopted. A leaf at the end of bidding
matches full rollouts in bid quality and is about 100x cheaper per bid
search, but E7 had already removed most of that cost. A card-play leaf loses
decision quality. The code stays on branch `vn/value-net`, off by default,
for later use; for example, a larger VN2 corpus or live latency under
tighter budgets.
