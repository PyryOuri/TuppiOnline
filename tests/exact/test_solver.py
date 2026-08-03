"""The exact solver, cross-checked against an independent brute-force reference.

Two defects were found by exactly this cross-check while the solver was written,
and both have a named regression test below:

* the root move loop maximized own tricks unconditionally, which silently
  inverted every NOLO answer;
* the equivalent-card reduction ignored cards already in the current trick, so it
  collapsed two cards of which one beat the trick and the other did not.

Neither was visible from the solver's own output. That is why the reference
implementation is kept: it is slow, unpruned, and obviously correct.
"""

from __future__ import annotations

import pytest

from tuppi_engine import EnginePhase
from tuppi_exact.errors import SolverBudgetError, SolverError
from tuppi_exact.solver import (
    DEFAULT_MAXIMUM_TRICKS_REMAINING,
    _equivalence_groups,
    _legal_indices,
    deal_outcome_for_split,
    is_within_exact_range,
    match_score_after_split,
    match_utility_from_score,
    match_utility_is_monotone,
    monotonicity_certificate,
    optimal_play_actions,
    solve_continuation,
    solve_late_game,
    team0_prefers_more_tricks,
)
from tuppi_rules import (
    Contract,
    MatchScore,
    TRICKS_PER_DEAL,
    Team,
    card_from_code,
    card_to_index,
    team_for_seat,
)

from .conftest import walk_deal


# ---------------------------------------------------------------- reference


def reference_value(state) -> int:
    """Unpruned minimax on team-0's final trick count. Obviously correct, slow."""

    team0_maximizes = state.contract is Contract.RAMI

    def recurse(hands, trick, actor, team0_tricks):
        if not any(hands):
            return team0_tricks
        hand = hands[actor]
        if trick:
            led = trick[0][1].suit
            candidates = [card for card in hand if card.suit is led] or list(hand)
        else:
            candidates = list(hand)
        values = []
        for card in candidates:
            following = list(hands)
            following[actor] = tuple(item for item in hand if item != card)
            extended = trick + ((actor, card),)
            if len(extended) == 4:
                led = extended[0][1].suit
                winner = max(
                    (play for play in extended if play[1].suit is led),
                    key=lambda play: play[1].rank.value,
                )[0]
                values.append(
                    recurse(
                        tuple(following),
                        (),
                        winner,
                        team0_tricks
                        + (1 if team_for_seat(winner) is Team.TEAM_0 else 0),
                    )
                )
            else:
                values.append(
                    recurse(tuple(following), extended, (actor + 1) % 4, team0_tricks)
                )
        maximizing = (team_for_seat(actor) is Team.TEAM_0) == team0_maximizes
        return max(values) if maximizing else min(values)

    return recurse(
        tuple(tuple(hand) for hand in state.hands),
        tuple((play.seat, play.card) for play in state.current_trick),
        state.current_actor,
        state.team_tricks[0],
    )


def reference_action_values(state) -> dict:
    """The exact value of every legal card, by unpruned search."""

    actor = state.current_actor
    hand = state.hands[actor]
    trick = tuple((play.seat, play.card) for play in state.current_trick)
    if trick:
        led = trick[0][1].suit
        candidates = [card for card in hand if card.suit is led] or list(hand)
    else:
        candidates = list(hand)
    values = {}
    for card in candidates:
        following = list(state.hands)
        following[actor] = tuple(item for item in hand if item != card)

        class _Stub:
            contract = state.contract
            hands = tuple(tuple(item) for item in following)
            current_trick = ()
            current_actor = 0
            team_tricks = (0, 0)

        extended = trick + ((actor, card),)
        if len(extended) == 4:
            led = extended[0][1].suit
            winner = max(
                (play for play in extended if play[1].suit is led),
                key=lambda play: play[1].rank.value,
            )[0]
            _Stub.current_actor = winner
            _Stub.team_tricks = (
                state.team_tricks[0]
                + (1 if team_for_seat(winner) is Team.TEAM_0 else 0),
                0,
            )
            _Stub.current_trick = ()
        else:
            _Stub.current_actor = (actor + 1) % 4
            _Stub.team_tricks = (state.team_tricks[0], 0)

            class _Play:
                def __init__(self, seat, card):
                    self.seat = seat
                    self.card = card

            _Stub.current_trick = tuple(
                _Play(seat, item) for seat, item in extended
            )
        values[card] = reference_value(_Stub)
    return values


# ------------------------------------------------------------------- scoring


def test_deal_outcome_matches_the_ruleset_tables():
    for tricks, points in ((6, 4), (5, 8), (0, 28)):
        score = deal_outcome_for_split(
            contract=Contract.NOLO, declarer=None, team0_tricks=tricks
        )
        assert score.points == points
        assert score.winner_team is Team.TEAM_0
    for tricks, points in ((7, 4), (13, 28)):
        score = deal_outcome_for_split(
            contract=Contract.RAMI, declarer=0, team0_tricks=tricks
        )
        assert score.points == points
        assert score.winner_team is Team.TEAM_0
    stolen = deal_outcome_for_split(
        contract=Contract.RAMI, declarer=0, team0_tricks=0
    )
    assert stolen.points == 56
    assert stolen.stolen_rami is True
    assert stolen.winner_team is Team.TEAM_1


