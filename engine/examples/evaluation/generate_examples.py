"""Regenerate the small deterministic Phase 3 evaluation examples."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from tuppi_engine import PlayCardAction, action_to_data
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
    evaluation_config_to_data,
)
from tuppi_eval.crossplay import (
    CROSSPLAY_CELL_SCHEMA_VERSION,
    CROSSPLAY_MATRIX_SCHEMA_VERSION,
    CrossplayCell,
    CrossplayCellStatus,
    CrossplayMatrix,
    crossplay_matrix_to_data,
)
from tuppi_eval.deals import DealerPolicy, deal_bank_to_data, generate_deal_bank
from tuppi_eval.identities import (
    AgentSpecification,
    DeterminismClass,
    SeedPolicy,
    TeamSpecification,
    team_spec_to_data,
)
from tuppi_eval.records import (
    DuplicateBlockRecord,
    PromotionDecision,
    PromotionOutcome,
    duplicate_block_to_data,
    game_record_from_data,
    game_record_to_data,
    promotion_decision_to_data,
)
from tuppi_eval.registry import AgentRegistry, baseline_registry
from tuppi_eval.schedules import (
    CANONICAL_SCHEDULE_DESIGN,
    build_canonical_schedule,
)
from tuppi_eval.serialization import atomic_write_canonical_json, content_digest
from tuppi_rules import FULL_DECK, MatchScore


OUTPUT = Path(__file__).resolve().parent


def teams(registry: AgentRegistry) -> tuple[TeamSpecification, TeamSpecification]:
    by_family = {item.agent_family: item for item in registry.specifications}
    homogeneous = TeamSpecification.build(
        component_agent_ids=(
            by_family["first_legal"].agent_id,
            by_family["first_legal"].agent_id,
        ),
        partner_convention_id=None,
        shared_instances=False,
        description="Homogeneous first-legal baseline fixture.",
    )
    heterogeneous = TeamSpecification.build(
        component_agent_ids=(
            by_family["lowest_legal_card"].agent_id,
            by_family["highest_legal_card"].agent_id,
        ),
        partner_convention_id="baseline_asymmetric_order_v1",
        shared_instances=False,
        description="Heterogeneous low/high baseline fixture.",
    )
    return homogeneous, heterogeneous


def config_for(bank, registry, team_a, team_b) -> EvaluationConfiguration:
    schedule = build_canonical_schedule(
        deal_bank=bank, team_a=team_a, team_b=team_b
    )
    return EvaluationConfiguration.build(
        ruleset_id="project_target_v1",
        engine_identity="tuppi_engine:phase2-d3a8331",
        deal_bank_id=bank.deal_bank_id,
        agent_specifications=registry.specifications,
        agent_registry_digest=registry.registry_digest,
        team_a=team_a,
        team_b=team_b,
        schedule_id=schedule.schedule_id,
        schedule_design_id=CANONICAL_SCHEDULE_DESIGN,
        evaluation_mode=schedule.mode,
        match_sequence_length=None,
        starting_score=MatchScore(),
        dealer_policy=bank.dealer_policy,
        number_base_deals=len(bank.base_deals),
        transformations_applied=tuple(
            item.transformation_id for item in schedule.transformations
        ),
        failure_policy=FailurePolicy.CONTINUE,
        output_mode=OutputMode.RAW_AND_SUMMARY,
        confidence_level=0.95,
        bootstrap_replicates=1000,
        permutation_replicates=1000,
        primary_metric=PrimaryMetric.PAIRED_DUPLICATE_UTILITY,
        seed_hierarchy=SeedHierarchy(1729, 2718, 31415),
        timeouts=TimeoutLimits(None, None, None),
        sequential_protocol=SequentialProtocol(
            mode=SequentialMode.FIXED_SAMPLE,
            maximum_base_deals=len(bank.base_deals),
            interim_checkpoints=(),
            stopping_boundaries=(),
        ),
        software_environment={
            "evaluation_package": "tuppi-research",
            "fixture": True,
        },
        description="One-deal deterministic baseline comparison fixture.",
    )


def synthetic_block() -> DuplicateBlockRecord:
    evaluation_id = f"eval:{content_digest({'fixture': 'synthetic-statistics'})}"
    game_ids = tuple(
        f"game:{content_digest({'fixture_game': index})}" for index in range(8)
    )
    identity = {
        "base_deal_id": f"base:{content_digest({'fixture_deal': 0})}",
        "block_index": 0,
        "block_outcome": "win",
        "complete": True,
        "evaluation_id": evaluation_id,
        "game_record_ids": list(game_ids),
        "invalid_game_count": 0,
        "paired_utility": 2.0,
        "schema_version": "tuppi.eval.duplicate_block_record.v1",
        "valid_game_count": 8,
    }
    return DuplicateBlockRecord(
        block_record_id=f"block:{content_digest(identity)}",
        evaluation_id=evaluation_id,
        block_index=0,
        base_deal_id=identity["base_deal_id"],
        game_record_ids=game_ids,
        valid_game_count=8,
        invalid_game_count=0,
        complete=True,
        paired_utility=2.0,
        block_outcome="win",
    )


def cell(left: str, right: str, value: float) -> CrossplayCell:
    identity = {
        "column_team_id": right,
        "evaluation_id": f"eval:{content_digest({'pair': [left, right]})}",
        "failure_count": 0,
        "independent_base_deals": 1,
        "mean_paired_utility_row_orientation": value,
        "result_id": f"result:{content_digest({'pair_result': [left, right]})}",
        "row_team_id": left,
        "schema_version": CROSSPLAY_CELL_SCHEMA_VERSION,
        "status": CrossplayCellStatus.VALID.value,
    }
    return CrossplayCell(
        cell_id=f"cell:{content_digest(identity)}",
        row_team_id=left,
        column_team_id=right,
        status=CrossplayCellStatus.VALID,
        evaluation_id=identity["evaluation_id"],
        result_id=identity["result_id"],
        mean_paired_utility_row_orientation=value,
        independent_base_deals=1,
        failure_count=0,
    )


def matrix(bank, team_ids: tuple[str, str]) -> CrossplayMatrix:
    cells = (
        cell(team_ids[0], team_ids[0], 0.0),
        cell(team_ids[0], team_ids[1], 2.0),
        cell(team_ids[1], team_ids[1], 0.0),
    )
    identity = {
        "cells": [item.identity_data() for item in cells],
        "deal_bank_id": bank.deal_bank_id,
        "schema_version": CROSSPLAY_MATRIX_SCHEMA_VERSION,
        "team_ids": list(team_ids),
    }
    return CrossplayMatrix(
        matrix_id=f"matrix:{content_digest(identity)}",
        team_ids=team_ids,
        deal_bank_id=bank.deal_bank_id,
        cells=cells,
    )


def failure_record(bank) -> dict[str, object]:
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
        description="Deliberately illegal evaluator fixture.",
    )
    registry = AgentRegistry.build((illegal,))
    team = TeamSpecification.build(
        component_agent_ids=(illegal.agent_id, illegal.agent_id),
        partner_convention_id=None,
        shared_instances=False,
        description="Structured failure fixture team.",
    )
    config = config_for(bank, registry, team, team)
    schedule = build_canonical_schedule(
        deal_bank=bank, team_a=team, team_b=team
    )
    with TemporaryDirectory(prefix="tuppi-eval-fixture-") as temporary:
        result = run_evaluation(
            config, bank, schedule, output_directory=temporary
        ).result
    data = game_record_to_data(result.game_records[0])
    data["duration_seconds"] = 0.0
    data["action_durations_seconds"] = []
    game_record_from_data(data)
    return data


def main() -> None:
    registry = baseline_registry()
    homogeneous, heterogeneous = teams(registry)
    bank = generate_deal_bank(
        count=1,
        root_seed=1729,
        dealer_policy=DealerPolicy.ROUND_ROBIN,
        initial_dealer=0,
        starting_score=MatchScore(),
        creation_metadata={
            "created_by": "examples/evaluation/generate_examples.py",
            "purpose": "small_ci_fixture",
        },
    )
    comparison = config_for(bank, registry, homogeneous, heterogeneous)
    atomic_write_canonical_json(OUTPUT / "small_deal_bank.json", deal_bank_to_data(bank))
    atomic_write_canonical_json(
        OUTPUT / "baseline_comparison.json",
        evaluation_config_to_data(comparison),
    )
    atomic_write_canonical_json(
        OUTPUT / "homogeneous_vs_heterogeneous.json",
        {
            "schema_version": "tuppi.eval.team_comparison_example.v1",
            "team_a": team_spec_to_data(homogeneous),
            "team_b": team_spec_to_data(heterogeneous),
        },
    )
    block = synthetic_block()
    atomic_write_canonical_json(
        OUTPUT / "duplicate_block.json", duplicate_block_to_data(block)
    )
    ordered_teams = tuple(sorted((homogeneous, heterogeneous), key=lambda item: item.team_id))
    comparisons = tuple(
        config_for(bank, registry, left, right)
        for left_index, left in enumerate(ordered_teams)
        for right in ordered_teams[left_index:]
    )
    atomic_write_canonical_json(
        OUTPUT / "baseline_crossplay.json",
        {
            "comparisons": [evaluation_config_to_data(item) for item in comparisons],
            "deal_bank_id": bank.deal_bank_id,
            "include_missing": False,
            "schema_version": "tuppi.eval.crossplay_request.v1",
        },
    )
    atomic_write_canonical_json(
        OUTPUT / "small_crossplay_matrix.json",
        crossplay_matrix_to_data(matrix(bank, tuple(item.team_id for item in ordered_teams))),
    )
    atomic_write_canonical_json(
        OUTPUT / "structured_failure.json", failure_record(bank)
    )
    schedule = build_canonical_schedule(
        deal_bank=bank, team_a=homogeneous, team_b=heterogeneous
    )
    atomic_write_canonical_json(
        OUTPUT / "interrupted_resume.json",
        {
            "completed_before_interrupt": [
                entry.entry_id for entry in schedule.entries[:3]
            ],
            "executed_after_resume": [
                entry.entry_id for entry in schedule.entries[3:]
            ],
            "final_completed_entry_count": 8,
            "repeated_entry_count": 0,
            "schema_version": "tuppi.eval.resume_example.v1",
        },
    )
    atomic_write_canonical_json(
        OUTPUT / "synthetic_statistics.json",
        {
            "analysis_seed": 31415,
            "expected_independent_base_deals": 4,
            "expected_mean_paired_utility": 2.0,
            "expected_transformed_games": 32,
            "paired_utilities": [4.0, -2.0, 0.0, 6.0],
            "schema_version": "tuppi.eval.synthetic_statistics.v1",
        },
    )
    promotion = PromotionDecision.build(
        candidate_team_id=heterogeneous.team_id,
        champion_team_id=homogeneous.team_id,
        evaluation_result_ids=(f"result:{content_digest({'fixture_result': 1})}",),
        primary_metric="paired_duplicate_utility_points_v1",
        confidence_interval=None,
        historical_agent_results={"status": "baseline_only"},
        contract_regressions={"status": "insufficient_sample"},
        score_state_regressions={"status": "insufficient_sample"},
        failure_rate=0.0,
        latency_budget_seconds=1.0,
        reproducible=True,
        outcome=PromotionOutcome.INCONCLUSIVE,
        rationale="Baseline fixture only; no strategic-strength claim.",
    )
    atomic_write_canonical_json(
        OUTPUT / "promotion_decision.json",
        promotion_decision_to_data(promotion),
    )


if __name__ == "__main__":
    main()
