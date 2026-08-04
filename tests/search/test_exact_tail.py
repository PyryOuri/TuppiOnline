"""The exact-tail continuation: thresholds, identity, and utility compatibility."""

from __future__ import annotations

import pytest

from tuppi_engine import EnginePhase
from tuppi_rules import Contract, TRICKS_PER_DEAL, team_for_seat

from tuppi_search.config import (
    ExactTailFailurePolicy,
    MAXIMUM_EXACT_TAIL_TRICKS_REMAINING,
    PimcConfiguration,
)
from tuppi_search.errors import ExactTailError, SearchConfigurationError
from tuppi_search.exact_tail import ExactTail
from tuppi_search.pimc import decide
from tuppi_search.rollout import SeatPolicies, complete_deal
from tuppi_search.utilities import OutcomeSource, UtilityId, utility_value

from .conftest import walk_deal


def test_a_disabled_tail_builds_nothing(smoke_config):
    assert smoke_config.exact_tail_enabled is False
    assert ExactTail.from_configuration(smoke_config) is None


def test_an_enabled_tail_carries_its_threshold_and_solver(tail_config):
    tail = ExactTail.from_configuration(tail_config)
    assert tail is not None
    assert tail.max_tricks_remaining == 4
    data = tail.to_data()
    assert data["solver_algorithm_id"] == "tuppi.exact.trick_count_minimax_v1"
    assert "concentrates perfect-information bias" in data["semantics"]


def test_the_threshold_changes_the_agent_identity():
    four = PimcConfiguration.build(
        world_count=4, exact_tail_enabled=True, exact_tail_max_tricks_remaining=4
    )
    three = PimcConfiguration.build(
        world_count=4, exact_tail_enabled=True, exact_tail_max_tricks_remaining=3
    )
    off = PimcConfiguration.build(world_count=4)
    assert len({four.configuration_id, three.configuration_id, off.configuration_id}) == 3


def test_a_threshold_beyond_the_measured_range_is_refused():
    with pytest.raises(SearchConfigurationError):
        PimcConfiguration.build(
            world_count=2,
            exact_tail_enabled=True,
            exact_tail_max_tricks_remaining=MAXIMUM_EXACT_TAIL_TRICKS_REMAINING + 1,
        )
    with pytest.raises(SearchConfigurationError):
        PimcConfiguration.build(
            world_count=2, exact_tail_max_tricks_remaining=4
        )


def test_the_threshold_is_respected_exactly(tail_config):
    tail = ExactTail.from_configuration(tail_config)
    for position in walk_deal(stream_index=1):
        state = position.deal_state
        if state.phase is not EnginePhase.TRICK_PLAY:
            assert tail.is_in_range(state) is False
            continue
        remaining = TRICKS_PER_DEAL - len(state.completed_tricks)
        assert tail.is_in_range(state) is (remaining <= 4)
        verdict = tail.consider(state, root_seat=state.current_actor)
        if remaining > 4:
            assert verdict is None
        else:
            assert verdict is not None
            assert verdict.solver_calls == 1
            assert verdict.summary is not None
            assert verdict.summary.source is OutcomeSource.EXACT_TAIL


def test_the_tail_fires_before_the_threshold_is_reached_only_when_in_range(
    mid_position, tail_config
):
    tail = ExactTail.from_configuration(tail_config)
    assert tail.is_in_range(mid_position.deal_state) is False
    assert tail.consider(
        mid_position.deal_state, root_seat=mid_position.deal_state.current_actor
    ) is None


def test_the_tail_terminates_the_rollout_and_reports_solver_work(
    late_position, tail_config, smoke_config
):
    seat = late_position.observation.observing_seat
    tail = ExactTail.from_configuration(tail_config)
    policies = SeatPolicies(configuration=tail_config, root_seat=seat)
    with_tail = complete_deal(
        late_position.deal_state, policies=policies, root_seat=seat, exact_tail=tail
    )
    without = complete_deal(
        late_position.deal_state,
        policies=SeatPolicies(configuration=smoke_config, root_seat=seat),
        root_seat=seat,
    )
    assert with_tail.exact_tail_used is True
    assert with_tail.solver_calls == 1
    assert with_tail.solver_nodes > 0
    assert without.exact_tail_used is False
    assert without.solver_calls == 0
    assert with_tail.actions_simulated < without.actions_simulated


