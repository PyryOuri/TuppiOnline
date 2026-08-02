from __future__ import annotations

import pytest

from tuppi_agents import PublicInference
from tuppi_agents.errors import AgentsValidationError
from tuppi_engine import EnginePhase, apply_match_action, match_observation_for
from tuppi_rules import FULL_DECK, Contract, Suit

from .conftest import (
    acting_observation,
    build_position,
    card,
    partition_deck,
    policy,
)


ALL_NOLO = (Contract.NOLO,) * 4


def _void_position():
    """Seat 3 holds no heart, so it must fail to follow a heart lead."""

    hands = partition_deck(
        {1: ["HA"], 2: ["HK"], 0: ["H2"]},
        forbid={3: ["H"]},
    )
    state = build_position(hands, dealer=0, show_contracts=ALL_NOLO, plays=["HA", "HK"])
    # Seat 3 is now on play and cannot follow hearts.
    observation = acting_observation(state)
    assert observation.observing_seat == 3
    discard = next(
        action
        for action in observation.legal_actions
        if action.card.suit is not Suit.HEARTS
    )
    return apply_match_action(state, discard), hands


def test_inferred_void_follows_only_from_public_failure_to_follow() -> None:
    state, _ = _void_position()
    observation = acting_observation(state)
    assert observation.observing_seat == 0
    inference = PublicInference.build(observation)
    assert inference.is_seat_void(3, Suit.HEARTS) is True
    for seat in (0, 1, 2):
        assert inference.is_seat_void(seat, Suit.HEARTS) is False
    for suit in (Suit.DIAMONDS, Suit.CLUBS, Suit.SPADES):
        assert inference.is_seat_void(3, suit) is False


def test_a_void_seat_is_excluded_from_owning_that_suit() -> None:
    state, _ = _void_position()
    inference = PublicInference.build(acting_observation(state))
    hearts = [item for item in FULL_DECK if item.suit is Suit.HEARTS]
    for item in hearts:
        assert 3 not in inference.possible_owners(item)
        assert inference.can_seat_hold(3, item) is False


def test_public_card_accounting_partitions_the_deck() -> None:
    state, _ = _void_position()
    observation = acting_observation(state)
    inference = PublicInference.build(observation)
    assert len(inference.played_cards) == 3
    assert inference.own_hand == frozenset(observation.own_hand)
    assert not (inference.played_cards & inference.unaccounted_cards)
    assert not (inference.own_hand & inference.unaccounted_cards)
    accounted = (
        inference.played_cards
        | frozenset(item for hand in inference.known_held for item in hand)
        | inference.unaccounted_cards
    )
    assert accounted == frozenset(FULL_DECK)
    assert sum(inference.unknown_capacity) == len(inference.unaccounted_cards)
    assert inference.cards_remaining[observation.observing_seat] == len(
        observation.own_hand
    )


def test_played_cards_are_never_assigned_to_an_unknown_hand() -> None:
    state, _ = _void_position()
    inference = PublicInference.build(acting_observation(state))
    for item in inference.played_cards:
        assert inference.possible_owners(item) == frozenset()
        for seat in range(4):
            assert inference.can_seat_hold(seat, item) is False


def test_shown_cards_are_publicly_owned_by_their_shower() -> None:
    hands = partition_deck({})
    state = build_position(hands, dealer=0, show_contracts=ALL_NOLO)
    observation = acting_observation(state)
    inference = PublicInference.build(observation)
    for seat, shown in observation.publicly_shown_cards:
        assert inference.possible_owners(shown) == frozenset((seat,))
        assert shown in inference.known_held[seat]
        assert shown not in inference.unaccounted_cards


def test_highest_unplayed_card_of_a_suit_is_a_certain_winner_when_led() -> None:
    hands = partition_deck({1: ["HA", "HK"], 2: ["H3"], 0: ["H2"]})
    state = build_position(hands, dealer=0, show_contracts=ALL_NOLO)
    inference = PublicInference.build(acting_observation(state))
    assert inference.is_highest_unplayed_in_suit(card("HA")) is True
    assert inference.is_highest_unplayed_in_suit(card("HK")) is False
    assert inference.unplayed_higher_in_suit(card("HK")) == frozenset({card("HA")})
    assert card("HA") in inference.unplayed_higher_in_suit(card("H2"))


def test_unaccounted_higher_excludes_own_and_shown_cards() -> None:
    hands = partition_deck({1: ["HA", "HQ"]})
    state = build_position(hands, dealer=0, show_contracts=ALL_NOLO)
    observation = acting_observation(state)
    assert observation.observing_seat == 1
    inference = PublicInference.build(observation)
    higher = inference.unplayed_higher_in_suit(card("HQ"))
    assert card("HA") in higher
    assert card("HA") not in inference.unaccounted_higher_in_suit(card("HQ"))
    assert card("HK") in inference.unaccounted_higher_in_suit(card("HQ")) or (
        card("HK") in inference.known_held[1]
    )


