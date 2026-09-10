"""Phase 5D-C differential gate for the back-ported rollout fast path.

`rollout.complete_deal` now finishes trick play on `fast_trick.FastTrickState`
instead of the authoritative engine, because profiling put 85% of a PIMC
decision in `_validate_deal_state` — the engine revalidating states it had just
produced. The optimisation is only admissible if it changes nothing observable,
so this file requires that at three levels:

* the projection from a `DealState` is exact for all four seats, refs included;
* every transition agrees field for field with `apply_action`, all the way to the
  deal score and the rising-score transition;
* the whole PIMC decision, diagnostics and all, is identical with the fast path
  on and off.

The third is the one that actually gates the change. The first two say why it
passes.
"""

from __future__ import annotations

import pytest

from tuppi_agents import construct_agent, phase4_specifications_by_profile_key
from tuppi_engine import PlayCardAction, apply_action, observation_for
from tuppi_engine.serialization import observation_to_data

from tuppi_search import pimc
from tuppi_search.config import PimcConfiguration
from tuppi_search.diagnostics import PimcDecisionDiagnostics
from tuppi_search.errors import IllegalRolloutActionError
from tuppi_search.fast_trick import FastTrickError, FastTrickState
from tuppi_search.rollout import SeatPolicies, complete_deal
from tuppi_search.utilities import UtilityId

from .conftest import advance_to

REFERENCE = "partner_aware_v1"


def _diagnostics(decision, policies):
    return PimcDecisionDiagnostics(
        agent_id="agent:sha256:" + "0" * 8,
        decision=decision,
        rollout_policy_agent_ids=policies.policy_agent_ids,
    ).to_data()


def _decide_both(observation, configuration):
    """One decision on each path, with everything else held identical."""

    common = dict(
        configuration=configuration,
        decision_seed="tuppi-rollout-differential-v1",
    )
    fast = pimc.decide(observation, **common, _fast_path=True)
    slow = pimc.decide(observation, **common, _fast_path=False)
    policies = SeatPolicies(
        configuration=configuration, root_seat=observation.observing_seat
    )
    return _diagnostics(fast, policies), _diagnostics(slow, policies)


# ------------------------------------------------------- level 1: projection


def test_projection_from_a_deal_state_is_exact_for_every_seat(
    mid_position, late_position, forced_position
):
    """Including match_ref and deal_ref, which the assignment path cannot keep."""

    for position in (mid_position, late_position, forced_position):
        fast = FastTrickState.from_deal_state(position.deal_state)
        for seat in range(4):
            assert observation_to_data(fast.observation_for(seat)) == (
                observation_to_data(observation_for(position.deal_state, seat))
            )


def test_projection_refuses_a_state_that_is_not_in_trick_play(showing_position):
    with pytest.raises(FastTrickError, match="trick-play deal state"):
        FastTrickState.from_deal_state(showing_position.deal_state)


# ------------------------------------------------------ level 2: transitions


@pytest.mark.parametrize("tricks", [0, 4, 9])
def test_every_transition_agrees_with_the_authoritative_engine(tricks):
    """Walk one deal on both representations and compare after each action."""

    position = advance_to(tricks=tricks)
    specification = phase4_specifications_by_profile_key()[REFERENCE]
    authoritative = position.deal_state
    fast = FastTrickState.from_deal_state(authoritative)
    steps = 0
    while not authoritative.complete:
        actor = authoritative.current_actor
        expected = observation_for(authoritative, actor)
        assert observation_to_data(fast.observation_for(actor)) == (
            observation_to_data(expected)
        )
        action = construct_agent(specification, seat=actor).choose_action(expected)
        authoritative = apply_action(authoritative, action)
        fast = fast.apply(action)
        steps += 1
        assert fast.hands == authoritative.hands
        assert fast.current_actor == authoritative.current_actor
        assert fast.current_trick == authoritative.current_trick
        assert fast.completed_tricks == authoritative.completed_tricks
        assert fast.team_tricks == authoritative.team_tricks
        assert fast.phase == authoritative.phase
        assert fast.deal_score == authoritative.deal_score
        assert fast.ending_score == authoritative.ending_score
        assert fast.next_dealer == authoritative.next_dealer
    remaining = 4 * (13 - len(position.deal_state.completed_tricks)) - len(
        position.deal_state.current_trick
    )
    assert steps == remaining
    assert fast.complete


