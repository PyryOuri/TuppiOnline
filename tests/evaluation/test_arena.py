from __future__ import annotations

from dataclasses import replace
import json
import shutil
from statistics import fmean

import pytest

from tuppi_engine import ExplicitMatchInput, PlayCardAction, action_to_data
from tuppi_engine.runner import run_match_input
from tuppi_eval import arena as arena_module
from tuppi_eval.agents import FirstLegalAgent
from tuppi_eval.arena import run_evaluation, summarize_run_directory
from tuppi_eval.config import FailurePolicy, TimeoutLimits
from tuppi_eval.deals import DealerPolicy, generate_deal_bank
from tuppi_eval.errors import InterruptedEvaluation
from tuppi_eval.identities import (
    AgentSpecification,
    DeterminismClass,
    SeedPolicy,
    TeamSpecification,
)
from tuppi_eval.records import (
    ExecutionStatus,
    FailureKind,
    evaluation_result_from_data,
    evaluation_result_to_data,
)
from tuppi_eval.registry import AgentRegistry
from tuppi_eval.schedules import EvaluationMode
from tuppi_eval.serialization import strict_json_load_file
from tuppi_rules import FULL_DECK, MatchScore, Team, match_transition_value

from .support import baseline_teams, comparison_config, evaluation_inputs


def test_finite_run_is_semantically_deterministic_and_path_independent(tmp_path) -> None:
    _, _, _, bank, schedule, config = evaluation_inputs(2)
    first = run_evaluation(config, bank, schedule, output_directory=tmp_path / "a")
    second = run_evaluation(config, bank, schedule, output_directory=tmp_path / "b")
    assert first.result.result_id == second.result.result_id
    assert [record.record_id for record in first.result.game_records] == [
        record.record_id for record in second.result.game_records
    ]
    assert first.result.summary["primary_inference"]["independent_base_deals"] == 2
    assert first.result.summary["primary_inference"]["transformed_games"] == 16
    supporting = first.result.summary["supporting_inference"]
    assert supporting["available"] is True
    assert supporting["promotion_eligible"] is False
    assert supporting["role"] == "development_screening_only"
    assert supporting["deal_win_advantage"]["independent_base_deals"] == 2
    assert supporting["deal_win_advantage"]["transformed_games"] == 16
    by_id = {record.record_id: record for record in first.result.game_records}
    expected_deal_wins = []
    expected_transitions = []
    for block in first.result.duplicate_blocks:
        block_records = tuple(by_id[record_id] for record_id in block.game_record_ids)
        expected_deal_wins.append(
            fmean(
                1.0 if record.winner_external_team == "A" else -1.0
                for record in block_records
            )
        )
        expected_transitions.append(
            fmean(
                match_transition_value(
                    MatchScore(*record.score_after),
                    Team(0 if record.seat_external_teams[0] == "A" else 1),
                )
                for record in block_records
            )
        )
    assert supporting["deal_win_advantage"]["mean_paired_utility"] == fmean(
        expected_deal_wins
    )
    assert supporting["deal_win_advantage"]["team_a_deal_win_probability"] == (
        1.0 + fmean(expected_deal_wins)
    ) / 2.0
    assert supporting["match_transition_utility"]["mean_paired_utility"] == fmean(
        expected_transitions
    )
    assert supporting == second.result.summary["supporting_inference"]
    assert len(tuple((tmp_path / "a" / "raw").glob("*.json"))) == 16
    assert evaluation_result_from_data(evaluation_result_to_data(first.result)) == first.result
    assert "hands" not in json.dumps(first.result.summary)