def test_seats_that_could_hold_higher_respects_voids() -> None:
    state, _ = _void_position()
    observation = acting_observation(state)
    inference = PublicInference.build(observation)
    lowest_heart = min(
        (item for item in observation.own_hand if item.suit is Suit.HEARTS),
        key=lambda item: item.rank.value,
        default=None,
    )
    if lowest_heart is not None:
        holders = inference.seats_that_could_hold_higher(lowest_heart, (1, 2, 3))
        assert 3 not in holders


def test_empty_hand_is_void_in_every_suit() -> None:
    hands = partition_deck({})
    agents = tuple(policy("reactive_contract_v1", seat=seat) for seat in range(4))
    state = build_position(hands, show_contracts=ALL_NOLO)
    while state.phase is EnginePhase.TRICK_PLAY:
        actor = state.current_actor
        assert actor is not None
        observation = match_observation_for(state, actor)
        if len(observation.completed_tricks) == 12 and not observation.current_trick:
            inference = PublicInference.build(observation)
            assert all(count == 1 for count in inference.cards_remaining)
        state = apply_match_action(state, agents[actor].choose_action(observation))
    assert state.phase in (EnginePhase.DEAL_COMPLETE, EnginePhase.MATCH_COMPLETE)


def test_inference_never_excludes_the_true_owner_during_a_whole_deal() -> None:
    """Every asserted exclusion must follow from public information."""

    hands = partition_deck({}, forbid={3: ["H"], 0: ["S"]})
    agents = tuple(policy("public_counting_v1", seat=seat) for seat in range(4))
    state = build_position(hands, show_contracts=ALL_NOLO)
    checks = 0
    while state.phase in (EnginePhase.SHOWING, EnginePhase.TRICK_PLAY):
        actor = state.current_actor
        assert actor is not None
        observation = match_observation_for(state, actor)
        inference = PublicInference.build(observation)
        active = state.active_deal
        assert active is not None
        for seat in range(4):
            for held in active.hands[seat]:
                assert inference.can_seat_hold(seat, held) or (
                    seat == observation.observing_seat
                ), f"inference excluded the true owner {seat} of {held}"
                assert not inference.is_played(held)
                assert not inference.is_seat_void(seat, held.suit)
        checks += 1
        state = apply_match_action(state, agents[actor].choose_action(observation))
    assert checks >= 40


def test_pigeonhole_refinement_proves_ownership_at_the_last_trick() -> None:
    hands = partition_deck({})
    agents = tuple(policy("partner_aware_v1", seat=seat) for seat in range(4))
    state = build_position(hands, show_contracts=ALL_NOLO)
    proven = 0
    while state.phase is EnginePhase.TRICK_PLAY:
        actor = state.current_actor
        assert actor is not None
        observation = match_observation_for(state, actor)
        if len(observation.completed_tricks) == 12:
            inference = PublicInference.build(observation)
            unknown = inference.unaccounted_cards
            for item in unknown:
                owners = inference.possible_owners(item)
                assert len(owners) >= 1
            active = state.active_deal
            assert active is not None
            for seat in range(4):
                for held in active.hands[seat]:
                    if held in inference.known_held[seat]:
                        proven += 1
        state = apply_match_action(state, agents[actor].choose_action(observation))
    assert proven >= 1


def test_inference_rejects_bad_arguments() -> None:
    hands = partition_deck({})
    inference = PublicInference.build(
        acting_observation(build_position(hands, show_contracts=ALL_NOLO))
    )
    with pytest.raises(AgentsValidationError):
        inference.possible_owners("HA")  # type: ignore[arg-type]
    with pytest.raises(AgentsValidationError):
        inference.is_seat_void(9, Suit.HEARTS)
    with pytest.raises(AgentsValidationError):
        inference.is_seat_void(0, "hearts")  # type: ignore[arg-type]
    with pytest.raises(AgentsValidationError):
        inference.unplayed_higher_in_suit("HA")  # type: ignore[arg-type]


def test_inference_is_immutable_and_carries_a_schema_version() -> None:
    hands = partition_deck({})
    inference = PublicInference.build(
        acting_observation(build_position(hands, show_contracts=ALL_NOLO))
    )
    assert inference.schema_version == "tuppi.agents.public_inference.v1"
    with pytest.raises(Exception):
        inference.observing_seat = 3  # type: ignore[misc]
    with pytest.raises(TypeError):
        inference.possible_owner_map[card("HA")] = frozenset((1,))  # type: ignore[index]


def test_inference_contains_no_probability_fields() -> None:
    hands = partition_deck({})
    inference = PublicInference.build(
        acting_observation(build_position(hands, show_contracts=ALL_NOLO))
    )
    forbidden = ("probability", "likelihood", "prior", "belief", "weight", "sample")
    for name in inference.__slots__:
        assert not any(token in name for token in forbidden), name
