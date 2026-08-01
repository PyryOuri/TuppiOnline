from __future__ import annotations

import pytest

from tuppi_engine import (
    EnginePhase,
    InvalidActionError,
    PlayCardAction,
    TerminalStateError,
    WrongActorError,
    apply_match_action,
    match_observation_for,
)
from tuppi_rules import Team, team_for_seat

from .conftest import (
    apply_first_legal,
    card,
    resolve_all_nolo,
    round_robin_hands,
    run_first_legal,
    start_match_deal,
)


def _playing_state(*, hands=None, dealer=0):
    return resolve_all_nolo(start_match_deal(hands=hands, dealer=dealer))


def test_correct_first_actor_and_leader_may_play_any_held_card() -> None:
    state = _playing_state(dealer=0)
    observation = match_observation_for(state, 1)
    assert state.current_actor == 1
    assert {action.card for action in observation.legal_actions} == set(
        observation.own_hand
    )


def test_follow_suit_is_enforced_when_possible() -> None:
    state = _playing_state(hands=round_robin_hands(), dealer=0)
    leader = state.current_actor
    leader_hand = state.active_deal.hands[leader]  # type: ignore[index,union-attr]
    follower = (leader + 1) % 4  # type: ignore[operator]
    follower_hand = state.active_deal.hands[follower]  # type: ignore[union-attr]
    lead_card = next(
        card_value
        for card_value in leader_hand
        if any(card.suit is card_value.suit for card in follower_hand)
        and any(card.suit is not card_value.suit for card in follower_hand)
    )
    state = apply_match_action(state, PlayCardAction(leader, lead_card))  # type: ignore[arg-type]
    off_suit = next(card for card in follower_hand if card.suit is not lead_card.suit)
    with pytest.raises(InvalidActionError, match="follow"):
        apply_match_action(state, PlayCardAction(follower, off_suit))
    observation = match_observation_for(state, follower)
    assert observation.legal_actions
    assert all(action.card.suit is lead_card.suit for action in observation.legal_actions)


def test_void_follower_may_discard_any_card() -> None:
    state = _playing_state(dealer=0)
    state = apply_match_action(state, PlayCardAction(1, card("D2")))
    observation = match_observation_for(state, 2)
    assert len(observation.legal_actions) == 13
    state = apply_match_action(state, PlayCardAction(2, card("CA")))
    assert state.active_deal.current_trick[-1].card == card("CA")  # type: ignore[union-attr]


def test_wrong_actor_and_card_not_in_hand_are_rejected() -> None:
    state = _playing_state(dealer=0)
    with pytest.raises(WrongActorError):
        apply_match_action(state, PlayCardAction(2, card("C2")))
    with pytest.raises(InvalidActionError, match="not in"):
        apply_match_action(state, PlayCardAction(1, card("H2")))


def test_duplicate_card_play_is_rejected_after_card_removal() -> None:
    state = _playing_state(dealer=0)
    state = apply_match_action(state, PlayCardAction(1, card("DA")))
    for _ in range(3):
        state = apply_first_legal(state)
    assert state.current_actor == 1
    with pytest.raises(InvalidActionError, match="not in"):
        apply_match_action(state, PlayCardAction(1, card("DA")))


def test_four_cards_complete_trick_and_correct_winner_leads_next() -> None:
    state = _playing_state(dealer=0)
    state = apply_match_action(state, PlayCardAction(1, card("D2")))
    state = apply_match_action(state, PlayCardAction(2, card("CA")))
    state = apply_match_action(state, PlayCardAction(3, card("SA")))
    assert len(state.active_deal.current_trick) == 3  # type: ignore[union-attr]
    state = apply_match_action(state, PlayCardAction(0, card("HA")))
    trick = state.active_deal.completed_tricks[0]  # type: ignore[union-attr]
    assert len(trick.plays) == 4
    assert trick.winner == 1
    assert state.current_actor == 1
    assert state.active_deal.team_tricks == (0, 1)  # type: ignore[union-attr]


def test_card_removal_and_global_conservation_after_every_play() -> None:
    state = _playing_state(dealer=0)
    for expected_played in range(1, 10):
        before = sum(len(hand) for hand in state.active_deal.hands)  # type: ignore[union-attr]
        state = apply_first_legal(state)
        after = sum(len(hand) for hand in state.active_deal.hands)  # type: ignore[union-attr]
        played = sum(
            len(trick.plays) for trick in state.active_deal.completed_tricks  # type: ignore[union-attr]
        ) + len(state.active_deal.current_trick)  # type: ignore[union-attr]
        assert before - after == 1
        assert after + played == 52
        assert played == expected_played


def test_no_early_termination_after_partnership_reaches_seven_tricks() -> None:
    state = _playing_state(dealer=0)
    while max(state.active_deal.team_tricks) < 7:  # type: ignore[union-attr]
        state = apply_first_legal(state)
    assert len(state.active_deal.completed_tricks) == 7  # type: ignore[union-attr]
    assert state.phase is EnginePhase.TRICK_PLAY
    assert sum(len(hand) for hand in state.active_deal.hands) == 24  # type: ignore[union-attr]


def test_exactly_thirteen_tricks_and_no_fourteenth_action() -> None:
    state = run_first_legal(start_match_deal(dealer=0))
    result = state.completed_deals[-1].public_result
    assert len(result.completed_tricks) == 13
    assert sum(result.team_tricks) == 13
    assert sum(len(trick.plays) for trick in result.completed_tricks) == 52
    assert len(
        {play.card for trick in result.completed_tricks for play in trick.plays}
    ) == 52
    with pytest.raises(TerminalStateError):
        apply_match_action(state, PlayCardAction(1, card("D2")))