def test_resume_is_idempotent_and_shard_discovery_order_is_irrelevant(tmp_path) -> None:
    _, _, _, bank, schedule, config = evaluation_inputs()
    original = run_evaluation(
        config, bank, schedule, output_directory=tmp_path / "original"
    )
    reordered = tmp_path / "reordered"
    (reordered / "games").mkdir(parents=True)
    (reordered / "raw").mkdir()
    for source in reversed(sorted((tmp_path / "original" / "games").glob("*.json"))):
        shutil.copy2(source, reordered / "games" / source.name)
    for source in reversed(sorted((tmp_path / "original" / "raw").glob("*.json"))):
        shutil.copy2(source, reordered / "raw" / source.name)
    resumed = run_evaluation(config, bank, schedule, output_directory=reordered)
    assert resumed.executed_game_count == 0
    assert resumed.resumed_game_count == 8
    assert resumed.result.result_id == original.result.result_id
    assert len({record.entry_id for record in resumed.result.game_records}) == 8
    assert summarize_run_directory(reordered).result_id == original.result.result_id


def test_interrupted_run_resumes_without_repeating_completed_entries(tmp_path) -> None:
    _, _, _, bank, schedule, config = evaluation_inputs()
    output = tmp_path / "interrupted"
    with pytest.raises(InterruptedEvaluation):
        run_evaluation(
            config,
            bank,
            schedule,
            output_directory=output,
            max_new_games=3,
        )
    assert len(tuple((output / "games").glob("*.json"))) == 3
    assert strict_json_load_file(output / "run_status.json")["status"] == "interrupted"
    completed = run_evaluation(config, bank, schedule, output_directory=output)
    assert completed.resumed_game_count == 3
    assert completed.executed_game_count == 5
    assert strict_json_load_file(output / "run_status.json")["status"] == "complete"


def _invalid_action_inputs():
    illegal = AgentSpecification.build(
        agent_family="fixed_illegal_play",
        configuration_version="1.0.0",
        implementation_reference="tuppi_eval.agents:fixed_script_v1",
        ruleset_compatibility=("project_target_v1",),
        observation_schema_compatibility=("tuppi.engine.player_observation.v1",),
        determinism=DeterminismClass.DETERMINISTIC,
        seed_policy=SeedPolicy.NONE,
        configuration={
            "actions": [
                action_to_data(PlayCardAction(seat=seat, card=FULL_DECK[seat]))
                for seat in range(4)
            ]
        },
        model_checkpoint_id=None,
        search_budget=None,
        partner_convention_id=None,
        description="Deliberately returns play-card actions during showing.",
    )
    registry = AgentRegistry.build((illegal,))
    team = TeamSpecification.build(
        component_agent_ids=(illegal.agent_id, illegal.agent_id),
        partner_convention_id=None,
        shared_instances=False,
        description="Deliberately invalid evaluator fixture team.",
    )
    bank = generate_deal_bank(
        count=1,
        root_seed=72,
        dealer_policy=DealerPolicy.ROUND_ROBIN,
        initial_dealer=0,
        starting_score=MatchScore(),
        creation_metadata={},
    )
    schedule, config = comparison_config(
        bank=bank,
        registry=registry,
        team_a=team,
        team_b=team,
    )
    return bank, schedule, config


def test_illegal_actions_are_quarantined_and_never_scored_as_outcomes(tmp_path) -> None:
    bank, schedule, config = _invalid_action_inputs()
    arena = run_evaluation(
        config, bank, schedule, output_directory=tmp_path / "failure"
    )
    assert arena.result.failure_count == 8
    assert all(
        record.execution_status is ExecutionStatus.FAILED
        and record.failure is not None
        and record.failure.kind is FailureKind.ILLEGAL_AGENT_ACTION
        and record.signed_utility is None
        for record in arena.result.game_records
    )
    assert arena.result.summary["primary_inference"]["independent_base_deals"] == 0
    assert arena.result.summary["outcome_metrics"]["team_a_deal_win_rate"] is None
    assert len(tuple((tmp_path / "failure" / "quarantine").glob("*.json"))) == 8


