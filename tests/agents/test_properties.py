from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from tuppi_agents import (
    LADDER_PROFILE_KEYS,
    STRATEGIC_PROFILE_KEYS,
    PublicInference,
    construct_agent,
    phase4_specifications_by_profile_key,
)
from tuppi_engine import (
    EnginePhase,
    ExplicitDeal,
    PlayCardAction,
    ShowAction,
    apply_match_action,
    begin_explicit_deal,
    create_match,
    match_observation_for,
    observation_to_data,
)
from tuppi_rules import (
    ELIGIBLE_SHOW_RANKS,
    FULL_DECK,
    MatchScore,
    Suit,
    valid_show_cards,
    verbal_declaration_required,
)


SPECIFICATIONS = phase4_specifications_by_profile_key()


def deals() -> st.SearchStrategy[tuple[tuple, ...]]:
    """Generate valid 52-card partitions by permuting the standard deck."""

    return st.permutations(FULL_DECK).map(
        lambda deck: tuple(tuple(deck[seat * 13 : (seat + 1) * 13]) for seat in range(4))
    )


def scores() -> st.SearchStrategy[MatchScore]:
    return st.sampled_from(
        [MatchScore(), MatchScore(20, 0), MatchScore(0, 20), MatchScore(48, 0)]
    )


def _start(hands, *, dealer: int = 0, score: MatchScore | None = None):
    state = create_match(
        initial_score=score or MatchScore(),
        initial_dealer=dealer,
        match_ref="property-run",
    )
    return begin_explicit_deal(state, ExplicitDeal(dealer=dealer, hands=hands))


@given(hands=deals(), key=st.sampled_from(STRATEGIC_PROFILE_KEYS))
@settings(max_examples=12)
def test_every_registered_agent_completes_a_random_deal_legally(hands, key) -> None:
    agents = tuple(construct_agent(SPECIFICATIONS[key], seat=seat) for seat in range(4))
    state = _start(hands)
    actions = 0
    while state.phase in (EnginePhase.SHOWING, EnginePhase.TRICK_PLAY):
        actor = state.current_actor
        assert actor is not None
        observation = match_observation_for(state, actor)
        action = agents[actor].choose_action(observation)
        assert action in observation.legal_actions
        state = apply_match_action(state, action)
        actions += 1
    assert state.phase in (EnginePhase.DEAL_COMPLETE, EnginePhase.MATCH_COMPLETE)
    assert 53 <= actions <= 56
    assert sum(state.completed_deals[-1].public_result.team_tricks) == 13


@given(hands=deals(), key=st.sampled_from(LADDER_PROFILE_KEYS))
@settings(max_examples=8)
def test_a_repeated_identical_observation_yields_an_identical_action(hands, key) -> None:
    agents = tuple(construct_agent(SPECIFICATIONS[key], seat=seat) for seat in range(4))
    state = _start(hands)
    while state.phase in (EnginePhase.SHOWING, EnginePhase.TRICK_PLAY):
        actor = state.current_actor
        assert actor is not None
        observation = match_observation_for(state, actor)
        first = agents[actor].choose_action(observation)
        assert agents[actor].choose_action(observation) == first
        fresh = construct_agent(SPECIFICATIONS[key], seat=actor)
        assert fresh.choose_action(observation) == first
        state = apply_match_action(state, first)


@given(hands=deals(), key=st.sampled_from(LADDER_PROFILE_KEYS))
@settings(max_examples=8)
def test_the_ranking_covers_every_legal_action_and_selects_its_maximum(hands, key) -> None:
    agents = tuple(construct_agent(SPECIFICATIONS[key], seat=seat) for seat in range(4))
    state = _start(hands)
    while state.phase in (EnginePhase.SHOWING, EnginePhase.TRICK_PLAY):
        actor = state.current_actor
        assert actor is not None
        observation = match_observation_for(state, actor)
        ranking = agents[actor].decide(observation, diagnostics=False).scored
        assert [item.action for item in ranking.candidates] == list(
            observation.legal_actions
        )
        best = max(
            ranking.candidates,
            key=lambda item: (tuple(item.score_vector), -item.action_order_index),
        )
        assert ranking.selected_index == best.action_order_index
        assert ranking.action is observation.legal_actions[ranking.selected_index]
        state = apply_match_action(state, ranking.action)


