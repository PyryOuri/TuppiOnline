from __future__ import annotations

from pathlib import Path

import pytest

from tuppi_engine import (
    DealOutcome,
    DealSequenceError,
    EventType,
    ExplicitMatchInput,
    FixedScriptAgent,
    MatchResult,
    TerminalStateError,
    agent_script_from_data,
    begin_explicit_deal,
    match_input_from_data,
    strict_json_load_file,
)
from tuppi_engine.runner import run_match_input
from tuppi_rules import Contract, MatchScore, Team


ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "examples/engine/project_target_v1"


def _load(name: str, script_name: str):
    match_input = match_input_from_data(strict_json_load_file(EXAMPLES / name))
    actions = agent_script_from_data(
        strict_json_load_file(EXAMPLES / script_name),
        expected_match_input_id=match_input.match_input_id,
    )
    by_seat = tuple(
        tuple(action for action in actions if action.seat == seat) for seat in range(4)
    )
    agents = tuple(FixedScriptAgent(actions) for actions in by_seat)
    result = run_match_input(match_input, agents, expected_actions=actions)
    return match_input, actions, result


def _assert_event_sequence(result) -> None:
    assert tuple(event.event_index for event in result.public_events) == tuple(
        range(len(result.public_events))
    )
    assert result.public_events[0].event_type is EventType.DEAL_STARTED
    for deal in result.deals:
        kinds = tuple(event.event_type for event in deal.public_result.events)
        assert kinds.count(EventType.CONTRACT_RESOLVED) == 1
        assert kinds.count(EventType.TRICK_STARTED) == 13
        assert kinds.count(EventType.CARD_PLAYED) == 52
        assert kinds.count(EventType.TRICK_COMPLETED) == 13
        assert kinds.count(EventType.DEAL_COMPLETED) == 1
        assert kinds.count(EventType.MATCH_SCORE_CHANGED) == 1
        assert kinds[-1] in (EventType.DEALER_ROTATED, EventType.MATCH_COMPLETED)


def test_complete_all_nolo_fixture_and_exact_events() -> None:
    _, actions, result = _load(
        "valid_one_deal_match.json", "full_nolo_script.json"
    )
    deal = result.deals[0].public_result
    assert len(actions) == 56
    assert deal.contract is Contract.NOLO
    assert deal.declarer is None
    assert deal.team_tricks == (0, 13)
    assert deal.deal_score.winner_team is Team.TEAM_0
    assert deal.deal_score.points == 28
    assert deal.score_after == MatchScore(28, 0)
    assert len(result.public_events) == 87
    _assert_event_sequence(result)


def test_complete_successful_rami_fixture() -> None:
    _, actions, result = _load(
        "successful_rami_match.json", "successful_rami_script.json"
    )
    deal = result.deals[0].public_result
    assert len(actions) == 53
    assert deal.contract is Contract.RAMI
    assert deal.declarer == 1
    assert deal.team_tricks == (0, 13)
    assert deal.outcome is DealOutcome.MADE_RAMI
    assert deal.deal_score.winner_team is Team.TEAM_1
    assert deal.deal_score.points == 28
    assert deal.score_after == MatchScore(0, 28)
    _assert_event_sequence(result)


def test_complete_stolen_rami_fixture_and_overshoot_match() -> None:
    _, actions, result = _load(
        "stolen_rami_match.json", "stolen_rami_script.json"
    )
    deal = result.deals[0].public_result
    assert len(actions) == 53
    assert deal.declarer == 0
    assert deal.team_tricks == (0, 13)
    assert deal.outcome is DealOutcome.STOLEN_RAMI
    assert deal.deal_score.points == 56
    assert deal.score_after == MatchScore(0, 56)
    assert result.terminal
    assert isinstance(result.match_result, MatchResult)
    assert result.match_result.winner_team is Team.TEAM_1
    assert result.public_events[-1].event_type is EventType.MATCH_COMPLETED
    _assert_event_sequence(result)


def test_complete_verbal_color_fallback_fixture() -> None:
    _, _, result = _load(
        "verbal_fallback_match.json", "verbal_fallback_script.json"
    )
    deal = result.deals[0].public_result
    show = deal.show_actions[0]
    assert show.declared_contract is Contract.RAMI
    assert show.shown_card.to_code() == "3C"
    assert show.verbal_required is True
    assert len(deal.completed_tricks) == 13
    assert sum(deal.team_tricks) == 13
    _assert_event_sequence(result)


