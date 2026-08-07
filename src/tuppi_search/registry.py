"""Immutable Phase 5C search-agent identities.

Phase 5C adds specifications; it never rewrites Phase 4's or Phase 5A's. The
Phase 4 registry, its digest, and the frozen behaviour snapshot are untouched,
which :mod:`tuppi_search.validation` verifies rather than assumes.

Every behaviourally material field is inside the specification's configuration and
therefore inside its ``agent_id``: the PIMC protocol version, the sampler and
solver versions, the world count, the sample-index protocol, the replica count, the
rollout policy, the utility, the exact-tail switch and threshold, the tie-break, the
action ordering, the seed protocol, showing-search support, and the failure policy.
Change any of them and you get a different agent, not a tuned one.

Registered configurations
-------------------------

Only fully benchmarked configurations are registered. The world counts come from
the Phase 5C benchmark, not from a guess: a PIMC decision costs roughly
``legal_actions x world_count x rollout_ms``, with a measured rollout of about
6.8 ms per remaining trick, so the budget is what makes a complete-match comparison
finish at all. See `docs/search/phase5c_evaluation.md`.
"""

from __future__ import annotations

from tuppi_eval.identities import (
    AgentSpecification,
    DeterminismClass,
    SeedPolicy,
    TeamSpecification,
)

from .config import (
    DEVELOPMENT_REFERENCE_POLICY,
    ExactTailFailurePolicy,
    PimcConfiguration,
)
from .errors import SearchConfigurationError
from .utilities import UtilityId


RULESET_ID = "project_target_v1"
OBSERVATION_SCHEMA_ID = "tuppi.engine.player_observation.v1"
PHASE5C_AGENT_VERSION = "1.0.0"
IMPLEMENTATION_REFERENCE = "tuppi_search.agents:uniform_feasible_pimc_v1"
AGENT_FAMILY = "uniform_feasible_pimc"


def smoke_configuration() -> PimcConfiguration:
    """The cheapest configuration that still exercises every code path.

    Two worlds is not a serious search budget and is not presented as one. It
    exists so that continuous tests execute real world sampling, real rollouts,
    and real aggregation in seconds rather than minutes.
    """

    return PimcConfiguration.build(world_count=2)


def small_configuration() -> PimcConfiguration:
    return PimcConfiguration.build(world_count=4)


def standard_configuration() -> PimcConfiguration:
    return PimcConfiguration.build(world_count=8)


def exact_tail_configuration() -> PimcConfiguration:
    """The standard budget with the Phase 5B exact tail at the measured threshold."""

    return PimcConfiguration.build(
        world_count=8,
        exact_tail_enabled=True,
        exact_tail_max_tricks_remaining=4,
        exact_tail_failure_policy=ExactTailFailurePolicy.STRICT,
    )


def counting_rollout_configuration() -> PimcConfiguration:
    """The small budget with the weaker ``public_counting_v1`` rollout policy.

    An ablation identity: it isolates the rollout policy from the world budget, so
    "a stronger rollout policy helps" can be measured instead of assumed.
    """

    return PimcConfiguration.build(
        world_count=4, rollout_policy_key="public_counting_v1"
    )


def deal_utility_configuration() -> PimcConfiguration:
    """The small budget scoring official deal points instead of the match transition."""

    return PimcConfiguration.build(
        world_count=4, utility_id=UtilityId.DEAL_RESULT_V1
    )


#: The registered Phase 5C agents, keyed by their stable Phase 5C profile key.
REGISTERED_CONFIGURATIONS: dict[str, PimcConfiguration] = {
    "uniform_feasible_pimc_smoke_v1": smoke_configuration(),
    "uniform_feasible_pimc_small_v1": small_configuration(),
    "uniform_feasible_pimc_standard_v1": standard_configuration(),
    "uniform_feasible_pimc_exact_tail_v1": exact_tail_configuration(),
    "uniform_feasible_pimc_counting_rollout_v1": counting_rollout_configuration(),
    "uniform_feasible_pimc_deal_utility_v1": deal_utility_configuration(),
}

#: The configuration the phase designates for its primary complete-match
#: comparison. Frozen before the primary evaluation ran, as Phase 5A requires.
PRIMARY_PROFILE_KEY = "uniform_feasible_pimc_small_v1"

