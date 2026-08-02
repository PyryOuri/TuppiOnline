from __future__ import annotations

from copy import deepcopy

import pytest

from tuppi_agents import (
    STRATEGIC_PROFILE_KEYS,
    assert_no_foreign_cards,
    construct_agent,
    phase4_specifications_by_profile_key,
)
from tuppi_engine import (
    EnginePhase,
    ExplicitDeal,
    apply_match_action,
    begin_explicit_deal,
    canonical_json_text,
    create_match,
    match_observation_for,
    observation_to_data,
)
from tuppi_rules import Card, Contract, MatchScore, card_to_code

from .conftest import build_position, partition_deck, start_deal


ALL_NOLO = (Contract.NOLO,) * 4
NOLO_THEN_RAMI = (Contract.NOLO, Contract.RAMI)


def _swap_hidden_cards(
    hands: tuple[tuple[Card, ...], ...],
    *,
    observer: int,
    consumed: frozenset[Card],
) -> tuple[tuple[Card, ...], ...]:
    """Swap one unplayed, unshown, same-suit card between two hidden seats.

    Swapping inside a suit preserves every seat's suit counts, so every past
    follow-suit decision stays legal and the resulting full state replays the
    identical public history. The observing seat's own hand is untouched, so its
    observation is identical while the underlying deal - and therefore the
    content-derived deal identifier - differs.
    """

    hidden = [seat for seat in range(4) if seat != observer]
    for index, first in enumerate(hidden):
        for second in hidden[index + 1 :]:
            for left in hands[first]:
                if left in consumed:
                    continue
                for right in hands[second]:
                    if right in consumed or right.suit is not left.suit:
                        continue
                    mutated = [list(hand) for hand in hands]
                    mutated[first][mutated[first].index(left)] = right
                    mutated[second][mutated[second].index(right)] = left
                    return tuple(tuple(hand) for hand in mutated)
    raise AssertionError("no hidden same-suit swap is available in this deal")


def _position(hands, *, plays, show_contracts, match_ref="conformance"):
    state = create_match(
        initial_score=MatchScore(), initial_dealer=0, match_ref=match_ref
    )
    state = begin_explicit_deal(state, ExplicitDeal(dealer=0, hands=hands))
    from .conftest import play_action_for, show_action_for

    for contract in show_contracts:
        state = apply_match_action(state, show_action_for(state, contract))
    for code in plays:
        state = apply_match_action(state, play_action_for(state, code))
    return state


@pytest.mark.parametrize("profile_key", STRATEGIC_PROFILE_KEYS)
def test_information_set_invariance_over_different_full_states(profile_key: str) -> None:
    """Different hidden hands, identical observation, identical behaviour."""

    specification = phase4_specifications_by_profile_key()[profile_key]
    base_hands = partition_deck({})
    original = _position(base_hands, plays=[], show_contracts=ALL_NOLO)
    # Advance a few tricks with the agent itself so the public record is rich.
    agents = tuple(construct_agent(specification, seat=seat) for seat in range(4))
    taken: list = []
    for _ in range(7):
        actor = original.current_actor
        assert actor is not None
        observation = match_observation_for(original, actor)
        action = agents[actor].choose_action(observation)
        taken.append(action)
        original = apply_match_action(original, action)

    observer = original.current_actor
    assert observer is not None
    active = original.active_deal
    assert active is not None
    consumed = (
        frozenset(
            play.card for trick in active.completed_tricks for play in trick.plays
        )
        | frozenset(play.card for play in active.current_trick)
        | frozenset(item.shown_card for item in active.show_actions)
    )
    swapped_hands = _swap_hidden_cards(
        base_hands, observer=observer, consumed=consumed
    )
    assert swapped_hands != base_hands

    alternative = _position(swapped_hands, plays=[], show_contracts=ALL_NOLO)
    for action in taken:
        alternative = apply_match_action(alternative, action)

    assert alternative.active_deal is not None
    assert alternative.active_deal.deal_id != active.deal_id

    first = match_observation_for(original, observer)
    second = match_observation_for(alternative, observer)
    assert observation_to_data(first) == observation_to_data(second)

    agent = construct_agent(specification, seat=observer)
    twin = construct_agent(specification, seat=observer)
    assert agent.choose_action(first) == twin.choose_action(second)
    assert agent.decide(first).diagnostics.to_data() == (
        twin.decide(second).diagnostics.to_data()
    )


@pytest.mark.parametrize("profile_key", STRATEGIC_PROFILE_KEYS)
def test_behaviour_does_not_depend_on_evaluator_metadata(profile_key: str) -> None:
    """Only the observation matters; a different match reference must not."""

    specification = phase4_specifications_by_profile_key()[profile_key]
    hands = partition_deck({})
    left = _position(hands, plays=[], show_contracts=ALL_NOLO, match_ref="alpha-run")
    right = _position(hands, plays=[], show_contracts=ALL_NOLO, match_ref="beta-run")
    for _ in range(5):
        actor = left.current_actor
        assert actor is not None
        first = match_observation_for(left, actor)
        second = match_observation_for(right, actor)
        assert first.match_ref != second.match_ref
        agent = construct_agent(specification, seat=actor)
        twin = construct_agent(specification, seat=actor)
        action = agent.choose_action(first)
        assert action == twin.choose_action(second)
        left = apply_match_action(left, action)
        right = apply_match_action(right, action)


