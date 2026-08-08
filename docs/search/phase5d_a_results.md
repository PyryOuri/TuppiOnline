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
was an artifact of drawing three hands. The table records the first corrected corpus used
for the original decomposition; the full 768-position corrected rerun is reported below.
`tests/search/test_phase5d_diagnostics.py` now asserts the deal-spread property directly,
and `build_corpus` caps the positions any one hand may contribute, spaces the kept card
decisions across tricks, and plays each hand at one rotated score state rather than all
four.

## Showing decomposition: a real, directional RAMI bias

The full corrected corpus contains 256 showing decisions, comparing PIMC's chosen action
with `partner_aware_v1`'s on the identical observation:

| Classification | Count | Rate |
| --- | --- | --- |
| PIMC RAMI, reference NOLO | 70 | 0.273 |
| PIMC NOLO, reference RAMI | 16 | 0.063 |
| Same contract, different card | 103 | 0.402 |
| Identical action | 67 | 0.262 |

PIMC's RAMI declaration rate is **0.496** against the reference's **0.285** - a difference
of **0.211**, with contract flips running PIMC-toward-RAMI by 70 to 16, a ratio of 4.4 : 1.
The full run confirms the direction of the earlier corrected-corpus result.

A contract flip is the only showing change that can move a match: the shown card is public
but changes no contract, no leader, and no trick, so the 103 "same contract, different
card" disagreements are match-irrelevant by construction. That leaves 86 of 256 decisions
that could matter, most of them in the same direction.

This is consistent with the Phase 5C showing census, where PIMC's RAMI rate rose with the
world budget rather than falling - which is why small-sample selection optimism was
refuted as the mechanism.

## Card-play decomposition: high disagreement, with structure

Over 512 trick-play positions, PIMC disagrees with the reference on **333 (65.0 %)**. Per
the pre-registered limits, disagreement is not error - the reference
is a transparent heuristic, not an optimum - so these slices say where the two policies
differ, not who is right. They are exploratory and carry no inferential claim.

| Slice | Disagreement rate |
| --- | --- |
| Leading a trick | 0.781 (118/151) |
| Following | 0.596 (215/361) |
| Different suit chosen | 1.000 (133/133) |
| Same suit chosen | 0.528 (200/379) |
| Partner does not hold the trick | 0.682 (264/387) |
| Partner holds the trick | 0.552 (69/125) |
| Early stage | 0.788 (149/189) |
| Middle stage | 0.598 (122/204) |
| Late stage | 0.521 (62/119) |
| RAMI | 0.636 (253/398) |
| NOLO | 0.702 (80/114) |

Two features are worth naming. Disagreement is highest when PIMC is **leading** a trick
(0.781), which is the decision with the widest branching and the least constraint from the
current trick. And when the two policies disagree, PIMC plays the **higher** card in 215
cases against the lower in 110 - a 2.0 : 1 tilt - while the 187 positions where both choose
an equal-ranked card are almost entirely agreements (8 disagreements, all suit choices).

Disagreement is also roughly uniform across contracts (0.649 RAMI, 0.667 NOLO), so this is
not a contract-specific defect. It is a broad difference in card selection, concentrated
where the value signal has the most candidates to separate - which connects directly to
the next section.

## Nested-budget convergence on the corrected corpus

The corrected run covers 112 positions (48 showing and 64 trick-play), using budgets 2, 4,
8, 16, and 32 with **nested prefixes** of one world set. A changed action therefore means a
changed opinion rather than a different sample. This is a convergence diagnostic, not a
strength evaluation.

| From → to | Adjacent agreement |
| --- | --- |
| 2 → 4 | 0.839 (94/112) |
| 4 → 8 | 0.830 (93/112) |
| 8 → 16 | 0.839 (94/112) |
| 16 → 32 | 0.875 (98/112) |

| Budget | Agreement with the 32-world action |
| --- | --- |
| 2 | 0.705 (79/112) |
| 4 | 0.759 (85/112) |
| 8 | 0.830 (93/112) |
| 16 | 0.875 (98/112) |
| 32 | 1.000 (112/112) |

Actions are substantially more stable on the corrected corpus: 16 and 32 worlds agree on
98 of 112 positions, and the 32-world action agrees with the 4-world action on 85 of 112.
Mean Spearman correlations across adjacent budgets are 0.833, 0.819, 0.791, and 0.854.
This does not establish correctness, but it does not support selecting Path C merely because
the deployed four-world action is noisy.

The selection-gap series remains descriptive:

