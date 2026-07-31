from __future__ import annotations

import pytest

from tuppi_rules import (
    Card,
    IllegalPlayError,
    InvalidTrickError,
    PlayedCard,
    Rank,
    Suit,
    legal_cards,
    trick_winner,
    validate_play,
    validate_trick,
)


def c(rank: Rank, suit: Suit) -> Card:
    return Card(suit, rank)


def test_leader_may_play_any_held_card() -> None:
    hand = (c(Rank.TWO, Suit.HEARTS), c(Rank.ACE, Suit.SPADES))
    assert legal_cards(hand, None) == frozenset(hand)
    for card in hand:
        assert validate_play(hand=hand, card=card, led_suit=None) == card


def test_follower_must_follow_suit_and_void_player_may_play_any_card() -> None:
    heart_two = c(Rank.TWO, Suit.HEARTS)
    heart_ace = c(Rank.ACE, Suit.HEARTS)
    club_ace = c(Rank.ACE, Suit.CLUBS)
    hand = (club_ace, heart_two, heart_ace)
    assert legal_cards(hand, Suit.HEARTS) == frozenset({heart_two, heart_ace})
    with pytest.raises(IllegalPlayError, match="follow"):
        validate_play(hand=hand, card=club_ace, led_suit=Suit.HEARTS)
    void_hand = (club_ace, c(Rank.TEN, Suit.SPADES))
    assert legal_cards(void_hand, Suit.HEARTS) == frozenset(void_hand)


def test_card_not_in_hand_is_rejected() -> None:
    with pytest.raises(IllegalPlayError, match="not in"):
        validate_play(
            hand=(c(Rank.TWO, Suit.HEARTS),),
            card=c(Rank.THREE, Suit.HEARTS),
            led_suit=None,
        )


def test_off_suit_ace_does_not_win_and_highest_led_suit_does() -> None:
    plays = (
        PlayedCard(2, c(Rank.TWO, Suit.HEARTS)),
        PlayedCard(3, c(Rank.ACE, Suit.SPADES)),
        PlayedCard(0, c(Rank.KING, Suit.HEARTS)),
        PlayedCard(1, c(Rank.ACE, Suit.CLUBS)),
    )
    assert trick_winner(plays) == 0


def test_ace_is_highest_at_led_suit_boundary() -> None:
    plays = (
        PlayedCard(3, c(Rank.TWO, Suit.DIAMONDS)),
        PlayedCard(0, c(Rank.KING, Suit.DIAMONDS)),
        PlayedCard(1, c(Rank.ACE, Suit.DIAMONDS)),
        PlayedCard(2, c(Rank.QUEEN, Suit.DIAMONDS)),
    )
    assert trick_winner(plays) == 1


@pytest.mark.parametrize("length", [0, 1, 2, 3, 5])
def test_trick_requires_exactly_four_cards(length: int) -> None:
    cards = (
        c(Rank.TWO, Suit.HEARTS),
        c(Rank.THREE, Suit.DIAMONDS),
        c(Rank.FOUR, Suit.CLUBS),
        c(Rank.FIVE, Suit.SPADES),
        c(Rank.SIX, Suit.HEARTS),
    )
    plays = tuple(PlayedCard(index % 4, cards[index]) for index in range(length))
    with pytest.raises(InvalidTrickError, match="exactly four"):
        validate_trick(plays)


def test_duplicate_nonclockwise_and_duplicate_card_tricks_are_rejected() -> None:
    cards = (
        c(Rank.TWO, Suit.HEARTS),
        c(Rank.THREE, Suit.DIAMONDS),
        c(Rank.FOUR, Suit.CLUBS),
        c(Rank.FIVE, Suit.SPADES),
    )
    with pytest.raises(InvalidTrickError, match="seat"):
        validate_trick(tuple(PlayedCard(seat, card) for seat, card in zip((0, 1, 1, 3), cards)))
    with pytest.raises(InvalidTrickError, match="clockwise"):
        validate_trick(tuple(PlayedCard(seat, card) for seat, card in zip((0, 2, 1, 3), cards)))
    with pytest.raises(InvalidTrickError, match="twice"):
        validate_trick(
            (
                PlayedCard(0, cards[0]),
                PlayedCard(1, cards[1]),
                PlayedCard(2, cards[0]),
                PlayedCard(3, cards[3]),
            )
        )


def test_noniterable_trick_raises_typed_error() -> None:
    with pytest.raises(InvalidTrickError):
        validate_trick(None)  # type: ignore[arg-type]
