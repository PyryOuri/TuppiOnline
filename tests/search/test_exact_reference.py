"""Small exact-reference tests: PIMC computed by hand, then compared.

Where the feasible set is small enough to enumerate, the PIMC value of every
candidate can be computed *exactly* - enumerate every feasible world, roll each one
out, average - with no sampling and no shared machinery. These tests do that
independently and compare against the search, which is the only way to be sure the
aggregation, the orientation, and the tie-break are all right rather than merely
self-consistent.
"""

from __future__ import annotations

import math

import pytest

from tuppi_engine import EnginePhase, apply_action
from tuppi_exact import HardConstraintModel, feasible_assignment_count

from tuppi_search.config import PimcConfiguration
from tuppi_search.pimc import decide
from tuppi_search.random import SearchSeedHierarchy, information_state_digest
from tuppi_search.rollout import SeatPolicies, complete_deal
from tuppi_search.utilities import utility_value
from tuppi_search.worlds import WorldSetMode, build_world_set, can_enumerate

from .conftest import walk_deal


def _seeds(observation, configuration, seed="exact"):
    return SearchSeedHierarchy(
        pimc_protocol=configuration.pimc_protocol_version,
        information_state=information_state_digest(observation),
        decision_seed=seed,
    )


def _independent_pimc_values(observation, configuration, world_set):
    """Compute each candidate's PIMC value without using the search code path."""

    seat = observation.observing_seat
    values: dict = {}
    for action in observation.legal_actions:
        utilities = []
        for world in world_set.worlds:
            forced = apply_action(world.state, action)
            outcome = complete_deal(
                forced,
                policies=SeatPolicies(configuration=configuration, root_seat=seat),
                root_seat=seat,
                actions_already_simulated=1,
            )
            utilities.append(
                utility_value(configuration.utility_id, outcome.summary)
            )
        values[action] = math.fsum(utilities) / len(utilities)
    return values


def _small_enumerable_position(*, maximum: int = 24):
    """Find a position whose feasible set is small enough to enumerate."""

    for stream_index in range(6):
        for position in walk_deal(stream_index=stream_index):
            if position.deal_state.phase is not EnginePhase.TRICK_PLAY:
                continue
            if len(position.observation.legal_actions) < 2:
                continue
            model = HardConstraintModel.build(position.observation)
            if not model.unknown_cards:
                continue
            total = feasible_assignment_count(model)
            if 2 <= total <= maximum and can_enumerate(position.observation):
                return position, total
    pytest.skip("no small enumerable multi-action position was reached")


def test_enumeration_matches_the_exact_feasible_count():
    position, total = _small_enumerable_position()
    configuration = PimcConfiguration.build(world_count=total)
    world_set = build_world_set(
        position.observation,
        configuration=configuration,
        seeds=_seeds(position.observation, configuration),
        mode=WorldSetMode.EXACT_ENUMERATION,
    )
    assert len(world_set) == total
    assert world_set.unique_world_count == total
    assert world_set.duplicate_count == 0


def test_exact_pimc_values_match_an_independent_computation():
    """The sharp test: search values equal a hand-rolled average, exactly."""

    position, total = _small_enumerable_position()
    configuration = PimcConfiguration.build(world_count=total)
    world_set = build_world_set(
        position.observation,
        configuration=configuration,
        seeds=_seeds(position.observation, configuration),
        mode=WorldSetMode.EXACT_ENUMERATION,
    )
    decision = decide(
        position.observation,
        configuration=configuration,
        decision_seed="exact",
        reuse_world_set=world_set,
    )
    expected = _independent_pimc_values(
        position.observation, configuration, world_set
    )
    for candidate in decision.candidates:
        assert candidate.mean_utility == pytest.approx(
            expected[candidate.action], abs=1e-12
        )


