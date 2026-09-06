"""N04 checks: security values, one action per information class, and the
negative controls that would catch a per-world (strategy-fusion) shortcut.

The brute-force reference here enumerates complete root plans and then lets the
opposition answer, which is generate-and-test rather than the module's recursive
minimisation. Agreement between the two is therefore evidence, not a restatement.
"""

from __future__ import annotations

from dataclasses import replace
from itertools import permutations, product
from pathlib import Path

import pytest

from tuppi_engine import EnginePhase, PlayCardAction, apply_action, observation_for
from tuppi_rules import card_to_code
from tuppi_exact.continuation import hypothetical_continuation
from tuppi_nolo.certificates import CheckStatus, PlanEntry, verify_certificate
from tuppi_nolo.fixtures import load_fixtures
from tuppi_nolo.security import (
    SecurityStatus,
    _search,
    solve_security,
)
from tuppi_nolo.support import SupportBudget, build_support, semantic_observation_key

PACKET = Path(__file__).resolve().parents[2] / "docs/nolo/tasks"


@pytest.fixture(scope="module")
def positions():
    return {f.id: f.replay() for f in load_fixtures(PACKET / "fixtures.json")}


def observation_of(state):
    return observation_for(state, state.current_actor)


def solved(state, budget=None):
    return solve_security(
        observation_of(state),
        budget or SupportBudget(),
        verification_budget=SupportBudget(),
    )


def values_by_card(result):
    return {card_to_code(v.action.card): v.security_value for v in result.root_values}


# --------------------------------------------------------------- endpoints


def test_fixture_a_prefers_8S_at_seven_and_rates_alternatives_nine(positions):
    result = solved(positions["A"])
    assert result.status is SecurityStatus.EXACT_COMPLETE
    assert result.world_count == 20
    values = values_by_card(result)
    assert values["8S"] == 7
    assert {card: v for card, v in values.items() if card != "8S"} == {"3H": 9, "QD": 9}
    assert card_to_code(result.selected_action.card) == "8S"
    assert result.verification.status is CheckStatus.EXACT_COMPLETE


def test_fixture_b_values_and_the_shared_second_choice(positions):
    """A first-card-only recommendation must not pass: 9C is only worth 4 if
    the same follow-up is played in both worlds."""

    state = positions["B"]
    result = solved(state)
    assert result.status is SecurityStatus.EXACT_COMPLETE
    assert values_by_card(result) == {"9C": 4, "3C": 5}
    assert card_to_code(result.selected_action.card) == "9C"

    observation = observation_of(state)
    seat = observation.observing_seat
    table = {entry.information_key: entry.action for entry in result.plan}
    support = build_support(observation, SupportBudget())
    seconds = set()

    def walk(node, depth):
        if node.phase is not EnginePhase.TRICK_PLAY:
            return
        current = observation_for(node, node.current_actor)
        if node.current_actor == seat:
            action = table.get(semantic_observation_key(current))
            if action is None:
                assert len(current.legal_actions) == 1
                action = current.legal_actions[0]
            if depth == 1:
                seconds.add(card_to_code(action.card))
            walk(apply_action(node, action), depth + 1)
            return
        for candidate in current.legal_actions:
            walk(apply_action(node, candidate), depth)

    for world in support.research_worlds:
        walk(apply_action(world.continuation.state, result.selected_action), 1)
    assert seconds == {"3C"}, "the plan must name one follow-up for both worlds"


def test_fixture_c_is_a_tie_that_keeps_the_baseline(positions):
    """All three roots are worth 6, so no universal correction is available."""

    result = solved(positions["C"])
    assert result.status is SecurityStatus.EXACT_COMPLETE
    assert result.world_count == 24
    assert set(values_by_card(result).values()) == {6}
    assert card_to_code(result.selected_action.card) == "KC"


# ------------------------------------------------- strategy-fusion control


def test_worst_case_and_expectation_objectives_are_not_the_same_number():
    """The tiny reference from docs/search/tiny_exact_information_reference.md.

    Two equally likely worlds share one future observation. After A, world 0
    rewards X and world 1 rewards Y; B pays 0.65 everywhere. Choosing per world
    is worth 1.0 and is not implementable. One shared choice is worth 0.5 in
    expectation and 0.0 in the worst case, and both objectives pick B.
    """

    payoff = {("A", "X"): (1.0, 0.0), ("A", "Y"): (0.0, 1.0),
              ("B", "X"): (0.65, 0.65), ("B", "Y"): (0.65, 0.65)}

    def clairvoyant(root):
        return sum(max(payoff[(root, f)][w] for f in "XY") for w in (0, 1)) / 2

    def expectation(root):
        return max(sum(payoff[(root, f)][w] for w in (0, 1)) / 2 for f in "XY")

    def worst_case(root):
        return max(min(payoff[(root, f)][w] for w in (0, 1)) for f in "XY")

    assert clairvoyant("A") == 1.0
    assert expectation("A") == 0.5 and expectation("B") == 0.65
    assert worst_case("A") == 0.0 and worst_case("B") == 0.65
    # The two objectives disagree about A's value and must not be conflated.
    assert expectation("A") != worst_case("A")
    assert max("AB", key=expectation) == "B"
    assert max("AB", key=worst_case) == "B"


