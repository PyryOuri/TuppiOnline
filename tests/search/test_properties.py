"""Property-based tests over deterministic deck permutations.

PIMC is expensive, so these use small budgets and few examples - the goal is to
explore *structural* variety (different hands, seats, phases, scores) rather than to
accumulate many samples of one position.
"""

from __future__ import annotations

from hypothesis import HealthCheck, given, settings, strategies as st

from tuppi_agents import construct_agent, phase4_specifications_by_profile_key
from tuppi_engine import (
    EnginePhase,
    ExplicitDeal,
    PlayCardAction,
    ShowAction,
    apply_action,
    begin_explicit_deal,
    create_match,
    observation_for,
)
from tuppi_exact import HardConstraintModel
from tuppi_rules import DECK_SIZE, FULL_DECK, MatchScore, TRICKS_PER_DEAL

from tuppi_search.config import PimcConfiguration
from tuppi_search.pimc import decide
from tuppi_search.random import information_state_digest
from tuppi_search.utilities import UtilityId, utility_value
from tuppi_search.worlds import build_world_set
from tuppi_search.random import SearchSeedHierarchy


PROPERTY_SETTINGS = settings(
    max_examples=4,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)

CONFIG = PimcConfiguration.build(world_count=2)
REFERENCE = phase4_specifications_by_profile_key()["partner_aware_v1"]


def _deal_from_permutation(order: list[int]) -> tuple:
    cards = [FULL_DECK[index] for index in order]
    return tuple(tuple(cards[seat * 13 : (seat + 1) * 13]) for seat in range(4))


@st.composite
def _positions(draw):
    """Draw a deck permutation, a score, and a number of actions to advance."""

    order = draw(st.permutations(range(DECK_SIZE)))
    advance = draw(st.integers(min_value=0, max_value=30))
    score = draw(
        st.sampled_from([(0, 0), (16, 0), (0, 16), (48, 0), (0, 48)])
    )
    hands = _deal_from_permutation(list(order))
    state = create_match(
        initial_score=MatchScore(*score), initial_dealer=0, match_ref="prop-0"
    )
    state = begin_explicit_deal(state, ExplicitDeal(dealer=0, hands=hands))
    deal = state.active_deal
    for _ in range(advance):
        if deal.complete:
            break
        actor = deal.current_actor
        deal = apply_action(
            deal,
            construct_agent(REFERENCE, seat=actor).choose_action(
                observation_for(deal, actor)
            ),
        )
    return deal


@given(_positions())
@PROPERTY_SETTINGS
def test_the_selected_action_is_always_legal(deal):
    if deal.complete:
        return
    observation = observation_for(deal, deal.current_actor)
    decision = decide(observation, configuration=CONFIG, decision_seed="prop")
    assert decision.selected_action in observation.legal_actions
    if observation.phase is EnginePhase.SHOWING:
        assert isinstance(decision.selected_action, ShowAction)
    else:
        assert isinstance(decision.selected_action, PlayCardAction)


@given(_positions())
@PROPERTY_SETTINGS
def test_the_same_input_and_seed_produce_the_same_action(deal):
    if deal.complete:
        return
    observation = observation_for(deal, deal.current_actor)
    first = decide(observation, configuration=CONFIG, decision_seed="prop")
    again = decide(observation, configuration=CONFIG, decision_seed="prop")
    assert first.selected_action == again.selected_action
    assert [item.mean_utility for item in first.candidates] == [
        item.mean_utility for item in again.candidates
    ]


@given(_positions())
@PROPERTY_SETTINGS
def test_all_candidates_receive_the_same_requested_world_count(deal):
    if deal.complete:
        return
    observation = observation_for(deal, deal.current_actor)
    decision = decide(observation, configuration=CONFIG, decision_seed="prop")
    if decision.single_legal_action_shortcut:
        return
    counts = {item.evaluations for item in decision.candidates}
    assert len(counts) == 1
    assert counts.pop() == CONFIG.world_count * CONFIG.rollout_replicas


