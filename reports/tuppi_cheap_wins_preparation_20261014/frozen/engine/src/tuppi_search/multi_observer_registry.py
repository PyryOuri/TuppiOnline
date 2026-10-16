"""Separate Phase 5E registry for multi-observer search agents."""

from __future__ import annotations

from tuppi_eval.identities import AgentSpecification, DeterminismClass, SeedPolicy, TeamSpecification
from tuppi_eval.serialization import content_digest

from .errors import SearchConfigurationError
from .multi_observer import (
    MULTI_OBSERVER_ALGORITHM_ID,
    MULTI_OBSERVER_PROTOCOL_VERSION,
    MultiObserverAgent,
    MultiObserverConfiguration,
    construct_multi_observer_agent,
)


MULTI_OBSERVER_AGENT_FAMILY = "redeterminizing_multi_observer_search"
MULTI_OBSERVER_AGENT_VERSION = "1.0.0"
MULTI_OBSERVER_IMPLEMENTATION = "tuppi_search.multi_observer:redeterminizing_ismcts_v1"
MULTI_OBSERVER_RULESET_ID = "project_target_v1"
MULTI_OBSERVER_OBSERVATION_SCHEMA_ID = "tuppi.engine.player_observation.v1"
MULTI_OBSERVER_POLICY_SEED = "tuppi-phase5e-policy-seed-v1"


def smoke_configuration() -> MultiObserverConfiguration:
    return MultiObserverConfiguration.build(simulation_budget=2)


def small_configuration() -> MultiObserverConfiguration:
    return MultiObserverConfiguration.build(simulation_budget=8)


def standard_configuration() -> MultiObserverConfiguration:
    return MultiObserverConfiguration.build(simulation_budget=32)


REGISTERED_MULTI_OBSERVER_CONFIGURATIONS = {
    "multi_observer_ismcts_smoke_v1": smoke_configuration(),
    "multi_observer_ismcts_small_v1": small_configuration(),
    "multi_observer_ismcts_standard_v1": standard_configuration(),
}

MULTI_OBSERVER_PRIMARY_PROFILE_KEY = "multi_observer_ismcts_small_v1"
_DESCRIPTIONS = {
    "multi_observer_ismcts_smoke_v1": "Two-simulation CI multi-observer re-determinizing search.",
    "multi_observer_ismcts_small_v1": "Eight-simulation Phase 5E development multi-observer search.",
    "multi_observer_ismcts_standard_v1": "Thirty-two-simulation Phase 5E development multi-observer search.",
}


def specification_for_configuration(
    profile_key: str, configuration: MultiObserverConfiguration
) -> AgentSpecification:
    if profile_key not in _DESCRIPTIONS:
        raise SearchConfigurationError(f"unknown multi-observer profile {profile_key!r}")
    payload = {
        **configuration.identity_data(),
        "belief_model": "uniform_hard_feasible_v1",
        "hidden_hand_sampling": configuration.sampler_algorithm_id,
        "information_set_search": MULTI_OBSERVER_PROTOCOL_VERSION,
        "learned_world_weighting": None,
        "learning": None,
        "multi_observer_configuration_id": configuration.configuration_id,
        "observation_only": True,
        "persistent_search_tree": None,
        "profile_key": profile_key,
        "self_play_training": None,
        "showing_policy_key": configuration.showing_policy_key,
    }
    return AgentSpecification.build(
        agent_family=MULTI_OBSERVER_AGENT_FAMILY,
        configuration_version=MULTI_OBSERVER_AGENT_VERSION,
        implementation_reference=MULTI_OBSERVER_IMPLEMENTATION,
        ruleset_compatibility=(MULTI_OBSERVER_RULESET_ID,),
        observation_schema_compatibility=(MULTI_OBSERVER_OBSERVATION_SCHEMA_ID,),
        determinism=DeterminismClass.DETERMINISTIC,
        seed_policy=SeedPolicy.NONE,
        configuration=payload,
        model_checkpoint_id=None,
        search_budget=configuration.simulation_budget,
        partner_convention_id=None,
        description=(
            f"{_DESCRIPTIONS[profile_key]} Each seat has a per-decision shared tree, "
            "non-root tree actions re-determinize from the acting observation, and "
            "fallback/showing both use frozen partner_aware_v1."
        ),
    )


