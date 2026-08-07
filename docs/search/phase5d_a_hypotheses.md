# Phase 5D-A: hypotheses, instruments, and what they cannot show

This document is written **before** the Phase 5D-A measurements, and deliberately so.
It states which hypotheses were nominated, which instrument addresses each, and what
each instrument cannot establish. Results live in
`docs/search/phase5d_a_results.md`; the split exists so that the reasoning cannot be
retrofitted to whatever the numbers turned out to be.

## The result being explained

Phase 5C measured `uniform_feasible_pimc_small_v1` against
`development_reference_v1` over 32 complementary complete-match pairs from 0-0:

| | |
| --- | --- |
| `p_win` | 0.156 |
| 95 % CI | [0.075, 0.238] |
| Pair W / T / L | 0 / 10 / 22 |
| Sign-flip p | 0.0001 |
| Censored / failed legs | 0 / 0 |

**These numbers are quoted, not recomputed.** They are the committed Phase 5C result
and Phase 5D-A does not revisit them, re-run them, or adjust them in light of
anything found later. The configuration is designated
`uniform_feasible_pimc_small_v1_negative_baseline`: rejected as a development
improvement, retained as a regression fixture and as the comparator for later search
families. The designation is metadata; the agent identity, its configuration id, and
the committed Phase 5C registry digest are all unchanged.

Phase 5C also recorded, and Phase 5D-A takes as given:

- action stability 0.667 from 2→4 worlds and 0.833 from 4→8 worlds;
- a RAMI declaration rate rising with budget (0.458 at 2 worlds to 0.583 at 16)
  against the reference's 0.417 - which **refuted** small-sample contract-variance
  optimism, since that mechanism predicts the rate falling;
- `match_transition_v1` and `deal_result_v1` are exactly ordinally equivalent at 0-0,
  so the Phase 5C utility ablation could not have separated them;
- a small heterogeneous hint that PIMC does less badly with a reference partner than
  with a PIMC partner;
- PIMC legs averaging 21.8 deals against the reference population's ~30.

## The six candidate causes

1. **Showing and contract selection.** PIMC picks the wrong contracts.
2. **Card-play PIMC.** PIMC plays cards worse than the reference heuristic.
3. **Partnership policy mismatch.** PIMC values an action assuming *reference* play
   by its own partner, while in a homogeneous team its partner is another PIMC.
4. **Insufficient world count.** Four worlds is too noisy to choose well.
5. **Rollout-policy mismatch.** The rollout policy is a poor model of the actual
   continuation, independently of who the partner is.
6. **Strategy fusion that survives all of the above.** The root averaging step is
   wrong in a way no control removes.

These are not mutually exclusive, and the phase is designed to *discriminate*, not to
find a single winner.

## Which instrument addresses which

| Cause | Instrument | Why it separates |
| --- | --- | --- |
| 1 | `uniform_feasible_pimc_show_only_v1` versus reference | PIMC chooses the contract; the frozen reference plays every card. Any loss is attributable to contract choice alone. |
| 2 | `uniform_feasible_pimc_play_only_v1` versus reference | The frozen reference chooses the contract; PIMC plays every card. Any loss is attributable to card play alone. |
| 3 | Seat-balanced heterogeneous partnerships | One PIMC seat with a reference partner. If mismatch is the cause, a single PIMC seat should do better than two. |
| 4 | Nested-budget convergence, 2 to 32 worlds | Prefixes nest exactly, so "the action changed" means "the opinion changed" rather than "the sample changed". |
| 5 | Rollout mismatch records | Replays the assumed continuation and compares it action-by-action with realized ones under three partner designs. |
| 6 | What is left over | Only credible once 1-5 have been controlled, which is the whole point of running them first. |

The two gated variants **partition** full PIMC's decisions: every decision is searched
by exactly one of them, which
`tests/search/test_phase5d_hybrid.py::test_the_two_variants_partition_full_pimc_decisions`
asserts directly. So the two comparisons together cover the same decision set the
Phase 5C agent faced.

## Fresh fixtures, and why

Every Phase 5D-A experiment uses a **new** unsealed development bank with a root seed
no earlier phase used:

| Bank | Root seed | Purpose |
| --- | --- | --- |
| `phase5d_a_match_v1` | `tuppi-phase5d-a-match-v1` | homogeneous complete-match comparisons |
| `phase5d_a_heterogeneous_v1` | `tuppi-phase5d-a-heterogeneous-v1` | seat-balanced mixed partnerships |
| `phase5d_a_deal_v1` | `tuppi-phase5d-a-deal-v1` | deal-level screens |
| `phase5d_a_corpus_v1` | `tuppi-phase5d-a-corpus-v1` | the frozen decision corpus |

