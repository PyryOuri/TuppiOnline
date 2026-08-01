from __future__ import annotations

from tuppi_eval.arena import run_evaluation
from tuppi_eval.config import (
    EvaluationConfiguration,
    FailurePolicy,
    OutputMode,
    PrimaryMetric,
    SeedHierarchy,
    SequentialMode,
    SequentialProtocol,
    TimeoutLimits,
    evaluation_config_from_data,
    evaluation_config_to_data,
)
from tuppi_eval.deals import DealerPolicy, generate_deal_bank
from tuppi_eval.identities import TeamSpecification
from tuppi_eval.registry import baseline_registry
from tuppi_eval.schedules import (
    CANONICAL_SCHEDULE_DESIGN,
    EvaluationMode,
    build_canonical_schedule,
)
from tuppi_rules import MatchScore


def _inputs(count: int = 1):
    registry = baseline_registry()
    by_family = {item.agent_family: item for item in registry.specifications}
    team_a = TeamSpecification.build(
        component_agent_ids=(
            by_family["first_legal"].agent_id,
            by_family["first_legal"].agent_id,
        ),
        partner_convention_id=None,
        shared_instances=False,
        description="Homogeneous first-legal evaluator fixture team.",
    )
    team_b = TeamSpecification.build(
        component_agent_ids=(
            by_family["lowest_legal_card"].agent_id,
            by_family["highest_legal_card"].agent_id,
        ),
        partner_convention_id="baseline_asymmetric_order_v1",
        shared_instances=False,
        description="Heterogeneous low/high evaluator fixture team.",
    )
    bank = generate_deal_bank(
        count=count,
        root_seed=1729,
        dealer_policy=DealerPolicy.ROUND_ROBIN,
        initial_dealer=0,
        starting_score=MatchScore(),
        creation_metadata={"purpose": "test"},
    )
    schedule = build_canonical_schedule(
        deal_bank=bank,
        team_a=team_a,
        team_b=team_b,
    )
    config = EvaluationConfiguration.build(
        ruleset_id="project_target_v1",
        engine_identity="tuppi_engine:1",
        deal_bank_id=bank.deal_bank_id,
        agent_specifications=registry.specifications,
        agent_registry_digest=registry.registry_digest,
        team_a=team_a,
        team_b=team_b,
        schedule_id=schedule.schedule_id,
        schedule_design_id=CANONICAL_SCHEDULE_DESIGN,
        evaluation_mode=EvaluationMode.DEAL,
        match_sequence_length=None,
        starting_score=MatchScore(),
        dealer_policy=DealerPolicy.ROUND_ROBIN,
        number_base_deals=count,
        transformations_applied=tuple(
            item.transformation_id for item in schedule.transformations
        ),
        failure_policy=FailurePolicy.CONTINUE,
        output_mode=OutputMode.RAW_AND_SUMMARY,
        confidence_level=0.95,
        bootstrap_replicates=100,
        permutation_replicates=100,
        primary_metric=PrimaryMetric.PAIRED_DUPLICATE_UTILITY,
        seed_hierarchy=SeedHierarchy(
            deal_root_seed=1729,
            agent_root_seed=2718,
            analysis_seed=31415,
        ),
        timeouts=TimeoutLimits(
            per_action_seconds=None,
            per_deal_seconds=None,
            per_match_seconds=None,
        ),
        sequential_protocol=SequentialProtocol(
            mode=SequentialMode.FIXED_SAMPLE,
            maximum_base_deals=count,
            interim_checkpoints=(),
            stopping_boundaries=(),
        ),
        software_environment={"implementation": "test"},
        description="Small deterministic baseline comparison.",
    )
    return registry, team_a, team_b, bank, schedule, config


def test_identity_deal_schedule_and_config_round_trip() -> None:
    first = _inputs(2)
    second = _inputs(2)
    assert first[3].deal_bank_id == second[3].deal_bank_id
    assert first[4].schedule_id == second[4].schedule_id
    assert first[5].evaluation_id == second[5].evaluation_id
    restored = evaluation_config_from_data(evaluation_config_to_data(first[5]))
    assert restored == first[5]
    assert len(first[4].entries) == 16


def test_arena_runs_and_resumes_without_repeating_entries(tmp_path) -> None:
    _, _, _, bank, schedule, config = _inputs()
    first = run_evaluation(
        config, bank, schedule, output_directory=tmp_path / "run"
    )
    assert first.executed_game_count == 8
    assert first.result.failure_count == 0
    assert len(first.result.duplicate_blocks) == 1
    second = run_evaluation(
        config, bank, schedule, output_directory=tmp_path / "run"
    )
    assert second.executed_game_count == 0
    assert second.resumed_game_count == 8
    assert first.result.result_id == second.result.result_id
