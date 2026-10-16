"""Separate Phase 5D-B registry for root information-set UCT agents.

The Phase 5C registry is intentionally not extended: its digest and the negative
baseline identity are frozen historical evidence.  This module owns the new
configuration family and its independently content-addressed specifications.
"""

from __future__ import annotations

from tuppi_eval.identities import (
    AgentSpecification,
    DeterminismClass,
    SeedPolicy,
    TeamSpecification,
)
from tuppi_eval.serialization import content_digest

from .errors import SearchConfigurationError
from .root_info_uct import (
    ROOT_INFO_UCT_PROTOCOL_VERSION,
    RootInfoUctConfiguration,
    RootInfoUctAgent,
    construct_root_info_uct_agent,
)


ROOT_INFO_UCT_AGENT_FAMILY = "root_information_set_uct"
ROOT_INFO_UCT_AGENT_VERSION = "1.0.0"
ROOT_INFO_UCT_IMPLEMENTATION = "tuppi_search.root_info_uct:root_info_uct_v1"
ROOT_INFO_UCT_RULESET_ID = "project_target_v1"
ROOT_INFO_UCT_OBSERVATION_SCHEMA_ID = "tuppi.engine.player_observation.v1"
ROOT_INFO_UCT_POLICY_SEED = "tuppi-phase5d-b-policy-seed-v1"


def smoke_configuration() -> RootInfoUctConfiguration:
    return RootInfoUctConfiguration.build(simulation_budget=2)


def small_configuration() -> RootInfoUctConfiguration:
    return RootInfoUctConfiguration.build(simulation_budget=4)


def standard_configuration() -> RootInfoUctConfiguration:
    return RootInfoUctConfiguration.build(simulation_budget=8)


REGISTERED_ROOT_INFO_UCT_CONFIGURATIONS: dict[str, RootInfoUctConfiguration] = {
    "root_info_uct_smoke_v1": smoke_configuration(),
    "root_info_uct_small_v1": small_configuration(),
    "root_info_uct_standard_v1": standard_configuration(),
}

ROOT_INFO_UCT_PRIMARY_PROFILE_KEY = "root_info_uct_small_v1"

_DESCRIPTIONS = {
    "root_info_uct_smoke_v1": "Two-simulation CI configuration for the observation-safe root information-set tree.",
    "root_info_uct_small_v1": "Four-simulation Phase 5D-B development configuration for root information-set UCT.",
    "root_info_uct_standard_v1": "Eight-simulation Phase 5D-B development configuration for root information-set UCT.",
}


def specification_for_configuration(
    profile_key: str, configuration: RootInfoUctConfiguration
) -> AgentSpecification:
    if profile_key not in _DESCRIPTIONS:
        raise SearchConfigurationError(f"unknown root-information UCT profile {profile_key!r}")
    payload = {
        **configuration.identity_data(),
        "belief_model": "uniform_hard_feasible_v1",
        "hidden_hand_sampling": configuration.sampler_algorithm_id,
        "information_set_search": ROOT_INFO_UCT_PROTOCOL_VERSION,
        "learned_world_weighting": None,
        "learning": None,
        "observation_only": True,
        "persistent_search_tree": None,
        "profile_key": profile_key,
        "root_info_uct_configuration_id": configuration.configuration_id,
        "self_play_training": None,
        "showing_policy_key": configuration.showing_policy_key,
    }
    return AgentSpecification.build(
        agent_family=ROOT_INFO_UCT_AGENT_FAMILY,
        configuration_version=ROOT_INFO_UCT_AGENT_VERSION,
        implementation_reference=ROOT_INFO_UCT_IMPLEMENTATION,
        ruleset_compatibility=(ROOT_INFO_UCT_RULESET_ID,),
        observation_schema_compatibility=(ROOT_INFO_UCT_OBSERVATION_SCHEMA_ID,),
        determinism=DeterminismClass.DETERMINISTIC,
        seed_policy=SeedPolicy.NONE,
        configuration=payload,
        model_checkpoint_id=None,
        search_budget=configuration.simulation_budget,
        partner_convention_id=None,
        description=(
            f"{_DESCRIPTIONS[profile_key]} Only the original root seat uses UCT; "
            "partner and opponents are frozen observation-only policies. Showing "
            "delegates exactly to partner_aware_v1, and the tree is per decision."
        ),
    )


