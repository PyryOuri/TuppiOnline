from __future__ import annotations

import math

import pytest

from tuppi_agents import construct_agent, phase4_specifications_by_profile_key
from tuppi_belief import (
    BehavioralBeliefConfiguration,
    CausalPublicHistory,
    DeterministicPolicyLikelihoodModel,
    EpsilonSmoothedPolicyModel,
    MixtureBehaviorModel,
    UniformLegalActionModel,
    build_belief,
)
from tuppi_belief.exact_reference import (
    enumerate_feasible_assignments,
    exact_behavioral_posterior,
)
from tuppi_belief.metrics import owner_metrics
from tuppi_belief.reconstruction import replay_candidate
from tuppi_belief.resampling import systematic_resample
from tuppi_belief.synthetic import generate_synthetic_positions
from tuppi_engine import (
    EnginePhase,
    ExplicitDeal,
    apply_match_action,
    begin_explicit_deal,
    create_match,
    match_observation_for,
)
from tuppi_match.streams import MatchStream
from tuppi_rules import MatchScore


def _position(steps: int, profile_key: str = "partner_aware_v1"):
    stream = MatchStream.build(
        root_seed="phase5g-b-tests", stream_index=0, initial_dealer=0
    )
    deal = stream.deal(0)
    state = create_match(
        initial_score=MatchScore(),
        initial_dealer=0,
        match_ref=f"belief-test-{steps}",
    )
    state = begin_explicit_deal(state, ExplicitDeal(dealer=0, hands=deal.hands))
    spec = phase4_specifications_by_profile_key()[profile_key]
    agents = tuple(construct_agent(spec, seat=seat) for seat in range(4))
    for _ in range(steps):
        actor = state.current_actor
        assert actor is not None
        observation = match_observation_for(state, actor)
        state = apply_match_action(state, agents[actor].choose_action(observation))
    actor = state.current_actor
    assert actor is not None and state.active_deal is not None
    return match_observation_for(state, actor), state.active_deal


def test_history_is_exactly_the_causal_prefix() -> None:
    observation, _state = _position(steps=10)
    history = CausalPublicHistory.from_observation(observation)
    assert len(history.actions) == 10
    assert [item.sequence for item in history.actions] == list(range(10))
    assert observation.current_actor == observation.observing_seat


def test_action_models_are_observation_only_and_normalized() -> None:
    observation, _state = _position(steps=0)
    uniform = UniformLegalActionModel().probabilities(observation)
    assert set(uniform) == set(observation.legal_actions)
    assert math.isclose(sum(uniform.values()), 1.0)
    smoothed = EpsilonSmoothedPolicyModel("partner_aware_v1", epsilon=0.1)
    values = smoothed.probabilities(observation)
    assert math.isclose(sum(values.values()), 1.0)
    selected = construct_agent(
        phase4_specifications_by_profile_key()["partner_aware_v1"],
        seat=observation.observing_seat,
    ).choose_action(observation)
    assert values[selected] > min(values.values())
    deterministic = DeterministicPolicyLikelihoodModel("partner_aware_v1")
    assert deterministic.probability(observation, selected) == 1.0


def test_mixture_is_explicit_and_normalized() -> None:
    observation, _state = _position(steps=0)
    components = (
        EpsilonSmoothedPolicyModel("reactive_contract_v1"),
        EpsilonSmoothedPolicyModel("public_counting_v1"),
        EpsilonSmoothedPolicyModel("partner_aware_v1"),
    )
    mixture = MixtureBehaviorModel(components=components, weights=(1 / 3,) * 3)
    probabilities = mixture.probabilities(observation)
    assert math.isclose(sum(probabilities.values()), 1.0)
    assert mixture.identity_data()["weights"] == [1 / 3, 1 / 3, 1 / 3]


