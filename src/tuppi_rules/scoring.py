"""Exhaustive deal-scoring formulas for NOLO and RAMI."""

from __future__ import annotations

from .errors import InvalidDealScoreError, InvalidDealStateError
from .model import Contract, DealScore, Team
from .seating import opposing_team, validate_team


def validate_team_trick_totals(
    team0_tricks: int, team1_tricks: int
) -> tuple[int, int]:
    for label, value in (("team0", team0_tricks), ("team1", team1_tricks)):
        if type(value) is not int or value < 0 or value > 13:
            raise InvalidDealStateError(
                f"{label} trick total must be an integer in 0..13"
            )
    if team0_tricks + team1_tricks != 13:
        raise InvalidDealStateError(
            "deal scoring requires team trick totals that sum to 13"
        )
    return (team0_tricks, team1_tricks)


def score_nolo(team0_tricks: int, team1_tricks: int) -> DealScore:
    totals = validate_team_trick_totals(team0_tricks, team1_tricks)
    winner = Team.TEAM_0 if team0_tricks < team1_tricks else Team.TEAM_1
    winner_tricks = totals[winner.value]
    points = 4 * (7 - winner_tricks)
    return DealScore(
        contract=Contract.NOLO,
        winner_team=winner,
        points=points,
        team_tricks=totals,
        declaring_team=None,
        stolen_rami=False,
    )


def score_rami(
    declaring_team: Team, team0_tricks: int, team1_tricks: int
) -> DealScore:
    validated_team = validate_team(declaring_team)
    totals = validate_team_trick_totals(team0_tricks, team1_tricks)
    declaring_tricks = totals[validated_team.value]
    if declaring_tricks >= 7:
        winner = validated_team
        points = 4 * (declaring_tricks - 6)
        stolen = False
    else:
        winner = opposing_team(validated_team)
        opponent_tricks = totals[winner.value]
        points = 8 * (opponent_tricks - 6)
        stolen = True
    return DealScore(
        contract=Contract.RAMI,
        winner_team=winner,
        points=points,
        team_tricks=totals,
        declaring_team=validated_team,
        stolen_rami=stolen,
    )


def score_rami_for_declarer(
    declarer: int, team0_tricks: int, team1_tricks: int
) -> DealScore:
    """Derive the declaring partnership from the first RAMI declarer's seat."""

    from .seating import team_for_seat

    return score_rami(team_for_seat(declarer), team0_tricks, team1_tricks)


def validate_deal_score(score: DealScore) -> DealScore:
    """Revalidate a score at a downstream trust boundary."""

    if not isinstance(score, DealScore):
        raise InvalidDealScoreError(
            "deal_score must come from a complete-deal scoring function"
        )
    try:
        return DealScore(
            contract=score.contract,
            winner_team=score.winner_team,
            points=score.points,
            team_tricks=score.team_tricks,
            declaring_team=score.declaring_team,
            stolen_rami=score.stolen_rami,
        )
    except (AttributeError, InvalidDealScoreError) as exc:
        raise InvalidDealScoreError("deal_score contains invalid fields") from exc