def multi_observer_specifications() -> dict[str, AgentSpecification]:
    mapping = {
        key: specification_for_configuration(key, configuration)
        for key, configuration in REGISTERED_MULTI_OBSERVER_CONFIGURATIONS.items()
    }
    if len({item.agent_id for item in mapping.values()}) != len(mapping):
        raise SearchConfigurationError("multi-observer profiles collided on identity")
    return mapping


def specification_for(profile_key: str) -> AgentSpecification:
    try:
        return multi_observer_specifications()[profile_key]
    except KeyError as exc:
        raise SearchConfigurationError(f"unknown multi-observer profile {profile_key!r}") from exc


def configuration_for(profile_key: str) -> MultiObserverConfiguration:
    try:
        return REGISTERED_MULTI_OBSERVER_CONFIGURATIONS[profile_key]
    except KeyError as exc:
        raise SearchConfigurationError(f"unknown multi-observer profile {profile_key!r}") from exc


def build_agent(
    profile_key: str,
    *,
    seat: int,
    policy_seed: str = MULTI_OBSERVER_POLICY_SEED,
) -> MultiObserverAgent:
    return construct_multi_observer_agent(
        specification_for(profile_key),
        seat=seat,
        configuration=configuration_for(profile_key),
        policy_seed=policy_seed,
    )


def homogeneous_team(profile_key: str = MULTI_OBSERVER_PRIMARY_PROFILE_KEY) -> TeamSpecification:
    specification = specification_for(profile_key)
    return TeamSpecification.build(
        component_agent_ids=(specification.agent_id, specification.agent_id),
        partner_convention_id=None,
        shared_instances=False,
        description=(
            f"Homogeneous {profile_key} multi-observer search partnership; "
            "each seat has an independent per-decision tree."
        ),
    )


def registry_snapshot() -> dict[str, object]:
    specifications = multi_observer_specifications()
    payload: dict[str, object] = {
        "agent_family": MULTI_OBSERVER_AGENT_FAMILY,
        "agents": [
            {
                "agent_id": specifications[key].agent_id,
                "configuration": specifications[key].configuration,
                "description": specifications[key].description,
                "profile_key": key,
                "search_budget": specifications[key].search_budget,
            }
            for key in sorted(specifications)
        ],
        "agents_version": MULTI_OBSERVER_AGENT_VERSION,
        "algorithm_id": MULTI_OBSERVER_ALGORITHM_ID,
        "primary_profile_key": MULTI_OBSERVER_PRIMARY_PROFILE_KEY,
        "promotion_status": (
            "No Phase 5E agent is promoted. All outputs are from a fresh unsealed "
            "development bank."
        ),
        "ruleset_id": MULTI_OBSERVER_RULESET_ID,
        "schema_version": "tuppi.search.phase5e_registry.v1",
    }
    payload["registry_digest"] = content_digest(payload)
    return payload


MULTI_OBSERVER_PROFILE_KEYS = tuple(sorted(REGISTERED_MULTI_OBSERVER_CONFIGURATIONS))


__all__ = (
    "MULTI_OBSERVER_AGENT_FAMILY",
    "MULTI_OBSERVER_AGENT_VERSION",
    "MULTI_OBSERVER_POLICY_SEED",
    "MULTI_OBSERVER_PRIMARY_PROFILE_KEY",
    "MULTI_OBSERVER_PROFILE_KEYS",
    "REGISTERED_MULTI_OBSERVER_CONFIGURATIONS",
    "build_agent",
    "configuration_for",
    "homogeneous_team",
    "multi_observer_specifications",
    "registry_snapshot",
    "specification_for",
)
