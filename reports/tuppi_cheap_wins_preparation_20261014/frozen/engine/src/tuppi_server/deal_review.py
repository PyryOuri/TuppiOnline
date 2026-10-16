"""After-deal review: a seat's own decisions in a completed deal, re-decided by a bot.

The server replays the completed deal and hands a *reviewer* each decision the
requesting seat took, with exactly the observation that seat had at the time.
The reviewer answers with findings: decisions where it would clearly have
done otherwise, what it would have done and what the difference is estimated
to cost. The reviewer is pluggable (``RoomManager.deal_reviewer``); the
server builds and validates the envelope itself:

* only the requesting seat's decisions are sent to the reviewer and returned;
* every recommended action must be one of that seat's own legal actions at
  that decision, so a finding cannot carry a card the seat did not hold;
* the decision kind and trick index are derived from the observation here,
  not taken from the reviewer.

Nothing here depends on how the reviewer searches.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import math
import threading
from typing import Protocol

from tuppi_engine import (
    Action,
    EnginePhase,
    PlayerObservation,
    action_to_data,
    apply_match_action,
    begin_explicit_deal,
    create_match,
    match_observation_for,
)
from tuppi_engine.trusted import trusted_transitions

DEAL_REVIEW_SCHEMA_VERSION = "tuppi.analysis.deal_review.v1"
DECISION_KINDS = frozenset({
    "bid", "sooli_offer", "sooli_give", "sooli_return",
    "lead", "follow", "discard", "sooli_lead", "sooli_follow", "sooli_discard",
})


class DealReviewError(ValueError):
    """A reviewer response or review request failed validation."""


@dataclass(frozen=True, slots=True)
class SeatDecision:
    decision_index: int
    event_index: int
    observation: PlayerObservation
    action: Action


@dataclass(frozen=True, slots=True)
class ReviewFinding:
    decision_index: int
    recommended: Action
    cost: float
    standard_error: float


class DealReviewer(Protocol):
    reviewer_id: str

    def review_decisions(self, decisions: Sequence[SeatDecision]) -> Sequence[ReviewFinding]:
        """Findings for the clear mistakes among ``decisions`` (one seat, in order)."""


def decision_kind(observation: PlayerObservation) -> tuple[str, int | None]:
    phase = observation.phase
    if phase is EnginePhase.SHOWING:
        return "bid", None
    if phase is EnginePhase.SOOLI_OFFER:
        return "sooli_offer", None
    if phase is EnginePhase.SOOLI_GIVE:
        return "sooli_give", None
    if phase is EnginePhase.SOOLI_RETURN:
        return "sooli_return", None
    sooli = phase is EnginePhase.SOOLI_PLAY
    tricks = observation.sooli_tricks if sooli else observation.completed_tricks
    current = observation.sooli_current_trick if sooli else observation.current_trick
    prefix = "sooli_" if sooli else ""
    if not current:
        return prefix + "lead", len(tricks)
    led = current[0].card.suit
    follows = any(card.suit is led for card in observation.own_hand)
    return prefix + ("follow" if follows else "discard"), len(tricks)


def seat_decisions(runner, *, deal_number: int, seat: int) -> list[SeatDecision]:
    """Replay the runner's accepted actions and collect ``seat``'s decisions in a deal."""

    deals = list(runner._deals)
    records = sorted(list(runner._accepted_actions), key=lambda item: item.action_index)
    from tuppi_engine.serialization import action_from_data

    out: list[SeatDecision] = []
    with trusted_transitions():
        state = create_match(
            initial_score=runner.state.initial_score,
            initial_dealer=runner.state.initial_dealer,
            match_ref=runner.match_ref,
            ruleset_id=runner.ruleset_id,
        )
        position = 0
        for record in records:
            if state.phase in (EnginePhase.AWAITING_DEAL, EnginePhase.DEAL_COMPLETE):
                if state.terminal:
                    break
                state = begin_explicit_deal(state, deals[len(state.completed_deals)])
            current_deal = len(state.completed_deals)
            if current_deal > deal_number:
                break
            action = action_from_data(record.action)
            if current_deal == deal_number and record.seat == seat:
                out.append(SeatDecision(
                    decision_index=position,
                    event_index=record.expected_event_index,
                    observation=match_observation_for(state, seat),
                    action=action,
                ))
                position += 1
            state = apply_match_action(state, action)
    return out


_REVIEW_LOCK = threading.Lock()


def generate_deal_review(runner, *, seat: int, deal_number: int, reviewer: DealReviewer) -> dict[str, object]:
    if deal_number < 0 or deal_number >= len(runner.state.completed_deals):
        raise DealReviewError("deal_not_complete")
    result = runner.state.completed_deals[deal_number].public_result
    decisions = seat_decisions(runner, deal_number=deal_number, seat=seat)
    by_index = {decision.decision_index: decision for decision in decisions}
    with _REVIEW_LOCK:  # one reviewer object serves every room
        findings = list(reviewer.review_decisions(decisions))
    items = []
    seen = set()
    for finding in findings:
        decision = by_index.get(finding.decision_index)
        if decision is None or finding.decision_index in seen:
            raise DealReviewError("finding does not name one of this seat's decisions")
        seen.add(finding.decision_index)
        legal = decision.observation.legal_actions
        if finding.recommended not in legal or finding.recommended == decision.action:
            raise DealReviewError("recommendation is not another legal action of this seat")
        cost, error = float(finding.cost), float(finding.standard_error)
        if not (math.isfinite(cost) and cost > 0 and math.isfinite(error) and error >= 0):
            raise DealReviewError("finding cost is invalid")
        kind, trick_index = decision_kind(decision.observation)
        items.append({
            "cost": round(cost, 6),
            "decision_index": decision.decision_index,
            "event_index": decision.event_index,
            "kind": kind,
            "played_action": action_to_data(decision.action),
            "recommended_action": action_to_data(finding.recommended),
            "standard_error": round(error, 6),
            "trick_index": trick_index,
        })
    items.sort(key=lambda item: item["decision_index"])
    return {
        "deal_number": deal_number,
        "deal_ref": result.deal_ref,
        "decisions_reviewed": sum(1 for d in decisions if len(d.observation.legal_actions) > 1),
        "findings": items,
        "match_ref": runner.match_ref,
        "reviewer_id": str(reviewer.reviewer_id),
        "ruleset_id": runner.ruleset_id.value,
        "schema_version": DEAL_REVIEW_SCHEMA_VERSION,
        "seat": seat,
        "total_cost": round(sum(item["cost"] for item in items), 6),
    }
