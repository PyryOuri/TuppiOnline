from __future__ import annotations

from functools import cache
import json
import random
from pathlib import Path

import pytest

import tuppi_server.match_runner as match_runner_module
from tuppi_agents import construct_registered_agent, phase4_specifications_by_profile_key
from tuppi_engine import ExplicitDeal, action_from_data, action_to_data
from tuppi_rules import FULL_DECK, card_to_code
from tuppi_server.analysis import validate_post_match_analysis_response
from tuppi_server.match_runner import LiveMatchRunner
from tuppi_server.post_match_diagnostics import (
    generate_completed_deal_diagnostics,
    generate_post_match_diagnostics,
    reconstruct_historical_decisions,
)
from tuppi_server.projection import project_event_batch
from tuppi_server.rooms import RoomError, RoomManager
from tuppi_ui_fixtures.validation import validate_instance


@cache
def _terminal_runner() -> LiveMatchRunner:
    """A stable completed match with enough variety for all three sources."""

    random_source = random.Random(260810)
    deals: list[ExplicitDeal] = []
    for deal_number in range(50):
        cards = list(FULL_DECK)
        random_source.shuffle(cards)
        hands = tuple(
            tuple(cards[seat * 13 : (seat + 1) * 13]) for seat in range(4)
        )
        deals.append(ExplicitDeal(dealer=deal_number % 4, hands=hands))
    remaining = iter(deals)
    original = match_runner_module.generate_live_deal

    def deterministic_deal(*, dealer: int) -> ExplicitDeal:
        deal = next(remaining)
        assert deal.dealer == dealer
        return deal

    match_runner_module.generate_live_deal = deterministic_deal
    try:
        runner = LiveMatchRunner(
            match_ref="post-match-diagnostics-test",
            ai_seats=frozenset({1, 2, 3}),
        )
        human_action_index = 0
        while not runner.terminal:
            observation = runner.observation(0)
            action = action_from_data(observation["legal_actions"][-1])
            runner.submit(
                seat=0,
                client_action_id=f"test-human:{human_action_index}",
                match_ref=runner.match_ref,
                expected_event_index=runner.event_cursor,
                action=action,
            )
            human_action_index += 1
    finally:
        match_runner_module.generate_live_deal = original
    assert runner.terminal
    return runner


@cache
def _seat_zero_response() -> dict[str, object]:
    return generate_post_match_diagnostics(_terminal_runner(), seat=0)


@cache
def _one_completed_deal_runner() -> LiveMatchRunner:
    runner = LiveMatchRunner(
        match_ref="completed-deal-diagnostics-test",
        ai_seats=frozenset({1, 2, 3}),
    )
    action_index = 0
    while not runner.state.completed_deals:
        observation = runner.observation(0)
        runner.submit(
            seat=0,
            client_action_id=f"one-deal:{action_index}",
            match_ref=runner.match_ref,
            expected_event_index=runner.event_cursor,
            action=action_from_data(observation["legal_actions"][-1]),
        )
        action_index += 1
    assert not runner.terminal
    return runner


def _action_card(action: dict[str, object]) -> str:
    card = action.get("card", action.get("shown_card"))
    assert isinstance(card, str)
    return card


def test_historical_reconstruction_uses_the_formal_observation_before_each_action() -> None:
    runner = _terminal_runner()
    decisions = reconstruct_historical_decisions(runner, seat=0)
    persisted_actions = [
        item for item in runner.persistence_record()["accepted_actions"] if item["seat"] == 0
    ]
    assert len(decisions) == len(persisted_actions)
    assert decisions

    for decision, persisted in zip(decisions, persisted_actions, strict=True):
        assert decision.action_index == persisted["action_index"]
        assert action_to_data(decision.action) == persisted["action"]
        assert decision.observation.observing_seat == 0
        assert decision.observation.current_actor == 0
        assert decision.action in decision.observation.legal_actions
        assert decision.observation.own_hand == decision.deal_state.hands[0]
        assert decision.observation.match_score == decision.deal_state.starting_score


def test_real_generator_ranks_exact_rule_and_reference_evidence() -> None:
    response = _seat_zero_response()
    assert response["schema_version"] == "tuppi.analysis.post_match.v2"
    assert response["seat"] == 0
    analyses = response["analyses"]
    assert isinstance(analyses, list)
    assert 3 <= len(analyses) <= 10
    sources = {item["source"] for item in analyses}
    assert "Exact" in sources
    assert "Rule-based" in sources
    assert "Reference" in sources
    assert all(item["seat"] == 0 for item in analyses)
    assert len({item["event_index"] for item in analyses}) == len(analyses)

    validate_instance(
        response,
        "https://example.invalid/tuppi/schemas/network/post_match_analysis.schema.json",
    )


def test_exact_diagnostic_has_measurable_values_and_tied_actions() -> None:
    analyses = _seat_zero_response()["analyses"]
    exact = next(item for item in analyses if item["source"] == "Exact")
    assert exact["confidence"] == "perfect_information_exact"
    assert exact["source_id"] == "phase5b_exact_late_game_v1"
    quantitative = exact["quantitative"]
    assert quantitative["metric"] == "own_team_final_tricks"
    assert quantitative["difference"] > 0
    assert exact["recommended_action"] in exact["legal_actions"]
    assert exact["played_action"] in exact["legal_actions"]
    assert exact["equivalent_actions"]
    assert "täydellisillä tiedoilla" in exact["explanation"][0]


