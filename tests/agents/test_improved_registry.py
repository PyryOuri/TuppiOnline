"""The improved policies must be citable without disturbing the frozen baseline.

Three properties matter here and each has its own test below:

* the improved identities are content addresses over the improved *behaviour*,
  so a changed layer parameter mints a new one and a reworded description does
  not;
* the chain is transitive - ``partner_aware_discard_v3`` extends
  ``partner_aware_lead_v2``, so its address moves when the parent's does;
* nothing about Phase 4 changes, because every Phase 4, 5 and 6 result is quoted
  against those identities.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from tuppi_agents import phase4_specifications_by_profile_key
from tuppi_agents.errors import AgentsValidationError
from tuppi_agents.improved_registry import (
    CORPUS_REFERENCE_PROFILE_KEY,
    IMPROVED_PROFILE_KEYS,
    PolicyLayer,
    construct_improved_agent,
    corpus_reference_specification,
    improved_agents_for_seats,
    improved_policies,
    improved_specifications_by_profile_key,
    specification_for_improved_policy,
)
from tuppi_agents.nolo_discard import liability_discard_agents_for_seats
from tuppi_agents.registry import STRATEGIC_PROFILE_KEYS
from tuppi_agents.void_lead import construct_void_lead_agent
from tuppi_engine import (
    EnginePhase,
    apply_match_action,
    begin_explicit_deal,
    create_match,
    match_observation_for,
)
from tuppi_engine.serialization import action_to_data
from tuppi_match.streams import MatchStream
from tuppi_rules import MatchScore


# The frozen identities of the improved policies. A change here is a deliberate
# new policy identity, not a test to update: every corpus manifest, evaluation
# record and report that cites one of these strings refers to the behaviour
# declared in ``improved_registry`` at the moment it was generated.
FROZEN_IMPROVED_AGENT_IDS = {
    "partner_aware_lead_v2": (
        "agent:sha256:252fe227b01900e3c1d94822179adee07a64e3a3eb761a529a425f39b95d435d"
    ),
    "partner_aware_discard_v3": (
        "agent:sha256:4b52fd908698de131ab1c9c4562b37da8da4733b8005b0e935fbd15339a17634"
    ),
}

# ``partner_aware_v1`` is the base of both improved policies and the reference
# every earlier phase is measured against.
FROZEN_BASE_AGENT_ID = (
    "agent:sha256:d8b426f1263c7ce32bdef82e4971dc2e494950f155e15db9b69fc6334a2ac929"
)


def _play(agents, streams: int = 3, deals: int = 6) -> list[object]:
    """Every action, in order, plus each match's score - the behaviour itself."""

    trace: list[object] = []
    for index in range(streams):
        stream = MatchStream.build(
            root_seed="improved-registry-test-v1",
            stream_index=index,
            initial_dealer=index % 4,
        )
        table = agents()
        state = create_match(
            initial_score=MatchScore(0, 0),
            initial_dealer=stream.initial_dealer,
            match_ref=f"improved-{index:06d}",
        )
        deal_index = 0
        while not state.terminal and deal_index < deals:
            if state.phase in (EnginePhase.AWAITING_DEAL, EnginePhase.DEAL_COMPLETE):
                state = begin_explicit_deal(
                    state, stream.deal(deal_index).explicit_deal(state.dealer)
                )
                deal_index += 1
                continue
            actor = state.current_actor
            observation = match_observation_for(state, actor)
            action = table[actor].choose_action(observation)
            trace.append((index, actor, action_to_data(action)))
            state = apply_match_action(state, action)
        trace.append((index, "score", (state.score.team0, state.score.team1)))
    return trace


def test_improved_identities_are_frozen() -> None:
    specifications = improved_specifications_by_profile_key()
    assert set(specifications) == set(IMPROVED_PROFILE_KEYS)
    for key, expected in FROZEN_IMPROVED_AGENT_IDS.items():
        assert specifications[key].agent_id == expected, (
            f"{key} changed identity; that is a new policy, not a stale test"
        )


def test_phase4_identities_are_untouched() -> None:
    """Registering the improved policies must not move the frozen baseline."""

    phase4 = phase4_specifications_by_profile_key()
    assert phase4["partner_aware_v1"].agent_id == FROZEN_BASE_AGENT_ID
    assert set(phase4) == set(STRATEGIC_PROFILE_KEYS)
    for key in IMPROVED_PROFILE_KEYS:
        assert key not in STRATEGIC_PROFILE_KEYS
        assert key not in phase4


def test_improved_identities_never_collide_with_phase4() -> None:
    phase4 = {spec.agent_id for spec in phase4_specifications_by_profile_key().values()}
    improved = {
        spec.agent_id for spec in improved_specifications_by_profile_key().values()
    }
    assert not phase4 & improved
    assert len(improved) == len(IMPROVED_PROFILE_KEYS)


