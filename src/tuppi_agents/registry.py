"""Immutable Phase 4 agent and team identities registered with Phase 3.

Phase 4 adds specifications; it never rewrites the Phase 3 control definitions.
``phase4_registry`` returns a combined registry whose control entries are
byte-identical to :func:`tuppi_eval.registry.baseline_agent_specifications`.

Every strategic specification records explicitly that it has no search, no
belief model, no solver, no learning, and no hidden-hand sampling. Those fields
are ``null`` on purpose: a later phase that adds any of them must produce a new
agent identity rather than silently reusing a Phase 4 one.
"""

from __future__ import annotations

from tuppi_eval.identities import (
    AgentSpecification,
    DeterminismClass,
    SeedPolicy,
    TeamSpecification,
)
from tuppi_eval.registry import AgentRegistry

from .diagnostics import DIAGNOSTICS_SCHEMA_VERSION
from .errors import AgentConstructionError
from .controls import control_agent_specifications, control_specification
from .ordering import ACTION_ORDERING_ID, TIE_BREAK_ID
from .profiles import HeuristicProfile, registered_profiles
from .rule_catalogue import RULE_CATALOGUE_SCHEMA_VERSION


RULESET_ID = "project_target_v1"
OBSERVATION_SCHEMA_ID = "tuppi.engine.player_observation.v1"
PHASE4_AGENT_VERSION = "1.0.0"

STRATEGIC_PROFILE_KEYS: tuple[str, ...] = (
    "legacy_heuristic_port_v1",
    "match_aware_no_match_features_v1",
    "match_aware_v1",
    "partner_aware_legacy_convention_v1",
    "partner_aware_v1",
    "public_counting_v1",
    "reactive_contract_legacy_show_v1",
    "reactive_contract_v1",
)

LADDER_PROFILE_KEYS: tuple[str, ...] = (
    "legacy_heuristic_port_v1",
    "reactive_contract_v1",
    "public_counting_v1",
    "partner_aware_v1",
    "match_aware_v1",
)


def strategic_configuration(profile: HeuristicProfile) -> dict[str, object]:
    """Return the canonical identity-bearing configuration of one policy."""

    return {
        "action_ordering_id": ACTION_ORDERING_ID,
        "belief_model": None,
        "diagnostics_schema": DIAGNOSTICS_SCHEMA_VERSION,
        "endgame_solver": None,
        "hidden_hand_sampling": None,
        "learning": None,
        "observation_only": True,
        "profile": profile.to_data(),
        "profile_digest": profile.profile_id.removeprefix("profile:"),
        "profile_id": profile.profile_id,
        "rollout_budget": None,
        "rule_catalogue_schema": RULE_CATALOGUE_SCHEMA_VERSION,
        "search": None,
        "tie_break_id": TIE_BREAK_ID,
    }


def specification_for_profile(profile: HeuristicProfile) -> AgentSpecification:
    """Build the immutable specification of any profile, including ablations."""

    return AgentSpecification.build(
        agent_family=profile.family.value,
        configuration_version=PHASE4_AGENT_VERSION,
        implementation_reference=profile.implementation_reference,
        ruleset_compatibility=(RULESET_ID,),
        observation_schema_compatibility=(OBSERVATION_SCHEMA_ID,),
        determinism=DeterminismClass.DETERMINISTIC,
        seed_policy=SeedPolicy.NONE,
        configuration=strategic_configuration(profile),
        model_checkpoint_id=None,
        search_budget=None,
        partner_convention_id=profile.partner_convention_id,
        description=(
            f"{profile.description} Phase 4 transparent baseline; deterministic, "
            "observation-only, and not an expert-strength claim."
        ),
    )


def phase4_agent_specifications() -> tuple[AgentSpecification, ...]:
    profiles = registered_profiles()
    missing = set(STRATEGIC_PROFILE_KEYS) - set(profiles)
    if missing:
        raise AgentConstructionError(f"unregistered profile keys: {sorted(missing)}")
    return tuple(
        specification_for_profile(profiles[key]) for key in STRATEGIC_PROFILE_KEYS
    )


def phase4_specifications_by_profile_key() -> dict[str, AgentSpecification]:
    profiles = registered_profiles()
    mapping = {
        key: specification_for_profile(profiles[key]) for key in STRATEGIC_PROFILE_KEYS
    }
    if len({spec.agent_id for spec in mapping.values()}) != len(mapping):
        raise AgentConstructionError(
            "two registered profiles produced the same agent identity"
        )
    return mapping


def phase4_registry() -> AgentRegistry:
    """Return the combined Phase 3 control plus Phase 4 strategic registry."""

    return AgentRegistry.build(
        control_agent_specifications() + phase4_agent_specifications()
    )


def strategic_agent_id(profile_key: str) -> str:
    return phase4_specifications_by_profile_key()[profile_key].agent_id


def control_agent_id(agent_family: str) -> str:
    return control_specification(agent_family).agent_id


# --------------------------------------------------------------------- teams


def _clone_team(agent_id: str, *, label: str, convention: str | None) -> TeamSpecification:
    return TeamSpecification.build(
        component_agent_ids=(agent_id, agent_id),
        partner_convention_id=convention,
        shared_instances=False,
        description=(
            f"Homogeneous {label} partnership; both seats receive independently "
            "instantiated identical agents."
        ),
    )


def _mixed_team(
    first: str, second: str, *, label: str, convention: str | None
) -> TeamSpecification:
    return TeamSpecification.build(
        component_agent_ids=(first, second),
        partner_convention_id=convention,
        shared_instances=False,
        description=f"Heterogeneous {label} partnership.",
    )


def phase4_team_specifications() -> dict[str, TeamSpecification]:
    """Return the committed Phase 4 partnerships used by the evaluation manifests."""

    strategic = phase4_specifications_by_profile_key()
    profiles = registered_profiles()
    teams: dict[str, TeamSpecification] = {}
    for key, specification in strategic.items():
        teams[f"{key}_clone"] = _clone_team(
            specification.agent_id,
            label=key,
            convention=profiles[key].partner_convention_id,
        )
    for family in ("first_legal", "lowest_legal_card", "highest_legal_card", "seeded_random_legal"):
        teams[f"control_{family}_clone"] = _clone_team(
            control_agent_id(family), label=f"control {family}", convention=None
        )
    teams["heterogeneous_match_aware_with_reactive"] = _mixed_team(
        strategic["match_aware_v1"].agent_id,
        strategic["reactive_contract_v1"].agent_id,
        label="match-aware and reactive strategic",
        convention=None,
    )
    teams["heterogeneous_partner_aware_with_legacy_port"] = _mixed_team(
        strategic["partner_aware_v1"].agent_id,
        strategic["legacy_heuristic_port_v1"].agent_id,
        label="partner-aware and legacy-port strategic",
        convention=None,
    )
    teams["heterogeneous_match_aware_with_control"] = _mixed_team(
        strategic["match_aware_v1"].agent_id,
        control_agent_id("first_legal"),
        label="match-aware strategic and first-legal control",
        convention=None,
    )
    if len({team.team_id for team in teams.values()}) != len(teams):
        raise AgentConstructionError("two Phase 4 teams share one team identity")
    return teams


def phase4_team(name: str) -> TeamSpecification:
    teams = phase4_team_specifications()
    if name not in teams:
        raise AgentConstructionError(f"unknown Phase 4 team {name!r}")
    return teams[name]
