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
            # This evidence-variety fixture predates the live default change.
            # Pin its actors so upgrading the default cannot erase its cases.
            ai_profile_key="partner_aware_v1",
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
    assert response["schema_version"] == "tuppi.analysis.post_match.v3"
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


def test_reference_agreement_counts_every_reconstructed_decision() -> None:
    runner = _terminal_runner()
    agreement = _seat_zero_response()["summary"]["reference_agreement"]
    decisions = reconstruct_historical_decisions(runner, seat=0)
    reference = construct_registered_agent(
        phase4_specifications_by_profile_key()["partner_aware_v1"],
        seat=0,
    )

    # The aggregate covers all of the seat's decisions, not the ten selected
    # diagnostics, so recompute it independently from the reference policy.
    expected_matches = sum(
        1
        for decision in decisions
        if reference.choose_action(decision.observation) == decision.action
    )
    expected_showing = sum(
        1 for decision in decisions if decision.observation.phase.value == "SHOWING"
    )
    assert agreement["reference_profile"] == "partner_aware_v1"
    assert agreement["decision_count"] == len(decisions)
    assert agreement["decision_count"] > len(_seat_zero_response()["analyses"])
    assert agreement["match_count"] == expected_matches
    assert agreement["showing_decision_count"] == expected_showing
    assert (
        agreement["showing_decision_count"] + agreement["trick_decision_count"]
        == agreement["decision_count"]
    )
    assert (
        agreement["top_rank_count"]
        + agreement["second_rank_count"]
        + agreement["lower_rank_count"]
        == agreement["decision_count"]
    )
    assert agreement["top_rank_count"] == agreement["match_count"]
    assert 1.0 <= agreement["mean_played_rank"] <= agreement["mean_legal_action_count"]

    # A forced decision has one legal action, so it agrees by construction and
    # must be reported separately rather than inflating the headline share.
    expected_forced = sum(
        1 for decision in decisions if len(decision.observation.legal_actions) == 1
    )
    assert agreement["forced_decision_count"] == expected_forced
    assert agreement["forced_decision_count"] <= agreement["match_count"]


def test_reference_ranking_places_the_played_action_in_the_policy_ordering() -> None:
    runner = _terminal_runner()
    response = _seat_zero_response()
    decisions = {
        item.event_index: item
        for item in reconstruct_historical_decisions(runner, seat=0)
    }
    reference = construct_registered_agent(
        phase4_specifications_by_profile_key()["partner_aware_v1"],
        seat=0,
    )
    for analysis in response["analyses"]:
        ranking = analysis["reference_ranking"]
        decision = decisions[analysis["event_index"]]
        scored = reference.decide(decision.observation, diagnostics=False).scored
        ordered = [action_to_data(item.action) for item in scored.ranked()]
        assert ranking["reference_profile"] == "partner_aware_v1"
        assert ranking["reference_action"] == action_to_data(scored.action)
        assert ranking["legal_action_count"] == len(ordered)
        assert ranking["played_rank"] == ordered.index(analysis["played_action"]) + 1
        assert ranking["reference_action"] in analysis["legal_actions"]
        # A strictly better action must exist unless the reference was
        # indifferent or it picked the played action itself.
        if ranking["reference_action"] == analysis["played_action"]:
            assert ranking["played_rank"] == 1
            assert ranking["strictly_better_count"] == 0
            assert ranking["reference_indifferent"] is False
        elif ranking["reference_indifferent"]:
            assert ranking["strictly_better_count"] == 0
            assert ranking["played_rank"] > 1
        else:
            assert ranking["strictly_better_count"] >= 1
        assert ranking["strictly_better_count"] < ranking["played_rank"]


def test_a_tied_top_score_is_reported_as_indifference_not_a_disagreement() -> None:
    """A tie the reference did not care about must not read as a measured error."""

    from dataclasses import replace

    from tuppi_server.post_match_diagnostics import _reference_view

    runner = _terminal_runner()
    reference = construct_registered_agent(
        phase4_specifications_by_profile_key()["partner_aware_v1"],
        seat=0,
    )
    verified = 0
    for decision in reconstruct_historical_decisions(runner, seat=0):
        scored = reference.decide(decision.observation, diagnostics=False).scored
        best = tuple(float(value) for value in scored.selected.score_vector)
        tied = [
            candidate
            for candidate in scored.candidates
            if tuple(float(value) for value in candidate.score_vector) == best
        ]
        if len(tied) < 2:
            continue
        # Replay the decision as if the seat had taken a tied-but-unselected
        # action; only the documented engine-index tie-break separated them.
        other = next(item for item in tied if item.action != scored.action)
        view = _reference_view(reference, replace(decision, action=other.action))
        assert view.indifferent
        assert not view.agreed
        assert view.strictly_better_count == 0
        assert view.played_rank > 1
        verified += 1
    assert verified, "the fixture match must contain a top-score tie to exercise this"


