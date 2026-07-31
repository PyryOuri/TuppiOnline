from __future__ import annotations

import pytest

from tuppi_rules import (
    Contract,
    DealScore,
    InvalidDealScoreError,
    InvalidDealStateError,
    InvalidTeamError,
    Team,
    score_nolo,
    score_rami,
)


@pytest.mark.parametrize("team0_tricks", range(14))
def test_nolo_scoring_exhausts_every_possible_split(team0_tricks: int) -> None:
    team1_tricks = 13 - team0_tricks
    result = score_nolo(team0_tricks, team1_tricks)
    expected_winner = Team.TEAM_0 if team0_tricks < team1_tricks else Team.TEAM_1
    winner_tricks = min(team0_tricks, team1_tricks)
    assert result.contract is Contract.NOLO
    assert result.winner_team is expected_winner
    assert winner_tricks <= 6
    assert result.points == 4 * (7 - winner_tricks)
    assert 4 <= result.points <= 28
    assert result.declaring_team is None
    assert result.stolen_rami is False


@pytest.mark.parametrize("declaring_team", list(Team))
@pytest.mark.parametrize("declaring_tricks", range(14))
def test_rami_scoring_exhausts_every_declarer_total(
    declaring_team: Team, declaring_tricks: int
) -> None:
    opponent_tricks = 13 - declaring_tricks
    totals = (
        (declaring_tricks, opponent_tricks)
        if declaring_team is Team.TEAM_0
        else (opponent_tricks, declaring_tricks)
    )
    result = score_rami(declaring_team, *totals)
    assert result.contract is Contract.RAMI
    assert result.declaring_team is declaring_team
    if declaring_tricks >= 7:
        assert result.winner_team is declaring_team
        assert result.points == 4 * (declaring_tricks - 6)
        assert result.stolen_rami is False
    else:
        assert result.winner_team is not declaring_team
        assert result.points == 8 * (opponent_tricks - 6)
        assert result.stolen_rami is True


def test_rami_six_seven_boundary_and_zero_trick_loss() -> None:
    stolen = score_rami(Team.TEAM_0, 6, 7)
    made = score_rami(Team.TEAM_0, 7, 6)
    shutout = score_rami(Team.TEAM_0, 0, 13)
    assert (stolen.winner_team, stolen.points) == (Team.TEAM_1, 8)
    assert (made.winner_team, made.points) == (Team.TEAM_0, 4)
    assert (shutout.winner_team, shutout.points) == (Team.TEAM_1, 56)


@pytest.mark.parametrize(
    ("team0", "team1"),
    [(-1, 14), (14, -1), (6, 6), (7, 7), (True, 12), (1.5, 11.5)],
)
def test_invalid_scoring_totals_are_rejected(team0, team1) -> None:
    with pytest.raises(InvalidDealStateError):
        score_nolo(team0, team1)


@pytest.mark.parametrize("team", [0, 1, True, "0", None])
def test_invalid_rami_team_identifiers_are_rejected(team) -> None:
    with pytest.raises(InvalidTeamError):
        score_rami(team, 7, 6)


def test_deal_score_constructor_rejects_inconsistent_or_raw_fields() -> None:
    with pytest.raises(InvalidDealScoreError, match="winner"):
        DealScore(
            contract=Contract.NOLO,
            winner_team=0,  # type: ignore[arg-type]
            points=4,
            team_tricks=(6, 7),
            declaring_team=None,
            stolen_rami=False,
        )
    with pytest.raises(InvalidDealScoreError, match="formula"):
        DealScore(
            contract=Contract.NOLO,
            winner_team=Team.TEAM_0,
            points=8,
            team_tricks=(6, 7),
            declaring_team=None,
            stolen_rami=False,
        )


@pytest.mark.parametrize(
    ("team0", "team1"),
    [(-1, 14), (14, -1), (6, 6), (7, 7), (True, 12), (1.5, 11.5)],
)
def test_rami_directly_rejects_invalid_scoring_totals(team0, team1) -> None:
    with pytest.raises(InvalidDealStateError):
        score_rami(Team.TEAM_0, team0, team1)
