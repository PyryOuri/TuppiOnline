from __future__ import annotations

from dataclasses import FrozenInstanceError, fields, is_dataclass
from enum import Enum

import pytest

from tuppi_engine import (
    DealState,
    ExplicitDeal,
    MatchState,
    PlayerObservation,
    ResearchDealResult,
    RunnerConfigurationError,
    apply_match_action,
    canonical_json_bytes,
    match_observation_for,
    observation_to_data,
)
from tuppi_engine.runner import run_match_input
from tuppi_engine import ExplicitMatchInput, FirstLegalActionAgent
from tuppi_rules import MatchScore
from tuppi_rules import FULL_DECK, Card, Contract, card_to_code

from .conftest import legal_action_for_contract, resolve_all_nolo, start_match_deal


PRIVATE_TYPES = (DealState, MatchState, ExplicitDeal, ResearchDealResult)
ALL_CODES = frozenset(card_to_code(card) for card in FULL_DECK)


def _walk(value, seen=None):
    if seen is None:
        seen = set()
    identity = id(value)
    if identity in seen:
        return
    seen.add(identity)
    yield value
    if isinstance(value, (str, bytes, int, bool, type(None), Enum, Card)):
        return
    if is_dataclass(value) and not isinstance(value, type):
        for item in fields(value):
            yield from _walk(getattr(value, item.name), seen)
    elif isinstance(value, (tuple, list, set, frozenset)):
        for item in value:
            yield from _walk(item, seen)
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _walk(key, seen)
            yield from _walk(item, seen)


def _serialized_card_codes(value) -> set[str]:
    found: set[str] = set()
    if isinstance(value, str) and value in ALL_CODES:
        found.add(value)
    elif isinstance(value, list):
        for item in value:
            found.update(_serialized_card_codes(item))
    elif isinstance(value, dict):
        for item in value.values():
            found.update(_serialized_card_codes(item))
    return found


@pytest.mark.parametrize("seat", range(4))
def test_each_player_observes_exactly_own_hidden_hand(seat: int, suit_hands) -> None:
    state = start_match_deal(hands=suit_hands)
    observation = match_observation_for(state, seat)
    assert observation.own_hand == suit_hands[seat]
    assert observation.observing_seat == seat
    data = observation_to_data(observation)
    assert _serialized_card_codes(data) == {
        card_to_code(card) for card in suit_hands[seat]
    }


@pytest.mark.parametrize("seat", range(4))
def test_private_state_and_other_hands_are_not_reachable(seat: int) -> None:
    observation = match_observation_for(start_match_deal(), seat)
    reachable = tuple(_walk(observation))
    assert not any(isinstance(value, PRIVATE_TYPES) for value in reachable)
    assert all(not callable(value) for value in reachable)
    field_names = {
        item.name
        for value in reachable
        if is_dataclass(value) and not isinstance(value, type)
        for item in fields(value)
    }
    assert "initial_hands" not in field_names
    assert "hands" not in field_names
    assert "deal_id" not in field_names


def test_input_mutation_cannot_change_observation(suit_hands) -> None:
    mutable = [list(hand) for hand in suit_hands]
    state = start_match_deal(hands=mutable)
    observation = match_observation_for(state, 0)
    before = observation.own_hand
    mutable[0].reverse()
    assert observation.own_hand == before
    assert state.active_deal.hands[0] == before  # type: ignore[union-attr]


def test_observation_collections_and_fields_are_immutable() -> None:
    observation = match_observation_for(start_match_deal(), 1)
    with pytest.raises(FrozenInstanceError):
        observation.current_actor = 2  # type: ignore[misc]
    with pytest.raises(TypeError):
        observation.own_hand[0] = observation.own_hand[1]  # type: ignore[index]


def test_public_show_is_visible_without_revealing_rest_of_opponent_hand() -> None:
    state = start_match_deal(dealer=3)
    state = apply_match_action(
        state, legal_action_for_contract(state, Contract.RAMI)
    )
    shown = state.active_deal.show_actions[0]  # type: ignore[union-attr]
    observer = (shown.seat + 1) % 4
    observation = match_observation_for(state, observer)
    assert (shown.seat, shown.shown_card) in observation.publicly_shown_cards
    visible = _serialized_card_codes(observation_to_data(observation))
    allowed = {card_to_code(card) for card in observation.own_hand}
    allowed.add(card_to_code(shown.shown_card))
    assert visible <= allowed
    hidden = set(state.active_deal.hands[shown.seat]) - {shown.shown_card}  # type: ignore[union-attr]
    assert not ({card_to_code(card) for card in hidden} & visible)


def test_played_card_becomes_public_but_unplayed_opponent_cards_remain_hidden() -> None:
    state = resolve_all_nolo(start_match_deal(dealer=0))
    actor = state.current_actor
    action = match_observation_for(state, actor).legal_actions[0]  # type: ignore[arg-type]
    state = apply_match_action(state, action)
    observer = (actor + 2) % 4  # type: ignore[operator]
    observation = match_observation_for(state, observer)
    visible = _serialized_card_codes(observation_to_data(observation))
    played_code = card_to_code(action.card)  # type: ignore[union-attr]
    assert played_code in visible
    opponent_unplayed = state.active_deal.hands[actor]  # type: ignore[index,union-attr]
    public_shows = {card for _, card in observation.publicly_shown_cards}
    hidden_codes = {
        card_to_code(card) for card in opponent_unplayed if card not in public_shows
    }
    assert not (hidden_codes & visible)


def test_observation_generation_is_pure_and_byte_deterministic() -> None:
    state = start_match_deal()
    before = state
    first = match_observation_for(state, 1)
    second = match_observation_for(state, 1)
    assert state == before
    assert first == second
    assert canonical_json_bytes(observation_to_data(first)) == canonical_json_bytes(
        observation_to_data(second)
    )
    assert len(state.public_events) == 1


def test_malicious_formal_agent_receives_only_observation_object() -> None:
    class CapturingAgent:
        captured = None

        def choose_action(self, observation):
            self.captured = observation
            return observation.legal_actions[0]

    state = start_match_deal()
    actor = state.current_actor
    agent = CapturingAgent()
    action = agent.choose_action(match_observation_for(state, actor))  # type: ignore[arg-type]
    state = apply_match_action(state, action)
    assert isinstance(agent.captured, PlayerObservation)
    assert not any(isinstance(value, PRIVATE_TYPES) for value in _walk(agent.captured))
    assert state.phase.value in {"SHOWING", "TRICK_PLAY"}


def test_same_stateful_agent_object_cannot_occupy_multiple_seats(suit_hands) -> None:
    match_input = ExplicitMatchInput(
        match_ref="agent-alias",
        initial_score=MatchScore(),
        initial_dealer=0,
        deals=(ExplicitDeal(dealer=0, hands=suit_hands),),
    )
    shared = FirstLegalActionAgent()
    with pytest.raises(RunnerConfigurationError, match="distinct agent"):
        run_match_input(match_input, (shared, shared, shared, shared))