def test_sample_prefix_and_weights_are_deterministic() -> None:
    observation, _state = _position(steps=10)
    model = EpsilonSmoothedPolicyModel("partner_aware_v1")
    short = build_belief(
        observation,
        model,
        configuration=BehavioralBeliefConfiguration(candidate_count=4, seed="prefix"),
    )
    long = build_belief(
        observation,
        model,
        configuration=BehavioralBeliefConfiguration(candidate_count=8, seed="prefix"),
    )
    assert short.candidate_ids == long.candidate_ids[:4]
    assert short.log_weights == long.log_weights[:4]
    assert short.to_data() == short.to_data()
    assert "assignments" not in short.to_data()


def test_observer_own_prior_actions_add_only_a_candidate_constant() -> None:
    observation, _state = _position(steps=10)
    model = EpsilonSmoothedPolicyModel("partner_aware_v1")
    default = build_belief(
        observation,
        model,
        configuration=BehavioralBeliefConfiguration(candidate_count=4, seed="own-actions"),
    )
    all_seats = build_belief(
        observation,
        model,
        configuration=BehavioralBeliefConfiguration(
            candidate_count=4,
            seed="own-actions",
            actor_seats=(0, 1, 2, 3),
        ),
    )
    differences = tuple(
        left - right for left, right in zip(all_seats.log_weights, default.log_weights, strict=True)
    )
    assert max(differences) - min(differences) < 1e-12


def test_candidate_replay_preserves_public_state_and_card_conservation() -> None:
    observation, _state = _position(steps=10)
    from tuppi_exact.sampling import UniformFeasibleSampler
    from tuppi_exact.constraints import HardConstraintModel

    sampler = UniformFeasibleSampler.build(
        HardConstraintModel.build(observation), seed="replay"
    )
    replay = replay_candidate(observation, sampler.sample_one(index=0))
    played_cards = sum(
        len(trick.plays) for trick in replay.current_state.completed_tricks
    ) + len(replay.current_state.current_trick)
    assert sum(len(hand) for hand in replay.current_state.hands) + played_cards == 52
    assert all(0 <= len(hand) <= 13 for hand in replay.current_state.hands)
    assert len(replay.observations_before_actions()) == 10


def test_tiny_exact_reference_is_independent_and_matches_count() -> None:
    observation = None
    exact_assignments = ()
    for steps in range(35, 50):
        candidate, _state = _position(steps=steps)
        possible = enumerate_feasible_assignments(candidate)
        if 1 < len(possible) < 100:
            observation = candidate
            exact_assignments = possible
            break
    assert observation is not None
    assert 1 < len(exact_assignments) < 100
    reference = exact_behavioral_posterior(
        observation, EpsilonSmoothedPolicyModel("partner_aware_v1")
    )
    assert reference.feasible_world_count == len(exact_assignments)
    assert math.isclose(sum(reference.normalized_weights), 1.0)


def test_resampling_is_deterministic_and_preserves_multiplicity() -> None:
    first = systematic_resample((0.1, 0.2, 0.7), count=32, seed="resample")
    second = systematic_resample((0.1, 0.2, 0.7), count=32, seed="resample")
    assert first == second
    assert len(first.source_indices) == 32
    assert sum(first.multiplicities) == 32
    assert first.unique_count <= 3


def test_owner_metrics_are_offline_only() -> None:
    observation, state = _position(steps=10)
    belief = build_belief(
        observation,
        EpsilonSmoothedPolicyModel("partner_aware_v1"),
        configuration=BehavioralBeliefConfiguration(candidate_count=4, seed="metrics"),
    )
    metrics = owner_metrics(belief, tuple(state.hands))
    assert metrics.card_count > 0
    assert metrics.nll >= 0.0
    assert metrics.brier >= 0.0


def test_synthetic_public_input_does_not_expose_labels() -> None:
    positions = generate_synthetic_positions(
        profile_key="reactive_contract_v1",
        root_seed="phase5g-b-synthetic-tests",
        stream_index=0,
        deal_indices=(0,),
        split="test",
    )
    assert positions
    public = positions[0].to_public_data()
    assert "true_current_hands" not in public
    assert "generating_profile_key" not in public
    assert positions[0].public_input() == positions[0].observation
