"""Explicit deal materialization and private state construction."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from tuppi_rules import (
    SUPPORTED_RULESETS,
    CARD_ENCODING_ID,
    Card,
    MatchScore,
    RulesError,
    RulesetId,
    forehand,
    is_match_terminal,
    validate_initial_hands,
    validate_seat,
)

from .errors import InvalidConstructionError
from .events import (
    DealStartedPayload,
    EventType,
    PublicEvent,
)
from .identity import (
    DEAL_IDENTITY_SCHEMA_VERSION,
    calculate_deal_id,
    deal_identity_data,
)
from .state import DealState, EnginePhase
from .validation import expected_deal_ref, is_valid_deal_ref, is_valid_match_ref


EXPLICIT_DEAL_SCHEMA_VERSION = "tuppi.engine.explicit_deal.v1"


@dataclass(frozen=True, slots=True, init=False)
class ExplicitDeal:
    """A fully materialized, validated, ordered four-hand deal."""

    dealer: int
    hands: tuple[tuple[Card, ...], ...]
    deal_id: str
    schema_version: str = field(
        default=EXPLICIT_DEAL_SCHEMA_VERSION, init=False
    )
    ruleset_id: RulesetId = field(default=RulesetId.PROJECT_TARGET_V1, init=False)
    card_encoding: str = field(default=CARD_ENCODING_ID, init=False)

    def __init__(
        self,
        *,
        dealer: int,
        hands: Iterable[Iterable[Card]],
        claimed_deal_id: str | None = None,
    ) -> None:
        try:
            validated_dealer = validate_seat(dealer)
            validated_hands = validate_initial_hands(hands)
        except RulesError as exc:
            raise InvalidConstructionError(f"invalid explicit deal: {exc}") from exc
        computed = calculate_deal_id(
            dealer=validated_dealer, hands=validated_hands
        )
        if claimed_deal_id is not None:
            if not isinstance(claimed_deal_id, str) or claimed_deal_id != computed:
                raise InvalidConstructionError(
                    "claimed deal_id does not match canonical deal content"
                )
        object.__setattr__(self, "dealer", validated_dealer)
        object.__setattr__(self, "hands", validated_hands)
        object.__setattr__(self, "deal_id", computed)
        object.__setattr__(self, "schema_version", EXPLICIT_DEAL_SCHEMA_VERSION)
        object.__setattr__(self, "ruleset_id", RulesetId.PROJECT_TARGET_V1)
        object.__setattr__(self, "card_encoding", CARD_ENCODING_ID)


def create_deal_state(
    explicit_deal: ExplicitDeal,
    *,
    starting_score: MatchScore,
    match_ref: str,
    deal_ref: str,
    deal_number: int,
    event_start_index: int,
    ruleset_id: RulesetId = RulesetId.PROJECT_TARGET_V1,
) -> DealState:
    """Create the first immutable state for an explicit deal."""
    if ruleset_id not in SUPPORTED_RULESETS:
        raise InvalidConstructionError("unsupported ruleset")

    if not isinstance(explicit_deal, ExplicitDeal):
        raise InvalidConstructionError("explicit_deal must be an ExplicitDeal")
    # Reconstruct to defend against objects forged with ``object.__new__``.
    checked = ExplicitDeal(
        dealer=explicit_deal.dealer,
        hands=explicit_deal.hands,
        claimed_deal_id=explicit_deal.deal_id,
    )
    if not isinstance(starting_score, MatchScore):
        raise InvalidConstructionError("starting_score must be a MatchScore")
    try:
        checked_score = MatchScore(starting_score.team0, starting_score.team1)
    except RulesError as exc:
        raise InvalidConstructionError(f"invalid starting_score: {exc}") from exc
    if is_match_terminal(checked_score):
        raise InvalidConstructionError("a deal cannot start from a terminal score")
    if not is_valid_match_ref(match_ref):
        raise InvalidConstructionError("match_ref does not match the public schema")
    if not is_valid_deal_ref(deal_ref):
        raise InvalidConstructionError("deal_ref does not match the public schema")
    if type(deal_number) is not int or deal_number < 0:
        raise InvalidConstructionError("deal_number must be nonnegative")
    if deal_ref != expected_deal_ref(match_ref, deal_number):
        raise InvalidConstructionError("deal_ref disagrees with match_ref or deal_number")
    if type(event_start_index) is not int or event_start_index < 0:
        raise InvalidConstructionError("event_start_index must be nonnegative")

    first_event = PublicEvent(
        event_index=event_start_index,
        event_type=EventType.DEAL_STARTED,
        match_ref=match_ref,
        deal_ref=deal_ref,
        payload=DealStartedPayload(
            deal_number=deal_number,
            dealer=checked.dealer,
            forehand=forehand(checked.dealer),
            score_before=checked_score,
        ),
        ruleset_id=ruleset_id,
    )
    return DealState(
        ruleset_id=ruleset_id,
        match_ref=match_ref,
        deal_ref=deal_ref,
        deal_id=checked.deal_id,
        deal_number=deal_number,
        dealer=checked.dealer,
        forehand=forehand(checked.dealer),
        starting_score=checked_score,
        initial_hands=checked.hands,
        hands=checked.hands,
        phase=EnginePhase.SHOWING,
        current_actor=forehand(checked.dealer),
        show_actions=(),
        contract=None,
        declarer=None,
        first_leader=None,
        current_trick=(),
        completed_tricks=(),
        team_tricks=(0, 0),
        deal_score=None,
        ending_score=None,
        next_dealer=None,
        event_start_index=event_start_index,
        events=(first_event,),
    )
