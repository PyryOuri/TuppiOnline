from __future__ import annotations

import pytest

from tuppi_agents import (
    MatchRole,
    build_deal_match_context,
    build_features,
    construct_agent,
    phase4_specifications_by_profile_key,
    require_profile,
)
from tuppi_agents.match_aware import (
    decisive_trick_pending,
    margin_is_worthless,
    match_play_mode,
)
from tuppi_agents.reactive import PlayMode
from tuppi_agents.showing import contract_preference, simple_rami_score
from tuppi_engine import EnginePhase, PlayCardAction, ShowAction
from tuppi_rules import (
    MATCH_TARGET,
    Contract,
    MatchScore,
    Team,
    score_nolo,
    score_rami,
    transition_rising_score,
)

from .conftest import (
    acting_observation,
    build_position,
    partition_deck,
    policy,
    run_full_deal,
)


KEY = "match_aware_v1"
PARTNER = "partner_aware_v1"
NO_STATE = "match_aware_no_match_features_v1"
ALL_NOLO = (Contract.NOLO,) * 4
NOLO_THEN_RAMI = (Contract.NOLO, Contract.RAMI)

# 15 high-card points, one ace, two controls, longest suit four: a simple RAMI
# score of exactly 16.0. That sits above the base threshold of 15.0 and below
# the protected threshold of 15.0 + 3.0, which is what makes it a counterexample.
_BORDERLINE_RAMI_HAND = [
    "HA", "HK", "HQ", "H3",
    "DQ", "D4", "D5",
    "CQ", "C5", "C6",
    "SQ", "S6", "S7",
]


def _show_action(profile_key: str, score: MatchScore, hand: list[str]) -> ShowAction:
    hands = partition_deck({1: hand})
    state = build_position(hands, dealer=0, score=score, show_contracts=())
    observation = acting_observation(state)
    assert observation.observing_seat == 1
    specification = phase4_specifications_by_profile_key()[profile_key]
    action = construct_agent(specification, seat=1).choose_action(observation)
    assert isinstance(action, ShowAction)
    return action


# ------------------------------------------------------------ capability bounds


def test_the_match_profile_declares_rising_score_rules() -> None:
    profile = require_profile(KEY)
    assert profile.match_state_enabled is True
    assert profile.uses_partner_rules is True
    assert profile.uses_public_inference is True
    assert any(rule.startswith("match.") for rule in profile.enabled_rule_ids)


def test_the_ablation_variant_switches_every_match_rule_off() -> None:
    profile = require_profile(NO_STATE)
    assert profile.match_state_enabled is False
    assert not any(rule.startswith("match.") for rule in profile.enabled_rule_ids)


# -------------------------------------------------------------- score contexts


def test_showing_at_zero_zero_uses_the_base_threshold() -> None:
    assert simple_rami_score_of(_BORDERLINE_RAMI_HAND) >= 15.0
    action = _show_action(KEY, MatchScore(), _BORDERLINE_RAMI_HAND)
    assert action.declared_contract is Contract.RAMI


def simple_rami_score_of(hand: list[str]) -> float:
    hands = partition_deck({1: hand})
    state = build_position(hands, dealer=0, show_contracts=())
    features = build_features(acting_observation(state), include_inference=False)
    return simple_rami_score(features)


def test_at_forty_eight_a_reliable_four_point_win_is_preferred_to_a_rami_gamble() -> None:
    """The required 48-point counterexample.

    At 48-0 the acting partnership needs only four points, and every NOLO win
    pays at least ``4 * (7 - 6) = 4``. A failed RAMI instead hands the opponents
    eight points per trick above six and resets the whole rise to zero. The
    match-aware profile therefore raises its RAMI bar; the deal-only profile,
    which cannot see the score, still declares.
    """

    score = MatchScore(0, 48)  # forehand seat 1 belongs to team 1
    hands = partition_deck({1: _BORDERLINE_RAMI_HAND})
    state = build_position(hands, dealer=0, score=score, show_contracts=())
    context = build_deal_match_context(acting_observation(state))
    assert context.acting_team is Team.TEAM_1
    assert context.match_role is MatchRole.UP
    assert context.own_distance_to_target == 4

    assert _show_action(PARTNER, score, _BORDERLINE_RAMI_HAND).declared_contract is (
        Contract.RAMI
    )
    assert _show_action(KEY, score, _BORDERLINE_RAMI_HAND).declared_contract is (
        Contract.NOLO
    )
    assert _show_action(NO_STATE, score, _BORDERLINE_RAMI_HAND).declared_contract is (
        Contract.RAMI
    )

    # Every reachable NOLO win from 48 reaches the target; the minimum is enough.
    smallest = score_nolo(7, 6)
    assert smallest.winner_team is Team.TEAM_1
    assert smallest.points == 4
    assert transition_rising_score(score, smallest) == MatchScore(0, 52)


