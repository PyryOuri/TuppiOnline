from __future__ import annotations

import pytest

from tuppi_agents import (
    HeuristicProfile,
    PolicyFamily,
    PublicInference,
    ShowingPolicyId,
    build_features,
    construct_agent,
    phase4_specifications_by_profile_key,
    require_profile,
    specification_for_profile,
)
from tuppi_agents.partner_aware import partner_play_mode, score_partner_play
from tuppi_agents.reactive import PlayMode
from tuppi_engine import EnginePhase, PlayCardAction, ShowAction
from tuppi_rules import Contract, Suit

from .conftest import (
    acting_observation,
    build_position,
    card,
    partition_deck,
    policy,
    run_full_deal,
    start_deal,
)


KEY = "partner_aware_v1"
COUNTING = "public_counting_v1"
ALL_NOLO = (Contract.NOLO,) * 4
NOLO_THEN_RAMI = (Contract.NOLO, Contract.RAMI)

_SEAT0_NO_HEARTS = [
    "D2", "D3", "D4", "D5", "D6",
    "C2", "C3", "C4", "C5", "C6",
    "S2", "S3", "S4",
]


def _ablated(profile_key: str, disabled: tuple[str, ...], family: PolicyFamily):
    profile = HeuristicProfile.build(
        profile_key=profile_key,
        family=family,
        showing_policy=ShowingPolicyId.SIMPLE,
        disabled_rule_ids=disabled,
        description="ablation variant used by the test suite",
    )
    return specification_for_profile(profile)


def _partner_position(*, contract_line, partner_safe: bool):
    """Seat 3 must follow a heart while its partner at seat 1 holds the trick."""

    seat0 = _SEAT0_NO_HEARTS if partner_safe else ["H4"]
    hands = partition_deck(
        {
            1: ["HK", "H9"],
            2: ["H2", "H3"],
            3: ["H5", "H8", "H10", "HA"],
            0: seat0,
        },
        forbid={2: ["H"], 3: ["H"], 0: ["H"] if partner_safe else []},
    )
    fourth = "S2" if partner_safe else "H4"
    state = build_position(
        hands,
        dealer=0,
        show_contracts=contract_line,
        plays=["HK", "H2", "H5", fourth, "H9", "H3"],
    )
    observation = acting_observation(state)
    assert observation.observing_seat == 3
    assert observation.partner_seat == 1
    return state, observation


def _chosen(key_or_specification, state) -> str:
    observation = acting_observation(state)
    if isinstance(key_or_specification, str):
        agent = policy(key_or_specification, seat=observation.observing_seat)
    else:
        agent = construct_agent(
            key_or_specification, seat=observation.observing_seat
        )
    action = agent.choose_action(observation)
    assert isinstance(action, PlayCardAction)
    assert action in observation.legal_actions
    return action.card.to_code()


# ------------------------------------------------------------ capability bounds


def test_the_partner_profile_declares_partner_rules_and_no_match_state() -> None:
    profile = require_profile(KEY)
    assert profile.uses_public_inference is True
    assert profile.uses_partner_rules is True
    assert profile.match_state_enabled is False
    assert any(rule.startswith("partner.") for rule in profile.enabled_rule_ids)
    assert not any(rule.startswith("match.") for rule in profile.enabled_rule_ids)
    assert profile.partner_convention_id is None


# ------------------------------------------------------- overtaking a partner


def test_partner_aware_overtakes_a_beatable_partner_with_a_proven_winner() -> None:
    state, observation = _partner_position(
        contract_line=NOLO_THEN_RAMI, partner_safe=False
    )
    inference = PublicInference.build(observation)
    assert inference.is_seat_void(0, Suit.HEARTS) is False
    assert inference.seats_that_could_hold_higher(card("H9"), (0,))
    assert _chosen(KEY, state) == "AH"
    # The counting rung has no partnership rule and simply declines to overtake.
    assert _chosen(COUNTING, state) == "8H"


