"""Card representation and immutable deck constants."""

from __future__ import annotations

from collections.abc import Iterable

from .errors import InvalidCardError, InvalidHandError
from .model import Card, Color, Rank, Suit


DECK_SIZE = 52
CARDS_PER_HAND = 13
SUIT_ORDER: tuple[Suit, ...] = (
    Suit.HEARTS,
    Suit.DIAMONDS,
    Suit.CLUBS,
    Suit.SPADES,
)
RANK_ORDER: tuple[Rank, ...] = tuple(Rank(value) for value in range(2, 15))
FULL_DECK: tuple[Card, ...] = tuple(
    Card(suit=suit, rank=rank) for suit in SUIT_ORDER for rank in RANK_ORDER
)
ELIGIBLE_SHOW_RANKS: frozenset[Rank] = frozenset(
    Rank(value) for value in range(3, 10)
)
CARD_ENCODING_ID = "project_target_v1_suit_major_hdcs_rank_2_to_ace"

_RANK_CODES: tuple[str, ...] = (
    "2",
    "3",
    "4",
    "5",
    "6",
    "7",
    "8",
    "9",
    "10",
    "J",
    "Q",
    "K",
    "A",
)
_SUIT_CODES: tuple[str, ...] = ("H", "D", "C", "S")


def card_color(card: Card) -> Color:
    if not isinstance(card, Card):
        raise InvalidCardError("card_color requires a Card value")
    if card.suit in (Suit.HEARTS, Suit.DIAMONDS):
        return Color.RED
    return Color.BLACK


def card_to_index(card: Card) -> int:
    if not isinstance(card, Card):
        raise InvalidCardError("card_to_index requires a Card value")
    return SUIT_ORDER.index(card.suit) * len(RANK_ORDER) + (card.rank.value - 2)


def card_from_index(index: int) -> Card:
    if type(index) is not int or index not in range(DECK_SIZE):
        raise InvalidCardError("card index must be an integer in 0..51")
    suit_index, rank_index = divmod(index, len(RANK_ORDER))
    return Card(SUIT_ORDER[suit_index], RANK_ORDER[rank_index])


def card_to_code(card: Card) -> str:
    if not isinstance(card, Card):
        raise InvalidCardError("card_to_code requires a Card value")
    return f"{_RANK_CODES[card.rank.value - 2]}{_SUIT_CODES[SUIT_ORDER.index(card.suit)]}"


def card_from_code(code: str) -> Card:
    if not isinstance(code, str):
        raise InvalidCardError("card code must be a string")
    normalized = code.strip().upper()
    if len(normalized) < 2:
        raise InvalidCardError(f"invalid card code {code!r}")
    rank_code, suit_code = normalized[:-1], normalized[-1]
    if rank_code not in _RANK_CODES or suit_code not in _SUIT_CODES:
        raise InvalidCardError(f"invalid card code {code!r}")
    return Card(
        SUIT_ORDER[_SUIT_CODES.index(suit_code)],
        Rank(_RANK_CODES.index(rank_code) + 2),
    )


def normalize_cards(
    cards: Iterable[Card], *, context: str, allow_empty: bool
) -> tuple[Card, ...]:
    if isinstance(cards, (str, bytes)):
        raise InvalidHandError(f"{context} must be an iterable of Card values")
    try:
        normalized = tuple(cards)
    except TypeError as exc:
        raise InvalidHandError(f"{context} must be iterable") from exc
    if not allow_empty and not normalized:
        raise InvalidHandError(f"{context} must not be empty")
    for position, card in enumerate(normalized):
        if not isinstance(card, Card):
            raise InvalidHandError(
                f"{context} card at position {position} must be a Card value"
            )
    if len(set(normalized)) != len(normalized):
        raise InvalidHandError(f"{context} must not contain duplicate cards")
    return normalized


def validate_initial_hands(
    hands: Iterable[Iterable[Card]],
) -> tuple[tuple[Card, ...], ...]:
    if isinstance(hands, (str, bytes)):
        raise InvalidHandError("initial hands must contain four hands")
    try:
        raw_hands = tuple(hands)
    except TypeError as exc:
        raise InvalidHandError("initial hands must be iterable") from exc
    if len(raw_hands) != 4:
        raise InvalidHandError("initial hands must contain exactly four hands")
    normalized = tuple(
        normalize_cards(hand, context=f"seat {seat} hand", allow_empty=False)
        for seat, hand in enumerate(raw_hands)
    )
    if any(len(hand) != CARDS_PER_HAND for hand in normalized):
        raise InvalidHandError("every initial hand must contain exactly 13 cards")
    flat = tuple(card for hand in normalized for card in hand)
    if len(set(flat)) != DECK_SIZE or frozenset(flat) != frozenset(FULL_DECK):
        raise InvalidHandError("initial hands must partition the standard 52-card deck")
    return normalized
