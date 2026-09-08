"""NOLO discards priced by the exact single-suit ducking law.

`reactive.nolo.discard_highest_liability.v1` chooses a discard from a rank-only
table - ace 4.0, king 3.0, queen 2.0, jack 1.0, ten 0.5, nine 0.25, everything
else 0.0 - and its catalogued limitation already concedes the problem: the
weights are uncalibrated legacy constants ported from `legacy_v9_unverified`.

The table cannot see anything that decides whether a high card is actually
dangerous: how much of its suit is still outstanding, which opponents have proved
void in it, how many rounds it can survive, or what the hand holds beneath the
honour. An ace in a suit nobody can lead again is not a 4.0 liability, and a nine
may be one when it is the hand's only card in a live suit.

This module prices each candidate discard instead, as the expected tricks the
holding takes if the card is *kept*, under exact ducking combinatorics
conditioned on the public record. The measured direction of the legacy error is
already known: spot cards are worth up to 1.63 tricks within a fixed honour
skeleton, while the table prices everything below a nine at nothing.

**What it conditions on, and what it refuses to.** Cards already played are gone
and a seat that failed to follow is void; both are certainties. Which *rank* an
opponent chose to play is deliberately unused. Read as an exact order statistic
it looks strongly informative, but under the honest reading "their lowest is at
most this" only 1-5% of the signal survives - the rest was measuring the
baseline's own determinism. `test_discard_ignores_which_low_card_was_played`
enforces that mechanically.

**A known, deliberate weakening.** A card shown at deal start but not yet played
is still held by a known seat. This release leaves such a card outstanding with
its owner unknown rather than modelling the placement, which discards
information it is entitled to use. At most one card per suit is affected. It is a
limitation, not a correctness claim, and it is the first thing a follow-up should
fix.

**A ranking, not an override.** The preference is a score *component* prepended
above every inherited component, so the chosen discard becomes the lexicographic
maximum while the base ranking survives beneath as the tie-break order.
``ScoredActions`` enforces that the selection is the deterministic maximum, and
the post-deal analysis reads the whole ranking to explain alternatives.

**Not a registered profile.** The frozen Phase 4 snapshot is digested and
verified elsewhere; registering a profile here would break that baseline. This
subclasses the registered policy and reports its own identity.

The suit maths below is a compact copy of
``tuppi_valuation.suits.conditional_ducking_round_probabilities``, duplicated
because this package may not depend on that one, which sits above it. The
duplication is pinned by
``test_local_ducking_law_matches_the_canonical_implementation``, which asserts
exact ``Fraction`` equality against the canonical version over a wide grid.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from fractions import Fraction
from functools import lru_cache
import math

from tuppi_engine import EnginePhase, PlayerObservation
from tuppi_rules import Card, Contract, Suit

from .errors import AgentsValidationError
from .void_lead import VoidSeekingPartnerAwarePolicy

#: Prefer the discard whose retention costs the most expected tricks.
LIABILITY_COMPONENT = "discard_liability_preference"
LIABILITY_REASON_CODE = "discard_priced_liability"

SUIT_SIZE = 13
OPPONENT_COUNT = 3
CARDS_PER_HAND = 13


def _multinomial(total: int, parts: Sequence[int]) -> int:
    if total < 0 or any(part < 0 for part in parts) or sum(parts) != total:
        return 0
    ways = math.factorial(total)
    for part in parts:
        ways //= math.factorial(part)
    return ways


def _capped_compositions(total: int, caps: tuple[int, int, int]) -> Iterator[tuple]:
    first_cap, second_cap, third_cap = caps
    for first in range(min(total, first_cap) + 1):
        remaining = total - first
        low = max(0, remaining - third_cap)
        for second in range(low, min(remaining, second_cap) + 1):
            third = remaining - second
            if third <= third_cap:
                yield first, second, third


@lru_cache(maxsize=8192)
def ducking_probabilities(
    own_ranks: tuple[int, ...],
    outstanding_ranks: tuple[int, ...],
    hand_sizes: tuple[int, int, int],
    void: tuple[bool, bool, bool],
    max_leads: int,
    *,
    contested_only: bool = False,
) -> tuple[Fraction, ...]:
    """P(this holding wins round *i*) for i = 1..max_leads, everyone ducking.

    Round *i* is contested by each seat's *i*-th lowest card, and an opponent's
    *i*-th lowest lies below a given card exactly when that opponent holds *i* or
    more cards below it. So a round turns only on how the outstanding ranks split
    into those below the card and those above it, never on which ranks they are -
    which is what replaces an enumeration over rank assignments with a pair of
    three-part compositions.

    With *contested_only*, a round counts only while some opponent can still
    contribute to it. That is the form a liability needs: a round nobody can lead
    is not a trick anybody takes.
    """

    mine = sorted(own_ranks)
    unseen = sum(hand_sizes)
    outstanding = len(outstanding_ranks)
    if outstanding > unseen:
        raise AgentsValidationError("more of the suit is outstanding than is unseen")
    filler = unseen - outstanding
    caps = tuple(0 if flag else size for flag, size in zip(void, hand_sizes))

    normaliser = 0
    for counts in _capped_compositions(outstanding, caps):
        remainder = tuple(size - count for size, count in zip(hand_sizes, counts))
        normaliser += _multinomial(outstanding, counts) * _multinomial(filler, remainder)
    if normaliser == 0:
        raise AgentsValidationError("the public record admits no placement of the suit")

    rounds = min(max_leads, len(mine))
    totals: list[Fraction] = []
    for index in range(rounds):
        card = mine[index]
        needed = index + 1
        below = sum(1 for rank in outstanding_ranks if rank < card)
        above = outstanding - below
        winning = 0
        for lows in _capped_compositions(below, caps):
            highs_caps = tuple(cap - low for cap, low in zip(caps, lows))
            for highs in _capped_compositions(above, highs_caps):
                held = tuple(low + high for low, high in zip(lows, highs))
                if contested_only and max(held) < needed:
                    continue
                if any(
                    total >= needed and low < needed
                    for total, low in zip(held, lows)
                ):
                    continue
                remainder = tuple(
                    size - count for size, count in zip(hand_sizes, held)
                )
                winning += (
                    _multinomial(below, lows)
                    * _multinomial(above, highs)
                    * _multinomial(filler, remainder)
                )
        totals.append(Fraction(winning, normaliser))
    return tuple(totals) + (Fraction(0),) * (max_leads - rounds)


def expected_ducking_tricks(
    own_ranks: tuple[int, ...],
    outstanding_ranks: tuple[int, ...],
    hand_sizes: tuple[int, int, int],
    void: tuple[bool, bool, bool],
) -> Fraction:
    """Expected tricks this holding takes while the suit is still contested."""

    if not own_ranks:
        return Fraction(0)
    return sum(
        ducking_probabilities(
            own_ranks, outstanding_ranks, hand_sizes, void,
            len(own_ranks), contested_only=True,
        ),
        Fraction(0),
    )


def card_liability(
    rank: int,
    own_ranks: tuple[int, ...],
    outstanding_ranks: tuple[int, ...],
    hand_sizes: tuple[int, int, int],
    void: tuple[bool, bool, bool],
) -> Fraction:
    """Expected tricks that keeping *rank* costs, over discarding it.

    The card discarded joins the outstanding pool only in the sense that it is
    gone from this hand; it cannot win a later trick for anybody, so it is
    dropped from the analysis rather than handed to an opponent.
    """

    if rank not in own_ranks:
        raise AgentsValidationError("the card must be held to be discarded")
    kept = expected_ducking_tricks(own_ranks, outstanding_ranks, hand_sizes, void)
    without = tuple(value for value in own_ranks if value != rank)
    shed = expected_ducking_tricks(without, outstanding_ranks, hand_sizes, void)
    return kept - shed


# ------------------------------------------------- reading the public record


def _played_cards(observation: PlayerObservation) -> list[tuple[int, Card]]:
    plays: list[tuple[int, Card]] = []
    for trick in observation.completed_tricks:
        for play in trick.plays:
            plays.append((play.seat, play.card))
    for play in observation.current_trick:
        plays.append((play.seat, play.card))
    return plays


def opponent_order(seat: int) -> tuple[int, int, int]:
    """The three other seats, in a fixed clockwise order from *seat*."""

    return ((seat + 1) % 4, (seat + 2) % 4, (seat + 3) % 4)


def public_conditioning(observation: PlayerObservation, suit: Suit) -> tuple:
    """Outstanding ranks, hand sizes and proven voids for *suit*.

    Only played cards and proven voids are used. A card shown at deal start but
    not yet played stays outstanding with an unknown owner, which is the
    documented weakening in this module's docstring.
    """

    seat = observation.observing_seat
    others = opponent_order(seat)
    plays = _played_cards(observation)

    played_in_suit = {card.rank.value for _, card in plays if card.suit is suit}
    held = {card.rank.value for card in observation.own_hand if card.suit is suit}
    outstanding = tuple(
        sorted(
            (
                rank
                for rank in range(2, 15)
                if rank not in played_in_suit and rank not in held
            ),
            reverse=True,
        )
    )

    counts = {other: 0 for other in others}
    for actor, _ in plays:
        if actor in counts:
            counts[actor] += 1
    hand_sizes = tuple(CARDS_PER_HAND - counts[other] for other in others)

    # A seat is void when it failed to follow a suit that was led.
    void_seats: set[int] = set()
    groups = [trick.plays for trick in observation.completed_tricks]
    if observation.current_trick:
        groups.append(tuple(observation.current_trick))
    for group in groups:
        if not group or group[0].card.suit is not suit:
            continue
        for play in group[1:]:
            if play.card.suit is not suit:
                void_seats.add(play.seat)
    void = tuple(other in void_seats for other in others)
    return outstanding, hand_sizes, void


def is_nolo_discard(observation: PlayerObservation) -> bool:
    """True when this policy's rule applies: our NOLO discard, void in the led suit."""

    if (
        observation.phase is not EnginePhase.TRICK_PLAY
        or observation.contract is not Contract.NOLO
        or observation.current_actor != observation.observing_seat
        or not observation.current_trick
    ):
        return False
    led = observation.current_trick[0].card.suit
    return all(card.suit is not led for card in observation.own_hand)


