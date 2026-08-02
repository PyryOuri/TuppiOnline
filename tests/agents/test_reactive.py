from __future__ import annotations

import pytest

from tuppi_agents import build_features, require_profile
from tuppi_agents.reactive import score_reactive_play
from tuppi_engine import PlayCardAction, ShowAction
from tuppi_rules import Contract

from .conftest import acting_observation, build_position, card, partition_deck, policy


ALL_NOLO = (Contract.NOLO,) * 4
NOLO_THEN_RAMI = (Contract.NOLO, Contract.RAMI)
KEY = "reactive_contract_v1"


def _chosen(state) -> str:
    observation = acting_observation(state)
    agent = policy(KEY, seat=observation.observing_seat)
    action = agent.choose_action(observation)
    assert isinstance(action, PlayCardAction)
    assert action in observation.legal_actions
    return action.card.to_code()


def _ranking(state):
    observation = acting_observation(state)
    profile = require_profile(KEY)
    features = build_features(observation, include_inference=False)
    return score_reactive_play(observation, features, profile)


# ------------------------------------------------------------ capability bounds


def test_the_reactive_profile_declares_no_inference_and_no_partner_rules() -> None:
    profile = require_profile(KEY)
    assert profile.uses_public_inference is False
    assert profile.uses_partner_rules is False
    assert profile.match_state_enabled is False
    assert not any(rule.startswith("counting.") for rule in profile.enabled_rule_ids)
    assert not any(rule.startswith("partner.") for rule in profile.enabled_rule_ids)
    assert not any(rule.startswith("match.") for rule in profile.enabled_rule_ids)


def test_reactive_features_are_built_without_public_inference() -> None:
    hands = partition_deck({})
    features = build_features(
        acting_observation(build_position(hands, show_contracts=ALL_NOLO)),
        include_inference=require_profile(KEY).uses_public_inference,
    )
    assert features.inference is None


# ------------------------------------------------------------------ RAMI play


def test_rami_takes_the_trick_with_the_cheapest_winning_card() -> None:
    hands = partition_deck(
        {1: ["H10"], 2: ["H5", "HJ", "HA"]}, forbid={2: ["H"]}
    )
    state = build_position(
        hands, dealer=0, show_contracts=NOLO_THEN_RAMI, plays=["H10"]
    )
    assert acting_observation(state).observing_seat == 2
    assert _chosen(state) == "JH"


def test_rami_preserves_strength_when_no_card_can_win() -> None:
    hands = partition_deck({1: ["HA"], 2: ["H5", "H9"]}, forbid={2: ["H"]})
    state = build_position(
        hands, dealer=0, show_contracts=NOLO_THEN_RAMI, plays=["HA"]
    )
    assert _chosen(state) == "5H"


def test_rami_avoids_overtaking_a_winning_partner() -> None:
    hands = partition_deck(
        {1: ["HQ"], 2: ["H3"], 3: ["H2", "HK"]}, forbid={3: ["H"]}
    )
    state = build_position(
        hands, dealer=0, show_contracts=NOLO_THEN_RAMI, plays=["HQ", "H3"]
    )
    observation = acting_observation(state)
    assert observation.observing_seat == 3
    assert observation.partner_seat == 1
    assert _chosen(state) == "2H"


def test_rami_overtakes_when_an_opponent_holds_the_trick() -> None:
    hands = partition_deck(
        {1: ["H4"], 2: ["HQ"], 3: ["H2", "HK"]}, forbid={3: ["H"]}
    )
    state = build_position(
        hands, dealer=0, show_contracts=NOLO_THEN_RAMI, plays=["H4", "HQ"]
    )
    observation = acting_observation(state)
    assert observation.observing_seat == 3
    # Seat 2 is an opponent of seat 3 and currently holds the trick.
    assert _chosen(state) == "KH"


def test_rami_lead_uses_the_documented_best_suit_rule() -> None:
    hand = [
        "H2", "H3", "H4", "H5", "H6",
        "D2", "D3", "D4",
        "C2", "C3", "C4",
        "SA", "SK",
    ]
    hands = partition_deck({1: hand})
    state = build_position(hands, dealer=0, show_contracts=NOLO_THEN_RAMI)
    observation = acting_observation(state)
    assert observation.observing_seat == 1
    assert observation.current_trick == ()
    # Spades score 4+3 honour weight plus 0.5*2 length = 8.0, the best suit.
    assert _chosen(state) == "AS"


def test_rami_discards_the_lowest_card_when_void_in_the_led_suit() -> None:
    hand = [
        "D2", "D3", "D4", "D5",
        "C2", "C3", "C4", "C5",
        "S2", "S3", "S4", "S5", "SA",
    ]
    hands = partition_deck({1: ["HA"], 2: hand}, forbid={2: ["H"]})
    state = build_position(
        hands, dealer=0, show_contracts=NOLO_THEN_RAMI, plays=["HA"]
    )
    assert _chosen(state) == "2D"


# ------------------------------------------------------------------ NOLO play


def test_nolo_prefers_the_highest_card_that_still_loses() -> None:
    hands = partition_deck({1: ["HK"], 2: ["H2", "H9", "HA"]}, forbid={2: ["H"]})
    state = build_position(hands, dealer=0, show_contracts=ALL_NOLO, plays=["HK"])
    assert _chosen(state) == "9H"


def test_nolo_forced_to_win_from_the_last_seat_purges_its_highest_card() -> None:
    hands = partition_deck(
        {1: ["H2"], 2: ["H3"], 3: ["H4"], 0: ["H5", "HA"]}, forbid={0: ["H"]}
    )
    state = build_position(
        hands, dealer=0, show_contracts=ALL_NOLO, plays=["H2", "H3", "H4"]
    )
    observation = acting_observation(state)
    assert observation.observing_seat == 0
    assert _chosen(state) == "AH"


