"""Strict versioned JSON boundaries and canonical privacy-separated output."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
from typing import Any

from tuppi_rules import (
    CARD_ENCODING_ID,
    RULESET_ID,
    Card,
    Contract,
    MatchScore,
    RulesError,
    RulesetId,
    Team,
    card_from_code,
    card_to_code,
    is_match_terminal,
)

from .actions import Action, PlayCardAction, ShowAction
from .deal import EXPLICIT_DEAL_SCHEMA_VERSION, ExplicitDeal
from .errors import EngineValidationError, SerializationError
from .events import (
    CardPlayedPayload,
    ContractResolvedPayload,
    DealCompletedPayload,
    DealStartedPayload,
    DealerRotatedPayload,
    EventType,
    MatchCompletedPayload,
    MatchScoreChangedPayload,
    PublicEvent,
    ShowAcceptedPayload,
    TrickCompletedPayload,
    TrickStartedPayload,
)
from .observations import PlayerObservation
from .results import (
    DealResult,
    MatchResult,
    ResearchDealResult,
    ResearchRunResult,
    calculate_match_input_id,
)
from .state import CompletedTrick
from .validation import is_sha256_identifier, is_valid_match_ref


MATCH_INPUT_SCHEMA_VERSION = "tuppi.engine.match_input.v1"
AGENT_SCRIPT_SCHEMA_VERSION = "tuppi.engine.agent_script.v1"
PUBLIC_EVENT_LOG_SCHEMA_VERSION = "tuppi.engine.public_event_log.v1"


def canonical_json_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise SerializationError("value is not canonical-JSON serializable") from exc


def canonical_json_text(value: object) -> str:
    return canonical_json_bytes(value).decode("utf-8")


def _digest(value: object) -> str:
    return f"sha256:{hashlib.sha256(canonical_json_bytes(value)).hexdigest()}"


def _score_data(score: MatchScore) -> list[int]:
    return [score.team0, score.team1]


def _played_card_data(play) -> dict[str, object]:
    return {"card": card_to_code(play.card), "seat": play.seat}


def _show_data(show) -> dict[str, object]:
    return {
        "declared_contract": show.declared_contract.value,
        "seat": show.seat,
        "shown_card": card_to_code(show.shown_card),
        "verbal_required": show.verbal_required,
    }


def action_to_data(action: Action) -> dict[str, object]:
    if isinstance(action, ShowAction):
        return {
            "declared_contract": action.declared_contract.value,
            "seat": action.seat,
            "shown_card": card_to_code(action.shown_card),
            "type": "show",
        }
    if isinstance(action, PlayCardAction):
        return {
            "card": card_to_code(action.card),
            "seat": action.seat,
            "type": "play",
        }
    raise SerializationError("cannot serialize a non-engine action")


def completed_trick_to_data(trick: CompletedTrick) -> dict[str, object]:
    return {
        "leader": trick.leader,
        "plays": [_played_card_data(play) for play in trick.plays],
        "trick_index": trick.trick_index,
        "winner": trick.winner,
    }


def event_to_data(event: PublicEvent) -> dict[str, object]:
    if not isinstance(event, PublicEvent):
        raise SerializationError("event must be a PublicEvent")
    payload = event.payload
    if isinstance(payload, DealStartedPayload):
        payload_data = {
            "deal_number": payload.deal_number,
            "dealer": payload.dealer,
            "forehand": payload.forehand,
            "score_before": _score_data(payload.score_before),
        }
    elif isinstance(payload, ShowAcceptedPayload):
        payload_data = {
            "declared_contract": payload.declared_contract.value,
            "seat": payload.seat,
            "shown_card": card_to_code(payload.shown_card),
            "verbal_required": payload.verbal_required,
        }
    elif isinstance(payload, ContractResolvedPayload):
        payload_data = {
            "contract": payload.contract.value,
            "declarer": payload.declarer,
            "first_leader": payload.first_leader,
        }
    elif isinstance(payload, TrickStartedPayload):
        payload_data = {
            "leader": payload.leader,
            "trick_index": payload.trick_index,
        }
    elif isinstance(payload, CardPlayedPayload):
        payload_data = {
            "card": card_to_code(payload.card),
            "position": payload.position,
            "seat": payload.seat,
            "trick_index": payload.trick_index,
        }
    elif isinstance(payload, TrickCompletedPayload):
        payload_data = {
            "team_tricks_after": list(payload.team_tricks_after),
            "trick_index": payload.trick_index,
            "winner": payload.winner,
        }
    elif isinstance(payload, DealCompletedPayload):
        payload_data = {
            "contract": payload.contract.value,
            "declarer": payload.declarer,
            "outcome": payload.outcome.value,
            "points": payload.points,
            "team_tricks": list(payload.team_tricks),
            "winner_team": payload.winner_team.value,
        }
    elif isinstance(payload, MatchScoreChangedPayload):
        payload_data = {
            "deal_points": payload.deal_points,
            "deal_winner": payload.deal_winner.value,
            "score_after": _score_data(payload.score_after),
            "score_before": _score_data(payload.score_before),
            "transition_kind": payload.transition_kind.value,
        }
    elif isinstance(payload, DealerRotatedPayload):
        payload_data = {
            "dealer_after": payload.dealer_after,
            "dealer_before": payload.dealer_before,
        }
    elif isinstance(payload, MatchCompletedPayload):
        payload_data = {
            "final_score": _score_data(payload.final_score),
            "winner_team": payload.winner_team.value,
        }
    else:
        raise SerializationError("unknown public event payload")
    return {
        "deal_ref": event.deal_ref,
        "event_index": event.event_index,
        "event_type": event.event_type.value,
        "match_ref": event.match_ref,
        "payload": payload_data,
        "ruleset_id": event.ruleset_id.value,
        "schema_version": event.schema_version,
    }


def public_event_log_to_data(
    events: tuple[PublicEvent, ...], *, match_ref: str
) -> dict[str, object]:
    return _event_sequence_to_data(events, match_ref=match_ref, require_zero=True)


def _event_sequence_to_data(
    events: tuple[PublicEvent, ...], *, match_ref: str, require_zero: bool
) -> dict[str, object]:
    if type(events) is not tuple:
        raise SerializationError("events must be an immutable tuple")
    if not is_valid_match_ref(match_ref):
        raise SerializationError("match_ref does not match the public schema")
    event_data = [event_to_data(event) for event in events]
    if require_zero and (
        not events or events[0].event_type is not EventType.DEAL_STARTED
    ):
        raise SerializationError("public event log must begin with deal_started")
    start = 0 if require_zero or not events else events[0].event_index
    if [event.event_index for event in events] != list(range(start, start + len(events))):
        qualifier = " from zero" if require_zero else ""
        raise SerializationError(f"event indices must be contiguous{qualifier}")
    if any(event.match_ref != match_ref for event in events):
        raise SerializationError("event belongs to a different match_ref")
    identity = {
        "events": event_data,
        "match_ref": match_ref,
        "ruleset_id": RULESET_ID.value,
        "schema_version": PUBLIC_EVENT_LOG_SCHEMA_VERSION,
    }
    return {**identity, "event_log_id": _digest(identity)}


def observation_to_data(observation: PlayerObservation) -> dict[str, object]:
    if not isinstance(observation, PlayerObservation):
        raise SerializationError("observation must be a PlayerObservation")
    return {
        "completed_tricks": [
            completed_trick_to_data(trick) for trick in observation.completed_tricks
        ],
        "contract": None if observation.contract is None else observation.contract.value,
        "current_actor": observation.current_actor,
        "current_trick": [_played_card_data(play) for play in observation.current_trick],
        "deal_ref": observation.deal_ref,
        "deal_terminal": observation.deal_terminal,
        "dealer": observation.dealer,
        "declarer": observation.declarer,
        "first_leader": observation.first_leader,
        "forehand": observation.forehand,
        "legal_actions": [action_to_data(action) for action in observation.legal_actions],
        "match_ref": observation.match_ref,
        "match_score": _score_data(observation.match_score),
        "match_terminal": observation.match_terminal,
        "observing_seat": observation.observing_seat,
        "own_hand": [card_to_code(card) for card in observation.own_hand],
        "partner_seat": observation.partner_seat,
        "phase": observation.phase.value,
        "publicly_shown_cards": [
            {"card": card_to_code(card), "seat": seat}
            for seat, card in observation.publicly_shown_cards
        ],
        "ruleset_id": observation.ruleset_id.value,
        "schema_version": observation.schema_version,
        "show_actions": [_show_data(show) for show in observation.show_actions],
        "team": observation.team.value,
        "team_tricks": list(observation.team_tricks),
        "visibility": observation.visibility,
    }


def deal_result_to_data(result: DealResult) -> dict[str, object]:
    if not isinstance(result, DealResult):
        raise SerializationError("result must be a DealResult")
    event_log = _event_sequence_to_data(
        result.events, match_ref=result.match_ref, require_zero=False
    )
    return {
        "contract": result.contract.value,
        "deal_number": result.deal_number,
        "deal_ref": result.deal_ref,
        "deal_score": {
            "declaring_team": (
                None
                if result.deal_score.declaring_team is None
                else result.deal_score.declaring_team.value
            ),
            "points": result.deal_score.points,
            "stolen_rami": result.deal_score.stolen_rami,
            "winner_team": result.deal_score.winner_team.value,
        },
        "dealer": result.dealer,
        "declarer": result.declarer,
        "event_log_id": event_log["event_log_id"],
        "events": event_log["events"],
        "first_leader": result.first_leader,
        "forehand": result.forehand,
        "match_ref": result.match_ref,
        "match_terminal": result.match_terminal,
        "next_dealer": result.next_dealer,
        "outcome": result.outcome.value,
        "ruleset_id": result.ruleset_id.value,
        "schema_version": result.schema_version,
        "score_after": _score_data(result.score_after),
        "score_before": _score_data(result.score_before),
        "show_actions": [_show_data(show) for show in result.show_actions],
        "team_tricks": list(result.team_tricks),
        "tricks": [completed_trick_to_data(trick) for trick in result.completed_tricks],
    }


def match_result_to_data(result: MatchResult) -> dict[str, object]:
    if not isinstance(result, MatchResult):
        raise SerializationError("result must be a MatchResult")
    event_log = public_event_log_to_data(result.events, match_ref=result.match_ref)
    return {
        "deals": [deal_result_to_data(deal) for deal in result.deals],
        "event_log_id": event_log["event_log_id"],
        "events": event_log["events"],
        "final_score": _score_data(result.final_score),
        "initial_dealer": result.initial_dealer,
        "initial_score": _score_data(result.initial_score),
        "match_ref": result.match_ref,
        "ruleset_id": result.ruleset_id.value,
        "schema_version": result.schema_version,
        "winner_team": result.winner_team.value,
    }


def explicit_deal_to_data(deal: ExplicitDeal) -> dict[str, object]:
    if not isinstance(deal, ExplicitDeal):
        raise SerializationError("deal must be an ExplicitDeal")
    return {
        "card_encoding": deal.card_encoding,
        "deal_id": deal.deal_id,
        "dealer": deal.dealer,
        "hands": [[card_to_code(card) for card in hand] for hand in deal.hands],
        "ruleset_id": deal.ruleset_id.value,
        "schema_version": deal.schema_version,
    }


@dataclass(frozen=True, slots=True, init=False)
class ExplicitMatchInput:
    match_input_id: str
    match_ref: str
    initial_score: MatchScore
    initial_dealer: int
    deals: tuple[ExplicitDeal, ...]
    schema_version: str = field(default=MATCH_INPUT_SCHEMA_VERSION, init=False)
    ruleset_id: RulesetId = field(default=RulesetId.PROJECT_TARGET_V1, init=False)

    def __init__(
        self,
        *,
        match_ref: str,
        initial_score: MatchScore,
        initial_dealer: int,
        deals: tuple[ExplicitDeal, ...],
        claimed_match_input_id: str | None = None,
    ) -> None:
        if not is_valid_match_ref(match_ref):
            raise SerializationError("match_ref contains unsupported characters")
        if not isinstance(initial_score, MatchScore):
            raise SerializationError("initial_score must be a MatchScore")
        try:
            checked_score = MatchScore(initial_score.team0, initial_score.team1)
        except RulesError as exc:
            raise SerializationError(f"invalid initial_score: {exc}") from exc
        if is_match_terminal(checked_score):
            raise SerializationError("initial_score must be nonterminal")
        if type(initial_dealer) is not int or initial_dealer not in range(4):
            raise SerializationError("initial_dealer must be an integer in 0..3")
        if type(deals) is not tuple or not deals or any(
            not isinstance(deal, ExplicitDeal) for deal in deals
        ):
            raise SerializationError("deals must be a nonempty ExplicitDeal tuple")
        for index, deal in enumerate(deals):
            expected = (initial_dealer + index) % 4
            if deal.dealer != expected:
                raise SerializationError(
                    f"deal {index} dealer {deal.dealer} does not match expected {expected}"
                )
        computed = calculate_match_input_id(
            initial_score=checked_score,
            initial_dealer=initial_dealer,
            deals=deals,
        )
        if claimed_match_input_id is not None and claimed_match_input_id != computed:
            raise SerializationError(
                "claimed match_input_id does not match canonical input"
            )
        object.__setattr__(self, "match_input_id", computed)
        object.__setattr__(self, "match_ref", match_ref)
        object.__setattr__(self, "initial_score", checked_score)
        object.__setattr__(self, "initial_dealer", initial_dealer)
        object.__setattr__(self, "deals", deals)
        object.__setattr__(self, "schema_version", MATCH_INPUT_SCHEMA_VERSION)
        object.__setattr__(self, "ruleset_id", RulesetId.PROJECT_TARGET_V1)


def match_input_to_data(value: ExplicitMatchInput) -> dict[str, object]:
    if not isinstance(value, ExplicitMatchInput):
        raise SerializationError("value must be an ExplicitMatchInput")
    return {
        "deals": [explicit_deal_to_data(deal) for deal in value.deals],
        "initial_dealer": value.initial_dealer,
        "initial_score": _score_data(value.initial_score),
        "match_input_id": value.match_input_id,
        "match_ref": value.match_ref,
        "ruleset_id": value.ruleset_id.value,
        "schema_version": value.schema_version,
    }


def research_deal_result_to_data(result: ResearchDealResult) -> dict[str, object]:
    if not isinstance(result, ResearchDealResult):
        raise SerializationError("result must be a ResearchDealResult")
    return {
        "deal_id": result.deal_id,
        "initial_hands": [
            [card_to_code(card) for card in hand] for hand in result.initial_hands
        ],
        "public_result": deal_result_to_data(result.public_result),
    }


def research_run_result_to_data(result: ResearchRunResult) -> dict[str, object]:
    if not isinstance(result, ResearchRunResult):
        raise SerializationError("result must be a ResearchRunResult")
    event_log = public_event_log_to_data(
        result.public_events, match_ref=result.match_ref
    )
    return {
        "agent_ids": list(result.agent_ids),
        "contains_hidden_information": result.contains_hidden_information,
        "deals": [research_deal_result_to_data(deal) for deal in result.deals],
        "event_log_id": event_log["event_log_id"],
        "execution_status": result.execution_status,
        "final_score": _score_data(result.final_score),
        "initial_dealer": result.initial_dealer,
        "initial_score": _score_data(result.initial_score),
        "match_input_id": result.match_input_id,
        "match_ref": result.match_ref,
        "match_result": (
            None if result.match_result is None else match_result_to_data(result.match_result)
        ),
        "next_dealer": result.next_dealer,
        "public_events": event_log["events"],
        "ruleset_id": result.ruleset_id.value,
        "schema_version": result.schema_version,
        "terminal": result.terminal,
        "visibility": result.visibility,
    }


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SerializationError(f"duplicate JSON object key {key!r}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise SerializationError(f"non-finite JSON number {value!r} is forbidden")


def strict_json_loads(text: str) -> object:
    if not isinstance(text, str):
        raise SerializationError("JSON input must be text")
    try:
        return json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except SerializationError:
        raise
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise SerializationError(f"invalid JSON: {exc}") from exc


def strict_json_load_file(path: str | Path) -> object:
    if str(path) == "-":
        raise SerializationError("stdin is not a supported input source")
    target = Path(path)
    try:
        metadata = target.stat()
        if not stat.S_ISREG(metadata.st_mode):
            raise SerializationError("JSON input must be a regular file")
        return strict_json_loads(target.read_text(encoding="utf-8"))
    except SerializationError:
        raise
    except (OSError, UnicodeError) as exc:
        raise SerializationError(f"cannot read JSON input {path!s}: {exc}") from exc


def _require_object(value: object, label: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise SerializationError(f"{label} must be a JSON object")
    return value


def _require_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        raise SerializationError(
            f"{label} fields differ; missing={missing}, unknown={unknown}"
        )


def _parse_card(value: object, label: str) -> Card:
    if not isinstance(value, str):
        raise SerializationError(f"{label} must be a canonical card code")
    try:
        card = card_from_code(value)
    except RulesError as exc:
        raise SerializationError(
            f"{label} is not a valid canonical card code"
        ) from exc
    if card_to_code(card) != value:
        raise SerializationError(f"{label} must use canonical uppercase card syntax")
    return card


def explicit_deal_from_data(value: object) -> ExplicitDeal:
    obj = _require_object(value, "explicit deal")
    expected = {
        "card_encoding",
        "deal_id",
        "dealer",
        "hands",
        "ruleset_id",
        "schema_version",
    }
    _require_keys(obj, expected, "explicit deal")
    if obj["schema_version"] != EXPLICIT_DEAL_SCHEMA_VERSION:
        raise SerializationError("unsupported explicit deal schema_version")
    if obj["ruleset_id"] != RulesetId.PROJECT_TARGET_V1.value:
        raise SerializationError("explicit deal ruleset_id must be project_target_v1")
    if obj["card_encoding"] != CARD_ENCODING_ID:
        raise SerializationError("unsupported card_encoding")
    if not is_sha256_identifier(obj["deal_id"]):
        raise SerializationError("deal_id must be a canonical sha256 identifier")
    hands_data = obj["hands"]
    if type(hands_data) is not list or len(hands_data) != 4:
        raise SerializationError("explicit deal must contain exactly four hands")
    hands: list[tuple[Card, ...]] = []
    for seat, hand_data in enumerate(hands_data):
        if type(hand_data) is not list or len(hand_data) != 13:
            raise SerializationError(f"seat {seat} hand must contain exactly 13 cards")
        hands.append(
            tuple(
                _parse_card(card, f"seat {seat} card {position}")
                for position, card in enumerate(hand_data)
            )
        )
    try:
        return ExplicitDeal(
            dealer=obj["dealer"],
            hands=tuple(hands),
            claimed_deal_id=obj["deal_id"],
        )
    except (RulesError, ValueError) as exc:
        raise SerializationError(f"invalid explicit deal: {exc}") from exc


def _parse_score(value: object, label: str) -> MatchScore:
    if type(value) is not list or len(value) != 2:
        raise SerializationError(f"{label} must be a two-integer array")
    try:
        return MatchScore(value[0], value[1])
    except RulesError as exc:
        raise SerializationError(f"invalid {label}: {exc}") from exc


def match_input_from_data(value: object) -> ExplicitMatchInput:
    obj = _require_object(value, "match input")
    expected = {
        "deals",
        "initial_dealer",
        "initial_score",
        "match_input_id",
        "match_ref",
        "ruleset_id",
        "schema_version",
    }
    _require_keys(obj, expected, "match input")
    if obj["schema_version"] != MATCH_INPUT_SCHEMA_VERSION:
        raise SerializationError("unsupported match input schema_version")
    if obj["ruleset_id"] != RulesetId.PROJECT_TARGET_V1.value:
        raise SerializationError("match input ruleset_id must be project_target_v1")
    if not is_sha256_identifier(obj["match_input_id"]):
        raise SerializationError(
            "match_input_id must be a canonical sha256 identifier"
        )
    deals_data = obj["deals"]
    if type(deals_data) is not list or not deals_data:
        raise SerializationError("match input deals must be a nonempty array")
    deals = tuple(explicit_deal_from_data(item) for item in deals_data)
    return ExplicitMatchInput(
        match_ref=obj["match_ref"],
        initial_score=_parse_score(obj["initial_score"], "initial_score"),
        initial_dealer=obj["initial_dealer"],
        deals=deals,
        claimed_match_input_id=obj["match_input_id"],
    )


def action_from_data(value: object) -> Action:
    obj = _require_object(value, "script action")
    action_type = obj.get("type")
    if action_type == "show":
        _require_keys(
            obj,
            {"declared_contract", "seat", "shown_card", "type"},
            "show action",
        )
        try:
            contract = Contract(obj["declared_contract"])
        except (TypeError, ValueError) as exc:
            raise SerializationError("show action has an invalid contract") from exc
        try:
            return ShowAction(
                seat=obj["seat"],
                shown_card=_parse_card(obj["shown_card"], "shown_card"),
                declared_contract=contract,
            )
        except EngineValidationError as exc:
            raise SerializationError(f"invalid show action: {exc}") from exc
    if action_type == "play":
        _require_keys(obj, {"card", "seat", "type"}, "play action")
        try:
            return PlayCardAction(
                seat=obj["seat"], card=_parse_card(obj["card"], "played card")
            )
        except EngineValidationError as exc:
            raise SerializationError(f"invalid play action: {exc}") from exc
    raise SerializationError("script action type must be 'show' or 'play'")


def agent_script_to_data(
    actions: tuple[Action, ...], *, match_input_id: str
) -> dict[str, object]:
    if type(actions) is not tuple or not actions:
        raise SerializationError("agent script actions must be a nonempty tuple")
    if not is_sha256_identifier(match_input_id):
        raise SerializationError("match_input_id must be a canonical sha256 identifier")
    return {
        "actions": [action_to_data(action) for action in actions],
        "match_input_id": match_input_id,
        "ruleset_id": RULESET_ID.value,
        "schema_version": AGENT_SCRIPT_SCHEMA_VERSION,
    }


def agent_script_from_data(
    value: object, *, expected_match_input_id: str
) -> tuple[Action, ...]:
    if not is_sha256_identifier(expected_match_input_id):
        raise SerializationError("expected_match_input_id must be canonical sha256")
    obj = _require_object(value, "agent script")
    _require_keys(
        obj,
        {"actions", "match_input_id", "ruleset_id", "schema_version"},
        "agent script",
    )
    if obj["schema_version"] != AGENT_SCRIPT_SCHEMA_VERSION:
        raise SerializationError("unsupported agent script schema_version")
    if obj["ruleset_id"] != RULESET_ID.value:
        raise SerializationError("agent script ruleset_id must be project_target_v1")
    if obj["match_input_id"] != expected_match_input_id:
        raise SerializationError("agent script belongs to a different match input")
    actions_data = obj["actions"]
    if type(actions_data) is not list or not actions_data:
        raise SerializationError("agent script actions must be a nonempty array")
    return tuple(action_from_data(item) for item in actions_data)


def _validate_output_target(target: Path) -> None:
    parent = target.parent
    if not parent.exists() or not parent.is_dir():
        raise SerializationError("output parent directory does not exist")
    try:
        metadata = target.lstat()
    except FileNotFoundError:
        return
    except OSError as exc:
        raise SerializationError(f"cannot inspect output {target}: {exc}") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise SerializationError("existing output destination must be a regular file")


def atomic_write_canonical_json_bundle(
    outputs: tuple[tuple[str | Path, object], ...],
) -> None:
    """Preflight and stage one or more canonical outputs before replacement."""

    if type(outputs) is not tuple or not outputs:
        raise SerializationError("output bundle must be a nonempty tuple")
    targets: list[Path] = []
    payloads: list[bytes] = []
    for item in outputs:
        if type(item) is not tuple or len(item) != 2:
            raise SerializationError("each output bundle item must be a path/value pair")
        path, value = item
        if str(path) == "-":
            raise SerializationError("stdout is not an authoritative output destination")
        target = Path(path)
        _validate_output_target(target)
        targets.append(target)
        payloads.append(canonical_json_bytes(value) + b"\n")
    if len({target.resolve() for target in targets}) != len(targets):
        raise SerializationError("output bundle destinations must differ")

    staged: list[str] = []
    try:
        for target, payload in zip(targets, payloads, strict=True):
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
            )
            staged.append(temporary_name)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
        for temporary_name, target in zip(staged, targets, strict=True):
            os.replace(temporary_name, target)
            temporary_name = ""
    except OSError as exc:
        raise SerializationError(f"cannot write output bundle: {exc}") from exc
    finally:
        for temporary_name in staged:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)


def atomic_write_canonical_json(path: str | Path, value: object) -> None:
    atomic_write_canonical_json_bundle(((path, value),))
