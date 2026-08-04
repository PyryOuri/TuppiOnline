"""Information-set invariance: the real hidden deal must have no influence.

This is the sharpest security test in Phase 5C. Two *different* real deals are
constructed that present the acting seat with the **same observation**, and the
search is required to behave identically: same constraints, same sampled worlds,
same candidate values, same diagnostics, same selected action.

If the real hidden hands could influence anything, this test fails - and it would
fail whether the leak came from an obvious mistake or from something subtle like a
digest that accidentally included the deal identifier.

How the pairs are built
-----------------------

Cards are moved only *outside* the information set: the observing seat's own hand
is untouched, every public card stays where it was, and the observation's own
consistency checks confirm the two projections are equal field by field. The Phase
5B sampler is used to produce the alternative worlds, so the alternatives are
guaranteed to be legal reachable states rather than hand-built approximations.
"""

from __future__ import annotations

import pytest

from tuppi_engine import (
    EnginePhase,
    ExplicitDeal,
    PlayCardAction,
    ShowAction as EngineShowAction,
    apply_action,
    create_deal_state,
    observation_for,
)
from tuppi_exact import HardConstraintModel, UniformFeasibleSampler
from tuppi_exact.continuation import reconstruct_initial_hands

from tuppi_search.agents import UniformFeasiblePimcAgent
from tuppi_search.pimc import decide
from tuppi_search.random import information_state_digest
from tuppi_search.registry import PRIMARY_PROFILE_KEY, specification_for
from tuppi_search.worlds import build_world_set
from tuppi_search.random import SearchSeedHierarchy

from .conftest import advance_to


def _alternative_real_states(position, *, count: int = 3):
    """Return real states that differ from ``position`` outside its information set.

    Each is produced by sampling a feasible hidden-hand assignment and replaying the
    public history into a deal state that carries the **original public labels**.

    That last part matters. ``hypothetical_continuation`` deliberately re-labels its
    ``match_ref`` so a hypothetical can never be filed as a dealt deal, and
    ``match_ref``/``deal_ref`` are genuine public fields of the observation. Using a
    hypothetical directly would therefore vary something *inside* the information
    set and the test would be proving the wrong thing. These alternatives are real,
    legal, engine-validated deals that the observing seat cannot distinguish from
    the original in any respect at all.
    """

    observation = position.observation
    model = HardConstraintModel.build(observation)
    if not model.unknown_cards:
        pytest.skip("this position leaves nothing hidden to vary")
    sampler = UniformFeasibleSampler.build(model, seed="invariance-alternatives")
    deal_number = int(observation.deal_ref.rsplit(":", 1)[1])
    states = []
    seen = {tuple(tuple(hand) for hand in position.deal_state.hands)}
    for assignment in sampler.sample(count * 8):
        hands = reconstruct_initial_hands(observation, assignment)
        state = create_deal_state(
            ExplicitDeal(dealer=observation.dealer, hands=hands),
            starting_score=observation.match_score,
            match_ref=observation.match_ref,
            deal_ref=observation.deal_ref,
            deal_number=deal_number,
            event_start_index=0,
        )
        for action in observation.show_actions:
            state = apply_action(
                state,
                EngineShowAction(
                    seat=action.seat,
                    shown_card=action.shown_card,
                    declared_contract=action.declared_contract,
                ),
            )
        for trick in observation.completed_tricks:
            for play in trick.plays:
                state = apply_action(
                    state, PlayCardAction(seat=play.seat, card=play.card)
                )
        for play in observation.current_trick:
            state = apply_action(
                state, PlayCardAction(seat=play.seat, card=play.card)
            )
        key = tuple(tuple(hand) for hand in state.hands)
        if key in seen:
            continue
        seen.add(key)
        states.append(state)
        if len(states) >= count:
            break
    if not states:
        pytest.skip("no distinct alternative world was produced")
    return states


def _same_observation(left, right) -> bool:
    return (
        left.observing_seat == right.observing_seat
        and left.own_hand == right.own_hand
        and left.phase is right.phase
        and left.current_actor == right.current_actor
        and left.completed_tricks == right.completed_tricks
        and left.current_trick == right.current_trick
        and left.show_actions == right.show_actions
        and left.contract is right.contract
        and left.declarer == right.declarer
        and left.first_leader == right.first_leader
        and left.team_tricks == right.team_tricks
        and left.match_score == right.match_score
        and left.legal_actions == right.legal_actions
        and left.dealer == right.dealer
    )


def test_alternative_real_states_present_the_same_observation(mid_position):
    for state in _alternative_real_states(mid_position):
        actor = state.current_actor
        assert actor == mid_position.observation.observing_seat
        alternative = observation_for(state, actor)
        assert _same_observation(alternative, mid_position.observation)
        # Public labels match too, so nothing inside the information set varies.
        assert alternative.match_ref == mid_position.observation.match_ref
        assert alternative.deal_ref == mid_position.observation.deal_ref
        # The real states genuinely differ, or the test would prove nothing.
        assert state.hands != mid_position.deal_state.hands
        assert state.deal_id != mid_position.deal_state.deal_id


