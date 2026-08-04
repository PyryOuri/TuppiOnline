"""The rollout boundary: policies see only their own seat's observation.

This is the test that would catch the most damaging possible defect in Phase 5C - a
rollout policy given the sampled world - so it does not check the boundary by
reading the code. It records **every argument every policy is called with** during
real rollouts and asserts that each was a ``PlayerObservation`` for the acting seat
and nothing else.
"""

from __future__ import annotations

import pytest

from tuppi_engine import DealState, MatchState, PlayerObservation
from tuppi_engine.errors import EngineError

from tuppi_search.errors import IllegalRolloutActionError, RolloutError, SearchError
from tuppi_search.pimc import decide
from tuppi_search.rollout import (
    MAXIMUM_ROLLOUT_ACTIONS,
    SeatPolicies,
    complete_deal,
)
from tuppi_search.validation import require_no_full_state

from .conftest import walk_deal


class _RecordingAgent:
    """Wraps a real policy and records exactly what it was handed."""

    def __init__(self, delegate, seat: int, log: list) -> None:
        self._delegate = delegate
        self._seat = seat
        self._log = log

    @property
    def identity(self) -> str:
        return self._delegate.identity

    def choose_action(self, *args, **kwargs):
        self._log.append(
            {
                "args": args,
                "kwargs": kwargs,
                "seat": self._seat,
            }
        )
        return self._delegate.choose_action(*args, **kwargs)


def test_rollout_policies_receive_exactly_one_observation_argument(
    mid_position, smoke_config, monkeypatch
):
    log: list = []
    original = SeatPolicies.build

    def recording_build(self):
        agents = original(self)
        return tuple(
            _RecordingAgent(agent, seat, log) for seat, agent in enumerate(agents)
        )

    monkeypatch.setattr(SeatPolicies, "build", recording_build)
    decide(mid_position.observation, configuration=smoke_config, decision_seed="sec")

    assert log, "no rollout policy was called"
    for entry in log:
        assert entry["kwargs"] == {}, "a policy received keyword arguments"
        assert len(entry["args"]) == 1, "a policy received more than the observation"
        payload = entry["args"][0]
        assert isinstance(payload, PlayerObservation)
        assert payload.observing_seat == entry["seat"]
        assert payload.current_actor == entry["seat"]


def test_no_rollout_policy_ever_receives_an_engine_state(
    mid_position, smoke_config, monkeypatch
):
    log: list = []
    original = SeatPolicies.build

    def recording_build(self):
        agents = original(self)
        return tuple(
            _RecordingAgent(agent, seat, log) for seat, agent in enumerate(agents)
        )

    monkeypatch.setattr(SeatPolicies, "build", recording_build)
    decide(mid_position.observation, configuration=smoke_config, decision_seed="sec")
    for entry in log:
        for value in tuple(entry["args"]) + tuple(entry["kwargs"].values()):
            assert not isinstance(value, (DealState, MatchState))
            require_no_full_state(value)


def test_require_no_full_state_rejects_real_states(mid_position):
    with pytest.raises(SearchError):
        require_no_full_state(mid_position.deal_state)
    # An observation is exactly what a policy may hold.
    require_no_full_state(mid_position.observation)


def test_each_seat_gets_a_distinct_runtime_agent(mid_position, smoke_config):
    policies = SeatPolicies(
        configuration=smoke_config,
        root_seat=mid_position.observation.observing_seat,
    )
    agents = policies.build()
    assert len(agents) == 4
    assert len({id(agent) for agent in agents}) == 4
    # Fresh objects per rollout, so no state can survive between rollouts.
    again = policies.build()
    assert {id(agent) for agent in agents}.isdisjoint({id(item) for item in again})


def test_the_root_seat_uses_the_configured_rollout_policy(mid_position, smoke_config):
    """Standard one-ply PIMC: all four seats share one policy after the forced action."""

    policies = SeatPolicies(
        configuration=smoke_config,
        root_seat=mid_position.observation.observing_seat,
    )
    identities = policies.policy_agent_ids
    assert len(set(identities)) == 1


