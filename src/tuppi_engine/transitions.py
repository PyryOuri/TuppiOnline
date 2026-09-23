"""Strict pure transitions for showing, trick play, and deal completion."""

from __future__ import annotations

from dataclasses import replace

from tuppi_rules import (
    Contract,
    MatchScore,
    PlayedCard,
    RulesError,
    Team,
    first_leader,
    is_match_terminal,
    match_winner,
    resolve_showing,
    rotate_dealer,
    score_nolo,
    score_rami_for_declarer,
    team_for_seat,
    transition_rising_score,
    trick_winner,
    validate_completed_deal,
    validate_play,
    validate_show_action,
)

from tuppi_rules import RulesetId
from tuppi_rules.sooli import (
    SOOLI_MAX_TRICKS,
    SooliScore,
    score_sooli,
    sooli_offer_order,
    sooli_trick_seats,
    sooli_trick_winner,
    transition_after_sooli,
    validate_exchange,
)

from .actions import Action, PlayCardAction, ShowAction, SooliDecisionAction, SooliExchangeAction
from .errors import InvalidActionError, TerminalStateError, WrongActorError, WrongPhaseError
from .events import (
    CardPlayedPayload,
    ContractResolvedPayload,
    DealCompletedPayload,
    DealOutcome,
    DealerRotatedPayload,
    EventPayload,
    EventType,
    MatchCompletedPayload,
    MatchScoreChangedPayload,
    PublicEvent,
    ScoreTransitionKind,
    ShowAcceptedPayload,
    SooliDecisionPayload,
    SooliExchangedPayload,
    TrickCompletedPayload,
    TrickStartedPayload,
)
from .results import DealResult, ResearchDealResult
from .state import CompletedTrick, DealState, EnginePhase, SooliTrick, validate_deal_state


def _events(
    state: DealState, additions: tuple[tuple[EventType, EventPayload], ...]
) -> tuple[PublicEvent, ...]:
    events = list(state.events)
    next_index = state.event_start_index + len(events)
    for event_type, payload in additions:
        events.append(
            PublicEvent(
                event_index=next_index,
                event_type=event_type,
                match_ref=state.match_ref,
                deal_ref=state.deal_ref,
                payload=payload,
                ruleset_id=state.ruleset_id,
            )
        )
        next_index += 1
    return tuple(events)


def apply_action(state: DealState, action: Action) -> DealState:
    """Validate and apply exactly one action; never repair or substitute it."""

    validate_deal_state(state)
    return _apply_action_validated(state, action)


def _apply_action_validated(state: DealState, action: Action) -> DealState:
    """Apply one action to a state the immediate caller just validated.

    Every actor, phase, action-type and follow-suit check below is retained,
    and the constructed successor state validates itself as before. The input
    exemption covers exactly one synchronous call from a public boundary in
    this package; it is never carried across an agent callback, an await, a
    separate public call, or deserialisation.
    """

    if state.phase in (EnginePhase.DEAL_COMPLETE, EnginePhase.MATCH_COMPLETE):
        raise TerminalStateError("the deal is complete and accepts no more actions")
    if state.phase is EnginePhase.SHOWING:
        if not isinstance(action, ShowAction):
            if isinstance(action, PlayCardAction):
                raise WrongPhaseError("card play is not allowed before showing resolves")
            raise InvalidActionError("agent must return an engine ShowAction")
        return _apply_show_action(state, action)
    if state.phase is EnginePhase.TRICK_PLAY:
        if not isinstance(action, PlayCardAction):
            if isinstance(action, ShowAction):
                raise WrongPhaseError("showing is already resolved")
            raise InvalidActionError("agent must return an engine PlayCardAction")
        return _apply_play_action(state, action)
    if state.phase is EnginePhase.SOOLI_OFFER:
        if not isinstance(action, SooliDecisionAction):
            raise WrongPhaseError("a defender must answer the sooli offer")
        return _apply_sooli_decision(state, action)
    if state.phase in (EnginePhase.SOOLI_GIVE, EnginePhase.SOOLI_RETURN):
        if not isinstance(action, SooliExchangeAction):
            raise WrongPhaseError("the sooli card exchange is in progress")
        return _apply_sooli_exchange(state, action)
    if state.phase is EnginePhase.SOOLI_PLAY:
        if not isinstance(action, PlayCardAction):
            raise WrongPhaseError("sooli trick play expects a PlayCardAction")
        return _apply_sooli_play(state, action)
    raise WrongPhaseError(f"actions are not accepted in phase {state.phase.value}")