def test_the_tail_and_the_rollout_agree_when_the_continuation_is_forced(
    smoke_config,
):
    """With one trick left every card is forced, so both continuations coincide.

    This is the sharp compatibility test: where the exact solver and a
    reference-policy rollout describe the *same* continuation, they must produce the
    same deal outcome and therefore the same utility.
    """

    single_trick = PimcConfiguration.build(
        world_count=2, exact_tail_enabled=True, exact_tail_max_tricks_remaining=1
    )
    tail = ExactTail.from_configuration(single_trick)
    checked = 0
    for position in walk_deal(stream_index=2):
        state = position.deal_state
        if state.phase is not EnginePhase.TRICK_PLAY:
            continue
        if TRICKS_PER_DEAL - len(state.completed_tricks) != 1:
            continue
        if state.current_trick:
            continue
        seat = state.current_actor
        verdict = tail.consider(state, root_seat=seat)
        assert verdict is not None and verdict.summary is not None
        rollout = complete_deal(
            state,
            policies=SeatPolicies(configuration=smoke_config, root_seat=seat),
            root_seat=seat,
        )
        assert verdict.summary.team0_tricks == rollout.summary.team0_tricks
        for item in UtilityId:
            assert utility_value(item, verdict.summary) == utility_value(
                item, rollout.summary
            )
        checked += 1
    assert checked >= 1


@pytest.mark.parametrize("contract_filter", [Contract.RAMI, Contract.NOLO])
def test_the_tail_works_for_both_contracts(contract_filter, tail_config):
    tail = ExactTail.from_configuration(tail_config)
    found = False
    for stream_index in range(8):
        for position in walk_deal(stream_index=stream_index):
            state = position.deal_state
            if state.phase is not EnginePhase.TRICK_PLAY:
                continue
            if state.contract is not contract_filter:
                continue
            if TRICKS_PER_DEAL - len(state.completed_tricks) > 4:
                continue
            verdict = tail.consider(state, root_seat=state.current_actor)
            assert verdict is not None and verdict.summary is not None
            assert verdict.summary.contract is contract_filter
            found = True
            break
        if found:
            break
    if not found:
        pytest.skip(f"no {contract_filter.value} tail position was reached")


def test_the_tail_handles_a_partial_current_trick(tail_config):
    tail = ExactTail.from_configuration(tail_config)
    checked = 0
    for position in walk_deal(stream_index=1):
        state = position.deal_state
        if state.phase is not EnginePhase.TRICK_PLAY or not state.current_trick:
            continue
        if TRICKS_PER_DEAL - len(state.completed_tricks) > 4:
            continue
        verdict = tail.consider(state, root_seat=state.current_actor)
        assert verdict is not None and verdict.summary is not None
        checked += 1
    assert checked >= 1


def test_the_tail_orientation_is_correct_for_both_teams(tail_config):
    tail = ExactTail.from_configuration(tail_config)
    seen = set()
    for stream_index in range(6):
        for position in walk_deal(stream_index=stream_index):
            state = position.deal_state
            if state.phase is not EnginePhase.TRICK_PLAY:
                continue
            if TRICKS_PER_DEAL - len(state.completed_tricks) > 4:
                continue
            for seat in range(4):
                verdict = tail.consider(state, root_seat=seat)
                assert verdict is not None and verdict.summary is not None
                assert verdict.summary.root_team is team_for_seat(seat)
                seen.add(team_for_seat(seat))
            # Both partnerships' views of one position must be exact mirrors in
            # trick count.
            zero = tail.consider(state, root_seat=0).summary
            one = tail.consider(state, root_seat=1).summary
            assert zero.team0_tricks == one.team0_tricks
            assert zero.root_team_tricks + one.root_team_tricks == TRICKS_PER_DEAL
            if len(seen) == 2:
                return
    raise AssertionError("no tail position covered both teams")


