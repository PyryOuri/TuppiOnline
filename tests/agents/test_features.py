from __future__ import annotations

import pytest

from tuppi_agents import (
    MatchRole,
    VerbalFallbackCategory,
    build_deal_match_context,
    build_features,
    build_showing_context,
    build_trick_context,
    describe_hand,
    verbal_fallback_category,
)
from tuppi_agents.errors import AgentsValidationError, ObservationBoundaryError
from tuppi_rules import (
    MATCH_TARGET,
    Contract,
    MatchScore,
    Suit,
    Team,
    score_rami,
    transition_rising_score,
)

from .conftest import (
    acting_observation,
    build_position,
    card,
    cards,
    partition_deck,
    suit_of,
)


ALL_NOLO = (Contract.NOLO,) * 4
NOLO_THEN_RAMI = (Contract.NOLO, Contract.RAMI)


def test_hand_descriptors_count_ranks_suits_and_shapes() -> None:
    hand = cards(
        [
            "HA", "HK", "H4",
            "DQ", "DJ", "D10", "D3",
            "C9", "C8", "C7", "C2",
            "SA", "S5",
        ]
    )
    descriptors = describe_hand(hand)
    assert descriptors.card_count == 13
    assert descriptors.high_card_points == 4 + 3 + 2 + 1 + 4
    assert descriptors.aces == 2
    assert descriptors.kings == 1
    assert descriptors.control_cards == 3
    assert descriptors.top_five_count == 6
    assert descriptors.honour_count == 5
    assert descriptors.low_card_count == 3
    assert descriptors.exit_card_count == 3
    assert descriptors.dangerous_high_cards == 4
    assert descriptors.suit_lengths == (3, 4, 4, 2)
    assert descriptors.longest_suit_length == 4
    assert descriptors.shortest_suit_length == 2
    assert descriptors.void_count == 0
    assert descriptors.singleton_count == 0
    assert descriptors.doubleton_count == 1
    assert descriptors.suit_length(Suit.DIAMONDS) == 4


def test_hand_descriptors_reject_non_cards() -> None:
    with pytest.raises(AgentsValidationError):
        describe_hand(())
    with pytest.raises(AgentsValidationError):
        describe_hand(("HA",))  # type: ignore[arg-type]


def test_current_winner_partner_status_and_winning_losing_sets() -> None:
    hands = partition_deck(
        {
            0: ["H9", "H5", "D4"],
            1: ["H10"],
            2: ["HA", "H2", "H3"],
            3: ["H7"],
        }
    )
    # Forehand is seat 1; all four pass NOLO, then seat 1 leads.
    state = build_position(hands, dealer=0, show_contracts=ALL_NOLO, plays=["H10"])
    observation = acting_observation(state)
    assert observation.observing_seat == 2
    trick = build_trick_context(observation)

    assert trick.led_suit is Suit.HEARTS
    assert trick.leader == 1
    assert trick.acting_position == 1
    assert trick.is_leading is False
    assert trick.is_last_to_play is False
    assert trick.seats_still_to_play == (3, 0)
    assert trick.current_winning_seat == 1
    assert trick.current_winning_card == card("H10")
    assert trick.partner_is_winning is False
    assert trick.opponent_is_winning is True
    assert trick.can_follow_suit is True
    assert set(trick.currently_winning_cards) == {card("HA")}
    assert set(trick.currently_losing_cards) == {card("H2"), card("H3")}
    assert trick.lowest_winning_card == card("HA")
    assert trick.highest_winning_card == card("HA")
    assert trick.lowest_losing_card == card("H2")
    assert trick.highest_losing_card == card("H3")
    assert trick.wins_now(card("HA")) is True
    assert trick.overtakes_partner(card("HA")) is False


def test_partner_winning_is_detected_and_overtaking_is_reported() -> None:
    hands = partition_deck({0: ["HK"], 1: ["H4"], 2: ["HA", "H2"], 3: ["H3"]})
    state = build_position(
        hands, dealer=0, show_contracts=ALL_NOLO, plays=["H4", "HA", "H3"]
    )
    observation = acting_observation(state)
    assert observation.observing_seat == 0
    trick = build_trick_context(observation)
    assert trick.current_winning_seat == 2
    assert trick.partner_is_winning is True
    assert trick.opponent_is_winning is False
    assert trick.is_last_to_play is True
    assert trick.seats_still_to_play == ()
    assert trick.overtakes_partner(card("HK")) is False  # HA already beats HK