def _check_actor(state: DealState, seat: int) -> None:
    if state.current_actor != seat:
        raise WrongActorError(
            f"seat {seat} acted while current actor is seat {state.current_actor}"
        )


def _apply_show_action(state: DealState, action: ShowAction) -> DealState:
    _check_actor(state, action.seat)
    try:
        accepted = validate_show_action(
            seat=action.seat,
            hand=state.hands[action.seat],
            shown_card=action.shown_card,
            declared_contract=action.declared_contract,
        )
    except RulesError as exc:
        raise InvalidActionError(f"illegal show action: {exc}") from exc

    shows = state.show_actions + (accepted,)
    additions: list[tuple[EventType, EventPayload]] = [
        (
            EventType.SHOW_ACCEPTED,
            ShowAcceptedPayload(
                seat=accepted.seat,
                shown_card=accepted.shown_card,
                declared_contract=accepted.declared_contract,
                verbal_required=accepted.verbal_required,
            ),
        )
    ]
    resolved = accepted.declared_contract is Contract.RAMI or len(shows) == 4
    if not resolved:
        return replace(
            state,
            current_actor=(accepted.seat + 1) % 4,
            show_actions=shows,
            events=_events(state, tuple(additions)),
        )

    try:
        resolution = resolve_showing(dealer=state.dealer, actions=shows)
        leader = first_leader(
            contract=resolution.contract,
            dealer=state.dealer,
            declarer=resolution.declarer,
        )
    except RulesError as exc:
        raise InvalidActionError(f"showing could not resolve: {exc}") from exc
    additions.append(
        (
            EventType.CONTRACT_RESOLVED,
            ContractResolvedPayload(
                contract=resolution.contract,
                declarer=resolution.declarer,
                first_leader=leader,
            ),
        )
    )
    if state.ruleset_id is RulesetId.PROJECT_TARGET_V2 and resolution.contract is Contract.RAMI:
        # v2: the defenders are asked about sooli before any card is played.
        return replace(
            state,
            phase=EnginePhase.SOOLI_OFFER,
            current_actor=sooli_offer_order(resolution.declarer)[0],
            show_actions=shows,
            contract=resolution.contract,
            declarer=resolution.declarer,
            first_leader=leader,
            events=_events(state, tuple(additions)),
        )
    additions.append(
        (
            EventType.TRICK_STARTED,
            TrickStartedPayload(trick_index=0, leader=leader),
        )
    )
    return replace(
        state,
        phase=EnginePhase.TRICK_PLAY,
        current_actor=leader,
        show_actions=shows,
        contract=resolution.contract,
        declarer=resolution.declarer,
        first_leader=leader,
        events=_events(state, tuple(additions)),
    )