_DESCRIPTIONS: dict[str, str] = {
    "uniform_feasible_pimc_smoke_v1": (
        "Two-world continuous-integration configuration. Exercises the full search "
        "path cheaply and is not a strength claim of any kind."
    ),
    "uniform_feasible_pimc_small_v1": (
        "Four-world development configuration; the Phase 5C primary. Chosen because "
        "it is the largest budget whose complete-match comparison finishes in a "
        "practical time at measured throughput."
    ),
    "uniform_feasible_pimc_standard_v1": (
        "Eight-world configuration for deal-level comparison against the four-world "
        "budget, isolating the effect of world count."
    ),
    "uniform_feasible_pimc_exact_tail_v1": (
        "Eight worlds with the Phase 5B exact solver taking over at four tricks "
        "remaining. Changes the continuation policy, not the utility, and "
        "concentrates perfect-information bias."
    ),
    "uniform_feasible_pimc_counting_rollout_v1": (
        "Four worlds rolled out with public_counting_v1 instead of the development "
        "reference, isolating the rollout policy."
    ),
    "uniform_feasible_pimc_deal_utility_v1": (
        "Four worlds scoring official deal points instead of the post-deal match "
        "transition, isolating the utility adapter."
    ),
}


def specification_for_configuration(
    profile_key: str, configuration: PimcConfiguration
) -> AgentSpecification:
    """Build the immutable specification of one PIMC configuration."""

    if profile_key not in _DESCRIPTIONS:
        raise SearchConfigurationError(f"unknown Phase 5C profile {profile_key!r}")
    configuration.require_registerable_utility()
    payload = dict(configuration.identity_data())
    payload.update(
        {
            "belief_model": None,
            "hidden_hand_sampling": configuration.sampler_algorithm_id,
            "information_set_search": None,
            "learned_world_weighting": None,
            "learning": None,
            "observation_only": True,
            "persistent_search_tree": None,
            "pimc_configuration_id": configuration.configuration_id,
            "profile_key": profile_key,
            "search": configuration.pimc_protocol_version,
            "self_play_training": None,
        }
    )
    return AgentSpecification.build(
        agent_family=AGENT_FAMILY,
        configuration_version=PHASE5C_AGENT_VERSION,
        implementation_reference=IMPLEMENTATION_REFERENCE,
        ruleset_compatibility=(RULESET_ID,),
        observation_schema_compatibility=(OBSERVATION_SCHEMA_ID,),
        determinism=DeterminismClass.DETERMINISTIC,
        seed_policy=SeedPolicy.NONE,
        configuration=payload,
        model_checkpoint_id=None,
        search_budget=configuration.total_rollouts_per_candidate,
        partner_convention_id=None,
        description=(
            f"{_DESCRIPTIONS[profile_key]} Classical root PIMC over uniformly "
            "sampled hard-feasible worlds; a baseline, not an equilibrium solver, "
            "and subject to strategy fusion."
        ),
    )


def phase5c_specifications() -> dict[str, AgentSpecification]:
    """Every registered Phase 5C specification, keyed by profile key."""

    mapping = {
        key: specification_for_configuration(key, configuration)
        for key, configuration in REGISTERED_CONFIGURATIONS.items()
    }
    if len({item.agent_id for item in mapping.values()}) != len(mapping):
        raise SearchConfigurationError(
            "two registered PIMC configurations produced the same agent identity"
        )
    return mapping


def specification_for(profile_key: str) -> AgentSpecification:
    specifications = phase5c_specifications()
    if profile_key not in specifications:
        raise SearchConfigurationError(f"unknown Phase 5C profile {profile_key!r}")
    return specifications[profile_key]


def configuration_for(profile_key: str) -> PimcConfiguration:
    if profile_key not in REGISTERED_CONFIGURATIONS:
        raise SearchConfigurationError(f"unknown Phase 5C profile {profile_key!r}")
    return REGISTERED_CONFIGURATIONS[profile_key]


def build_agent(profile_key: str, *, seat: int, policy_seed: str | None = None):
    """Construct one registered PIMC agent for one seat."""

    from .agents import DEFAULT_POLICY_SEED, construct_pimc_agent

    return construct_pimc_agent(
        specification_for(profile_key),
        seat=seat,
        configuration=configuration_for(profile_key),
        policy_seed=policy_seed or DEFAULT_POLICY_SEED,
    )


def homogeneous_team(profile_key: str) -> TeamSpecification:
    """A partnership of two independently instantiated identical PIMC agents."""

    specification = specification_for(profile_key)
    return TeamSpecification.build(
        component_agent_ids=(specification.agent_id, specification.agent_id),
        partner_convention_id=None,
        shared_instances=False,
        description=(
            f"Homogeneous {profile_key} partnership; both seats receive "
            "independently instantiated identical PIMC agents."
        ),
    )


