# Phase 5D-A: results of the PIMC failure decomposition

Companion to `docs/search/phase5d_a_hypotheses.md`, which was written **before** these
measurements and is not edited in light of them. That document states the six candidate
causes, which instrument addresses each, and the inferential limits that bound every
conclusion below. This document reports what the instruments returned and which decision
path the evidence selects.

Every experiment here runs on a fresh unsealed **development** bank. Nothing in this
document is promotion evidence, and the promotion-sealed bank was not opened.

## The result being explained, quoted not recomputed

Phase 5C measured `uniform_feasible_pimc_small_v1` against `development_reference_v1`
over 32 complementary complete-match pairs from 0-0:

| | |
| --- | --- |
| `p_win` | 0.156 |
| 95 % CI | [0.075, 0.238] |
| Pair W / T / L | 0 / 10 / 22 |
| Sign-flip p | 0.0001 |

These figures are **quoted** from `reports/phase5c/phase5c_evaluation.json`. Phase 5D-A
does not re-run, revisit, or adjust them. The configuration carries the frozen
designation `uniform_feasible_pimc_small_v1_negative_baseline`, which is metadata only:
the agent id, its configuration id, and the committed Phase 5C registry digest are all
unchanged, and `tests/search/test_phase5d_architecture.py` asserts it.

## Protocol deviation: a smaller per-leg deal cap

Phase 5C ran complete matches with a safety cap of **704** deals per leg and recorded
zero censored legs, because its candidate was weak enough that legs ended quickly - the
PIMC legs averaged 21.8 deals against the reference population's ~30.

Phase 5D-A's candidates are *stronger*, and that makes complete matches dramatically
more expensive. `project_target_v1` resets the score to 0-0 whenever the down team wins a
deal, so two near-equal teams can trade resets almost indefinitely. A first attempt at
the play-only comparison with the Phase 5C cap of 704 ran for **ten hours across six
worker processes without completing a single pair**, and was abandoned.

Phase 5D-A therefore uses a cap of **96** deals per leg. This is a real deviation with a
real cost: censoring is **not** missing-at-random, because the legs it removes are
exactly the closest ones. A censored pair is excluded from `complete_pair_count`, so
p_win here is conditional on the match having resolved within 96 deals. Censoring counts
are reported with every comparison below and the deviation is recorded in
`reports/phase5d_a/phase5d_a_findings.json` under `safety_cap_deviation`.

The measured per-deal cost that forces this is 24.5 s/deal for the play-only variant with
two gated seats, measured on a single instrumented leg.

As it turned out, **the cap never bound in either homogeneous comparison**: zero pairs were
censored and the longest single leg ran 71 deals against the cap of 96. So while the
deviation is real and is recorded, it cost these two results nothing, and their p_win
values are not conditional on anything the Phase 5C protocol would have measured
differently.

## Play-only and show-only: both phases lose, separately

Twelve complementary complete-match pairs each, from 0-0, on the fresh
`phase5d_a_match_v1` bank.

| | Full PIMC (Phase 5C) | Play-only | Show-only |
| --- | --- | --- | --- |
| Searched decisions | showing + cards | cards only | showing only |
| `p_win` | 0.156 | **0.250** | **0.333** |
| 95 % CI | [0.075, 0.238] | [0.059, 0.441] | [0.149, 0.518] |
| Pair W / T / L | 0 / 10 / 22 | 1 / 4 / 7 | 1 / 6 / 5 |
| Sign-flip p | 0.0001 | 0.070 | 0.219 |
| Pairs | 32 | 12 | 12 |
| Censored / failed | 0 / 0 | 0 / 0 | 0 / 0 |

The Phase 5C column is on a different bank with a different cap and four times the pairs;
it is shown for orientation and the three columns are **not** a like-for-like series.

Neither variant is near parity. Play-only, with the reference choosing every contract,
still loses (CI upper bound 0.441). Show-only, with the reference playing every card, also
has its point estimate below 0.5, though its interval spans it and is therefore unresolved
at this sample size. **Restricting search to either phase alone does not recover
competitiveness.**

The secondary metrics say *how* each one loses, and the two stories are different:

| | Play-only | Show-only |
| --- | --- | --- |
| Tricks per match, candidate vs opponent | 191.2 vs **205.2** | 184.2 vs 182.0 |
| Deal points per match, candidate vs opponent | 144.8 vs 220.5 | 147.8 vs 184.0 |
| RAMI share of deals | 0.780 | **0.905** |
| Stolen-RAMI share of RAMI deals | 0.263 | 0.315 |
| Resets per match | 9.8 | 9.2 |

Play-only loses **tricks** - 191 against 205 - which is what a weaker card policy looks
like directly. Show-only wins tricks essentially evenly (184 vs 182, a 1.2 % edge) and
still loses 148 points to 184, while pushing the RAMI share of deals to 0.905 against
play-only's 0.780. That is the showing bias measured above, now visible in match play: PIMC
declares RAMI more often, and the deals it thereby enters do not pay for themselves even
when its side takes an equal number of tricks.