def _apply_play_action(state: DealState, action: PlayCardAction) -> DealState:
    _check_actor(state, action.seat)
    led_suit = state.current_trick[0].card.suit if state.current_trick else None
    try:
        validate_play(
            hand=state.hands[action.seat],
            card=action.card,
            led_suit=led_suit,
        )
    except RulesError as exc:
        raise InvalidActionError(f"illegal card play: {exc}") from exc

    mutable_hands = list(state.hands)
    hand = mutable_hands[action.seat]
    card_position = hand.index(action.card)
    mutable_hands[action.seat] = hand[:card_position] + hand[card_position + 1 :]
    hands = tuple(mutable_hands)
    play = PlayedCard(seat=action.seat, card=action.card)
    partial = state.current_trick + (play,)
    trick_index = len(state.completed_tricks)
    additions: list[tuple[EventType, EventPayload]] = [
        (
            EventType.CARD_PLAYED,
            CardPlayedPayload(
                trick_index=trick_index,
                position=len(partial) - 1,
                seat=action.seat,
                card=action.card,
            ),
        )
    ]
    if len(partial) < 4:
        return replace(
            state,
            hands=hands,
            current_actor=(action.seat + 1) % 4,
            current_trick=partial,
            events=_events(state, tuple(additions)),
        )

    winner = trick_winner(partial)
    completed = CompletedTrick(
        trick_index=trick_index,
        leader=partial[0].seat,
        plays=partial,
        winner=winner,
    )
    completed_tricks = state.completed_tricks + (completed,)
    team_tricks = list(state.team_tricks)
    team_tricks[team_for_seat(winner).value] += 1
    totals = (team_tricks[0], team_tricks[1])
    additions.append(
        (
            EventType.TRICK_COMPLETED,
            TrickCompletedPayload(
                trick_index=trick_index,
                winner=winner,
                team_tricks_after=totals,
            ),
        )
    )
    if len(completed_tricks) < 13:
        additions.append(
            (
                EventType.TRICK_STARTED,
                TrickStartedPayload(
                    trick_index=len(completed_tricks), leader=winner
                ),
            )
        )
        return replace(
            state,
            hands=hands,
            current_actor=winner,
            current_trick=(),
            completed_tricks=completed_tricks,
            team_tricks=totals,
            events=_events(state, tuple(additions)),
        )

    if state.first_leader is None or state.contract is None:
        raise InvalidActionError("internal resolved-contract fields are unavailable")
    validate_completed_deal(
        tuple(trick.plays for trick in completed_tricks),
        expected_first_leader=state.first_leader,
    )
    if state.contract is Contract.NOLO:
        deal_score = score_nolo(*totals)
        outcome = DealOutcome.NOLO
    else:
        if state.declarer is None:
            raise InvalidActionError("RAMI completion requires a declarer")
        deal_score = score_rami_for_declarer(state.declarer, *totals)
        outcome = (
            DealOutcome.STOLEN_RAMI
            if deal_score.stolen_rami
            else DealOutcome.MADE_RAMI
        )
    ending_score = transition_rising_score(state.starting_score, deal_score)
    terminal = is_match_terminal(ending_score)
    next_dealer = None if terminal else rotate_dealer(state.dealer)

    additions.extend(
        (
            (
                EventType.DEAL_COMPLETED,
                DealCompletedPayload(
                    contract=state.contract,
                    declarer=state.declarer,
                    outcome=outcome,
                    winner_team=deal_score.winner_team,
                    points=deal_score.points,
                    team_tricks=totals,
                ),
            ),
            (
                EventType.MATCH_SCORE_CHANGED,
                MatchScoreChangedPayload(
                    score_before=state.starting_score,
                    score_after=ending_score,
                    deal_winner=deal_score.winner_team,
                    deal_points=deal_score.points,
                    transition_kind=_score_transition_kind(
                        state.starting_score, deal_score.winner_team
                    ),
                ),
            ),
        )
    )
    phase: EnginePhase
    if terminal:
        winner_team = match_winner(ending_score)
        if winner_team is None:
            raise InvalidActionError("terminal score has no winner")
        additions.append(
            (
                EventType.MATCH_COMPLETED,
                MatchCompletedPayload(
                    final_score=ending_score,
                    winner_team=winner_team,
                ),
            )
        )
        phase = EnginePhase.MATCH_COMPLETE
    else:
        additions.append(
            (
                EventType.DEALER_ROTATED,
                DealerRotatedPayload(
                    dealer_before=state.dealer,
                    dealer_after=next_dealer,
                ),
            )
        )
        phase = EnginePhase.DEAL_COMPLETE

    return replace(
        state,
        hands=hands,
        phase=phase,
        current_actor=None,
        current_trick=(),
        completed_tricks=completed_tricks,
        team_tricks=totals,
        deal_score=deal_score,
        ending_score=ending_score,
        next_dealer=next_dealer,
        events=_events(state, tuple(additions)),
    )


def _apply_sooli_decision(state: DealState, action: SooliDecisionAction) -> DealState:
    _check_actor(state, action.seat)
    decisions = state.sooli_decisions + ((action.seat, action.play_sooli),)
    additions: list[tuple[EventType, EventPayload]] = [
        (EventType.SOOLI_DECISION, SooliDecisionPayload(seat=action.seat, play_sooli=action.play_sooli))
    ]
    if action.play_sooli:
        return replace(
            state,
            phase=EnginePhase.SOOLI_GIVE,
            current_actor=action.seat,
            sooli_decisions=decisions,
            soolaaja=action.seat,
            events=_events(state, tuple(additions)),
        )
    if len(decisions) < 2:
        return replace(
            state,
            current_actor=sooli_offer_order(state.declarer)[len(decisions)],
            sooli_decisions=decisions,
            events=_events(state, tuple(additions)),
        )
    # Both declined: an ordinary RAMI deal, exactly as in project_target_v1.
    additions.append((EventType.TRICK_STARTED, TrickStartedPayload(trick_index=0, leader=state.first_leader)))
    return replace(
        state,
        phase=EnginePhase.TRICK_PLAY,
        current_actor=state.first_leader,
        sooli_decisions=decisions,
        events=_events(state, tuple(additions)),
    )


