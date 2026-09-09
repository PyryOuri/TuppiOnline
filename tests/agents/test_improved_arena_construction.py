"""An improved policy must be reachable through the ordinary evaluator route.

The improved policies are declared in ``improved_registry`` and are deliberately
not Phase 4 profiles, but they carry a ``tuppi_agents.*`` implementation
reference. That reference is what ``tuppi_eval.agents.construct_agent`` uses to
route a registry agent ID into ``construct_registered_agent``, so before the
delegation added to the factory an improved specification reached the Phase 4
branch, missed ``POLICY_IMPLEMENTATIONS`` and was refused - which meant the
evaluator's arena could not run the profile at all.

These tests pin that the evaluator route now constructs the declared policy, one
fresh object per seat, without loosening anything: Phase 4 dispatch, the
unsupported-reference refusal and specification-tampering refusal all stand.
"""

from __future__ import annotations

import pytest

from tuppi_agents import phase4_specifications_by_profile_key
from tuppi_agents.errors import AgentConstructionError
from tuppi_agents.factory import construct_registered_agent
from tuppi_agents.improved_registry import (
    IMPROVED_PROFILE_KEYS,
    improved_specifications_by_profile_key,
)
from tuppi_eval.agents import construct_agent as evaluator_construct_agent
from tuppi_eval.identities import AgentSpecification


@pytest.mark.parametrize("profile_key", IMPROVED_PROFILE_KEYS)
def test_evaluator_route_constructs_every_declared_improved_policy(
    profile_key: str,
) -> None:
    specification = improved_specifications_by_profile_key()[profile_key]
    agents = [
        evaluator_construct_agent(specification, seed=None, seat=seat)
        for seat in range(4)
    ]
    assert len({id(agent) for agent in agents}) == 4
    assert {agent.identity for agent in agents} == {specification.agent_id}


def test_improved_agent_reports_its_content_addressed_identity() -> None:
    specification = improved_specifications_by_profile_key()["partner_aware_lead_v2"]
    agent = construct_registered_agent(specification, seat=0)
    assert agent.identity == specification.agent_id
    assert agent.identity.startswith("agent:sha256:")


def test_phase4_dispatch_is_unchanged() -> None:
    for key, specification in phase4_specifications_by_profile_key().items():
        agent = construct_registered_agent(specification, seat=1)
        assert agent.identity == specification.agent_id, key


def test_an_unknown_tuppi_agents_reference_is_still_refused() -> None:
    specification = improved_specifications_by_profile_key()["partner_aware_lead_v2"]
    invented = AgentSpecification.build(
        agent_family=specification.agent_family,
        configuration_version=specification.configuration_version,
        implementation_reference="tuppi_agents.invented:not_a_policy_v1",
        ruleset_compatibility=specification.ruleset_compatibility,
        observation_schema_compatibility=(
            specification.observation_schema_compatibility
        ),
        determinism=specification.determinism,
        seed_policy=specification.seed_policy,
        configuration=specification.configuration,
        model_checkpoint_id=None,
        search_budget=None,
        partner_convention_id=None,
        description=specification.description,
    )
    with pytest.raises(AgentConstructionError, match="unsupported Phase 4 reference"):
        construct_registered_agent(invented, seat=0)


def test_an_edited_improved_configuration_is_refused() -> None:
    specification = improved_specifications_by_profile_key()["partner_aware_lead_v2"]
    tampered_configuration = dict(specification.configuration)
    tampered_configuration["search"] = 100
    tampered = AgentSpecification.build(
        agent_family=specification.agent_family,
        configuration_version=specification.configuration_version,
        implementation_reference=specification.implementation_reference,
        ruleset_compatibility=specification.ruleset_compatibility,
        observation_schema_compatibility=(
            specification.observation_schema_compatibility
        ),
        determinism=specification.determinism,
        seed_policy=specification.seed_policy,
        configuration=tampered_configuration,
        model_checkpoint_id=None,
        search_budget=None,
        partner_convention_id=None,
        description=specification.description,
    )
    assert tampered.agent_id != specification.agent_id
    with pytest.raises(AgentConstructionError):
        construct_registered_agent(tampered, seat=0)


def test_a_seed_and_a_bad_seat_are_refused_before_improved_dispatch() -> None:
    specification = improved_specifications_by_profile_key()["partner_aware_lead_v2"]
    with pytest.raises(AgentConstructionError, match="take no seed"):
        construct_registered_agent(specification, seat=0, seed="abc")
    with pytest.raises(AgentConstructionError, match="seat must be in"):
        construct_registered_agent(specification, seat=4)