def test_both_contracts_reduce_to_one_trick_count_direction():
    assert team0_prefers_more_tricks(Contract.RAMI) is True
    assert team0_prefers_more_tricks(Contract.NOLO) is False


def test_match_utility_discards_overshoot():
    """Reaching 52 and reaching 56 must be worth the same."""

    exact = match_score_after_split(
        contract=Contract.RAMI,
        declarer=0,
        team0_tricks=7,
        starting_score=MatchScore(48, 0),
    )
    over = match_score_after_split(
        contract=Contract.RAMI,
        declarer=0,
        team0_tricks=13,
        starting_score=MatchScore(48, 0),
    )
    assert exact.as_tuple() == (52, 0)
    assert over.as_tuple() == (76, 0)
    assert match_utility_from_score(exact, Team.TEAM_0) == match_utility_from_score(
        over, Team.TEAM_0
    ) == (1, 0)


def test_a_down_team_win_is_worth_the_same_at_any_margin():
    small = match_score_after_split(
        contract=Contract.NOLO,
        declarer=None,
        team0_tricks=6,
        starting_score=MatchScore(0, 20),
    )
    large = match_score_after_split(
        contract=Contract.NOLO,
        declarer=None,
        team0_tricks=0,
        starting_score=MatchScore(0, 20),
    )
    assert small.as_tuple() == (0, 0)
    assert large.as_tuple() == (0, 0)
    assert match_utility_from_score(small, Team.TEAM_0) == match_utility_from_score(
        large, Team.TEAM_0
    )


def test_monotonicity_certificate_is_exhaustive_and_holds():
    certificate = monotonicity_certificate()
    assert certificate["holds"] is True
    assert certificate["failures"] == []
    assert certificate["cases_checked"] >= 200
    assert "Perfect information" in certificate["scope"]
    for contract in Contract:
        declarers = (None,) if contract is Contract.NOLO else (0, 1, 2, 3)
        for declarer in declarers:
            for team in Team:
                assert match_utility_is_monotone(
                    contract=contract,
                    declarer=declarer,
                    starting_score=MatchScore(48, 0),
                    team=team,
                )


# -------------------------------------------------------------------- search


def test_solver_agrees_with_the_reference_at_every_late_position(late_positions):
    checked = {"NOLO": 0, "RAMI": 0}
    for position in late_positions:
        solution = solve_late_game(position.deal_state, maximum_tricks_remaining=4)
        assert solution.optimal_team0_tricks_final == reference_value(
            position.deal_state
        )
        checked[solution.contract.value] += 1
    assert sum(checked.values()) > 40


def test_every_action_value_agrees_with_the_reference(late_positions):
    verified = 0
    for position in late_positions[:40]:
        solution = solve_late_game(position.deal_state, maximum_tricks_remaining=4)
        for card, value in reference_action_values(position.deal_state).items():
            assert solution.value_for(card).team0_tricks_final == value
            verified += 1
    assert verified > 60


def test_nolo_minimizes_own_tricks_regression(late_positions):
    """Regression: the root loop once maximized own tricks in NOLO too."""

    nolo = [
        position
        for position in late_positions
        if position.deal_state.contract is Contract.NOLO
    ]
    if not nolo:
        pytest.skip("this fixture produced no NOLO late positions")
    for position in nolo:
        solution = solve_late_game(position.deal_state, maximum_tricks_remaining=4)
        assert solution.own_team_prefers_more_tricks is False
        achieved = [
            action.own_team_tricks_final for action in solution.actions
        ]
        assert solution.optimal_own_team_tricks_final == min(achieved)


def test_rami_maximizes_own_tricks(late_positions):
    rami = [
        position
        for position in late_positions
        if position.deal_state.contract is Contract.RAMI
    ]
    if not rami:
        pytest.skip("this fixture produced no RAMI late positions")
    for position in rami:
        solution = solve_late_game(position.deal_state, maximum_tricks_remaining=4)
        assert solution.own_team_prefers_more_tricks is True
        achieved = [action.own_team_tricks_final for action in solution.actions]
        assert solution.optimal_own_team_tricks_final == max(achieved)


def test_equivalence_reduction_counts_the_current_trick_regression():
    """Regression: a card in the current trick separates two ranks.

    The acting seat holds only 5H and 7H of hearts. Nobody else holds 6H because
    it is already on the table, so an equivalence rule that looked only at the
    other hands would collapse 5H and 7H - even though 7H beats the trick and 5H
    does not.
    """

    hands = (
        frozenset({card_to_index(card_from_code("5H")), card_to_index(card_from_code("7H"))}),
        frozenset({card_to_index(card_from_code("2S"))}),
        frozenset({card_to_index(card_from_code("3S"))}),
        frozenset({card_to_index(card_from_code("4S"))}),
    )
    trick = ((3, card_to_index(card_from_code("6H"))),)
    legal = _legal_indices(hands[0], trick)
    assert len(legal) == 2
    groups = _equivalence_groups(legal, hands, 0, trick)
    assert len(groups) == 2, "a separating card in the current trick was ignored"
    empty_trick_groups = _equivalence_groups(
        _legal_indices(hands[0], ()), hands, 0, ()
    )
    assert len(empty_trick_groups) == 1, "with 6H out of play the two are equivalent"