def test_both_rollout_paths_return_the_same_outcome(mid_position, smoke_config):
    policies = SeatPolicies(configuration=smoke_config, root_seat=0)
    fast = complete_deal(
        mid_position.deal_state, policies=policies, root_seat=0, _fast_path=True
    )
    slow = complete_deal(
        mid_position.deal_state, policies=policies, root_seat=0, _fast_path=False
    )
    assert fast.summary.to_data() == slow.summary.to_data()
    assert fast.actions_simulated == slow.actions_simulated
    assert (fast.exact_tail_used, fast.solver_calls, fast.solver_nodes) == (
        slow.exact_tail_used,
        slow.solver_calls,
        slow.solver_nodes,
    )


def test_the_fast_path_counts_a_forced_root_action_the_same_way(
    mid_position, smoke_config
):
    """`actions_already_simulated` must survive the handover unchanged."""

    policies = SeatPolicies(configuration=smoke_config, root_seat=0)
    outcomes = [
        complete_deal(
            mid_position.deal_state,
            policies=policies,
            root_seat=0,
            actions_already_simulated=1,
            _fast_path=fast,
        ).actions_simulated
        for fast in (True, False)
    ]
    assert outcomes[0] == outcomes[1]


# -------------------------------------------------------- level 3: decisions


def test_the_whole_decision_is_identical_on_both_paths(mid_position, late_position):
    configuration = PimcConfiguration.build(world_count=2)
    for position in (mid_position, late_position):
        fast, slow = _decide_both(position.observation, configuration)
        assert fast == slow


def test_the_opening_lead_decision_is_identical_on_both_paths():
    """The position the back-port exists for: 13 arms, a full-length rollout."""

    position = advance_to(tricks=0)
    assert position.legal_action_count == 13
    configuration = PimcConfiguration.build(
        world_count=2, showing_search_enabled=False
    )
    fast, slow = _decide_both(position.observation, configuration)
    assert fast == slow


def test_a_showing_root_is_identical_on_both_paths(showing_position):
    """A showing root walks the engine first, then hands over mid-rollout."""

    configuration = PimcConfiguration.build(
        world_count=2, showing_search_enabled=True
    )
    fast, slow = _decide_both(showing_position.observation, configuration)
    assert fast == slow


def test_the_deal_points_utility_is_identical_on_both_paths(mid_position):
    """The fast summary must score the same under every adapter, not just one."""

    configuration = PimcConfiguration.build(
        world_count=2, utility_id=UtilityId.DEAL_RESULT_V1
    )
    fast, slow = _decide_both(mid_position.observation, configuration)
    assert fast == slow


# --------------------------------------------------------------- boundaries


def test_an_exact_tail_keeps_the_authoritative_path(late_position, tail_config):
    """The solver needs a real DealState, so the tail must suppress the handover."""

    policies = SeatPolicies(configuration=tail_config, root_seat=0)
    from tuppi_search.exact_tail import ExactTail

    tail = ExactTail.from_configuration(tail_config)
    assert tail is not None
    outcome = complete_deal(
        late_position.deal_state,
        policies=policies,
        root_seat=0,
        exact_tail=tail,
        _fast_path=True,
    )
    assert outcome.exact_tail_used
    assert outcome.solver_calls >= 1


def test_the_fast_path_refuses_a_revoke_rather_than_repairing_it(smoke_config):
    """Phase 0B's recorded fidelity failure was substituting a legal card.

    The refusal is raised by ``_choose`` before the transition sees the action,
    because the fast state offers the same legal set the engine would. That is
    the point: the check did not move, it is just no longer paid for with a
    whole-state revalidation.
    """

    from tuppi_search import rollout as rollout_module

    class Revoking:
        """Plays off-suit while holding the led suit, whenever it can."""

        def choose_action(self, observation):
            legal = observation.legal_actions
            if not observation.current_trick:
                return legal[0]
            led = observation.current_trick[0].card.suit
            offsuit = [
                action
                for action in observation.legal_actions
                if action.card.suit is not led
            ]
            in_hand_offsuit = [
                card for card in observation.own_hand if card.suit is not led
            ]
            holds_led = any(card.suit is led for card in observation.own_hand)
            if holds_led and in_hand_offsuit and not offsuit:
                            return PlayCardAction(
                    seat=observation.observing_seat, card=in_hand_offsuit[0]
                )
            return legal[0]

    agents = tuple(Revoking() for _ in range(4))
    refusals = 0
    for tricks in (0, 4, 9):
        try:
            rollout_module._complete_fast(
                advance_to(tricks=tricks).deal_state,
                agents=agents,
                root_seat=0,
                simulated=0,
            )
        except IllegalRolloutActionError:
            refusals += 1
    assert refusals >= 1, "no position produced a reachable revoke"