@given(hands=deals())
@settings(max_examples=8)
def test_observations_are_frozen_against_policy_side_effects(hands) -> None:
    agents = tuple(
        construct_agent(SPECIFICATIONS["match_aware_v1"], seat=seat) for seat in range(4)
    )
    state = _start(hands)
    while state.phase in (EnginePhase.SHOWING, EnginePhase.TRICK_PLAY):
        actor = state.current_actor
        assert actor is not None
        observation = match_observation_for(state, actor)
        before = observation_to_data(observation)
        action = agents[actor].choose_action(observation)
        assert observation_to_data(observation) == before
        with pytest.raises(Exception):
            observation.own_hand = ()  # type: ignore[misc]
        state = apply_match_action(state, action)


@given(hands=deals())
@settings(max_examples=8)
def test_public_inference_stays_sound_for_the_whole_deal(hands) -> None:
    agents = tuple(
        construct_agent(SPECIFICATIONS["partner_aware_v1"], seat=seat)
        for seat in range(4)
    )
    state = _start(hands)
    while state.phase in (EnginePhase.SHOWING, EnginePhase.TRICK_PLAY):
        actor = state.current_actor
        assert actor is not None
        observation = match_observation_for(state, actor)
        inference = PublicInference.build(observation)
        active = state.active_deal
        assert active is not None

        for played in inference.played_cards:
            assert inference.possible_owners(played) == frozenset()
            for seat in range(4):
                assert played not in active.hands[seat]

        for seat in range(4):
            for held in active.hands[seat]:
                assert not inference.is_played(held)
                if seat != actor:
                    assert inference.can_seat_hold(seat, held)
                assert not inference.is_seat_void(seat, held.suit)

        for seat in range(4):
            for suit in Suit:
                if inference.is_seat_void(seat, suit):
                    assert not any(
                        held.suit is suit for held in active.hands[seat]
                    ), "an inferred void contradicted the true hand"

        state = apply_match_action(state, agents[actor].choose_action(observation))


@given(hands=deals())
@settings(max_examples=8)
def test_inferred_voids_follow_only_from_public_failure_to_follow(hands) -> None:
    agents = tuple(
        construct_agent(SPECIFICATIONS["public_counting_v1"], seat=seat)
        for seat in range(4)
    )
    state = _start(hands)
    while state.phase in (EnginePhase.SHOWING, EnginePhase.TRICK_PLAY):
        actor = state.current_actor
        assert actor is not None
        observation = match_observation_for(state, actor)
        inference = PublicInference.build(observation)
        witnessed: dict[int, set[Suit]] = {seat: set() for seat in range(4)}
        for trick in observation.completed_tricks:
            led = trick.plays[0].card.suit
            for play in trick.plays:
                if play.card.suit is not led:
                    witnessed[play.seat].add(led)
        if observation.current_trick:
            led = observation.current_trick[0].card.suit
            for play in observation.current_trick:
                if play.card.suit is not led:
                    witnessed[play.seat].add(led)
        exhausted = {
            seat for seat in range(4) if inference.cards_remaining[seat] == 0
        }
        for seat in range(4):
            declared = set(inference.void_suits[seat])
            if seat in exhausted:
                assert declared == set(Suit)
            else:
                assert declared == witnessed[seat]
        state = apply_match_action(state, agents[actor].choose_action(observation))