def _apply_sooli_exchange(state: DealState, action: SooliExchangeAction) -> DealState:
    _check_actor(state, action.seat)
    solo = state.soolaaja
    partner = (solo + 2) % 4
    giving = state.phase is EnginePhase.SOOLI_GIVE
    try:
        validate_exchange(giver_hand=state.hands[action.seat], card=action.card,
                          received=None if giving else state.sooli_given)
    except RulesError as exc:
        raise InvalidActionError(f"illegal sooli exchange: {exc}") from exc
    receiver = partner if giving else solo
    hands = list(state.hands)
    giver_hand = hands[action.seat]
    position = giver_hand.index(action.card)
    hands[action.seat] = giver_hand[:position] + giver_hand[position + 1:]
    hands[receiver] = hands[receiver] + (action.card,)
    if giving:
        return replace(state, phase=EnginePhase.SOOLI_RETURN, current_actor=partner,
                       hands=tuple(hands), sooli_given=action.card)
    additions = (
        (EventType.SOOLI_EXCHANGED, SooliExchangedPayload(soolaaja=solo, partner=partner)),
        (EventType.TRICK_STARTED, TrickStartedPayload(trick_index=0, leader=state.declarer)),
    )
    return replace(state, phase=EnginePhase.SOOLI_PLAY, current_actor=state.declarer,
                   hands=tuple(hands), sooli_returned=action.card, events=_events(state, additions))


def _apply_sooli_play(state: DealState, action: PlayCardAction) -> DealState:
    _check_actor(state, action.seat)
    led_suit = state.sooli_current[0].card.suit if state.sooli_current else None
    try:
        validate_play(hand=state.hands[action.seat], card=action.card, led_suit=led_suit)
    except RulesError as exc:
        raise InvalidActionError(f"illegal card play: {exc}") from exc
    hands = list(state.hands)
    hand = hands[action.seat]
    position = hand.index(action.card)
    hands[action.seat] = hand[:position] + hand[position + 1:]
    play = PlayedCard(seat=action.seat, card=action.card)
    partial = state.sooli_current + (play,)
    trick_index = len(state.sooli_tricks)
    leader = partial[0].seat
    seats = sooli_trick_seats(leader=leader, declarer=state.declarer, soolaaja=state.soolaaja)
    additions: list[tuple[EventType, EventPayload]] = [
        (EventType.CARD_PLAYED, CardPlayedPayload(trick_index=trick_index, position=len(partial) - 1,
                                                  seat=action.seat, card=action.card))
    ]
    if len(partial) < 3:
        return replace(state, hands=tuple(hands), current_actor=seats[len(partial)], sooli_current=partial,
                       events=_events(state, tuple(additions)))
    winner = sooli_trick_winner(partial)
    trick = SooliTrick(trick_index=trick_index, leader=leader, plays=partial, winner=winner)
    tricks = state.sooli_tricks + (trick,)
    totals = list(state.team_tricks)
    totals[team_for_seat(winner).value] += 1
    team_tricks = (totals[0], totals[1])
    additions.append((EventType.TRICK_COMPLETED,
                      TrickCompletedPayload(trick_index=trick_index, winner=winner, team_tricks_after=team_tricks)))
    soolaaja_won = winner == state.soolaaja
    if not soolaaja_won and len(tricks) < SOOLI_MAX_TRICKS:
        additions.append((EventType.TRICK_STARTED, TrickStartedPayload(trick_index=len(tricks), leader=winner)))
        return replace(state, hands=tuple(hands), current_actor=winner, sooli_current=(), sooli_tricks=tricks,
                       team_tricks=team_tricks, events=_events(state, tuple(additions)))
    deal_score = score_sooli(declarer=state.declarer, soolaaja=state.soolaaja,
                             soolaaja_won_trick=soolaaja_won, tricks_played=len(tricks))
    ending_score = transition_after_sooli(state.starting_score, deal_score)
    return _complete_deal(
        state,
        dict(hands=tuple(hands), sooli_current=(), sooli_tricks=tricks, team_tricks=team_tricks),
        additions, deal_score, ending_score,
        DealOutcome.SOOLI_LOST if soolaaja_won else DealOutcome.SOOLI_WON,
    )


