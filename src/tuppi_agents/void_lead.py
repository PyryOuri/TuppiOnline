"""The partnership-aware baseline, with both leads corrected.

`partner_aware_v1` leads the lowest-ranked card in the whole hand and uses
shortness only to break rank ties (`reactive.nolo.lead_lowest_from_shortest_suit.v1`).
That is a one-trick heuristic: it minimises the chance of winning the trick in
front of it and never pays anything for a void. But in NOLO a high card cannot be
shed within its own suit - it wins whatever trick it is played to - so its only
escape is a discard, and a discard requires a void. Voiding is therefore the only
instrument a hand has for exporting its losers, and it is worth investing in.

This policy swaps the priority of the two keys and changes nothing else::

    partner_aware_v1:  lead the lowest card in hand;  break ties toward the shortest suit
    this policy:       lead the shortest suit;        within it, lead the lowest card

Measured over identical forced-NOLO deals, for the side that changes:

===============================  ==============  ==============
outcome                          greedy lead     void-seeking
===============================  ==============  ==============
tricks taken (lower is better)   6.652           5.962
deal-win rate                    47.4%           61.3%
===============================  ==============  ==============

That is -0.69 tricks (z = -9.3) and +13.9 points of deal-win rate. It is not
merely an exploit of a weak opponent: against opponents *also* leading this way
it still gains +12.2 points (z = +8.1), so greedy leading is dominated.

Two design points were measured rather than assumed. Leading the *highest* card
of the shortest suit is clearly worse (+0.49 tricks, -4.3 points), because
exhausting a suit is order-independent - the order you shed it in cannot change
when it empties, only whether you win the trick on the way out. And selecting the
suit by "short and free of high cards" instead of by length alone measured at
-0.007 tricks, which is nothing.

**NOLO only.** In RAMI the leader wins 71.6% of tricks against a follower's
8-12%, so leading is how you take tricks rather than avoid them; RAMI scoring is
inherited untouched.

**A ranking, not an override.** The rule is applied by *scoring*: a preference
component is prepended above every inherited component, so the void-seeking card
becomes the lexicographic maximum while the base ranking survives beneath it as
the tie-break order. ``ScoredActions`` enforces that the selection is the
deterministic maximum, and the post-deal analysis reads the whole ranking to
explain alternatives - so overriding the choice without re-scoring would both be
rejected and destroy the diagnostics.

**Not a registered profile.** ``STRATEGIC_PROFILE_KEYS`` and the Phase 4 frozen
snapshot are digested by ``tuppi_match.freeze`` and verified by the Phase 5B
layer's integrity report; registering a profile here would break that baseline.
This subclasses the registered policy and reports its own identity instead, so a
consumer can always tell which one actually played.

See ``docs/valuation/void_seeking_lead.md`` for the evidence and its limits.
"""

from __future__ import annotations

from collections.abc import Sequence
from fractions import Fraction
from functools import lru_cache
import math

from tuppi_engine import EnginePhase, PlayerObservation
from tuppi_rules import Card, Contract, Suit
from tuppi_rules.cards import RANK_ORDER, SUIT_ORDER

from .action_scoring import CandidateEvaluation, ScoredActions
from .errors import AgentsValidationError
from .features import PublicFeatures
from .partner_aware import PartnerAwarePolicy


VOID_LEAD_SCHEMA_VERSION = "tuppi.agents.void_seeking_lead.v1"

#: The registered profile this policy is built on and scores through.
BASE_PROFILE_KEY = "partner_aware_v1"

#: The identity this policy reports. Distinct from BASE_PROFILE_KEY, because a
#: consumer must be able to tell which policy actually played.
VOID_LEAD_PROFILE_KEY = "partner_aware_lead_v2"

#: The score component this policy prepends, above every inherited one.
VOID_LEAD_COMPONENT = "void_lead_preference"

#: The RAMI counterpart: prefer the suit worth the most tricks if played out.
ESTABLISH_COMPONENT = "establishment_preference"
ESTABLISH_REASON_CODE = "establish_longest_paying_suit"

