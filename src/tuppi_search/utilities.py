"""Versioned, root-team-oriented utility adapters.

Every PIMC value in Phase 5C is produced by exactly one of these adapters, and
every adapter scores the *same* value type: a :class:`DealOutcomeSummary`. That is
deliberate and structural. A completed rollout and an exact-tail solver call both
reduce to ``(contract, declarer, team0 tricks, starting score, root team)``, so
"the solver and the rollout use compatible utility semantics" is not a property
that has to be maintained by hand and tested for drift - the two paths cannot
disagree, because there is only one scoring function and only one input type.

Orientation
-----------

Nothing here assumes Team 0 is the agent's team. Every summary carries its
``root_team``, and every adapter converts from the engine's team-0-relative trick
count into a value for that team. Tests cover all four root seats.

The three adapters
------------------

``deal_result_v1``
    Signed official deal points for the root team, scaled to ``[-1, 1]``. The
    honest currency for a *deal*, and the wrong one for a match: it pays the down
    team for a margin the rising score throws away.

``match_transition_v1``
    The authoritative post-deal rising-score transition, scored so that winning
    the match dominates, a larger own rise beats a smaller one, and a reset is
    neutral-to-bad. This is the adapter the registered Phase 5C agents use,
    because Phase 5A established the match as the endpoint and Phase 5B showed
    that deal margin is partly fictitious currency.

    **It is not exact nonterminal match equity.** A real equity would need a model
    of the deals still to come. It is a documented, bounded, monotone ordering of
    post-deal states, and it is chosen for exactly that.

``trick_split_v1``
    The root team's trick share, signed by contract. Diagnostic and
    compatibility-baseline only; it ignores the 6/7 boundary that decides who
    actually wins, so it must never be the registered utility.

Range and monotonicity
----------------------

Every adapter returns a value in ``[-1, 1]``. ``match_transition_v1`` is
additionally *order-compatible* with Phase 5B's
:func:`tuppi_exact.match_utility_from_score` lexicographic ordering, which
:mod:`tests.search.test_utilities` verifies exhaustively over every reachable
post-deal score. Keeping the two orderings identical is what lets Phase 5C's
scalar averages and Phase 5B's exact per-decision verdicts be read side by side.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from tuppi_engine import DealState, EnginePhase
from tuppi_exact import deal_outcome_for_split, match_score_after_split
from tuppi_rules import (
    Contract,
    DealScore,
    MATCH_TARGET,
    MatchScore,
    TRICKS_PER_DEAL,
    Team,
    is_match_terminal,
    opposing_team,
    team_for_seat,
)

from .errors import UtilityError


UTILITY_SCHEMA_VERSION = "tuppi.search.utility.v1"

#: The largest deal award the ruleset can produce: a 13-trick stolen RAMI.
MAXIMUM_DEAL_POINTS = 56


class UtilityId(StrEnum):
    """The versioned utility adapters. The identifier is behaviourally material."""

    DEAL_RESULT_V1 = "tuppi.search.utility.deal_result.v1"
    MATCH_TRANSITION_V1 = "tuppi.search.utility.match_transition.v1"
    TRICK_SPLIT_V1 = "tuppi.search.utility.trick_split.v1"


class OutcomeSource(StrEnum):
    """How a deal outcome was obtained. Recorded, never used for scoring."""

    ROLLOUT = "rollout"
    EXACT_TAIL = "exact_tail"


@dataclass(frozen=True, slots=True)
class DealOutcomeSummary:
    """The complete input to every utility adapter.

    A rollout that played all thirteen tricks and an exact-tail solve that stopped
    early both produce this, which is why they cannot drift apart.
    """

    contract: Contract
    declarer: int | None
    team0_tricks: int
    starting_score: MatchScore
    root_team: Team
    source: OutcomeSource
    tricks_simulated: int
    solver_nodes: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.contract, Contract):
            raise UtilityError("contract must be a Contract value")
        if self.contract is Contract.NOLO and self.declarer is not None:
            raise UtilityError("a NOLO deal has no declarer")
        if self.contract is Contract.RAMI and (
            type(self.declarer) is not int or self.declarer not in range(4)
        ):
            raise UtilityError("a RAMI deal requires a declarer seat")
        if type(self.team0_tricks) is not int or self.team0_tricks not in range(
            TRICKS_PER_DEAL + 1
        ):
            raise UtilityError("team0_tricks must be an integer in 0..13")
        if not isinstance(self.starting_score, MatchScore):
            raise UtilityError("starting_score must be a MatchScore")
        if not isinstance(self.root_team, Team):
            raise UtilityError("root_team must be a Team value")
        if not isinstance(self.source, OutcomeSource):
            raise UtilityError("source must be an OutcomeSource value")
        if type(self.tricks_simulated) is not int or self.tricks_simulated < 0:
            raise UtilityError("tricks_simulated must be a nonnegative integer")
        if type(self.solver_nodes) is not int or self.solver_nodes < 0:
            raise UtilityError("solver_nodes must be a nonnegative integer")

    @property
    def root_team_tricks(self) -> int:
        if self.root_team is Team.TEAM_0:
            return self.team0_tricks
        return TRICKS_PER_DEAL - self.team0_tricks

    @property
    def deal_score(self) -> DealScore:
        return deal_outcome_for_split(
            contract=self.contract,
            declarer=self.declarer,
            team0_tricks=self.team0_tricks,
        )

    @property
    def match_score_after(self) -> MatchScore:
        return match_score_after_split(
            contract=self.contract,
            declarer=self.declarer,
            team0_tricks=self.team0_tricks,
            starting_score=self.starting_score,
        )

    @property
    def root_team_wins_deal(self) -> bool:
        return self.deal_score.winner_team is self.root_team

    def to_data(self) -> dict[str, object]:
        score = self.deal_score
        after = self.match_score_after
        return {
            "contract": self.contract.value,
            "deal_points": score.points,
            "deal_winner_team": score.winner_team.value,
            "declarer": self.declarer,
            "match_score_after": list(after.as_tuple()),
            "match_terminal": is_match_terminal(after),
            "root_team": self.root_team.value,
            "root_team_tricks": self.root_team_tricks,
            "root_team_wins_deal": self.root_team_wins_deal,
            "source": self.source.value,
            "starting_score": list(self.starting_score.as_tuple()),
            "team0_tricks": self.team0_tricks,
            "tricks_simulated": self.tricks_simulated,
        }


def summary_from_completed_deal(
    state: DealState, *, root_seat: int, source: OutcomeSource, tricks_simulated: int
) -> DealOutcomeSummary:
    """Build a summary from a rollout that played the deal to completion."""

    if not isinstance(state, DealState):
        raise UtilityError("summary_from_completed_deal requires a DealState")
    if not state.complete:
        raise UtilityError("the deal is not complete")
    if state.contract is None or state.deal_score is None:
        raise UtilityError("a completed deal must carry a contract and a score")
    if type(root_seat) is not int or root_seat not in range(4):
        raise UtilityError("root_seat must be an integer in 0..3")
    return DealOutcomeSummary(
        contract=state.contract,
        declarer=state.declarer,
        team0_tricks=state.team_tricks[0],
        starting_score=state.starting_score,
        root_team=team_for_seat(root_seat),
        source=source,
        tricks_simulated=tricks_simulated,
    )


# ------------------------------------------------------------------- adapters


def _deal_result_value(summary: DealOutcomeSummary) -> float:
    score = summary.deal_score
    signed = score.points if score.winner_team is summary.root_team else -score.points
    return signed / MAXIMUM_DEAL_POINTS


def _match_transition_value(summary: DealOutcomeSummary) -> float:
    after = summary.match_score_after
    own = after.for_team(summary.root_team)
    opponent = after.for_team(opposing_team(summary.root_team))
    if is_match_terminal(after):
        return 1.0 if own >= opponent else -1.0
    return (own - opponent) / MATCH_TARGET


def _trick_split_value(summary: DealOutcomeSummary) -> float:
    own = summary.root_team_tricks
    centred = (own - TRICKS_PER_DEAL / 2) / (TRICKS_PER_DEAL / 2)
    # NOLO rewards *avoiding* tricks, so the raw share must be inverted or the
    # adapter would score every NOLO position backwards.
    return centred if summary.contract is Contract.RAMI else -centred


_ADAPTERS = {
    UtilityId.DEAL_RESULT_V1: _deal_result_value,
    UtilityId.MATCH_TRANSITION_V1: _match_transition_value,
    UtilityId.TRICK_SPLIT_V1: _trick_split_value,
}


def utility_value(utility_id: UtilityId, summary: DealOutcomeSummary) -> float:
    """Score one deal outcome for the root team under the named adapter."""

    if not isinstance(utility_id, UtilityId):
        raise UtilityError("utility_id must be a UtilityId value")
    if not isinstance(summary, DealOutcomeSummary):
        raise UtilityError("utility_value requires a DealOutcomeSummary")
    value = _ADAPTERS[utility_id](summary)
    if not -1.0 <= value <= 1.0:
        raise UtilityError(
            f"{utility_id.value} produced {value}, outside its documented range"
        )
    return value


def utility_range(utility_id: UtilityId) -> tuple[float, float]:
    """The documented finite range of one adapter."""

    if not isinstance(utility_id, UtilityId):
        raise UtilityError("utility_id must be a UtilityId value")
    return (-1.0, 1.0)


def utility_description(utility_id: UtilityId) -> str:
    if utility_id is UtilityId.DEAL_RESULT_V1:
        return (
            "Signed official deal points for the root team, divided by 56. Honest "
            "for a deal; wrong for a match, because it pays the down team for a "
            "margin the rising score discards."
        )
    if utility_id is UtilityId.MATCH_TRANSITION_V1:
        return (
            "The authoritative post-deal rising-score transition: +1 for winning "
            "the match, -1 for losing it, and the signed rise difference over 52 "
            "otherwise. A documented bounded ordering of post-deal states, not "
            "exact nonterminal match equity."
        )
    return (
        "The root team's trick share, signed by contract. Diagnostic only: it "
        "ignores the 6/7 boundary that decides who wins the deal."
    )


def is_registerable(utility_id: UtilityId) -> bool:
    """Whether an adapter may be the utility of a registered Phase 5C agent.

    ``trick_split_v1`` is excluded on purpose. It is available for ablation and
    for comparison against Phase 4's trick-oriented scoring, but an agent that
    maximized it would be maximizing something the ruleset does not reward.
    """

    return utility_id is not UtilityId.TRICK_SPLIT_V1


def utility_catalogue() -> tuple[dict[str, object], ...]:
    """Canonical documentation of every adapter, for reports and schemas."""

    return tuple(
        {
            "description": utility_description(item),
            "is_registerable": is_registerable(item),
            "range": list(utility_range(item)),
            "schema_version": UTILITY_SCHEMA_VERSION,
            "utility_id": item.value,
        }
        for item in UtilityId
    )


def exact_tail_summary(
    *,
    contract: Contract,
    declarer: int | None,
    team0_tricks: int,
    starting_score: MatchScore,
    root_seat: int,
    tricks_simulated: int,
    solver_nodes: int,
) -> DealOutcomeSummary:
    """Build a summary from an exact-tail solver value.

    Identical in type and interpretation to a rollout summary, which is the whole
    point: the tail changes the *continuation policy*, never the currency.
    """

    if type(root_seat) is not int or root_seat not in range(4):
        raise UtilityError("root_seat must be an integer in 0..3")
    return DealOutcomeSummary(
        contract=contract,
        declarer=declarer,
        team0_tricks=team0_tricks,
        starting_score=starting_score,
        root_team=team_for_seat(root_seat),
        source=OutcomeSource.EXACT_TAIL,
        tricks_simulated=tricks_simulated,
        solver_nodes=solver_nodes,
    )


def require_trick_play(state: DealState) -> DealState:
    if not isinstance(state, DealState):
        raise UtilityError("require_trick_play needs a DealState")
    if state.phase is not EnginePhase.TRICK_PLAY:
        raise UtilityError("the exact tail applies only during trick play")
    return state