def root_info_uct_specifications() -> dict[str, AgentSpecification]:
    mapping = {
        key: specification_for_configuration(key, configuration)
        for key, configuration in REGISTERED_ROOT_INFO_UCT_CONFIGURATIONS.items()
    }
    if len({item.agent_id for item in mapping.values()}) != len(mapping):
        raise SearchConfigurationError("root-information UCT profiles collided on agent identity")
    return mapping


def specification_for(profile_key: str) -> AgentSpecification:
    try:
        return root_info_uct_specifications()[profile_key]
    except KeyError as exc:
        raise SearchConfigurationError(f"unknown root-information UCT profile {profile_key!r}") from exc


def configuration_for(profile_key: str) -> RootInfoUctConfiguration:
    try:
        return REGISTERED_ROOT_INFO_UCT_CONFIGURATIONS[profile_key]
    except KeyError as exc:
        raise SearchConfigurationError(f"unknown root-information UCT profile {profile_key!r}") from exc


def build_agent(
    profile_key: str,
    *,
    seat: int,
    policy_seed: str = ROOT_INFO_UCT_POLICY_SEED,
) -> RootInfoUctAgent:
    return construct_root_info_uct_agent(
        specification_for(profile_key),
        seat=seat,
        configuration=configuration_for(profile_key),
        policy_seed=policy_seed,
    )


def homogeneous_team(profile_key: str = ROOT_INFO_UCT_PRIMARY_PROFILE_KEY) -> TeamSpecification:
    specification = specification_for(profile_key)
    return TeamSpecification.build(
        component_agent_ids=(specification.agent_id, specification.agent_id),
        partner_convention_id=None,
        shared_instances=False,
        description=(
            f"Homogeneous {profile_key} root-information UCT partnership; "
            "each seat has an independent per-decision tree."
        ),
    )


def registry_snapshot() -> dict[str, object]:
    specifications = root_info_uct_specifications()
    payload: dict[str, object] = {
        "agent_family": ROOT_INFO_UCT_AGENT_FAMILY,
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
        "agents_version": ROOT_INFO_UCT_AGENT_VERSION,
        "primary_profile_key": ROOT_INFO_UCT_PRIMARY_PROFILE_KEY,
        "promotion_status": (
            "No Phase 5D-B agent is promoted. All evaluation outputs are from a "
            "fresh unsealed development bank."
        ),
        "ruleset_id": ROOT_INFO_UCT_RULESET_ID,
        "schema_version": "tuppi.search.phase5d_b_registry.v1",
    }
    payload["registry_digest"] = content_digest(payload)
    return payload


ROOT_INFO_UCT_PROFILE_KEYS = tuple(sorted(REGISTERED_ROOT_INFO_UCT_CONFIGURATIONS))


__all__ = (
    "ROOT_INFO_UCT_AGENT_FAMILY",
    "ROOT_INFO_UCT_AGENT_VERSION",
    "ROOT_INFO_UCT_IMPLEMENTATION",
    "ROOT_INFO_UCT_POLICY_SEED",
    "ROOT_INFO_UCT_PRIMARY_PROFILE_KEY",
    "ROOT_INFO_UCT_PROFILE_KEYS",
    "REGISTERED_ROOT_INFO_UCT_CONFIGURATIONS",
    "build_agent",
    "configuration_for",
    "homogeneous_team",
    "registry_snapshot",
    "root_info_uct_specifications",
    "specification_for",
)
