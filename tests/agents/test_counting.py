from __future__ import annotations

from tuppi_agents import PublicInference, build_features, require_profile
from tuppi_agents.counting import certainly_wins, score_counting_play
from tuppi_agents.reactive import score_reactive_play
from tuppi_engine import PlayCardAction
from tuppi_rules import Contract, Suit

from .conftest import acting_observation, build_position, card, partition_deck, policy


NOLO_THEN_RAMI = (Contract.NOLO, Contract.RAMI)
ALL_NOLO = (Contract.NOLO,) * 4
KEY = "public_counting_v1"
REACTIVE = "reactive_contract_v1"

_SEAT0_NO_HEARTS = [
    "D2", "D3", "D4", "D5", "D6",
    "C2", "C3", "C4", "C5", "C6",
    "S2", "S3", "S4",
]
_SEAT0_ONE_HEART = [
    "H2",
    "D2", "D3", "D4", "D5", "D6",
    "C2", "C3", "C4", "C5", "C6",
    "S2", "S3",
]


def _position(*, seat0: list[str], lead_first: str):
    """Build a RAMI position where seat 3 must follow a heart at position two."""

    hands = partition_deck(
        {
            1: ["HA", "H5", "H9"],
            2: ["H3", "H6"],
            3: ["H4", "H7", "HK"],
            0: seat0,
        },
        forbid={2: ["H"], 3: ["H"], 0: ["H"]},
    )
    trick_one = [lead_first, "H3", "H4", "S2" if "H2" not in seat0 else "H2"]
    state = build_position(
        hands,
        dealer=0,
        show_contracts=NOLO_THEN_RAMI,
        plays=[*trick_one, "H5", "H6"],
    )
    observation = acting_observation(state)
    assert observation.observing_seat == 3
    assert observation.contract is Contract.RAMI
    return state, observation


def _chosen(key: str, state) -> str:
    observation = acting_observation(state)
    action = policy(key, seat=observation.observing_seat).choose_action(observation)
    assert isinstance(action, PlayCardAction)
    assert action in observation.legal_actions
    return action.card.to_code()


# ------------------------------------------------------------ capability bounds


def test_the_counting_profile_declares_inference_and_no_partner_rules() -> None:
    profile = require_profile(KEY)
    assert profile.uses_public_inference is True
    assert profile.uses_partner_rules is False
    assert profile.match_state_enabled is False
    assert any(rule.startswith("counting.") for rule in profile.enabled_rule_ids)
    assert not any(rule.startswith("partner.") for rule in profile.enabled_rule_ids)
    assert not any(rule.startswith("match.") for rule in profile.enabled_rule_ids)


# ----------------------------------------------- inferred voids change the play


def test_an_inferred_void_makes_the_cheapest_winner_certain_and_changes_the_card() -> None:
    """Seat 0 failed to follow hearts, so nothing can beat seat 3's cheap winner."""

    void_state, void_observation = _position(seat0=_SEAT0_NO_HEARTS, lead_first="HA")
    inference = PublicInference.build(void_observation)
    assert inference.is_seat_void(0, Suit.HEARTS) is True
    assert void_observation.current_trick[0].seat == 1
    assert _chosen(KEY, void_state) == "7H"

    following_state, following_observation = _position(
        seat0=_SEAT0_ONE_HEART, lead_first="HA"
    )
    assert (
        PublicInference.build(following_observation).is_seat_void(0, Suit.HEARTS) is False
    )
    # With no proven void the cheap winner can still be beaten, so the counting
    # agent spends the proven winner instead.
    assert _chosen(KEY, following_state) == "KH"


def test_the_public_played_record_alone_changes_the_selected_card() -> None:
    """Positions differing only in which heart was led earlier differ in play."""

    ace_played, _ = _position(seat0=_SEAT0_ONE_HEART, lead_first="HA")
    ace_held, observation = _position(seat0=_SEAT0_ONE_HEART, lead_first="H9")
    inference = PublicInference.build(observation)
    assert inference.is_played(card("HA")) is False
    assert inference.is_highest_unplayed_in_suit(card("HK")) is False
    assert _chosen(KEY, ace_played) == "KH"
    assert _chosen(KEY, ace_held) == "7H"


def test_counting_and_reactive_differ_exactly_where_certainty_is_available() -> None:
    state, _ = _position(seat0=_SEAT0_ONE_HEART, lead_first="HA")
    assert _chosen(REACTIVE, state) == "7H"
    assert _chosen(KEY, state) == "KH"


