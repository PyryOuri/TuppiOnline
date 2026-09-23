"""Canonical construction of privacy-safe events from accepted public state."""

from __future__ import annotations

from tuppi_rules import (
    Contract,
    DealScore,
    MatchScore,
    PlayedCard,
    RulesetId,
    ShowAction as RulesShowAction,
    is_match_terminal,
    match_winner,
    team_for_seat,
)
from tuppi_rules.sooli import SOOLI_MAX_TRICKS, SooliScore

from .errors import StateInvariantError
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
    SooliDecisionPayload,
    SooliExchangedPayload,
    TrickCompletedPayload,
    TrickStartedPayload,
)


def build_expected_deal_events(
    *,
    event_start_index: int,
    match_ref: str,
    deal_ref: str,
    deal_number: int,
    dealer: int,
    forehand_seat: int,
    score_before: MatchScore,
    show_actions: tuple[RulesShowAction, ...],
    contract: Contract | None,
    declarer: int | None,
    first_leader_seat: int | None,
    completed_tricks: tuple[object, ...],
    current_trick: tuple[PlayedCard, ...],
    team_tricks: tuple[int, int],
    deal_score: DealScore | None,
    score_after: MatchScore | None,
    next_dealer: int | None,
    ruleset_id: RulesetId = RulesetId.PROJECT_TARGET_V1,
    sooli_decisions: tuple[tuple[int, bool], ...] = (),
    soolaaja: int | None = None,
    sooli_exchanged: bool = False,
    sooli_tricks: tuple[object, ...] = (),
    sooli_current: tuple[PlayedCard, ...] = (),
) -> tuple[PublicEvent, ...]:
    """Return the sole canonical event stream for these accepted fields.

    Under project_target_v2 a RAMI resolution is followed by the public sooli
    decisions. If both defenders decline, the v1 stream continues unchanged.
    If one accepts, a single ``sooli_exchanged`` event (no card identities)
    precedes three-card tricks led first by the declarer, reported with the
    ordinary trick events.
    """

    payloads: list[tuple[EventType, EventPayload]] = [
        (
            EventType.DEAL_STARTED,
            DealStartedPayload(
                deal_number=deal_number,
                dealer=dealer,
                forehand=forehand_seat,
                score_before=score_before,
            ),
        )
    ]
    payloads.extend(
        (
            EventType.SHOW_ACCEPTED,
            ShowAcceptedPayload(
                seat=action.seat,
                shown_card=action.shown_card,
                declared_contract=action.declared_contract,
                verbal_required=action.verbal_required,
            ),
        )
        for action in show_actions
    )
    v2_rami = ruleset_id is RulesetId.PROJECT_TARGET_V2 and contract is Contract.RAMI
    if contract is not None:
        if first_leader_seat is None:
            raise StateInvariantError("resolved deal lacks first leader")
        payloads.append(
            (
                EventType.CONTRACT_RESOLVED,
                ContractResolvedPayload(
                    contract=contract,
                    declarer=declarer,
                    first_leader=first_leader_seat,
                ),
            )
        )
    if contract is not None and v2_rami:
        payloads.extend(
            (EventType.SOOLI_DECISION, SooliDecisionPayload(seat=seat, play_sooli=accepted))
            for seat, accepted in sooli_decisions
        )
    offers_pending = v2_rami and soolaaja is None and len(sooli_decisions) < 2
    if contract is not None and soolaaja is not None:
        if sooli_exchanged:
            payloads.append(
                (EventType.SOOLI_EXCHANGED, SooliExchangedPayload(soolaaja=soolaaja, partner=(soolaaja + 2) % 4))
            )
            payloads.append((EventType.TRICK_STARTED, TrickStartedPayload(trick_index=0, leader=declarer)))
            running = [0, 0]
            for trick in sooli_tricks:
                payloads.extend(
                    (
                        EventType.CARD_PLAYED,
                        CardPlayedPayload(trick_index=trick.trick_index, position=position,
                                          seat=play.seat, card=play.card),
                    )
                    for position, play in enumerate(trick.plays)
                )
                running[team_for_seat(trick.winner).value] += 1
                payloads.append(
                    (
                        EventType.TRICK_COMPLETED,
                        TrickCompletedPayload(trick_index=trick.trick_index, winner=trick.winner,
                                              team_tricks_after=(running[0], running[1])),
                    )
                )
                if trick.winner != soolaaja and trick.trick_index + 1 < SOOLI_MAX_TRICKS:
                    payloads.append(
                        (EventType.TRICK_STARTED,
                         TrickStartedPayload(trick_index=trick.trick_index + 1, leader=trick.winner))
                    )
            payloads.extend(
                (
                    EventType.CARD_PLAYED,
                    CardPlayedPayload(trick_index=len(sooli_tricks), position=position,
                                      seat=play.seat, card=play.card),
                )
                for position, play in enumerate(sooli_current)
            )
    elif contract is not None and not offers_pending:
        payloads.append(
            (
                EventType.TRICK_STARTED,
                TrickStartedPayload(
                    trick_index=0, leader=first_leader_seat
                ),
            )
        )
        running_totals = [0, 0]
        for trick in completed_tricks:
            payloads.extend(
                (
                    EventType.CARD_PLAYED,
                    CardPlayedPayload(
                        trick_index=trick.trick_index,
                        position=position,
                        seat=play.seat,
                        card=play.card,
                    ),
                )
                for position, play in enumerate(trick.plays)
            )
            running_totals[team_for_seat(trick.winner).value] += 1
            payloads.append(
                (
                    EventType.TRICK_COMPLETED,
                    TrickCompletedPayload(
                        trick_index=trick.trick_index,
                        winner=trick.winner,
                        team_tricks_after=(running_totals[0], running_totals[1]),
                    ),
                )
            )
            if trick.trick_index < 12:
                payloads.append(
                    (
                        EventType.TRICK_STARTED,
                        TrickStartedPayload(
                            trick_index=trick.trick_index + 1,
                            leader=trick.winner,
                        ),
                    )
                )
        current_index = len(completed_tricks)
        payloads.extend(
            (
                EventType.CARD_PLAYED,
                CardPlayedPayload(
                    trick_index=current_index,
                    position=position,
                    seat=play.seat,
                    card=play.card,
                ),
            )
            for position, play in enumerate(current_trick)
        )

    if deal_score is not None:
        if contract is None or score_after is None:
            raise StateInvariantError("completed deal lacks result event fields")
        if isinstance(deal_score, SooliScore):
            outcome = DealOutcome.SOOLI_LOST if deal_score.soolaaja_won_trick else DealOutcome.SOOLI_WON
        else:
            outcome = (
                DealOutcome.NOLO
                if contract is Contract.NOLO
                else DealOutcome.STOLEN_RAMI
                if deal_score.stolen_rami
                else DealOutcome.MADE_RAMI
            )
        transition_kind = (
            ScoreTransitionKind.ESTABLISH_UP
            if score_before.up_team is None
            else ScoreTransitionKind.ADD_TO_UP
            if score_before.up_team is deal_score.winner_team
            else ScoreTransitionKind.RESET_BY_DOWN
        )
        payloads.extend(
            (
                (
                    EventType.DEAL_COMPLETED,
                    DealCompletedPayload(
                        contract=contract,
                        declarer=declarer,
                        outcome=outcome,
                        winner_team=deal_score.winner_team,
                        points=deal_score.points,
                        team_tricks=team_tricks,
                    ),
                ),
                (
                    EventType.MATCH_SCORE_CHANGED,
                    MatchScoreChangedPayload(
                        score_before=score_before,
                        score_after=score_after,
                        deal_winner=deal_score.winner_team,
                        deal_points=deal_score.points,
                        transition_kind=transition_kind,
                    ),
                ),
            )
        )
        if is_match_terminal(score_after):
            winner = match_winner(score_after)
            if winner is None:
                raise StateInvariantError("terminal event state has no winner")
            payloads.append(
                (
                    EventType.MATCH_COMPLETED,
                    MatchCompletedPayload(
                        final_score=score_after, winner_team=winner
                    ),
                )
            )
        else:
            if next_dealer is None:
                raise StateInvariantError("nonterminal event state has no next dealer")
            payloads.append(
                (
                    EventType.DEALER_ROTATED,
                    DealerRotatedPayload(
                        dealer_before=dealer, dealer_after=next_dealer
                    ),
                )
            )

    return tuple(
        PublicEvent(
            event_index=event_start_index + offset,
            event_type=event_type,
            match_ref=match_ref,
            deal_ref=deal_ref,
            payload=payload,
            ruleset_id=ruleset_id,
        )
        for offset, (event_type, payload) in enumerate(payloads)
    )