def priced_discard(observation: PlayerObservation) -> Card:
    """The card to discard: the one whose retention costs the most tricks.

    Ties break deterministically - the larger liability, then the shorter suit,
    then the higher rank, then canonical suit order - so the rule carries no
    hidden randomness.
    """

    by_suit: dict[Suit, list[Card]] = {}
    for card in observation.own_hand:
        if not isinstance(card, Card):
            raise AgentsValidationError("a discard requires Card values")
        by_suit.setdefault(card.suit, []).append(card)
    if not by_suit:
        raise AgentsValidationError("a discard requires a non-empty hand")

    best: tuple | None = None
    chosen: Card | None = None
    for suit, cards in by_suit.items():
        outstanding, hand_sizes, void = public_conditioning(observation, suit)
        own = tuple(sorted(card.rank.value for card in cards))
        for card in cards:
            liability = card_liability(
                card.rank.value, own, outstanding, hand_sizes, void
            )
            key = (liability, -len(cards), card.rank.value, -_suit_order(card.suit))
            if best is None or key > best:
                best, chosen = key, card
    if chosen is None:
        raise AgentsValidationError("no discard could be priced")
    return chosen


def _suit_order(suit: Suit) -> int:
    return list(Suit).index(suit)


class LiabilityDiscardPolicy(VoidSeekingPartnerAwarePolicy):
    """`partner_aware_lead_v2` with its NOLO discard priced instead of tabled."""

    def score_play_actions(self, observation, features):
        scored = super().score_play_actions(observation, features)
        if not is_nolo_discard(observation):
            return scored
        return self._prefer(
            scored,
            priced_discard(observation),
            LIABILITY_COMPONENT,
            LIABILITY_REASON_CODE,
        )


LIABILITY_PROFILE_KEY = "partner_aware_discard_v3"


def liability_discard_agent_from_specification(
    specification, *, seat: int
) -> LiabilityDiscardPolicy:
    """A fresh priced-discard policy for *seat* from an owned specification."""

    from .factory import profile_of

    if type(seat) is not int or seat not in range(4):
        raise AgentsValidationError("seat must be an integer in 0..3")
    return LiabilityDiscardPolicy(
        agent_id=f"{LIABILITY_PROFILE_KEY}:{specification.agent_id}",
        profile=profile_of(specification),
    )


def liability_discard_agents_for_seats(seats: Sequence[int]) -> dict:
    """One catalogue resolution for a whole table, one fresh agent per seat."""

    from .void_lead import registered_specification

    specification = registered_specification()
    return {
        seat: liability_discard_agent_from_specification(specification, seat=seat)
        for seat in seats
    }
