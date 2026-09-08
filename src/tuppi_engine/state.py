"""Frozen private deal state and its defensive invariants."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from tuppi_rules import (
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
    if state.ruleset_id is not RulesetId.PROJECT_TARGET_V1:
        raise StateInvariantError("clean engine supports only project_target_v1")
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

    expected_hands = tuple(tuple(hand) for hand in replay_hands)
    if state.hands != expected_hands:
        raise StateInvariantError("current hands disagree with the accepted play history")

    expected_team_tricks = (
        sum(team_for_seat(trick.winner).value == 0 for trick in state.completed_tricks),
        sum(team_for_seat(trick.winner).value == 1 for trick in state.completed_tricks),
    )
    if state.team_tricks != expected_team_tricks:
        raise StateInvariantError("team trick totals disagree with trick winners")
    if sum(state.team_tricks) != len(state.completed_tricks):
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

    if state.phase is EnginePhase.TRICK_PLAY:
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
        EnginePhase.SHOWING: (EventType.DEAL_STARTED, EventType.SHOW_ACCEPTED),
        EnginePhase.TRICK_PLAY: (
            EventType.TRICK_STARTED,
            EventType.CARD_PLAYED,
        ),
        EnginePhase.DEAL_COMPLETE: (EventType.DEALER_ROTATED,),
        EnginePhase.MATCH_COMPLETE: (EventType.MATCH_COMPLETED,),
    }[state.phase]
    if state.events[-1].event_type not in expected_last:
        raise StateInvariantError("last public event is inconsistent with deal phase")


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
    )
