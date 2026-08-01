"""Immutable content identities for agents and partnerships."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import json
import re
from typing import Any

from .errors import RegistryError
from .serialization import (
    canonical_json_text,
    content_digest,
    require_exact_keys,
    require_object,
    require_sha256,
)


AGENT_SPEC_SCHEMA_VERSION = "tuppi.eval.agent_spec.v1"
TEAM_SPEC_SCHEMA_VERSION = "tuppi.eval.team_spec.v1"
_REFERENCE = re.compile(r"[A-Za-z0-9_.:-]{1,160}")


class DeterminismClass(StrEnum):
    DETERMINISTIC = "deterministic"
    SEEDED_STOCHASTIC = "seeded_stochastic"


class SeedPolicy(StrEnum):
    NONE = "none"
    DERIVED_PER_ENTRY_SEAT = "derived_per_entry_seat"


def _reference(value: object, label: str) -> str:
    if not isinstance(value, str) or _REFERENCE.fullmatch(value) is None:
        raise RegistryError(f"{label} has an invalid stable-reference syntax")
    return value


def _string_tuple(value: object, label: str) -> tuple[str, ...]:
    if type(value) not in (list, tuple):
        raise RegistryError(f"{label} must be a nonempty string sequence")
    result = tuple(value)
    if not result or any(not isinstance(item, str) or not item for item in result):
        raise RegistryError(f"{label} must be a nonempty string sequence")
    if len(set(result)) != len(result):
        raise RegistryError(f"{label} must not contain duplicates")
    return result


@dataclass(frozen=True, slots=True)
class AgentSpecification:
    agent_id: str
    agent_family: str
    configuration_version: str
    implementation_reference: str
    ruleset_compatibility: tuple[str, ...]
    observation_schema_compatibility: tuple[str, ...]
    determinism: DeterminismClass
    seed_policy: SeedPolicy
    configuration_json: str
    configuration_digest: str
    model_checkpoint_id: str | None
    search_budget: int | None
    partner_convention_id: str | None
    description: str
    schema_version: str = field(default=AGENT_SPEC_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        _reference(self.agent_family, "agent_family")
        _reference(self.configuration_version, "configuration_version")
        _reference(self.implementation_reference, "implementation_reference")
        _string_tuple(self.ruleset_compatibility, "ruleset_compatibility")
        _string_tuple(
            self.observation_schema_compatibility,
            "observation_schema_compatibility",
        )
        if not isinstance(self.determinism, DeterminismClass):
            raise RegistryError("determinism must be a DeterminismClass")
        if not isinstance(self.seed_policy, SeedPolicy):
            raise RegistryError("seed_policy must be a SeedPolicy")
        if (
            self.determinism is DeterminismClass.DETERMINISTIC
            and self.seed_policy is not SeedPolicy.NONE
        ) or (
            self.determinism is DeterminismClass.SEEDED_STOCHASTIC
            and self.seed_policy is not SeedPolicy.DERIVED_PER_ENTRY_SEAT
        ):
            raise RegistryError("determinism and seed_policy are inconsistent")
        try:
            configuration = json.loads(self.configuration_json)
        except (json.JSONDecodeError, TypeError) as exc:
            raise RegistryError("configuration_json is invalid") from exc
        if type(configuration) is not dict:
            raise RegistryError("agent configuration must be a JSON object")
        if canonical_json_text(configuration) != self.configuration_json:
            raise RegistryError("configuration_json must be canonical")
        if self.configuration_digest != content_digest(configuration):
            raise RegistryError("configuration_digest disagrees with configuration")
        if self.model_checkpoint_id is not None:
            _reference(self.model_checkpoint_id, "model_checkpoint_id")
        if self.search_budget is not None and (
            type(self.search_budget) is not int or self.search_budget <= 0
        ):
            raise RegistryError("search_budget must be null or a positive integer")
        if self.partner_convention_id is not None:
            _reference(self.partner_convention_id, "partner_convention_id")
        if not isinstance(self.description, str) or not self.description:
            raise RegistryError("description must be nonempty")
        expected_id = f"agent:{content_digest(self.identity_data())}"
        if self.agent_id != expected_id:
            raise RegistryError("agent_id disagrees with immutable configuration")

    @classmethod
    def build(
        cls,
        *,
        agent_family: str,
        configuration_version: str,
        implementation_reference: str,
        ruleset_compatibility: tuple[str, ...],
        observation_schema_compatibility: tuple[str, ...],
        determinism: DeterminismClass,
        seed_policy: SeedPolicy,
        configuration: dict[str, Any],
        model_checkpoint_id: str | None,
        search_budget: int | None,
        partner_convention_id: str | None,
        description: str,
        claimed_agent_id: str | None = None,
    ) -> "AgentSpecification":
        if type(configuration) is not dict:
            raise RegistryError("agent configuration must be a JSON object")
        configuration_json = canonical_json_text(configuration)
        provisional = object.__new__(cls)
        values = {
            "agent_family": agent_family,
            "configuration_version": configuration_version,
            "implementation_reference": implementation_reference,
            "ruleset_compatibility": tuple(ruleset_compatibility),
            "observation_schema_compatibility": tuple(
                observation_schema_compatibility
            ),
            "determinism": determinism,
            "seed_policy": seed_policy,
            "configuration_json": configuration_json,
            "configuration_digest": content_digest(configuration),
            "model_checkpoint_id": model_checkpoint_id,
            "search_budget": search_budget,
            "partner_convention_id": partner_convention_id,
            "description": description,
        }
        for name, value in values.items():
            object.__setattr__(provisional, name, value)
        identity = provisional.identity_data()
        computed = f"agent:{content_digest(identity)}"
        return cls(agent_id=claimed_agent_id or computed, **values)

    @property
    def configuration(self) -> dict[str, Any]:
        return json.loads(self.configuration_json)

    def identity_data(self) -> dict[str, object]:
        return {
            "agent_family": self.agent_family,
            "configuration": json.loads(self.configuration_json),
            "configuration_version": self.configuration_version,
            "determinism": self.determinism.value,
            "implementation_reference": self.implementation_reference,
            "model_checkpoint_id": self.model_checkpoint_id,
            "observation_schema_compatibility": list(
                self.observation_schema_compatibility
            ),
            "partner_convention_id": self.partner_convention_id,
            "ruleset_compatibility": list(self.ruleset_compatibility),
            "schema_version": AGENT_SPEC_SCHEMA_VERSION,
            "search_budget": self.search_budget,
            "seed_policy": self.seed_policy.value,
        }


def agent_spec_to_data(spec: AgentSpecification) -> dict[str, object]:
    if not isinstance(spec, AgentSpecification):
        raise RegistryError("spec must be an AgentSpecification")
    return {
        "agent_family": spec.agent_family,
        "agent_id": spec.agent_id,
        "configuration": spec.configuration,
        "configuration_digest": spec.configuration_digest,
        "configuration_version": spec.configuration_version,
        "description": spec.description,
        "determinism": spec.determinism.value,
        "implementation_reference": spec.implementation_reference,
        "model_checkpoint_id": spec.model_checkpoint_id,
        "observation_schema_compatibility": list(
            spec.observation_schema_compatibility
        ),
        "partner_convention_id": spec.partner_convention_id,
        "ruleset_compatibility": list(spec.ruleset_compatibility),
        "schema_version": spec.schema_version,
        "search_budget": spec.search_budget,
        "seed_policy": spec.seed_policy.value,
    }


def agent_spec_from_data(value: object) -> AgentSpecification:
    obj = require_object(value, "agent specification")
    expected = {
        "agent_family",
        "agent_id",
        "configuration",
        "configuration_digest",
        "configuration_version",
        "description",
        "determinism",
        "implementation_reference",
        "model_checkpoint_id",
        "observation_schema_compatibility",
        "partner_convention_id",
        "ruleset_compatibility",
        "schema_version",
        "search_budget",
        "seed_policy",
    }
    require_exact_keys(obj, expected, "agent specification")
    if obj["schema_version"] != AGENT_SPEC_SCHEMA_VERSION:
        raise RegistryError("unsupported agent specification schema_version")
    agent_id = obj["agent_id"]
    if not isinstance(agent_id, str) or not agent_id.startswith("agent:"):
        raise RegistryError("agent_id must use the agent:sha256 namespace")
    require_sha256(agent_id.removeprefix("agent:"), "agent_id")
    require_sha256(obj["configuration_digest"], "configuration_digest")
    try:
        determinism = DeterminismClass(obj["determinism"])
        seed_policy = SeedPolicy(obj["seed_policy"])
    except (TypeError, ValueError) as exc:
        raise RegistryError("invalid determinism or seed policy") from exc
    spec = AgentSpecification.build(
        agent_family=obj["agent_family"],
        configuration_version=obj["configuration_version"],
        implementation_reference=obj["implementation_reference"],
        ruleset_compatibility=_string_tuple(
            obj["ruleset_compatibility"], "ruleset_compatibility"
        ),
        observation_schema_compatibility=_string_tuple(
            obj["observation_schema_compatibility"],
            "observation_schema_compatibility",
        ),
        determinism=determinism,
        seed_policy=seed_policy,
        configuration=require_object(obj["configuration"], "configuration"),
        model_checkpoint_id=obj["model_checkpoint_id"],
        search_budget=obj["search_budget"],
        partner_convention_id=obj["partner_convention_id"],
        description=obj["description"],
        claimed_agent_id=obj["agent_id"],
    )
    if spec.configuration_digest != obj["configuration_digest"]:
        raise RegistryError("claimed configuration_digest is invalid")
    return spec


@dataclass(frozen=True, slots=True)
class TeamSpecification:
    team_id: str
    component_agent_ids: tuple[str, str]
    partner_convention_id: str | None
    shared_instances: bool
    description: str
    schema_version: str = field(default=TEAM_SPEC_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        if type(self.component_agent_ids) is not tuple or len(
            self.component_agent_ids
        ) != 2:
            raise RegistryError("team requires exactly two component agent IDs")
        for agent_id in self.component_agent_ids:
            if not isinstance(agent_id, str) or not agent_id.startswith("agent:sha256:"):
                raise RegistryError("team component has an invalid agent ID")
        if self.partner_convention_id is not None:
            _reference(self.partner_convention_id, "partner_convention_id")
        if type(self.shared_instances) is not bool:
            raise RegistryError("shared_instances must be a boolean")
        if self.shared_instances:
            raise RegistryError(
                "Phase 3 requires distinct runtime agent instances per seat"
            )
        if not isinstance(self.description, str) or not self.description:
            raise RegistryError("team description must be nonempty")
        if self.team_id != f"team:{content_digest(self.identity_data())}":
            raise RegistryError("team_id disagrees with component configuration")

    @classmethod
    def build(
        cls,
        *,
        component_agent_ids: tuple[str, str],
        partner_convention_id: str | None,
        shared_instances: bool,
        description: str,
        claimed_team_id: str | None = None,
    ) -> "TeamSpecification":
        identity = {
            "component_agent_ids": list(component_agent_ids),
            "partner_convention_id": partner_convention_id,
            "schema_version": TEAM_SPEC_SCHEMA_VERSION,
            "shared_instances": shared_instances,
        }
        computed = f"team:{content_digest(identity)}"
        return cls(
            team_id=claimed_team_id or computed,
            component_agent_ids=tuple(component_agent_ids),
            partner_convention_id=partner_convention_id,
            shared_instances=shared_instances,
            description=description,
        )

    @property
    def homogeneous(self) -> bool:
        return self.component_agent_ids[0] == self.component_agent_ids[1]

    def identity_data(self) -> dict[str, object]:
        return {
            "component_agent_ids": list(self.component_agent_ids),
            "partner_convention_id": self.partner_convention_id,
            "schema_version": TEAM_SPEC_SCHEMA_VERSION,
            "shared_instances": self.shared_instances,
        }


def team_spec_to_data(spec: TeamSpecification) -> dict[str, object]:
    return {
        "component_agent_ids": list(spec.component_agent_ids),
        "description": spec.description,
        "partner_convention_id": spec.partner_convention_id,
        "schema_version": spec.schema_version,
        "shared_instances": spec.shared_instances,
        "team_id": spec.team_id,
    }


def team_spec_from_data(value: object) -> TeamSpecification:
    obj = require_object(value, "team specification")
    require_exact_keys(
        obj,
        {
            "component_agent_ids",
            "description",
            "partner_convention_id",
            "schema_version",
            "shared_instances",
            "team_id",
        },
        "team specification",
    )
    if obj["schema_version"] != TEAM_SPEC_SCHEMA_VERSION:
        raise RegistryError("unsupported team specification schema_version")
    components = obj["component_agent_ids"]
    if type(components) is not list or len(components) != 2:
        raise RegistryError("component_agent_ids must contain exactly two IDs")
    return TeamSpecification.build(
        component_agent_ids=(components[0], components[1]),
        partner_convention_id=obj["partner_convention_id"],
        shared_instances=obj["shared_instances"],
        description=obj["description"],
        claimed_team_id=obj["team_id"],
    )
