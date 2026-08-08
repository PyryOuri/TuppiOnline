"""Phase 5D-B root-information UCT correctness and privacy tests."""

from __future__ import annotations

from dataclasses import replace
import json

import pytest

from tuppi_agents import construct_agent, phase4_specifications_by_profile_key
from tuppi_engine import DealState, PlayerObservation, observation_for
from tuppi_exact import HardConstraintModel, UniformFeasibleSampler, hypothetical_continuation
from tuppi_rules import FULL_DECK

from tuppi_search.diagnostics import FORBIDDEN_KEYS, observation_visible_card_codes, require_privacy_safe
from tuppi_search.errors import RootInfoUctDecisionError
from tuppi_search.information_state import root_information_state_key
from tuppi_search.root_info_uct import RootInfoUctTree
import tuppi_search.root_info_uct as uct_module
from tuppi_search.root_info_uct_registry import (
    ROOT_INFO_UCT_PROFILE_KEYS,
    build_agent,
    configuration_for,
    registry_snapshot,
)
from tuppi_search.tiny_information_reference import TinyInformationSetReference


def test_root_information_key_excludes_match_and_deal_references(mid_position):
    original = mid_position.observation
    alternate = replace(
        original,
        match_ref="alternate-match",
        deal_ref="alternate-match/deal:0",
    )
    assert root_information_state_key(original) == root_information_state_key(alternate)


def test_two_sampled_full_states_share_one_tree_node(mid_position):
    observation = mid_position.observation
    model = HardConstraintModel.build(observation)
    sampler = UniformFeasibleSampler.build(model, seed="phase5d-b-node-merge")
    first, second = sampler.sample(2)
    first_observation = observation_for(
        hypothetical_continuation(observation, first).state,
        observation.observing_seat,
    )
    second_observation = observation_for(
        hypothetical_continuation(observation, second).state,
        observation.observing_seat,
    )
    assert root_information_state_key(first_observation) == root_information_state_key(
        second_observation
    )
    tree = RootInfoUctTree()
    first_node = tree.node_for(first_observation)
    second_node = tree.node_for(second_observation)
    assert first_node is second_node
    first_node.visits = 1
    tree.node_for(second_observation)
    assert tree.node_revisit_count == 1


def test_publicly_different_information_states_do_not_merge(mid_position, late_position):
    assert root_information_state_key(mid_position.observation) != root_information_state_key(
        late_position.observation
    )


def test_showing_delegates_byte_for_byte_and_does_not_sample(showing_position, monkeypatch):
    specification = phase4_specifications_by_profile_key()["partner_aware_v1"]
    seat = showing_position.observation.observing_seat
    expected = construct_agent(specification, seat=seat).choose_action(
        showing_position.observation
    )

    def forbidden_sampler(*args, **kwargs):
        raise AssertionError("showing must not construct a hidden-world sampler")

    monkeypatch.setattr(uct_module.UniformFeasibleSampler, "build", forbidden_sampler)
    got = build_agent("root_info_uct_smoke_v1", seat=seat).explain(
        showing_position.observation
    )
    assert got.selected_action == expected
    assert got.showing_delegated is True
    assert got.simulations_completed == 0


def test_root_search_is_deterministic_and_future_root_turns_share_tree(mid_position):
    seat = mid_position.observation.observing_seat
    agent = build_agent("root_info_uct_smoke_v1", seat=seat)
    first = agent.explain(mid_position.observation)
    second = agent.explain(mid_position.observation)
    assert first.to_data() == second.to_data()
    assert first.selected_action in mid_position.observation.legal_actions
    assert first.maximum_tree_depth >= 2
    assert first.root_information_set_nodes >= 2
    assert first.cross_world_node_merge_count >= 0