def brute_force_security(observation, budget, root_action, *, ceiling=50_000):
    """Enumerate *complete* own plans, then let every other seat answer.

    Independent of the module's recursion: a plan is a full assignment of one
    action to every own information key that any plan can reach, and only after
    fixing it is the worst leaf taken. Grouping partial plans instead would let
    a short branch and a long one be scored as different strategies, which
    understates the value; that mistake is what this reference exists to avoid.
    """

    seat = observation.observing_seat
    team = seat % 2
    support = build_support(observation, budget)
    assert support.status.value == "EXACT_COMPLETE"
    roots = tuple(
        apply_action(world.continuation.state, root_action)
        for world in support.research_worlds
    )

    options: dict[str, tuple] = {}

    def scout(nodes):
        if nodes[0].phase is not EnginePhase.TRICK_PLAY:
            return
        actor = nodes[0].current_actor
        if actor == seat:
            current = observation_for(nodes[0], seat)
            key = semantic_observation_key(current)
            if key not in options:
                common = set(current.legal_actions)
                for node in nodes[1:]:
                    common &= set(observation_for(node, seat).legal_actions)
                options[key] = tuple(sorted(common, key=lambda a: card_to_code(a.card)))
            for action in options[key]:
                scout(tuple(apply_action(node, action) for node in nodes))
            return
        union: dict = {}
        for node in nodes:
            for action in observation_for(node, actor).legal_actions:
                union.setdefault(action, []).append(node)
        for action, subset in union.items():
            scout(tuple(apply_action(node, action) for node in subset))

    scout(roots)
    keys = sorted(options)
    total = 1
    for key in keys:
        total *= len(options[key])
    if total > ceiling:
        pytest.skip(f"{total} complete plans exceeds the enumeration ceiling")

    best = None
    for combination in product(*(options[key] for key in keys)):
        plan = dict(zip(keys, combination))
        worst = -1

        def run(nodes):
            nonlocal worst
            if nodes[0].phase is not EnginePhase.TRICK_PLAY:
                worst = max(worst, max(node.team_tricks[team] for node in nodes))
                return
            actor = nodes[0].current_actor
            if actor == seat:
                key = semantic_observation_key(observation_for(nodes[0], seat))
                run(tuple(apply_action(node, plan[key]) for node in nodes))
                return
            union: dict = {}
            for node in nodes:
                for action in observation_for(node, actor).legal_actions:
                    union.setdefault(action, []).append(node)
            for action, subset in union.items():
                run(tuple(apply_action(node, action) for node in subset))

        run(roots)
        best = worst if best is None else min(best, worst)
    return best


def test_brute_force_agrees_on_the_small_position(positions):
    observation = observation_of(positions["B"])
    result = solved(positions["B"])
    for value in result.root_values:
        assert brute_force_security(observation, SupportBudget(), value.action) == (
            value.security_value
        ), f"disagreement on {value.action.card}"


# ------------------------------------------------------------- invariances


def test_a_different_hidden_layout_behind_one_observation_changes_nothing(positions):
    """Swapping the unseen hands must not move the decision: the observation is
    all the seat has, and the support is rebuilt from it either way."""

    observation = observation_of(positions["B"])
    support = build_support(observation, SupportBudget())
    assert support.world_count >= 2
    outcomes = []
    for world in support.research_worlds:
        rebuilt = observation_for(world.continuation.state, observation.observing_seat)
        assert semantic_observation_key(rebuilt) == semantic_observation_key(observation)
        answer = solve_security(rebuilt, SupportBudget())
        outcomes.append((values_by_card(answer), card_to_code(answer.selected_action.card)))
    assert len(set(map(str, outcomes))) == 1


def test_reordering_the_support_changes_no_value_or_action(positions):
    """Order of enumeration is not information; the recursion must not use it."""

    from tuppi_agents.void_lead import void_seeking_agents
    from tuppi_nolo.security import _Meter

    observation = observation_of(positions["B"])
    seat = observation.observing_seat
    support = build_support(observation, SupportBudget())
    agents = void_seeking_agents()
    root = observation.legal_actions[0]

    seen = set()
    for order in permutations(range(support.world_count)):
        meter = _Meter(SupportBudget().max_engine_transitions, 0)
        states = tuple(
            meter.step(support.research_worlds[i].continuation.state, root)
            for i in order
        )
        value, plan = _search(states, seat=seat, team=seat % 2, meter=meter, agents=agents)
        seen.add((value, tuple(sorted((k, card_to_code(a.card)) for k, a in plan.items()))))
    assert len(seen) == 1


