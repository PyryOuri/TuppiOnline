from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from tuppi_rules import (
    FULL_DECK,
    Card,
    Contract,
    InvalidHandError,
    InvalidShowActionError,
    Rank,
    ShowAction,
    Suit,
    is_show_rank_eligible,
    valid_show_cards,
    validate_show_action,
    verbal_declaration_required,
)


def c(rank: Rank, suit: Suit) -> Card:
    return Card(suit, rank)


def complete_show_hand(*cards: Card) -> tuple[Card, ...]:
    fillers = tuple(
        card
        for card in FULL_DECK
        if not is_show_rank_eligible(card) and card not in cards
    )
    return (*cards, *fillers[: 13 - len(cards)])


def test_show_rank_eligibility_is_exactly_three_through_nine() -> None:
    for card in FULL_DECK:
        assert is_show_rank_eligible(card) is (3 <= card.rank.value <= 9)
    assert sum(is_show_rank_eligible(card) for card in FULL_DECK) == 28


@pytest.mark.parametrize(
    ("contract", "matching", "mismatched"),
    [
        (Contract.RAMI, c(Rank.THREE, Suit.HEARTS), c(Rank.FOUR, Suit.CLUBS)),
        (Contract.NOLO, c(Rank.THREE, Suit.CLUBS), c(Rank.FOUR, Suit.HEARTS)),
    ],
)
def test_matching_eligible_color_must_be_used_when_available(
    contract, matching, mismatched
) -> None:
    hand = complete_show_hand(matching, mismatched)
    assert valid_show_cards(hand, contract) == frozenset({matching})
    normal = validate_show_action(
        seat=0, hand=hand, shown_card=matching, declared_contract=contract
    )
    assert normal.verbal_required is False
    with pytest.raises(InvalidShowActionError, match="hierarchy"):
        validate_show_action(
            seat=0, hand=hand, shown_card=mismatched, declared_contract=contract
        )


@pytest.mark.parametrize(
    ("contract", "eligible_cards"),
    [
        (
            Contract.RAMI,
            (c(Rank.THREE, Suit.CLUBS), c(Rank.NINE, Suit.SPADES)),
        ),
        (
            Contract.NOLO,
            (c(Rank.FOUR, Suit.HEARTS), c(Rank.EIGHT, Suit.DIAMONDS)),
        ),
    ],
)
def test_any_eligible_card_allowed_when_desired_eligible_color_absent(
    contract, eligible_cards
) -> None:
    hand = complete_show_hand(*eligible_cards)
    assert valid_show_cards(hand, contract) == frozenset(eligible_cards)
    for shown in eligible_cards:
        action = validate_show_action(
            seat=1, hand=hand, shown_card=shown, declared_contract=contract
        )
        assert action.verbal_required is True


@pytest.mark.parametrize("contract", [Contract.RAMI, Contract.NOLO])
def test_any_hand_card_allowed_when_no_eligible_ranks_exist(contract) -> None:
    hand = complete_show_hand(
        c(Rank.TWO, Suit.HEARTS),
        c(Rank.TEN, Suit.CLUBS),
        c(Rank.JACK, Suit.DIAMONDS),
        c(Rank.ACE, Suit.SPADES),
    )
    assert valid_show_cards(hand, contract) == frozenset(hand)
    for shown in hand:
        assert verbal_declaration_required(hand, shown, contract) is True


def test_no_eligible_fallback_is_verbal_even_when_card_color_matches() -> None:
    hand = complete_show_hand(
        c(Rank.ACE, Suit.HEARTS), c(Rank.TWO, Suit.CLUBS)
    )
    action = validate_show_action(
        seat=2,
        hand=hand,
        shown_card=c(Rank.ACE, Suit.HEARTS),
        declared_contract=Contract.RAMI,
    )
    assert action.verbal_required is True


def test_shown_card_must_belong_to_hand() -> None:
    hand = complete_show_hand(c(Rank.THREE, Suit.HEARTS))
    with pytest.raises(InvalidShowActionError, match="belong"):
        validate_show_action(
            seat=0,
            hand=hand,
            shown_card=c(Rank.FOUR, Suit.HEARTS),
            declared_contract=Contract.RAMI,
        )


def test_verbal_flag_is_derived_and_cannot_be_lied_about() -> None:
    hand = complete_show_hand(c(Rank.THREE, Suit.HEARTS))
    with pytest.raises(InvalidShowActionError, match="disagrees"):
        validate_show_action(
            seat=0,
            hand=hand,
            shown_card=hand[0],
            declared_contract=Contract.RAMI,
            claimed_verbal_required=True,
        )
    with pytest.raises(InvalidShowActionError, match="disagrees"):
        ShowAction(
            seat=0,
            hand=hand,
            shown_card=hand[0],
            declared_contract=Contract.RAMI,
            claimed_verbal_required=True,
        )


def test_showing_retains_card_and_does_not_mutate_hand() -> None:
    hand = complete_show_hand(
        c(Rank.THREE, Suit.HEARTS), c(Rank.ACE, Suit.CLUBS)
    )
    before = hand
    action = validate_show_action(
        seat=3,
        hand=hand,
        shown_card=hand[0],
        declared_contract=Contract.RAMI,
    )
    assert hand == before
    assert action.shown_card in hand
    with pytest.raises(FrozenInstanceError):
        action.seat = 0  # type: ignore[misc]


def test_empty_or_duplicate_showing_hands_are_rejected() -> None:
    with pytest.raises(InvalidHandError, match="empty"):
        valid_show_cards((), Contract.RAMI)
    card = c(Rank.THREE, Suit.HEARTS)
    with pytest.raises(InvalidHandError, match="duplicate"):
        valid_show_cards((card, card), Contract.RAMI)


def test_show_action_requires_a_complete_thirteen_card_hand() -> None:
    card = c(Rank.THREE, Suit.HEARTS)
    with pytest.raises(InvalidShowActionError, match="13-card"):
        validate_show_action(
            seat=0,
            hand=(card,),
            shown_card=card,
            declared_contract=Contract.RAMI,
        )


def test_invalid_contract_and_nonboolean_claim_are_rejected() -> None:
    hand = complete_show_hand(c(Rank.THREE, Suit.HEARTS))
    with pytest.raises(InvalidShowActionError, match="Contract"):
        validate_show_action(
            seat=0,
            hand=hand,
            shown_card=hand[0],
            declared_contract="RAMI",  # type: ignore[arg-type]
        )
    with pytest.raises(InvalidShowActionError, match="boolean"):
        validate_show_action(
            seat=0,
            hand=hand,
            shown_card=hand[0],
            declared_contract=Contract.RAMI,
            claimed_verbal_required=0,  # type: ignore[arg-type]
        )