| Budget | Mean gap between best and second-best | Tie rate | Ties broken by canonical order |
| --- | --- | --- | --- |
| 2 | 0.0563 | 0.875 | 98/112 |
| 4 | 0.0391 | 0.857 | 96/112 |
| 8 | 0.0379 | 0.750 | 84/112 |
| 16 | 0.0310 | 0.714 | 80/112 |
| 32 | 0.0251 | 0.679 | 76/112 |

The selection gap still shrinks with budget, and tie-breaking remains common: 67.9 % of
32-world decisions are ties resolved by canonical order, compared with 85.7 % at four
worlds. That is a weak-value-signal observation, not evidence that the reference is optimal
or that PIMC is correct at 32 worlds.

The corrected run is large enough to replace the defective-corpus result, but the gap and
tie-rate series remain descriptive. Convergence is not strength, and this instrument does
not justify tuning the world count before changing the algorithm family.

Two observations from the same run are robust to the corpus defect, because they are
properties of the sampler and the cost model rather than of position selection:

- Mean duplicate-world fraction rises from 0.004 at 2 worlds to 0.059 at 32 worlds, so
  duplicate sampling is measurable but remains a secondary diagnostic rather than a
  strength result.
- Cost is almost exactly linear in the budget - 1.00 s, 2.00 s, 3.99 s, 8.01 s, 15.95 s
  per decision at 2, 4, 8, 16, 32 worlds - so buying convergence by budget is
  proportionally expensive.

## Rollout mismatch: the continuation assumption fails almost immediately

Thirty-two corpus positions, each replayed for a 12-action horizon under three partner
designs. Labelled a **perfect-information diagnostic**: it uses the restricted-truth
channel to replay actual continuations and is never used to select a deployable action.

| Partner design | Diverged | Mean matched fraction | Mean first divergence index | First divergence in root team |
| --- | --- | --- | --- | --- |
| `reference_partner` (control) | 0/32 | **1.000** | – | 0/32 |
| `pimc_partner` | 29/32 | 0.172 | 1.03 | 29/32 |
| `all_pimc` | 29/32 | 0.120 | 0.34 | 24/32 |

The control behaves exactly as it must: when every seat really does play
`partner_aware_v1`, the assumed continuation is the realized one, matching perfectly in
all thirty-two positions. That is the assumption itself, so a perfect match validates the
instrument rather than saying anything about PIMC.

The other two rows are the finding. As soon as PIMC's partner is another PIMC instance -
the situation in the homogeneous team Phase 5C evaluated - the assumed continuation
diverges in 29 of 32 positions, after fewer than half an action on average in the
`all_pimc` design, and the first divergence falls inside the root's own team in 53 of the
58 diverging cases. PIMC's rollout is modelling a partner that is not there.

Per the pre-registered limits this is divergence, not causation: the counterfactual - the
same decision under a correct continuation model - is not available here.

## Corpus composition, and where it fell short of target

| | Decomposition corpus | Convergence corpus |
| --- | --- | --- |
| `corpus_id` | `corpus:sha256:3d69a141…` | `corpus:sha256:4486e587…` |
| Total positions | 768 | 112 |
| Showing / trick-play positions | 256 / 512 | 48 / 64 |
| Stage (early / middle / late) | 189 / 204 / 119 | not reported |
| Score states (down / table / up) | 150 / 101 / 133 | not reported |

The phase's original 256-512 showing and 512-1024 trick-play target was reached at its
lower bound in the corrected full decomposition run. The convergence run deliberately uses
a smaller, balanced subset because its nested-budget evaluations are the expensive stage.

Both corpora are built from **reference** play, so no comparison here is conditioned on a
trajectory PIMC itself reached.

Every position carries the formal `PlayerObservation` plus labels derived from the
observation alone. The real `DealState` lives in a separate restricted mapping reachable
only by explicit lookup, used only by the labelled perfect-information diagnostic above.
The deployable PIMC path takes no such parameter.

The consequence for inference: **read the distinct-hand count, not the position count, as
the effective sample size.** A hand's four showing decisions share the same cards, and a
hand's kept card decisions share the same deal. The compact full-run report records labels,
not a hand-count estimator, so strata below roughly 20 positions remain descriptive only.

## Cost, and why this phase stopped where it did

The corrected large runs were executed sequentially by stage on the migrated M3 Max; the
following per-decision timings come from the corrected convergence artifact.