def test_the_transition_itself_still_validates_the_play(mid_position):
    """Not only ``_choose``: ``apply`` refuses an illegal card on its own.

    A card held by another seat is illegal at every position, so this pins the
    transition guard without depending on a revoke being reachable here.
    """

    fast = FastTrickState.from_deal_state(mid_position.deal_state)
    actor = fast.current_actor
    held_elsewhere = next(
        card
        for seat in range(4)
        if seat != actor
        for card in fast.hands[seat]
    )
    assert held_elsewhere not in fast.hands[actor]
    with pytest.raises(FastTrickError, match="illegal fast-path play"):
        fast.apply(PlayCardAction(seat=actor, card=held_elsewhere))


def test_the_transition_refuses_an_action_from_the_wrong_seat(mid_position):
    fast = FastTrickState.from_deal_state(mid_position.deal_state)
    other = (fast.current_actor + 1) % 4
    with pytest.raises(FastTrickError, match="wrong seat"):
        fast.apply(PlayCardAction(seat=other, card=fast.hands[other][0]))


# ------------------------------------- the incumbent as a rollout continuation


def test_the_production_incumbent_is_an_admitted_rollout_policy():
    """PIMC's value estimate is "this action, then reference play". The reference
    could not previously be the policy that will actually play the deal."""

    from tuppi_search.config import SUPPORTED_ROLLOUT_POLICIES

    assert "partner_aware_lead_v2" in SUPPORTED_ROLLOUT_POLICIES


def test_admitting_it_did_not_select_it():
    """Every existing result keeps the continuation it was measured with."""

    from tuppi_search.config import DEVELOPMENT_REFERENCE_POLICY

    assert DEVELOPMENT_REFERENCE_POLICY == "partner_aware_v1"
    assert PimcConfiguration.build(world_count=2).rollout_policy_key == (
        "partner_aware_v1"
    )


#: Every registered Phase 5C identity, recorded before the incumbent was admitted
#: to ``SUPPORTED_ROLLOUT_POLICIES`` and verified byte-for-byte against the tree
#: at that commit. Nothing in the suite pinned these — the registry test only
#: checked that the digest *starts with* "sha256:" — so an identity could have
#: drifted silently. A change that moves one of these is not necessarily wrong,
#: but it invalidates every result quoted against the old id, so it has to be a
#: decision rather than a side effect.
FROZEN_PHASE5C_IDENTITIES = {
    "uniform_feasible_pimc_counting_rollout_v1":
        "agent:sha256:31fdf79ceed47ae4c1e0e52cff35e394f6fd0bca351b192424516d80fdd77c0a",
    "uniform_feasible_pimc_deal_utility_v1":
        "agent:sha256:71954163ffd9932342bfae32ddc06374ab13fabeaaf3e8b7872d878045522a9b",
    "uniform_feasible_pimc_exact_tail_v1":
        "agent:sha256:2a9e750661142187b0c7d1fb8f7ee08bcae0ed0a7c894b18a59cf0da6a752ebb",
    "uniform_feasible_pimc_small_v1":
        "agent:sha256:ebbdd6079eb6db4bb7308e46f0ceedc159dc799e4a81cc613b2d62f7071e5ef8",
    "uniform_feasible_pimc_smoke_v1":
        "agent:sha256:9b2ab3729faa066cac2ee9dbb0227b221b08830c8d2f69a06ada97efe6af59f6",
    "uniform_feasible_pimc_standard_v1":
        "agent:sha256:290f3b012e53b769970b558b0905dfc3e95767ca13863591382e3e375a59332d",
}

