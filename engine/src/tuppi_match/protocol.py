"""The definitive complete-match duplicate protocol.

For each independent stream fixture the protocol plays two legs:

``Leg E``
    The candidate partnership occupies seats 0 and 2; the opponent takes 1 and 3.
``Leg O``
    The candidate partnership occupies seats 1 and 3; the opponent takes 0 and 2.

Both legs start at the same score, use the same initial dealer, read the *same*
extensible deterministic stream, rotate the dealer by ``project_target_v1``, and
run until one partnership reaches at least 52. They may consume different
prefix lengths, and the longer leg simply keeps going: nothing is truncated to
the shorter one.

Two properties are load-bearing and are asserted by the test suite rather than
assumed:

* the legs read the same stream, so the shorter leg's consumed deals are a
  prefix of the longer leg's;
* the match reference handed to the engine - and therefore visible in every
  observation - is derived from an ordinal, never from the stream, the bank, or
  the seed. A sealed fixture identity can never reach a policy.
"""

from __future__ import annotations

import time

from tuppi_engine import (
    EnginePhase,
    Agent,
    apply_match_action,
    begin_explicit_deal,
    create_match,
    match_observation_for,
    play_active_deal,
)
from tuppi_engine.errors import EngineError
from tuppi_rules import MATCH_TARGET, Contract, MatchScore, Team

from .errors import ExecutionError
from .manifest import MatchComparison
from .records import (
    LegIdentity,
    LegRecord,
    LegStatus,
    PairRecord,
    ScoreStateOccupancy,
)
from .streams import MatchStream


CENSORED_KIND = "censored_infrastructure"


def seat_assignment(leg: LegIdentity) -> tuple[bool, bool, bool, bool]:
    """Return, per seat, whether the candidate occupies it."""

    if leg is LegIdentity.EVEN:
        return (True, False, True, False)
    return (False, True, False, True)


def candidate_engine_team(leg: LegIdentity) -> Team:
    """Which engine team the candidate is in this leg."""

    return Team.TEAM_0 if leg is LegIdentity.EVEN else Team.TEAM_1


def match_reference(*, leg: LegIdentity, ordinal: int) -> str:
    """Build a fixture-independent engine label.

    The reference is visible inside every ``PlayerObservation``, so it must not
    encode the stream, the bank, or the seed. An ordinal is enough for the
    engine and reveals nothing about a sealed fixture.
    """

    if type(ordinal) is not int or ordinal < 0:
        raise ExecutionError("match ordinal must be a nonnegative integer")
    return f"cm-{leg.value.lower()}-{ordinal:06d}"


