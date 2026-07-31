from __future__ import annotations

import pytest

from tuppi_rules import (
    FULL_DECK,
    RANK_ORDER,
    SUIT_ORDER,
    Card,
    Color,
    InvalidCardError,
    InvalidHandError,
    Rank,
    Suit,
    card_color,
    card_from_code,
    card_from_index,
    card_to_code,
    card_to_index,
    validate_initial_hands,
)


def test_standard_deck_has_exactly_52_distinct_cards() -> None:
    assert len(FULL_DECK) == 52
    assert len(set(FULL_DECK)) == 52
    assert len(SUIT_ORDER) == 4
    assert len(RANK_ORDER) == 13


def test_suit_colors_are_authoritative() -> None:
    for rank in Rank:
        assert card_color(Card(Suit.HEARTS, rank)) is Color.RED
        assert card_color(Card(Suit.DIAMONDS, rank)) is Color.RED
        assert card_color(Card(Suit.CLUBS, rank)) is Color.BLACK
        assert card_color(Card(Suit.SPADES, rank)) is Color.BLACK


def test_rank_order_is_two_through_ace() -> None:
    assert tuple(rank.value for rank in RANK_ORDER) == tuple(range(2, 15))
    assert RANK_ORDER[0] is Rank.TWO
    assert RANK_ORDER[-1] is Rank.ACE


def test_all_cards_round_trip_through_index_and_code() -> None:
    for index, card in enumerate(FULL_DECK):
        assert card_to_index(card) == index
        assert card_from_index(index) == card
        assert card_from_code(card_to_code(card)) == card
        assert Card.from_code(card.to_code()) == card


def test_initial_hands_must_partition_the_full_deck() -> None:
    hands = tuple(FULL_DECK[index * 13 : (index + 1) * 13] for index in range(4))
    assert validate_initial_hands(hands) == hands
    with pytest.raises(InvalidHandError, match="13"):
        validate_initial_hands((hands[0][:-1], *hands[1:]))
    duplicate = (hands[0], hands[1], hands[2], hands[3][:-1] + (hands[0][0],))
    with pytest.raises(InvalidHandError, match="partition"):
        validate_initial_hands(duplicate)


@pytest.mark.parametrize("index", [-1, 52, True, 1.5, "1"])
def test_invalid_card_indices_are_rejected(index) -> None:
    with pytest.raises(InvalidCardError):
        card_from_index(index)


@pytest.mark.parametrize("code", ["", "1H", "11H", "AHH", "AX", 12])
def test_invalid_card_codes_are_rejected(code) -> None:
    with pytest.raises(InvalidCardError):
        card_from_code(code)


def test_card_constructor_rejects_raw_enum_values() -> None:
    with pytest.raises(InvalidCardError):
        Card("hearts", Rank.THREE)  # type: ignore[arg-type]
    with pytest.raises(InvalidCardError):
        Card(Suit.HEARTS, 3)  # type: ignore[arg-type]
