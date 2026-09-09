"""Declared research candidates must be constructible, pinned, and quarantined.

Three properties, one test group each:

* the evaluator's ordinary construction route reaches a declared candidate, which
  is the gap this registry exists to close;
* a candidate's identity is a content address over its base and its override, so
  an edited or undeclared candidate cannot be evaluated under a declared name;
* candidates stay out of the production lineage - being tested must not grant a
  policy a production identity.
"""

from __future__ import annotations

import pytest

from tuppi_agents.errors import AgentConstructionError, AgentsValidationError
from tuppi_agents.factory import construct_registered_agent
from tuppi_agents.improved_registry import improved_specifications_by_profile_key
from tuppi_agents.registry import phase4_specifications_by_profile_key
from tuppi_agents.research_candidates import (
    CANDIDATE_KEYS,
    REFERENCE_PREFIX,
    CandidateOverride,
    candidate_specifications_by_key,
    research_candidates,
    specification_for_candidate,
)
from tuppi_engine import (
    EnginePhase,
    ExplicitDeal,
    apply_match_action,
    begin_explicit_deal,
    create_match,
    match_observation_for,
)
from tuppi_eval.agents import construct_agent as evaluator_construct_agent
from tuppi_eval.identities import AgentSpecification
from tuppi_rules import FULL_DECK, MatchScore


def table(specification):
    return {
        seat: evaluator_construct_agent(specification, seed=None, seat=seat)
        for seat in range(4)
    }


def trace(specification) -> tuple[str, ...]:
    agents = table(specification)
    hands = tuple(tuple(FULL_DECK[seat * 13 : (seat + 1) * 13]) for seat in range(4))
    state = create_match(
        initial_score=MatchScore(), initial_dealer=0, match_ref="candidate-trace"
    )
    state = begin_explicit_deal(state, ExplicitDeal(dealer=0, hands=hands))
    actions: list[str] = []
    while state.phase in (EnginePhase.SHOWING, EnginePhase.TRICK_PLAY):
        actor = state.current_actor
        observation = match_observation_for(state, actor)
        action = agents[actor].choose_action(observation)
        assert action in observation.legal_actions
        actions.append(repr(action))
        state = apply_match_action(state, action)
    return tuple(actions)


# ---------------------------------------------------- the gap this closes
@pytest.mark.parametrize("candidate_key", CANDIDATE_KEYS)
def test_the_evaluator_route_constructs_every_declared_candidate(candidate_key):
    specification = candidate_specifications_by_key()[candidate_key]
    agents = table(specification)
    assert len({id(agent) for agent in agents.values()}) == 4
    assert {agent.identity for agent in agents.values()} == {specification.agent_id}


@pytest.mark.parametrize("candidate_key", CANDIDATE_KEYS)
def test_a_candidate_only_ever_returns_a_legal_action(candidate_key):
    # trace() asserts membership in the legal tuple at every decision
    assert len(trace(candidate_specifications_by_key()[candidate_key])) == 56


def test_the_noop_candidate_is_behaviourally_the_incumbent():
    incumbent = improved_specifications_by_profile_key()["partner_aware_lead_v2"]
    candidate = candidate_specifications_by_key()["research_noop_v1"]
    assert candidate.agent_id != incumbent.agent_id
    assert trace(candidate) == trace(incumbent)


def test_the_shift_candidate_really_differs():
    incumbent = improved_specifications_by_profile_key()["partner_aware_lead_v2"]
    candidate = candidate_specifications_by_key()["research_legal_shift_v1"]
    assert trace(candidate) != trace(incumbent)


# ------------------------------------------------------------- identity
def test_identity_is_a_content_address_over_base_and_override():
    declared = research_candidates()["research_legal_shift_v1"]
    original = specification_for_candidate(declared)
    from dataclasses import replace

    moved = replace(
        declared,
        override=CandidateOverride(
            override_id=declared.override.override_id,
            parameters=(("phase", "TRICK_PLAY"), ("shift", 2)),
        ),
    )
    assert specification_for_candidate(moved).agent_id != original.agent_id
    reworded = replace(declared, description=declared.description + " Reworded.")
    assert specification_for_candidate(reworded).agent_id == original.agent_id


def test_an_edited_candidate_specification_is_refused():
    specification = candidate_specifications_by_key()["research_legal_shift_v1"]
    tampered_configuration = dict(specification.configuration)
    tampered_configuration["override"] = {
        "override_id": "tuppi.research.legal_index_shift.v1",
        "parameters": {"phase": "TRICK_PLAY", "shift": 3},
    }
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
        partner_convention_id=specification.partner_convention_id,
        description=specification.description,
    )
    with pytest.raises(AgentConstructionError, match="disagrees with its declared"):
        construct_registered_agent(tampered, seat=0)


def test_an_undeclared_candidate_is_refused():
    specification = candidate_specifications_by_key()["research_noop_v1"]
    invented = AgentSpecification.build(
        agent_family="research_candidate_invented",
        configuration_version=specification.configuration_version,
        implementation_reference=f"{REFERENCE_PREFIX}not_declared_v1",
        ruleset_compatibility=specification.ruleset_compatibility,
        observation_schema_compatibility=(
            specification.observation_schema_compatibility
        ),
        determinism=specification.determinism,
        seed_policy=specification.seed_policy,
        configuration={"candidate_key": "not_declared_v1"},
        model_checkpoint_id=None,
        search_budget=None,
        partner_convention_id=None,
        description="Not in the registry.",
    )
    with pytest.raises(AgentConstructionError, match="undeclared research candidate"):
        construct_registered_agent(invented, seat=0)


def test_override_parameters_must_be_ordered_scalars():
    with pytest.raises(AgentsValidationError, match="sorted by name"):
        CandidateOverride(override_id="x", parameters=(("b", 1), ("a", 2)))
    with pytest.raises(AgentsValidationError, match="JSON scalar"):
        CandidateOverride(override_id="x", parameters=(("a", [1, 2]),))
    with pytest.raises(AgentsValidationError, match="duplicate parameter"):
        CandidateOverride(override_id="x", parameters=(("a", 1), ("a", 2)))


# ------------------------------------------------------------ quarantine
def test_candidates_are_not_in_the_production_lineage():
    candidate_ids = {
        spec.agent_id for spec in candidate_specifications_by_key().values()
    }
    production_ids = {
        spec.agent_id for spec in improved_specifications_by_profile_key().values()
    } | {spec.agent_id for spec in phase4_specifications_by_profile_key().values()}
    assert candidate_ids.isdisjoint(production_ids)
    assert not (set(CANDIDATE_KEYS) & set(improved_specifications_by_profile_key()))
    assert not (set(CANDIDATE_KEYS) & set(phase4_specifications_by_profile_key()))


def test_every_declared_candidate_is_marked_a_calibration_control():
    """The two seeded candidates are instrument controls, not proposals."""
    assert all(item.is_calibration_control for item in research_candidates().values())
    for item in research_candidates().values():
        assert "never promotable" in item.description


def test_phase4_and_improved_dispatch_are_unaffected():
    for specification in phase4_specifications_by_profile_key().values():
        assert construct_registered_agent(specification, seat=1).identity == (
            specification.agent_id
        )
    for specification in improved_specifications_by_profile_key().values():
        assert construct_registered_agent(specification, seat=1).identity == (
            specification.agent_id
        )
