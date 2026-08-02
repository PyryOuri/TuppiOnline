from __future__ import annotations

from tuppi_agents import phase4_registry, phase4_team_specifications
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
from tuppi_eval.deals import DealBank, DealerPolicy, generate_deal_bank
from tuppi_eval.identities import TeamSpecification
from tuppi_eval.schedules import (
    CANONICAL_SCHEDULE_DESIGN,
    EvaluationMode,
    Schedule,
    build_canonical_schedule,
)
from tuppi_rules import MatchScore


ENGINE_IDENTITY = "tuppi_engine:phase2"


def phase4_bank(
    *,
    count: int = 1,
    root_seed: int | str = 4321,
    starting_score: MatchScore | None = None,
) -> DealBank:
    return generate_deal_bank(
        count=count,
        root_seed=root_seed,
        dealer_policy=DealerPolicy.ROUND_ROBIN,
        initial_dealer=0,
        starting_score=starting_score or MatchScore(),
        creation_metadata={"purpose": "phase4_tests"},
    )


def phase4_comparison(
    *,
    bank: DealBank,
    team_a: TeamSpecification,
    team_b: TeamSpecification,
    mode: EvaluationMode = EvaluationMode.DEAL,
    match_sequence_length: int | None = None,
    description: str = "Phase 4 test comparison.",
) -> tuple[Schedule, EvaluationConfiguration]:
    registry = phase4_registry()
    schedule = build_canonical_schedule(
        deal_bank=bank,
        team_a=team_a,
        team_b=team_b,
        mode=mode,
        match_sequence_length=match_sequence_length,
    )
    config = EvaluationConfiguration.build(
        ruleset_id="project_target_v1",
        engine_identity=ENGINE_IDENTITY,
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
        failure_policy=FailurePolicy.CONTINUE,
        output_mode=OutputMode.RAW_AND_SUMMARY,
        confidence_level=0.95,
        bootstrap_replicates=50,
        permutation_replicates=50,
        primary_metric=PrimaryMetric.PAIRED_DUPLICATE_UTILITY,
        seed_hierarchy=SeedHierarchy(
            deal_root_seed=bank.root_seed,
            agent_root_seed=2718,
            analysis_seed=31415,
        ),
        timeouts=TimeoutLimits(
            per_action_seconds=None, per_deal_seconds=None, per_match_seconds=None
        ),
        sequential_protocol=SequentialProtocol(
            mode=SequentialMode.FIXED_SAMPLE,
            maximum_base_deals=len(bank.base_deals),
            interim_checkpoints=(),
            stopping_boundaries=(),
        ),
        software_environment={"implementation": "phase4_tests"},
        description=description,
    )
    return schedule, config


def team(name: str) -> TeamSpecification:
    return phase4_team_specifications()[name]
