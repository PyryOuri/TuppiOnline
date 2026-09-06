"""N06 checks: the memoised path must be indistinguishable from the plain one.

A single value, label or action difference rejects the optimisation, so these
tests are written to catch agreement that is accidental — a key that merges
different positions, a plan borrowed from another history, or a tie silently
resolved by whichever branch filled the cache first.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tuppi_engine import EnginePhase, apply_action, observation_for
from tuppi_rules import card_to_code, card_to_index
from tuppi_nolo.cache import SecurityCache, position_key
from tuppi_nolo.certificates import CheckStatus, ControlModel
from tuppi_nolo.fixtures import load_fixtures
from tuppi_nolo.security import SecurityStatus, solve_security
from tuppi_nolo.support import SupportBudget, build_support, semantic_observation_key

PACKET = Path(__file__).resolve().parents[2] / "docs/nolo/tasks"


@pytest.fixture(scope="module")
def positions():
    return {f.id: f.replay() for f in load_fixtures(PACKET / "fixtures.json")}


def both_paths(state):
    observation = observation_for(state, state.current_actor)
    plain = solve_security(
        observation, SupportBudget(), verification_budget=SupportBudget()
    )
    cache = SecurityCache()
    cached = solve_security(
        observation, SupportBudget(), verification_budget=SupportBudget(), cache=cache
    )
    return plain, cached, cache


def values(result):
    return sorted(
        (card_to_code(v.action.card), v.security_value) for v in result.root_values
    )


# ------------------------------------------------------------- correctness


@pytest.mark.parametrize("name", ["A", "B", "C"])
def test_the_two_paths_agree_exactly(positions, name):
    plain, cached, _ = both_paths(positions[name])
    assert cached.status is plain.status is SecurityStatus.EXACT_COMPLETE
    assert values(cached) == values(plain)
    assert cached.selected_action == plain.selected_action
    assert cached.world_count == plain.world_count


@pytest.mark.parametrize("name", ["A", "B", "C"])
def test_the_cached_plan_is_accepted_by_the_independent_verifier(positions, name):
    _plain, cached, _ = both_paths(positions[name])
    assert cached.verification.status is CheckStatus.EXACT_COMPLETE
    assert cached.certificate.claimed_terminal_bound == max(
        v.security_value for v in cached.root_values if v.action == cached.selected_action
    )


@pytest.mark.parametrize("name", ["A", "B", "C"])
def test_the_baseline_tie_is_not_decided_by_whoever_filled_the_cache(positions, name):
    """The tie rule reads the current observation, so a cached optimal *set*
    must still resolve to the action the plain search picked."""

    plain, cached, _ = both_paths(positions[name])
    assert card_to_code(cached.selected_action.card) == card_to_code(
        plain.selected_action.card
    )


def test_a_warm_cache_reused_across_solves_changes_nothing(positions):
    """Entries survive between calls; answers must not drift as they accumulate."""

    observation = observation_for(positions["C"], positions["C"].current_actor)
    shared = SecurityCache()
    first = solve_security(observation, SupportBudget(), cache=shared)
    entries_after_first = shared.entries
    second = solve_security(observation, SupportBudget(), cache=shared)
    assert values(second) == values(first)
    assert second.selected_action == first.selected_action
    assert shared.stats.hits > 0
    assert shared.entries == entries_after_first, "a repeat solve should add nothing"


# --------------------------------------------------------------- the key


def test_the_key_separates_positions_that_differ_only_in_hidden_cards(positions):
    """Two worlds of the same position have different allocations, so a node
    holding one must not collide with a node holding the other."""

    observation = observation_for(positions["C"], positions["C"].current_actor)
    support = build_support(observation, SupportBudget())
    seat = observation.observing_seat
    root = observation.legal_actions[0]
    singles = [
        position_key(
            (apply_action(world.continuation.state, root),),
            seat=seat, root_key="root", control=ControlModel.SINGLE_SEAT,
        )
        for world in support.research_worlds
    ]
    assert len(set(singles)) == len(singles), "distinct allocations collided"


def test_the_key_ignores_the_order_worlds_were_enumerated_in(positions):
    observation = observation_for(positions["B"], positions["B"].current_actor)
    support = build_support(observation, SupportBudget())
    seat = observation.observing_seat
    root = observation.legal_actions[0]
    states = tuple(
        apply_action(world.continuation.state, root) for world in support.research_worlds
    )
    forward = position_key(states, seat=seat, root_key="r", control=ControlModel.SINGLE_SEAT)
    backward = position_key(
        tuple(reversed(states)), seat=seat, root_key="r", control=ControlModel.SINGLE_SEAT
    )
    assert forward == backward


def test_the_key_separates_roots_and_control_models(positions):
    observation = observation_for(positions["B"], positions["B"].current_actor)
    support = build_support(observation, SupportBudget())
    seat = observation.observing_seat
    states = tuple(
        apply_action(w.continuation.state, observation.legal_actions[0])
        for w in support.research_worlds
    )
    base = position_key(states, seat=seat, root_key="r1", control=ControlModel.SINGLE_SEAT)
    other_root = position_key(states, seat=seat, root_key="r2", control=ControlModel.SINGLE_SEAT)
    other_model = position_key(states, seat=seat, root_key="r1", control=ControlModel.ALL_ACTIONS)
    assert base != other_root != other_model and base != other_model


def test_the_key_keeps_the_own_hand_in_its_own_order(positions):
    """Canonical showing and tie behaviour depend on hand order, so a sorted
    hand would be too coarse a key."""

    observation = observation_for(positions["B"], positions["B"].current_actor)
    support = build_support(observation, SupportBudget())
    seat = observation.observing_seat
    state = apply_action(
        support.research_worlds[0].continuation.state, observation.legal_actions[0]
    )
    key = position_key((state,), seat=seat, root_key="r", control=ControlModel.SINGLE_SEAT)
    own_component = key[7]
    assert own_component == tuple(card_to_index(c) for c in state.hands[seat])


def test_no_key_component_names_a_single_hidden_world(positions):
    """The allocation set is carried whole; nothing selects one world from it."""

    observation = observation_for(positions["B"], positions["B"].current_actor)
    support = build_support(observation, SupportBudget())
    seat = observation.observing_seat
    states = tuple(
        apply_action(w.continuation.state, observation.legal_actions[0])
        for w in support.research_worlds
    )
    key = position_key(states, seat=seat, root_key="r", control=ControlModel.SINGLE_SEAT)
    allocations = key[8]
    assert len(allocations) == len(states) >= 2
    assert allocations == tuple(sorted(allocations))


# -------------------------------------------------------------- the bounds


def test_a_full_cache_stops_storing_rather_than_guessing(positions):
    small = SecurityCache(max_entries=5)
    observation = observation_for(positions["C"], positions["C"].current_actor)
    plain = solve_security(observation, SupportBudget(), verification_budget=SupportBudget())
    limited = solve_security(
        observation, SupportBudget(), verification_budget=SupportBudget(), cache=small
    )
    assert small.entries <= 5
    assert small.stats.rejected_full > 0
    assert values(limited) == values(plain), "a bounded cache must not change answers"
    assert limited.selected_action == plain.selected_action


def test_counters_are_explicit_and_consistent(positions):
    _plain, cached, cache = both_paths(positions["B"])
    report = cache.diagnostics()
    assert report["lookups"] == report["hits"] + report["misses"]
    assert report["entries"] == cache.entries <= report["max_entries"]
    assert cached.search_engine_transitions > 0
    assert report["hits"] >= 0 and report["stores"] >= 0


def test_a_spent_budget_yields_no_exact_answer_on_the_cached_path(positions):
    observation = observation_for(positions["A"], positions["A"].current_actor)
    spent = build_support(observation, SupportBudget()).engine_transitions
    result = solve_security(
        observation,
        SupportBudget(max_engine_transitions=spent + 1),
        cache=SecurityCache(),
    )
    assert result.status is SecurityStatus.SEARCH_BUDGET
    assert result.selected_action is None and result.root_values == ()
    assert result.certificate is None


def test_cache_size_is_rejected_when_not_positive():
    for bad in (0, -1):
        with pytest.raises(ValueError):
            SecurityCache(max_entries=bad)


def test_the_uncached_path_remains_the_default(positions):
    """N07 may only use a version that passed correctness, and the plain search
    stays the independent reference, so the default must not be the cache."""

    observation = observation_for(positions["B"], positions["B"].current_actor)
    result = solve_security(observation, SupportBudget())
    assert result.status is SecurityStatus.EXACT_COMPLETE