#: The preference is expressed as a score *component*, not as a catalogued rule
#: id. Every rule id in a candidate must resolve in ``rule_catalogue``, whose
#: entries carry provenance constraints tied to the frozen Phase 4 profiles;
#: adding one there for a non-registered policy would mean editing a structure
#: that sits beside the frozen baseline. The component name and reason code
#: below carry the same explanation into the diagnostics without that coupling.
VOID_LEAD_REASON_CODE = "void_lead_shortest_suit"


# --------------------------------------------------------------- suit maths
#
# A compact copy of ``tuppi_valuation.suits.expected_suit_tricks``. It is
# duplicated rather than imported because this package may depend on neither
# ``tuppi_valuation`` (which sits above it) nor the Phase 5B exact layer (whose
# one-directional check forbids it). Neither layer is named in full here: that
# check is a raw-text scan over this package's source, so writing the name in a
# comment reports a dependency that does not exist - the same reason
# ``nolo_discard`` never names it either. The duplication is pinned by
# ``test_local_suit_maths_matches_the_canonical_implementation``, which asserts
# exact Fraction equality against the canonical version over a wide grid.


@lru_cache(maxsize=None)
def _rounds_survived(outstanding: int, hand_size: int, void_count: int) -> tuple:
    """Law of M: rounds the suit survives among the opponents.

    Hand sizes are equal at the moment a lead is chosen - every seat has played
    the same number of cards - so the law depends on the *number* of proven
    voids, not on which opponents they are.
    """

    live = 3 - void_count
    unseen = 3 * hand_size
    if live <= 0 or outstanding == 0:
        return ((0, Fraction(1)),)
    if outstanding > live * hand_size:
        raise AgentsValidationError("more of the suit is outstanding than can be held")

    law: dict[int, Fraction] = {}
    total = Fraction(0)
    def walk(index: int, left: int, counts: tuple[int, ...]) -> None:
        nonlocal total
        if index == live:
            if left:
                return
            ways = math.factorial(outstanding)
            for count in counts:
                ways //= math.factorial(count)
            remaining = unseen - outstanding
            slots = [hand_size - c for c in counts] + [hand_size] * void_count
            filler = math.factorial(remaining)
            for slot in slots:
                filler //= math.factorial(slot)
            weight = Fraction(ways * filler)
            rounds = max(counts) if counts else 0
            law[rounds] = law.get(rounds, Fraction(0)) + weight
            total += weight
            return
        for take in range(min(left, hand_size) + 1):
            walk(index + 1, left - take, counts + (take,))

    walk(0, outstanding, ())
    if total == 0:
        raise AgentsValidationError("no placement of the suit is possible")
    return tuple(sorted((r, w / total) for r, w in law.items()))


def expected_suit_tricks(
    *, own_length: int, top_sequence_length: int,
    outstanding: int, hand_size: int, void_count: int,
) -> Fraction:
    """E[min(top_sequence, M) + max(0, own_length - M)].

    The expectation is taken *inside*: ``min`` is concave, so evaluating it at
    ``E[M]`` overstates the honour term and biases the score back toward
    honour-heavy suits, which is the bias a length-aware score exists to remove.
    """

    return sum(
        (
            probability * Fraction(
                min(top_sequence_length, rounds) + max(0, own_length - rounds)
            )
            for rounds, probability in _rounds_survived(
                outstanding, hand_size, void_count
            )
        ),
        Fraction(0),
    )


def top_sequence_length(ranks) -> int:
    """How many of the suit's very highest cards this holding owns."""

    held = set(ranks)
    count = 0
    for rank in reversed(RANK_ORDER):
        if rank.value in held:
            count += 1
        else:
            break
    return count