# ------------------------------------------------------- hard component values


def test_certainty_component_equals_the_hard_public_predicate() -> None:
    state, observation = _position(seat0=_SEAT0_NO_HEARTS, lead_first="HA")
    profile = require_profile(KEY)
    features = build_features(observation, include_inference=True)
    ranking = score_counting_play(observation, features, profile)
    assert ranking.candidates[0].component_names == (
        "trick_preference",
        "certainty",
        "rank_cost",
    )
    inference = features.require_inference()
    trick = features.require_trick()
    for candidate in ranking.candidates:
        assert isinstance(candidate.action, PlayCardAction)
        expected = 1.0 if certainly_wins(candidate.action.card, trick, inference) else 0.0
        assert candidate.score_vector[1] == expected


def test_counting_adds_a_component_to_the_reactive_layout() -> None:
    state, observation = _position(seat0=_SEAT0_NO_HEARTS, lead_first="HA")
    profile = require_profile(KEY)
    counting = score_counting_play(
        observation, build_features(observation, include_inference=True), profile
    )
    reactive = score_reactive_play(
        observation, build_features(observation, include_inference=False), profile
    )
    assert len(counting.candidates[0].component_names) == (
        len(reactive.candidates[0].component_names) + 1
    )
    assert set(reactive.candidates[0].component_names).issubset(
        set(counting.candidates[0].component_names)
    )


def test_nolo_lead_counts_unaccounted_higher_cards_exactly() -> None:
    hand = [
        "H2", "H3", "H4",
        "D2", "DA",
        "C3", "C4", "C5", "C6",
        "S3", "S4", "S5", "S6",
    ]
    hands = partition_deck({1: hand})
    state = build_position(hands, dealer=0, show_contracts=ALL_NOLO)
    observation = acting_observation(state)
    features = build_features(observation, include_inference=True)
    ranking = score_counting_play(observation, features, require_profile(KEY))
    assert ranking.candidates[0].component_names == (
        "lead_rank_cost",
        "unaccounted_higher_count",
        "lead_suit_shortness",
    )
    inference = features.require_inference()
    for candidate in ranking.candidates:
        expected = float(len(inference.unaccounted_higher_in_suit(candidate.action.card)))
        assert candidate.score_vector[1] == expected
        assert expected == int(expected)


def test_discard_ranking_prefers_shedding_a_proven_future_winner() -> None:
    hand = [
        "D2", "D3", "D4", "D5",
        "C2", "C3", "C4", "C5",
        "S2", "S3", "S4", "S5", "SA",
    ]
    hands = partition_deck({1: ["H7"], 2: hand}, forbid={2: ["H"]})
    state = build_position(hands, dealer=0, show_contracts=ALL_NOLO, plays=["H7"])
    observation = acting_observation(state)
    features = build_features(observation, include_inference=True)
    ranking = score_counting_play(observation, features, require_profile(KEY))
    assert ranking.candidates[0].component_names == (
        "shed_certain_winner",
        "discard_liability",
        "short_suit_bonus",
        "rank_preference",
    )
    inference = features.require_inference()
    for candidate in ranking.candidates:
        expected = (
            1.0
            if inference.is_highest_unplayed_in_suit(candidate.action.card)
            else 0.0
        )
        assert candidate.score_vector[0] == expected
    assert isinstance(ranking.action, PlayCardAction)
    assert inference.is_highest_unplayed_in_suit(ranking.action.card)


def test_no_counting_component_is_a_probability() -> None:
    state, observation = _position(seat0=_SEAT0_NO_HEARTS, lead_first="HA")
    features = build_features(observation, include_inference=True)
    ranking = score_counting_play(observation, features, require_profile(KEY))
    for candidate in ranking.candidates:
        for name, value in candidate.feature_contributions:
            assert not any(
                token in name for token in ("probability", "prior", "belief", "weight")
            )
            if name in ("certainty", "shed_certain_winner", "certain_trick"):
                assert value in (0.0, 1.0)
            if name == "unaccounted_higher_count":
                assert value == int(value)


def test_counting_never_asserts_an_impossible_owner() -> None:
    state, observation = _position(seat0=_SEAT0_NO_HEARTS, lead_first="HA")
    inference = PublicInference.build(observation)
    active = state.active_deal
    assert active is not None
    for seat in range(4):
        for held in active.hands[seat]:
            assert inference.can_seat_hold(seat, held) or seat == 3
    for played in inference.played_cards:
        assert inference.possible_owners(played) == frozenset()
