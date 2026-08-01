from __future__ import annotations

import pytest

from tuppi_engine import (
    EnginePhase,
    InvalidActionError,
    PlayCardAction,
    ShowAction,
    WrongActorError,
    WrongPhaseError,
    apply_match_action,
)
from tuppi_rules import Contract, Rank, Suit, forehand

from .conftest import (
    card,
    legal_action_for_contract,
    no_eligible_forehand_hands,
    resolve_all_nolo,
    start_match_deal,
)


@pytest.mark.parametrize("dealer", range(4))
def test_forehand_is_first_actor_for_every_dealer(dealer: int) -> None:
    state = start_match_deal(dealer=dealer)
    assert state.current_actor == forehand(dealer)


def test_showing_order_advances_clockwise() -> None:
    state = start_match_deal(dealer=0)
    observed = []
    for _ in range(3):
        observed.append(state.current_actor)
        state = apply_match_action(
            state, legal_action_for_contract(state, Contract.NOLO)
        )
    assert observed == [1, 2, 3]
    assert state.current_actor == 0


def test_normal_red_rami_show_resolves_without_verbal_declaration() -> None:
    state = start_match_deal(dealer=3)
    action = ShowAction(0, card("H3"), Contract.RAMI)
    state = apply_match_action(state, action)
    accepted = state.active_deal.show_actions[0]  # type: ignore[union-attr]
    assert accepted.verbal_required is False
    assert state.phase is EnginePhase.TRICK_PLAY
    assert state.active_deal.contract is Contract.RAMI  # type: ignore[union-attr]
    assert state.active_deal.declarer == 0  # type: ignore[union-attr]
    assert state.current_actor == 3


def test_normal_black_nolo_show_is_accepted_without_verbal_declaration() -> None:
    state = start_match_deal(dealer=1)
    state = apply_match_action(state, ShowAction(2, card("C3"), Contract.NOLO))
    accepted = state.active_deal.show_actions[0]  # type: ignore[union-attr]
    assert accepted.verbal_required is False
    assert state.phase is EnginePhase.SHOWING


def test_verbal_color_mismatch_fallback_is_derived() -> None:
    state = start_match_deal(dealer=1)
    state = apply_match_action(state, ShowAction(2, card("C3"), Contract.RAMI))
    accepted = state.active_deal.show_actions[0]  # type: ignore[union-attr]
    assert accepted.verbal_required is True
    assert state.active_deal.contract is Contract.RAMI  # type: ignore[union-attr]


def test_no_eligible_rank_allows_any_hand_card_and_requires_verbal() -> None:
    state = start_match_deal(hands=no_eligible_forehand_hands(), dealer=0)
    before = state.active_deal.hands[1]  # type: ignore[union-attr]
    state = apply_match_action(state, ShowAction(1, card("H2"), Contract.RAMI))
    accepted = state.active_deal.show_actions[0]  # type: ignore[union-attr]
    assert accepted.shown_card == card("H2")
    assert accepted.verbal_required is True
    assert state.active_deal.hands[1] == before  # type: ignore[union-attr]


def test_wrong_color_show_is_rejected_when_matching_eligible_exists(suit_hands) -> None:
    mutable = [list(hand) for hand in suit_hands]
    club_three = card("C3")
    heart_ace = card("HA")
    mutable[0][mutable[0].index(heart_ace)] = club_three
    mutable[2][mutable[2].index(club_three)] = heart_ace
    state = start_match_deal(hands=mutable, dealer=3)
    with pytest.raises(InvalidActionError, match="fallback hierarchy"):
        apply_match_action(state, ShowAction(0, club_three, Contract.RAMI))


def test_shown_card_not_in_hand_is_rejected() -> None:
    state = start_match_deal(dealer=3)
    with pytest.raises(InvalidActionError, match="belong"):
        apply_match_action(state, ShowAction(0, card("C3"), Contract.RAMI))


def test_wrong_actor_and_duplicate_show_are_rejected() -> None:
    state = start_match_deal(dealer=0)
    action = legal_action_for_contract(state, Contract.NOLO)
    with pytest.raises(WrongActorError):
        apply_match_action(
            state,
            ShowAction((action.seat + 1) % 4, card("C3"), Contract.NOLO),
        )
    state = apply_match_action(state, action)
    with pytest.raises(WrongActorError):
        apply_match_action(state, action)


def test_rami_terminates_showing_and_later_show_is_rejected() -> None:
    state = start_match_deal(dealer=3)
    state = apply_match_action(state, ShowAction(0, card("H3"), Contract.RAMI))
    assert len(state.active_deal.show_actions) == 1  # type: ignore[union-attr]
    with pytest.raises(WrongPhaseError, match="resolved"):
        apply_match_action(state, ShowAction(1, card("D3"), Contract.NOLO))


def test_four_nolo_actions_resolve_without_declarer() -> None:
    state = resolve_all_nolo(start_match_deal(dealer=0))
    assert state.phase is EnginePhase.TRICK_PLAY
    assert state.active_deal.contract is Contract.NOLO  # type: ignore[union-attr]
    assert state.active_deal.declarer is None  # type: ignore[union-attr]
    assert state.active_deal.first_leader == 1  # type: ignore[union-attr]
    assert state.current_actor == 1


@pytest.mark.parametrize("dealer", range(4))
@pytest.mark.parametrize("show_position", range(4))
def test_first_leader_for_every_declarer_position(
    dealer: int, show_position: int
) -> None:
    state = start_match_deal(dealer=dealer)
    for _ in range(show_position):
        state = apply_match_action(
            state, legal_action_for_contract(state, Contract.NOLO)
        )
    declarer = state.current_actor
    state = apply_match_action(
        state, legal_action_for_contract(state, Contract.RAMI)
    )
    assert state.active_deal.declarer == declarer  # type: ignore[union-attr]
    assert state.active_deal.first_leader == (declarer - 1) % 4  # type: ignore[union-attr,operator]
    assert state.current_actor == (declarer - 1) % 4  # type: ignore[operator]


def test_shown_card_remains_playable_in_hand() -> None:
    state = resolve_all_nolo(start_match_deal(dealer=0))
    shown = state.active_deal.show_actions[0].shown_card  # type: ignore[union-attr]
    seat = state.active_deal.show_actions[0].seat  # type: ignore[union-attr]
    assert shown in state.active_deal.hands[seat]  # type: ignore[union-attr]


def test_play_action_before_showing_resolves_is_rejected() -> None:
    state = start_match_deal(dealer=0)
    with pytest.raises(WrongPhaseError, match="before showing"):
        apply_match_action(state, PlayCardAction(1, card("D2")))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"seat": True, "shown_card": card("H3"), "declared_contract": Contract.RAMI},
        {"seat": 0, "shown_card": "H3", "declared_contract": Contract.RAMI},
        {"seat": 0, "shown_card": card("H3"), "declared_contract": "RAMI"},
    ],
)
def test_malformed_show_actions_fail_at_construction(kwargs) -> None:
    with pytest.raises(InvalidActionError):
        ShowAction(**kwargs)