| Quantity | Measured |
| --- | --- |
| Play-only deal, two gated seats | 24.5 s |
| PIMC decision at 2 / 4 / 8 / 16 / 32 worlds | 1.00 / 2.00 / 3.99 / 8.01 / 15.95 s |
| Complete-match leg, play-only | mean 30.5 deals, median 28, max 71 |
| Complete-match leg, show-only | mean 28.2 deals, median 22.5, max 66 |
| Actions per complete match | 1670 (play-only), 1527 (show-only) |
| Resets per complete match | 9.8 (play-only), 9.2 (show-only) |
| One 12-pair homogeneous comparison | ~2 h wall on 5 workers |
| Corrected 768-position corpus + decomposition | completed on the M3 Max |

Three cost facts dominated the phase and are worth recording for whoever runs it next.

**Near-parity candidates make complete matches expensive.** `project_target_v1` resets the
score to 0-0 whenever the down team wins a deal, so the closer a candidate is to the
reference, the longer its legs run - a mean of 9.8 resets per match here. The weakest
candidate is the cheapest to evaluate, which is precisely backwards from what a development
loop wants.

**Pair-level progress reporting is too coarse.** A comparison reports only on completed
pairs, and a pair is two full legs. The first attempt at the play-only comparison ran ten
hours across six workers without emitting a single line, because it used the Phase 5C cap of
704 deals per leg. Per-deal or per-leg progress would have surfaced that in minutes.

**Watch for pool workers going idle.** One heterogeneous run spent 100 minutes with a single
active worker while three sat at 0 % CPU, having exited; `d-compare` on the same machine kept
five workers at 97 %. The `chunksize=1` dispatch is correct, so this is worth checking with
`top` shortly after any long launch rather than assumed.

## What remains outside the requested completion set

Named rather than omitted. The required heterogeneous-full-PIMC, corrected convergence, and
full decomposition runs are now complete. These additional instruments were not run:

| Planned | Status | What it would decide |
| --- | --- | --- |
| Heterogeneous play-only, seat-balanced | **not run** | Whether the mismatch effect survives when only cards are searched |
| Full PIMC on the `phase5d_a_match_v1` bank | **not run** | The like-for-like comparator that would make the play-only and show-only numbers a true series |
| Deal-level screens | not run | Cheap secondary confirmation only |

The two unrun match instruments would refine the decomposition but are not needed for the
Path B versus Path D decision made by the completed seat-balanced full-PIMC comparison.

## The decision: Path D selected

**Selected path: D - structural PIMC failure, subject to the recorded sample and censoring
limits.**

What the evidence supports:

- **Path A is not primary.** If contract selection were the dominant cost, handing showing
  back to the frozen reference should recover most of the strength. It does not:
  `uniform_feasible_pimc_play_only_v1` reaches `p_win = 0.250` with a 95 % interval of
  [0.059, 0.441] that excludes parity. Both phases lose separately - show-only 0.333,
  play-only 0.250 - so neither is the single cause. Freezing heuristic showing and searching
  only cards, which is what Path A would license, is not supported.
- **Path C is not supported on the corrected convergence run.** Adjacent agreement rises to
  0.875 at 16 → 32 worlds, and the 16- and 32-world actions agree on 98 of 112 positions.
  The convergence instrument is not a strength evaluation, but it does not license spending
  the next phase merely increasing the world count.
- **Path B is not supported behaviorally.** With one PIMC seat and a reference partner, the
  two seat arrangements reached p_win 0.333 and 0.375. One had 9 complete pairs and 3
  censored pairs; the other had 12 complete pairs and no censoring. Both remained below
  parity, so a reference partner did not recover competitiveness. This result is small and
  the cap deviation remains explicit; it is evidence against partnership mismatch as the
  primary explanation, not a promotion claim.
- **Path D is selected.** Play-only remains negative with the reference choosing every
  contract, the heterogeneous full-PIMC comparison remains negative with a reference partner,
  and corrected-budget actions stabilize without recovering strength. Freeze PIMC as a
  negative baseline and move to observation-safe information-set search.

**Is ISMCTS justified next? Yes, as a new development phase.** It must be observation-safe,
deterministic, and compared first against the frozen negative baseline and the development
reference. It must not alter the Phase 5C configuration identity, introduce recursive PIMC,
or open the promotion-sealed bank.

The next phase should begin with a concise design and acceptance specification for the
information-set searcher before implementation.

## Development-bank status

Every fixture used here is a fresh unsealed **development** bank with a root seed no earlier
phase used, and each of the four banks has a distinct `bank_id`:
`phase5d_a_match_v1`, `phase5d_a_heterogeneous_v1`, `phase5d_a_deal_v1`,
`phase5d_a_corpus_v1`. No result in this document is promotion evidence, no result was tuned
against the 32 Phase 5C streams, and the promotion-sealed bank was not opened.
