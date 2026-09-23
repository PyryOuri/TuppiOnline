"""Pure construction of immutable player-specific observations."""

from __future__ import annotations

from dataclasses import dataclass, field

from tuppi_rules import (
    Card,
    Contract,
    MatchScore,
    PlayedCard,
    RulesetId,
    ShowAction as RulesShowAction,
    Team,
    legal_cards,
    partner_for_seat,
    team_for_seat,
    valid_show_cards,
    validate_seat,
)

from .actions import Action, PlayCardAction, ShowAction, SooliDecisionAction, SooliExchangeAction
from .errors import StateInvariantError, WrongPhaseError
from .state import CompletedTrick, DealState, EnginePhase, SooliTrick, validate_deal_state
from .validation import is_valid_deal_ref, is_valid_match_ref


OBSERVATION_SCHEMA_VERSION = "tuppi.engine.player_observation.v1"
CONTRACT_ACTION_ORDER: tuple[Contract, ...] = (Contract.NOLO, Contract.RAMI)


@dataclass(frozen=True, slots=True)
class PlayerObservation:
    match_ref: str
    deal_ref: str
    observing_seat: int
    team: Team
    partner_seat: int
    dealer: int
    forehand: int
    phase: EnginePhase
    current_actor: int | None
    own_hand: tuple[Card, ...]
    show_actions: tuple[RulesShowAction, ...]
    publicly_shown_cards: tuple[tuple[int, Card], ...]
    contract: Contract | None
    declarer: int | None
    first_leader: int | None
    completed_tricks: tuple[CompletedTrick, ...]
    current_trick: tuple[PlayedCard, ...]
    team_tricks: tuple[int, int]
    match_score: MatchScore
    legal_actions: tuple[Action, ...]
    deal_terminal: bool
    match_terminal: bool
    schema_version: str = field(default=OBSERVATION_SCHEMA_VERSION, init=False)
    ruleset_id: RulesetId = RulesetId.PROJECT_TARGET_V1
    visibility: str = field(default="player_private", init=False)
    # project_target_v2 (sooli). The exchanged cards are visible only to the
    # soolaaja and the partner; the RAMI pair sees that the exchange happened.
    sooli_decisions: tuple[tuple[int, bool], ...] = ()
    soolaaja: int | None = None
    sooli_exchanged: bool = False
    sooli_given_card: Card | None = None
    sooli_returned_card: Card | None = None
    sooli_tricks: tuple[SooliTrick, ...] = ()
    sooli_current_trick: tuple[PlayedCard, ...] = ()

    def __post_init__(self) -> None:
        if not is_valid_match_ref(self.match_ref):
            raise StateInvariantError("observation match_ref is invalid")
        if not is_valid_deal_ref(self.deal_ref):
            raise StateInvariantError("observation deal_ref is invalid")
        if type(self.observing_seat) is not int or self.observing_seat not in range(4):
            raise StateInvariantError("observing_seat must be in 0..3")
        if self.team is not team_for_seat(self.observing_seat):
            raise StateInvariantError("observation team disagrees with seat")
        if self.partner_seat != partner_for_seat(self.observing_seat):
            raise StateInvariantError("observation partner disagrees with seat")
        if type(self.own_hand) is not tuple:
            raise StateInvariantError("own_hand must be an immutable tuple")
        if type(self.show_actions) is not tuple or type(self.completed_tricks) is not tuple:
            raise StateInvariantError("public histories must be immutable tuples")
        if type(self.current_trick) is not tuple or type(self.legal_actions) is not tuple:
            raise StateInvariantError("partial trick and legal actions must be tuples")
        if self.current_actor != self.observing_seat and self.legal_actions:
            raise StateInvariantError("nonacting observation cannot contain legal actions")
        if self.deal_terminal and self.legal_actions:
            raise StateInvariantError("terminal observation cannot contain legal actions")
        if type(self.deal_terminal) is not bool or type(self.match_terminal) is not bool:
            raise StateInvariantError("terminal fields must be booleans")
        if self.publicly_shown_cards != tuple(
            (action.seat, action.shown_card) for action in self.show_actions
        ):
            raise StateInvariantError("public shown-card list disagrees with show history")
        if self.match_terminal and not self.deal_terminal:
            raise StateInvariantError("match-terminal observation must be deal-terminal")
        in_exchange = self.soolaaja is not None and self.observing_seat in (self.soolaaja, (self.soolaaja + 2) % 4)
        if not in_exchange and (self.sooli_given_card is not None or self.sooli_returned_card is not None):
            raise StateInvariantError("exchanged cards are private to the soolaaja and the partner")


