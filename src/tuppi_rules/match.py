"""Continuous rising-score transitions and terminal detection."""

from __future__ import annotations

from .errors import InvalidMatchScoreError, TerminalMatchError
from .model import DealScore, MatchScore, Team
from .scoring import validate_deal_score


MATCH_TARGET = 52


def _validate_match_score(score: MatchScore) -> MatchScore:
    if not isinstance(score, MatchScore):
        raise InvalidMatchScoreError("score must be a MatchScore value")
    return score


def is_match_terminal(score: MatchScore) -> bool:
    validated = _validate_match_score(score)
    return validated.team0 >= MATCH_TARGET or validated.team1 >= MATCH_TARGET


def match_winner(score: MatchScore) -> Team | None:
    validated = _validate_match_score(score)
    if validated.team0 >= MATCH_TARGET:
        return Team.TEAM_0
    if validated.team1 >= MATCH_TARGET:
        return Team.TEAM_1
    return None


def transition_rising_score(current: MatchScore, deal_score: DealScore) -> MatchScore:
    validated = _validate_match_score(current)
    deal_score = validate_deal_score(deal_score)
    if is_match_terminal(validated):
        raise TerminalMatchError("a terminal match cannot accept another deal score")

    winner = deal_score.winner_team
    up_team = validated.up_team
    if up_team is None:
        if winner is Team.TEAM_0:
            return MatchScore(deal_score.points, 0)
        return MatchScore(0, deal_score.points)
    if winner is up_team:
        if up_team is Team.TEAM_0:
            return MatchScore(validated.team0 + deal_score.points, 0)
        return MatchScore(0, validated.team1 + deal_score.points)
    return MatchScore(0, 0)