@pytest.mark.parametrize("profile_key", STRATEGIC_PROFILE_KEYS)
def test_behaviour_does_not_depend_on_observation_construction_count(
    profile_key: str,
) -> None:
    specification = phase4_specifications_by_profile_key()[profile_key]
    hands = partition_deck({})
    state = build_position(hands, dealer=0, show_contracts=ALL_NOLO)
    actor = state.current_actor
    assert actor is not None
    agent = construct_agent(specification, seat=actor)
    baseline = agent.choose_action(match_observation_for(state, actor))
    for _ in range(4):
        for seat in range(4):
            match_observation_for(state, seat)
        assert agent.choose_action(match_observation_for(state, actor)) == baseline


@pytest.mark.parametrize("profile_key", STRATEGIC_PROFILE_KEYS)
def test_choosing_an_action_mutates_neither_the_observation_nor_the_state(
    profile_key: str,
) -> None:
    specification = phase4_specifications_by_profile_key()[profile_key]
    hands = partition_deck({})
    state = build_position(hands, dealer=0, show_contracts=ALL_NOLO, plays=[])
    actor = state.current_actor
    assert actor is not None
    observation = match_observation_for(state, actor)
    before_observation = canonical_json_text(observation_to_data(observation))
    before_state = deepcopy(state)
    agent = construct_agent(specification, seat=actor)
    agent.decide(observation, diagnostics=True)
    agent.choose_action(observation)
    assert canonical_json_text(observation_to_data(observation)) == before_observation
    assert state == before_state
    assert state.active_deal.hands == before_state.active_deal.hands


@pytest.mark.parametrize("profile_key", STRATEGIC_PROFILE_KEYS)
def test_diagnostics_never_mention_a_card_the_agent_cannot_see(
    profile_key: str,
) -> None:
    specification = phase4_specifications_by_profile_key()[profile_key]
    hands = partition_deck({})
    state = build_position(hands, dealer=0, show_contracts=())
    agents = tuple(construct_agent(specification, seat=seat) for seat in range(4))
    checked = 0
    while state.phase in (EnginePhase.SHOWING, EnginePhase.TRICK_PLAY):
        actor = state.current_actor
        assert actor is not None
        observation = match_observation_for(state, actor)
        decision = agents[actor].decide(observation, diagnostics=True)
        assert decision.diagnostics is not None
        active = state.active_deal
        assert active is not None
        visible = {card_to_code(item) for item in observation.own_hand}
        visible |= {card_to_code(item) for _, item in observation.publicly_shown_cards}
        visible |= {
            card_to_code(play.card)
            for trick in observation.completed_tricks
            for play in trick.plays
        }
        visible |= {card_to_code(play.card) for play in observation.current_trick}
        foreign = frozenset(
            card_to_code(item)
            for seat in range(4)
            for item in active.hands[seat]
            if card_to_code(item) not in visible
        )
        assert_no_foreign_cards(decision.diagnostics, foreign)
        checked += 1
        state = apply_match_action(state, decision.action)
    assert 53 <= checked <= 56


@pytest.mark.parametrize("profile_key", STRATEGIC_PROFILE_KEYS)
def test_diagnostics_do_not_change_the_selected_action(profile_key: str) -> None:
    specification = phase4_specifications_by_profile_key()[profile_key]
    hands = partition_deck({})
    plain = tuple(construct_agent(specification, seat=seat) for seat in range(4))
    verbose = tuple(construct_agent(specification, seat=seat) for seat in range(4))
    state = start_deal(hands)
    while state.phase in (EnginePhase.SHOWING, EnginePhase.TRICK_PLAY):
        actor = state.current_actor
        assert actor is not None
        observation = match_observation_for(state, actor)
        quiet = plain[actor].choose_action(observation)
        loud = verbose[actor].decide(observation, diagnostics=True)
        assert quiet == loud.action
        state = apply_match_action(state, quiet)


def test_a_policy_refuses_a_non_observation_and_a_foreign_seat() -> None:
    from tuppi_agents.errors import ObservationBoundaryError

    specification = phase4_specifications_by_profile_key()["match_aware_v1"]
    hands = partition_deck({})
    state = build_position(hands, dealer=0, show_contracts=ALL_NOLO)
    actor = state.current_actor
    assert actor is not None
    agent = construct_agent(specification, seat=actor)
    with pytest.raises(ObservationBoundaryError):
        agent.choose_action({"legal_actions": []})  # type: ignore[arg-type]
    other = match_observation_for(state, (actor + 1) % 4)
    with pytest.raises(ObservationBoundaryError):
        agent.choose_action(other)
