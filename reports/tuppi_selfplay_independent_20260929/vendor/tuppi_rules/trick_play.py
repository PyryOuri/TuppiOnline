"""Pure follow-suit, trick-winner, and completed-deal validation."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from .cards import FULL_DECK, normalize_cards
from .errors import IllegalPlayError, InvalidCardError, InvalidDealStateError, InvalidTrickError
from .model import Card, PlayedCard, Suit
from .seating import team_for_seat, validate_seat


CARDS_PER_TRICK = 4
TRICKS_PER_DEAL = 13


def legal_cards(hand: Iterable[Card], led_suit: Suit | None) -> frozenset[Card]:
    cards = normalize_cards(hand, context="play hand", allow_empty=False)
    if led_suit is not None and not isinstance(led_suit, Suit):
        raise InvalidCardError("led_suit must be a Suit value or None")
    if led_suit is None:
        return frozenset(cards)
    following = frozenset(card for card in cards if card.suit is led_suit)
    return following if following else frozenset(cards)


def validate_play(
    *, hand: Iterable[Card], card: Card, led_suit: Suit | None
) -> Card:
    cards = normalize_cards(hand, context="play hand", allow_empty=False)
    if not isinstance(card, Card):
        raise IllegalPlayError("played card must be a Card value")
    if card not in cards:
        raise IllegalPlayError("played card is not in the player's hand")
    if card not in legal_cards(cards, led_suit):
        raise IllegalPlayError("player must follow the led suit when possible")
    return card


def validate_trick(plays: Sequence[PlayedCard]) -> tuple[PlayedCard, ...]:
    if isinstance(plays, (str, bytes)):
        raise InvalidTrickError("a trick must be a sequence of PlayedCard values")
    try:
        normalized = tuple(plays)
    except TypeError as exc:
        raise InvalidTrickError(
            "a trick must be a sequence of PlayedCard values"
        ) from exc
    if len(normalized) != CARDS_PER_TRICK:
        raise InvalidTrickError("a completed trick must contain exactly four cards")
    if any(not isinstance(play, PlayedCard) for play in normalized):
        raise InvalidTrickError("every trick entry must be a PlayedCard value")
    seats = tuple(play.seat for play in normalized)
    if len(set(seats)) != 4:
        raise InvalidTrickError("every seat must play exactly once in a trick")
    expected = tuple((seats[0] + offset) % 4 for offset in range(4))
    if seats != expected:
        raise InvalidTrickError(
            f"trick seats must proceed clockwise from the leader; expected {expected}"
        )
    cards = tuple(play.card for play in normalized)
    if len(set(cards)) != 4:
        raise InvalidTrickError("a card cannot be played twice in one trick")
    return normalized


def trick_winner(plays: Sequence[PlayedCard]) -> int:
    normalized = validate_trick(plays)
    led_suit = normalized[0].card.suit
    led_plays = tuple(play for play in normalized if play.card.suit is led_suit)
    return max(led_plays, key=lambda play: play.card.rank.value).seat


def is_deal_complete(completed_tricks: int) -> bool:
    if type(completed_tricks) is not int or completed_tricks not in range(14):
        raise InvalidDealStateError("completed trick count must be an integer in 0..13")
    return completed_tricks == TRICKS_PER_DEAL


def validate_completed_deal(
    tricks: Sequence[Sequence[PlayedCard]], *, expected_first_leader: int
) -> tuple[int, int]:
    if isinstance(tricks, (str, bytes)):
        raise InvalidDealStateError("completed deal must be a sequence of tricks")
    try:
        normalized_tricks = tuple(tricks)
    except TypeError as exc:
        raise InvalidDealStateError(
            "completed deal must be a sequence of tricks"
        ) from exc
    if len(normalized_tricks) != TRICKS_PER_DEAL:
        raise InvalidDealStateError(
            "a completed project_target_v1 deal must contain exactly 13 tricks"
        )
    expected_first_leader = validate_seat(expected_first_leader)

    validated_tricks: list[tuple[PlayedCard, ...]] = []
    winners: list[int] = []
    for trick_index, trick in enumerate(normalized_tricks):
        try:
            validated = validate_trick(trick)
        except InvalidTrickError as exc:
            raise InvalidDealStateError(f"trick {trick_index} is invalid: {exc}") from exc
        if trick_index == 0 and validated[0].seat != expected_first_leader:
            raise InvalidDealStateError("first trick has the wrong leader")
        if trick_index > 0 and validated[0].seat != winners[-1]:
            raise InvalidDealStateError("each trick winner must lead the next trick")
        validated_tricks.append(validated)
        winners.append(trick_winner(validated))

    cards = tuple(
        play.card for trick in validated_tricks for play in trick
    )
    if len(set(cards)) != 52 or frozenset(cards) != frozenset(FULL_DECK):
        raise InvalidDealStateError(
            "a completed deal must play every standard-deck card exactly once"
        )

    remaining = {
        seat: [
            play.card
            for trick in validated_tricks
            for play in trick
            if play.seat == seat
        ]
        for seat in range(4)
    }
    for trick_index, trick in enumerate(validated_tricks):
        led_suit = trick[0].card.suit
        for position, play in enumerate(trick):
            try:
                validate_play(
                    hand=remaining[play.seat],
                    card=play.card,
                    led_suit=None if position == 0 else led_suit,
                )
            except IllegalPlayError as exc:
                raise InvalidDealStateError(
                    f"trick {trick_index}, seat {play.seat} violates follow-suit: {exc}"
                ) from exc
            remaining[play.seat].remove(play.card)
    team0 = sum(team_for_seat(winner).value == 0 for winner in winners)
    team1 = TRICKS_PER_DEAL - team0
    return (team0, team1)
