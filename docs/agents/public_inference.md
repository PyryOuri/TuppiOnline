# Hard public inference, and why it is not a belief model

`tuppi_agents.public_inference.PublicInference` answers exactly one kind of
question: *is this excluded by public information?* It never answers *how
likely is this?*

There are no probabilities, no priors, no weights, no sampling, no particle
filters, and no hidden-hand reconstruction in this module. Anything the public
record does not settle stays genuinely unknown, and an unknown card's possible
owner set is the full set of seats the facts allow, with no ordering among them.

## The five facts

Every exclusion is a deduction from one of these:

1. **Own hand.** The observing player holds these cards; nobody else can.
2. **Played cards.** A played card is in nobody's hand. Its possible-owner set is
   empty, not "unlikely".
3. **Shown cards.** A card shown during showing is publicly known to be held by
   that seat until it is played. `project_target_v1` does not remove a shown card
   from its hand.
4. **Failure to follow.** A seat that did not follow the led suit is void in that
   suit. A seat with an empty hand is trivially void in every suit.
5. **Remaining capacity.** Each seat holds `13 - (cards it has played)` cards.

## The two deductions

Both are exact, and both run to a bounded fixed point
(`MAXIMUM_REFINEMENT_PASSES = 4`, so the derivation cost stays deterministic):

- **Singleton.** If a card's possible-owner set has one element, that seat holds
  it.
- **Pigeonhole.** If the number of unaccounted cards a seat could still hold
  equals its remaining unknown capacity, it holds all of them. Symmetrically, a
  seat with zero unknown capacity is removed from every candidate set.

The object validates its own arithmetic on construction: the sum of unknown
capacities must equal the number of unaccounted cards, a played card may not be
in the own hand, and a publicly shown card may not contradict an inferred void
(which cannot happen in a legal state, because a seat holding the led suit must
follow it).

## What the layer exposes

| Query | Meaning |
| --- | --- |
| `possible_owners(card)` | Every seat the facts still allow. Empty for a played card. |
| `can_seat_hold(seat, card)` | The same fact, seat-first. |
| `is_seat_void(seat, suit)` | Proven void from failure to follow or an empty hand. |
| `known_held[seat]` | Cards publicly proven to be in that hand right now. |
| `unaccounted_cards` | Neither played nor publicly owned. |
| `cards_remaining` / `unknown_capacity` | Hand sizes and how much of each is unknown. |
| `is_highest_unplayed_in_suit(card)` | See below - a mechanical certainty. |
| `unplayed_higher_in_suit(card)` | Hard set. |
| `unaccounted_higher_in_suit(card)` | Hard set, restricted to unknown owners. |
| `seats_that_could_hold_higher(card, seats)` | Hard set of seats. |
| `unaccounted_count_by_suit()` | Hard counts, not a distribution. |

`own_void_suits` is kept separate from `void_suits` on purpose: the former uses
the observing player's own hand, the latter is strictly the public record. The
property test `test_inferred_voids_follow_only_from_public_failure_to_follow`
reconstructs the witnessed failure-to-follow events from the observation and
requires the inferred void sets to match exactly.

## Two mechanical certainties this buys

Both follow from the ruleset, not from an opinion, because `project_target_v1`
has **no trump suit** and only led-suit cards can win a trick:

1. **Leading the highest unplayed card of a suit always wins that trick.** Any
   seat that can follow plays a lower card of the suit; any seat that cannot
   follow discards off-suit, which cannot win.
2. **A card certainly wins the current trick** if it beats the current best card
   of the led suit and no seat that has not yet played can still hold a higher
   card of that suit.

`public_counting_v1` and above use exactly these. A cheap winner becomes a
*proven* winner as soon as a later seat is proven void - which is the designed
behavioural difference tested in `tests/agents/test_counting.py`.

## Soundness testing

- **Deterministic:** whole deals are replayed and, at every decision, the
  inference derived from the acting seat's observation is checked against the
  true hands: it must never exclude the true owner of any card, never mark a
  held card as played, and never assert a void that the true hand contradicts.
- **Property-based:** the same invariants over Hypothesis-generated deck
  permutations, plus the requirement that a played card has an empty
  possible-owner set and is in nobody's hand.
- **Structural:** no attribute of `PublicInference` may contain the tokens
  `probability`, `likelihood`, `prior`, `belief`, `weight`, or `sample`.

## Relationship to a future belief model

This object is a **precursor** to belief modelling and must not be confused with
one. A Phase 5 probabilistic model should sit *on top of* it and treat it as a
hard constraint set: any sampler, particle filter, or determinization that
assigns a card to a seat this object excludes is wrong by construction, whatever
its likelihood says. Keeping the two apart is what lets a later phase add
probability without quietly making Phase 4's claims probabilistic in retrospect.