Re-running variants on the 32 Phase 5C streams would be tuning against the fixture
that produced the result being explained. The promotion-sealed bank is not touched.

## Seat balancing in the heterogeneous design

A mixed partnership has an asymmetry the homogeneous one does not: *which* of the two
candidate seats holds the search agent. The complete-match protocol already rotates
the partnership across physical seats through its complementary legs, so Phase 5D-A
adds the second axis - the search agent at the numerically lower candidate seat, and
at the higher one - and runs both.

Each arrangement is reported as its **own** comparison rather than pooled, because the
two share their streams and are therefore not independent of each other. Pooling would
understate that dependence and overstate the precision.

## The corpus, and its privacy boundary

Decision-level analysis needs many positions asked the same question repeatedly, so
the corpus is built once from *reference* play - not PIMC play, which would condition
every later comparison on the trajectory PIMC happens to reach - and frozen.

The privacy design is two structures, not one. A `CorpusPosition` carries the formal
observation plus labels derived from the observation alone. The real `DealState` lives
in a **separate** restricted mapping keyed by position id, reachable only by explicit
lookup and used only by labelled perfect-information diagnostics. Nothing in the
deployable path takes one, and the tests assert that a position exposes no engine
state and that its serialized form names no card the observing seat cannot see.

## What Phase 5D-A deliberately does not do

No ISMCTS, RIS-MCTS, MO-ISMCTS, or POMCP. No persistent search tree or tree reuse. No
neural or learned partner policy. No heuristic likelihood weighting or particle
filter. No reinforcement learning. No new expert heuristics. No change to
`partner_aware_v1`. The sealed bank is not opened.

**And specifically: no recursive PIMC.** Policy mismatch has an obvious-looking fix -
let PIMC's rollout call PIMC for its own partner's turns - and that fix is forbidden
here. It multiplies cost by the branching factor at every ply, and its semantics are
unclear: a nested search would itself assume something about *its* partner, so the
regress does not terminate at any principled depth.
`tuppi_search.validation` scans for it. A fast distilled or learned partner model may
be considered later, but only after this diagnosis says whether partner modelling is
where the loss actually lives.

## Limits of diagnostic inference

Stated plainly, because these bound every conclusion the results document can draw.

**Decomposition is not additive.** Play-only and show-only partition the *decisions*,
not the *loss*. Contract choice and card play interact: a contract the reference would
not have taken changes every subsequent card decision. So a play-only result of X and a
show-only result of Y do not combine into the full-PIMC result, and no arithmetic here
pretends otherwise.

**Disagreement is not error.** The reference is a transparent Phase 4 heuristic, not an
optimum. PIMC disagreeing with it says the two differ, not that either is wrong.

**Divergence is not causation.** A rollout-mismatch record shows that the assumed
continuation did not happen. It cannot show that the difference is what cost the
match, because the counterfactual - the same decision under a correct continuation
model - is not available.

**Convergence is not strength.** An agent whose action stops changing has stopped
changing its mind. Phase 5C already demonstrated these come apart: the RAMI rate moved
*further* from the reference as the budget grew.

**Small samples resolve large effects only.** Phase 5D-A sizes each comparison for the
effect magnitude Phase 5C observed, not for a small one. A comparison that lands near
0.5 will be reported as unresolved rather than as a null.

**Exploratory strata are not tested hypotheses.** The card-play decomposition slices
positions many ways. No multiple-comparison correction is applied and none of those
slices carries an inferential claim; they exist to point at where a mechanism would
have to act.

## The decision this phase must reach

One of four paths, on the evidence:

- **A - showing is primary:** play-only materially better than full PIMC, show-only
  materially worse than reference. Freeze heuristic showing; search cards only.
- **B - partnership mismatch is primary:** heterogeneous competitive or positive while
  homogeneous stays strongly negative, with substantial assumed-versus-actual
  divergence. Prioritize multi-observer search or explicit partner-action modelling.
- **C - world-count instability is primary:** actions still moving through 16-32
  worlds and larger budgets recovering strength. Optimize simulation speed before
  changing algorithm family. **Not** to be selected merely because four worlds is
  unconverged - Phase 5C already established that.
- **D - structural PIMC failure:** play-only still strongly negative, heterogeneous
  still negative, budgets stabilizing without recovering strength. Freeze PIMC as a
  negative baseline and proceed to observation-safe information-set search.