def establishment_lead(observation: PlayerObservation) -> Card:
    """The RAMI lead: the highest card of the suit worth the most tricks.

    `partner_aware_v1` scores a suit as ``HCP + 0.5 * length``. Honour weight
    runs 0-10 while the length credit maxes near 4, so honours dominate and a
    long weak suit is never chosen - even though, with no trump, such a suit
    runs unopposed once the other three seats are void.
    """

    by_suit: dict[Suit, list[Card]] = {}
    for card in observation.own_hand:
        by_suit.setdefault(card.suit, []).append(card)
    if not by_suit:
        raise AgentsValidationError("cannot lead from an empty hand")

    tricks_done = len(observation.completed_tricks)
    hand_size = 13 - tricks_done
    me = observation.observing_seat

    def score(suit: Suit) -> Fraction:
        cards = by_suit[suit]
        played = sum(
            1 for trick in observation.completed_tricks
            for play in trick.plays if play.card.suit is suit
        )
        outstanding = len(RANK_ORDER) - len(cards) - played
        voids = 0
        for other in range(4):
            if other == me:
                continue
            if any(
                play.seat == other and play.card.suit is not suit
                for trick in observation.completed_tricks
                if trick.plays[0].card.suit is suit
                for play in trick.plays
            ):
                voids += 1
        outstanding = max(0, min(outstanding, (3 - voids) * hand_size))
        return expected_suit_tricks(
            own_length=len(cards),
            top_sequence_length=top_sequence_length(c.rank.value for c in cards),
            outstanding=outstanding,
            hand_size=hand_size,
            void_count=voids,
        )

    suit = max(by_suit, key=lambda s: (score(s), -SUIT_ORDER.index(s)))
    return max(by_suit[suit], key=lambda card: card.rank.value)


def is_rami_lead(observation: PlayerObservation) -> bool:
    """True when the establishment rule applies: our own RAMI lead."""

    return (
        observation.phase is EnginePhase.TRICK_PLAY
        and observation.contract is Contract.RAMI
        and not observation.current_trick
        and observation.current_actor == observation.observing_seat
    )


def shortest_suit_lead(hand: Sequence[Card]) -> Card:
    """The card this policy leads: the lowest of the shortest suit held.

    Ties break deterministically - fewest cards, then the lower card, then
    canonical suit order - so the rule carries no hidden randomness.
    """

    by_suit: dict[Suit, list[Card]] = {}
    for card in hand:
        if not isinstance(card, Card):
            raise AgentsValidationError("a lead requires Card values")
        by_suit.setdefault(card.suit, []).append(card)
    if not by_suit:
        raise AgentsValidationError("cannot lead from an empty hand")
    suit = min(
        by_suit,
        key=lambda s: (
            len(by_suit[s]),
            min(card.rank.value for card in by_suit[s]),
            SUIT_ORDER.index(s),
        ),
    )
    return min(by_suit[suit], key=lambda card: card.rank.value)


def is_nolo_lead(observation: PlayerObservation) -> bool:
    """True when this policy's rule applies: our own NOLO lead."""

    return (
        observation.phase is EnginePhase.TRICK_PLAY
        and observation.contract is Contract.NOLO
        and not observation.current_trick
        and observation.current_actor == observation.observing_seat
    )


class VoidSeekingPartnerAwarePolicy(PartnerAwarePolicy):
    """`partner_aware_v1` with its leads corrected in both contracts."""

    def score_play_actions(
        self, observation: PlayerObservation, features: PublicFeatures
    ) -> ScoredActions:
        scored = super().score_play_actions(observation, features)
        if is_nolo_lead(observation):
            wanted = shortest_suit_lead(observation.own_hand)
            component, reason = VOID_LEAD_COMPONENT, VOID_LEAD_REASON_CODE
        elif is_rami_lead(observation):
            wanted = establishment_lead(observation)
            component, reason = ESTABLISH_COMPONENT, ESTABLISH_REASON_CODE
        else:
            return scored
        return self._prefer(scored, wanted, component, reason)

    @staticmethod
    def _prefer(scored, wanted, component, reason):
        """Re-score so *wanted* is the lexicographic maximum.

        The inherited ranking survives underneath as the tie-break order, which
        is what keeps the post-deal diagnostics able to explain alternatives.
        """

        preferred = [
            candidate.action_order_index
            for candidate in scored.candidates
            if getattr(candidate.action, "card", None) == wanted
        ]
        if len(preferred) != 1:
            # Every held card is legal to lead, so exactly one candidate should
            # match. If that ever stops holding, defer to the inherited ranking
            # rather than guess.
            return scored
        chosen = preferred[0]

        candidates = tuple(
            CandidateEvaluation(
                action=candidate.action,
                action_order_index=candidate.action_order_index,
                component_names=(component,) + candidate.component_names,
                score_vector=(
                    1.0 if candidate.action_order_index == chosen else 0.0,
                ) + candidate.score_vector,
                rule_ids=candidate.rule_ids,
                reason_codes=(
                    (reason,) if candidate.action_order_index == chosen else ()
                ) + candidate.reason_codes,
            )
            for candidate in scored.candidates
        )
        return ScoredActions(candidates=candidates, selected_index=chosen)