def registry_snapshot() -> dict[str, object]:
    """A canonical snapshot of the Phase 5C agent registry."""

    from tuppi_eval.serialization import content_digest

    specifications = phase5c_specifications()
    payload = {
        "agent_family": AGENT_FAMILY,
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
        "agents_version": PHASE5C_AGENT_VERSION,
        "development_reference_policy": DEVELOPMENT_REFERENCE_POLICY,
        "primary_profile_key": PRIMARY_PROFILE_KEY,
        "promotion_status": (
            "No Phase 5C agent is a promoted champion. Every result is from an "
            "unsealed development bank."
        ),
        "ruleset_id": RULESET_ID,
        "schema_version": "tuppi.search.phase5c_registry.v1",
    }
    payload["registry_digest"] = content_digest(payload)
    return payload


# --------------------------------------------------------------- Phase 5D-A


#: Phase 5C's primary configuration, designated a rejected development result.
#:
#: This is **metadata only**. The agent identity, its configuration, and the
#: committed Phase 5C registry digest are all unchanged, and
#: :func:`registry_snapshot` above still reproduces exactly what Phase 5C
#: committed. A designation records how a measured result should be *used*; it
#: never edits the thing that was measured.
NEGATIVE_BASELINE_DESIGNATION = "uniform_feasible_pimc_small_v1_negative_baseline"

NEGATIVE_BASELINE_PROFILE_KEY = PRIMARY_PROFILE_KEY

NEGATIVE_BASELINE_STATEMENT = (
    "Rejected as a development improvement. Over 32 complementary complete-match "
    "pairs from 0-0 this configuration lost to development_reference_v1 with "
    "p_win 0.156, CI [0.075, 0.238], sign-flip p = 0.0001, and 0 wins / 10 ties / "
    "22 losses, with zero censored legs and zero failed decisions. It remains "
    "useful as a regression fixture and as the comparator for later search "
    "families. No strength claim is made or implied about PIMC designs in "
    "general: one configuration was measured, not a family."
)


def negative_baseline_designation() -> dict[str, object]:
    """The frozen designation of the Phase 5C primary result."""

    specification = specification_for(NEGATIVE_BASELINE_PROFILE_KEY)
    configuration = configuration_for(NEGATIVE_BASELINE_PROFILE_KEY)
    return {
        "agent_id": specification.agent_id,
        "designation": NEGATIVE_BASELINE_DESIGNATION,
        "identity_unchanged": True,
        "pimc_configuration_id": configuration.configuration_id,
        "profile_key": NEGATIVE_BASELINE_PROFILE_KEY,
        "schema_version": "tuppi.search.negative_baseline_designation.v1",
        "scope_limit": (
            "One configuration was measured. The designation applies to that "
            "configuration only."
        ),
        "statement": NEGATIVE_BASELINE_STATEMENT,
        "uses": [
            "regression fixture for search-layer changes",
            "comparator for later information-set search families",
        ],
    }


def play_only_gate() -> "PhaseGatedConfiguration":
    """PIMC for every card; the frozen reference policy for the show."""

    from .hybrid import PhaseGatedConfiguration, SearchedPhase

    return PhaseGatedConfiguration.build(
        searched_phase=SearchedPhase.TRICK_PLAY_ONLY,
        pimc=configuration_for(PRIMARY_PROFILE_KEY),
    )


def show_only_gate() -> "PhaseGatedConfiguration":
    """PIMC for the show; the frozen reference policy for every card."""

    from .hybrid import PhaseGatedConfiguration, SearchedPhase

    return PhaseGatedConfiguration.build(
        searched_phase=SearchedPhase.SHOWING_ONLY,
        pimc=configuration_for(PRIMARY_PROFILE_KEY),
    )


#: The Phase 5D-A diagnostic agents. Deliberately a *separate* registry: adding
#: them to REGISTERED_CONFIGURATIONS would change that registry's digest and
#: contradict the committed Phase 5C artifact.
PHASE5D_A_GATES: dict[str, object] = {
    "uniform_feasible_pimc_play_only_v1": play_only_gate(),
    "uniform_feasible_pimc_show_only_v1": show_only_gate(),
}

_PHASE5D_A_DESCRIPTIONS: dict[str, str] = {
    "uniform_feasible_pimc_play_only_v1": (
        "Card-play PIMC with the frozen partner_aware_v1 showing policy. Isolates "
        "trick-play search from contract-selection search, and is cheaper because "
        "showing roots are the most expensive decisions in a deal."
    ),
    "uniform_feasible_pimc_show_only_v1": (
        "Contract-selection PIMC with the frozen partner_aware_v1 card play. "
        "Isolates whether the elevated RAMI declaration rate Phase 5C measured is "
        "responsible for the negative result."
    ),
}


