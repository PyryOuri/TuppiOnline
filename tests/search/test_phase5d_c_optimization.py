"""Phase 5D-C differential checks for the search-local trick-play path."""

from __future__ import annotations

import gc
import tracemalloc

from tuppi_agents import construct_agent, phase4_specifications_by_profile_key
from tuppi_engine import EnginePhase, apply_action, observation_for
from tuppi_engine.serialization import observation_to_data
from tuppi_exact import HardConstraintModel, UniformFeasibleSampler, hypothetical_continuation
from tuppi_rules import Contract

from tuppi_search import root_info_uct as uct
from tuppi_search.fast_trick import FastTrickState
from tuppi_search.root_info_uct_registry import (
    ROOT_INFO_UCT_PROFILE_KEYS,
    build_agent,
)


def _without_refs(observation):
    value = observation_to_data(observation)
    value.pop("match_ref")
    value.pop("deal_ref")
    return value


def _nolo_observations(showing_position):
    state = showing_position.deal_state
    while state.phase is EnginePhase.SHOWING:
        observation = observation_for(state, state.current_actor)
        state = apply_action(
            state,
            next(
                action
                for action in observation.legal_actions
                if action.declared_contract is Contract.NOLO
            ),
        )
    reference = phase4_specifications_by_profile_key()["partner_aware_v1"]
    found = {}
    while not state.complete:
        actor = state.current_actor
        observation = observation_for(state, actor)
        tricks = len(state.completed_tricks)
        if state.phase is EnginePhase.TRICK_PLAY and len(observation.legal_actions) >= 2:
            found.setdefault(tricks, observation)
        state = apply_action(
            state,
            construct_agent(reference, seat=actor).choose_action(observation),
        )
    return found


def _sampler_for(observation, agent):
    model = HardConstraintModel.build(observation)
    seed = uct._world_sampling_seed(
        root_information_state_id=uct.root_information_state_key(observation),
        decision_seed=agent.decision_seed(observation),
    )
    return UniformFeasibleSampler.build(model, seed=seed)


def test_fast_projection_matches_authoritative_projection(mid_position, late_position):
    for position in (mid_position, late_position):
        agent = build_agent(
            "root_info_uct_smoke_v1",
            seat=position.observation.observing_seat,
        )
        for assignment in _sampler_for(position.observation, agent).sample(2):
            authoritative = hypothetical_continuation(position.observation, assignment).state
            fast = FastTrickState.from_observation_assignment(
                position.observation, assignment
            )
            for seat in range(4):
                assert _without_refs(fast.observation_for(seat)) == _without_refs(
                    observation_for(authoritative, seat)
                )


def test_fast_transitions_match_authoritative_engine(mid_position, showing_position):
    nolo = _nolo_observations(showing_position)[0]
    reference = phase4_specifications_by_profile_key()["partner_aware_v1"]
    for observation in (mid_position.observation, nolo):
        agent = build_agent("root_info_uct_smoke_v1", seat=observation.observing_seat)
        for assignment in _sampler_for(observation, agent).sample(2):
            authoritative = hypothetical_continuation(observation, assignment).state
            fast = FastTrickState.from_observation_assignment(observation, assignment)
            while not authoritative.complete:
                actor = authoritative.current_actor
                expected = observation_for(authoritative, actor)
                action = construct_agent(reference, seat=actor).choose_action(expected)
                authoritative = apply_action(authoritative, action)
                fast = fast.apply(action)
                assert _without_refs(fast.observation_for(actor)) == _without_refs(
                    observation_for(authoritative, actor)
                )
                assert fast.hands == authoritative.hands
                assert fast.current_actor == authoritative.current_actor
                assert fast.current_trick == authoritative.current_trick
                assert fast.completed_tricks == authoritative.completed_tricks
                assert fast.team_tricks == authoritative.team_tricks
                assert fast.phase == authoritative.phase
                assert fast.deal_score == authoritative.deal_score
                assert fast.ending_score == authoritative.ending_score


def test_registered_decisions_match_authoritative_reference(
    mid_position, late_position, showing_position
):
    nolo = _nolo_observations(showing_position)[4]
    for observation in (mid_position.observation, late_position.observation, nolo):
        for profile_key in ROOT_INFO_UCT_PROFILE_KEYS:
            agent = build_agent(profile_key, seat=observation.observing_seat)
            fast = agent.explain(observation)
            slow = uct.decide(
                observation,
                configuration=agent.configuration,
                decision_seed=agent.decision_seed(observation),
                _fast_path=False,
            )
            assert fast.to_data() == slow.to_data()


def test_repeated_decisions_do_not_retain_unbounded_search_state(mid_position):
    agent = build_agent(
        "root_info_uct_smoke_v1", seat=mid_position.observation.observing_seat
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