# -------------------------------------------------------- negative controls


def test_a_deliberately_wrong_plan_entry_is_rejected(positions):
    """Swap one planned action for another legal one and the bound must fail."""

    state = positions["B"]
    observation = observation_of(state)
    result = solved(state)
    seat = observation.observing_seat

    swapped = None
    support = build_support(observation, SupportBudget())
    table = {entry.information_key: entry.action for entry in result.plan}
    for world in support.research_worlds:
        node = apply_action(world.continuation.state, result.selected_action)
        while node.phase is EnginePhase.TRICK_PLAY and node.current_actor != seat:
            node = apply_action(node, observation_for(node, node.current_actor).legal_actions[0])
        if node.phase is not EnginePhase.TRICK_PLAY:
            continue
        current = observation_for(node, seat)
        key = semantic_observation_key(current)
        alternatives = [a for a in current.legal_actions if a != table.get(key)]
        if key in table and alternatives:
            swapped = (key, alternatives[0])
            break
    assert swapped is not None, "no own node with an alternative to corrupt"

    key, wrong = swapped
    corrupted = tuple(
        PlanEntry(entry.information_key, wrong if entry.information_key == key else entry.action)
        for entry in result.plan
    )
    verdict = verify_certificate(
        observation, replace(result.certificate, plan=corrupted), SupportBudget()
    )
    assert verdict.status is not CheckStatus.EXACT_COMPLETE


def test_claiming_a_better_bound_than_achieved_is_disproved(positions):
    result = solved(positions["B"])
    observation = observation_of(positions["B"])
    optimistic = replace(
        result.certificate,
        claimed_terminal_bound=result.certificate.claimed_terminal_bound - 1,
    )
    verdict = verify_certificate(observation, optimistic, SupportBudget())
    assert verdict.status is CheckStatus.DISPROVED_BOUND


def test_dropping_a_real_choice_from_the_plan_is_rejected(positions):
    """Removing a *forced* entry is harmless, so the branch dropped here has to
    be one where the seat genuinely had alternatives."""

    state = positions["B"]
    observation = observation_of(state)
    result = solved(state)
    seat = observation.observing_seat
    table = {entry.information_key: entry.action for entry in result.plan}
    support = build_support(observation, SupportBudget())

    choices: set[str] = set()

    def walk(node):
        if node.phase is not EnginePhase.TRICK_PLAY:
            return
        current = observation_for(node, node.current_actor)
        if node.current_actor == seat:
            key = semantic_observation_key(current)
            if len(current.legal_actions) > 1 and key in table:
                choices.add(key)
            walk(apply_action(node, table.get(key, current.legal_actions[0])))
            return
        for candidate in current.legal_actions:
            walk(apply_action(node, candidate))

    for world in support.research_worlds:
        walk(apply_action(world.continuation.state, result.selected_action))
    assert choices, "no genuine own choice to remove"

    target = sorted(choices)[0]
    thinned = replace(
        result.certificate,
        plan=tuple(e for e in result.certificate.plan if e.information_key != target),
    )
    verdict = verify_certificate(observation, thinned, SupportBudget())
    assert verdict.status is CheckStatus.ILLEGAL_PLAN


@pytest.mark.parametrize("name", ["A", "B", "C"])
def test_too_small_a_budget_yields_search_budget_and_no_choice(positions, name):
    """Enough allowance to enumerate the support, not enough to search it."""

    observation = observation_of(positions[name])
    spent = build_support(observation, SupportBudget()).engine_transitions
    result = solve_security(observation, SupportBudget(max_engine_transitions=spent + 1))
    assert result.status is SecurityStatus.SEARCH_BUDGET
    assert result.selected_action is None
    assert result.root_values == ()
    assert result.certificate is None


def test_zero_budget_is_unresolved_rather_than_an_assertion(positions):
    observation = observation_of(positions["B"])
    result = solve_security(observation, SupportBudget(max_engine_transitions=0))
    assert result.status is not SecurityStatus.EXACT_COMPLETE
    assert result.selected_action is None


def test_a_non_acting_observer_is_invalid_input(positions):
    state = positions["B"]
    other = (state.current_actor + 1) % 4
    result = solve_security(observation_for(state, other), SupportBudget())
    assert result.status is SecurityStatus.INVALID_INPUT
    assert result.selected_action is None


def test_diagnostics_carry_no_private_material(positions):
    result = solved(positions["B"])
    text = repr(result.diagnostics())
    assert "assignment" not in text and "hands" not in text
    assert result.diagnostics()["control_model"].startswith("single_seat")