def test_nolo_forced_to_win_from_an_early_seat_keeps_the_trick_cheap() -> None:
    hands = partition_deck({1: ["H2"], 2: ["H5", "HA"]}, forbid={2: ["H"]})
    state = build_position(hands, dealer=0, show_contracts=ALL_NOLO, plays=["H2"])
    observation = acting_observation(state)
    assert observation.observing_seat == 2
    assert _chosen(state) == "5H"


def test_nolo_discards_the_highest_liability_card_when_void() -> None:
    hand = [
        "D2", "D3", "D4", "D5",
        "C2", "C3", "C4", "C5",
        "S2", "S3", "S4", "S5", "SA",
    ]
    hands = partition_deck({1: ["H7"], 2: hand}, forbid={2: ["H"]})
    state = build_position(hands, dealer=0, show_contracts=ALL_NOLO, plays=["H7"])
    assert _chosen(state) == "AS"


def test_nolo_lead_uses_the_documented_low_short_rule() -> None:
    hand = [
        "H2",
        "D2", "D3",
        "C3", "C4", "C5", "C6", "C7",
        "S3", "S4", "S5", "S6", "S7",
    ]
    hands = partition_deck({1: hand})
    state = build_position(hands, dealer=0, show_contracts=ALL_NOLO)
    # Rank 2 ties between H2 and D2; hearts is the shorter suit.
    assert _chosen(state) == "2H"


# ------------------------------------------------------- ranking and tie-breaks


def test_every_legal_action_is_ranked_exactly_once() -> None:
    hands = partition_deck({})
    state = build_position(hands, dealer=0, show_contracts=ALL_NOLO)
    observation = acting_observation(state)
    ranking = _ranking(state)
    assert len(ranking.candidates) == len(observation.legal_actions)
    assert [item.action for item in ranking.candidates] == list(
        observation.legal_actions
    )
    assert len({item.action_order_index for item in ranking.candidates}) == len(
        observation.legal_actions
    )


def test_selection_is_the_lexicographic_maximum_with_index_tie_break() -> None:
    hands = partition_deck({})
    state = build_position(hands, dealer=0, show_contracts=ALL_NOLO)
    ranking = _ranking(state)
    best = max(tuple(item.score_vector) for item in ranking.candidates)
    tied = [
        item.action_order_index
        for item in ranking.candidates
        if tuple(item.score_vector) == best
    ]
    assert ranking.selected_index == min(tied)
    assert ranking.selected.action is ranking.action


def test_repeated_identical_observations_give_the_identical_action() -> None:
    hands = partition_deck({})
    state = build_position(hands, dealer=0, show_contracts=ALL_NOLO, plays=[])
    observation = acting_observation(state)
    agent = policy(KEY, seat=observation.observing_seat)
    first = agent.choose_action(observation)
    for _ in range(5):
        assert agent.choose_action(observation) == first


def test_two_independently_constructed_agents_agree() -> None:
    hands = partition_deck({})
    state = build_position(hands, dealer=0, show_contracts=ALL_NOLO)
    observation = acting_observation(state)
    left = policy(KEY, seat=observation.observing_seat)
    right = policy(KEY, seat=observation.observing_seat)
    assert left is not right
    assert left.choose_action(observation) == right.choose_action(observation)


# ---------------------------------------------------------------------- showing


def test_reactive_showing_uses_the_simple_profile_and_a_legal_card() -> None:
    hands = partition_deck({})
    state = build_position(hands, dealer=0, show_contracts=())
    observation = acting_observation(state)
    action = policy(KEY, seat=observation.observing_seat).choose_action(observation)
    assert isinstance(action, ShowAction)
    assert action in observation.legal_actions
    assert require_profile(KEY).showing_policy.value == "simple_show_v1"


def test_reactive_declares_rami_only_above_its_threshold() -> None:
    strong = [
        "HA", "HK", "HQ", "H3",
        "DA", "DK", "DQ", "D4",
        "CA", "CK", "C5",
        "SA", "S6",
    ]
    hands = partition_deck({1: strong})
    state = build_position(hands, dealer=0, show_contracts=())
    observation = acting_observation(state)
    action = policy(KEY, seat=1).choose_action(observation)
    assert isinstance(action, ShowAction)
    assert action.declared_contract is Contract.RAMI

    weak = [
        "H2", "H3", "H4",
        "D2", "D3", "D4",
        "C2", "C3", "C4",
        "S2", "S3", "S4", "S5",
    ]
    hands = partition_deck({1: weak})
    state = build_position(hands, dealer=0, show_contracts=())
    observation = acting_observation(state)
    action = policy(KEY, seat=1).choose_action(observation)
    assert isinstance(action, ShowAction)
    assert action.declared_contract is Contract.NOLO


def test_shown_card_is_the_lowest_eligible_card_of_the_wanted_colour() -> None:
    strong = [
        "HA", "HK", "HQ", "H7", "H5",
        "DA", "DK", "DQ", "D4",
        "CA", "CK",
        "SA", "S6",
    ]
    hands = partition_deck({1: strong})
    state = build_position(hands, dealer=0, show_contracts=())
    observation = acting_observation(state)
    action = policy(KEY, seat=1).choose_action(observation)
    assert action.declared_contract is Contract.RAMI
    # Eligible red ranks are D4, H5, H7; the lowest is D4.
    assert action.shown_card == card("D4")
