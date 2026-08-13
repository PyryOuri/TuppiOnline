# Deal-level and match-level endpoints are different questions

Phase 4 measured agents with **signed deal points per independently generated
base deal**. Phase 5A measures them with **match win probability per complete
complementary pair**. Both are legitimate; they answer different questions, and
only one of them can evaluate a policy whose objective is the match.

## Why signed deal points cannot score match-aware strategy

`project_target_v1` uses one continuous rising score to 52, and only one
partnership may hold points at a time. Three consequences follow directly from
`transition_rising_score`:

1. **A win by the non-rising partnership scores it nothing.** The rising side
   is reset to 0-0 and the winner starts from zero. A 56-point stolen RAMI and a
   4-point NOLO win by a partnership that is behind have *identical* match
   value.
2. **Points beyond the target are discarded.** Winning at 48-0 by 4 and by 28
   are the same match.
3. **A loss while rising destroys the whole accumulated score,** whatever its
   margin.

`match_aware_v1` exists to exploit exactly these facts. Its protect rule
withholds a marginal RAMI declaration at 48-0 precisely because a 4-point NOLO
win already reaches 52 while a failed RAMI resets the entire rise. That is a
deliberate trade of *deal margin* for *match safety*.

A metric denominated in deal points cannot see the thing being bought. Worse, it
charges for it: every point of margin surrendered is counted as a loss, and none
of the reduced variance is counted as a gain. Phase 4's own result showed this -
the rising-score rules measured **-1.03 deal points per base deal** on a 48-0
bank - and the honest reading was never "the rules are bad" but "this endpoint
cannot answer the question".

## What each endpoint is good for

| | Deal-level (Phase 3/4) | Match-level (Phase 5A) |
| --- | --- | --- |
| Unit | independently generated base deal | complete complementary pair |
| Value | signed deal points | `D_match ∈ {-1, 0, +1}` |
| Endpoint | mean paired utility | `(1 + mean D_match) / 2` |
| Cost | one deal per game | one whole match per leg, two legs per unit |
| Sees card play quality | yes, finely | yes, but only through match outcomes |
| Sees match safety | **no** | yes |
| Sees showing risk trade-offs | partially | yes |
| Variance per unit | low | high; a match is a single binary outcome |
| Good for | trick-play and showing changes | anything whose objective is the match |

Deal-mode summary schema `tuppi.eval.summary.v2` now adds paired deal-win
advantage and paired post-deal match-transition utility as development screens.
They make “wins more deals” and “improves the immediate rising-score state”
visible without pretending either is a completed-match outcome. The final
strength gate remains the complete-match endpoint. See
[model-performance methodology](../evaluation/model_performance_methodology.md).

The deal-level evaluator is not deprecated. It remains the cheaper,
higher-resolution instrument for changes whose effect is local to a deal, and it
stays in `src/tuppi_eval/`. It simply must not be used to adjudicate
match-strategy questions.

## The price of the match endpoint

A match outcome is one bit. Each pair yields `D_match ∈ {-1, 0, +1}`, so the
per-unit variance is large and a pair costs two complete matches - on the order
of eighty deals against the Phase 4 agents, against one deal per deal-level
observation. Detecting a small edge therefore needs hundreds of pairs, which is
why Phase 5A ships a calibration procedure and a sample-size recalculation rule
rather than a fixed number.

The duplicate design is what makes it affordable at all. Because both legs read
the same deals, the deal luck that dominates a single match largely cancels
inside the pair, and the `complementary_leg_correlation` reported with every
comparison says how much of it cancelled:

- correlation near **-1**: the same seats won both legs, so the deals decided
  the match and the pair correctly scored 0;
- correlation near **+1**: the candidate won or lost both orientations, so the
  policy decided the match.

## Reading a Phase 5A comparison

Report and read, in this order:

1. `complete_pair_count` - the actual sample size, after censoring;
2. `candidate_match_win_probability` with its interval;
3. `pair_outcomes` - the win/tie/loss counts behind that mean;
4. `censored_pair_count` and `failed_pair_count` - infrastructure honesty;
5. `complementary_leg_correlation` - how much deal luck the design removed;
6. secondary metrics, which may *explain* a result but can never override it.