def phase5d_a_specification(profile_key: str) -> AgentSpecification:
    """Build the immutable specification of one phase-gated diagnostic agent."""

    if profile_key not in PHASE5D_A_GATES:
        raise SearchConfigurationError(f"unknown Phase 5D-A profile {profile_key!r}")
    gate = PHASE5D_A_GATES[profile_key]
    gate.pimc.require_registerable_utility()
    payload = dict(gate.pimc.identity_data())
    payload.update(
        {
            "belief_model": None,
            "delegated_phase": gate.to_data()["delegated_phase"],
            "frozen_delegate_policy_key": gate.delegate_policy_key,
            "hidden_hand_sampling": gate.pimc.sampler_algorithm_id,
            "information_set_search": None,
            "learned_world_weighting": None,
            "learning": None,
            "observation_only": True,
            "persistent_search_tree": None,
            "phase_gate_id": gate.gate_id,
            "pimc_configuration_id": gate.pimc.configuration_id,
            "profile_key": profile_key,
            "recursive_search": None,
            "search": gate.pimc.pimc_protocol_version,
            "searched_phase": gate.searched_phase.value,
            "self_play_training": None,
        }
    )
    return AgentSpecification.build(
        agent_family="phase_gated_uniform_feasible_pimc",
        configuration_version=PHASE5C_AGENT_VERSION,
        implementation_reference="tuppi_search.hybrid:phase_gated_pimc_v1",
        ruleset_compatibility=(RULESET_ID,),
        observation_schema_compatibility=(OBSERVATION_SCHEMA_ID,),
        determinism=DeterminismClass.DETERMINISTIC,
        seed_policy=SeedPolicy.NONE,
        configuration=payload,
        model_checkpoint_id=None,
        search_budget=gate.pimc.total_rollouts_per_candidate,
        partner_convention_id=None,
        description=(
            f"{_PHASE5D_A_DESCRIPTIONS[profile_key]} A Phase 5D-A diagnostic "
            "identity; one-ply PIMC with no recursion, and not a promoted agent."
        ),
    )


def phase5d_a_specifications() -> dict[str, AgentSpecification]:
    mapping = {
        key: phase5d_a_specification(key) for key in PHASE5D_A_GATES
    }
    if len({item.agent_id for item in mapping.values()}) != len(mapping):
        raise SearchConfigurationError(
            "two Phase 5D-A configurations produced the same agent identity"
        )
    phase5c = {item.agent_id for item in phase5c_specifications().values()}
    for key, specification in mapping.items():
        if specification.agent_id in phase5c:
            raise SearchConfigurationError(
                f"{key} collides with a Phase 5C agent identity"
            )
    return mapping


def gate_for(profile_key: str) -> "PhaseGatedConfiguration":
    if profile_key not in PHASE5D_A_GATES:
        raise SearchConfigurationError(f"unknown Phase 5D-A profile {profile_key!r}")
    return PHASE5D_A_GATES[profile_key]


def is_phase5d_a_profile(profile_key: str) -> bool:
    return profile_key in PHASE5D_A_GATES


def build_phase5d_a_agent(
    profile_key: str, *, seat: int, policy_seed: str | None = None
):
    """Construct one registered Phase 5D-A diagnostic agent for one seat."""

    from .agents import DEFAULT_POLICY_SEED
    from .hybrid import construct_gated_agent

    return construct_gated_agent(
        phase5d_a_specification(profile_key),
        seat=seat,
        gate=gate_for(profile_key),
        policy_seed=policy_seed or DEFAULT_POLICY_SEED,
    )


def phase5d_a_registry_snapshot() -> dict[str, object]:
    """A canonical snapshot of the Phase 5D-A diagnostic registry."""

    from tuppi_eval.serialization import content_digest

    specifications = phase5d_a_specifications()
    payload = {
        "agents": [
            {
                "agent_id": specifications[key].agent_id,
                "configuration": specifications[key].configuration,
                "description": specifications[key].description,
                "phase_gate": PHASE5D_A_GATES[key].to_data(),
                "profile_key": key,
            }
            for key in sorted(specifications)
        ],
        "agents_version": PHASE5C_AGENT_VERSION,
        "development_reference_policy": DEVELOPMENT_REFERENCE_POLICY,
        "negative_baseline": negative_baseline_designation(),
        "phase": "phase5d-a",
        "phase5c_registry_digest_unchanged": registry_snapshot()["registry_digest"],
        "promotion_status": (
            "No Phase 5D-A agent is a promoted champion. These are diagnostic "
            "identities built to decompose a measured negative result."
        ),
        "purpose": (
            "Separate the Phase 5C failure into contract selection, card play, "
            "partnership mismatch, world budget, and rollout mismatch."
        ),
        "ruleset_id": RULESET_ID,
        "schema_version": "tuppi.search.phase5d_a_registry.v1",
    }
    payload["registry_digest"] = content_digest(payload)
    return payload
