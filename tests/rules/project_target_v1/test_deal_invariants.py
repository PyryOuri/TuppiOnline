from __future__ import annotations

import pytest

from tuppi_rules import (
    FULL_DECK,
    InvalidDealStateError,
    PlayedCard,
    is_deal_complete,
    validate_completed_deal,
    validate_team_trick_totals,
)


def complete_structural_deal(leader: int = 0):
    tricks = []
    for rank_index in range(13):
        cards = tuple(FULL_DECK[suit_index * 13 + rank_index] for suit_index in range(4))
        tricks.append(
            tuple(
                PlayedCard((leader + offset) % 4, card)
                for offset, card in enumerate(cards)
            )
        )
    return tuple(tricks)


@pytest.mark.parametrize("count", range(13))
def test_deal_cannot_complete_before_thirteen_tricks(count: int) -> None:
    assert is_deal_complete(count) is False


def test_deal_is_complete_at_exactly_thirteen_tricks() -> None:
    assert is_deal_complete(13) is True


@pytest.mark.parametrize("count", [-1, 14, True, 1.5])
def test_invalid_completed_trick_counts_are_rejected(count) -> None:
    with pytest.raises(InvalidDealStateError):
        is_deal_complete(count)


def test_completed_deal_requires_thirteen_tricks_all_cards_and_winner_leads() -> None:
    tricks = complete_structural_deal(leader=0)
    assert validate_completed_deal(tricks, expected_first_leader=0) == (13, 0)
    with pytest.raises(InvalidDealStateError, match="13 tricks"):
        validate_completed_deal(tricks[:-1], expected_first_leader=0)
    with pytest.raises(InvalidDealStateError, match="wrong leader"):
        validate_completed_deal(tricks, expected_first_leader=1)


def test_completed_deal_rejects_duplicate_or_missing_card() -> None:
    tricks = list(complete_structural_deal())
    last = list(tricks[-1])
    last[-1] = PlayedCard(last[-1].seat, tricks[0][0].card)
    tricks[-1] = tuple(last)
    with pytest.raises(InvalidDealStateError, match="every standard-deck card"):
        validate_completed_deal(tuple(tricks), expected_first_leader=0)


def test_completed_deal_rejects_wrong_next_leader() -> None:
    tricks = list(complete_structural_deal())
    cards = tuple(play.card for play in tricks[1])
    tricks[1] = tuple(
        PlayedCard((1 + offset) % 4, card)
        for offset, card in enumerate(cards)
    )
    with pytest.raises(InvalidDealStateError, match="winner must lead"):
        validate_completed_deal(tuple(tricks), expected_first_leader=0)


def test_completed_deal_rejects_reconstructed_follow_suit_violation() -> None:
    tricks = list(complete_structural_deal())
    second = list(tricks[1])
    # Seat 1 plays D2 on the first heart lead while H3 remains in its
    # reconstructed hand for trick 2. Swap H3/D3 within trick 2 so the
    # transcript still contains every card once and seat 0 still wins/leads.
    second[0], second[1] = (
        PlayedCard(second[0].seat, second[1].card),
        PlayedCard(second[1].seat, second[0].card),
    )
    tricks[1] = tuple(second)
    with pytest.raises(InvalidDealStateError, match="follow-suit"):
        validate_completed_deal(tuple(tricks), expected_first_leader=0)


def test_completed_deal_malformed_iterables_raise_typed_error() -> None:
    with pytest.raises(InvalidDealStateError):
        validate_completed_deal(None, expected_first_leader=0)  # type: ignore[arg-type]
    with pytest.raises(InvalidDealStateError, match="trick 0"):
        validate_completed_deal((None,) * 13, expected_first_leader=0)  # type: ignore[arg-type]


def test_team_trick_totals_must_sum_to_thirteen() -> None:
    for team0 in range(14):
        assert validate_team_trick_totals(team0, 13 - team0) == (team0, 13 - team0)
    with pytest.raises(InvalidDealStateError, match="sum to 13"):
        validate_team_trick_totals(6, 6)
