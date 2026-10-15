"""N05: what a trick difference is actually worth on the scoreboard.

A guarantee expressed in tricks is not yet a claim about the match. Rising
scoring makes the mapping lossy in both directions: a down team's win erases
the leader's total regardless of margin, and an up team past 52 has won
regardless of overshoot. So two lines that differ by a trick can land on the
same score state, and a strict trick difference is then **not** a score gain.

This module maps attainable own-team totals to authoritative score states and
labels the resulting claim. It fits nothing: no equity table, no opponent
model, no posterior over worlds. ``score_state_proxy`` is a deterministic
ordering of post-deal states and is deliberately not named match equity.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from fractions import Fraction

from tuppi_rules import (
    MatchScore,
    Team,
    match_transition_value,
    score_nolo,
    transition_rising_score,
)
from tuppi_rules.match import MATCH_TARGET, is_match_terminal, match_winner

TRICKS_PER_DEAL = 13


class ClaimLabel(str, Enum):
    """Kept apart from resolution status: a resolved search can still tie."""

    UNIVERSAL = "UNIVERSAL"
    SECURITY_ONLY = "SECURITY_ONLY"
    TIE = "TIE"
    UNCLASSIFIED = "UNCLASSIFIED"


@dataclass(frozen=True, slots=True)
class ScoreOutcome:
    """One attainable own-team total, priced by the authoritative rules."""

    own_total: int
    team_tricks: tuple[int, int]
    winner_team: Team
    points: int
    score_before: MatchScore
    score_after: MatchScore
    terminal: bool
    proxy: Fraction

    @property
    def state(self) -> tuple[int, int]:
        """The authoritative score pair, overshoot included."""

        return (self.score_after.team0, self.score_after.team1)

    @property
    def settled_state(self):
        """The state as an *outcome*, which is what a claim may compare.

        Winning by four past the target and winning by twelve are the same
        result: the match is over and the surplus buys nothing. Comparing the
        raw pairs would report a preference between them, which is exactly the
        overshoot claim the rules forbid.
        """

        if self.terminal:
            return ("terminal", int(self.winner_team))
        return self.state


def score_state_proxy(score_after: MatchScore, root_team: Team) -> Fraction:
    """Exact rational counterpart of ``match_transition_value``.

    Terminal win or loss is ``+1``/``-1``; otherwise the root team's signed
    rising-score lead over the target. A deterministic ordering of post-deal
    states, **not** an estimate of nonterminal match equity, and never to be
    called one.
    """

    winner = match_winner(score_after)
    if winner is not None:
        return Fraction(1) if winner is root_team else Fraction(-1)
    opponent = Team.TEAM_1 if root_team is Team.TEAM_0 else Team.TEAM_0
    return Fraction(
        score_after.for_team(root_team) - score_after.for_team(opponent), MATCH_TARGET
    )


def outcome_for_total(own_total: int, *, seat: int, score_before: MatchScore) -> ScoreOutcome:
    """Price one attainable own-team final total from one seat's orientation.

    The split is reconstructed in the correct seat orientation rather than
    assumed to be Team 0's, and the losing side's points never enter: only the
    winner's total drives ``score_nolo``.
    """

    if type(own_total) is not int or not 0 <= own_total <= TRICKS_PER_DEAL:
        raise ValueError("own_total must be an integer number of tricks in 0..13")
    if type(seat) is not int or seat not in range(4):
        raise ValueError("seat must be an integer in 0..3")
    if is_match_terminal(score_before):
        raise ValueError("a terminal match cannot accept another deal")

    root_team = Team(seat % 2)
    opponent_total = TRICKS_PER_DEAL - own_total
    if root_team is Team.TEAM_0:
        team0, team1 = own_total, opponent_total
    else:
        team0, team1 = opponent_total, own_total

    deal_score = score_nolo(team0, team1)
    score_after = transition_rising_score(score_before, deal_score)
    return ScoreOutcome(
        own_total=own_total,
        team_tricks=(team0, team1),
        winner_team=deal_score.winner_team,
        points=deal_score.points,
        score_before=score_before,
        score_after=score_after,
        terminal=is_match_terminal(score_after),
        proxy=score_state_proxy(score_after, root_team),
    )


def score_states(
    own_totals, *, seat: int, score_before: MatchScore
) -> tuple[ScoreOutcome, ...]:
    """Price every attainable total, ordered by total for reproducibility."""

    return tuple(
        outcome_for_total(total, seat=seat, score_before=score_before)
        for total in sorted(set(own_totals))
    )


def distinct_states(outcomes) -> frozenset:
    """Outcome classes, so terminal overshoot cannot masquerade as a gain."""

    return frozenset(outcome.settled_state for outcome in outcomes)


def worst_case_proxy(outcomes) -> Fraction:
    """The value a security choice maximises: the least favourable leaf."""

    return min(outcome.proxy for outcome in outcomes)


@dataclass(frozen=True, slots=True)
class ClaimAssessment:
    label: ClaimLabel
    reason: str
    candidate_states: frozenset
    baseline_states: frozenset
    candidate_worst_proxy: Fraction | None = None
    baseline_worst_proxy: Fraction | None = None


def classify_claim(
    *,
    seat: int,
    score_before: MatchScore,
    candidate_totals,
    baseline_totals,
    candidate_upper_bound: int | None = None,
    baseline_lower_bound: int | None = None,
) -> ClaimAssessment:
    """Label a candidate against the baseline it would replace.

    ``UNIVERSAL`` needs the strong condition from the packet's definitions: the
    candidate's certified upper trick bound no greater than the baseline's
    lower bound over *all* legal continuations, with a feasible strict case.
    ``SECURITY_ONLY`` is a better worst case under one stated control model and
    promises nothing against an opponent who errs. ``TIE`` is reserved for
    identical score states — a strict trick difference that prices the same is
    not a score gain, which is the whole point of running this comparison.
    """

    candidate = score_states(candidate_totals, seat=seat, score_before=score_before)
    baseline = score_states(baseline_totals, seat=seat, score_before=score_before)
    candidate_set = distinct_states(candidate)
    baseline_set = distinct_states(baseline)
    candidate_worst = worst_case_proxy(candidate)
    baseline_worst = worst_case_proxy(baseline)

    def assess(label, reason):
        return ClaimAssessment(
            label, reason, candidate_set, baseline_set, candidate_worst, baseline_worst
        )

    if candidate_set == baseline_set:
        return assess(
            ClaimLabel.TIE,
            "identical score states; a trick difference that prices the same is not a gain",
        )
    if (
        candidate_upper_bound is not None
        and baseline_lower_bound is not None
        and candidate_upper_bound <= baseline_lower_bound
        and max(baseline_totals) > candidate_upper_bound
    ):
        return assess(
            ClaimLabel.UNIVERSAL,
            "certified upper bound at or below the baseline's all-continuation "
            "lower bound, with a strictly better case available",
        )
    if candidate_worst > baseline_worst:
        return assess(
            ClaimLabel.SECURITY_ONLY,
            "better worst case under the stated control model only; no claim "
            "against an opponent who errs",
        )
    return assess(
        ClaimLabel.UNCLASSIFIED,
        "no score-state improvement established under the stated model",
    )


def duck_sensitivity(q: Fraction) -> Fraction:
    """B's analytical scenario: a duck totals 3 with probability ``q``, else 5.

    Returns the duck's expected own tricks, ``5 - 2q``. The take-and-club line
    yields 4 deterministically, so the two cross at ``q = 1/2``. These are
    **assumed scenario probabilities**, stated to show what would have to be
    believed for the duck to be preferred in expectation. Nothing here is
    fitted, observed, or a posterior, and a better expectation at some ``q``
    does not upgrade a SECURITY_ONLY claim.
    """

    weight = Fraction(q)
    if not 0 <= weight <= 1:
        raise ValueError("q must be a probability in 0..1")
    return 5 - 2 * weight


def sensitivity_table(points=(Fraction(0), Fraction(1, 2), Fraction(1))) -> tuple:
    """(q, duck expectation, deterministic take line, which is preferred)."""

    rows = []
    for q in points:
        duck = duck_sensitivity(q)
        take = Fraction(4)
        if duck < take:
            preferred = "duck"
        elif duck > take:
            preferred = "take"
        else:
            preferred = "tie"
        rows.append((Fraction(q), duck, take, preferred))
    return tuple(rows)


def proxy_agrees_with_reference(score_after: MatchScore, root_team: Team) -> bool:
    """The exact rational must agree with the repository's float ordering."""

    return float(score_state_proxy(score_after, root_team)) == match_transition_value(
        score_after, root_team
    )