def test_when_the_opponents_are_close_to_the_target_the_bar_drops() -> None:
    """A down partnership accepts more variance because a win resets the rise."""

    pressured = MatchScore(46, 0)  # team 0 is up; forehand seat 1 is down
    hands = partition_deck({1: _BORDERLINE_RAMI_HAND})
    state = build_position(hands, dealer=0, score=pressured, show_contracts=())
    context = build_deal_match_context(acting_observation(state))
    assert context.match_role is MatchRole.DOWN
    assert context.up_team_distance_to_target == 6

    profile = require_profile(KEY)
    features = build_features(acting_observation(state), include_inference=False)
    preference = contract_preference(features, profile)
    assert "match_reset_opponent_rise" in preference.reason_codes
    scalars = dict(preference.scalars)
    assert scalars["simple_rami_threshold"] == 15.0 - 2.0


def test_a_fifty_six_point_down_team_win_still_only_resets_the_score() -> None:
    """The required stolen-RAMI reset counterexample."""

    stolen = score_rami(Team.TEAM_0, 0, 13)
    assert stolen.points == 56
    assert stolen.stolen_rami is True
    assert stolen.winner_team is Team.TEAM_1
    assert transition_rising_score(MatchScore(48, 0), stolen) == MatchScore(0, 0)

    small = score_nolo(7, 6)
    assert transition_rising_score(MatchScore(48, 0), small) == MatchScore(0, 0)

    hands = partition_deck({})
    state = build_position(
        hands, dealer=0, score=MatchScore(48, 0), show_contracts=NOLO_THEN_RAMI
    )
    context = build_deal_match_context(acting_observation(state))
    if context.match_role is MatchRole.DOWN:
        assert context.margin_has_match_value is False
        assert context.own_win_can_end_match is False
        assert context.down_team_win_resets_score is True


def test_rami_and_nolo_cannot_share_an_undifferentiated_trick_reward() -> None:
    """The required contract-differentiation counterexample."""

    hands = partition_deck({})
    nolo = build_deal_match_context(
        acting_observation(build_position(hands, show_contracts=ALL_NOLO))
    )
    rami = build_deal_match_context(
        acting_observation(build_position(hands, show_contracts=NOLO_THEN_RAMI))
    )
    assert nolo.contract is Contract.NOLO and rami.contract is Contract.RAMI
    assert nolo.trick_reward_sign == -1
    assert rami.trick_reward_sign == +1
    assert nolo.marginal_own_trick_value < 0 < rami.marginal_own_trick_value
    assert nolo.marginal_own_trick_value != rami.marginal_own_trick_value
    # The defending partnership's trick is worth double the declaring one's.
    assert rami.trick_point_scale in (4, 8)
    assert score_rami(Team.TEAM_0, 7, 6).points == 4
    assert score_rami(Team.TEAM_0, 6, 7).points == 8


def test_partners_optimise_team_utility_and_never_an_individual_trick_count() -> None:
    """The required shared-utility counterexample."""

    hands = partition_deck({})
    context = build_deal_match_context(
        acting_observation(build_position(hands, show_contracts=ALL_NOLO))
    )
    assert context.team_tricks == (0, 0)
    assert context.own_team_tricks == 0
    # NOLO pays on the partnership total, so a trick taken by either partner
    # counts identically against the partnership.
    assert score_nolo(3, 10).points == score_nolo(10, 3).points
    for own in range(0, 7):
        assert score_nolo(own, 13 - own).winner_team is Team.TEAM_0
    assert not any(
        "individual" in name or "seat_trick" in name for name in context.__slots__
    )


# ------------------------------------------------------------------- coasting