def run_leg(
    *,
    stream: MatchStream,
    comparison: MatchComparison,
    leg: LegIdentity,
    safety_cap: int,
    ordinal: int,
    build_candidate,
    build_opponent,
) -> LegRecord:
    """Play one leg to natural termination, or record structured censoring."""

    if type(safety_cap) is not int or safety_cap <= 0:
        raise ExecutionError("safety_cap must be a positive integer")
    occupies = seat_assignment(leg)
    candidate_team = candidate_engine_team(leg)
    opponent_team = Team.TEAM_1 if candidate_team is Team.TEAM_0 else Team.TEAM_0
    agents: list[Agent] = []
    for seat in range(4):
        builder = build_candidate if occupies[seat] else build_opponent
        agents.append(builder(seat))
    if len({id(agent) for agent in agents}) != 4:
        raise ExecutionError("each seat requires a distinct runtime agent object")

    starting = MatchScore(*comparison.starting_score)
    state = create_match(
        initial_score=starting,
        initial_dealer=stream.initial_dealer,
        match_ref=match_reference(leg=leg, ordinal=ordinal),
    )

    consumed: list[str] = []
    resets = rami_deals = nolo_deals = successful_rami = stolen_rami = 0
    declarers = [0, 0, 0, 0]
    candidate_points = opponent_points = 0
    candidate_tricks = opponent_tricks = 0
    at_table = candidate_up = candidate_down = 0
    action_count = 0
    failure_kind: str | None = None
    failure_detail: str | None = None
    started = time.perf_counter()

    try:
        while not state.terminal and len(consumed) < safety_cap:
            stream_deal = stream.deal(len(consumed))
            state = begin_explicit_deal(
                state, stream_deal.explicit_deal(state.dealer)
            )
            while state.phase in (EnginePhase.SHOWING, EnginePhase.TRICK_PLAY):
                actor = state.current_actor
                if actor is None:  # pragma: no cover - engine invariant
                    raise ExecutionError("active deal has no current actor")
                observation = match_observation_for(state, actor)
                state = apply_match_action(
                    state, agents[actor].choose_action(observation)
                )
                action_count += 1
            consumed.append(stream_deal.deal_content_id)

            result = state.completed_deals[-1].public_result
            before = result.score_before
            if before.up_team is None:
                at_table += 1
            elif before.up_team is candidate_team:
                candidate_up += 1
            else:
                candidate_down += 1
            if before.up_team is not None and result.score_after.as_tuple() == (0, 0):
                resets += 1
            if result.contract is Contract.RAMI:
                rami_deals += 1
                if result.deal_score.stolen_rami:
                    stolen_rami += 1
                else:
                    successful_rami += 1
            else:
                nolo_deals += 1
            if result.declarer is not None:
                declarers[result.declarer] += 1
            if result.deal_score.winner_team is candidate_team:
                candidate_points += result.deal_score.points
            else:
                opponent_points += result.deal_score.points
            candidate_tricks += result.team_tricks[candidate_team.value]
            opponent_tricks += result.team_tricks[opponent_team.value]
    except (EngineError, ExecutionError) as exc:
        failure_kind = type(exc).__name__
        failure_detail = str(exc)[:400]

    duration = time.perf_counter() - started
    if failure_kind is not None:
        status = LegStatus.FAILED
    elif state.terminal:
        status = LegStatus.COMPLETE
    else:
        status = LegStatus.CENSORED_INFRASTRUCTURE
        failure_kind = CENSORED_KIND
        failure_detail = (
            f"reached the {safety_cap}-deal infrastructure safety cap without a "
            "partnership reaching 52; this is not a draw and not a policy result"
        )

    score = state.score.as_tuple()
    if status is LegStatus.COMPLETE:
        winner = 0 if score[0] >= MATCH_TARGET else 1
        even_won = winner == 0
        candidate_won = winner == candidate_team.value
    else:
        winner = None
        even_won = None
        candidate_won = None

    return LegRecord.build(
        comparison_id=comparison.comparison_id,
        stream_id=stream.stream_id,
        leg=leg,
        initial_dealer=stream.initial_dealer,
        safety_cap=safety_cap,
        status=status,
        deals_consumed=len(consumed),
        consumed_deal_ids=tuple(consumed),
        final_score=score,
        winning_engine_team=winner,
        even_partnership_won=even_won,
        candidate_won=candidate_won,
        resets=resets,
        rami_deals=rami_deals,
        nolo_deals=nolo_deals,
        successful_rami=successful_rami,
        stolen_rami=stolen_rami,
        declarer_seat_counts=tuple(declarers),
        candidate_deal_points=candidate_points,
        opponent_deal_points=opponent_points,
        candidate_tricks=candidate_tricks,
        opponent_tricks=opponent_tricks,
        immediate_completion=status is LegStatus.COMPLETE and len(consumed) == 1,
        occupancy=ScoreStateOccupancy(
            deals_at_table=at_table,
            deals_candidate_up=candidate_up,
            deals_candidate_down=candidate_down,
        ),
        action_count=action_count,
        duration_seconds=duration,
        failure_kind=failure_kind,
        failure_detail=failure_detail,
    )


def run_pair(
    *,
    stream: MatchStream,
    comparison: MatchComparison,
    safety_cap: int,
    ordinal: int,
    build_candidate,
    build_opponent,
) -> PairRecord:
    """Play both complementary legs of one stream and join them into a pair."""

    even = run_leg(
        stream=stream,
        comparison=comparison,
        leg=LegIdentity.EVEN,
        safety_cap=safety_cap,
        ordinal=ordinal,
        build_candidate=build_candidate,
        build_opponent=build_opponent,
    )
    odd = run_leg(
        stream=stream,
        comparison=comparison,
        leg=LegIdentity.ODD,
        safety_cap=safety_cap,
        ordinal=ordinal,
        build_candidate=build_candidate,
        build_opponent=build_opponent,
    )
    return PairRecord.build(
        comparison_id=comparison.comparison_id,
        stream_id=stream.stream_id,
        leg_even=even,
        leg_odd=odd,
    )