def test_leading_reports_every_legal_card_as_provisionally_winning() -> None:
    hands = partition_deck({1: ["HA", "S2"]})
    state = build_position(hands, dealer=0, show_contracts=ALL_NOLO)
    observation = acting_observation(state)
    trick = build_trick_context(observation)
    assert trick.is_leading is True
    assert trick.led_suit is None
    assert trick.current_winning_seat is None
    assert set(trick.currently_winning_cards) == set(trick.legal_cards)
    assert trick.currently_losing_cards == ()


def test_showing_context_reports_position_eligibility_and_fallback() -> None:
    hands = partition_deck(
        {1: ["H3", "H4", "D5", "C6", "S7"]},
    )
    state = build_position(hands, dealer=0, show_contracts=())
    observation = acting_observation(state)
    context = build_showing_context(observation)
    assert context.observing_seat == 1
    assert context.dealer == 0
    assert context.forehand == 1
    assert context.showing_position == 0
    assert context.previous_show_actions == ()
    assert context.previous_nolo_count == 0
    assert context.rami_already_resolved is False
    assert card("H3") in context.eligible_rami_show_cards
    assert card("C6") in context.eligible_nolo_show_cards
    assert context.rami_fallback_category is VerbalFallbackCategory.DIRECT_COLOR_CARD
    assert context.nolo_fallback_category is VerbalFallbackCategory.DIRECT_COLOR_CARD
    assert context.verbal_required(Contract.RAMI) is False


def test_showing_context_after_one_nolo_show_tracks_history() -> None:
    hands = partition_deck({})
    state = build_position(hands, dealer=0, show_contracts=(Contract.NOLO,))
    context = build_showing_context(acting_observation(state))
    assert context.showing_position == 1
    assert context.previous_nolo_count == 1
    assert len(context.previous_show_actions) == 1
    assert context.rami_already_resolved is False


def test_verbal_fallback_categories_cover_all_three_branches() -> None:
    red_eligible = cards(["H3", "SA", "SK"])
    assert (
        verbal_fallback_category(red_eligible, Contract.RAMI)
        is VerbalFallbackCategory.DIRECT_COLOR_CARD
    )
    black_only = cards(["C3", "HA", "HK"])
    assert (
        verbal_fallback_category(black_only, Contract.RAMI)
        is VerbalFallbackCategory.ELIGIBLE_OFF_COLOR
    )
    assert (
        verbal_fallback_category(black_only, Contract.NOLO)
        is VerbalFallbackCategory.DIRECT_COLOR_CARD
    )
    no_eligible = cards(["HA", "HK", "H2", "SJ"])
    for contract in (Contract.RAMI, Contract.NOLO):
        assert (
            verbal_fallback_category(no_eligible, contract)
            is VerbalFallbackCategory.NO_ELIGIBLE_RANK
        )


def test_match_role_table_up_and_down() -> None:
    hands = partition_deck({})
    at_table = build_deal_match_context(
        acting_observation(build_position(hands, show_contracts=ALL_NOLO))
    )
    assert at_table.match_role is MatchRole.TABLE
    assert at_table.up_team is None
    assert at_table.down_team_win_resets_score is False
    assert at_table.margin_has_match_value is True

    up = build_deal_match_context(
        acting_observation(
            build_position(hands, score=MatchScore(20, 0), show_contracts=ALL_NOLO)
        )
    )
    assert up.acting_team is Team.TEAM_1  # forehand seat 1 leads an all-NOLO deal
    assert up.match_role is MatchRole.DOWN
    assert up.down_team_win_resets_score is True
    assert up.margin_has_match_value is False
    assert up.up_team_distance_to_target == MATCH_TARGET - 20


