"""N05 checks: tricks priced into authoritative score states, and the labels
that keep a trick difference from being reported as a score gain.

Every score endpoint is mirrored to a Team-1 seat, so a team-indexing mistake
cannot pass by being right about Team 0 only.
"""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path

import pytest

from tuppi_engine import observation_for
from tuppi_rules import MatchScore, Team, card_to_code, match_transition_value
from tuppi_rules.errors import RulesError
from tuppi_nolo.certificates import all_action_bounds
from tuppi_nolo.fixtures import load_fixtures
from tuppi_nolo.outcomes import (
    ClaimLabel,
    classify_claim,
    duck_sensitivity,
    outcome_for_total,
    proxy_agrees_with_reference,
    score_state_proxy,
    score_states,
    sensitivity_table,
    worst_case_proxy,
)
from tuppi_nolo.security import solve_security
from tuppi_nolo.support import SupportBudget

PACKET = Path(__file__).resolve().parents[2] / "docs/nolo/tasks"
BASELINE = {"A": "QD", "B": "3C", "C": "KC"}


@pytest.fixture(scope="module")
def positions():
    return {f.id: f.replay() for f in load_fixtures(PACKET / "fixtures.json")}


def state_of(total, *, seat, before):
    return outcome_for_total(total, seat=seat, score_before=MatchScore(*before)).state


# ------------------------------------------------------- the exact endpoints


@pytest.mark.parametrize(
    "before, seven, nine",
    [((0, 0), (0, 4), (0, 12)), ((0, 40), (0, 44), (0, 52))],
)
def test_fixture_a_score_consequences(before, seven, nine):
    assert state_of(7, seat=2, before=before) == seven
    assert state_of(9, seat=2, before=before) == nine


def test_fixture_a_when_its_team_is_up_is_a_tie_for_this_margin():
    """A down-team win erases the leader whatever the margin, so 7 and 9 land
    on the same state and the trick difference buys nothing here."""

    assert state_of(7, seat=2, before=(40, 0)) == (0, 0)
    assert state_of(9, seat=2, before=(40, 0)) == (0, 0)


@pytest.mark.parametrize(
    "before, expected",
    [
        ((0, 0), [(12, 0), (8, 0), (4, 0)]),
        ((40, 0), [(52, 0), (48, 0), (44, 0)]),
        ((0, 40), [(0, 0), (0, 0), (0, 0)]),
    ],
)
def test_fixture_b_score_consequences(before, expected):
    assert [state_of(t, seat=0, before=before) for t in (4, 5, 6)] == expected


def test_up_at_48_every_winning_margin_is_terminal_with_no_overshoot_preference():
    outcomes = score_states((4, 5, 6), seat=0, score_before=MatchScore(48, 0))
    assert all(o.terminal for o in outcomes)
    assert {o.proxy for o in outcomes} == {Fraction(1)}


@pytest.mark.parametrize("seat", [1, 3])
def test_team_one_seats_are_mirrored_not_assumed(seat):
    """The same totals must price from the other partnership's orientation."""

    assert state_of(7, seat=seat, before=(0, 0)) == (4, 0)
    assert state_of(9, seat=seat, before=(0, 0)) == (12, 0)
    assert [state_of(t, seat=seat, before=(0, 0)) for t in (4, 5, 6)] == [
        (0, 12),
        (0, 8),
        (0, 4),
    ]


def test_the_split_uses_the_seat_orientation_and_the_winner_only():
    """Team totals are reconstructed for the acting seat's partnership, and the
    losing side's points never enter the formula."""

    team0 = outcome_for_total(4, seat=0, score_before=MatchScore(0, 0))
    team1 = outcome_for_total(4, seat=1, score_before=MatchScore(0, 0))
    assert team0.team_tricks == (4, 9) and team0.winner_team is Team.TEAM_0
    assert team1.team_tricks == (9, 4) and team1.winner_team is Team.TEAM_1
    assert team0.points == team1.points == 12


# ------------------------------------------------------------------- proxy


@pytest.mark.parametrize(
    "score, team",
    [
        ((0, 0), Team.TEAM_0), ((12, 0), Team.TEAM_0), ((0, 12), Team.TEAM_0),
        ((44, 0), Team.TEAM_1), ((52, 0), Team.TEAM_0), ((0, 52), Team.TEAM_0),
        ((48, 0), Team.TEAM_1),
    ],
)
def test_exact_proxy_agrees_with_the_repository_reference(score, team):
    assert proxy_agrees_with_reference(MatchScore(*score), team)


def test_terminal_states_are_plus_or_minus_one_and_ignore_overshoot():
    assert score_state_proxy(MatchScore(52, 0), Team.TEAM_0) == Fraction(1)
    assert score_state_proxy(MatchScore(60, 0), Team.TEAM_0) == Fraction(1)
    assert score_state_proxy(MatchScore(60, 0), Team.TEAM_1) == Fraction(-1)
    assert isinstance(score_state_proxy(MatchScore(8, 0), Team.TEAM_0), Fraction)


def test_the_proxy_is_monotone_in_avoiding_own_tricks():
    outcomes = score_states(range(0, 7), seat=0, score_before=MatchScore(0, 0))
    proxies = [o.proxy for o in outcomes]
    assert proxies == sorted(proxies, reverse=True), "fewer own tricks must not price worse"


