"""Candidate-world replay and historical observation reconstruction."""

from __future__ import annotations

from dataclasses import dataclass

from tuppi_engine import (
    DealState,
    ExplicitDeal,
    PlayerObservation,
    apply_action,
    create_deal_state,
    observation_for,
)
from tuppi_eval.serialization import content_digest

from tuppi_exact.continuation import reconstruct_initial_hands
from tuppi_exact.sampling import HiddenHandAssignment

from .history import CausalPublicHistory, PublicAction


@dataclass(frozen=True, slots=True)
class CandidateReplay:
    """A candidate state and its public-prefix replay.

    The state is research-private and never crosses the behaviour-model API.
    """

    initial_state: DealState
    current_state: DealState
    history: CausalPublicHistory

    def observations_before_actions(
        self,
    ) -> tuple[tuple[PublicAction, PlayerObservation], ...]:
        state = self.initial_state
        records: list[tuple[PublicAction, PlayerObservation]] = []
        for item in self.history.actions:
            records.append((item, observation_for(state, item.action.seat)))
            state = apply_action(state, item.action)
        if state != self.current_state:
            raise ValueError("candidate replay did not end at the observed state")
        return tuple(records)


def _candidate_match_ref(observation: PlayerObservation) -> str:
    compact = {
        "dealer": observation.dealer,
        "match_score": [observation.match_score.team0, observation.match_score.team1],
        "observing_seat": observation.observing_seat,
        "schema": "tuppi.belief.candidate_replay.v1",
        "shows": [
            {
                "card": action.shown_card.to_code(),
                "contract": action.declared_contract.value,
                "seat": action.seat,
            }
            for action in observation.show_actions
        ],
        "tricks": [
            {
                "card": play.card.to_code(),
                "seat": play.seat,
            }
            for trick in observation.completed_tricks
            for play in trick.plays
        ]
        + [
            {"card": play.card.to_code(), "seat": play.seat}
            for play in observation.current_trick
        ],
    }
    return f"hypothetical:{content_digest(compact)[7:]}"


def replay_candidate(
    observation: PlayerObservation,
    assignment: HiddenHandAssignment,
    history: CausalPublicHistory | None = None,
) -> CandidateReplay:
    """Replay a sampled feasible assignment through authoritative transitions."""

    if not isinstance(observation, PlayerObservation):
        raise TypeError("candidate replay requires a PlayerObservation")
    if not isinstance(assignment, HiddenHandAssignment):
        raise TypeError("candidate replay requires a HiddenHandAssignment")
    if assignment.observing_seat != observation.observing_seat:
        raise ValueError("assignment and observation belong to different seats")
    public_history = history or CausalPublicHistory.from_observation(observation)
    hands = reconstruct_initial_hands(observation, assignment)
    match_ref = _candidate_match_ref(observation)
    state = create_deal_state(
        ExplicitDeal(dealer=observation.dealer, hands=hands),
        starting_score=observation.match_score,
        match_ref=match_ref,
        deal_ref=f"{match_ref}/deal:0",
        deal_number=0,
        event_start_index=0,
    )
    initial = state
    for item in public_history.actions:
        state = apply_action(state, item.action)
    # The replay must agree on every public field at the decision boundary.  The
    # candidate state may differ only in hidden hands and deal identity.
    candidate_observation = observation_for(state, observation.observing_seat)
    if _public_observation_key(candidate_observation) != _public_observation_key(observation):
        raise ValueError("candidate replay does not match the observed public prefix")
    return CandidateReplay(initial_state=initial, current_state=state, history=public_history)


def _public_observation_key(observation: PlayerObservation) -> tuple[object, ...]:
    """Fields that must be identical between a real and candidate observation."""

    return (
        observation.observing_seat,
        observation.team,
        observation.partner_seat,
        observation.dealer,
        observation.forehand,
        observation.phase,
        observation.current_actor,
        observation.show_actions,
        observation.publicly_shown_cards,
        observation.contract,
        observation.declarer,
        observation.first_leader,
        observation.completed_tricks,
        observation.current_trick,
        observation.team_tricks,
        observation.match_score,
        observation.legal_actions,
        observation.deal_terminal,
        observation.match_terminal,
    )