def test_terminal_distance_and_reachable_outcomes_in_nolo() -> None:
    hands = partition_deck({})
    state = build_position(hands, score=MatchScore(0, 48), show_contracts=ALL_NOLO)
    context = build_deal_match_context(acting_observation(state))
    assert context.contract is Contract.NOLO
    assert context.acting_team is Team.TEAM_1
    assert context.match_role is MatchRole.UP
    assert context.own_distance_to_target == 4
    assert context.own_win_requires_at_most_tricks == 6
    assert context.own_win_requires_at_least_tricks is None
    # Winning NOLO with t tricks pays 4*(7-t) for t in 0..6.
    assert context.reachable_own_win_points == tuple(
        sorted({4 * (7 - t) for t in range(0, 7)})
    )
    assert context.own_minimum_win_points == 4
    assert context.own_maximum_win_points == 28
    assert context.own_win_can_end_match is True
    assert context.own_minimum_win_ends_match is True
    assert context.margin_has_match_value is True
    assert context.margin_beyond_minimum_has_match_value is False
    assert context.trick_reward_sign == -1
    assert context.trick_point_scale == 4
    assert context.marginal_own_trick_value == -4.0


def test_rami_declaring_and_defending_trick_rewards_differ() -> None:
    hands = partition_deck({})
    state = build_position(hands, dealer=0, show_contracts=NOLO_THEN_RAMI)
    # Forehand seat 1 passes NOLO, seat 2 declares RAMI, so team 0 declares.
    declarer_view = build_deal_match_context(acting_observation(state))
    assert declarer_view.contract is Contract.RAMI
    assert declarer_view.declaring_team is Team.TEAM_0
    assert declarer_view.own_win_requires_at_least_tricks == 7
    assert declarer_view.own_win_requires_at_most_tricks is None
    if declarer_view.acting_team is Team.TEAM_0:
        assert declarer_view.trick_point_scale == 4
    else:
        assert declarer_view.trick_point_scale == 8
    assert declarer_view.marginal_own_trick_value > 0


def test_down_team_win_of_fifty_six_points_still_only_resets() -> None:
    """A 56-point stolen RAMI by the non-rising side yields a reset, not a win."""

    stolen = score_rami(Team.TEAM_0, 0, 13)
    assert stolen.points == 56
    assert stolen.winner_team is Team.TEAM_1
    assert stolen.stolen_rami is True
    after = transition_rising_score(MatchScore(48, 0), stolen)
    assert after == MatchScore(0, 0)

    hands = partition_deck({})
    state = build_position(hands, score=MatchScore(48, 0), show_contracts=NOLO_THEN_RAMI)
    context = build_deal_match_context(acting_observation(state))
    if context.match_role is MatchRole.DOWN:
        assert context.own_win_can_end_match is False
        assert context.margin_has_match_value is False
        assert context.down_team_win_resets_score is True


def test_features_require_the_acting_seat_and_a_supported_phase() -> None:
    hands = partition_deck({})
    state = build_position(hands, show_contracts=ALL_NOLO)
    observation = acting_observation(state)
    features = build_features(observation, include_inference=True)
    assert features.inference is not None
    assert features.showing is None
    assert features.trick is not None

    without = build_features(observation, include_inference=False)
    assert without.inference is None
    with pytest.raises(AgentsValidationError):
        without.require_inference()

    from tuppi_engine import match_observation_for

    other = match_observation_for(state, (observation.observing_seat + 1) % 4)
    with pytest.raises(AgentsValidationError):
        build_features(other, include_inference=False)


def test_features_reject_non_observations() -> None:
    with pytest.raises(ObservationBoundaryError):
        build_features({"phase": "SHOWING"}, include_inference=False)  # type: ignore[arg-type]


def test_feature_layer_exposes_only_team_trick_totals() -> None:
    """Partners must optimise team utility; no per-seat trick reward exists."""

    hands = partition_deck({})
    state = build_position(hands, show_contracts=ALL_NOLO)
    context = build_deal_match_context(acting_observation(state))
    fields = set(context.__slots__)
    assert "team_tricks" in fields
    assert not any("seat_tricks" in name or "player_tricks" in name for name in fields)
    assert context.own_team_tricks + context.opponent_team_tricks == context.tricks_completed


def test_suit_helper_rejects_bad_input() -> None:
    hands = partition_deck({})
    features = build_features(
        acting_observation(build_position(hands, show_contracts=ALL_NOLO)),
        include_inference=False,
    )
    with pytest.raises(AgentsValidationError):
        features.hand.suit_length("hearts")  # type: ignore[arg-type]
    assert features.hand.suit_length(suit_of("H")) >= 0