def _complete_deal(state: DealState, fields: dict, additions, deal_score, ending_score, outcome) -> DealState:
    """Result events, score transition and dealer rotation for a sooli completion.

    The completed state is built in one step: every intermediate DealState
    validates itself, so a half-updated one would be rejected.
    """
    terminal = is_match_terminal(ending_score)
    next_dealer = None if terminal else rotate_dealer(state.dealer)
    additions = list(additions)
    additions.extend(
        (
            (EventType.DEAL_COMPLETED,
             DealCompletedPayload(contract=state.contract, declarer=state.declarer, outcome=outcome,
                                  winner_team=deal_score.winner_team, points=deal_score.points,
                                  team_tricks=fields["team_tricks"])),
            (EventType.MATCH_SCORE_CHANGED,
             MatchScoreChangedPayload(score_before=state.starting_score, score_after=ending_score,
                                      deal_winner=deal_score.winner_team, deal_points=deal_score.points,
                                      transition_kind=_score_transition_kind(state.starting_score,
                                                                             deal_score.winner_team))),
        )
    )
    if terminal:
        winner_team = match_winner(ending_score)
        additions.append((EventType.MATCH_COMPLETED,
                          MatchCompletedPayload(final_score=ending_score, winner_team=winner_team)))
        phase = EnginePhase.MATCH_COMPLETE
    else:
        additions.append((EventType.DEALER_ROTATED,
                          DealerRotatedPayload(dealer_before=state.dealer, dealer_after=next_dealer)))
        phase = EnginePhase.DEAL_COMPLETE
    return replace(state, **fields, phase=phase, current_actor=None, deal_score=deal_score,
                   ending_score=ending_score, next_dealer=next_dealer, events=_events(state, tuple(additions)))


def _score_transition_kind(
    score_before: MatchScore, deal_winner: Team
) -> ScoreTransitionKind:
    if score_before.up_team is None:
        return ScoreTransitionKind.ESTABLISH_UP
    if score_before.up_team is deal_winner:
        return ScoreTransitionKind.ADD_TO_UP
    return ScoreTransitionKind.RESET_BY_DOWN


def deal_result_from_state(state: DealState) -> DealResult:
    validate_deal_state(state)
    if not state.complete:
        raise WrongPhaseError("deal result is unavailable before all 13 tricks")
    if (
        state.contract is None
        or state.first_leader is None
        or state.deal_score is None
        or state.ending_score is None
    ):
        raise WrongPhaseError("completed deal is missing result fields")
    if isinstance(state.deal_score, SooliScore):
        outcome = DealOutcome.SOOLI_LOST if state.deal_score.soolaaja_won_trick else DealOutcome.SOOLI_WON
    else:
        outcome = (
            DealOutcome.NOLO
            if state.contract is Contract.NOLO
            else DealOutcome.STOLEN_RAMI
            if state.deal_score.stolen_rami
            else DealOutcome.MADE_RAMI
        )
    return DealResult(
        match_ref=state.match_ref,
        deal_ref=state.deal_ref,
        deal_number=state.deal_number,
        dealer=state.dealer,
        forehand=state.forehand,
        contract=state.contract,
        declarer=state.declarer,
        first_leader=state.first_leader,
        show_actions=state.show_actions,
        completed_tricks=state.completed_tricks,
        team_tricks=state.team_tricks,
        deal_score=state.deal_score,
        outcome=outcome,
        score_before=state.starting_score,
        score_after=state.ending_score,
        match_terminal=state.terminal,
        next_dealer=state.next_dealer,
        events=state.events,
        ruleset_id=state.ruleset_id,
        sooli_decisions=state.sooli_decisions,
        soolaaja=state.soolaaja,
        sooli_tricks=state.sooli_tricks,
    )


def research_deal_result_from_state(state: DealState) -> ResearchDealResult:
    return ResearchDealResult(
        public_result=deal_result_from_state(state),
        deal_id=state.deal_id,
        initial_hands=state.initial_hands,
        sooli_given=state.sooli_given,
        sooli_returned=state.sooli_returned,
    )
