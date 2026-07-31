from __future__ import annotations

import pytest

from tuppi_rules import (
    InvalidDealScoreError,
    InvalidMatchScoreError,
    MatchScore,
    Team,
    TerminalMatchError,
    is_match_terminal,
    match_winner,
    score_nolo,
    score_rami,
    transition_rising_score,
)


def test_table_state_awards_points_to_either_winner() -> None:
    team0_four = score_nolo(6, 7)
    team1_eight = score_nolo(8, 5)
    assert transition_rising_score(MatchScore(), team0_four) == MatchScore(4, 0)
    assert transition_rising_score(MatchScore(), team1_eight) == MatchScore(0, 8)


def test_up_team_win_adds_points() -> None:
    assert transition_rising_score(
        MatchScore(20, 0), score_nolo(5, 8)
    ) == MatchScore(28, 0)
    assert transition_rising_score(
        MatchScore(0, 20), score_nolo(8, 5)
    ) == MatchScore(0, 28)


def test_down_team_win_resets_without_receiving_points() -> None:
    assert transition_rising_score(
        MatchScore(20, 0), score_nolo(8, 5)
    ) == MatchScore(0, 0)
    assert transition_rising_score(
        MatchScore(0, 20), score_nolo(5, 8)
    ) == MatchScore(0, 0)


def test_48_plus_four_and_eight_end_at_52_or_56() -> None:
    fifty_two = transition_rising_score(MatchScore(48, 0), score_nolo(6, 7))
    fifty_six = transition_rising_score(MatchScore(48, 0), score_nolo(5, 8))
    assert fifty_two == MatchScore(52, 0)
    assert fifty_six == MatchScore(56, 0)
    assert is_match_terminal(fifty_two)
    assert is_match_terminal(fifty_six)
    assert match_winner(fifty_two) is Team.TEAM_0
    assert match_winner(fifty_six) is Team.TEAM_0


def test_down_team_56_point_stolen_rami_still_only_resets() -> None:
    stolen = score_rami(Team.TEAM_0, 0, 13)
    assert stolen.winner_team is Team.TEAM_1
    assert stolen.points == 56
    assert transition_rising_score(MatchScore(48, 0), stolen) == MatchScore(0, 0)


def test_terminal_detection_uses_greater_than_or_equal() -> None:
    assert not is_match_terminal(MatchScore(51, 0))
    assert is_match_terminal(MatchScore(52, 0))
    assert is_match_terminal(MatchScore(56, 0))
    assert is_match_terminal(MatchScore(0, 100))


@pytest.mark.parametrize(
    ("team0", "team1"),
    [(-1, 0), (0, -1), (1, 1), (True, 0), (0, False), (1.0, 0)],
)
def test_invalid_match_scores_are_rejected(team0, team1) -> None:
    with pytest.raises(InvalidMatchScoreError):
        MatchScore(team0, team1)


def test_terminal_match_rejects_additional_transition() -> None:
    with pytest.raises(TerminalMatchError, match="terminal"):
        transition_rising_score(MatchScore(52, 0), score_nolo(6, 7))


def test_transition_rejects_unvalidated_deal_score() -> None:
    with pytest.raises(InvalidDealScoreError):
        transition_rising_score(MatchScore(), object())  # type: ignore[arg-type]
