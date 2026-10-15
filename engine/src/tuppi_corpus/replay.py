"""Deriving decisions from a stored deal.

The corpus stores no decision rows.  A decision is a pure function of a deal
plus a ply, so this module reconstructs them by replaying the stored deal
through the engine, and that is the *only* supported path from a stored hand to
anything a model may read.

That is a privacy mechanism, not a convenience.  ``DealRecord.hands`` is
research-private, and a pipeline that built features from it directly would
quietly break the observation boundary every Phase 4, 5 and 6 result rests on.
Here, each yielded observation comes from ``match_observation_for``, so it
carries exactly what the acting seat was entitled to see, and
``tests/corpus/test_privacy.py`` plants sentinel cards in the other three hands
and fails if any of them reaches a derived decision.

Cost, measured: a deal replays in about 16 ms on the trusted path and yields
about 55 decisions, so one core sustains roughly 3 400 decisions per second and
eight loader processes about 27 000 - well beyond what a GTX 1070 needs at this
model scale (``docs/database/phase7_charter.md`` §3.4).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

from tuppi_engine import (
    Action,
    EnginePhase,
    ExplicitDeal,
    PlayCardAction,
    PlayerObservation,
    ShowAction,
    apply_match_action,
    begin_explicit_deal,
    create_match,
    match_observation_for,
)
from tuppi_engine.trusted import trusted_transitions
from tuppi_rules import MatchScore

from .errors import CorpusIntegrityError
from .records import DealRecord


REPLAY_SCHEMA_VERSION = "tuppi.corpus.replay.v1"


@dataclass(frozen=True, slots=True)
class Decision:
    """One derived decision: what the seat could see, and what it did.

    ``return_deal_points`` is the primary training target - signed deal points
    for the acting partnership - and it is the same endpoint the RAMI/NOLO
    threshold experiment and the valuation A/B work both chose.  Terminal match
    win/loss is deliberately not the primary label: a mean 33-deal match credits
    one bit to about 1 810 actions.
    """

    ply: int
    seat: int
    phase: EnginePhase
    observation: PlayerObservation
    action: Action
    legal_action_count: int
    tricks_remaining: int
    return_deal_points: int
    return_team_tricks: int


def _match_ref(deal: DealRecord) -> str:
    return f"tdcr-{deal.match_row:09d}-{deal.deal_number:04d}"


def replay_deal(deal: DealRecord, *, trusted: bool = True) -> Iterator[Decision]:
    """Yield every decision of one stored deal, in order.

    Reconstructs the deal's own match context from ``score_before`` and
    ``dealer``.  The deal number and references differ from the original run's,
    which cannot matter: ``tests/agents/test_conformance.py`` proves a selected
    action is independent of ``match_ref``.
    """

    context = trusted_transitions() if trusted else _null_context()
    with context:
        state = create_match(
            initial_score=MatchScore(*deal.score_before),
            initial_dealer=deal.dealer,
            match_ref=_match_ref(deal),
        )
        state = begin_explicit_deal(
            state, ExplicitDeal(dealer=deal.dealer, hands=deal.hands)
        )
        signed = [
            deal.deal_points[0] - deal.deal_points[1],
            deal.deal_points[1] - deal.deal_points[0],
        ]
        shows = list(deal.shows)
        plays = list(deal.plays)
        ply = 0
        played = 0
        while state.phase in (EnginePhase.SHOWING, EnginePhase.TRICK_PLAY):
            seat = state.current_actor
            observation = match_observation_for(state, seat)
            if state.phase is EnginePhase.SHOWING:
                if not shows:
                    raise CorpusIntegrityError("stored deal ran out of show actions")
                card, contract = shows.pop(0)
                action: Action = ShowAction(
                    seat=seat, shown_card=card, declared_contract=contract
                )
            else:
                if not plays:
                    raise CorpusIntegrityError("stored deal ran out of played cards")
                action = PlayCardAction(seat=seat, card=plays.pop(0))
                played += 1
            team = seat % 2
            yield Decision(
                ply=ply,
                seat=seat,
                phase=state.phase,
                observation=observation,
                action=action,
                legal_action_count=len(observation.legal_actions),
                tricks_remaining=13 - (played - 1) // 4 - 1
                if state.phase is EnginePhase.TRICK_PLAY
                else 13,
                return_deal_points=signed[team],
                return_team_tricks=deal.team_tricks[team],
            )
            state = apply_match_action(state, action)
            ply += 1
        if shows or plays:
            raise CorpusIntegrityError("stored deal has unconsumed actions")


class _null_context:
    def __enter__(self) -> None:
        return None

    def __exit__(self, *_exc: object) -> bool:
        return False


def verify_deal(deal: DealRecord) -> None:
    """Replay a stored deal and require the recorded outcome to reappear.

    This is the check that makes the "derive, do not store" decision safe: if a
    stored deal did not in fact produce the outcome stored beside it, the record
    is wrong and every label derived from it would be wrong too.  Runs through
    the **authoritative** path, so it also revalidates the state machine.
    """

    decisions = tuple(replay_deal(deal, trusted=False))
    if not decisions:
        raise CorpusIntegrityError("stored deal produced no decisions")
    if len(decisions) != len(deal.shows) + len(deal.plays):
        raise CorpusIntegrityError("replayed decision count disagrees with the record")

    state = create_match(
        initial_score=MatchScore(*deal.score_before),
        initial_dealer=deal.dealer,
        match_ref=_match_ref(deal),
    )
    state = begin_explicit_deal(state, ExplicitDeal(dealer=deal.dealer, hands=deal.hands))
    for decision in decisions:
        state = apply_match_action(state, decision.action)
    if not state.completed_deals:
        raise CorpusIntegrityError("replayed deal did not complete")
    result = state.completed_deals[-1].public_result
    if result.contract is not deal.contract:
        raise CorpusIntegrityError("replayed contract disagrees with the record")
    if tuple(result.team_tricks) != deal.team_tricks:
        raise CorpusIntegrityError("replayed team tricks disagree with the record")
    if tuple(trick.winner for trick in result.completed_tricks) != deal.trick_winners:
        raise CorpusIntegrityError("replayed trick winners disagree with the record")
    if (result.score_after.team0, result.score_after.team1) != deal.score_after:
        raise CorpusIntegrityError("replayed score disagrees with the record")


__all__ = ["REPLAY_SCHEMA_VERSION", "Decision", "replay_deal", "verify_deal"]