def test_a_changed_layer_parameter_mints_a_new_identity() -> None:
    policy = improved_policies()["partner_aware_lead_v2"]
    original = specification_for_improved_policy(policy)
    tweaked_layer = replace(
        policy.layers[0], parameters=(("primary_key", "longest_suit"),)
    )
    tweaked = specification_for_improved_policy(
        replace(policy, layers=(tweaked_layer,) + policy.layers[1:])
    )
    assert tweaked.agent_id != original.agent_id


def test_a_reworded_description_does_not_mint_a_new_identity() -> None:
    policy = improved_policies()["partner_aware_lead_v2"]
    original = specification_for_improved_policy(policy)
    reworded = specification_for_improved_policy(
        replace(policy, description="Entirely different prose, identical behaviour.")
    )
    assert reworded.agent_id == original.agent_id


def test_a_reordered_layer_stack_mints_a_new_identity() -> None:
    policy = improved_policies()["partner_aware_lead_v2"]
    original = specification_for_improved_policy(policy)
    reordered = specification_for_improved_policy(
        replace(policy, layers=tuple(reversed(policy.layers)))
    )
    assert reordered.agent_id != original.agent_id


def test_the_chain_is_transitive() -> None:
    """A change to ``lead_v2`` must move ``discard_v3``'s address too."""

    declared = improved_policies()
    discard = declared["partner_aware_discard_v3"]
    resolved = improved_specifications_by_profile_key()
    assert discard.base_improved_key == "partner_aware_lead_v2"

    with_parent = specification_for_improved_policy(
        discard,
        base_improved_agent_id=resolved["partner_aware_lead_v2"].agent_id,
    )
    with_other_parent = specification_for_improved_policy(
        discard, base_improved_agent_id="agent:sha256:" + "0" * 64
    )
    assert with_parent.agent_id == resolved["partner_aware_discard_v3"].agent_id
    assert with_other_parent.agent_id != with_parent.agent_id


def test_the_new_constructors_change_the_identity_and_nothing_else() -> None:
    """The whole point: a citable id, with byte-identical play."""

    existing_lead = _play(lambda: {s: construct_void_lead_agent(s) for s in range(4)})
    registered_lead = _play(lambda: improved_agents_for_seats("partner_aware_lead_v2"))
    assert existing_lead == registered_lead

    existing_discard = _play(lambda: liability_discard_agents_for_seats(range(4)))
    registered_discard = _play(
        lambda: improved_agents_for_seats("partner_aware_discard_v3")
    )
    assert existing_discard == registered_discard

    # And the two improved policies are genuinely different players.
    assert existing_lead != existing_discard


def test_constructed_agents_report_the_content_addressed_identity() -> None:
    specifications = improved_specifications_by_profile_key()
    for key in IMPROVED_PROFILE_KEYS:
        agent = construct_improved_agent(key, seat=2)
        assert agent.identity == specifications[key].agent_id
        assert agent.identity.startswith("agent:sha256:")


def test_the_corpus_reference_is_the_improved_lead_policy() -> None:
    assert CORPUS_REFERENCE_PROFILE_KEY == "partner_aware_lead_v2"
    assert (
        corpus_reference_specification().agent_id
        == FROZEN_IMPROVED_AGENT_IDS["partner_aware_lead_v2"]
    )


def test_seat_and_profile_arguments_are_validated() -> None:
    with pytest.raises(AgentsValidationError):
        construct_improved_agent("partner_aware_lead_v2", seat=4)
    with pytest.raises(AgentsValidationError):
        construct_improved_agent("partner_aware_lead_v2", seat=True)
    with pytest.raises(AgentsValidationError):
        construct_improved_agent("no_such_policy_v1", seat=0)
    with pytest.raises(AgentsValidationError):
        improved_agents_for_seats("partner_aware_lead_v2", (0, 7))


def test_layer_declarations_are_strict() -> None:
    with pytest.raises(AgentsValidationError):
        PolicyLayer(layer_id="", supersedes=None, introduces=("x",), parameters=())
    with pytest.raises(AgentsValidationError):
        PolicyLayer(layer_id="a", supersedes=None, introduces=(), parameters=())
    with pytest.raises(AgentsValidationError):
        PolicyLayer(
            layer_id="a",
            supersedes=None,
            introduces=("x",),
            parameters=(("k", object()),),
        )
    with pytest.raises(AgentsValidationError):
        PolicyLayer(
            layer_id="a",
            supersedes=None,
            introduces=("x",),
            parameters=(("k", 1), ("k", 2)),
        )
    with pytest.raises(AgentsValidationError):
        PolicyLayer(
            layer_id="a",
            supersedes=None,
            introduces=("x",),
            parameters=(),
            catalogued=True,
        )


def test_every_improved_layer_declares_what_it_supersedes_or_adds() -> None:
    for policy in improved_policies().values():
        assert policy.layers
        for layer in policy.layers:
            assert layer.catalogued is False
            assert layer.introduces
            assert layer.layer_id.startswith("tuppi.agents.")