def test_equivalent_cards_are_reported_and_all_optimal(late_positions):
    for position in late_positions[:30]:
        solution = solve_late_game(position.deal_state, maximum_tricks_remaining=4)
        for action in solution.actions:
            assert action.card in action.equivalent_cards
            for card in action.equivalent_cards:
                assert solution.value_for(card) is action
        for card in solution.optimal_cards:
            assert solution.is_optimal(card)
            assert solution.regret_in_tricks(card) == 0
            assert solution.match_utility_regret(card) == 0


def test_regret_is_nonnegative_and_zero_only_at_the_optimum(late_positions):
    for position in late_positions[:30]:
        solution = solve_late_game(position.deal_state, maximum_tricks_remaining=4)
        for action in solution.actions:
            assert solution.regret_in_tricks(action.card) >= 0
            assert solution.regret_in_deal_points(action.card) >= 0
            if action.card not in solution.optimal_cards:
                assert solution.regret_in_tricks(action.card) > 0


def test_optimal_play_actions_are_engine_actions(late_positions):
    position = late_positions[0]
    actions = optimal_play_actions(position.deal_state, maximum_tricks_remaining=4)
    assert actions
    for action in actions:
        assert action.seat == position.deal_state.current_actor


def test_the_solver_refuses_rather_than_estimating():
    for position in walk_deal():
        state = position.deal_state
        if state.phase is not EnginePhase.TRICK_PLAY:
            continue
        if 13 - len(state.completed_tricks) <= 2:
            continue
        assert not is_within_exact_range(state, maximum_tricks_remaining=1)
        with pytest.raises(SolverBudgetError):
            solve_late_game(state, maximum_tricks_remaining=1)
        return
    raise AssertionError("no trick-play position was reached")


def test_the_node_budget_is_a_hard_error():
    for position in walk_deal():
        state = position.deal_state
        if state.phase is not EnginePhase.TRICK_PLAY:
            continue
        if 13 - len(state.completed_tricks) < 4:
            continue
        with pytest.raises(SolverBudgetError):
            solve_late_game(state, maximum_tricks_remaining=13, node_budget=1)
        return
    raise AssertionError("no deep trick-play position was reached")


def test_the_solver_rejects_a_showing_position():
    for position in walk_deal():
        if position.deal_state.phase is EnginePhase.SHOWING:
            with pytest.raises(SolverError):
                solve_late_game(position.deal_state)
            return
    raise AssertionError("no showing position was reached")


def test_the_solver_rejects_malformed_arguments(late_positions):
    state = late_positions[0].deal_state
    with pytest.raises(SolverError):
        solve_late_game(state, maximum_tricks_remaining=0)
    with pytest.raises(SolverError):
        solve_late_game(state, node_budget=0)
    with pytest.raises(SolverError):
        solve_late_game("not a state")  # type: ignore[arg-type]
    with pytest.raises(SolverError):
        solve_continuation("not a continuation")  # type: ignore[arg-type]


def test_solution_data_is_canonical(late_positions):
    solution = solve_late_game(
        late_positions[0].deal_state, maximum_tricks_remaining=4
    )
    data = solution.to_data()
    assert data["is_exact"] is True
    assert data["schema_version"] == "tuppi.exact.late_game_solution.v1"
    assert data["algorithm_id"] == "tuppi.exact.trick_count_minimax_v1"
    assert data["optimal_own_team_tricks_final"] in range(TRICKS_PER_DEAL + 1)
    assert len(data["actions"]) == len(solution.actions)


def test_solving_a_sampled_continuation_is_exact_for_that_world():
    from tuppi_exact.constraints import HardConstraintModel
    from tuppi_exact.continuation import hypothetical_continuation
    from tuppi_exact.sampling import UniformFeasibleSampler

    solved = 0
    for position in walk_deal():
        state = position.deal_state
        if state.phase is not EnginePhase.TRICK_PLAY:
            continue
        if 13 - len(state.completed_tricks) > 4:
            continue
        model = HardConstraintModel.build(position.observation)
        if not model.unknown_cards:
            continue
        sampler = UniformFeasibleSampler.build(model, seed="solve-sampled")
        for assignment in sampler.sample(3):
            continuation = hypothetical_continuation(position.observation, assignment)
            solution = solve_continuation(continuation, maximum_tricks_remaining=4)
            assert solution.is_exact is True
            assert solution.acting_seat == position.observation.observing_seat
            assert solution.optimal_team0_tricks_final == reference_value(
                continuation.state
            )
            solved += 1
    assert solved > 5