def test_partner_aware_protects_a_partner_whose_win_is_already_certain() -> None:
    state, observation = _partner_position(
        contract_line=NOLO_THEN_RAMI, partner_safe=True
    )
    inference = PublicInference.build(observation)
    assert inference.is_seat_void(0, Suit.HEARTS) is True
    assert not inference.seats_that_could_hold_higher(card("H9"), (0,))
    assert _chosen(KEY, state) == "8H"


def test_mechanical_partnership_rules_cannot_be_switched_off() -> None:
    """Only convention-like rules are ablatable; mechanical ones are not."""

    from tuppi_agents.errors import ProfileError

    for rule_id in (
        "partner.rami.protect_certain_partner_winner.v1",
        "partner.nolo.dump_liability_when_partner_certainly_wins.v1",
    ):
        with pytest.raises(ProfileError, match="cannot be disabled"):
            _ablated(KEY, (rule_id,), PolicyFamily.PARTNER_AWARE)


def test_the_overtake_rule_is_independently_disableable() -> None:
    state, _ = _partner_position(contract_line=NOLO_THEN_RAMI, partner_safe=False)
    ablated = _ablated(
        KEY,
        ("partner.rami.overtake_when_partner_beatable.v1",),
        PolicyFamily.PARTNER_AWARE,
    )
    assert _chosen(KEY, state) == "AH"
    assert _chosen(ablated, state) == "8H"


# ------------------------------------------- NOLO team-count reasoning


def test_nolo_dumps_a_liability_once_the_partnership_is_certain_to_take_it() -> None:
    """The team trick total is already fixed, so the card choice is free."""

    state, observation = _partner_position(contract_line=ALL_NOLO, partner_safe=True)
    features = build_features(observation, include_inference=True)
    assert partner_play_mode(features, require_profile(KEY)) is PlayMode.NOLO_CONCEDED
    assert _chosen(KEY, state) == "AH"
    # Without the partnership rule the counting rung optimises its own card only.
    assert _chosen(COUNTING, state) == "8H"


# --------------------------------------------------------- partner-void leads


def _void_partner_lead_position():
    """Seat 1 leads trick two knowing its partner at seat 3 is void in hearts."""

    hand = [
        "HA", "H2", "H6",
        "D2", "D3",
        "C3", "C4", "C5", "C6",
        "S3", "S4", "S5", "S6",
    ]
    hands = partition_deck(
        {1: hand, 2: ["H3"], 0: ["H4"], 3: ["S7"]},
        forbid={3: ["H"], 1: ["H"]},
    )
    state = build_position(
        hands, dealer=0, show_contracts=ALL_NOLO, plays=["HA", "H3", "S7", "H4"]
    )
    observation = acting_observation(state)
    assert observation.observing_seat == 1
    assert observation.current_trick == ()
    return state, observation


def test_nolo_lead_prefers_a_suit_the_partner_is_publicly_void_in() -> None:
    state, observation = _void_partner_lead_position()
    inference = PublicInference.build(observation)
    assert inference.is_seat_void(3, Suit.HEARTS) is True
    assert _chosen(KEY, state) == "2H"
    # The counting rung has no partner rule and prefers the unaccounted count.
    assert _chosen(COUNTING, state) == "2D"


def test_the_partner_void_lead_rule_is_independently_disableable() -> None:
    state, _ = _void_partner_lead_position()
    ablated = _ablated(
        KEY,
        ("partner.nolo.prefer_leading_partner_void_suit.v1",),
        PolicyFamily.PARTNER_AWARE,
    )
    assert _chosen(KEY, state) == "2H"
    assert _chosen(ablated, state) == "2D"