@given(hands=deals(), key=st.sampled_from(STRATEGIC_PROFILE_KEYS), score=scores())
@settings(max_examples=10)
def test_every_show_action_satisfies_the_target_showing_rules(hands, key, score) -> None:
    agents = tuple(construct_agent(SPECIFICATIONS[key], seat=seat) for seat in range(4))
    state = _start(hands, score=score)
    while state.phase is EnginePhase.SHOWING:
        actor = state.current_actor
        assert actor is not None
        observation = match_observation_for(state, actor)
        action = agents[actor].choose_action(observation)
        assert isinstance(action, ShowAction)
        allowed = valid_show_cards(observation.own_hand, action.declared_contract)
        assert action.shown_card in allowed
        derived = verbal_declaration_required(
            observation.own_hand, action.shown_card, action.declared_contract
        )
        if not derived:
            assert action.shown_card.rank in ELIGIBLE_SHOW_RANKS
        state = apply_match_action(state, action)
    assert state.phase is EnginePhase.TRICK_PLAY


@given(hands=deals(), key=st.sampled_from(LADDER_PROFILE_KEYS))
@settings(max_examples=6)
def test_swapping_hidden_cards_inside_a_suit_cannot_change_behaviour(hands, key) -> None:
    """Changing hidden hands within one information set must be irrelevant."""

    agents = tuple(construct_agent(SPECIFICATIONS[key], seat=seat) for seat in range(4))
    state = _start(hands)
    taken = []
    for _ in range(6):
        actor = state.current_actor
        assert actor is not None
        action = agents[actor].choose_action(match_observation_for(state, actor))
        taken.append(action)
        state = apply_match_action(state, action)

    observer = state.current_actor
    assert observer is not None
    active = state.active_deal
    assert active is not None
    consumed = (
        frozenset(
            play.card for trick in active.completed_tricks for play in trick.plays
        )
        | frozenset(play.card for play in active.current_trick)
        | frozenset(item.shown_card for item in active.show_actions)
    )
    hidden = [seat for seat in range(4) if seat != observer]
    swap = None
    for index, first in enumerate(hidden):
        for second in hidden[index + 1 :]:
            for left in hands[first]:
                if left in consumed:
                    continue
                for right in hands[second]:
                    if right in consumed or right.suit is not left.suit:
                        continue
                    swap = (first, left, second, right)
                    break
                if swap:
                    break
            if swap:
                break
        if swap:
            break
    if swap is None:
        return
    first_seat, left_card, second_seat, right_card = swap
    mutated = [list(hand) for hand in hands]
    mutated[first_seat][mutated[first_seat].index(left_card)] = right_card
    mutated[second_seat][mutated[second_seat].index(right_card)] = left_card
    alternative = _start(tuple(tuple(hand) for hand in mutated))
    for action in taken:
        alternative = apply_match_action(alternative, action)

    original_observation = match_observation_for(state, observer)
    alternative_observation = match_observation_for(alternative, observer)
    assert observation_to_data(original_observation) == observation_to_data(
        alternative_observation
    )
    agent = construct_agent(SPECIFICATIONS[key], seat=observer)
    twin = construct_agent(SPECIFICATIONS[key], seat=observer)
    assert agent.choose_action(original_observation) == twin.choose_action(
        alternative_observation
    )


@given(hands=deals(), key=st.sampled_from(LADDER_PROFILE_KEYS))
@settings(max_examples=6)
def test_selected_play_cards_always_come_from_the_legal_set(hands, key) -> None:
    agents = tuple(construct_agent(SPECIFICATIONS[key], seat=seat) for seat in range(4))
    state = _start(hands)
    while state.phase in (EnginePhase.SHOWING, EnginePhase.TRICK_PLAY):
        actor = state.current_actor
        assert actor is not None
        observation = match_observation_for(state, actor)
        action = agents[actor].choose_action(observation)
        if isinstance(action, PlayCardAction):
            assert action.card in observation.own_hand
            led = (
                observation.current_trick[0].card.suit
                if observation.current_trick
                else None
            )
            if led is not None and any(
                held.suit is led for held in observation.own_hand
            ):
                assert action.card.suit is led
        state = apply_match_action(state, action)