def legal_actions_for(state: DealState, observing_seat: int) -> tuple[Action, ...]:
    validate_deal_state(state)
    return _legal_actions_for_validated(state, validate_seat(observing_seat))


def _legal_actions_for_validated(state: DealState, seat: int) -> tuple[Action, ...]:
    """Order the legal actions of a state the immediate caller just validated.

    The exemption covers exactly one synchronous call from a public boundary in
    this package. It is never carried across an agent callback, an await, a
    separate public call, or deserialisation: those must revalidate.
    """

    if state.current_actor != seat or state.complete:
        return ()
    hand = state.hands[seat]
    if state.phase is EnginePhase.SHOWING:
        actions: list[Action] = []
        for contract in CONTRACT_ACTION_ORDER:
            allowed = valid_show_cards(hand, contract)
            actions.extend(
                ShowAction(
                    seat=seat,
                    shown_card=card,
                    declared_contract=contract,
                )
                for card in hand
                if card in allowed
            )
        if not actions:
            raise StateInvariantError("current showing actor has no legal actions")
        return tuple(actions)
    if state.phase is EnginePhase.TRICK_PLAY:
        led_suit = state.current_trick[0].card.suit if state.current_trick else None
        allowed = legal_cards(hand, led_suit)
        actions = tuple(
            PlayCardAction(seat=seat, card=card) for card in hand if card in allowed
        )
        if not actions:
            raise StateInvariantError("current playing actor has no legal actions")
        return actions
    if state.phase is EnginePhase.SOOLI_OFFER:
        return (SooliDecisionAction(seat=seat, play_sooli=False), SooliDecisionAction(seat=seat, play_sooli=True))
    if state.phase is EnginePhase.SOOLI_GIVE:
        return tuple(SooliExchangeAction(seat=seat, card=card) for card in hand)
    if state.phase is EnginePhase.SOOLI_RETURN:
        return tuple(SooliExchangeAction(seat=seat, card=card) for card in hand if card != state.sooli_given)
    if state.phase is EnginePhase.SOOLI_PLAY:
        led_suit = state.sooli_current[0].card.suit if state.sooli_current else None
        allowed = legal_cards(hand, led_suit)
        actions = tuple(PlayCardAction(seat=seat, card=card) for card in hand if card in allowed)
        if not actions:
            raise StateInvariantError("current sooli actor has no legal actions")
        return actions
    raise WrongPhaseError(f"legal actions are unavailable in {state.phase.value}")


def observation_for(state: DealState, observing_seat: int) -> PlayerObservation:
    """Copy only information legally available to one player."""

    validate_deal_state(state)
    return _observation_for_validated(state, validate_seat(observing_seat))


def _observation_for_validated(state: DealState, seat: int) -> PlayerObservation:
    """Project a state the immediate caller just validated, for a checked seat.

    ``match_observation_for`` reuses its own match validation - which already
    revalidates the active deal - through this helper and the legal-action
    helper above, so one public observation performs one full deal validation.
    """

    current_score = state.ending_score or state.starting_score
    return PlayerObservation(
        match_ref=state.match_ref,
        deal_ref=state.deal_ref,
        observing_seat=seat,
        team=team_for_seat(seat),
        partner_seat=partner_for_seat(seat),
        dealer=state.dealer,
        forehand=state.forehand,
        phase=state.phase,
        current_actor=state.current_actor,
        own_hand=tuple(state.hands[seat]),
        show_actions=tuple(state.show_actions),
        publicly_shown_cards=tuple(
            (action.seat, action.shown_card) for action in state.show_actions
        ),
        contract=state.contract,
        declarer=state.declarer,
        first_leader=state.first_leader,
        completed_tricks=tuple(state.completed_tricks),
        current_trick=tuple(state.current_trick),
        team_tricks=state.team_tricks,
        match_score=current_score,
        legal_actions=_legal_actions_for_validated(state, seat),
        deal_terminal=state.complete,
        match_terminal=state.terminal,
        ruleset_id=state.ruleset_id,
        sooli_decisions=tuple(state.sooli_decisions),
        soolaaja=state.soolaaja,
        sooli_exchanged=state.sooli_returned is not None,
        sooli_given_card=state.sooli_given if _knows_exchange(state, seat) else None,
        sooli_returned_card=state.sooli_returned if _knows_exchange(state, seat) else None,
        sooli_tricks=tuple(state.sooli_tricks),
        sooli_current_trick=tuple(state.sooli_current),
    )


def _knows_exchange(state: DealState, seat: int) -> bool:
    return state.soolaaja is not None and seat in (state.soolaaja, (state.soolaaja + 2) % 4)
