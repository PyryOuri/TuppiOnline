"""Immutable, privacy-safe public events emitted by accepted transitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TypeAlias

from tuppi_rules import LOCKED_BID_RULESETS, SOOLI_RULESETS, SUPPORTED_RULESETS, Card, Contract, MatchScore, RulesetId, Team

from .errors import StateInvariantError
from .validation import is_valid_deal_ref, is_valid_match_ref


PUBLIC_EVENT_SCHEMA_VERSION = "tuppi.engine.public_event.v1"


class EventType(StrEnum):
    DEAL_STARTED = "deal_started"
    SHOW_ACCEPTED = "show_accepted"
    CONTRACT_RESOLVED = "contract_resolved"
    TRICK_STARTED = "trick_started"
    CARD_PLAYED = "card_played"
    TRICK_COMPLETED = "trick_completed"
    DEAL_COMPLETED = "deal_completed"
    MATCH_SCORE_CHANGED = "match_score_changed"
    DEALER_ROTATED = "dealer_rotated"
    MATCH_COMPLETED = "match_completed"
    # project_target_v2 and v3
    SOOLI_DECISION = "sooli_decision"
    SOOLI_EXCHANGED = "sooli_exchanged"
    # project_target_v3 only: a seat's bid was taken; what it was stays hidden
    # until showing resolves (then SHOW_ACCEPTED reveals the bids in order).
    BID_LOCKED = "bid_locked"


#: Event types that exist only under the sooli rulesets (v2, v3).
V2_ONLY_EVENT_TYPES = frozenset({EventType.SOOLI_DECISION, EventType.SOOLI_EXCHANGED})
#: Event types that exist only under the locked-bid rulesets (v3).
LOCKED_BID_EVENT_TYPES = frozenset({EventType.BID_LOCKED})


class DealOutcome(StrEnum):
    NOLO = "NOLO"
    MADE_RAMI = "MADE_RAMI"
    STOLEN_RAMI = "STOLEN_RAMI"
    # project_target_v2 only: the soolaaja took no trick / took a trick.
    SOOLI_WON = "SOOLI_WON"
    SOOLI_LOST = "SOOLI_LOST"


SOOLI_OUTCOMES = frozenset({DealOutcome.SOOLI_WON, DealOutcome.SOOLI_LOST})


class ScoreTransitionKind(StrEnum):
    ESTABLISH_UP = "ESTABLISH_UP"
    ADD_TO_UP = "ADD_TO_UP"
    RESET_BY_DOWN = "RESET_BY_DOWN"


def _seat(value: object, label: str) -> None:
    if type(value) is not int or value not in range(4):
        raise StateInvariantError(f"{label} must be an integer in 0..3")


def _trick_index(value: object) -> None:
    if type(value) is not int or value not in range(13):
        raise StateInvariantError("trick_index must be an integer in 0..12")


def _team_tricks(value: object) -> None:
    if (
        type(value) is not tuple
        or len(value) != 2
        or any(type(count) is not int or count < 0 for count in value)
    ):
        raise StateInvariantError("team_tricks must be a nonnegative integer pair")


@dataclass(frozen=True, slots=True)
class DealStartedPayload:
    deal_number: int
    dealer: int
    forehand: int
    score_before: MatchScore

    def __post_init__(self) -> None:
        if type(self.deal_number) is not int or self.deal_number < 0:
            raise StateInvariantError("deal_number must be a nonnegative integer")
        _seat(self.dealer, "dealer")
        _seat(self.forehand, "forehand")
        if not isinstance(self.score_before, MatchScore):
            raise StateInvariantError("score_before must be a MatchScore")


@dataclass(frozen=True, slots=True)
class ShowAcceptedPayload:
    seat: int
    shown_card: Card
    declared_contract: Contract
    verbal_required: bool

    def __post_init__(self) -> None:
        _seat(self.seat, "show seat")
        if not isinstance(self.shown_card, Card):
            raise StateInvariantError("shown_card must be a Card")
        if not isinstance(self.declared_contract, Contract):
            raise StateInvariantError("declared_contract must be a Contract")
        if type(self.verbal_required) is not bool:
            raise StateInvariantError("verbal_required must be a boolean")


@dataclass(frozen=True, slots=True)
class BidLockedPayload:
    """project_target_v3: ``seat`` has bid; the card and declaration stay hidden."""

    seat: int
    bid_index: int

    def __post_init__(self) -> None:
        _seat(self.seat, "bid seat")
        if type(self.bid_index) is not int or self.bid_index not in range(4):
            raise StateInvariantError("bid_index must be an integer in 0..3")


@dataclass(frozen=True, slots=True)
class ContractResolvedPayload:
    contract: Contract
    declarer: int | None
    first_leader: int

    def __post_init__(self) -> None:
        if not isinstance(self.contract, Contract):
            raise StateInvariantError("contract must be a Contract")
        if self.contract is Contract.RAMI:
            _seat(self.declarer, "declarer")
        elif self.declarer is not None:
            raise StateInvariantError("NOLO must not have a declarer")
        _seat(self.first_leader, "first_leader")


@dataclass(frozen=True, slots=True)
class TrickStartedPayload:
    trick_index: int
    leader: int

    def __post_init__(self) -> None:
        _trick_index(self.trick_index)
        _seat(self.leader, "leader")


@dataclass(frozen=True, slots=True)
class CardPlayedPayload:
    trick_index: int
    position: int
    seat: int
    card: Card

    def __post_init__(self) -> None:
        _trick_index(self.trick_index)
        if type(self.position) is not int or self.position not in range(4):
            raise StateInvariantError("position must be an integer in 0..3")
        _seat(self.seat, "playing seat")
        if not isinstance(self.card, Card):
            raise StateInvariantError("played card must be a Card")


@dataclass(frozen=True, slots=True)
class TrickCompletedPayload:
    trick_index: int
    winner: int
    team_tricks_after: tuple[int, int]

    def __post_init__(self) -> None:
        _trick_index(self.trick_index)
        _seat(self.winner, "trick winner")
        _team_tricks(self.team_tricks_after)
        if sum(self.team_tricks_after) != self.trick_index + 1:
            raise StateInvariantError("team trick totals must equal completed tricks")


@dataclass(frozen=True, slots=True)
class DealCompletedPayload:
    contract: Contract
    declarer: int | None
    outcome: DealOutcome
    winner_team: Team
    points: int
    team_tricks: tuple[int, int]

    def __post_init__(self) -> None:
        if not isinstance(self.contract, Contract):
            raise StateInvariantError("contract must be a Contract")
        if self.contract is Contract.RAMI:
            _seat(self.declarer, "declarer")
        elif self.declarer is not None:
            raise StateInvariantError("NOLO must not have a declarer")
        if not isinstance(self.outcome, DealOutcome):
            raise StateInvariantError("outcome must be a DealOutcome")
        if not isinstance(self.winner_team, Team):
            raise StateInvariantError("winner_team must be a Team")
        if type(self.points) is not int or self.points <= 0:
            raise StateInvariantError("points must be a positive integer")
        _team_tricks(self.team_tricks)
        if self.outcome in SOOLI_OUTCOMES:
            if self.contract is not Contract.RAMI or not 1 <= sum(self.team_tricks) <= 13:
                raise StateInvariantError("a sooli deal is a RAMI deal of 1 to 13 tricks")
        elif sum(self.team_tricks) != 13:
            raise StateInvariantError("completed deal trick totals must sum to 13")


@dataclass(frozen=True, slots=True)
class SooliDecisionPayload:
    seat: int
    play_sooli: bool

    def __post_init__(self) -> None:
        _seat(self.seat, "seat")
        if type(self.play_sooli) is not bool:
            raise StateInvariantError("play_sooli must be a boolean")


@dataclass(frozen=True, slots=True)
class SooliExchangedPayload:
    """Public record that the exchange happened; the cards stay private."""

    soolaaja: int
    partner: int

    def __post_init__(self) -> None:
        _seat(self.soolaaja, "soolaaja")
        _seat(self.partner, "partner")
        if (self.soolaaja + 2) % 4 != self.partner:
            raise StateInvariantError("the sooli partner must sit opposite the soolaaja")


@dataclass(frozen=True, slots=True)
class MatchScoreChangedPayload:
    score_before: MatchScore
    score_after: MatchScore
    deal_winner: Team
    deal_points: int
    transition_kind: ScoreTransitionKind

    def __post_init__(self) -> None:
        if not isinstance(self.score_before, MatchScore) or not isinstance(
            self.score_after, MatchScore
        ):
            raise StateInvariantError("score change requires MatchScore values")
        if not isinstance(self.deal_winner, Team):
            raise StateInvariantError("deal_winner must be a Team")
        if type(self.deal_points) is not int or self.deal_points <= 0:
            raise StateInvariantError("deal_points must be positive")
        if not isinstance(self.transition_kind, ScoreTransitionKind):
            raise StateInvariantError("transition_kind must be a ScoreTransitionKind")


@dataclass(frozen=True, slots=True)
class DealerRotatedPayload:
    dealer_before: int
    dealer_after: int

    def __post_init__(self) -> None:
        _seat(self.dealer_before, "dealer_before")
        _seat(self.dealer_after, "dealer_after")


@dataclass(frozen=True, slots=True)
class MatchCompletedPayload:
    final_score: MatchScore
    winner_team: Team

    def __post_init__(self) -> None:
        if not isinstance(self.final_score, MatchScore):
            raise StateInvariantError("final_score must be a MatchScore")
        if not isinstance(self.winner_team, Team):
            raise StateInvariantError("winner_team must be a Team")


EventPayload: TypeAlias = (
    DealStartedPayload
    | ShowAcceptedPayload
    | ContractResolvedPayload
    | TrickStartedPayload
    | CardPlayedPayload
    | TrickCompletedPayload
    | DealCompletedPayload
    | MatchScoreChangedPayload
    | DealerRotatedPayload
    | MatchCompletedPayload
    | SooliDecisionPayload
    | SooliExchangedPayload
    | BidLockedPayload
)


@dataclass(frozen=True, slots=True)
class PublicEvent:
    event_index: int
    event_type: EventType
    match_ref: str
    deal_ref: str
    payload: EventPayload
    schema_version: str = field(
        default=PUBLIC_EVENT_SCHEMA_VERSION, init=False
    )
    ruleset_id: RulesetId = RulesetId.PROJECT_TARGET_V1

    def __post_init__(self) -> None:
        if self.ruleset_id not in SUPPORTED_RULESETS:
            raise StateInvariantError("event ruleset is not supported")
        if self.event_type in V2_ONLY_EVENT_TYPES and self.ruleset_id not in SOOLI_RULESETS:
            raise StateInvariantError("sooli events exist only under sooli rulesets")
        if self.event_type in LOCKED_BID_EVENT_TYPES and self.ruleset_id not in LOCKED_BID_RULESETS:
            raise StateInvariantError("bid_locked events exist only under locked-bid rulesets")
        if type(self.event_index) is not int or self.event_index < 0:
            raise StateInvariantError("event_index must be a nonnegative integer")
        if not isinstance(self.event_type, EventType):
            raise StateInvariantError("event_type must be an EventType")
        if not is_valid_match_ref(self.match_ref):
            raise StateInvariantError("match_ref does not match the public schema")
        if not is_valid_deal_ref(self.deal_ref):
            raise StateInvariantError("deal_ref does not match the public schema")
        expected_prefix = f"{self.match_ref}/deal:"
        if not self.deal_ref.startswith(expected_prefix):
            raise StateInvariantError("deal_ref belongs to a different match_ref")
        expected_type = (
            (EventType.DEAL_STARTED, DealStartedPayload),
            (EventType.SHOW_ACCEPTED, ShowAcceptedPayload),
            (EventType.CONTRACT_RESOLVED, ContractResolvedPayload),
            (EventType.TRICK_STARTED, TrickStartedPayload),
            (EventType.CARD_PLAYED, CardPlayedPayload),
            (EventType.TRICK_COMPLETED, TrickCompletedPayload),
            (EventType.DEAL_COMPLETED, DealCompletedPayload),
            (EventType.MATCH_SCORE_CHANGED, MatchScoreChangedPayload),
            (EventType.DEALER_ROTATED, DealerRotatedPayload),
            (EventType.MATCH_COMPLETED, MatchCompletedPayload),
            (EventType.SOOLI_DECISION, SooliDecisionPayload),
            (EventType.SOOLI_EXCHANGED, SooliExchangedPayload),
            (EventType.BID_LOCKED, BidLockedPayload),
        )
        payload_type = next(
            payload_class
            for event_type, payload_class in expected_type
            if event_type is self.event_type
        )
        if not isinstance(self.payload, payload_type):
            raise StateInvariantError(
                f"{self.event_type.value} event has the wrong payload type"
            )
        if isinstance(self.payload, DealStartedPayload):
            encoded_number = int(self.deal_ref.removeprefix(expected_prefix))
            if self.payload.deal_number != encoded_number:
                raise StateInvariantError(
                    "deal_started number disagrees with deal_ref"
                )
