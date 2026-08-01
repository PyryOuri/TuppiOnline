from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest

from tuppi_engine import (
    EnginePhase,
    ExplicitDeal,
    InvalidConstructionError,
    MatchState,
    StateInvariantError,
    create_match,
)
from tuppi_rules import FULL_DECK, MatchScore

from .conftest import start_match_deal


def test_valid_explicit_deal_constructs_private_showing_state(suit_hands) -> None:
    state = start_match_deal(hands=suit_hands, dealer=2)
    assert state.phase is EnginePhase.SHOWING
    assert state.dealer == 2
    assert state.current_actor == 3
    assert state.active_deal is not None
    assert state.active_deal.initial_hands == suit_hands
    assert state.active_deal.hands == suit_hands


def test_duplicate_card_is_rejected(suit_hands) -> None:
    duplicate = list(map(list, suit_hands))
    duplicate[3][-1] = duplicate[0][0]
    with pytest.raises(InvalidConstructionError, match="partition"):
        ExplicitDeal(dealer=0, hands=duplicate)


def test_missing_card_and_wrong_hand_size_are_rejected(suit_hands) -> None:
    missing = [list(hand) for hand in suit_hands]
    missing[0].pop()
    with pytest.raises(InvalidConstructionError, match="13"):
        ExplicitDeal(dealer=0, hands=missing)


@pytest.mark.parametrize("dealer", [-1, 4, True, 1.5, "0", None])
def test_invalid_dealer_is_rejected(dealer, suit_hands) -> None:
    with pytest.raises(InvalidConstructionError):
        ExplicitDeal(dealer=dealer, hands=suit_hands)


def test_invalid_and_terminal_starting_scores_are_rejected() -> None:
    with pytest.raises(InvalidConstructionError):
        create_match(initial_score=(0, 0), initial_dealer=0, match_ref="m")  # type: ignore[arg-type]
    with pytest.raises(InvalidConstructionError, match="terminal"):
        create_match(initial_score=MatchScore(52, 0), initial_dealer=0, match_ref="m")
    forged = object.__new__(MatchScore)
    object.__setattr__(forged, "team0", 20)
    object.__setattr__(forged, "team1", 20)
    with pytest.raises(InvalidConstructionError, match="invalid initial_score"):
        create_match(initial_score=forged, initial_dealer=0, match_ref="m")


@pytest.mark.parametrize("match_ref", ["contains space", "", "slash/ref", "x" * 97])
def test_match_reference_must_match_public_schema(match_ref: str) -> None:
    with pytest.raises(InvalidConstructionError, match="public schema"):
        create_match(
            initial_score=MatchScore(), initial_dealer=0, match_ref=match_ref
        )


def test_direct_match_state_rejects_forged_both_positive_score() -> None:
    forged = object.__new__(MatchScore)
    object.__setattr__(forged, "team0", 20)
    object.__setattr__(forged, "team1", 20)
    with pytest.raises(StateInvariantError, match="score"):
        MatchState(
            match_ref="forged-score",
            initial_score=MatchScore(),
            initial_dealer=0,
            score=forged,
            dealer=0,
            phase=EnginePhase.AWAITING_DEAL,
            active_deal=None,
            completed_deals=(),
            public_events=(),
        )


def test_deal_id_is_stable_and_uses_ordered_hands(suit_hands) -> None:
    first = ExplicitDeal(dealer=0, hands=suit_hands)
    second = ExplicitDeal(dealer=0, hands=[list(hand) for hand in suit_hands])
    reordered = tuple((hand[1], hand[0], *hand[2:]) for hand in suit_hands)
    third = ExplicitDeal(dealer=0, hands=reordered)
    assert first.deal_id == second.deal_id
    assert first.deal_id.startswith("sha256:")
    assert first.deal_id != third.deal_id
    assert first.deal_id != ExplicitDeal(dealer=1, hands=suit_hands).deal_id


def test_mutating_input_after_construction_cannot_change_state(suit_hands) -> None:
    mutable = [list(hand) for hand in suit_hands]
    explicit = ExplicitDeal(dealer=0, hands=mutable)
    state = start_match_deal(hands=mutable)
    original_id = explicit.deal_id
    original_hands = state.active_deal.initial_hands  # type: ignore[union-attr]
    mutable[0][0], mutable[1][0] = mutable[1][0], mutable[0][0]
    assert explicit.deal_id == original_id
    assert state.active_deal.initial_hands == original_hands  # type: ignore[union-attr]
    with pytest.raises(FrozenInstanceError):
        state.dealer = 2  # type: ignore[misc]


def test_private_deal_state_rejects_forged_content_identity() -> None:
    active = start_match_deal().active_deal
    assert active is not None
    with pytest.raises(StateInvariantError, match="canonical deal content"):
        replace(active, deal_id="sha256:" + "0" * 64)


def test_deal_has_exactly_52_unique_cards(suit_hands) -> None:
    explicit = ExplicitDeal(dealer=0, hands=suit_hands)
    flat = tuple(card for hand in explicit.hands for card in hand)
    assert len(flat) == 52
    assert len(set(flat)) == 52
    assert frozenset(flat) == frozenset(FULL_DECK)
