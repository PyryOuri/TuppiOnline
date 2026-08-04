# The utility adapters

Every PIMC value in Phase 5C comes from exactly one versioned adapter, and every
adapter scores the same value type: a `DealOutcomeSummary` carrying
`(contract, declarer, team0 tricks, starting score, root team, source)`.

That is structural, not stylistic. A completed rollout and an exact-tail solve both
reduce to this type, so the two paths share one scoring function and cannot drift
apart.

## Orientation

Nothing assumes Team 0 is the agent's team. Every summary carries its `root_team`,
derived from the acting seat, and every adapter converts the engine's
team-0-relative trick count into a value for that team.
`tests/search/test_utilities.py` checks that one team's value is the exact negation
of the other's at every trick split, that the two seats of one partnership agree
exactly, and that all four root seats behave correctly.

## The three adapters

### `tuppi.search.utility.deal_result.v1`

Signed official deal points for the root team, divided by 56 (a 13-trick stolen
RAMI, the largest award the ruleset can produce). Range `[-1, 1]`.

Honest for a *deal*. Wrong for a *match*: it pays the down team for a margin the
rising score throws away, which Phase 5A established is a currency the ruleset
partly does not have. Registerable, and used by one ablation identity.

### `tuppi.search.utility.match_transition.v1` — the registered choice

The authoritative post-deal rising-score transition:

| Post-deal state | Value |
| --- | --- |
| root team has won the match | `+1` |
| nonterminal | `(own rise - opponent rise) / 52` |
| root team has lost the match | `-1` |

Range `[-1, 1]`. **Overshoot past 52 is worth nothing** - reaching 52 and reaching
76 score identically - because the rising score awards nothing for it. Phase 5B
learned that lesson the hard way: an earlier version of its exact verdicts credited
the overshoot and made a rule that stops competing for a worthless margin look
harmful.

Chosen for the primary agent because Phase 5A established the match as the endpoint
and Phase 5B showed deal margin is partly fictitious.

**It is not exact nonterminal match equity.** A real equity would need a model of the
deals still to come. It is a documented, bounded, monotone *ordering* of post-deal
states, and it is order-compatible with Phase 5B's
`tuppi_exact.match_utility_from_score`: `tests/search/test_utilities.py` verifies
that exhaustively over every contract, declarer, reachable score, seat, and trick
split - more than ten thousand pairwise comparisons. Keeping the two orderings
identical is what lets a Phase 5C average and a Phase 5B exact verdict be read side
by side.

### `tuppi.search.utility.trick_split.v1`

The root team's trick share, signed by contract (inverted for NOLO, since both
partnerships want to avoid tricks there). Range `[-1, 1]`.

**Not registerable.** It ignores the 6/7 boundary that decides who actually wins the
deal, so an agent maximizing it would be maximizing something the ruleset does not
reward. `PimcConfiguration.require_registerable_utility` refuses it for a registered
agent, and it is kept only for ablation and for comparison against Phase 4's
trick-oriented scoring.

## Rule coverage in the tests

Every case the ruleset can produce is covered explicitly: successful RAMI, stolen
RAMI seen from both sides, the full NOLO table, an up-team win that reaches the
target, a down-team win that resets to 0-0 at two different margins (equal under
`match_transition_v1`, unequal under `deal_result_v1` - which is exactly the point),
and immediate match completion.

## The utility is part of the identity

`utility_id` is inside the configuration's `identity_data`, so changing it produces a
different `configuration_id` and a different `agent_id`. The primary agent's utility
was frozen before its primary evaluation ran, as Phase 5A requires.

## No opaque mixtures

There are no weighted combinations of adapters. A blend would need its weights
documented, its range re-derived, its monotonicity re-checked, and an ablation to
justify it; none of that was done, so none is offered.