@given(_positions())
@PROPERTY_SETTINGS
def test_every_sampled_world_satisfies_the_hard_constraints(deal):
    if deal.complete:
        return
    observation = observation_for(deal, deal.current_actor)
    model = HardConstraintModel.build(observation)
    world_set = build_world_set(
        observation,
        configuration=CONFIG,
        seeds=SearchSeedHierarchy(
            pimc_protocol=CONFIG.pimc_protocol_version,
            information_state=information_state_digest(observation),
            decision_seed="prop",
        ),
    )
    for world in world_set.worlds:
        state = world.state
        assert tuple(state.hands[model.observing_seat]) == tuple(observation.own_hand)
        flat = [card for hand in state.hands for card in hand]
        played = sum(
            len(trick.plays) for trick in state.completed_tricks
        ) + len(state.current_trick)
        assert len(flat) + played == DECK_SIZE
        assert len(set(flat)) == len(flat)


@given(_positions())
@PROPERTY_SETTINGS
def test_every_completed_rollout_conserves_cards_and_plays_thirteen_tricks(deal):
    if deal.complete or deal.phase is not EnginePhase.TRICK_PLAY:
        return
    observation = observation_for(deal, deal.current_actor)
    decision = decide(observation, configuration=CONFIG, decision_seed="prop")
    if decision.single_legal_action_shortcut:
        return
    already = sum(
        len(trick.plays) for trick in deal.completed_tricks
    ) + len(deal.current_trick)
    for candidate in decision.candidates:
        per_rollout = candidate.actions_simulated / candidate.evaluations
        assert per_rollout == DECK_SIZE - already


@given(_positions())
@PROPERTY_SETTINGS
def test_candidate_values_stay_inside_the_utility_range(deal):
    if deal.complete:
        return
    observation = observation_for(deal, deal.current_actor)
    decision = decide(observation, configuration=CONFIG, decision_seed="prop")
    low, high = -1.0, 1.0
    for candidate in decision.candidates:
        assert low <= candidate.minimum <= candidate.mean_utility <= candidate.maximum
        assert candidate.maximum <= high
        assert candidate.standard_deviation >= 0.0


@given(_positions())
@PROPERTY_SETTINGS
def test_a_hidden_state_permutation_preserving_the_observation_changes_nothing(deal):
    """Re-deal the hidden cards, keep the observation, and expect the same action."""

    if deal.complete or deal.phase is not EnginePhase.TRICK_PLAY:
        return
    from tuppi_exact import UniformFeasibleSampler
    from tuppi_exact.continuation import reconstruct_initial_hands
    from tuppi_engine import ShowAction as EngineShowAction, create_deal_state

    observation = observation_for(deal, deal.current_actor)
    model = HardConstraintModel.build(observation)
    if not model.unknown_cards:
        return
    baseline = decide(observation, configuration=CONFIG, decision_seed="prop")
    sampler = UniformFeasibleSampler.build(model, seed="permutation")
    deal_number = int(observation.deal_ref.rsplit(":", 1)[1])
    for assignment in sampler.sample(2):
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
        alternative = observation_for(state, state.current_actor)
        decision = decide(alternative, configuration=CONFIG, decision_seed="prop")
        assert decision.selected_action == baseline.selected_action


@given(
    st.permutations(range(DECK_SIZE)),
    st.integers(min_value=0, max_value=TRICKS_PER_DEAL),
    st.sampled_from([(0, 0), (48, 0), (0, 48)]),
)
@settings(max_examples=8, deadline=None)
def test_utility_orientation_is_antisymmetric_between_teams(order, split, score):
    """For any split, one team's deal value is the exact negation of the other's."""

    from tuppi_rules import Contract, team_for_seat

    from tuppi_search.utilities import DealOutcomeSummary, OutcomeSource

    del order
    for contract, declarer in ((Contract.NOLO, None), (Contract.RAMI, 0)):
        values = []
        for seat in (0, 1):
            values.append(
                utility_value(
                    UtilityId.DEAL_RESULT_V1,
                    DealOutcomeSummary(
                        contract=contract,
                        declarer=declarer,
                        team0_tricks=split,
                        starting_score=MatchScore(*score),
                        root_team=team_for_seat(seat),
                        source=OutcomeSource.ROLLOUT,
                        tricks_simulated=TRICKS_PER_DEAL,
                    ),
                )
            )
        assert values[0] == -values[1]