def test_an_alternate_root_policy_is_a_different_configuration(mid_position):
    from tuppi_search.config import PimcConfiguration, RootContinuation

    configuration = PimcConfiguration.build(
        world_count=2,
        rollout_policy_key="partner_aware_v1",
        root_continuation=RootContinuation.ALTERNATE_ROLLOUT_POLICY,
        root_rollout_policy_key="public_counting_v1",
    )
    standard = PimcConfiguration.build(world_count=2)
    assert configuration.configuration_id != standard.configuration_id
    policies = SeatPolicies(
        configuration=configuration,
        root_seat=mid_position.observation.observing_seat,
    )
    identities = policies.policy_agent_ids
    assert len(set(identities)) == 2


def test_an_illegal_rollout_action_is_never_repaired(mid_position, smoke_config):
    """The legacy emulator substituted a legal action here. Phase 5C raises."""

    class _IllegalAgent:
        @property
        def identity(self) -> str:
            return "illegal_test_agent"

        def choose_action(self, observation):
            from tuppi_engine import PlayCardAction

            # A card the acting seat certainly does not hold in this position.
            other = next(
                card
                for seat in range(4)
                if seat != observation.observing_seat
                for card in mid_position.deal_state.hands[seat]
            )
            return PlayCardAction(seat=observation.observing_seat, card=other)

    class _IllegalPolicies(SeatPolicies):
        def build(self):
            return tuple(_IllegalAgent() for _ in range(4))

    policies = _IllegalPolicies(
        configuration=smoke_config,
        root_seat=mid_position.observation.observing_seat,
    )
    with pytest.raises((IllegalRolloutActionError, RolloutError, EngineError)):
        complete_deal(
            mid_position.deal_state,
            policies=policies,
            root_seat=mid_position.observation.observing_seat,
        )


def test_an_action_outside_the_offered_legal_set_is_refused(
    mid_position, smoke_config
):
    class _WrongSeatAgent:
        @property
        def identity(self) -> str:
            return "wrong_seat_agent"

        def choose_action(self, observation):
            from tuppi_engine import PlayCardAction

            wrong = (observation.observing_seat + 1) % 4
            return PlayCardAction(seat=wrong, card=observation.own_hand[0])

    class _WrongPolicies(SeatPolicies):
        def build(self):
            return tuple(_WrongSeatAgent() for _ in range(4))

    policies = _WrongPolicies(
        configuration=smoke_config,
        root_seat=mid_position.observation.observing_seat,
    )
    with pytest.raises(IllegalRolloutActionError):
        complete_deal(
            mid_position.deal_state,
            policies=policies,
            root_seat=mid_position.observation.observing_seat,
        )


def test_every_rollout_conserves_cards_and_plays_thirteen_tricks(smoke_config):
    """Card conservation, measured by counting rather than asserted.

    The engine forbids replaying a card and reconciles hands against history on
    every transition, so a rollout that completed the deal *and* simulated exactly
    the number of outstanding plays has played all 52 cards exactly once.
    """

    from tuppi_rules import DECK_SIZE, TRICKS_PER_DEAL

    checked = 0
    for position in walk_deal(stream_index=3):
        state = position.deal_state
        if state.phase.value != "TRICK_PLAY":
            continue
        already_played = (
            sum(len(trick.plays) for trick in state.completed_tricks)
            + len(state.current_trick)
        )
        seat = position.observation.observing_seat
        policies = SeatPolicies(configuration=smoke_config, root_seat=seat)
        outcome = complete_deal(state, policies=policies, root_seat=seat)
        assert outcome.summary.tricks_simulated == TRICKS_PER_DEAL
        assert 0 <= outcome.summary.team0_tricks <= TRICKS_PER_DEAL
        assert outcome.actions_simulated == DECK_SIZE - already_played
        assert outcome.actions_simulated <= MAXIMUM_ROLLOUT_ACTIONS
        checked += 1
        if checked >= 3:
            break
    assert checked >= 3


def test_the_search_agent_has_no_parameter_for_a_full_state():
    """The boundary is structural: there is nowhere to pass a state."""

    import inspect

    from tuppi_search.agents import UniformFeasiblePimcAgent

    parameters = set(
        inspect.signature(UniformFeasiblePimcAgent.__init__).parameters
    )
    assert parameters == {"self", "agent_id", "configuration", "seat", "policy_seed"}
    choose = set(
        inspect.signature(UniformFeasiblePimcAgent.choose_action).parameters
    )
    assert choose == {"self", "observation"}
