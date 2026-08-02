"""Hard public inference: proven constraints only, never a belief model.

This module answers questions of the form *"is this excluded by public
information?"*. It never answers *"how likely is this?"*. There are no
probabilities, no sampling, no particle filters, and no priors here. Every
exclusion is a deduction from one of five facts:

1. the observing player's own hand;
2. cards already played (a played card is in nobody's hand);
3. cards publicly shown by a known seat during showing;
4. a seat that failed to follow a led suit is void in that suit;
5. remaining hand capacity per seat, applied as a pigeonhole argument.

Anything the five facts do not settle stays genuinely unknown: the possible
owner set of an unaccounted card is the full set of seats the facts allow, with
no weighting. Phase 5 may add a probabilistic belief model *on top of* this
object; it must not be confused with it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

from tuppi_engine import PlayerObservation
from tuppi_rules import (
    CARDS_PER_HAND,
    FULL_DECK,
    Card,
    Suit,
    partner_for_seat,
)

from .errors import AgentsValidationError
from .ordering import require_observation


PUBLIC_INFERENCE_SCHEMA_VERSION = "tuppi.agents.public_inference.v1"
MAXIMUM_REFINEMENT_PASSES = 4

_ALL_SUITS: frozenset[Suit] = frozenset(Suit)
_SUIT_CARDS: dict[Suit, tuple[Card, ...]] = {
    suit: tuple(card for card in FULL_DECK if card.suit is suit) for suit in Suit
}


@dataclass(frozen=True, slots=True)
class PublicInference:
    """An immutable set of proven constraints derived from one observation."""

    observing_seat: int
    played_cards: frozenset[Card]
    own_hand: frozenset[Card]
    own_void_suits: frozenset[Suit]
    known_held: tuple[frozenset[Card], ...]
    void_suits: tuple[frozenset[Suit], ...]
    cards_remaining: tuple[int, ...]
    unknown_capacity: tuple[int, ...]
    unaccounted_cards: frozenset[Card]
    possible_owner_map: Mapping[Card, frozenset[int]]
    schema_version: str = field(
        default=PUBLIC_INFERENCE_SCHEMA_VERSION, init=False
    )

    def __post_init__(self) -> None:
        if type(self.observing_seat) is not int or self.observing_seat not in range(4):
            raise AgentsValidationError("inference seat must be an integer in 0..3")
        for label, value in (
            ("known_held", self.known_held),
            ("void_suits", self.void_suits),
            ("cards_remaining", self.cards_remaining),
            ("unknown_capacity", self.unknown_capacity),
        ):
            if type(value) is not tuple or len(value) != 4:
                raise AgentsValidationError(f"{label} must be a four-seat tuple")
        if sum(self.unknown_capacity) != len(self.unaccounted_cards):
            raise AgentsValidationError(
                "unknown capacity disagrees with the unaccounted card count"
            )
        if self.played_cards & self.own_hand:
            raise AgentsValidationError("a played card cannot be in the own hand")
        for card, owners in self.possible_owner_map.items():
            if card in self.played_cards and owners:
                raise AgentsValidationError(
                    "a played card must have an empty possible-owner set"
                )
            if not isinstance(owners, frozenset):
                raise AgentsValidationError("possible-owner sets must be frozen")

    # ---------------------------------------------------------------- builders

    @classmethod
    def build(cls, observation: PlayerObservation) -> "PublicInference":
        checked = require_observation(observation)
        seat = checked.observing_seat
        own_hand = frozenset(checked.own_hand)

        played: set[Card] = set()
        played_count = [0, 0, 0, 0]
        voids: list[set[Suit]] = [set(), set(), set(), set()]
        for trick in checked.completed_tricks:
            led = trick.plays[0].card.suit
            for play in trick.plays:
                played.add(play.card)
                played_count[play.seat] += 1
                if play.card.suit is not led:
                    voids[play.seat].add(led)
        if checked.current_trick:
            led = checked.current_trick[0].card.suit
            for play in checked.current_trick:
                played.add(play.card)
                played_count[play.seat] += 1
                if play.card.suit is not led:
                    voids[play.seat].add(led)

        remaining = tuple(CARDS_PER_HAND - count for count in played_count)
        for index, count in enumerate(remaining):
            if count == 0:
                # An empty hand is void in every suit; this is a trivially sound
                # consequence of the public play history, not a guess.
                voids[index] = set(_ALL_SUITS)

        known: list[set[Card]] = [set(), set(), set(), set()]
        for shown_seat, shown_card in checked.publicly_shown_cards:
            if shown_card not in played:
                known[shown_seat].add(shown_card)
        known[seat] = set(own_hand)

        for index in range(4):
            if any(card.suit in voids[index] for card in known[index]):
                raise AgentsValidationError(
                    "public shown card contradicts an inferred void"
                )

        accounted = played | {card for hand in known for card in hand}
        unaccounted = frozenset(FULL_DECK) - accounted
        capacity = tuple(
            0 if index == seat else remaining[index] - len(known[index])
            for index in range(4)
        )
        if any(value < 0 for value in capacity):
            raise AgentsValidationError(
                "public shown cards exceed a seat's remaining capacity"
            )

        possible = _initial_possible_owners(
            unaccounted=unaccounted,
            observing_seat=seat,
            remaining=remaining,
            voids=voids,
            capacity=capacity,
        )
        possible, certain = _refine_possible_owners(
            possible=possible, capacity=capacity
        )
        for owner_seat, cards in certain.items():
            known[owner_seat] |= cards
        final_unaccounted = frozenset(possible)
        final_capacity = tuple(
            0 if index == seat else remaining[index] - len(known[index])
            for index in range(4)
        )
        owner_map: dict[Card, frozenset[int]] = {}
        for card in played:
            owner_map[card] = frozenset()
        for index in range(4):
            for card in known[index]:
                owner_map[card] = frozenset((index,))
        owner_map.update(possible)

        return cls(
            observing_seat=seat,
            played_cards=frozenset(played),
            own_hand=own_hand,
            own_void_suits=frozenset(
                suit for suit in Suit if not any(card.suit is suit for card in own_hand)
            ),
            known_held=tuple(frozenset(hand) for hand in known),
            void_suits=tuple(frozenset(suit_set) for suit_set in voids),
            cards_remaining=remaining,
            unknown_capacity=final_capacity,
            unaccounted_cards=final_unaccounted,
            possible_owner_map=MappingProxyType(owner_map),
        )

    # ----------------------------------------------------------------- queries

    @property
    def partner_seat(self) -> int:
        return partner_for_seat(self.observing_seat)

    @property
    def opponent_seats(self) -> tuple[int, int]:
        partner = self.partner_seat
        return tuple(  # type: ignore[return-value]
            index
            for index in range(4)
            if index != self.observing_seat and index != partner
        )

    def possible_owners(self, card: Card) -> frozenset[int]:
        """Return every seat that public information still allows to hold ``card``."""

        if not isinstance(card, Card):
            raise AgentsValidationError("possible_owners requires a Card")
        return self.possible_owner_map.get(card, frozenset())

    def can_seat_hold(self, seat: int, card: Card) -> bool:
        return seat in self.possible_owners(card)

    def is_seat_void(self, seat: int, suit: Suit) -> bool:
        if type(seat) is not int or seat not in range(4):
            raise AgentsValidationError("seat must be an integer in 0..3")
        if not isinstance(suit, Suit):
            raise AgentsValidationError("suit must be a Suit value")
        return suit in self.void_suits[seat]

    def is_played(self, card: Card) -> bool:
        return card in self.played_cards

    def unplayed_higher_in_suit(self, card: Card) -> frozenset[Card]:
        """Return unplayed same-suit cards that outrank ``card``."""

        if not isinstance(card, Card):
            raise AgentsValidationError("unplayed_higher_in_suit requires a Card")
        return frozenset(
            other
            for other in _SUIT_CARDS[card.suit]
            if other.rank.value > card.rank.value and other not in self.played_cards
        )

    def unplayed_lower_in_suit(self, card: Card) -> frozenset[Card]:
        if not isinstance(card, Card):
            raise AgentsValidationError("unplayed_lower_in_suit requires a Card")
        return frozenset(
            other
            for other in _SUIT_CARDS[card.suit]
            if other.rank.value < card.rank.value and other not in self.played_cards
        )

    def is_highest_unplayed_in_suit(self, card: Card) -> bool:
        """True when no unplayed card of the same suit outranks ``card``.

        ``project_target_v1`` has no trump suit and only led-suit cards can win
        a trick, so leading the highest unplayed card of a suit wins that trick
        with certainty. This is a mechanical consequence of the ruleset.
        """

        return not self.unplayed_higher_in_suit(card)

    def unaccounted_higher_in_suit(self, card: Card) -> frozenset[Card]:
        """Return higher same-suit cards whose holder is not publicly known."""

        return self.unplayed_higher_in_suit(card) & self.unaccounted_cards

    def seats_that_could_hold_higher(
        self, card: Card, seats: tuple[int, ...]
    ) -> frozenset[int]:
        """Return the subset of ``seats`` that could still hold a higher card."""

        higher = self.unplayed_higher_in_suit(card)
        return frozenset(
            seat
            for seat in seats
            if any(seat in self.possible_owners(other) for other in higher)
        )

    def unaccounted_count_by_suit(self) -> tuple[tuple[Suit, int], ...]:
        return tuple(
            (
                suit,
                sum(1 for card in self.unaccounted_cards if card.suit is suit),
            )
            for suit in Suit
        )

    def own_suit_length(self, suit: Suit) -> int:
        if not isinstance(suit, Suit):
            raise AgentsValidationError("suit must be a Suit value")
        return sum(1 for card in self.own_hand if card.suit is suit)


def _initial_possible_owners(
    *,
    unaccounted: frozenset[Card],
    observing_seat: int,
    remaining: tuple[int, ...],
    voids: list[set[Suit]],
    capacity: tuple[int, ...],
) -> dict[Card, frozenset[int]]:
    candidates: dict[Card, frozenset[int]] = {}
    for card in unaccounted:
        allowed = frozenset(
            seat
            for seat in range(4)
            if seat != observing_seat
            and remaining[seat] > 0
            and capacity[seat] > 0
            and card.suit not in voids[seat]
        )
        if not allowed:
            raise AgentsValidationError(
                "public constraints exclude every holder of an unaccounted card"
            )
        candidates[card] = allowed
    return candidates


def _refine_possible_owners(
    *, possible: dict[Card, frozenset[int]], capacity: tuple[int, ...]
) -> tuple[dict[Card, frozenset[int]], dict[int, frozenset[Card]]]:
    """Apply sound singleton and pigeonhole deductions to a fixed point.

    Two deductions run here, both exact:

    * a card whose possible-owner set has one element is certainly at that seat;
    * if the number of cards a seat could still hold equals its remaining
      unknown capacity, every one of those cards is certainly at that seat.

    Passes are bounded so the derivation cost stays deterministic and finite.
    """

    working = dict(possible)
    certain: dict[int, set[Card]] = {seat: set() for seat in range(4)}
    remaining_capacity = list(capacity)
    for _ in range(MAXIMUM_REFINEMENT_PASSES):
        changed = False
        for card in sorted(working, key=_card_order):
            owners = working[card]
            if len(owners) == 1:
                (seat,) = tuple(owners)
                certain[seat].add(card)
                remaining_capacity[seat] -= 1
                del working[card]
                changed = True
        for seat in range(4):
            if remaining_capacity[seat] < 0:
                raise AgentsValidationError(
                    "pigeonhole refinement produced a negative hand capacity"
                )
            if remaining_capacity[seat] == 0:
                for card in sorted(working, key=_card_order):
                    if seat in working[card]:
                        reduced = working[card] - {seat}
                        if not reduced:
                            raise AgentsValidationError(
                                "refinement excluded every holder of a card"
                            )
                        working[card] = reduced
                        changed = True
                continue
            owned = tuple(
                card
                for card in sorted(working, key=_card_order)
                if seat in working[card]
            )
            if len(owned) == remaining_capacity[seat]:
                for card in owned:
                    if working[card] != frozenset((seat,)):
                        working[card] = frozenset((seat,))
                        changed = True
        if not changed:
            break
    return working, {seat: frozenset(cards) for seat, cards in certain.items()}


def _card_order(card: Card) -> tuple[str, int]:
    return (card.suit.value, card.rank.value)
