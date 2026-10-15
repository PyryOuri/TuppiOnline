"""Strict immutable evaluation configuration with no result-changing defaults."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import json
from typing import Any

from tuppi_rules import MatchScore, RULESET_ID, RulesError, is_match_terminal

from .deals import DealerPolicy
from .errors import ConfigurationError
from .identities import (
    AgentSpecification,
    TeamSpecification,
    agent_spec_from_data,
    agent_spec_to_data,
    team_spec_from_data,
    team_spec_to_data,
)
from .registry import AgentRegistry
from .schedules import (
    CANONICAL_SCHEDULE_DESIGN,
    EvaluationMode,
    canonical_transformations,
)
from .serialization import (
    canonical_json_text,
    content_digest,
    require_exact_keys,
    require_object,
)


EVALUATION_CONFIG_SCHEMA_VERSION = "tuppi.eval.evaluation_config.v1"


class FailurePolicy(StrEnum):
    CONTINUE = "continue"
    ABORT = "abort"


class OutputMode(StrEnum):
    RAW_AND_SUMMARY = "raw_and_summary"


class PrimaryMetric(StrEnum):
    PAIRED_DUPLICATE_UTILITY = "paired_duplicate_utility_points_v1"


class SequentialMode(StrEnum):
    FIXED_SAMPLE = "fixed_sample"


@dataclass(frozen=True, slots=True)
class TimeoutLimits:
    per_action_seconds: float | None
    per_deal_seconds: float | None
    per_match_seconds: float | None

    def __post_init__(self) -> None:
        for label, value in (
            ("per_action_seconds", self.per_action_seconds),
            ("per_deal_seconds", self.per_deal_seconds),
            ("per_match_seconds", self.per_match_seconds),
        ):
            if value is not None and (
                type(value) not in (int, float)
                or isinstance(value, bool)
                or value <= 0
            ):
                raise ConfigurationError(f"{label} must be null or positive")

    def to_data(self) -> dict[str, object]:
        return {
            "per_action_seconds": self.per_action_seconds,
            "per_deal_seconds": self.per_deal_seconds,
            "per_match_seconds": self.per_match_seconds,
        }


@dataclass(frozen=True, slots=True)
class SeedHierarchy:
    deal_root_seed: int | str
    agent_root_seed: int | str
    analysis_seed: int | str

    def __post_init__(self) -> None:
        for label, value in (
            ("deal_root_seed", self.deal_root_seed),
            ("agent_root_seed", self.agent_root_seed),
            ("analysis_seed", self.analysis_seed),
        ):
            if type(value) not in (int, str) or isinstance(value, bool):
                raise ConfigurationError(f"{label} must be an integer or string")
            if isinstance(value, str) and not value:
                raise ConfigurationError(f"{label} must not be empty")

    def to_data(self) -> dict[str, object]:
        return {
            "agent_root_seed": self.agent_root_seed,
            "analysis_seed": self.analysis_seed,
            "deal_root_seed": self.deal_root_seed,
        }


@dataclass(frozen=True, slots=True)
class SequentialProtocol:
    mode: SequentialMode
    maximum_base_deals: int
    interim_checkpoints: tuple[int, ...]
    stopping_boundaries: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.mode is not SequentialMode.FIXED_SAMPLE:
            raise ConfigurationError(
                "formal sequential testing is deferred; fixed_sample is required"
            )
        if type(self.maximum_base_deals) is not int or self.maximum_base_deals <= 0:
            raise ConfigurationError("maximum_base_deals must be positive")
        if self.interim_checkpoints or self.stopping_boundaries:
            raise ConfigurationError(
                "fixed-sample mode forbids interim looks and stopping boundaries"
            )

    def to_data(self) -> dict[str, object]:
        return {
            "interim_checkpoints": list(self.interim_checkpoints),
            "maximum_base_deals": self.maximum_base_deals,
            "mode": self.mode.value,
            "stopping_boundaries": list(self.stopping_boundaries),
        }


@dataclass(frozen=True, slots=True)
class EvaluationConfiguration:
    evaluation_id: str
    configuration_digest: str
    ruleset_id: str
    engine_identity: str
    deal_bank_id: str
    agent_specifications: tuple[AgentSpecification, ...]
    agent_registry_digest: str
    team_a: TeamSpecification
    team_b: TeamSpecification
    schedule_id: str
    schedule_design_id: str
    evaluation_mode: EvaluationMode
    match_sequence_length: int | None
    starting_score: MatchScore
    dealer_policy: DealerPolicy
    number_base_deals: int
    transformations_applied: tuple[str, ...]
    failure_policy: FailurePolicy
    output_mode: OutputMode
    confidence_level: float
    bootstrap_replicates: int
    permutation_replicates: int
    primary_metric: PrimaryMetric
    seed_hierarchy: SeedHierarchy
    timeouts: TimeoutLimits
    sequential_protocol: SequentialProtocol
    software_environment_json: str
    description: str
    schema_version: str = field(default=EVALUATION_CONFIG_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        if self.ruleset_id != RULESET_ID.value:
            raise ConfigurationError("Phase 3 supports only project_target_v1")
        if not isinstance(self.engine_identity, str) or not self.engine_identity:
            raise ConfigurationError("engine_identity must be nonempty")
        registry = AgentRegistry.build(self.agent_specifications)
        if self.agent_specifications != registry.specifications:
            raise ConfigurationError(
                "agent_specifications must be sorted by stable agent ID"
            )
        if registry.registry_digest != self.agent_registry_digest:
            raise ConfigurationError("agent registry digest mismatch")
        registered = {spec.agent_id for spec in registry.specifications}
        for team in (self.team_a, self.team_b):
            if any(agent_id not in registered for agent_id in team.component_agent_ids):
                raise ConfigurationError("team references an unregistered agent")
        if not isinstance(self.evaluation_mode, EvaluationMode):
            raise ConfigurationError("evaluation_mode is invalid")
        if type(self.number_base_deals) is not int or self.number_base_deals <= 0:
            raise ConfigurationError("number_base_deals must be positive")
        if not isinstance(self.dealer_policy, DealerPolicy):
            raise ConfigurationError("dealer_policy is invalid")
        if self.evaluation_mode is EvaluationMode.DEAL:
            if self.match_sequence_length is not None:
                raise ConfigurationError(
                    "deal mode requires a null match_sequence_length"
                )
        elif (
            type(self.match_sequence_length) is not int
            or self.match_sequence_length <= 0
            or self.number_base_deals % self.match_sequence_length
        ):
            raise ConfigurationError(
                "match mode requires a positive sequence length dividing base deals"
            )
        if (
            self.evaluation_mode is EvaluationMode.MATCH
            and self.dealer_policy is not DealerPolicy.ROUND_ROBIN
        ):
            raise ConfigurationError(
                "match mode requires round_robin dealers for explicit rotation"
            )
        if not isinstance(self.starting_score, MatchScore) or is_match_terminal(
            self.starting_score
        ):
            raise ConfigurationError("starting_score must be a nonterminal MatchScore")
        try:
            if MatchScore(*self.starting_score.as_tuple()) != self.starting_score:
                raise ConfigurationError("starting_score is invalid")
        except RulesError as exc:
            raise ConfigurationError("starting_score is invalid") from exc
        if self.schedule_design_id != CANONICAL_SCHEDULE_DESIGN:
            raise ConfigurationError("unsupported schedule design")
        expected_transformations = tuple(
            item.transformation_id for item in canonical_transformations()
        )
        if (
            type(self.transformations_applied) is not tuple
            or self.transformations_applied != expected_transformations
        ):
            raise ConfigurationError(
                "transformations must be the ordered canonical eight-game design"
            )
        if not isinstance(self.failure_policy, FailurePolicy):
            raise ConfigurationError("failure_policy is invalid")
        if self.output_mode is not OutputMode.RAW_AND_SUMMARY:
            raise ConfigurationError("unsupported output mode")
        if (
            type(self.confidence_level) not in (int, float)
            or isinstance(self.confidence_level, bool)
            or not 0.5 < self.confidence_level < 1.0
        ):
            raise ConfigurationError("confidence_level must be between 0.5 and 1")
        for label, value in (
            ("bootstrap_replicates", self.bootstrap_replicates),
            ("permutation_replicates", self.permutation_replicates),
        ):
            if type(value) is not int or value <= 0:
                raise ConfigurationError(f"{label} must be a positive integer")
        if self.primary_metric is not PrimaryMetric.PAIRED_DUPLICATE_UTILITY:
            raise ConfigurationError("unsupported primary metric")
        if not isinstance(self.seed_hierarchy, SeedHierarchy):
            raise ConfigurationError("seed_hierarchy is invalid")
        if not isinstance(self.timeouts, TimeoutLimits):
            raise ConfigurationError("timeouts are invalid")
        if not isinstance(self.sequential_protocol, SequentialProtocol):
            raise ConfigurationError("sequential_protocol is invalid")
        if self.sequential_protocol.maximum_base_deals != self.number_base_deals:
            raise ConfigurationError(
                "fixed-sample maximum must equal number_base_deals"
            )
        try:
            environment = json.loads(self.software_environment_json)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ConfigurationError("software_environment is invalid") from exc
        if type(environment) is not dict or (
            canonical_json_text(environment) != self.software_environment_json
        ):
            raise ConfigurationError(
                "software_environment must be a canonical JSON object"
            )
        if not isinstance(self.description, str) or not self.description:
            raise ConfigurationError("description must be nonempty")
        digest = content_digest(self.identity_data())
        if self.configuration_digest != digest or self.evaluation_id != f"eval:{digest}":
            raise ConfigurationError(
                "evaluation identity disagrees with immutable configuration"
            )

    @classmethod
    def build(
        cls,
        *,
        ruleset_id: str,
        engine_identity: str,
        deal_bank_id: str,
        agent_specifications: tuple[AgentSpecification, ...],
        agent_registry_digest: str,
        team_a: TeamSpecification,
        team_b: TeamSpecification,
        schedule_id: str,
        schedule_design_id: str,
        evaluation_mode: EvaluationMode,
        match_sequence_length: int | None,
        starting_score: MatchScore,
        dealer_policy: DealerPolicy,
        number_base_deals: int,
        transformations_applied: tuple[str, ...],
        failure_policy: FailurePolicy,
        output_mode: OutputMode,
        confidence_level: float,
        bootstrap_replicates: int,
        permutation_replicates: int,
        primary_metric: PrimaryMetric,
        seed_hierarchy: SeedHierarchy,
        timeouts: TimeoutLimits,
        sequential_protocol: SequentialProtocol,
        software_environment: dict[str, Any],
        description: str,
        claimed_evaluation_id: str | None = None,
        claimed_configuration_digest: str | None = None,
    ) -> "EvaluationConfiguration":
        environment_json = canonical_json_text(software_environment)
        values = {
            "ruleset_id": ruleset_id,
            "engine_identity": engine_identity,
            "deal_bank_id": deal_bank_id,
            "agent_specifications": tuple(agent_specifications),
            "agent_registry_digest": agent_registry_digest,
            "team_a": team_a,
            "team_b": team_b,
            "schedule_id": schedule_id,
            "schedule_design_id": schedule_design_id,
            "evaluation_mode": evaluation_mode,
            "match_sequence_length": match_sequence_length,
            "starting_score": starting_score,
            "dealer_policy": dealer_policy,
            "number_base_deals": number_base_deals,
            "transformations_applied": tuple(transformations_applied),
            "failure_policy": failure_policy,
            "output_mode": output_mode,
            "confidence_level": confidence_level,
            "bootstrap_replicates": bootstrap_replicates,
            "permutation_replicates": permutation_replicates,
            "primary_metric": primary_metric,
            "seed_hierarchy": seed_hierarchy,
            "timeouts": timeouts,
            "sequential_protocol": sequential_protocol,
            "software_environment_json": environment_json,
            "description": description,
        }
        provisional = object.__new__(cls)
        for name, value in values.items():
            object.__setattr__(provisional, name, value)
        digest = content_digest(provisional.identity_data())
        return cls(
            evaluation_id=claimed_evaluation_id or f"eval:{digest}",
            configuration_digest=claimed_configuration_digest or digest,
            **values,
        )

    @property
    def software_environment(self) -> dict[str, Any]:
        return json.loads(self.software_environment_json)

    def identity_data(self) -> dict[str, object]:
        return {
            "agent_registry_digest": self.agent_registry_digest,
            "agent_specifications": [
                agent_spec_to_data(item) for item in self.agent_specifications
            ],
            "confidence_level": self.confidence_level,
            "bootstrap_replicates": self.bootstrap_replicates,
            "deal_bank_id": self.deal_bank_id,
            "dealer_policy": self.dealer_policy.value,
            "description": self.description,
            "engine_identity": self.engine_identity,
            "evaluation_mode": self.evaluation_mode.value,
            "failure_policy": self.failure_policy.value,
            "match_sequence_length": self.match_sequence_length,
            "number_base_deals": self.number_base_deals,
            "output_mode": self.output_mode.value,
            "primary_metric": self.primary_metric.value,
            "permutation_replicates": self.permutation_replicates,
            "ruleset_id": self.ruleset_id,
            "schedule_design_id": self.schedule_design_id,
            "schedule_id": self.schedule_id,
            "schema_version": EVALUATION_CONFIG_SCHEMA_VERSION,
            "seed_hierarchy": self.seed_hierarchy.to_data(),
            "sequential_protocol": self.sequential_protocol.to_data(),
            "software_environment": self.software_environment,
            "starting_score": list(self.starting_score.as_tuple()),
            "team_a": team_spec_to_data(self.team_a),
            "team_b": team_spec_to_data(self.team_b),
            "timeouts": self.timeouts.to_data(),
            "transformations_applied": list(self.transformations_applied),
        }


def evaluation_config_to_data(config: EvaluationConfiguration) -> dict[str, object]:
    return {
        **config.identity_data(),
        "configuration_digest": config.configuration_digest,
        "evaluation_id": config.evaluation_id,
    }


def _tuple_of_strings(value: object, label: str) -> tuple[str, ...]:
    if type(value) is not list or any(not isinstance(item, str) for item in value):
        raise ConfigurationError(f"{label} must be a string array")
    return tuple(value)


def evaluation_config_from_data(value: object) -> EvaluationConfiguration:
    obj = require_object(value, "evaluation configuration")
    expected = {
        "agent_registry_digest",
        "agent_specifications",
        "bootstrap_replicates",
        "confidence_level",
        "configuration_digest",
        "deal_bank_id",
        "dealer_policy",
        "description",
        "engine_identity",
        "evaluation_id",
        "evaluation_mode",
        "failure_policy",
        "match_sequence_length",
        "number_base_deals",
        "output_mode",
        "primary_metric",
        "permutation_replicates",
        "ruleset_id",
        "schedule_design_id",
        "schedule_id",
        "schema_version",
        "seed_hierarchy",
        "sequential_protocol",
        "software_environment",
        "starting_score",
        "team_a",
        "team_b",
        "timeouts",
        "transformations_applied",
    }
    require_exact_keys(obj, expected, "evaluation configuration")
    if obj["schema_version"] != EVALUATION_CONFIG_SCHEMA_VERSION:
        raise ConfigurationError("unsupported evaluation configuration schema_version")
    raw_agents = obj["agent_specifications"]
    if type(raw_agents) is not list or not raw_agents:
        raise ConfigurationError("agent_specifications must be a nonempty array")
    score = obj["starting_score"]
    if type(score) is not list or len(score) != 2:
        raise ConfigurationError("starting_score must contain two integers")
    try:
        starting_score = MatchScore(score[0], score[1])
        mode = EvaluationMode(obj["evaluation_mode"])
        dealer_policy = DealerPolicy(obj["dealer_policy"])
        failure_policy = FailurePolicy(obj["failure_policy"])
        output_mode = OutputMode(obj["output_mode"])
        primary_metric = PrimaryMetric(obj["primary_metric"])
    except (RulesError, TypeError, ValueError) as exc:
        raise ConfigurationError("configuration contains an invalid enum or score") from exc
    raw_seeds = require_object(obj["seed_hierarchy"], "seed_hierarchy")
    require_exact_keys(
        raw_seeds,
        {"agent_root_seed", "analysis_seed", "deal_root_seed"},
        "seed_hierarchy",
    )
    raw_timeouts = require_object(obj["timeouts"], "timeouts")
    require_exact_keys(
        raw_timeouts,
        {"per_action_seconds", "per_deal_seconds", "per_match_seconds"},
        "timeouts",
    )
    raw_sequential = require_object(
        obj["sequential_protocol"], "sequential_protocol"
    )
    require_exact_keys(
        raw_sequential,
        {
            "interim_checkpoints",
            "maximum_base_deals",
            "mode",
            "stopping_boundaries",
        },
        "sequential_protocol",
    )
    try:
        sequential_mode = SequentialMode(raw_sequential["mode"])
    except (TypeError, ValueError) as exc:
        raise ConfigurationError("unknown sequential mode") from exc
    checkpoints = raw_sequential["interim_checkpoints"]
    boundaries = raw_sequential["stopping_boundaries"]
    if type(checkpoints) is not list or type(boundaries) is not list:
        raise ConfigurationError("sequential arrays are invalid")
    return EvaluationConfiguration.build(
        ruleset_id=obj["ruleset_id"],
        engine_identity=obj["engine_identity"],
        deal_bank_id=obj["deal_bank_id"],
        agent_specifications=tuple(agent_spec_from_data(item) for item in raw_agents),
        agent_registry_digest=obj["agent_registry_digest"],
        team_a=team_spec_from_data(obj["team_a"]),
        team_b=team_spec_from_data(obj["team_b"]),
        schedule_id=obj["schedule_id"],
        schedule_design_id=obj["schedule_design_id"],
        evaluation_mode=mode,
        match_sequence_length=obj["match_sequence_length"],
        starting_score=starting_score,
        dealer_policy=dealer_policy,
        number_base_deals=obj["number_base_deals"],
        transformations_applied=_tuple_of_strings(
            obj["transformations_applied"], "transformations_applied"
        ),
        failure_policy=failure_policy,
        output_mode=output_mode,
        confidence_level=obj["confidence_level"],
        bootstrap_replicates=obj["bootstrap_replicates"],
        permutation_replicates=obj["permutation_replicates"],
        primary_metric=primary_metric,
        seed_hierarchy=SeedHierarchy(
            deal_root_seed=raw_seeds["deal_root_seed"],
            agent_root_seed=raw_seeds["agent_root_seed"],
            analysis_seed=raw_seeds["analysis_seed"],
        ),
        timeouts=TimeoutLimits(
            per_action_seconds=raw_timeouts["per_action_seconds"],
            per_deal_seconds=raw_timeouts["per_deal_seconds"],
            per_match_seconds=raw_timeouts["per_match_seconds"],
        ),
        sequential_protocol=SequentialProtocol(
            mode=sequential_mode,
            maximum_base_deals=raw_sequential["maximum_base_deals"],
            interim_checkpoints=tuple(checkpoints),
            stopping_boundaries=tuple(boundaries),
        ),
        software_environment=require_object(
            obj["software_environment"], "software_environment"
        ),
        description=obj["description"],
        claimed_evaluation_id=obj["evaluation_id"],
        claimed_configuration_digest=obj["configuration_digest"],
    )
