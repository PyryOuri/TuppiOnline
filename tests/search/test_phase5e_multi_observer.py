"""Focused Phase 5E protocol, privacy, and deterministic-tree tests."""

from __future__ import annotations

from dataclasses import replace
import json

import pytest

from tuppi_agents import construct_agent, phase4_specifications_by_profile_key
from tuppi_engine import DealState, EnginePhase, PlayerObservation
from tuppi_exact import HardConstraintModel, UniformFeasibleSampler
from tuppi_rules import FULL_DECK

from tuppi_search.diagnostics import FORBIDDEN_KEYS, observation_visible_card_codes, require_privacy_safe
from tuppi_search.fast_trick import FastTrickState
from tuppi_search.multi_observer import (
    MultiObserverConfiguration,
    decide,
    multi_observer_information_state_key,
    redeterminize_observer,
)
from tuppi_search.multi_observer import _root_sampling_seed
from tuppi_search.multi_observer_registry import build_agent
import tuppi_search.multi_observer as multi_module
from tuppi_search.information_state import root_information_state_key
from tuppi_search.tiny_multi_observer_reference import TinyMultiObserverReference
from tuppi_search.multi_observer import MultiObserverTree
from tuppi_search.errors import SearchConfigurationError


def test_showing_delegates_without_sampler(showing_position, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Phase 5E showing must not sample hidden worlds")

    monkeypatch.setattr(multi_module.UniformFeasibleSampler, "build", forbidden)
    observation = showing_position.observation
    decision = build_agent(
        "multi_observer_ismcts_smoke_v1", seat=observation.observing_seat
    ).explain(observation)
    frozen = construct_agent(
        phase4_specifications_by_profile_key()["partner_aware_v1"],
        seat=observation.observing_seat,
    )
    assert decision.showing_delegated is True
    assert decision.simulations_completed == 0
    assert decision.selected_action == frozen.choose_action(observation)


def test_smoke_decision_is_deterministic_and_legal(mid_position):
    seat = mid_position.observation.observing_seat
    agent = build_agent("multi_observer_ismcts_smoke_v1", seat=seat)
    first = agent.explain(mid_position.observation)
    second = agent.explain(mid_position.observation)
    assert first.to_data() == second.to_data()
    assert first.selected_action in mid_position.observation.legal_actions
    assert first.simulations_completed == 2
    assert first.root_sampled_world_count == 2
    assert first.fallback_rollout_count == 0


def test_larger_budget_enters_non_root_tree_and_redeterminizes(mid_position):
    observation = mid_position.observation
    configuration = MultiObserverConfiguration.build(simulation_budget=16)
    decision = decide(
        observation,
        configuration=configuration,
        decision_seed="phase5e-high-budget",
    )
    assert decision.selected_action in observation.legal_actions
    assert decision.observer_redeterminization_count > 0
    assert sum(decision.per_seat_information_node_count) > 1
    assert sum(decision.redeterminizations_by_seat) == decision.observer_redeterminization_count
    assert decision.fallback_rollout_count == 0


def test_fallback_policies_receive_only_formal_parent_observations(mid_position, monkeypatch):
    original = multi_module.construct_agent
    calls: list[tuple[int, object]] = []

    def recording(specification, *, seat, **kwargs):
        delegate = original(specification, seat=seat, **kwargs)

        class RecordingAgent:
            identity = delegate.identity

            def choose_action(self, observation):
                calls.append((seat, observation))
                return delegate.choose_action(observation)

        return RecordingAgent()

    monkeypatch.setattr(multi_module, "construct_agent", recording)
    observation = mid_position.observation
    decide(
        observation,
        configuration=MultiObserverConfiguration.build(
            simulation_budget=2, max_tree_depth=1
        ),
        decision_seed="phase5e-fallback-test",
    )
    root = observation.observing_seat
    assert calls
    assert {seat for seat, _ in calls}.issubset(set(range(4)))
    assert all(isinstance(item, PlayerObservation) for _, item in calls)
    assert all(not isinstance(item, DealState) for _, item in calls)
    assert all(item.observing_seat == seat for seat, item in calls)
    assert all(seat != root or item.observing_seat == root for seat, item in calls)


def test_observer_redeterminization_ignores_parent_references(mid_position):
    observation = mid_position.observation
    alternate = replace(
        observation,
        match_ref="alternate-match",
        deal_ref="alternate-match/deal:0",
    )
    root_key = root_information_state_key(observation)
    kwargs = {
        "root_information_state_id": root_key,
        "decision_seed": "phase5e-seed",
        "simulation_index": 3,
        "observer_decision_index": 1,
    }
    first = redeterminize_observer(observation, **kwargs)
    second = redeterminize_observer(alternate, **kwargs)
    assert first.content_key() == second.content_key()


def test_root_sampler_prefix_is_budget_stable(mid_position):
    observation = mid_position.observation
    root_key = root_information_state_key(observation)
    decision_seed = "phase5e-prefix-seed"
    model = HardConstraintModel.build(observation)
    seed = _root_sampling_seed(
        root_information_state_id=root_key, decision_seed=decision_seed
    )
    short = UniformFeasibleSampler.build(model, seed=seed).sample(8)
    long = UniformFeasibleSampler.build(model, seed=seed).sample(32)
    assert [item.content_key() for item in short] == [
        item.content_key() for item in long[:8]
    ]


def test_observer_local_state_preserves_acting_hand(mid_position):
    observation = mid_position.observation
    model = HardConstraintModel.build(observation)
    assignment = UniformFeasibleSampler.build(model, seed="phase5e-local").sample_one()
    state = FastTrickState.from_observation_assignment(observation, assignment)
    actor_observation = state.observation_for(observation.observing_seat)
    local_assignment = redeterminize_observer(
        actor_observation,
        root_information_state_id=root_information_state_key(observation),
        decision_seed="phase5e-local-seed",
        simulation_index=0,
        observer_decision_index=0,
    )
    local_state = FastTrickState.from_observation_assignment(
        actor_observation, local_assignment
    )
    assert local_state.hands[observation.observing_seat] == state.hands[
        observation.observing_seat
    ]
    assert multi_observer_information_state_key(actor_observation) == (
        multi_observer_information_state_key(local_state.observation_for(observation.observing_seat))
    )


def test_same_observation_merges_nodes_and_different_public_state_does_not(
    mid_position, late_position
):
    first = mid_position.observation
    alternate = replace(first, match_ref="alternate", deal_ref="alternate/deal:0")
    tree = MultiObserverTree()
    first_node, first_created = tree.node_for(first, first.observing_seat)
    second_node, second_created = tree.node_for(alternate, alternate.observing_seat)
    assert first_created is True
    assert second_created is False
    assert first_node is second_node
    assert all(value.availability == 2 for value in first_node.actions.values())
    different_node, different_created = tree.node_for(
        late_position.observation, late_position.observation.observing_seat
    )
    assert different_created is True
    assert different_node is not first_node


def test_diagnostics_are_privacy_safe(mid_position):
    observation = mid_position.observation
    decision = build_agent(
        "multi_observer_ismcts_smoke_v1", seat=observation.observing_seat
    ).explain(observation)
    payload = decision.to_data()
    require_privacy_safe(payload)
    serialized = json.dumps(payload, sort_keys=True)
    visible = observation_visible_card_codes(observation)
    for card in FULL_DECK:
        if card.to_code() not in visible:
            assert f'"{card.to_code()}"' not in serialized
    assert not any(key in serialized for key in FORBIDDEN_KEYS)
    assert "hidden_hands" not in serialized


def test_configuration_rejects_exact_tail_and_wrong_redeterminization():
    with pytest.raises(SearchConfigurationError):
        MultiObserverConfiguration.build(simulation_budget=2, fallback_policy_key="public_counting_v1")


def test_independent_tiny_multi_observer_counterexample():
    reference = TinyMultiObserverReference.structural_counterexample()
    assert reference.pimc_best_action() == "A"
    assert reference.root_only_prefix(1)["action"] == "A"
    assert reference.exact_best_action() == "B"
    assert reference.multi_observer_prefix(4)["action"] == "B"