#: The registry snapshot digest over all six, recorded at the same commit.
FROZEN_REGISTRY_DIGEST = (
    "sha256:dc746583f655c2cff13c5136571060bcf9861a2b1514b507f6bb555a2d270743"
)


def test_no_registered_phase5c_agent_identity_moved():
    """The whitelist is validation, not identity: admitting a value must not
    change a single content-addressed agent id."""

    from tuppi_search.registry import phase5c_specifications

    specifications = phase5c_specifications()
    assert set(specifications) == set(FROZEN_PHASE5C_IDENTITIES)
    for key, expected in sorted(FROZEN_PHASE5C_IDENTITIES.items()):
        assert specifications[key].agent_id == expected, key


def test_the_registry_digest_did_not_move():
    from tuppi_search.registry import registry_snapshot

    assert registry_snapshot()["registry_digest"] == FROZEN_REGISTRY_DIGEST


def test_no_registered_configuration_identity_moved():
    from tuppi_search.registry import configuration_for, phase5c_specifications

    for key in phase5c_specifications():
        configuration = configuration_for(key)
        assert configuration.configuration_id.startswith("pimcfg:sha256:")
        # The configuration id is digested into the agent id above, so pinning
        # those pins these; this only asserts the default continuation is the one
        # every recorded result was measured with.
        assert configuration.rollout_policy_key in (
            "partner_aware_v1",
            "public_counting_v1",
        )


def test_the_incumbent_builds_four_distinct_seats_with_its_own_identity():
    configuration = PimcConfiguration.build(
        world_count=2, rollout_policy_key="partner_aware_lead_v2"
    )
    policies = SeatPolicies(configuration=configuration, root_seat=0)
    agents = policies.build()
    assert len({id(agent) for agent in agents}) == 4
    # A real content-addressed identity over the improved behaviour, not the base
    # profile's id with a name glued to the front.
    reported = set(policies.policy_agent_ids)
    assert len(reported) == 1
    assert reported.pop().startswith("agent:sha256:")


def test_the_incumbent_identity_is_not_the_base_profile_identity():
    """The mismatch this closes would be invisible if the two shared an id."""

    from tuppi_agents import phase4_specifications_by_profile_key

    from tuppi_search.config import rollout_specifications

    specifications = rollout_specifications()
    base = phase4_specifications_by_profile_key()["partner_aware_v1"]
    assert specifications["partner_aware_lead_v2"].agent_id != base.agent_id


def test_a_rollout_with_the_incumbent_completes_and_scores(mid_position):
    configuration = PimcConfiguration.build(
        world_count=2, rollout_policy_key="partner_aware_lead_v2"
    )
    policies = SeatPolicies(configuration=configuration, root_seat=0)
    outcome = complete_deal(
        mid_position.deal_state, policies=policies, root_seat=0
    )
    assert outcome.summary.tricks_simulated == 13
    assert not outcome.exact_tail_used


def test_the_incumbent_continuation_is_identical_on_both_rollout_paths(mid_position):
    """The fast path must hold for a policy it was never measured against."""

    configuration = PimcConfiguration.build(
        world_count=2, rollout_policy_key="partner_aware_lead_v2"
    )
    fast, slow = _decide_both(mid_position.observation, configuration)
    assert fast == slow


def test_determinism_is_read_off_the_specifications_not_assumed():
    """It used to return a bare True justified by "all are Phase 4 profiles"."""

    for key in ("partner_aware_v1", "partner_aware_lead_v2"):
        configuration = PimcConfiguration.build(world_count=2, rollout_policy_key=key)
        assert configuration.all_policies_deterministic
    with pytest.raises(Exception):
        PimcConfiguration.build(
            world_count=2, rollout_replicas=2, rollout_policy_key="partner_aware_lead_v2"
        )


def test_an_unknown_rollout_policy_is_still_refused():
    with pytest.raises(Exception, match="unsupported rollout policy"):
        PimcConfiguration.build(
            world_count=2, rollout_policy_key="partner_aware_discard_v3"
        )


def test_phase4_keys_cannot_be_shadowed_by_an_improved_policy():
    from tuppi_agents import phase4_specifications_by_profile_key

    from tuppi_search.config import rollout_specifications

    merged = rollout_specifications()
    for key, specification in phase4_specifications_by_profile_key().items():
        assert merged[key] == specification