def test_complete_no_eligible_rank_fallback_fixture() -> None:
    _, _, result = _load(
        "no_eligible_show_match.json", "no_eligible_show_script.json"
    )
    deal = result.deals[0].public_result
    show = deal.show_actions[0]
    assert show.shown_card.to_code() == "2H"
    assert show.verbal_required is True
    assert deal.team_tricks == (4, 9)
    assert deal.score_after == MatchScore(0, 12)
    assert len(deal.completed_tricks) == 13
    _assert_event_sequence(result)


def test_complete_exact_52_match_progression_reset_and_rotation() -> None:
    match_input, actions, result = _load(
        "exact_52_match.json", "exact_52_script.json"
    )
    assert len(match_input.deals) == 4
    assert len(actions) == 216
    assert [deal.public_result.dealer for deal in result.deals] == [0, 1, 2, 3]
    assert [deal.public_result.score_after.as_tuple() for deal in result.deals] == [
        (0, 28),
        (0, 0),
        (0, 28),
        (0, 52),
    ]
    assert [deal.public_result.team_tricks for deal in result.deals] == [
        (0, 13),
        (13, 0),
        (0, 13),
        (1, 12),
    ]
    assert result.final_score == MatchScore(0, 52)
    assert result.terminal
    assert result.next_dealer is None
    assert result.match_result.winner_team is Team.TEAM_1  # type: ignore[union-attr]
    kinds = tuple(event.event_type for event in result.public_events)
    assert kinds.count(EventType.DEALER_ROTATED) == 3
    assert kinds.count(EventType.MATCH_COMPLETED) == 1
    assert kinds[-1] is EventType.MATCH_COMPLETED
    assert len(result.public_events) == 340
    _assert_event_sequence(result)


def test_extra_explicit_deal_after_terminal_match_is_rejected() -> None:
    match_input = match_input_from_data(
        strict_json_load_file(EXAMPLES / "exact_52_match.json")
    )
    extra = ExplicitMatchInput(
        match_ref=match_input.match_ref,
        initial_score=match_input.initial_score,
        initial_dealer=match_input.initial_dealer,
        deals=match_input.deals + (match_input.deals[0],),
    )
    actions = agent_script_from_data(
        strict_json_load_file(EXAMPLES / "exact_52_script.json"),
        expected_match_input_id=match_input.match_input_id,
    )
    by_seat = tuple(
        tuple(action for action in actions if action.seat == seat) for seat in range(4)
    )
    agents = tuple(FixedScriptAgent(items) for items in by_seat)
    with pytest.raises(DealSequenceError, match="already completed"):
        run_match_input(extra, agents)


def test_runner_calls_only_current_actor_with_player_observation() -> None:
    match_input = match_input_from_data(
        strict_json_load_file(EXAMPLES / "valid_one_deal_match.json")
    )

    class RecordingAgent:
        def __init__(self, seat):
            self.seat = seat
            self.calls = []

        @property
        def identity(self):
            return f"recording-seat-{self.seat}"

        def choose_action(self, observation):
            assert observation.observing_seat == self.seat
            assert observation.current_actor == self.seat
            self.calls.append(observation)
            return observation.legal_actions[0]

    agents = tuple(RecordingAgent(seat) for seat in range(4))
    result = run_match_input(match_input, agents)
    assert result.deals
    assert all(agent.calls for agent in agents)
    assert sum(len(agent.calls) for agent in agents) == 56


def test_same_scripted_execution_is_byte_identical() -> None:
    from tuppi_engine import canonical_json_bytes, public_event_log_to_data
    from tuppi_engine import research_run_result_to_data

    first_input, _, first = _load(
        "successful_rami_match.json", "successful_rami_script.json"
    )
    second_input, _, second = _load(
        "successful_rami_match.json", "successful_rami_script.json"
    )
    assert first_input == second_input
    assert canonical_json_bytes(research_run_result_to_data(first)) == canonical_json_bytes(
        research_run_result_to_data(second)
    )
    assert canonical_json_bytes(
        public_event_log_to_data(first.public_events, match_ref=first.match_ref)
    ) == canonical_json_bytes(
        public_event_log_to_data(second.public_events, match_ref=second.match_ref)
    )