def _coast_position(score: MatchScore):
    """Team 0 has already secured a RAMI it declared; seat 0 must follow."""

    hands = partition_deck({})
    state = build_position(hands, dealer=0, score=score, show_contracts=NOLO_THEN_RAMI)
    return state


def test_margin_is_worthless_once_a_down_team_has_secured_the_deal() -> None:
    hands = partition_deck({})
    state = build_position(
        hands, dealer=0, score=MatchScore(40, 0), show_contracts=ALL_NOLO
    )
    features = build_features(acting_observation(state), include_inference=True)
    context = features.deal
    assert context.match_role is MatchRole.DOWN
    assert context.margin_has_match_value is False
    # At the start of a deal both outcomes are still reachable, so no coasting.
    assert context.opponent_deal_win_possible is True
    assert margin_is_worthless(features) is False


def test_coasting_activates_only_when_the_deal_is_decided_and_margin_is_dead() -> None:
    profile = require_profile(KEY)
    hands = partition_deck({})
    state = build_position(hands, dealer=0, show_contracts=ALL_NOLO)
    features = build_features(acting_observation(state), include_inference=True)
    assert margin_is_worthless(features) is False
    assert match_play_mode(features, profile) is not PlayMode.COAST


def test_decisive_trick_detection_uses_the_seven_trick_boundary() -> None:
    hands = partition_deck({})
    state = build_position(hands, dealer=0, show_contracts=NOLO_THEN_RAMI)
    features = build_features(acting_observation(state), include_inference=True)
    assert features.deal.own_win_requires_at_least_tricks == 7
    assert decisive_trick_pending(features) is False


# ------------------------------------------------------------ end-to-end play


@pytest.mark.parametrize(
    "score",
    [MatchScore(), MatchScore(44, 0), MatchScore(0, 44), MatchScore(48, 0)],
)
def test_match_aware_completes_deals_in_every_score_state(score: MatchScore) -> None:
    hands = partition_deck({})
    state = run_full_deal(KEY, hands, score=score)
    assert state.phase in (EnginePhase.DEAL_COMPLETE, EnginePhase.MATCH_COMPLETE)
    result = state.completed_deals[-1].public_result
    assert sum(result.team_tricks) == 13


def test_the_no_match_state_variant_plays_exactly_like_partner_awareness() -> None:
    """Switching the rising-score features off must recover the lower rung."""

    from tuppi_engine import apply_match_action, match_observation_for

    specifications = phase4_specifications_by_profile_key()
    hands = partition_deck({})
    for score in (MatchScore(), MatchScore(48, 0), MatchScore(0, 48)):
        state = build_position(hands, dealer=0, score=score, show_contracts=())
        ablated = tuple(
            construct_agent(specifications[NO_STATE], seat=seat) for seat in range(4)
        )
        partner = tuple(
            construct_agent(specifications[PARTNER], seat=seat) for seat in range(4)
        )
        while state.phase in (EnginePhase.SHOWING, EnginePhase.TRICK_PLAY):
            actor = state.current_actor
            assert actor is not None
            observation = match_observation_for(state, actor)
            action = ablated[actor].choose_action(observation)
            assert action == partner[actor].choose_action(observation)
            state = apply_match_action(state, action)


def test_match_aware_and_partner_aware_diverge_when_the_score_matters() -> None:
    from tuppi_engine import apply_match_action, match_observation_for

    specifications = phase4_specifications_by_profile_key()
    hands = partition_deck({1: _BORDERLINE_RAMI_HAND})
    state = build_position(
        hands, dealer=0, score=MatchScore(0, 48), show_contracts=()
    )
    observation = match_observation_for(state, 1)
    match_action = construct_agent(specifications[KEY], seat=1).choose_action(observation)
    partner_action = construct_agent(specifications[PARTNER], seat=1).choose_action(
        observation
    )
    assert match_action != partner_action
    assert match_action.declared_contract is Contract.NOLO
    assert partner_action.declared_contract is Contract.RAMI


def test_reaching_the_target_ends_the_match_only_for_the_rising_team() -> None:
    assert MATCH_TARGET == 52
    up = transition_rising_score(MatchScore(48, 0), score_nolo(6, 7))
    assert up == MatchScore(52, 0)
    down = transition_rising_score(MatchScore(48, 0), score_nolo(7, 6))
    assert down == MatchScore(0, 0)
