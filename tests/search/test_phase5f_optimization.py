"""Semantic-preservation checks for the Phase 5F execution optimizations."""

from __future__ import annotations

import gc
import tracemalloc

from tuppi_engine import EnginePhase
from tuppi_exact import HardConstraintModel, UniformFeasibleSampler
from tuppi_exact.sampling import DeterministicBitSource
from tuppi_search import multi_observer as multi_module
from tuppi_search.multi_observer import MultiObserverTree, multi_observer_information_state_key
from tuppi_search.multi_observer_registry import build_agent


def test_indexed_sampler_matches_the_pre_5f_sequential_reference(
    mid_position, late_position
):
    """Skipping prior draws preserves the historical indexed stream exactly."""

    for position in (mid_position, late_position):
        model = HardConstraintModel.build(position.observation)
        sampler = UniformFeasibleSampler.build(model, seed="phase5f-indexed")
        source = DeterministicBitSource(sampler._stream_seed())
        reference = [sampler._draw(source, index).content_key() for index in range(12)]
        actual = [sampler.sample_one(index=index).content_key() for index in range(12)]
        assert actual == reference


def test_cached_sampler_context_preserves_prefix_and_counts(mid_position):
    model = HardConstraintModel.build(mid_position.observation)
    sampler = UniformFeasibleSampler.build(model, seed="phase5f-context")
    short = sampler.sample(8)
    long = sampler.sample(32)
    assert [item.content_key() for item in short] == [
        item.content_key() for item in long[:8]
    ]
    assert sampler.total_assignments > 0
    assert sampler._completions(0, sampler.plan.capacities) == sampler.total_assignments


def test_optimized_multi_observer_decision_matches_sequential_sampler(
    mid_position, monkeypatch
):
    seat = mid_position.observation.observing_seat
    optimized = build_agent("multi_observer_ismcts_standard_v1", seat=seat).explain(
        mid_position.observation
    )
    original = multi_module.UniformFeasibleSampler.sample_one

    def legacy(self, *, index=0):
        return self.sample(index + 1)[index]

    monkeypatch.setattr(multi_module.UniformFeasibleSampler, "sample_one", legacy)
    sequential = build_agent("multi_observer_ismcts_standard_v1", seat=seat).explain(
        mid_position.observation
    )
    monkeypatch.setattr(multi_module.UniformFeasibleSampler, "sample_one", original)
    assert optimized.to_data() == sequential.to_data()


def test_precomputed_observer_key_node_lookup_matches_digest_lookup(mid_position):
    observation = mid_position.observation
    key = multi_observer_information_state_key(observation)
    tree = MultiObserverTree()
    first, created = tree.node_for(observation, observation.observing_seat)
    second, reused = tree.node_for_key(
        key=key, observation=observation, seat=observation.observing_seat
    )
    assert created is True
    assert reused is False
    assert first is second


def test_optimization_corpus_fixture_is_trick_play_only(mid_position):
    assert mid_position.observation.phase is EnginePhase.TRICK_PLAY
    assert mid_position.observation.current_actor == mid_position.observation.observing_seat


def test_repeated_multi_observer_decisions_do_not_retain_trees(mid_position):
    agent = build_agent(
        "multi_observer_ismcts_smoke_v1",
        seat=mid_position.observation.observing_seat,
    )
    gc.collect()
    tracemalloc.start()
    for _ in range(4):
        agent.choose_action(mid_position.observation)
    first_current, first_peak = tracemalloc.get_traced_memory()
    for _ in range(4):
        agent.choose_action(mid_position.observation)
    second_current, second_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert second_peak < first_peak * 2 + 2_000_000
    assert second_current < first_current * 2 + 2_000_000