def test_a_tail_decision_is_deterministic_and_legal(late_position, tail_config):
    first = decide(
        late_position.observation, configuration=tail_config, decision_seed="t"
    )
    again = decide(
        late_position.observation, configuration=tail_config, decision_seed="t"
    )
    assert first.selected_action == again.selected_action
    assert first.selected_action in late_position.observation.legal_actions
    total_tail = sum(item.exact_tail_evaluations for item in first.candidates)
    assert total_tail == sum(item.evaluations for item in first.candidates)


def test_the_tail_does_not_change_public_observations(late_position, tail_config):
    """Solver output must never reach an observation or a public event."""

    from tuppi_engine import observation_for

    before = observation_for(
        late_position.deal_state, late_position.observation.observing_seat
    )
    decide(late_position.observation, configuration=tail_config, decision_seed="t")
    after = observation_for(
        late_position.deal_state, late_position.observation.observing_seat
    )
    assert before == after
    assert before.legal_actions == after.legal_actions


def test_a_strict_failure_policy_raises_rather_than_guessing():
    """A refused solve must not silently become a partial exact result."""

    tail = ExactTail(
        max_tricks_remaining=4,
        node_budget=1,
        failure_policy=ExactTailFailurePolicy.STRICT,
    )
    for position in walk_deal(stream_index=1):
        state = position.deal_state
        if state.phase is not EnginePhase.TRICK_PLAY:
            continue
        if TRICKS_PER_DEAL - len(state.completed_tricks) != 4:
            continue
        with pytest.raises(ExactTailError):
            tail.consider(state, root_seat=state.current_actor)
        return
    raise AssertionError("no four-trick position was reached")


def test_a_fallback_failure_policy_returns_to_the_rollout():
    tail = ExactTail(
        max_tricks_remaining=4,
        node_budget=1,
        failure_policy=ExactTailFailurePolicy.FALLBACK_ROLLOUT,
    )
    for position in walk_deal(stream_index=1):
        state = position.deal_state
        if state.phase is not EnginePhase.TRICK_PLAY:
            continue
        if TRICKS_PER_DEAL - len(state.completed_tricks) != 4:
            continue
        verdict = tail.consider(state, root_seat=state.current_actor)
        assert verdict is not None
        assert verdict.refused is True
        assert verdict.summary is None
        assert verdict.solver_calls == 1
        return
    raise AssertionError("no four-trick position was reached")


def test_a_malformed_tail_is_refused():
    with pytest.raises(ExactTailError):
        ExactTail(
            max_tricks_remaining=0,
            node_budget=10,
            failure_policy=ExactTailFailurePolicy.STRICT,
        )
    with pytest.raises(ExactTailError):
        ExactTail(
            max_tricks_remaining=4,
            node_budget=0,
            failure_policy=ExactTailFailurePolicy.STRICT,
        )
    with pytest.raises(ExactTailError):
        ExactTail.from_configuration("not a configuration")  # type: ignore[arg-type]


def test_the_registered_tail_agent_uses_the_benchmarked_threshold():
    from tuppi_search.registry import configuration_for

    configuration = configuration_for("uniform_feasible_pimc_exact_tail_v1")
    assert configuration.exact_tail_enabled is True
    assert configuration.exact_tail_max_tricks_remaining == 4
    assert configuration.exact_tail_failure_policy is ExactTailFailurePolicy.STRICT


def test_tail_and_no_tail_may_disagree_and_that_is_expected(late_position):
    """The tail changes the estimand, so a different action is not a defect."""

    off = PimcConfiguration.build(world_count=2)
    on = PimcConfiguration.build(
        world_count=2, exact_tail_enabled=True, exact_tail_max_tricks_remaining=4
    )
    first = decide(late_position.observation, configuration=off, decision_seed="x")
    second = decide(late_position.observation, configuration=on, decision_seed="x")
    # Both must be legal and deterministic; equality is not required.
    assert first.selected_action in late_position.observation.legal_actions
    assert second.selected_action in late_position.observation.legal_actions
    assert off.configuration_id != on.configuration_id