def test_non_root_rollouts_receive_only_their_own_observations(mid_position, monkeypatch):
    original_construct = uct_module.construct_agent
    calls: list[tuple[int, object]] = []

    def recording_construct(specification, *, seat, **kwargs):
        delegate = original_construct(specification, seat=seat, **kwargs)

        class RecordingAgent:
            identity = delegate.identity

            def choose_action(self, observation):
                calls.append((seat, observation))
                return delegate.choose_action(observation)

        return RecordingAgent()

    monkeypatch.setattr(uct_module, "construct_agent", recording_construct)
    root_seat = mid_position.observation.observing_seat
    build_agent("root_info_uct_smoke_v1", seat=root_seat).choose_action(
        mid_position.observation
    )
    assert calls
    assert {seat for seat, _ in calls}.isdisjoint({root_seat})
    assert all(isinstance(observation, PlayerObservation) for _, observation in calls)
    assert all(not isinstance(observation, DealState) for _, observation in calls)


def test_diagnostics_are_privacy_safe_and_do_not_name_sampled_cards(mid_position):
    decision = build_agent(
        "root_info_uct_smoke_v1", seat=mid_position.observation.observing_seat
    ).explain(mid_position.observation)
    payload = decision.to_data()
    require_privacy_safe(payload)
    serialized = json.dumps(payload, sort_keys=True)
    visible = observation_visible_card_codes(mid_position.observation)
    for card in FULL_DECK:
        code = card.to_code()
        if code not in visible:
            assert f'"{code}"' not in serialized
    assert not any(key in serialized for key in FORBIDDEN_KEYS)
    assert "hidden_hands" not in serialized


def test_nested_sampler_prefixes_are_identical(mid_position):
    agent = build_agent("root_info_uct_smoke_v1", seat=mid_position.observation.observing_seat)
    key = root_information_state_key(mid_position.observation)
    seed = uct_module._world_sampling_seed(
        root_information_state_id=key,
        decision_seed=agent.decision_seed(mid_position.observation),
    )
    model = HardConstraintModel.build(mid_position.observation)
    short = UniformFeasibleSampler.build(model, seed=seed).sample(2)
    long = UniformFeasibleSampler.build(model, seed=seed).sample(8)
    assert tuple(item.content_key() for item in short) == tuple(
        item.content_key() for item in long[:2]
    )


def test_illegal_non_root_rollout_is_a_fatal_classified_failure(mid_position, monkeypatch):
    class BrokenAgent:
        identity = "broken-rollout"

        def choose_action(self, observation):
            return None

    monkeypatch.setattr(uct_module, "construct_agent", lambda specification, *, seat: BrokenAgent())
    with pytest.raises(RootInfoUctDecisionError) as caught:
        build_agent(
            "root_info_uct_smoke_v1", seat=mid_position.observation.observing_seat
        ).choose_action(mid_position.observation)
    assert caught.value.failure_kind == "rollout_illegal_action"


def test_registered_budgets_and_ids_are_distinct():
    snapshot = registry_snapshot()
    assert tuple(sorted(ROOT_INFO_UCT_PROFILE_KEYS)) == (
        "root_info_uct_small_v1",
        "root_info_uct_smoke_v1",
        "root_info_uct_standard_v1",
    )
    assert len({entry["agent_id"] for entry in snapshot["agents"]}) == 3
    assert len({configuration_for(key).configuration_id for key in ROOT_INFO_UCT_PROFILE_KEYS}) == 3
    assert all(configuration_for(key).exact_tail_enabled is False for key in ROOT_INFO_UCT_PROFILE_KEYS)


def test_tiny_exact_reference_exposes_the_strategy_fusion_counterexample():
    reference = TinyInformationSetReference.strategy_fusion_counterexample()
    assert reference.pimc_best_action() == "A"
    assert reference.exact_best_action() == "B"
    assert reference.pimc_values()["A"] == 1.0
    assert reference.exact_information_set_values()["A"] == 0.5
    assert reference.uct_prefix(16)["action"] == "B"
    assert reference.uct_prefix(64)["action"] == "B"
