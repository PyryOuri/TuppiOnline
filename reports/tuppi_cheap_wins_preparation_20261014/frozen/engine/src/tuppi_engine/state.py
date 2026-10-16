"""Frozen private deal state and its defensive invariants."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from tuppi_rules import (
    SOOLI_RULESETS,
    SUPPORTED_RULESETS,
    Card,
    Contract,
    DealScore,
    MatchScore,
    PlayedCard,
    RulesError,
    RulesetId,
    ShowAction as RulesShowAction,
    first_leader,
    forehand,
    is_match_terminal,
    match_winner,
    resolve_showing,
    rotate_dealer,
    team_for_seat,
    transition_rising_score,
    trick_winner,
    validate_initial_hands,
    validate_play,
    validate_show_action,
    validate_trick,
)

from tuppi_rules.sooli import (
    SOOLI_MAX_TRICKS,
    SooliScore,
    score_sooli,
    sooli_offer_order,
    sooli_trick_seats,
    sooli_trick_winner,
    transition_after_sooli,
    validate_exchange,
    validate_sooli_trick,
)

from .errors import StateInvariantError
from .event_builder import build_expected_deal_events
from .identity import calculate_deal_id
from .events import (
    CardPlayedPayload,
    ContractResolvedPayload,
    DealCompletedPayload,
    DealOutcome,
    DealStartedPayload,
    DealerRotatedPayload,
    EventPayload,
    EventType,
    MatchCompletedPayload,
    MatchScoreChangedPayload,
    PublicEvent,
    ScoreTransitionKind,
    ShowAcceptedPayload,
    TrickCompletedPayload,
    TrickStartedPayload,
)
from .trusted import is_trusted
from .validation import (
    expected_deal_ref,
    is_sha256_identifier,
    is_valid_deal_ref,
    is_valid_match_ref,
)


class EnginePhase(StrEnum):
    AWAITING_DEAL = "AWAITING_DEAL"
    SHOWING = "SHOWING"
    TRICK_PLAY = "TRICK_PLAY"
    DEAL_COMPLETE = "DEAL_COMPLETE"
    MATCH_COMPLETE = "MATCH_COMPLETE"
    # project_target_v2 only
    SOOLI_OFFER = "SOOLI_OFFER"
    SOOLI_GIVE = "SOOLI_GIVE"
    SOOLI_RETURN = "SOOLI_RETURN"
    SOOLI_PLAY = "SOOLI_PLAY"


SOOLI_PHASES = frozenset(
    {EnginePhase.SOOLI_OFFER, EnginePhase.SOOLI_GIVE, EnginePhase.SOOLI_RETURN, EnginePhase.SOOLI_PLAY}
)
#: Phases in which a deal is waiting for an action.
ACTIVE_PHASES = frozenset({EnginePhase.SHOWING, EnginePhase.TRICK_PLAY}) | SOOLI_PHASES


@dataclass(frozen=True, slots=True)
class CompletedTrick:
    trick_index: int
    leader: int
    plays: tuple[PlayedCard, ...]
    winner: int

    def __post_init__(self) -> None:
        if type(self.trick_index) is not int or self.trick_index not in range(13):
            raise StateInvariantError("trick_index must be an integer in 0..12")
        if type(self.leader) is not int or self.leader not in range(4):
            raise StateInvariantError("trick leader must be an integer in 0..3")
        if type(self.plays) is not tuple:
            raise StateInvariantError("completed trick plays must be a tuple")
        try:
            validated = validate_trick(self.plays)
        except RulesError as exc:
            raise StateInvariantError(f"completed trick is invalid: {exc}") from exc
        if validated[0].seat != self.leader:
            raise StateInvariantError("completed trick leader disagrees with first play")
        expected_winner = trick_winner(validated)
        if type(self.winner) is not int or self.winner != expected_winner:
            raise StateInvariantError("completed trick winner is invalid")


@dataclass(frozen=True, slots=True)
class SooliTrick:
    """One completed three-card sooli trick (project_target_v2)."""

    trick_index: int
    leader: int
    plays: tuple[PlayedCard, ...]
    winner: int

    def __post_init__(self) -> None:
        if type(self.trick_index) is not int or self.trick_index not in range(SOOLI_MAX_TRICKS):
            raise StateInvariantError("sooli trick_index must be an integer in 0..12")
        if type(self.leader) is not int or self.leader not in range(4):
            raise StateInvariantError("sooli trick leader must be an integer in 0..3")
        if (
            type(self.plays) is not tuple
            or len(self.plays) != 3
            or any(not isinstance(play, PlayedCard) for play in self.plays)
        ):
            raise StateInvariantError("a sooli trick holds exactly three PlayedCard values")
        if len({play.seat for play in self.plays}) != 3 or len({play.card for play in self.plays}) != 3:
            raise StateInvariantError("sooli trick seats and cards must be distinct")
        if self.plays[0].seat != self.leader:
            raise StateInvariantError("sooli trick leader disagrees with first play")
        try:
            expected = sooli_trick_winner(self.plays)
        except RulesError as exc:
            raise StateInvariantError(f"sooli trick is invalid: {exc}") from exc
        if type(self.winner) is not int or self.winner != expected:
            raise StateInvariantError("sooli trick winner is invalid")


@dataclass(frozen=True, slots=True)
class DealState:
    """Complete private state for one active or just-completed explicit deal."""

    ruleset_id: RulesetId
    match_ref: str
    deal_ref: str
    deal_id: str
    deal_number: int
    dealer: int
    forehand: int
    starting_score: MatchScore
    initial_hands: tuple[tuple[Card, ...], ...]
    hands: tuple[tuple[Card, ...], ...]
    phase: EnginePhase
    current_actor: int | None
    show_actions: tuple[RulesShowAction, ...]
    contract: Contract | None
    declarer: int | None
    first_leader: int | None
    current_trick: tuple[PlayedCard, ...]
    completed_tricks: tuple[CompletedTrick, ...]
    team_tricks: tuple[int, int]
    deal_score: DealScore | None
    ending_score: MatchScore | None
    next_dealer: int | None
    event_start_index: int
    events: tuple[PublicEvent, ...]
    # project_target_v2 (sooli); defaults describe every v1 state.
    sooli_decisions: tuple[tuple[int, bool], ...] = ()
    soolaaja: int | None = None
    sooli_given: Card | None = None
    sooli_returned: Card | None = None
    sooli_tricks: tuple[SooliTrick, ...] = ()
    sooli_current: tuple[PlayedCard, ...] = ()

    def __post_init__(self) -> None:
        # Implicit revalidation of a state this engine just produced. Elided
        # inside ``trusted.trusted_transitions``; see that module for what
        # stays validated and what the caller takes on in exchange.
        if not is_trusted():
            _validate_deal_state(self)

    @property
    def terminal(self) -> bool:
        return self.phase is EnginePhase.MATCH_COMPLETE

    @property
    def complete(self) -> bool:
        return self.phase in (EnginePhase.DEAL_COMPLETE, EnginePhase.MATCH_COMPLETE)


def validate_deal_state(state: DealState) -> DealState:
    """Revalidate a state at a public transition boundary."""

    if not isinstance(state, DealState):
        raise StateInvariantError("state must be a DealState")
    _validate_deal_state(state)
    return state


def _validate_deal_state(state: DealState) -> None:
    try:
        _validate_deal_state_rules(state)
    except StateInvariantError:
        raise
    except RulesError as exc:
        raise StateInvariantError(f"deal state violates project_target_v1: {exc}") from exc
    except (AttributeError, IndexError, TypeError, ValueError) as exc:
        raise StateInvariantError("deal state contains malformed fields") from exc


def _validate_deal_state_rules(state: DealState) -> None:
    if state.ruleset_id not in SUPPORTED_RULESETS:
        raise StateInvariantError("clean engine supports project_target_v1 and project_target_v2")
    v2 = state.ruleset_id in SOOLI_RULESETS
    sooli_fields_default = (
        state.sooli_decisions == ()
        and state.soolaaja is None
        and state.sooli_given is None
        and state.sooli_returned is None
        and state.sooli_tricks == ()
        and state.sooli_current == ()
    )
    if not v2 and (not sooli_fields_default or state.phase in SOOLI_PHASES):
        raise StateInvariantError("project_target_v1 has no sooli")
    if not is_valid_match_ref(state.match_ref):
        raise StateInvariantError("match_ref does not match the public schema")
    if not is_valid_deal_ref(state.deal_ref):
        raise StateInvariantError("deal_ref does not match the public schema")
    if not is_sha256_identifier(state.deal_id):
        raise StateInvariantError("deal_id must be a canonical sha256 identifier")
    if type(state.deal_number) is not int or state.deal_number < 0:
        raise StateInvariantError("deal_number must be a nonnegative integer")
    if state.deal_ref != expected_deal_ref(state.match_ref, state.deal_number):
        raise StateInvariantError("deal_ref disagrees with match_ref or deal_number")
    if type(state.dealer) is not int or state.dealer not in range(4):
        raise StateInvariantError("dealer must be an integer in 0..3")
    if state.forehand != forehand(state.dealer):
        raise StateInvariantError("forehand is inconsistent with dealer")
    if not isinstance(state.starting_score, MatchScore):
        raise StateInvariantError("starting_score must be a MatchScore")
    if MatchScore(
        state.starting_score.team0, state.starting_score.team1
    ) != state.starting_score:
        raise StateInvariantError("starting_score contains invalid fields")
    if is_match_terminal(state.starting_score):
        raise StateInvariantError("a deal cannot start from a terminal match score")
    if type(state.initial_hands) is not tuple or any(
        type(hand) is not tuple for hand in state.initial_hands
    ):
        raise StateInvariantError("initial hands must be immutable ordered tuples")
    initial_hands = validate_initial_hands(state.initial_hands)
    if state.deal_id != calculate_deal_id(
        dealer=state.dealer, hands=initial_hands
    ):
        raise StateInvariantError("deal_id disagrees with canonical deal content")
    if type(state.hands) is not tuple or len(state.hands) != 4:
        raise StateInvariantError("current hands must be a four-hand tuple")
    if any(type(hand) is not tuple for hand in state.hands):
        raise StateInvariantError("every current hand must be a tuple")
    if not isinstance(state.phase, EnginePhase) or state.phase is EnginePhase.AWAITING_DEAL:
        raise StateInvariantError("a DealState requires an active or completed deal phase")

    if type(state.show_actions) is not tuple or any(
        not isinstance(action, RulesShowAction) for action in state.show_actions
    ):
        raise StateInvariantError("show_actions must be a tuple of validated shows")
    expected_show_seats = tuple(
        (state.forehand + offset) % 4 for offset in range(len(state.show_actions))
    )
    if tuple(action.seat for action in state.show_actions) != expected_show_seats:
        raise StateInvariantError("show actions are not the clockwise forehand prefix")
    for action in state.show_actions:
        expected = validate_show_action(
            seat=action.seat,
            hand=initial_hands[action.seat],
            shown_card=action.shown_card,
            declared_contract=action.declared_contract,
            claimed_verbal_required=action.verbal_required,
        )
        if action != expected:
            raise StateInvariantError("stored show action is not authoritatively derived")

    if type(state.completed_tricks) is not tuple or any(
        not isinstance(trick, CompletedTrick) for trick in state.completed_tricks
    ):
        raise StateInvariantError("completed_tricks must contain CompletedTrick values")
    for trick in state.completed_tricks:
        if CompletedTrick(
            trick_index=trick.trick_index,
            leader=trick.leader,
            plays=trick.plays,
            winner=trick.winner,
        ) != trick:
            raise StateInvariantError("completed trick contains invalid fields")
    if tuple(trick.trick_index for trick in state.completed_tricks) != tuple(
        range(len(state.completed_tricks))
    ):
        raise StateInvariantError("completed trick indices must be contiguous from zero")
    if type(state.current_trick) is not tuple or len(state.current_trick) > 3:
        raise StateInvariantError("current_trick must be a tuple containing zero to three plays")
    if any(not isinstance(play, PlayedCard) for play in state.current_trick):
        raise StateInvariantError("current_trick must contain PlayedCard values")

    all_plays = tuple(
        play for trick in state.completed_tricks for play in trick.plays
    ) + state.current_trick
    played_cards = tuple(play.card for play in all_plays)
    if len(set(played_cards)) != len(played_cards):
        raise StateInvariantError("a card has been played more than once")

    replay_hands = [list(hand) for hand in initial_hands]
    sooli = state.soolaaja is not None
    if sooli:
        _apply_recorded_exchange(state, initial_hands, replay_hands)
    elif state.sooli_given is not None or state.sooli_returned is not None or state.sooli_tricks or state.sooli_current:
        raise StateInvariantError("sooli play fields require a soolaaja")
    previous_winner: int | None = None
    for trick in state.completed_tricks:
        expected_leader = state.first_leader if trick.trick_index == 0 else previous_winner
        if expected_leader is None or trick.leader != expected_leader:
            raise StateInvariantError("completed trick has the wrong leader")
        led_suit = trick.plays[0].card.suit
        for position, play in enumerate(trick.plays):
            validate_play(
                hand=replay_hands[play.seat],
                card=play.card,
                led_suit=None if position == 0 else led_suit,
            )
            replay_hands[play.seat].remove(play.card)
        previous_winner = trick.winner

    if state.current_trick:
        partial_leader = state.first_leader if not state.completed_tricks else previous_winner
        if partial_leader is None:
            raise StateInvariantError("partial trick has no derived leader")
        expected_seats = tuple(
            (partial_leader + offset) % 4 for offset in range(len(state.current_trick))
        )
        if tuple(play.seat for play in state.current_trick) != expected_seats:
            raise StateInvariantError("partial trick seats are not clockwise from its leader")
        led_suit = state.current_trick[0].card.suit
        for position, play in enumerate(state.current_trick):
            validate_play(
                hand=replay_hands[play.seat],
                card=play.card,
                led_suit=None if position == 0 else led_suit,
            )
            replay_hands[play.seat].remove(play.card)

    sooli_ended = False
    if sooli:
        if state.completed_tricks or state.current_trick:
            raise StateInvariantError("a sooli deal has no four-card tricks")
        sooli_ended = _replay_sooli_tricks(state, replay_hands)

    expected_hands = tuple(tuple(hand) for hand in replay_hands)
    if state.hands != expected_hands:
        raise StateInvariantError("current hands disagree with the accepted play history")

    winners = tuple(trick.winner for trick in state.completed_tricks) + tuple(
        trick.winner for trick in state.sooli_tricks
    )
    expected_team_tricks = (
        sum(team_for_seat(winner).value == 0 for winner in winners),
        sum(team_for_seat(winner).value == 1 for winner in winners),
    )
    if state.team_tricks != expected_team_tricks:
        raise StateInvariantError("team trick totals disagree with trick winners")
    if sum(state.team_tricks) != len(winners):
        raise StateInvariantError("team trick totals must equal completed trick count")

    if state.phase is EnginePhase.SHOWING:
        if len(state.show_actions) >= 4 or any(
            action.declared_contract is Contract.RAMI for action in state.show_actions
        ):
            raise StateInvariantError("resolved showing cannot remain in SHOWING phase")
        if any(
            value is not None
            for value in (state.contract, state.declarer, state.first_leader)
        ):
            raise StateInvariantError("SHOWING phase cannot have a resolved contract")
        if state.completed_tricks or state.current_trick or state.hands != initial_hands:
            raise StateInvariantError("card play cannot occur during SHOWING")
        expected_actor = (state.forehand + len(state.show_actions)) % 4
        if state.current_actor != expected_actor:
            raise StateInvariantError("SHOWING current_actor is invalid")
        if any(
            value is not None
            for value in (state.deal_score, state.ending_score, state.next_dealer)
        ):
            raise StateInvariantError("SHOWING phase cannot contain terminal scoring fields")
        if not sooli_fields_default:
            raise StateInvariantError("SHOWING phase cannot contain sooli fields")
    else:
        resolution = resolve_showing(dealer=state.dealer, actions=state.show_actions)
        if state.contract is not resolution.contract or state.declarer != resolution.declarer:
            raise StateInvariantError("resolved contract fields disagree with showing")
        expected_first = first_leader(
            contract=resolution.contract,
            dealer=state.dealer,
            declarer=resolution.declarer,
        )
        if state.first_leader != expected_first:
            raise StateInvariantError("first_leader disagrees with contract resolution")
        if v2:
            _validate_sooli_offers(state)

    if state.phase in SOOLI_PHASES:
        _validate_sooli_phase(state, sooli_ended)
    elif state.phase is EnginePhase.TRICK_PLAY:
        if len(state.completed_tricks) >= 13:
            raise StateInvariantError("TRICK_PLAY cannot contain 13 completed tricks")
        if not state.current_trick:
            expected_actor = (
                state.first_leader
                if not state.completed_tricks
                else state.completed_tricks[-1].winner
            )
        else:
            expected_actor = (state.current_trick[-1].seat + 1) % 4
        if state.current_actor != expected_actor:
            raise StateInvariantError("TRICK_PLAY current_actor is invalid")
        if any(
            value is not None
            for value in (state.deal_score, state.ending_score, state.next_dealer)
        ):
            raise StateInvariantError("TRICK_PLAY cannot contain terminal scoring fields")
        if sooli:
            raise StateInvariantError("a sooli deal is played in SOOLI_PLAY, not TRICK_PLAY")
    elif sooli and state.phase in (EnginePhase.DEAL_COMPLETE, EnginePhase.MATCH_COMPLETE):
        _validate_sooli_completion(state, sooli_ended)
    elif state.phase in (EnginePhase.DEAL_COMPLETE, EnginePhase.MATCH_COMPLETE):
        if state.current_actor is not None or state.current_trick:
            raise StateInvariantError("completed state cannot have an actor or partial trick")
        if len(state.completed_tricks) != 13 or any(state.hands):
            raise StateInvariantError("completed deal requires 13 tricks and empty hands")
        if not isinstance(state.deal_score, DealScore) or not isinstance(
            state.ending_score, MatchScore
        ):
            raise StateInvariantError("completed deal requires deal and match scores")
        if state.deal_score.team_tricks != state.team_tricks:
            raise StateInvariantError("deal score trick totals disagree with state")
        expected_ending = transition_rising_score(state.starting_score, state.deal_score)
        if state.ending_score != expected_ending:
            raise StateInvariantError("ending score disagrees with rising-score transition")
        terminal = is_match_terminal(state.ending_score)
        if state.phase is EnginePhase.MATCH_COMPLETE:
            if not terminal or state.next_dealer is not None:
                raise StateInvariantError("MATCH_COMPLETE fields are inconsistent")
        elif terminal or state.next_dealer != rotate_dealer(state.dealer):
            raise StateInvariantError("DEAL_COMPLETE dealer or score is inconsistent")

    if type(state.event_start_index) is not int or state.event_start_index < 0:
        raise StateInvariantError("event_start_index must be nonnegative")
    if type(state.events) is not tuple or not state.events:
        raise StateInvariantError("deal state must contain an immutable public event history")
    if tuple(event.event_index for event in state.events) != tuple(
        range(state.event_start_index, state.event_start_index + len(state.events))
    ):
        raise StateInvariantError("deal event indices must be contiguous")
    if any(
        event.match_ref != state.match_ref or event.deal_ref != state.deal_ref
        for event in state.events
    ):
        raise StateInvariantError("deal event identifiers disagree with state")
    if state.events[0].event_type is not EventType.DEAL_STARTED:
        raise StateInvariantError("first deal event must be deal_started")
    if state.events != _expected_events(state):
        raise StateInvariantError("public event history disagrees with accepted state")
    expected_last = {
        EnginePhase.SHOWING: (EventType.DEAL_STARTED, EventType.SHOW_ACCEPTED, EventType.BID_LOCKED),
        EnginePhase.TRICK_PLAY: (
            EventType.TRICK_STARTED,
            EventType.CARD_PLAYED,
        ),
        EnginePhase.DEAL_COMPLETE: (EventType.DEALER_ROTATED,),
        EnginePhase.MATCH_COMPLETE: (EventType.MATCH_COMPLETED,),
        EnginePhase.SOOLI_OFFER: (EventType.CONTRACT_RESOLVED, EventType.SOOLI_DECISION),
        EnginePhase.SOOLI_GIVE: (EventType.SOOLI_DECISION,),
        EnginePhase.SOOLI_RETURN: (EventType.SOOLI_DECISION,),
        EnginePhase.SOOLI_PLAY: (EventType.TRICK_STARTED, EventType.CARD_PLAYED),
    }[state.phase]
    if state.events[-1].event_type not in expected_last:
        raise StateInvariantError("last public event is inconsistent with deal phase")


def _apply_recorded_exchange(state: DealState, initial_hands, replay_hands) -> None:
    """Replay the exchange onto `replay_hands` (soolaaja gives first, partner returns)."""
    solo = state.soolaaja
    if type(solo) is not int or solo not in range(4):
        raise StateInvariantError("soolaaja must be a seat")
    partner = (solo + 2) % 4
    if state.sooli_given is None:
        if state.sooli_returned is not None:
            raise StateInvariantError("the partner cannot return before the soolaaja gives")
        return
    validate_exchange(giver_hand=initial_hands[solo], card=state.sooli_given)
    replay_hands[solo].remove(state.sooli_given)
    replay_hands[partner].append(state.sooli_given)
    if state.sooli_returned is None:
        return
    validate_exchange(giver_hand=replay_hands[partner], card=state.sooli_returned, received=state.sooli_given)
    replay_hands[partner].remove(state.sooli_returned)
    replay_hands[solo].append(state.sooli_returned)


def _sooli_next_leader(state: DealState) -> int:
    if state.declarer is None:
        raise StateInvariantError("sooli requires a declarer")
    return state.sooli_tricks[-1].winner if state.sooli_tricks else state.declarer


def _replay_sooli_tricks(state: DealState, replay_hands) -> bool:
    """Validate the sooli transcript against `replay_hands`; return whether it has ended."""
    if state.declarer is None or state.soolaaja is None:
        raise StateInvariantError("sooli play requires a declarer and a soolaaja")
    if type(state.sooli_tricks) is not tuple or any(not isinstance(t, SooliTrick) for t in state.sooli_tricks):
        raise StateInvariantError("sooli_tricks must contain SooliTrick values")
    if (state.sooli_tricks or state.sooli_current) and state.sooli_returned is None:
        raise StateInvariantError("sooli play cannot start before the exchange")
    leader = state.declarer
    ended = False
    for index, trick in enumerate(state.sooli_tricks):
        if ended:
            raise StateInvariantError("no sooli trick may follow the end of the deal")
        if SooliTrick(trick_index=trick.trick_index, leader=trick.leader, plays=trick.plays,
                      winner=trick.winner) != trick or trick.trick_index != index:
            raise StateInvariantError("sooli trick contains invalid fields")
        if trick.leader != leader:
            raise StateInvariantError("sooli trick has the wrong leader")
        validate_sooli_trick(trick.plays, leader=leader, declarer=state.declarer, soolaaja=state.soolaaja)
        led = trick.plays[0].card.suit
        for position, play in enumerate(trick.plays):
            validate_play(hand=replay_hands[play.seat], card=play.card, led_suit=None if position == 0 else led)
            replay_hands[play.seat].remove(play.card)
        ended = trick.winner == state.soolaaja or index + 1 == SOOLI_MAX_TRICKS
        leader = trick.winner
    if type(state.sooli_current) is not tuple or any(not isinstance(p, PlayedCard) for p in state.sooli_current):
        raise StateInvariantError("sooli_current must contain PlayedCard values")
    if state.sooli_current:
        if ended:
            raise StateInvariantError("no sooli card may be played after the deal ended")
        validate_sooli_trick(state.sooli_current, leader=leader, declarer=state.declarer,
                             soolaaja=state.soolaaja, complete=False)
        if len(state.sooli_current) >= 3:
            raise StateInvariantError("a complete sooli trick must be recorded as a SooliTrick")
        led = state.sooli_current[0].card.suit
        for position, play in enumerate(state.sooli_current):
            validate_play(hand=replay_hands[play.seat], card=play.card, led_suit=None if position == 0 else led)
            replay_hands[play.seat].remove(play.card)
    return ended


def _validate_sooli_offers(state: DealState) -> None:
    decisions = state.sooli_decisions
    if type(decisions) is not tuple or any(
        type(d) is not tuple or len(d) != 2 or type(d[0]) is not int or type(d[1]) is not bool for d in decisions
    ):
        raise StateInvariantError("sooli_decisions must be (seat, bool) pairs")
    if state.contract is not Contract.RAMI:
        if decisions or state.soolaaja is not None or state.phase in SOOLI_PHASES:
            raise StateInvariantError("sooli exists only in a RAMI deal")
        return
    order = sooli_offer_order(state.declarer)
    if tuple(seat for seat, _ in decisions) != order[: len(decisions)]:
        raise StateInvariantError("sooli offers must follow seat order from the declarer")
    if any(accepted for _, accepted in decisions[:-1]):
        raise StateInvariantError("no offer may follow an accepted sooli")
    accepted = bool(decisions) and decisions[-1][1]
    if accepted != (state.soolaaja is not None) or (accepted and state.soolaaja != decisions[-1][0]):
        raise StateInvariantError("soolaaja disagrees with the sooli decisions")
    complete = accepted or len(decisions) == 2
    if (state.phase is EnginePhase.SOOLI_OFFER) == complete:
        raise StateInvariantError("sooli offer phase disagrees with the decisions")


def _validate_sooli_phase(state: DealState, ended: bool) -> None:
    if any(value is not None for value in (state.deal_score, state.ending_score, state.next_dealer)):
        raise StateInvariantError("an active sooli phase cannot contain terminal scoring fields")
    if state.phase is EnginePhase.SOOLI_OFFER:
        if state.completed_tricks or state.current_trick or state.sooli_tricks or state.sooli_current:
            raise StateInvariantError("no card may be played before the sooli offers are answered")
        expected_actor = sooli_offer_order(state.declarer)[len(state.sooli_decisions)]
    elif state.soolaaja is None:
        raise StateInvariantError("sooli exchange and play require a soolaaja")
    elif state.phase is EnginePhase.SOOLI_GIVE:
        if state.sooli_given is not None or state.sooli_tricks or state.sooli_current:
            raise StateInvariantError("SOOLI_GIVE precedes the exchange")
        expected_actor = state.soolaaja
    elif state.phase is EnginePhase.SOOLI_RETURN:
        if state.sooli_given is None or state.sooli_returned is not None or state.sooli_tricks or state.sooli_current:
            raise StateInvariantError("SOOLI_RETURN follows the soolaaja's card and precedes play")
        expected_actor = (state.soolaaja + 2) % 4
    else:  # SOOLI_PLAY
        if state.sooli_returned is None or ended:
            raise StateInvariantError("SOOLI_PLAY requires a finished exchange and an unfinished deal")
        leader = _sooli_next_leader(state)
        seats = sooli_trick_seats(leader=leader, declarer=state.declarer, soolaaja=state.soolaaja)
        expected_actor = seats[len(state.sooli_current)]
    if state.current_actor != expected_actor:
        raise StateInvariantError(f"{state.phase.value} current_actor is invalid")


def _validate_sooli_completion(state: DealState, ended: bool) -> None:
    if state.current_actor is not None or state.sooli_current or not ended:
        raise StateInvariantError("a completed sooli deal has no actor, no partial trick, and has ended")
    last = state.sooli_tricks[-1]
    expected = score_sooli(declarer=state.declarer, soolaaja=state.soolaaja,
                           soolaaja_won_trick=last.winner == state.soolaaja,
                           tricks_played=len(state.sooli_tricks))
    if not isinstance(state.deal_score, SooliScore) or state.deal_score != expected:
        raise StateInvariantError("sooli deal score disagrees with the transcript")
    if not isinstance(state.ending_score, MatchScore):
        raise StateInvariantError("completed deal requires a match score")
    if state.ending_score != transition_after_sooli(state.starting_score, state.deal_score):
        raise StateInvariantError("ending score disagrees with rising-score transition")
    terminal = is_match_terminal(state.ending_score)
    if state.phase is EnginePhase.MATCH_COMPLETE:
        if not terminal or state.next_dealer is not None:
            raise StateInvariantError("MATCH_COMPLETE fields are inconsistent")
    elif terminal or state.next_dealer != rotate_dealer(state.dealer):
        raise StateInvariantError("DEAL_COMPLETE dealer or score is inconsistent")


def _expected_events(state: DealState) -> tuple[PublicEvent, ...]:
    """Reconstruct the only privacy-safe event stream for this state."""
    return build_expected_deal_events(
        event_start_index=state.event_start_index,
        match_ref=state.match_ref,
        deal_ref=state.deal_ref,
        deal_number=state.deal_number,
        dealer=state.dealer,
        forehand_seat=state.forehand,
        score_before=state.starting_score,
        show_actions=state.show_actions,
        contract=state.contract,
        declarer=state.declarer,
        first_leader_seat=state.first_leader,
        completed_tricks=state.completed_tricks,
        current_trick=state.current_trick,
        team_tricks=state.team_tricks,
        deal_score=state.deal_score,
        score_after=state.ending_score,
        next_dealer=state.next_dealer,
        ruleset_id=state.ruleset_id,
        sooli_decisions=state.sooli_decisions,
        soolaaja=state.soolaaja,
        sooli_exchanged=state.sooli_returned is not None,
        sooli_tricks=state.sooli_tricks,
        sooli_current=state.sooli_current,
    )
