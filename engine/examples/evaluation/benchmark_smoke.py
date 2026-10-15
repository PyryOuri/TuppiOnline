"""Finite diagnostic evaluator benchmark; no performance threshold is asserted."""

from __future__ import annotations

from pathlib import Path
import platform
import sys
from tempfile import TemporaryDirectory
import time
import tracemalloc

from tuppi_eval.arena import run_evaluation, summarize_run_directory
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
from tuppi_eval.deals import DealerPolicy, generate_deal_bank
from tuppi_eval.identities import TeamSpecification
from tuppi_eval.records import evaluation_result_to_data
from tuppi_eval.registry import baseline_registry
from tuppi_eval.schedules import CANONICAL_SCHEDULE_DESIGN, build_canonical_schedule
from tuppi_eval.serialization import canonical_json_bytes, canonical_json_text
from tuppi_rules import MatchScore


BASE_DEALS = 20
SERIALIZATION_REPETITIONS = 50


def inputs(base_deals: int):
    registry = baseline_registry()
    by_family = {item.agent_family: item for item in registry.specifications}
    first = by_family["first_legal"].agent_id
    low = by_family["lowest_legal_card"].agent_id
    high = by_family["highest_legal_card"].agent_id
    team_a = TeamSpecification.build(
        component_agent_ids=(first, first),
        partner_convention_id=None,
        shared_instances=False,
        description="Benchmark first-legal baseline.",
    )
    team_b = TeamSpecification.build(
        component_agent_ids=(low, high),
        partner_convention_id="benchmark_low_high_v1",
        shared_instances=False,
        description="Benchmark heterogeneous baseline.",
    )
    bank = generate_deal_bank(
        count=base_deals,
        root_seed=1729,
        dealer_policy=DealerPolicy.ROUND_ROBIN,
        initial_dealer=0,
        starting_score=MatchScore(),
        creation_metadata={"purpose": "diagnostic_benchmark"},
    )
    schedule = build_canonical_schedule(
        deal_bank=bank, team_a=team_a, team_b=team_b
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
        evaluation_mode=schedule.mode,
        match_sequence_length=None,
        starting_score=MatchScore(),
        dealer_policy=bank.dealer_policy,
        number_base_deals=base_deals,
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
            maximum_base_deals=base_deals,
            interim_checkpoints=(),
            stopping_boundaries=(),
        ),
        software_environment={"benchmark": "phase3_smoke_v1"},
        description="Finite diagnostic throughput smoke test.",
    )
    return bank, schedule, config


def main() -> None:
    bank, schedule, config = inputs(BASE_DEALS)
    with TemporaryDirectory(prefix="tuppi-eval-benchmark-") as temporary:
        output = Path(temporary)
        started = time.perf_counter()
        arena = run_evaluation(
            config, bank, schedule, output_directory=output
        )
        arena_seconds = time.perf_counter() - started

        started = time.perf_counter()
        for _ in range(SERIALIZATION_REPETITIONS):
            canonical_json_bytes(evaluation_result_to_data(arena.result))
        serialization_seconds = time.perf_counter() - started

        started = time.perf_counter()
        rebuilt = summarize_run_directory(output)
        summary_seconds = time.perf_counter() - started

    memory_bank, memory_schedule, memory_config = inputs(1)
    with TemporaryDirectory(prefix="tuppi-eval-memory-") as temporary:
        tracemalloc.start()
        run_evaluation(
            memory_config,
            memory_bank,
            memory_schedule,
            output_directory=temporary,
        )
        current_bytes, peak_bytes = tracemalloc.get_traced_memory()
        tracemalloc.stop()

    report = {
        "arena_seconds": arena_seconds,
        "base_deals": BASE_DEALS,
        "failure_count": arena.result.failure_count,
        "games_per_second": len(schedule.entries) / arena_seconds,
        "memory_trace_transformed_games": len(memory_schedule.entries),
        "platform": platform.platform(),
        "python_version": sys.version.split()[0],
        "result_serialization_repetitions": SERIALIZATION_REPETITIONS,
        "result_serialization_seconds": serialization_seconds,
        "schema_version": "tuppi.eval.performance_smoke.v1",
        "semantic_result_rebuilt": rebuilt.result_id == arena.result.result_id,
        "summary_rebuild_seconds": summary_seconds,
        "tracemalloc_current_bytes": current_bytes,
        "tracemalloc_peak_bytes": peak_bytes,
        "transformed_games": len(schedule.entries),
    }
    print(canonical_json_text(report))


if __name__ == "__main__":
    main()
