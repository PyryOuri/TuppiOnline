"""Continuous rising-score transitions and terminal detection."""

from __future__ import annotations

from .errors import InvalidMatchScoreError, TerminalMatchError
from .model import DealScore, MatchScore, Team
from .scoring import validate_deal_score
from .seating import opposing_team, validate_team


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


def match_transition_value(score_after: MatchScore, root_team: Team) -> float:
    """Return the bounded root-team value of an authoritative score state.

    Terminal wins and losses are worth ``+1`` and ``-1``.  A nonterminal state
    is the root team's signed rising-score lead divided by the target.  This is
    a deterministic ordering of post-deal states, not an estimate of exact
    nonterminal match equity.
    """

    validated = _validate_match_score(score_after)
    root = validate_team(root_team)
    winner = match_winner(validated)
    if winner is not None:
        return 1.0 if winner is root else -1.0
    return (
        validated.for_team(root) - validated.for_team(opposing_team(root))
    ) / MATCH_TARGET


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