def test_the_information_state_digest_ignores_the_hidden_deal(mid_position):
    baseline = information_state_digest(mid_position.observation)
    for state in _alternative_real_states(mid_position):
        alternative = observation_for(state, state.current_actor)
        assert information_state_digest(alternative) == baseline


def test_constraints_and_worlds_are_identical(mid_position, smoke_config):
    baseline_observation = mid_position.observation
    seeds = SearchSeedHierarchy(
        pimc_protocol=smoke_config.pimc_protocol_version,
        information_state=information_state_digest(baseline_observation),
        decision_seed="invariance",
    )
    baseline_model = HardConstraintModel.build(baseline_observation)
    baseline_worlds = build_world_set(
        baseline_observation, configuration=smoke_config, seeds=seeds
    )
    for state in _alternative_real_states(mid_position):
        alternative = observation_for(state, state.current_actor)
        model = HardConstraintModel.build(alternative)
        assert model.identity_data() == baseline_model.identity_data()
        worlds = build_world_set(
            alternative,
            configuration=smoke_config,
            seeds=SearchSeedHierarchy(
                pimc_protocol=smoke_config.pimc_protocol_version,
                information_state=information_state_digest(alternative),
                decision_seed="invariance",
            ),
        )
        assert worlds.world_set_id == baseline_worlds.world_set_id
        assert [item.world_id for item in worlds.worlds] == [
            item.world_id for item in baseline_worlds.worlds
        ]


def test_candidate_values_and_selection_are_identical(mid_position, smoke_config):
    baseline = decide(
        mid_position.observation,
        configuration=smoke_config,
        decision_seed="invariance",
    )
    for state in _alternative_real_states(mid_position):
        alternative = observation_for(state, state.current_actor)
        decision = decide(
            alternative, configuration=smoke_config, decision_seed="invariance"
        )
        assert decision.selected_action == baseline.selected_action
        assert [item.to_data() for item in decision.candidates] == [
            item.to_data() for item in baseline.candidates
        ]
        assert decision.selection_gap == baseline.selection_gap


def test_diagnostics_are_identical(mid_position):
    """Semantic diagnostics must not vary with the real deal either."""

    specification = specification_for(PRIMARY_PROFILE_KEY)
    from tuppi_search.registry import configuration_for

    configuration = configuration_for(PRIMARY_PROFILE_KEY)
    seat = mid_position.observation.observing_seat
    agent = UniformFeasiblePimcAgent(
        agent_id=specification.agent_id,
        configuration=configuration,
        seat=seat,
        policy_seed="invariance",
    )
    baseline = agent.explain(mid_position.observation).to_data()
    for state in _alternative_real_states(mid_position, count=2):
        alternative = observation_for(state, state.current_actor)
        payload = agent.explain(alternative).to_data()
        assert payload == baseline


def test_the_agent_derives_the_same_decision_seed(mid_position):
    from tuppi_search.registry import configuration_for

    specification = specification_for(PRIMARY_PROFILE_KEY)
    seat = mid_position.observation.observing_seat
    agent = UniformFeasiblePimcAgent(
        agent_id=specification.agent_id,
        configuration=configuration_for(PRIMARY_PROFILE_KEY),
        seat=seat,
        policy_seed="invariance",
    )
    baseline = agent.decision_seed(mid_position.observation)
    for state in _alternative_real_states(mid_position, count=2):
        alternative = observation_for(state, state.current_actor)
        assert agent.decision_seed(alternative) == baseline


def test_invariance_also_holds_at_a_showing_root(showing_position, smoke_config):
    """Showing roots hide 39 cards, so the invariance surface is largest there."""

    baseline = decide(
        showing_position.observation,
        configuration=smoke_config,
        decision_seed="invariance-show",
    )
    for state in _alternative_real_states(showing_position, count=2):
        alternative = observation_for(state, state.current_actor)
        assert alternative.phase is EnginePhase.SHOWING
        decision = decide(
            alternative,
            configuration=smoke_config,
            decision_seed="invariance-show",
        )
        assert decision.selected_action == baseline.selected_action
        assert [item.mean_utility for item in decision.candidates] == [
            item.mean_utility for item in baseline.candidates
        ]


def test_invariance_holds_at_a_late_position(late_position, smoke_config):
    baseline = decide(
        late_position.observation,
        configuration=smoke_config,
        decision_seed="invariance-late",
    )
    for state in _alternative_real_states(late_position, count=2):
        alternative = observation_for(state, state.current_actor)
        decision = decide(
            alternative,
            configuration=smoke_config,
            decision_seed="invariance-late",
        )
        assert decision.selected_action == baseline.selected_action