def test_showing_diagnostics_expose_the_contract_scalars_and_closed_notes() -> None:
    from tuppi_server.analysis import VERDICT_NOTES

    analyses = _seat_zero_response()["analyses"]
    showing = [item for item in analyses if item["decision_kind"] == "SHOWING"]
    assert showing, "the fixture match must contain at least one showing diagnostic"
    for item in showing:
        reasoning = item["contract_reasoning"]
        metrics = {entry["name"]: entry["value"] for entry in reasoning["metrics"]}
        # partner_aware_v1 uses simple_show_v1, whose RAMI/NOLO choice is a
        # threshold test and a veto test over these four scalars.
        assert set(metrics) == {
            "simple_rami_score",
            "simple_nolo_score",
            "simple_rami_threshold",
            "simple_nolo_veto_threshold",
        }
        assert all(isinstance(value, float) for value in metrics.values())
        assert reasoning["declared_contract"] == item["played_action"]["declared_contract"]
        assert reasoning["reference_contract"] in {"RAMI", "NOLO"}
        assert set(reasoning["verdict_notes"]) <= VERDICT_NOTES
        threshold_met = metrics["simple_rami_score"] >= metrics["simple_rami_threshold"]
        veto = metrics["simple_nolo_score"] > metrics["simple_nolo_veto_threshold"]
        assert ("rami_threshold_met" in reasoning["verdict_notes"]) == threshold_met
        assert ("nolo_veto_applied" in reasoning["verdict_notes"]) == veto
        expected = "RAMI" if threshold_met and not veto else "NOLO"
        assert reasoning["reference_contract"] == expected

    for item in analyses:
        if item["decision_kind"] == "TRICK_PLAY":
            assert item["contract_reasoning"] is None


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
    assert response["schema_version"] == "tuppi.analysis.post_match.v3"
    assert response["seat"] == host.seat


def test_completed_deal_generator_is_available_before_52_and_stays_deal_scoped() -> None:
    runner = _one_completed_deal_runner()
    response = generate_completed_deal_diagnostics(runner, seat=0, deal_number=0)
    assert response["schema_version"] == "tuppi.analysis.completed_deal.v2"
    assert response["deal_ref"].endswith("/deal:0")
    assert response["summary"]["diagnostic_count"] == len(response["analyses"])
    assert all(item["deal_number"] == 0 for item in response["analyses"])
    assert "/deal:1" not in json.dumps(response, sort_keys=True)
    validate_instance(
        response,
        "https://example.invalid/tuppi/schemas/network/completed_deal_analysis.schema.json",
    )


def test_completed_deal_analysis_is_available_to_every_participant_between_deals() -> None:
    """A finished deal is reviewable mid-match, in a practice or human room.

    All 52 of its cards were played publicly and the next deal is an independent
    shuffle, so waiting for 52 protected nothing.
    """

    manager = RoomManager()
    room, host = manager.create_room(
        display_name="Pelaaja",
        ai_seats=frozenset({1, 2, 3}),
    )
    room.runner = _one_completed_deal_runner()
    assert not room.runner.terminal
    response = manager.completed_deal_analysis_for_session(
        code=room.code,
        token=host.token,
        deal_number=0,
    )
    assert response["seat"] == 0

    competitive = RoomManager()
    room, host = competitive.create_room(display_name="Isäntä")
    _, guest = competitive.join_room(code=room.code, display_name="Vierailija")
    room.runner = _one_completed_deal_runner()
    assert not room.runner.terminal
    for session in (host, guest):
        seat_response = competitive.completed_deal_analysis_for_session(
            code=room.code,
            token=session.token,
            deal_number=0,
        )
        # Each participant receives only their own seat's review.
        assert seat_response["seat"] == session.seat
        assert all(item["seat"] == session.seat for item in seat_response["analyses"])


def test_a_deal_still_in_progress_stays_closed() -> None:
    manager = RoomManager()
    room, host = manager.create_room(
        display_name="Pelaaja",
        ai_seats=frozenset({1, 2, 3}),
    )
    room.runner = _one_completed_deal_runner()
    # Deal 0 is complete; deal 1 is the one being played.
    assert len(room.runner.state.completed_deals) == 1
    with pytest.raises(RoomError, match="deal_not_complete"):
        manager.completed_deal_analysis_for_session(
            code=room.code,
            token=host.token,
            deal_number=1,
        )
    with pytest.raises(RoomError, match="deal_not_complete"):
        manager.completed_deal_analysis_for_session(
            code=room.code,
            token=host.token,
            deal_number=-1,
        )


def test_post_match_analysis_still_requires_a_finished_match() -> None:
    """Opening per-deal review must not open the whole-match endpoint early."""

    manager = RoomManager()
    room, host = manager.create_room(
        display_name="Pelaaja",
        ai_seats=frozenset({1, 2, 3}),
    )
    room.runner = _one_completed_deal_runner()
    with pytest.raises(RoomError, match="match_not_complete"):
        manager.post_match_analysis_for_session(code=room.code, token=host.token)


def test_empty_review_response_is_valid_for_a_completed_match_with_no_findings() -> None:
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
