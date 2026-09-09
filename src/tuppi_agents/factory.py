"""Construct a Phase 4 agent from an immutable specification and a seat.

The factory receives exactly three things: the specification, the seat, and (for
the seeded protocol controls only) an explicit seed. It never receives engine
state, a deal, an evaluator, or a writer. Every call returns a *fresh* runtime
object so that no two seats can share mutable state.
"""

from __future__ import annotations

from tuppi_engine import Action, Agent
from tuppi_eval.identities import AgentSpecification

from .controls import construct_control_agent
from .counting import PublicCountingPolicy
from .errors import AgentConstructionError
from .legacy_port import LegacyHeuristicPortPolicy
from .match_aware import MatchAwarePolicy
from .partner_aware import PartnerAwarePolicy
from .profiles import HeuristicProfile, profile_from_data
from .protocol import RuleBasedPolicy
from .reactive import ReactiveContractPolicy
from .registry import strategic_configuration


POLICY_IMPLEMENTATIONS: dict[str, type[RuleBasedPolicy]] = {
    "tuppi_agents.factory:legacy_heuristic_port_v1": LegacyHeuristicPortPolicy,
    "tuppi_agents.factory:match_aware_v1": MatchAwarePolicy,
    "tuppi_agents.factory:partner_aware_v1": PartnerAwarePolicy,
    "tuppi_agents.factory:public_counting_v1": PublicCountingPolicy,
    "tuppi_agents.factory:reactive_contract_v1": ReactiveContractPolicy,
}


def is_phase4_reference(implementation_reference: object) -> bool:
    return (
        isinstance(implementation_reference, str)
        and implementation_reference.startswith("tuppi_agents.")
    )


def profile_of(specification: AgentSpecification) -> HeuristicProfile:
    """Recover and revalidate the profile embedded in a specification."""

    if not isinstance(specification, AgentSpecification):
        raise AgentConstructionError("a Phase 4 agent requires an AgentSpecification")
    configuration = specification.configuration
    raw = configuration.get("profile")
    if raw is None:
        raise AgentConstructionError("specification carries no heuristic profile")
    profile = profile_from_data(raw)
    if strategic_configuration(profile) != configuration:
        raise AgentConstructionError(
            "specification configuration disagrees with its declared profile"
        )
    if profile.implementation_reference != specification.implementation_reference:
        raise AgentConstructionError(
            "profile family disagrees with the implementation reference"
        )
    return profile


def _construct_improved_if_declared(
    specification: AgentSpecification, *, seat: int
) -> Agent | None:
    """Construct a declared improved policy, or return ``None`` if it is not one.

    Improved policies (``partner_aware_lead_v2`` and its successors) are declared
    in :mod:`improved_registry`, not in ``POLICY_IMPLEMENTATIONS``, and are
    deliberately not Phase 4 profiles: their configuration is the layered improved
    configuration, so :func:`profile_of` rejects them. They do carry a
    ``tuppi_agents.*`` implementation reference, which is what routes an
    evaluator-registry agent ID into :func:`construct_registered_agent`, so
    without this delegation a declared improved policy cannot be evaluated through
    the ordinary arena path at all.

    Matching is by identity, not by name: the specification must equal the one the
    improved registry itself resolves, so a caller cannot substitute a forged or
    edited improved specification for the declared one. Only consulted after the
    Phase 4 lookup has already missed, so Phase 4 construction is unaffected.
    """

    from .improved_registry import (
        improved_agent_from_specification,
        improved_specifications_by_profile_key,
    )

    agent_id = getattr(specification, "agent_id", None)
    if not isinstance(agent_id, str):
        return None
    for profile_key, declared in improved_specifications_by_profile_key().items():
        if declared.agent_id != agent_id:
            continue
        if declared != specification:
            raise AgentConstructionError(
                "improved specification disagrees with its declared registry entry"
            )
        if specification.determinism.value != "deterministic":
            raise AgentConstructionError("an improved policy must be deterministic")
        if specification.search_budget is not None:
            raise AgentConstructionError(
                "improved policies must declare no search budget"
            )
        if specification.model_checkpoint_id is not None:
            raise AgentConstructionError("improved policies must declare no checkpoint")
        return improved_agent_from_specification(
            specification, profile_key=profile_key, seat=seat
        )
    return None


def _construct_candidate_if_declared(
    specification: AgentSpecification, *, seat: int
) -> Agent | None:
    """Construct a declared research candidate, or ``None`` if it is not one.

    Identity is checked inside :func:`research_candidates.construct_candidate_agent`,
    which refuses a specification that is not byte-for-byte the declared entry.
    """

    from .research_candidates import (
        construct_candidate_agent,
        is_research_candidate_reference,
    )

    if not is_research_candidate_reference(
        getattr(specification, "implementation_reference", None)
    ):
        return None
    return construct_candidate_agent(specification, seat=seat)


def construct_registered_agent(
    specification: AgentSpecification, *, seat: int, seed: str | None = None
) -> Agent:
    """Construct one Phase 4 strategic agent for exactly one seat."""

    if type(seat) is not int or seat not in range(4):
        raise AgentConstructionError("agent construction seat must be in 0..3")
    if seed is not None:
        raise AgentConstructionError(
            "Phase 4 strategic policies are deterministic and take no seed"
        )
    reference = specification.implementation_reference
    if not is_phase4_reference(reference):
        raise AgentConstructionError(
            f"{reference!r} is not a Phase 4 implementation reference"
        )
    policy_class = POLICY_IMPLEMENTATIONS.get(reference)
    if policy_class is None:
        improved = _construct_improved_if_declared(specification, seat=seat)
        if improved is not None:
            return improved
        # Research candidates are policies under test, declared in their own
        # registry and kept out of the production lineage on purpose. They are
        # routed here for the same reason the improved policies are: the
        # evaluator dispatches on a `tuppi_agents.*` reference and should stay
        # ignorant of what is being tried. Also a fall-through, so neither Phase 4
        # nor improved construction is affected.
        candidate = _construct_candidate_if_declared(specification, seat=seat)
        if candidate is not None:
            return candidate
        raise AgentConstructionError(f"unsupported Phase 4 reference {reference!r}")
    profile = profile_of(specification)
    if specification.determinism.value != "deterministic":
        raise AgentConstructionError("a Phase 4 policy must be deterministic")
    if specification.search_budget is not None:
        raise AgentConstructionError("Phase 4 policies must declare no search budget")
    if specification.model_checkpoint_id is not None:
        raise AgentConstructionError("Phase 4 policies must declare no checkpoint")
    return policy_class(agent_id=specification.agent_id, profile=profile)


def construct_agent(
    specification: AgentSpecification,
    *,
    seat: int,
    seed: str | None = None,
    scripted_actions: tuple[Action, ...] | None = None,
) -> Agent:
    """Construct any registered agent: Phase 4 strategic or Phase 3 control."""

    if is_phase4_reference(getattr(specification, "implementation_reference", None)):
        if scripted_actions is not None:
            raise AgentConstructionError(
                "Phase 4 strategic policies do not consume scripted actions"
            )
        return construct_registered_agent(specification, seat=seat, seed=seed)
    return construct_control_agent(
        specification, seat=seat, seed=seed, scripted_actions=scripted_actions
    )