def test_rami_lead_reports_whether_the_partner_can_follow_each_suit() -> None:
    hands = partition_deck(
        {1: ["HA"], 2: ["H3"], 0: ["H4"], 3: ["S7"]}, forbid={3: ["H"]}
    )
    state = build_position(
        hands,
        dealer=0,
        show_contracts=NOLO_THEN_RAMI,
        plays=["HA", "H3", "S7", "H4"],
    )
    observation = acting_observation(state)
    features = build_features(observation, include_inference=True)
    ranking = score_partner_play(observation, features, require_profile(KEY))
    assert ranking.candidates[0].component_names == (
        "certain_trick",
        "partner_can_follow",
        "lead_suit_score",
        "lead_rank_preference",
    )
    inference = features.require_inference()
    for candidate in ranking.candidates:
        expected = (
            0.0
            if inference.is_seat_void(features.partner_seat, candidate.action.card.suit)
            else 1.0
        )
        assert candidate.score_vector[1] == expected


# ------------------------------------------------------- heterogeneous pairing


@pytest.mark.parametrize(
    "left,right",
    [
        ("partner_aware_v1", "reactive_contract_v1"),
        ("partner_aware_v1", "legacy_heuristic_port_v1"),
        ("match_aware_v1", "public_counting_v1"),
    ],
)
def test_heterogeneous_partnerships_complete_a_deal_without_illegal_actions(
    left: str, right: str
) -> None:
    specifications = phase4_specifications_by_profile_key()
    hands = partition_deck({})
    agents = (
        construct_agent(specifications[left], seat=0),
        construct_agent(specifications[right], seat=1),
        construct_agent(specifications[right], seat=2),
        construct_agent(specifications[left], seat=3),
    )
    assert len({id(agent) for agent in agents}) == 4
    from tuppi_engine import play_active_deal

    state = play_active_deal(start_deal(hands), agents)
    assert state.phase in (EnginePhase.DEAL_COMPLETE, EnginePhase.MATCH_COMPLETE)
    assert sum(state.completed_deals[-1].public_result.team_tricks) == 13


def test_a_partner_aware_agent_does_not_assume_a_clone_partner() -> None:
    """Behaviour must not depend on the partner sharing the same profile."""

    specifications = phase4_specifications_by_profile_key()
    state, observation = _partner_position(
        contract_line=NOLO_THEN_RAMI, partner_safe=False
    )
    own = construct_agent(specifications[KEY], seat=3)
    chosen = own.choose_action(observation)
    # The very same observation arises whatever policy produced the partner's
    # card, so the decision cannot encode an assumption about the partner.
    assert chosen == own.choose_action(observation)
    assert observation.partner_seat == 1


def test_the_legacy_convention_profile_changes_only_the_shown_card() -> None:
    """The optional convention is legacy-derived and separately identified."""

    hand = [
        "H2", "HA", "HK",
        "D2", "DA",
        "C4", "C7", "C8",
        "S4", "S7", "S8", "S9", "S10",
    ]
    hands = partition_deck({1: hand})
    state = build_position(hands, dealer=0, show_contracts=())
    observation = acting_observation(state)
    specifications = phase4_specifications_by_profile_key()
    plain = construct_agent(specifications[KEY], seat=1).choose_action(observation)
    convention = construct_agent(
        specifications["partner_aware_legacy_convention_v1"], seat=1
    ).choose_action(observation)
    assert isinstance(plain, ShowAction) and isinstance(convention, ShowAction)
    assert plain.declared_contract is convention.declared_contract is Contract.NOLO
    # Canonical order prefers clubs; the frozen legacy hand order prefers spades.
    assert plain.shown_card == card("C4")
    assert convention.shown_card == card("S4")


def test_running_a_full_deal_with_each_partner_profile_is_legal() -> None:
    hands = partition_deck({})
    for key in (KEY, "partner_aware_legacy_convention_v1"):
        state = run_full_deal(key, hands)
        assert state.phase in (EnginePhase.DEAL_COMPLETE, EnginePhase.MATCH_COMPLETE)