def test_worst_case_proxy_selects_the_least_favourable_leaf():
    outcomes = score_states((4, 6), seat=0, score_before=MatchScore(0, 0))
    assert worst_case_proxy(outcomes) == min(o.proxy for o in outcomes)


def test_a_terminal_match_cannot_be_priced_again():
    with pytest.raises((ValueError, RulesError)):
        outcome_for_total(4, seat=0, score_before=MatchScore(52, 0))


# -------------------------------------------------------------- the labels


def assessed(positions, name, before=(0, 0)):
    state = positions[name]
    observation = observation_for(state, state.current_actor)
    result = solve_security(
        observation, SupportBudget(), verification_budget=SupportBudget()
    )
    baseline = next(
        a for a in observation.legal_actions if card_to_code(a.card) == BASELINE[name]
    )
    candidate_totals = sorted({o.own_tricks for o in result.verification.outcomes})
    baseline_totals = sorted(
        {o.own_tricks for o in all_action_bounds(observation, baseline, SupportBudget()).outcomes}
    )
    return classify_claim(
        seat=observation.observing_seat,
        score_before=MatchScore(*before),
        candidate_totals=candidate_totals,
        baseline_totals=baseline_totals,
        candidate_upper_bound=max(candidate_totals),
        baseline_lower_bound=min(baseline_totals),
    )


def test_fixture_a_is_a_universal_improvement(positions):
    verdict = assessed(positions, "A")
    assert verdict.label is ClaimLabel.UNIVERSAL
    assert verdict.candidate_states == {(0, 4)}


def test_fixture_b_is_security_only_not_universal(positions):
    """Its upper bound is not under the baseline's lower bound, so the stronger
    label is unavailable however good the worst case looks."""

    verdict = assessed(positions, "B")
    assert verdict.label is ClaimLabel.SECURITY_ONLY
    assert verdict.candidate_worst_proxy > verdict.baseline_worst_proxy


def test_fixture_c_is_a_tie(positions):
    verdict = assessed(positions, "C")
    assert verdict.label is ClaimLabel.TIE
    assert verdict.candidate_states == verdict.baseline_states


def test_fixture_b_becomes_a_tie_when_its_team_is_down(positions):
    """Down at 40 every winning line resets to 0-0, so the same decision that
    is SECURITY_ONLY at love prices identically here."""

    verdict = assessed(positions, "B", before=(0, 40))
    assert verdict.label is ClaimLabel.TIE
    assert verdict.candidate_states == verdict.baseline_states == {(0, 0)}


def test_terminal_overshoot_is_not_a_preference(positions):
    """Up at 48 every winning margin ends the match, so lines that differ by
    tricks must classify as a tie rather than preferring the larger surplus."""

    verdict = assessed(positions, "B", before=(48, 0))
    assert verdict.label is ClaimLabel.TIE
    assert verdict.candidate_states == verdict.baseline_states == {("terminal", 0)}


def test_raw_score_pairs_are_still_available_even_though_claims_collapse_them():
    outcomes = score_states((4, 6), seat=0, score_before=MatchScore(48, 0))
    assert {o.state for o in outcomes} == {(60, 0), (52, 0)}
    assert {o.settled_state for o in outcomes} == {("terminal", 0)}


def test_a_strict_trick_difference_with_one_score_state_is_not_a_gain():
    verdict = classify_claim(
        seat=0,
        score_before=MatchScore(0, 40),
        candidate_totals=[4],
        baseline_totals=[6],
        candidate_upper_bound=4,
        baseline_lower_bound=6,
    )
    assert verdict.label is ClaimLabel.TIE


def test_no_improvement_is_left_unclassified_rather_than_upgraded():
    verdict = classify_claim(
        seat=0,
        score_before=MatchScore(0, 0),
        candidate_totals=[6],
        baseline_totals=[4],
        candidate_upper_bound=6,
        baseline_lower_bound=4,
    )
    assert verdict.label is ClaimLabel.UNCLASSIFIED


# --------------------------------------------------------- B's sensitivity


def test_duck_sensitivity_is_five_minus_two_q():
    assert duck_sensitivity(Fraction(0)) == 5
    assert duck_sensitivity(Fraction(1, 2)) == 4
    assert duck_sensitivity(Fraction(1)) == 3


def test_the_lines_cross_at_one_half():
    rows = {q: preferred for q, _duck, _take, preferred in sensitivity_table()}
    assert rows[Fraction(0)] == "take"
    assert rows[Fraction(1, 2)] == "tie"
    assert rows[Fraction(1)] == "duck"


def test_a_favourable_scenario_probability_does_not_promote_the_label(positions):
    """At q=1 the duck wins in expectation, and the security claim is unchanged:
    an assumed probability is not evidence about worst cases."""

    assert duck_sensitivity(Fraction(1)) < 4
    assert assessed(positions, "B").label is ClaimLabel.SECURITY_ONLY


def test_scenario_probabilities_are_rejected_outside_zero_to_one():
    for bad in (Fraction(-1, 10), Fraction(11, 10)):
        with pytest.raises(ValueError):
            duck_sensitivity(bad)
