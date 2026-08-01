from __future__ import annotations

from dataclasses import replace

from tuppi_eval.config import (
    EvaluationConfiguration,
    FailurePolicy,
    OutputMode,
    PrimaryMetric,
    SeedHierarchy,
    SequentialMode,
    SequentialProtocol,
    TimeoutLimits,
)
from tuppi_eval.deals import DealerPolicy, DealBank, generate_deal_bank
from tuppi_eval.identities import TeamSpecification
from tuppi_eval.records import DuplicateBlockRecord
from tuppi_eval.registry import AgentRegistry, baseline_registry
from tuppi_eval.schedules import (
    CANONICAL_SCHEDULE_DESIGN,
    EvaluationMode,
    Schedule,
    build_canonical_schedule,
)
from tuppi_eval.serialization import content_digest
from tuppi_rules import MatchScore


def baseline_teams(
    registry: AgentRegistry | None = None,
) -> tuple[AgentRegistry, TeamSpecification, TeamSpecification]:
    registry = registry or baseline_registry()
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
    return registry, team_a, team_b


def comparison_config(
    *,
    bank: DealBank,
    registry: AgentRegistry,
    team_a: TeamSpecification,
    team_b: TeamSpecification,
    mode: EvaluationMode = EvaluationMode.DEAL,
    match_sequence_length: int | None = None,
    timeouts: TimeoutLimits | None = None,
    failure_policy: FailurePolicy = FailurePolicy.CONTINUE,
) -> tuple[Schedule, EvaluationConfiguration]:
    schedule = build_canonical_schedule(
        deal_bank=bank,
        team_a=team_a,
        team_b=team_b,
        mode=mode,
        match_sequence_length=match_sequence_length,
    )
    config = EvaluationConfiguration.build(
        ruleset_id="project_target_v1",
        engine_identity="tuppi_engine:phase2",
        deal_bank_id=bank.deal_bank_id,
        agent_specifications=registry.specifications,
        agent_registry_digest=registry.registry_digest,
        team_a=team_a,
        team_b=team_b,
        schedule_id=schedule.schedule_id,
        schedule_design_id=CANONICAL_SCHEDULE_DESIGN,
        evaluation_mode=mode,
        match_sequence_length=match_sequence_length,
        starting_score=bank.base_deals[0].starting_score,
        dealer_policy=bank.dealer_policy,
        number_base_deals=len(bank.base_deals),
        transformations_applied=tuple(
            item.transformation_id for item in schedule.transformations
        ),
        failure_policy=failure_policy,
        output_mode=OutputMode.RAW_AND_SUMMARY,
        confidence_level=0.95,
        bootstrap_replicates=100,
        permutation_replicates=100,
        primary_metric=PrimaryMetric.PAIRED_DUPLICATE_UTILITY,
        seed_hierarchy=SeedHierarchy(
            deal_root_seed=bank.root_seed,
            agent_root_seed=2718,
            analysis_seed=31415,
        ),
        timeouts=timeouts
        or TimeoutLimits(
            per_action_seconds=None,
            per_deal_seconds=None,
            per_match_seconds=None,
        ),
        sequential_protocol=SequentialProtocol(
            mode=SequentialMode.FIXED_SAMPLE,
            maximum_base_deals=len(bank.base_deals),
            interim_checkpoints=(),
            stopping_boundaries=(),
        ),
        software_environment={"implementation": "test"},
        description="Small deterministic baseline comparison.",
    )
    return schedule, config


def evaluation_inputs(
    count: int = 1,
    *,
    starting_score: MatchScore = MatchScore(),
    mode: EvaluationMode = EvaluationMode.DEAL,
    match_sequence_length: int | None = None,
) -> tuple[
    AgentRegistry,
    TeamSpecification,
    TeamSpecification,
    DealBank,
    Schedule,
    EvaluationConfiguration,
]:
    registry, team_a, team_b = baseline_teams()
    bank = generate_deal_bank(
        count=count,
        root_seed=1729,
        dealer_policy=DealerPolicy.ROUND_ROBIN,
        initial_dealer=0,
        starting_score=starting_score,
        creation_metadata={"purpose": "test"},
    )
    schedule, config = comparison_config(
        bank=bank,
        registry=registry,
        team_a=team_a,
        team_b=team_b,
        mode=mode,
        match_sequence_length=match_sequence_length,
    )
    return registry, team_a, team_b, bank, schedule, config


def synthetic_block(value: float | None, index: int) -> DuplicateBlockRecord:
    game_ids = tuple(
        f"game:{content_digest({'block': index, 'game': game})}"
        for game in range(8)
    )
    complete = value is not None
    outcome = None
    if value is not None:
        outcome = "win" if value > 0 else "loss" if value < 0 else "tie"
    identity = {
        "base_deal_id": f"base:{content_digest({'block': index})}",
        "block_index": index,
        "block_outcome": outcome,
        "complete": complete,
        "evaluation_id": f"eval:{content_digest({'synthetic': True})}",
        "game_record_ids": list(game_ids),
        "invalid_game_count": 0 if complete else 1,
        "paired_utility": value,
        "schema_version": "tuppi.eval.duplicate_block_record.v1",
        "valid_game_count": 8 if complete else 7,
    }
    return DuplicateBlockRecord(
        block_record_id=f"block:{content_digest(identity)}",
        evaluation_id=identity["evaluation_id"],
        block_index=index,
        base_deal_id=identity["base_deal_id"],
        game_record_ids=game_ids,
        valid_game_count=identity["valid_game_count"],
        invalid_game_count=identity["invalid_game_count"],
        complete=complete,
        paired_utility=value,
        block_outcome=outcome,
    )