def test_the_selected_action_is_the_exact_argmax_with_canonical_tie_break():
    position, total = _small_enumerable_position()
    configuration = PimcConfiguration.build(world_count=total)
    world_set = build_world_set(
        position.observation,
        configuration=configuration,
        seeds=_seeds(position.observation, configuration),
        mode=WorldSetMode.EXACT_ENUMERATION,
    )
    decision = decide(
        position.observation,
        configuration=configuration,
        decision_seed="exact",
        reuse_world_set=world_set,
    )
    expected = _independent_pimc_values(
        position.observation, configuration, world_set
    )
    best_value = max(expected.values())
    winners = [
        index
        for index, action in enumerate(position.observation.legal_actions)
        if expected[action] == pytest.approx(best_value, abs=1e-12)
    ]
    assert decision.selected_index == min(winners)


def test_sampling_reproduces_the_enumerated_values_on_a_tiny_feasible_set():
    """When the feasible set has one member, sampling and enumeration coincide."""

    for stream_index in range(6):
        for position in walk_deal(stream_index=stream_index):
            if position.deal_state.phase is not EnginePhase.TRICK_PLAY:
                continue
            if len(position.observation.legal_actions) < 2:
                continue
            model = HardConstraintModel.build(position.observation)
            if feasible_assignment_count(model) != 1:
                continue
            configuration = PimcConfiguration.build(world_count=4)
            sampled = decide(
                position.observation,
                configuration=configuration,
                decision_seed="tiny",
            )
            enumerated_set = build_world_set(
                position.observation,
                configuration=PimcConfiguration.build(world_count=1),
                seeds=_seeds(position.observation, configuration),
                mode=WorldSetMode.EXACT_ENUMERATION,
            )
            enumerated = decide(
                position.observation,
                configuration=PimcConfiguration.build(world_count=1),
                decision_seed="tiny",
                reuse_world_set=enumerated_set,
            )
            assert sampled.selected_action == enumerated.selected_action
            assert [item.mean_utility for item in sampled.candidates] == pytest.approx(
                [item.mean_utility for item in enumerated.candidates]
            )
            return
    pytest.skip("no fully determined multi-action position was reached")


def test_a_deterministic_small_fixed_sample_is_reproducible_by_hand():
    """A two-world decision must equal the average of its two rollouts."""

    position, _ = _small_enumerable_position()
    configuration = PimcConfiguration.build(world_count=2)
    world_set = build_world_set(
        position.observation,
        configuration=configuration,
        seeds=_seeds(position.observation, configuration),
    )
    decision = decide(
        position.observation,
        configuration=configuration,
        decision_seed="exact",
        reuse_world_set=world_set,
    )
    expected = _independent_pimc_values(
        position.observation, configuration, world_set
    )
    for candidate in decision.candidates:
        assert candidate.evaluations == 2
        assert candidate.mean_utility == pytest.approx(
            expected[candidate.action], abs=1e-12
        )
        # With two values the reported spread is exactly their half-range.
        assert candidate.standard_deviation == pytest.approx(
            abs(candidate.maximum - candidate.minimum) / 2, abs=1e-12
        )


def test_orientation_is_exact_against_an_independent_computation():
    """A partner's view of the same position must use the same team orientation."""

    position, total = _small_enumerable_position()
    seat = position.observation.observing_seat
    partner = (seat + 2) % 4
    configuration = PimcConfiguration.build(world_count=total)
    world_set = build_world_set(
        position.observation,
        configuration=configuration,
        seeds=_seeds(position.observation, configuration),
        mode=WorldSetMode.EXACT_ENUMERATION,
    )
    decision = decide(
        position.observation,
        configuration=configuration,
        decision_seed="exact",
        reuse_world_set=world_set,
    )
    from tuppi_rules import team_for_seat

    assert decision.root_team is team_for_seat(seat)
    assert team_for_seat(partner) is decision.root_team
    # Every world's utility must be scored for that team, which the independent
    # computation reproduces exactly.
    expected = _independent_pimc_values(
        position.observation, configuration, world_set
    )
    assert decision.selected_value == pytest.approx(
        max(expected.values()), abs=1e-12
    )