So the two decompositions each identify a real, independent cost, and neither is the whole
loss. Per the pre-registered limits this is exactly what non-additivity predicts: the two
variants partition the *decisions*, not the loss, and a contract the reference would not
have taken changes every card decision that follows it.

## A defective first corpus, and what it changed

The first decision corpus built for this phase was unusable, and the numbers it produced
were wrong. It filled its trick-play target in encounter order, and because a single deal
offers dozens of unforced card decisions, **all 96 of its trick-play positions came from
one set of hands** and its 48 showing positions from three. The clustering was invisible
in the position count and in every stratum table.

It was caught by an independent check rather than by the report itself: the corpus put the
reference's RAMI declaration rate at 0.083, and a direct measurement of the same policy on
the same bank put it at 0.250. That discrepancy could not be explained by conditioning, so
the sampler was wrong.

The consequences, stated because the defective figures are the more striking ones:

| | Defective corpus | Corrected corpus |
| --- | --- | --- |
| Trick-play positions / distinct hands | 96 / **1** | 256 / **64** |
| Showing positions / distinct hands | 48 / **3** | 128 / **32** |
| Reference RAMI declaration rate | 0.083 | 0.289 |
| PIMC-RAMI-over-reference-NOLO flips | 21 | 33 |
| Reverse flips | **0** | **9** |
| Trick-play contract mix | NOLO 96 / RAMI 0 | RAMI 205 / NOLO 51 |

The defective corpus said the RAMI bias was *perfectly* one-directional. It is not; that
was an artifact of drawing three hands. Everything below uses the corrected corpus.
`tests/search/test_phase5d_diagnostics.py` now asserts the deal-spread property directly,
and `build_corpus` caps the positions any one hand may contribute, spaces the kept card
decisions across tricks, and plays each hand at one rotated score state rather than all
four.

## Showing decomposition: a real, directional RAMI bias

Over 128 showing decisions from 32 distinct hands, comparing PIMC's chosen action with
`partner_aware_v1`'s on the identical observation:

| Classification | Count | Rate |
| --- | --- | --- |
| PIMC RAMI, reference NOLO | 33 | 0.258 |
| PIMC NOLO, reference RAMI | 9 | 0.070 |
| Same contract, different card | 51 | 0.398 |
| Identical action | 35 | 0.273 |

PIMC's RAMI declaration rate is **0.477** against the reference's **0.289** - a difference
of **0.188**, with contract flips running PIMC-toward-RAMI by 33 to 9, a ratio of 3.7 : 1.
The bias holds in every showing position measured from the forehand (R0 14-3, R1 8-1,
R2 7-4, R3 4-1), so it is not one seat's artifact.

A contract flip is the only showing change that can move a match: the shown card is public
but changes no contract, no leader, and no trick, so the 51 "same contract, different
card" disagreements are match-irrelevant by construction. That leaves 42 of 128 decisions
that could matter, three-quarters of them in the same direction.

This is consistent with the Phase 5C showing census, where PIMC's RAMI rate rose with the
world budget rather than falling - which is why small-sample selection optimism was
refuted as the mechanism.

## Card-play decomposition: high disagreement, with structure

Over 256 trick-play positions from 64 distinct hands, PIMC disagrees with the reference on
**167 (65.2 %)**. Per the pre-registered limits, disagreement is not error - the reference
is a transparent heuristic, not an optimum - so these slices say where the two policies
differ, not who is right. They are exploratory and carry no inferential claim.

| Slice | Disagreement rate |
| --- | --- |
| Leading a trick | 0.803 (57/71) |
| Following | 0.595 (110/185) |
| Different suit chosen | 1.000 (69/69) |
| Same suit chosen | 0.524 (98/187) |
| Partner does not hold the trick | 0.695 (130/187) |
| Partner holds the trick | 0.536 (37/69) |
| Early stage | 0.781 (75/96) |
| Middle stage | 0.578 (59/102) |
| Late stage | 0.569 (33/58) |
| RAMI | 0.649 (133/205) |
| NOLO | 0.667 (34/51) |

Two features are worth naming. Disagreement is highest when PIMC is **leading** a trick
(0.803), which is the decision with the widest branching and the least constraint from the
current trick. And when the two policies disagree, PIMC plays the **higher** card in 101
cases against the lower in 62 - a 1.6 : 1 tilt - while the 93 positions where both choose
an equal-ranked card are almost entirely agreements (4 disagreements, all suit choices).

Disagreement is also roughly uniform across contracts (0.649 RAMI, 0.667 NOLO), so this is
not a contract-specific defect. It is a broad difference in card selection, concentrated
where the value signal has the most candidates to separate - which connects directly to
the next section.

## Nested-budget convergence: actions still move, and the margins are vanishing

Budgets 2, 4, 8, 16, 32 over 28 positions, using **nested prefixes** of one world set, so
a changed action means a changed opinion rather than a different sample.

| From → to | Adjacent agreement |
| --- | --- |
| 2 → 4 | 0.607 |
| 4 → 8 | 0.786 |
| 8 → 16 | 0.750 |
| 16 → 32 | 0.714 |