def test_supporting_transition_metric_uses_terminal_and_reset_score_states(
    tmp_path,
) -> None:
    for label, starting_score, result_field in (
        ("reset", MatchScore(48, 0), "reset"),
        ("terminal", MatchScore(0, 48), "terminal"),
    ):
        _, _, _, bank, schedule, config = evaluation_inputs(
            starting_score=starting_score
        )
        arena = run_evaluation(
            config, bank, schedule, output_directory=tmp_path / label
        )
        records = arena.result.game_records
        assert any(getattr(record, result_field) for record in records)
        expected = fmean(
            match_transition_value(
                MatchScore(*record.score_after),
                Team(0 if record.seat_external_teams[0] == "A" else 1),
            )
            for record in records
        )
        supporting = arena.result.summary["supporting_inference"]
        assert (
            supporting["match_transition_utility"]["mean_paired_utility"]
            == expected
        )


def test_per_action_timeout_is_a_structured_failure(tmp_path) -> None:
    registry, team_a, team_b, bank, _, _ = evaluation_inputs()
    schedule, config = comparison_config(
        bank=bank,
        registry=registry,
        team_a=team_a,
        team_b=team_b,
        timeouts=TimeoutLimits(
            per_action_seconds=1e-15,
            per_deal_seconds=None,
            per_match_seconds=None,
        ),
    )
    arena = run_evaluation(config, bank, schedule, output_directory=tmp_path / "timeout")
    assert arena.result.failure_count == 8
    assert {
        record.failure.kind for record in arena.result.game_records if record.failure
    } == {FailureKind.TIMEOUT}


def test_agents_are_fresh_objects_for_every_entry_and_seat(tmp_path, monkeypatch) -> None:
    _, _, _, bank, schedule, config = evaluation_inputs()
    constructed: list[object] = []
    original = arena_module.construct_agent

    def recording_constructor(*args, **kwargs):
        value = original(*args, **kwargs)
        constructed.append(value)
        return value

    monkeypatch.setattr(arena_module, "construct_agent", recording_constructor)
    run_evaluation(config, bank, schedule, output_directory=tmp_path / "fresh")
    assert len(constructed) == 32
    assert len({id(value) for value in constructed}) == 32


def test_match_mode_executes_explicit_common_deal_sequence(tmp_path) -> None:
    registry, team, _ = baseline_teams()
    by_family = {item.agent_family: item for item in registry.specifications}
    first_spec = by_family["first_legal"]
    mirror = TeamSpecification.build(
        component_agent_ids=(first_spec.agent_id, first_spec.agent_id),
        partner_convention_id=None,
        shared_instances=False,
        description="First-legal mirror partnership.",
    )
    zero_bank = generate_deal_bank(
        count=1,
        root_seed=808,
        dealer_policy=DealerPolicy.ROUND_ROBIN,
        initial_dealer=0,
        starting_score=MatchScore(),
        creation_metadata={},
    )
    explicit = zero_bank.base_deals[0].explicit_deal()
    probe = run_match_input(
        ExplicitMatchInput(
            match_ref="evaluation-match-probe",
            initial_score=MatchScore(),
            initial_dealer=explicit.dealer,
            deals=(explicit,),
        ),
        tuple(FirstLegalAgent(first_spec.agent_id) for _ in range(4)),
    )
    winning_team = probe.deals[0].public_result.deal_score.winner_team.value
    score = MatchScore(51, 0) if winning_team == 0 else MatchScore(0, 51)
    bank = generate_deal_bank(
        count=1,
        root_seed=808,
        dealer_policy=DealerPolicy.ROUND_ROBIN,
        initial_dealer=0,
        starting_score=score,
        creation_metadata={},
    )
    schedule, config = comparison_config(
        bank=bank,
        registry=registry,
        team_a=mirror,
        team_b=mirror,
        mode=EvaluationMode.MATCH,
        match_sequence_length=1,
    )
    result = run_evaluation(config, bank, schedule, output_directory=tmp_path / "match")
    assert result.result.failure_count == 0
    assert all(record.terminal and record.deals_played == 1 for record in result.result.game_records)
    assert result.result.summary["outcome_metrics"]["match_win_rate_team_a"] is not None
    assert result.result.summary["supporting_inference"] == {
        "available": False,
        "promotion_eligible": False,
        "reason": (
            "Supporting deal endpoints are only defined for deal-mode duplicate "
            "blocks; use tuppi_match complete complementary pairs for strength."
        ),
        "role": "development_screening_only",
    }
