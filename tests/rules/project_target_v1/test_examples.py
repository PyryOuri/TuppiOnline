from __future__ import annotations

import json
from pathlib import Path

from tuppi_rules import (
    Contract,
    MatchScore,
    Team,
    card_from_code,
    first_leader,
    is_match_terminal,
    match_winner,
    resolve_showing,
    score_nolo,
    score_rami,
    transition_rising_score,
    valid_show_cards,
    validate_show_action,
)

ROOT = Path(__file__).resolve().parents[3]
FIXTURE_ROOT = ROOT / "examples/rules/project_target_v1"


def load_fixture(name: str):
    value = json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))
    assert value["schema_version"] == "tuppi.rules.examples.v1"
    assert value["ruleset_id"] == "project_target_v1"
    assert isinstance(value["scenarios"], list) and value["scenarios"]
    return value


def test_all_required_show_action_examples_execute() -> None:
    fixture = load_fixture("show_actions.json")
    assert fixture["operation"] == "validate_show_action"
    for scenario in fixture["scenarios"]:
        hand = tuple(card_from_code(code) for code in scenario["hand"])
        shown = card_from_code(scenario["shown_card"])
        contract = Contract(scenario["declared_contract"])
        action = validate_show_action(
            seat=scenario["seat"],
            hand=hand,
            shown_card=shown,
            declared_contract=contract,
            claimed_verbal_required=scenario["expected_verbal_required"],
        )
        assert action.verbal_required is scenario["expected_verbal_required"]
        assert {card.to_code() for card in valid_show_cards(hand, contract)} == set(
            scenario["expected_valid_show_cards"]
        )
        assert shown in hand


def test_required_contract_resolution_examples_execute() -> None:
    fixture = load_fixture("contract_resolution.json")
    hands = {
        int(seat): tuple(card_from_code(code) for code in hand)
        for seat, hand in fixture["hands_by_seat"].items()
    }
    for scenario in fixture["scenarios"]:
        actions = tuple(
            validate_show_action(
                seat=raw["seat"],
                hand=hands[raw["seat"]],
                shown_card=card_from_code(raw["shown_card"]),
                declared_contract=Contract(raw["declared_contract"]),
            )
            for raw in scenario["actions"]
        )
        result = resolve_showing(dealer=scenario["dealer"], actions=actions)
        assert result.contract.value == scenario["expected_contract"]
        assert result.declarer == scenario["expected_declarer"]
        assert first_leader(
            contract=result.contract,
            dealer=scenario["dealer"],
            declarer=result.declarer,
        ) == scenario["expected_first_leader"]


def score_fixture_deal(raw):
    if raw["contract"] == "NOLO":
        return score_nolo(raw["team0_tricks"], raw["team1_tricks"])
    return score_rami(
        Team(raw["declaring_team"]), raw["team0_tricks"], raw["team1_tricks"]
    )


def test_required_deal_scoring_examples_execute() -> None:
    fixture = load_fixture("deal_scoring.json")
    for scenario in fixture["scenarios"]:
        score = score_fixture_deal(scenario)
        assert score.winner_team.value == scenario["expected_winner_team"]
        assert score.points == scenario["expected_points"]
        assert score.stolen_rami is scenario["expected_stolen_rami"]


def test_required_match_transition_examples_execute() -> None:
    fixture = load_fixture("match_transitions.json")
    for scenario in fixture["scenarios"]:
        current = MatchScore(*scenario["current_score"])
        deal_score = score_fixture_deal(scenario["deal"])
        result = transition_rising_score(current, deal_score)
        assert list(result.as_tuple()) == scenario["expected_score"]
        assert is_match_terminal(result) is scenario["expected_terminal"]
        winner = match_winner(result)
        assert (winner.value if winner is not None else None) == scenario[
            "expected_winner_team"
        ]


def test_fixture_set_contains_every_required_representative_situation() -> None:
    all_ids = []
    for name in (
        "show_actions.json",
        "contract_resolution.json",
        "deal_scoring.json",
        "match_transitions.json",
    ):
        all_ids.extend(item["id"] for item in load_fixture(name)["scenarios"])
    assert len(all_ids) == 14
    assert len(set(all_ids)) == len(all_ids)
    assert set(all_ids) == {
        "normal_red_rami_show",
        "normal_black_nolo_show",
        "rami_verbal_fallback_black_eligible",
        "nolo_verbal_fallback_red_eligible",
        "no_eligible_rank_arbitrary_card_verbal",
        "rami_declared_by_forehand",
        "rami_declared_by_dealer",
        "four_player_nolo_sequence",
        "nolo_6_to_7",
        "rami_7_to_6",
        "stolen_rami_6_to_7",
        "team_at_48_reaches_52",
        "down_team_resets_48_point_up_team",
        "down_team_56_point_stolen_rami_only_resets",
    }