def test_reference_comparison_replays_partner_aware_on_the_same_observation() -> None:
    runner = _terminal_runner()
    decisions = {
        item.event_index: item
        for item in reconstruct_historical_decisions(runner, seat=0)
    }
    reference = construct_registered_agent(
        phase4_specifications_by_profile_key()["partner_aware_v1"],
        seat=0,
    )
    analyses = _seat_zero_response()["analyses"]
    item = next(item for item in analyses if item["source"] == "Reference")
    decision = decisions[item["event_index"]]
    assert item["recommended_action"] == action_to_data(
        reference.choose_action(decision.observation)
    )
    assert item["played_action"] == action_to_data(decision.action)
    assert item["quantitative"] is None
    assert "ei matemaattinen optimi" in item["limitations"][0]


def test_response_is_seat_scoped_and_contains_no_raw_private_diagnostics() -> None:
    runner = _terminal_runner()
    response = _seat_zero_response()
    serialized = json.dumps(response, sort_keys=True)
    for forbidden in (
        "initial_hands",
        "hidden_hands",
        "search_tree",
        "world_set",
        "belief_particles",
        "observation_digest",
        "score_vector",
    ):
        assert forbidden not in serialized

    decisions = {
        item.event_index: item
        for item in reconstruct_historical_decisions(runner, seat=0)
    }
    for analysis in response["analyses"]:
        decision = decisions[analysis["event_index"]]
        own_starting_cards = {
            card_to_code(card) for card in decision.deal_state.initial_hands[0]
        }
        action_arrays = (
            [analysis["played_action"], analysis["recommended_action"]]
            + analysis["legal_actions"]
            + analysis["equivalent_actions"]
        )
        assert {_action_card(action) for action in action_arrays} <= own_starting_cards


def test_analysis_endpoint_is_terminal_only_and_generates_after_restart_material() -> None:
    manager = RoomManager()
    room, host = manager.create_room(display_name="Pelaaja", ai_seats=frozenset({1, 2, 3}))
    room.runner = LiveMatchRunner(
        match_ref=f"room-{room.code.lower()}",
        ai_seats=frozenset({1, 2, 3}),
    )
    with pytest.raises(RoomError, match="match_not_complete"):
        manager.post_match_analysis_for_session(code=room.code, token=host.token)

    # A persistence replay is the same material available after server restart.
    terminal = LiveMatchRunner.from_persistence_record(
        _terminal_runner().persistence_record()
    )
    room.runner = terminal
    room.lifecycle = "completed"
    response = manager.post_match_analysis_for_session(code=room.code, token=host.token)
    assert response["schema_version"] == "tuppi.analysis.post_match.v2"
    assert response["seat"] == host.seat


def test_completed_deal_generator_is_available_before_52_and_stays_deal_scoped() -> None:
    runner = _one_completed_deal_runner()
    response = generate_completed_deal_diagnostics(runner, seat=0, deal_number=0)
    assert response["schema_version"] == "tuppi.analysis.completed_deal.v1"
    assert response["deal_ref"].endswith("/deal:0")
    assert response["summary"]["diagnostic_count"] == len(response["analyses"])
    assert all(item["deal_number"] == 0 for item in response["analyses"])
    assert "/deal:1" not in json.dumps(response, sort_keys=True)
    validate_instance(
        response,
        "https://example.invalid/tuppi/schemas/network/completed_deal_analysis.schema.json",
    )


def test_completed_deal_analysis_is_early_only_for_solo_ai_practice() -> None:
    manager = RoomManager()
    room, host = manager.create_room(
        display_name="Pelaaja",
        ai_seats=frozenset({1, 2, 3}),
    )
    room.runner = _one_completed_deal_runner()
    response = manager.completed_deal_analysis_for_session(
        code=room.code,
        token=host.token,
        deal_number=0,
    )
    assert response["seat"] == 0

    competitive = RoomManager()
    room, host = competitive.create_room(display_name="Isäntä")
    competitive.join_room(code=room.code, display_name="Vierailija")
    room.runner = _one_completed_deal_runner()
    with pytest.raises(RoomError, match="analysis_locked_until_match_complete"):
        competitive.completed_deal_analysis_for_session(
            code=room.code,
            token=host.token,
            deal_number=0,
        )


def test_empty_v2_response_is_valid_for_a_completed_match_with_no_findings() -> None:
    runner = _terminal_runner()
    response = _seat_zero_response()
    empty = {
        **response,
        "summary": {**response["summary"], "diagnostic_count": 0},
        "analyses": [],
    }
    assert validate_post_match_analysis_response(
        empty,
        expected_match_ref=runner.match_ref,
        public_events=project_event_batch(runner.state.public_events),
    ) == empty


def test_product_generator_does_not_import_failed_search_or_belief_agents() -> None:
    source = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "tuppi_server"
        / "post_match_diagnostics.py"
    ).read_text(encoding="utf-8")
    assert "tuppi_search" not in source
    assert "tuppi_belief" not in source
    assert "PIMC" not in source
    assert "root_info_uct" not in source
    assert "multi_observer_ismcts" not in source