def registered_specification(profile_key: str = BASE_PROFILE_KEY):
    """Resolve one registered base profile's immutable ``AgentSpecification``.

    The type is not annotated because only the harness modules listed in
    ``tests/agents/test_architecture.py`` may import ``tuppi_eval``.

    Callers that build several void-lead agents at once own the returned
    specification and pass it to :func:`void_lead_agent_from_specification`,
    so the identity-bearing catalogue is built once rather than per seat.
    """

    from .registry import phase4_specifications_by_profile_key

    specifications = phase4_specifications_by_profile_key()
    if profile_key not in specifications:
        raise AgentsValidationError(f"unregistered agent profile {profile_key!r}")
    return specifications[profile_key]


def void_lead_agent_from_specification(
    specification, *, seat: int
) -> VoidSeekingPartnerAwarePolicy:
    """A fresh improved-lead policy for *seat* from an owned specification."""

    from .factory import profile_of

    if type(seat) is not int or seat not in range(4):
        raise AgentsValidationError("seat must be an integer in 0..3")
    return VoidSeekingPartnerAwarePolicy(
        agent_id=f"{VOID_LEAD_PROFILE_KEY}:{specification.agent_id}",
        profile=profile_of(specification),
    )


def construct_void_lead_agent(
    seat: int, *, profile_key: str = BASE_PROFILE_KEY
) -> VoidSeekingPartnerAwarePolicy:
    """One improved-lead policy for *seat*, scored through a registered profile."""

    if type(seat) is not int or seat not in range(4):
        raise AgentsValidationError("seat must be an integer in 0..3")
    return void_lead_agent_from_specification(
        registered_specification(profile_key), seat=seat
    )


def void_lead_agents_for_seats(
    seats: Sequence[int], *, profile_key: str = BASE_PROFILE_KEY
) -> dict[int, VoidSeekingPartnerAwarePolicy]:
    """Fresh, distinct improved-lead policies for *seats*, resolved once.

    Every seat still receives its own runtime object; only the immutable
    specification behind them is shared.
    """

    specification = registered_specification(profile_key)
    return {
        seat: void_lead_agent_from_specification(specification, seat=seat)
        for seat in seats
    }


def void_seeking_agents(
    profile_key: str = BASE_PROFILE_KEY, *, seats: Sequence[int] | None = None
) -> tuple:
    """Four agents for one deal, with the named seats leading void-seekingly.

    ``seats`` defaults to every seat. Pass ``(0, 2)`` to change one partnership
    only, which is how the effect was measured.
    """

    from .factory import construct_registered_agent

    specification = registered_specification(profile_key)
    chosen = frozenset(range(4) if seats is None else seats)
    if not chosen <= frozenset(range(4)):
        raise AgentsValidationError("seats must be a subset of 0..3")
    return tuple(
        void_lead_agent_from_specification(specification, seat=seat)
        if seat in chosen
        else construct_registered_agent(specification, seat=seat)
        for seat in range(4)
    )


__all__ = [
    "BASE_PROFILE_KEY",
    "VOID_LEAD_COMPONENT",
    "VOID_LEAD_PROFILE_KEY",
    "VOID_LEAD_REASON_CODE",
    "VOID_LEAD_SCHEMA_VERSION",
    "ESTABLISH_COMPONENT",
    "ESTABLISH_REASON_CODE",
    "VoidSeekingPartnerAwarePolicy",
    "establishment_lead",
    "expected_suit_tricks",
    "is_rami_lead",
    "top_sequence_length",
    "construct_void_lead_agent",
    "registered_specification",
    "void_lead_agent_from_specification",
    "void_lead_agents_for_seats",
    "is_nolo_lead",
    "shortest_suit_lead",
    "void_seeking_agents",
]