| Budget | Agreement with the 32-world action |
| --- | --- |
| 2 | 0.500 |
| 4 | **0.536** |
| 8 | 0.643 |
| 16 | 0.714 |

Actions are **still moving at 16 → 32 worlds**: adjacent agreement does not climb toward
1, and the mean Spearman correlation between per-action value orderings is flat at
0.68 → 0.75 → 0.71 → 0.70 rather than rising. At the deployed budget of four worlds, PIMC
agrees with its own 32-world opinion on only 53.6 % of decisions.

Read alone, that is Path C evidence. The selection-gap series is why it is not:

| Budget | Mean gap between best and second-best | Tie rate | Ties broken by canonical order |
| --- | --- | --- | --- |
| 2 | 0.0343 | 0.679 | 19/28 |
| 4 | 0.0316 | 0.643 | 18/28 |
| 8 | 0.0244 | 0.500 | 14/28 |
| 16 | 0.0197 | 0.571 | 16/28 |
| 32 | **0.0123** | 0.429 | 12/28 |

More worlds make the margin between the best and second-best action **smaller**, not
larger. On a utility scale spanning [-1, 1], the best action at 32 worlds beats the
runner-up by a mean of 0.012, and 42.9 % of decisions remain exact ties resolved by
canonical card order. At the deployed four worlds, **64.3 % of decisions are settled by
tie-break rather than by value.**

That is the opposite of what a sample-size problem looks like. If the instability were
Monte Carlo error around a real difference, more worlds would resolve the difference and
the gap would grow. Instead the estimate sharpens and reveals that PIMC's root utility
barely distinguishes the actions at all. The instability is a *symptom* of a weak value
signal, not a shortage of samples.

World diversity is not the constraint either: the mean duplicate-world fraction is
**0.000 at every budget**, so the uniform-feasible sampler is doing its job.

Cost is almost exactly linear in the budget - 2.30 s, 4.57 s, 9.15 s, 18.65 s, 37.14 s
per decision at 2, 4, 8, 16, 32 worlds - so buying convergence by budget is
proportionally expensive and, on this evidence, buys sharper indifference rather than
better play.

## Rollout mismatch: the continuation assumption fails almost immediately

Twenty corpus positions, each replayed for a 12-action horizon under three partner
designs. Labelled a **perfect-information diagnostic**: it uses the restricted-truth
channel to replay actual continuations and is never used to select a deployable action.

| Partner design | Diverged | Mean matched fraction | Mean first divergence index | First divergence in root team |
| --- | --- | --- | --- | --- |
| `reference_partner` (control) | 0/20 | **1.000** | – | 0/20 |
| `pimc_partner` | 19/20 | 0.158 | 1.37 | 19/20 |
| `all_pimc` | 19/20 | 0.083 | 0.42 | 16/20 |

The control behaves exactly as it must: when every seat really does play
`partner_aware_v1`, the assumed continuation is the realized one, matching perfectly in
all twenty positions. That is the assumption itself, so a perfect match validates the
instrument rather than saying anything about PIMC.

The other two rows are the finding. As soon as PIMC's partner is another PIMC instance -
the situation in the homogeneous team Phase 5C evaluated - the assumed continuation
diverges in 19 of 20 positions, after fewer than half an action on average in the
`all_pimc` design, and the first divergence falls inside the root's own team in 35 of the
38 diverging cases. PIMC's rollout is modelling a partner that is not there.

Per the pre-registered limits this is divergence, not causation: the counterfactual - the
same decision under a correct continuation model - is not available here.

## Corpus composition, and where it fell short of target

| | Decomposition corpus | Convergence corpus |
| --- | --- | --- |
| `corpus_id` | `corpus:sha256:73dd4bc6…` | `corpus:sha256:…` |
| Showing positions / distinct hands | 128 / 32 | 40 / 10 |
| Trick-play positions / distinct hands | 256 / 64 | 56 / 14 |
| Stage (early / middle / late) | 96 / 102 / 58 | – |
| Score states (down / table / up) | 150 / 101 / 133 | – |

The phase target was 256-512 showing and 512-1024 trick-play positions. **That was not
reached, and the shortfall is a compute limit rather than a design choice.** A full-size
build (256 showing / 512 trick-play) projected 31 hours on this machine and was abandoned;
labelling each position requires a PIMC decision at the deployed budget on top of the
reference deal walk that generates it. The achieved corpus is half the lower bound on
showing positions and half on trick-play.

Both corpora are built from **reference** play, so no comparison here is conditioned on a
trajectory PIMC itself reached.

Every position carries the formal `PlayerObservation` plus labels derived from the
observation alone. The real `DealState` lives in a separate restricted mapping reachable
only by explicit lookup, used only by the labelled perfect-information diagnostic above.
The deployable PIMC path takes no such parameter.

The consequence for inference: **read the distinct-hand count, not the position count, as
the effective sample size.** A hand's four showing decisions share the same cards, and a
hand's kept card decisions share the same deal, so 128 showing positions carry closer to
32 hands' worth of independent information. Strata below roughly 20 positions are
descriptive only.
