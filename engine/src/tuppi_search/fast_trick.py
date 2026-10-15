"""Validated search-local trick-play state for Phase 5D-C.

The authoritative engine remains the reference implementation.  This module
only represents the already-resolved trick-play suffix of one hypothetical
deal.  It omits engine event logs and repeated whole-state validation, which
are not consumed by the frozen rollout policies.

There are two ways in, and they lose different amounts.
:meth:`FastTrickState.from_observation_assignment` builds from a formal
observation plus one Phase 5B assignment, so it must undo the sampler's hand
canonicalization for the observing seat.  :meth:`FastTrickState.from_deal_state`
builds from an authoritative state the caller already holds — the rollout's
sampled world — and is an exact projection for all four seats.

The representation is immutable and owns no mutable card containers.  Its
transition and observation functions are differential-tested against
``tuppi_engine`` before use in the registered search agent.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from tuppi_engine import EnginePhase, PlayCardAction, PlayerObservation
from tuppi_engine.state import CompletedTrick
from tuppi_exact.sampling import HiddenHandAssignment
from tuppi_rules import (
    Contract,
    DealScore,
    MatchScore,
    PlayedCard,
    Team,
    is_match_terminal,
    legal_cards,
    match_winner,
    rotate_dealer,
    score_nolo,
    score_rami_for_declarer,
    team_for_seat,
    transition_rising_score,
    trick_winner,
    validate_play,
)


class FastTrickError(Exception):
    """A search-local transition or projection failed its strict contract."""


@dataclass(frozen=True, slots=True)
class FastTrickState:
    """Minimal immutable state for a resolved hypothetical trick-play suffix."""

    match_ref: str
    deal_ref: str
    dealer: int
    forehand: int
    starting_score: MatchScore
    hands: tuple[tuple, ...]
    current_actor: int | None
    show_actions: tuple
    publicly_shown_cards: tuple[tuple[int, object], ...]
    contract: Contract
    declarer: int | None
    first_leader: int
    current_trick: tuple[PlayedCard, ...]
    completed_tricks: tuple[CompletedTrick, ...]
    team_tricks: tuple[int, int]
    phase: EnginePhase = EnginePhase.TRICK_PLAY
    deal_score: DealScore | None = None
    ending_score: MatchScore | None = None
    next_dealer: int | None = None

    @classmethod
    def from_observation_assignment(
        cls, observation: PlayerObservation, assignment: HiddenHandAssignment
    ) -> "FastTrickState":
        if not isinstance(observation, PlayerObservation):
            raise FastTrickError("fast state requires a PlayerObservation")
        if not isinstance(assignment, HiddenHandAssignment):
            raise FastTrickError("fast state requires a hidden-hand assignment")
        if observation.phase is not EnginePhase.TRICK_PLAY:
            raise FastTrickError("fast state requires a trick-play observation")
        if assignment.observing_seat != observation.observing_seat:
            raise FastTrickError("assignment and observation seats disagree")
        if set(assignment.hands[observation.observing_seat]) != set(
            observation.own_hand
        ):
            raise FastTrickError("assignment changed the observing player's hand")
        if observation.contract is None or observation.first_leader is None:
            raise FastTrickError("trick-play observation lacks resolved contract fields")
        hands = [tuple(hand) for hand in assignment.hands]
        # The sampler canonicalizes every assignment hand.  The observer's
        # current order is public and is behaviorally relevant to Phase 4's
        # legal-action tie-break, so restore that one order exactly.
        hands[observation.observing_seat] = tuple(observation.own_hand)
        return cls(
            match_ref=observation.match_ref,
            deal_ref=observation.deal_ref,
            dealer=observation.dealer,
            forehand=observation.forehand,
            starting_score=observation.match_score,
            hands=tuple(hands),
            current_actor=observation.current_actor,
            show_actions=observation.show_actions,
            publicly_shown_cards=observation.publicly_shown_cards,
            contract=observation.contract,
            declarer=observation.declarer,
            first_leader=observation.first_leader,
            current_trick=observation.current_trick,
            completed_tricks=observation.completed_tricks,
            team_tricks=observation.team_tricks,
        )

    @classmethod
    def from_deal_state(cls, state) -> "FastTrickState":
        """Project an authoritative trick-play state onto the search-local one.

        The rollout already holds a full :class:`~tuppi_engine.DealState` — the
        sampled world with the candidate action forced — so it needs no
        observation and no assignment to hand over. Every field below is copied
        or derived, never inferred: ``publicly_shown_cards`` is the same
        derivation ``observation_for`` performs, and the four hands keep the
        engine's own order, which the legal-action tie-break is sensitive to.

        Unlike :meth:`from_observation_assignment` this loses nothing. There is
        no hidden-hand sampling step here and so no canonicalization to undo:
        the projection is exact for all four seats, not just the observer's.
        """

        if state.phase is not EnginePhase.TRICK_PLAY:
            raise FastTrickError(
                f"fast state requires a trick-play deal state, not {state.phase.value}"
            )
        if state.contract is None or state.first_leader is None:
            raise FastTrickError("trick-play state lacks resolved contract fields")
        return cls(
            match_ref=state.match_ref,
            deal_ref=state.deal_ref,
            dealer=state.dealer,
            forehand=state.forehand,
            starting_score=state.starting_score,
            hands=tuple(tuple(hand) for hand in state.hands),
            current_actor=state.current_actor,
            show_actions=tuple(state.show_actions),
            publicly_shown_cards=tuple(
                (action.seat, action.shown_card) for action in state.show_actions
            ),
            contract=state.contract,
            declarer=state.declarer,
            first_leader=state.first_leader,
            current_trick=tuple(state.current_trick),
            completed_tricks=tuple(state.completed_tricks),
            team_tricks=state.team_tricks,
        )

    @property
    def complete(self) -> bool:
        return self.phase in (EnginePhase.DEAL_COMPLETE, EnginePhase.MATCH_COMPLETE)

    @property
    def terminal(self) -> bool:
        return self.phase is EnginePhase.MATCH_COMPLETE

    def observation_for(self, observing_seat: int) -> PlayerObservation:
        """Project exactly the formal observation consumed by Phase 4 agents."""

        if type(observing_seat) is not int or observing_seat not in range(4):
            raise FastTrickError("observation seat must be an integer in 0..3")
        legal_actions = self._legal_actions_for(observing_seat)
        current_score = self.ending_score or self.starting_score
        return PlayerObservation(
            match_ref=self.match_ref,
            deal_ref=self.deal_ref,
            observing_seat=observing_seat,
            team=team_for_seat(observing_seat),
            partner_seat=(observing_seat + 2) % 4,
            dealer=self.dealer,
            forehand=self.forehand,
            phase=self.phase,
            current_actor=self.current_actor,
            own_hand=tuple(self.hands[observing_seat]),
            show_actions=self.show_actions,
            publicly_shown_cards=self.publicly_shown_cards,
            contract=self.contract,
            declarer=self.declarer,
            first_leader=self.first_leader,
            completed_tricks=self.completed_tricks,
            current_trick=self.current_trick,
            team_tricks=self.team_tricks,
            match_score=current_score,
            legal_actions=legal_actions,
            deal_terminal=self.complete,
            match_terminal=self.terminal,
        )

    def _legal_actions_for(self, observing_seat: int) -> tuple[PlayCardAction, ...]:
        if self.complete or self.current_actor != observing_seat:
            return ()
        led_suit = self.current_trick[0].card.suit if self.current_trick else None
        allowed = legal_cards(self.hands[observing_seat], led_suit)
        return tuple(
            PlayCardAction(seat=observing_seat, card=card)
            for card in self.hands[observing_seat]
            if card in allowed
        )

    def apply(self, action: PlayCardAction) -> "FastTrickState":
        """Apply one validated trick-play action without rebuilding engine events."""

        if self.complete:
            raise FastTrickError("fast state is complete")
        if not isinstance(action, PlayCardAction):
            raise FastTrickError("fast trick state accepts card-play actions only")
        if self.current_actor != action.seat:
            raise FastTrickError("fast transition received an action from the wrong seat")
        led_suit = self.current_trick[0].card.suit if self.current_trick else None
        try:
            validate_play(
                hand=self.hands[action.seat], card=action.card, led_suit=led_suit
            )
        except Exception as exc:  # the authoritative rules error is not public here
            raise FastTrickError(f"illegal fast-path play: {exc}") from exc

        mutable_hands = list(self.hands)
        hand = mutable_hands[action.seat]
        card_position = hand.index(action.card)
        mutable_hands[action.seat] = hand[:card_position] + hand[card_position + 1 :]
        hands = tuple(mutable_hands)
        partial = self.current_trick + (PlayedCard(seat=action.seat, card=action.card),)
        if len(partial) < 4:
            return replace(
                self,
                hands=hands,
                current_actor=(action.seat + 1) % 4,
                current_trick=partial,
            )

        winner = trick_winner(partial)
        completed = self.completed_tricks + (
            CompletedTrick(
                trick_index=len(self.completed_tricks),
                leader=partial[0].seat,
                plays=partial,
                winner=winner,
            ),
        )
        totals = list(self.team_tricks)
        totals[team_for_seat(winner).value] += 1
        team_totals = (totals[0], totals[1])
        if len(completed) < 13:
            return replace(
                self,
                hands=hands,
                current_actor=winner,
                current_trick=(),
                completed_tricks=completed,
                team_tricks=team_totals,
            )

        if self.contract is Contract.NOLO:
            deal_score = score_nolo(*team_totals)
        else:
            if self.declarer is None:
                raise FastTrickError("RAMI fast completion lacks a declarer")
            deal_score = score_rami_for_declarer(
                self.declarer, *team_totals
            )
        ending_score = transition_rising_score(self.starting_score, deal_score)
        terminal = is_match_terminal(ending_score)
        if terminal and match_winner(ending_score) is None:
            raise FastTrickError("terminal fast score has no match winner")
        return replace(
            self,
            hands=hands,
            phase=EnginePhase.MATCH_COMPLETE if terminal else EnginePhase.DEAL_COMPLETE,
            current_actor=None,
            current_trick=(),
            completed_tricks=completed,
            team_tricks=team_totals,
            deal_score=deal_score,
            ending_score=ending_score,
            next_dealer=None if terminal else rotate_dealer(self.dealer),
        )
