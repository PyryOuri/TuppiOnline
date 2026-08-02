"""The frozen Phase 4 baseline evaluation protocol.

This module owns the committed development deal banks, the immutable
evaluation manifests, and the report builder. It runs the Phase 3 arena
unchanged: Phase 4 contributes agents and manifests, not a second evaluator.

Three separate result classes are kept apart on purpose and are labelled as
such in the report:

``development``
    Deal-level and match-level comparisons on the committed development banks.
    These banks are visible to development, so their numbers are descriptive
    and must not be quoted as sealed promotion evidence.
``protocol_control``
    Comparisons against the non-strategic Phase 3 fixtures. They establish a
    floor, not a ranking among strategic agents.
``ablation``
    Same deals, same schedule, one capability changed.

Sample sizes are deliberately modest so the whole suite stays reproducible on a
laptop. Every reported effect carries its interval, and small strata are marked
as descriptive.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

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
from tuppi_eval.crossplay import crossplay_matrix_to_data, run_crossplay
from tuppi_eval.deals import (
    DealBank,
    DealerPolicy,
    generate_deal_bank,
    load_deal_bank,
    save_deal_bank,
)
from tuppi_eval.identities import AgentSpecification, TeamSpecification
from tuppi_eval.records import ExecutionStatus
from tuppi_eval.registry import AgentRegistry
from tuppi_eval.schedules import (
    CANONICAL_SCHEDULE_DESIGN,
    EvaluationMode,
    build_canonical_schedule,
)
from tuppi_engine import (
    ENGINE_VERSION,
    atomic_write_canonical_json,
    strict_json_load_file,
)
from tuppi_rules import MatchScore

from .errors import AgentsValidationError
from .profiles import registered_profiles
from .registry import (
    LADDER_PROFILE_KEYS,
    phase4_specifications_by_profile_key,
    phase4_team_specifications,
)


BASELINE_REPORT_SCHEMA_VERSION = "tuppi.agents.baseline_report.v1"
ENGINE_IDENTITY = f"tuppi_engine:v{ENGINE_VERSION}"

DEAL_BANK_SEED = "phase4-development-deal-v1"
DEAL_BANK_COUNT = 64
# A deal-level bank whose deals start from 48-0. The 0-0 bank cannot test
# rising-score behaviour at all: every match-state rule is inert at the table,
# so an ablation run only on that bank measures nothing. This bank puts one
# partnership four points from the target and the other on a reset-only win,
# which is exactly where the match-aware rules fire.
DEAL_UP_BANK_SEED = "phase4-development-deal-up-v1"
DEAL_UP_BANK_COUNT = 64
DEAL_UP_STARTING_SCORE = (48, 0)
CROSSPLAY_BANK_SEED = "phase4-crossplay-v1"
CROSSPLAY_BANK_COUNT = 8
MATCH_BANK_SEED = "phase4-development-match-v1"
MATCH_SEQUENCE_LENGTH = 40
MATCH_BLOCKS = 32
MATCH_BANK_COUNT = MATCH_SEQUENCE_LENGTH * MATCH_BLOCKS

BANK_FILES = {
    "development_deal": "phase4_development_deal_v1.json",
    "development_deal_up": "phase4_development_deal_up_v1.json",
    "crossplay": "phase4_crossplay_v1.json",
    "development_match": "phase4_development_match_v1.json",
}

CROSSPLAY_TEAM_NAMES: tuple[str, ...] = (
    "control_first_legal_clone",
    "control_highest_legal_card_clone",
    "control_lowest_legal_card_clone",
    "control_seeded_random_legal_clone",
    "legacy_heuristic_port_v1_clone",
    "reactive_contract_v1_clone",
    "public_counting_v1_clone",
    "partner_aware_v1_clone",
    "match_aware_v1_clone",
    "heterogeneous_match_aware_with_reactive",
    "heterogeneous_match_aware_with_control",
)


@dataclass(frozen=True, slots=True)
class ComparisonSpec:
    """One named manifest: a pair of teams on one bank in one mode."""

    name: str
    result_class: str
    hypothesis: str
    team_a: str
    team_b: str
    bank: str
    mode: EvaluationMode = EvaluationMode.DEAL
    match_sequence_length: int | None = None


LADDER_COMPARISONS: tuple[ComparisonSpec, ...] = (
    ComparisonSpec(
        name="deal_legacy_port_vs_reactive",
        result_class="development",
        hypothesis=(
            "Does the transparent reactive baseline differ from the ported legacy "
            "heuristic on identical deals?"
        ),
        team_a="reactive_contract_v1_clone",
        team_b="legacy_heuristic_port_v1_clone",
        bank="development_deal",
    ),
    ComparisonSpec(
        name="deal_reactive_vs_counting",
        result_class="ablation",
        hypothesis="Isolates the value of hard public inference.",
        team_a="public_counting_v1_clone",
        team_b="reactive_contract_v1_clone",
        bank="development_deal",
    ),
    ComparisonSpec(
        name="deal_counting_vs_partner_aware",
        result_class="ablation",
        hypothesis="Isolates the value of explicit partnership rules.",
        team_a="partner_aware_v1_clone",
        team_b="public_counting_v1_clone",
        bank="development_deal",
    ),
    ComparisonSpec(
        name="deal_partner_aware_vs_match_aware",
        result_class="ablation",
        hypothesis="Isolates the value of deterministic rising-score rules.",
        team_a="match_aware_v1_clone",
        team_b="partner_aware_v1_clone",
        bank="development_deal",
    ),
    ComparisonSpec(
        name="deal_match_aware_vs_control",
        result_class="protocol_control",
        hypothesis="Establishes the floor against a non-strategic fixture.",
        team_a="match_aware_v1_clone",
        team_b="control_first_legal_clone",
        bank="development_deal",
    ),
)

ABLATION_COMPARISONS: tuple[ComparisonSpec, ...] = (
    ComparisonSpec(
        name="ablate_showing_legacy_vs_simple",
        result_class="ablation",
        hypothesis=(
            "Legacy-derived showing against the simple transparent showing "
            "profile, with identical trick play."
        ),
        team_a="reactive_contract_v1_clone",
        team_b="reactive_contract_legacy_show_v1_clone",
        bank="development_deal",
    ),
    ComparisonSpec(
        name="ablate_legacy_convention_on_off",
        result_class="ablation",
        hypothesis="The optional legacy showing convention switched on and off.",
        team_a="partner_aware_v1_clone",
        team_b="partner_aware_legacy_convention_v1_clone",
        bank="development_deal",
    ),
    ComparisonSpec(
        name="ablate_match_state_on_off",
        result_class="ablation",
        hypothesis="Every rising-score rule switched on and off.",
        team_a="match_aware_v1_clone",
        team_b="match_aware_no_match_features_v1_clone",
        bank="development_deal",
    ),
)

RISING_SCORE_COMPARISONS: tuple[ComparisonSpec, ...] = (
    ComparisonSpec(
        name="deal_partner_aware_vs_match_aware_from_48",
        result_class="ablation",
        hypothesis=(
            "Isolates the rising-score rules where they can actually fire: every "
            "deal starts at 48-0, so one partnership is four points from the "
            "target and the other can only reset."
        ),
        team_a="match_aware_v1_clone",
        team_b="partner_aware_v1_clone",
        bank="development_deal_up",
    ),
    ComparisonSpec(
        name="ablate_match_state_on_off_from_48",
        result_class="ablation",
        hypothesis=(
            "Every rising-score rule switched on and off, on deals that start "
            "at 48-0."
        ),
        team_a="match_aware_v1_clone",
        team_b="match_aware_no_match_features_v1_clone",
        bank="development_deal_up",
    ),
)

MATCH_COMPARISONS: tuple[ComparisonSpec, ...] = (
    ComparisonSpec(
        name="match_partner_aware_vs_match_aware",
        result_class="development",
        hypothesis=(
            "Complete matches from 0-0: does rising-score awareness change the "
            "match outcome, not just the deal margin?"
        ),
        team_a="match_aware_v1_clone",
        team_b="partner_aware_v1_clone",
        bank="development_match",
        mode=EvaluationMode.MATCH,
        match_sequence_length=MATCH_SEQUENCE_LENGTH,
    ),
    ComparisonSpec(
        name="match_match_aware_vs_control",
        result_class="protocol_control",
        hypothesis="Complete matches against a non-strategic fixture.",
        team_a="match_aware_v1_clone",
        team_b="control_first_legal_clone",
        bank="development_match",
        mode=EvaluationMode.MATCH,
        match_sequence_length=MATCH_SEQUENCE_LENGTH,
    ),
)

ALL_COMPARISONS: tuple[ComparisonSpec, ...] = (
    LADDER_COMPARISONS
    + ABLATION_COMPARISONS
    + RISING_SCORE_COMPARISONS
    + MATCH_COMPARISONS
)


# ------------------------------------------------------------------ deal banks


def build_bank(name: str) -> DealBank:
    """Rebuild one committed development bank from its frozen parameters."""

    starting_score = MatchScore()
    if name == "development_deal":
        count, seed = DEAL_BANK_COUNT, DEAL_BANK_SEED
    elif name == "development_deal_up":
        count, seed = DEAL_UP_BANK_COUNT, DEAL_UP_BANK_SEED
        starting_score = MatchScore(*DEAL_UP_STARTING_SCORE)
    elif name == "crossplay":
        count, seed = CROSSPLAY_BANK_COUNT, CROSSPLAY_BANK_SEED
    elif name == "development_match":
        count, seed = MATCH_BANK_COUNT, MATCH_BANK_SEED
    else:
        raise AgentsValidationError(f"unknown Phase 4 deal bank {name!r}")
    return generate_deal_bank(
        count=count,
        root_seed=seed,
        dealer_policy=DealerPolicy.ROUND_ROBIN,
        initial_dealer=0,
        starting_score=starting_score,
        creation_metadata={
            "bank_name": name,
            "phase": "phase4",
            "purpose": "phase4_development_bank",
            "reuse_restriction": (
                "Development bank: visible to development, therefore descriptive "
                "only. It is not a sealed promotion benchmark."
            ),
        },
    )


def write_banks(directory: str | Path) -> dict[str, str]:
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    identifiers: dict[str, str] = {}
    for name, filename in BANK_FILES.items():
        bank = build_bank(name)
        save_deal_bank(target / filename, bank)
        identifiers[name] = bank.deal_bank_id
    return identifiers


def read_bank(directory: str | Path, name: str) -> DealBank:
    return load_deal_bank(Path(directory) / BANK_FILES[name])


# ------------------------------------------------------------------- manifests


def _registry_for(teams: Iterable[TeamSpecification]) -> AgentRegistry:
    """Build the smallest registry that covers the referenced agents."""

    specifications = {
        specification.agent_id: specification
        for specification in _all_specifications()
    }
    needed = {
        agent_id for team in teams for agent_id in team.component_agent_ids
    }
    missing = needed - set(specifications)
    if missing:
        raise AgentsValidationError(f"unregistered agent IDs: {sorted(missing)}")
    return AgentRegistry.build(tuple(specifications[key] for key in sorted(needed)))


def _all_specifications() -> tuple[AgentSpecification, ...]:
    from .registry import phase4_registry

    return phase4_registry().specifications


def build_configuration(
    specification: ComparisonSpec, bank: DealBank
) -> EvaluationConfiguration:
    teams = phase4_team_specifications()
    team_a = teams[specification.team_a]
    team_b = teams[specification.team_b]
    registry = _registry_for((team_a, team_b))
    schedule = build_canonical_schedule(
        deal_bank=bank,
        team_a=team_a,
        team_b=team_b,
        mode=specification.mode,
        match_sequence_length=specification.match_sequence_length,
    )
    return EvaluationConfiguration.build(
        ruleset_id="project_target_v1",
        engine_identity=ENGINE_IDENTITY,
        deal_bank_id=bank.deal_bank_id,
        agent_specifications=registry.specifications,
        agent_registry_digest=registry.registry_digest,
        team_a=team_a,
        team_b=team_b,
        schedule_id=schedule.schedule_id,
        schedule_design_id=CANONICAL_SCHEDULE_DESIGN,
        evaluation_mode=specification.mode,
        match_sequence_length=specification.match_sequence_length,
        starting_score=bank.base_deals[0].starting_score,
        dealer_policy=bank.dealer_policy,
        number_base_deals=len(bank.base_deals),
        transformations_applied=tuple(
            item.transformation_id for item in schedule.transformations
        ),
        failure_policy=FailurePolicy.CONTINUE,
        output_mode=OutputMode.RAW_AND_SUMMARY,
        confidence_level=0.95,
        bootstrap_replicates=2000,
        permutation_replicates=2000,
        primary_metric=PrimaryMetric.PAIRED_DUPLICATE_UTILITY,
        seed_hierarchy=SeedHierarchy(
            deal_root_seed=bank.root_seed,
            agent_root_seed="phase4-agent-seed-v1",
            analysis_seed="phase4-analysis-seed-v1",
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
        software_environment={
            "engine_identity": ENGINE_IDENTITY,
            "phase": "phase4",
            "result_class": specification.result_class,
        },
        description=f"Phase 4 {specification.name}: {specification.hypothesis}",
    )


def crossplay_configurations(bank: DealBank) -> tuple[EvaluationConfiguration, ...]:
    """Build one normalized configuration per unordered team pair."""

    teams = phase4_team_specifications()
    selected = {name: teams[name] for name in CROSSPLAY_TEAM_NAMES}
    ordered = sorted(selected.items(), key=lambda item: item[1].team_id)
    configurations: list[EvaluationConfiguration] = []
    for index, (left_name, left) in enumerate(ordered):
        for right_name, right in ordered[index:]:
            configurations.append(
                build_configuration(
                    ComparisonSpec(
                        name=f"crossplay_{left_name}__{right_name}",
                        result_class="development",
                        hypothesis=(
                            "Descriptive cross-play cell on a small shared bank."
                        ),
                        team_a=left_name,
                        team_b=right_name,
                        bank="crossplay",
                    ),
                    bank,
                )
            )
    return tuple(configurations)


def write_manifests(directory: str | Path, bank_directory: str | Path) -> list[str]:
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for specification in ALL_COMPARISONS:
        bank = read_bank(bank_directory, specification.bank)
        config = build_configuration(specification, bank)
        path = target / f"{specification.name}.json"
        atomic_write_canonical_json(path, evaluation_config_to_data(config))
        written.append(path.name)
    crossplay_bank = read_bank(bank_directory, "crossplay")
    request = {
        "comparisons": [
            evaluation_config_to_data(item)
            for item in crossplay_configurations(crossplay_bank)
        ],
        "deal_bank_id": crossplay_bank.deal_bank_id,
        "include_missing": False,
        "schema_version": "tuppi.eval.crossplay_request.v1",
    }
    atomic_write_canonical_json(target / "crossplay_request.json", request)
    written.append("crossplay_request.json")
    index = {
        "banks": {name: BANK_FILES[name] for name in sorted(BANK_FILES)},
        "comparisons": [
            {
                "bank": item.bank,
                "hypothesis": item.hypothesis,
                "manifest": f"{item.name}.json",
                "match_sequence_length": item.match_sequence_length,
                "mode": item.mode.value,
                "name": item.name,
                "result_class": item.result_class,
                "team_a": item.team_a,
                "team_b": item.team_b,
            }
            for item in ALL_COMPARISONS
        ],
        "crossplay_request": "crossplay_request.json",
        "crossplay_teams": list(CROSSPLAY_TEAM_NAMES),
        "schema_version": "tuppi.agents.evaluation_manifest_index.v1",
    }
    atomic_write_canonical_json(target / "index.json", index)
    written.append("index.json")
    return sorted(written)


# ------------------------------------------------------------------- execution


_SUMMARY_STRATA = (
    "agent_partnership_assignment",
    "contract",
    "rami_outcome",
    "score_state",
    "team_a_up_down_status",
)


def _comparison_report(
    specification: ComparisonSpec, config: EvaluationConfiguration, run
) -> dict[str, object]:
    summary = run.result.summary
    teams = phase4_team_specifications()
    censored = sum(
        1
        for record in run.result.game_records
        if record.execution_status is ExecutionStatus.FAILED
        and record.failure is not None
        and record.failure.kind.value == "insufficient_match_deals"
    )
    return {
        "bank": specification.bank,
        "censored_games": censored,
        "contract_metrics": summary["contract_metrics"],
        "evaluation_id": config.evaluation_id,
        "execution_metrics": summary["execution_metrics"],
        "hypothesis": specification.hypothesis,
        "mode": specification.mode.value,
        "name": specification.name,
        "outcome_metrics": summary["outcome_metrics"],
        "primary_inference": summary["primary_inference"],
        "result_class": specification.result_class,
        "result_id": run.result.result_id,
        "strata": {
            key: summary["strata"][key]
            for key in _SUMMARY_STRATA
            if key in summary["strata"]
        },
        "team_a": {
            "name": specification.team_a,
            "team_id": teams[specification.team_a].team_id,
        },
        "team_b": {
            "name": specification.team_b,
            "team_id": teams[specification.team_b].team_id,
        },
        "transformed_games": len(run.result.game_records),
    }


def run_comparisons(
    *,
    bank_directory: str | Path,
    output_directory: str | Path,
    selected: tuple[ComparisonSpec, ...] = ALL_COMPARISONS,
    progress=None,
    reuse: dict[str, dict[str, object]] | None = None,
) -> list[dict[str, object]]:
    """Run each comparison, optionally reusing an earlier report's entries.

    ``reuse`` maps ``evaluation_id`` to the comparison block a previous run
    produced. A reused entry is only accepted when the manifest rebuilt from
    code has the identical evaluation identity, so report-level resume cannot
    silently mix results from different configurations.
    """

    output = Path(output_directory)
    output.mkdir(parents=True, exist_ok=True)
    reports: list[dict[str, object]] = []
    for specification in selected:
        bank = read_bank(bank_directory, specification.bank)
        config = build_configuration(specification, bank)
        cached = (reuse or {}).get(config.evaluation_id)
        if cached is not None:
            if cached.get("name") != specification.name:
                raise AgentsValidationError(
                    "a reused comparison disagrees with its manifest name"
                )
            if progress is not None:
                progress(f"reusing {specification.name}")
            reports.append(cached)
            continue
        schedule = build_canonical_schedule(
            deal_bank=bank,
            team_a=phase4_team_specifications()[specification.team_a],
            team_b=phase4_team_specifications()[specification.team_b],
            mode=specification.mode,
            match_sequence_length=specification.match_sequence_length,
        )
        if progress is not None:
            progress(f"running {specification.name}")
        run = run_evaluation(
            config,
            bank,
            schedule,
            output_directory=output / specification.name,
        )
        reports.append(_comparison_report(specification, config, run))
    return reports


def run_crossplay_matrix(
    *, bank_directory: str | Path, output_directory: str | Path, progress=None
) -> dict[str, object]:
    bank = read_bank(bank_directory, "crossplay")
    configurations = crossplay_configurations(bank)
    if progress is not None:
        progress(f"running cross-play over {len(configurations)} team pairs")
    matrix = run_crossplay(
        configurations,
        bank,
        output_directory=Path(output_directory) / "crossplay",
        include_missing=False,
    )
    teams = phase4_team_specifications()
    names = {team.team_id: name for name, team in teams.items()}
    data = crossplay_matrix_to_data(matrix)
    data["team_names"] = [
        {"name": names.get(team_id, "unknown"), "team_id": team_id}
        for team_id in matrix.team_ids
    ]
    return data


def build_baseline_report(
    *,
    comparisons: list[dict[str, object]],
    crossplay: dict[str, object] | None,
    performance: dict[str, object] | None,
    bank_identifiers: dict[str, str],
) -> dict[str, object]:
    profiles = registered_profiles()
    specifications = phase4_specifications_by_profile_key()
    teams = phase4_team_specifications()
    return {
        "agents": [
            {
                "agent_id": specifications[key].agent_id,
                "family": profiles[key].family.value,
                "in_ladder": key in LADDER_PROFILE_KEYS,
                "partner_convention_id": profiles[key].partner_convention_id,
                "profile_id": profiles[key].profile_id,
                "profile_key": key,
                "showing_policy": profiles[key].showing_policy.value,
            }
            for key in sorted(specifications)
        ],
        "banks": [
            {"deal_bank_id": value, "name": name}
            for name, value in sorted(bank_identifiers.items())
        ],
        "comparisons": comparisons,
        "crossplay": crossplay,
        "engine_identity": ENGINE_IDENTITY,
        "interpretation": {
            "development_bank_status": (
                "The development banks were visible while the agents were "
                "written. Their numbers are descriptive and must not be quoted "
                "as sealed promotion evidence."
            ),
            "ladder_claim": (
                "Phase 4 establishes a reproducible reference population. A "
                "higher rung is a strictly larger capability set, not a proven "
                "stronger player. Where a more capable rung scores worse the "
                "result is preserved and diagnosed by ablation."
            ),
            "no_expert_claim": (
                "No agent in this report is expert-validated, tuned against an "
                "expert, or claimed to be strong."
            ),
            "sample_size_warning": (
                "Independent base deals, not transformed games, are the unit of "
                "inference. Cross-play uses a deliberately small shared bank and "
                "is descriptive only."
            ),
        },
        "performance": performance,
        "ruleset_id": "project_target_v1",
        "schema_version": BASELINE_REPORT_SCHEMA_VERSION,
        "teams": [
            {"name": name, "team_id": team.team_id}
            for name, team in sorted(teams.items())
        ],
    }


def reusable_comparisons(path: str | Path) -> dict[str, dict[str, object]]:
    """Index an earlier report's comparisons by their evaluation identity."""

    report = load_report(path)
    return {
        item["evaluation_id"]: item
        for item in report["comparisons"]
        if isinstance(item, dict) and "evaluation_id" in item
    }


def load_report(path: str | Path) -> dict[str, object]:
    data = strict_json_load_file(path)
    if type(data) is not dict or data.get("schema_version") != (
        BASELINE_REPORT_SCHEMA_VERSION
    ):
        raise AgentsValidationError("not a Phase 4 baseline report")
    return data
