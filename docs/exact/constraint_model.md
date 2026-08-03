# The hard public constraint model

`tuppi_exact.constraints.HardConstraintModel` is the explicit combinatorial form
of everything public information settles about the hidden hands. It answers one
kind of question - *which seats may still hold this card* - and it answers with a
set, never with a weight.

## What it is

A degree-constrained bipartite structure:

- **Unknown cards** on one side: neither played nor publicly owned.
- **Seats with exact residual capacities** on the other: how many unknown cards
  each seat must still receive.
- **An edge** wherever public information permits.

Plus the derived facts a caller needs: `known_held`, `void_suits`,
`played_cards`, `cards_remaining`, and the per-seat `show_exclusions`.

Every field is a set or an integer. The test suite asserts that no attribute name
contains `probability`, `likelihood`, `prior`, `belief`, or `weight`, for the same
reason Phase 4 asserts it of `PublicInference`: keeping hard constraint from soft
belief is what lets a later phase add probability without making Phase 4's claims
probabilistic in retrospect.

## The sixth fact: what a show action proves

Phase 4's five facts are own hand, played cards, shown cards, failure to follow
suit, and remaining capacity. Phase 5B adds the one Phase 4 never needed.

`project_target_v1` requires a mandatory, ordered showing hierarchy:

| Priority | Hand condition for the declared contract | Valid shown cards | `verbal_required` |
| --- | --- | --- | --- |
| 1 | At least one eligible card of the normal colour exists | Only eligible cards of that colour | false |
| 2 | No eligible matching-colour card, but at least one eligible card | Any eligible card | true |
| 3 | No eligible card of either colour | Any card | true |

`verbal_required` is *derived from the hand*, so its public value is a hard
statement about what the hand does not contain:

- **false** - priority 1 applied. The shown card is itself an eligible card of the
  normal colour. Nothing new is excluded.
- **true and the shown rank is 3-9** - priority 2 applied. The hand contains **no
  eligible card of the contract's normal colour**: 14 specific cards are excluded
  from that seat.
- **true and the shown rank is not 3-9** - priority 3 applied. The hand contains
  **no eligible card of either colour**: all 28 cards of ranks 3-9 are excluded.

Priority 3 can never show an eligible card, because under priority 3 the hand
holds none. So the shown card's rank distinguishes priority 2 from priority 3
*with certainty*, which is what makes the deduction exact rather than a plausible
reading.

### It is a constraint on the initial hand, and that is fine

The deduction is about the shower's complete 13-card hand. Every card that seat
has since played is already public, so the only live consequence is an exclusion
over its remaining unknown cards. If an excluded card had already been played by
that seat, the public record would be self-contradictory;
`derive_show_exclusions` raises rather than quietly dropping the case, because in
a legal `project_target_v1` state it cannot happen.

The observing seat never receives an exclusion. Its own hand is known outright, so
an exclusion would be redundant - and applying one could contradict the very hand
the engine handed over. `own_show_exclusion_is_consistent` is available as a
self-check on the observation, not as an inference.

### How much it buys

Over 384 deals of census play the exclusion fires on roughly 4 % of decisions,
almost always at priority 2 (14 cards excluded from one seat). Priority 3 is
vanishingly rare, as it must be: a 13-card hand with no rank between 3 and 9 has
to be drawn entirely from the 24 ineligible cards.

Rare is not the same as unimportant. Where it fires it removes 14 candidate
holders at once, and - decisively - **without it a sampled assignment can
contradict the public record**, which makes hypothetical continuation
construction fail outright. See `docs/exact/continuation.md`.

## Propagation

Four exact deductions run to a fixed point:

1. **Singleton.** A card with one allowed seat is certainly at that seat.
2. **Zero capacity.** A seat with no residual capacity is removed from every
   candidate set.
3. **Tight seat.** If the number of cards a seat could hold equals its capacity,
   it holds all of them.
4. **Hall / Gale-Hoffman on seat subsets.** For every subset `S` of open seats,
   the cards *captive* to `S` - those no seat outside `S` may hold - must number
   at most the total capacity of `S`. On equality, every other card is excluded
   from `S`; on excess, the model is infeasible and raises.

With at most three unknown seats there are at most seven subsets, so step 4 is a
**complete** feasibility test rather than a screen: `is_structurally_feasible` is
exact. The authoritative oracle is still
`tuppi_exact.counting.feasible_assignment_count`, which returns zero for an
infeasible model, and the two must agree.

The loop is bounded and raises if it fails to converge. It cannot fail to
converge - each productive pass either proves one card's owner or removes an edge,
and both are monotone - but a bound that raises is preferable to a loop that
silently runs long.

## Soundness

The property that matters is one-directional: **the model may never exclude the
truth.**

- `tests/exact/test_constraints.py::test_model_is_sound_against_the_true_hands`
  replays six deals and checks, at every decision, that the true owner of every
  unknown card is still allowed, that every publicly-held card really is held, and
  that no show exclusion contains a card the seat actually holds.
- `test_model_is_at_least_as_strong_as_phase4_inference` checks the other
  direction of the relationship: adding show exclusions may only *narrow* an
  allowed-seat set, never widen one, and may only *grow* `known_held`.
- The engine provides an independent check. An unsound model produces samples the
  engine rejects during continuation construction, so soundness is verified twice
  by different mechanisms.

## What it deliberately does not do

It does not rank the seats in an allowed set. It does not record how many facts
support a candidate. It does not learn. An unknown card's allowed-seat set is the
full set the facts permit, with no ordering among its members - and the *count* of
assignments over that set, computed in `tuppi_exact.counting`, is a property of the
constraint system rather than a claim about what an opponent would do.
