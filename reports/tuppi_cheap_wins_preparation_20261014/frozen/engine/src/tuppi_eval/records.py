"""Canonical immutable game, duplicate-block, run, and promotion records."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import json
from typing import Any

from .errors import EvaluationValidationError
from .serialization import (
    canonical_json_text,
    content_digest,
    require_exact_keys,
    require_object,
)


GAME_RECORD_SCHEMA_VERSION = "tuppi.eval.game_record.v1"
DUPLICATE_BLOCK_SCHEMA_VERSION = "tuppi.eval.duplicate_block_record.v1"
EVALUATION_RESULT_SCHEMA_VERSION = "tuppi.eval.evaluation_result.v1"
PROMOTION_DECISION_SCHEMA_VERSION = "tuppi.eval.promotion_decision.v1"


class ExecutionStatus(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"


class FailureKind(StrEnum):
    INVALID_CONFIGURATION = "invalid_configuration"
    INVALID_DEAL_BANK = "invalid_deal_bank"
    AGENT_CONSTRUCTION = "agent_construction_failure"
    ILLEGAL_AGENT_ACTION = "illegal_agent_action"
    ENGINE_INVARIANT = "engine_invariant_failure"
    TIMEOUT = "timeout"
    SERIALIZATION = "serialization_failure"
    INTERRUPTED = "interrupted_run"
    AGENT_PROTOCOL = "agent_protocol_failure"
    INSUFFICIENT_MATCH_DEALS = "insufficient_match_deals"
    UNEXPECTED = "unexpected_failure"


class PromotionOutcome(StrEnum):
    PROMOTED = "promoted"
    REJECTED = "rejected"
    INCONCLUSIVE = "inconclusive"
    INVALID_RUN = "invalid_run"


@dataclass(frozen=True, slots=True)
class FailureDetails:
    kind: FailureKind
    exception_type: str
    message: str
    acting_seat: int | None
    action_index: int | None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, FailureKind):
            raise EvaluationValidationError("failure kind is invalid")
        if not self.exception_type or not isinstance(self.exception_type, str):
            raise EvaluationValidationError("failure exception_type is required")
        if not isinstance(self.message, str):
            raise EvaluationValidationError("failure message must be a string")
        if self.acting_seat is not None and self.acting_seat not in range(4):
            raise EvaluationValidationError("failure acting_seat must be null or 0..3")
        if self.action_index is not None and (
            type(self.action_index) is not int or self.action_index < 0
        ):
            raise EvaluationValidationError("failure action_index must be nonnegative")

    def to_data(self) -> dict[str, object]:
        return {
            "acting_seat": self.acting_seat,
            "action_index": self.action_index,
            "exception_type": self.exception_type,
            "kind": self.kind.value,
            "message": self.message,
        }


@dataclass(frozen=True, slots=True)
class GameRecord:
    record_id: str
    evaluation_id: str
    entry_id: str
    base_deal_id: str
    transformation_id: str
    transformed_deal_id: str
    schedule_position: int
    block_index: int
    evaluation_mode: str
    ruleset_id: str
    engine_identity: str
    seat_team_ids: tuple[str, str, str, str]
    seat_agent_ids: tuple[str, str, str, str]
    seat_external_teams: tuple[str, str, str, str]
    dealer: int
    forehand: int
    starting_score: tuple[int, int]
    contract: str | None
    declarer: int | None
    declaring_engine_team: int | None
    declaring_external_team: str | None
    first_leader: int | None
    team_tricks: tuple[int, int] | None
    winner_engine_team: int | None
    winner_external_team: str | None
    deal_points: int | None
    score_after: tuple[int, int] | None
    reset: bool | None
    terminal: bool | None
    match_winner_external_team: str | None
    deals_played: int
    execution_status: ExecutionStatus
    failure: FailureDetails | None
    raw_result_digest: str | None
    event_log_id: str | None
    agent_seeds: tuple[str | None, str | None, str | None, str | None]
    determinism_metadata_json: str
    duration_seconds: float
    action_durations_seconds: tuple[float, ...]
    schema_version: str = field(default=GAME_RECORD_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        if type(self.schedule_position) is not int or self.schedule_position < 0:
            raise EvaluationValidationError("schedule_position must be nonnegative")
        if type(self.block_index) is not int or self.block_index < 0:
            raise EvaluationValidationError("block_index must be nonnegative")
        for values in (
            self.seat_team_ids,
            self.seat_agent_ids,
            self.seat_external_teams,
            self.agent_seeds,
        ):
            if type(values) is not tuple or len(values) != 4:
                raise EvaluationValidationError("seat metadata must contain four values")
        if any(item not in ("A", "B") for item in self.seat_external_teams):
            raise EvaluationValidationError("external team mapping is invalid")
        if (
            type(self.dealer) is not int
            or self.dealer not in range(4)
            or type(self.forehand) is not int
            or self.forehand != (self.dealer + 1) % 4
        ):
            raise EvaluationValidationError("dealer or forehand is invalid")
        if (
            type(self.starting_score) is not tuple
            or len(self.starting_score) != 2
            or any(type(item) is not int or item < 0 for item in self.starting_score)
        ):
            raise EvaluationValidationError("starting_score must be a score pair")
        if type(self.deals_played) is not int or self.deals_played < 0:
            raise EvaluationValidationError("deals_played must be nonnegative")
        if self.evaluation_mode not in ("deal", "match"):
            raise EvaluationValidationError("evaluation_mode is invalid")
        if not isinstance(self.execution_status, ExecutionStatus):
            raise EvaluationValidationError("execution_status is invalid")
        if type(self.duration_seconds) not in (int, float) or self.duration_seconds < 0:
            raise EvaluationValidationError("duration_seconds must be nonnegative")
        if type(self.action_durations_seconds) is not tuple or any(
            type(value) not in (int, float) or value < 0
            for value in self.action_durations_seconds
        ):
            raise EvaluationValidationError("action durations are invalid")
        try:
            metadata = json.loads(self.determinism_metadata_json)
        except (json.JSONDecodeError, TypeError) as exc:
            raise EvaluationValidationError("determinism metadata is invalid") from exc
        if type(metadata) is not dict or (
            canonical_json_text(metadata) != self.determinism_metadata_json
        ):
            raise EvaluationValidationError(
                "determinism metadata must be a canonical JSON object"
            )
        if self.execution_status is ExecutionStatus.SUCCESS:
            required = (
                self.contract,
                self.first_leader,
                self.team_tricks,
                self.winner_engine_team,
                self.winner_external_team,
                self.deal_points,
                self.score_after,
                self.reset,
                self.terminal,
                self.raw_result_digest,
                self.event_log_id,
            )
            if any(item is None for item in required) or self.failure is not None:
                raise EvaluationValidationError("successful game lacks result fields")
            if self.contract == "RAMI" and (
                self.declarer is None
                or self.declaring_engine_team is None
                or self.declaring_external_team is None
            ):
                raise EvaluationValidationError("RAMI result lacks declarer metadata")
            if self.contract == "NOLO" and any(
                item is not None
                for item in (
                    self.declarer,
                    self.declaring_engine_team,
                    self.declaring_external_team,
                )
            ):
                raise EvaluationValidationError("NOLO result cannot have a declarer")
            if self.team_tricks is None or sum(self.team_tricks) != 13:
                raise EvaluationValidationError("successful game must account for 13 tricks")
            if self.winner_engine_team not in (0, 1) or (
                self.winner_external_team not in ("A", "B")
            ):
                raise EvaluationValidationError("successful game winner is invalid")
            if self.evaluation_mode == "match" and (
                self.terminal is not True
                or self.match_winner_external_team not in ("A", "B")
            ):
                raise EvaluationValidationError("successful match record is not terminal")
        else:
            if self.failure is None:
                raise EvaluationValidationError("failed game requires failure details")
            result_fields = (
                self.contract,
                self.declarer,
                self.declaring_engine_team,
                self.declaring_external_team,
                self.first_leader,
                self.team_tricks,
                self.winner_engine_team,
                self.winner_external_team,
                self.deal_points,
                self.score_after,
                self.reset,
                self.terminal,
                self.match_winner_external_team,
                self.raw_result_digest,
                self.event_log_id,
            )
            if any(item is not None for item in result_fields):
                raise EvaluationValidationError(
                    "failed game must not masquerade as an ordinary outcome"
                )
        if self.record_id != f"game:{content_digest(self.semantic_data())}":
            raise EvaluationValidationError("game record identity is invalid")

    @property
    def determinism_metadata(self) -> dict[str, Any]:
        return json.loads(self.determinism_metadata_json)

    @property
    def signed_utility(self) -> float | None:
        if self.execution_status is not ExecutionStatus.SUCCESS:
            return None
        if self.evaluation_mode == "match":
            if self.match_winner_external_team is None:
                return None
            return 1.0 if self.match_winner_external_team == "A" else -1.0
        assert self.deal_points is not None and self.winner_external_team is not None
        return float(self.deal_points if self.winner_external_team == "A" else -self.deal_points)

    def semantic_data(self) -> dict[str, object]:
        return {
            "agent_seeds": list(self.agent_seeds),
            "base_deal_id": self.base_deal_id,
            "block_index": self.block_index,
            "contract": self.contract,
            "deal_points": self.deal_points,
            "dealer": self.dealer,
            "deals_played": self.deals_played,
            "declarer": self.declarer,
            "declaring_engine_team": self.declaring_engine_team,
            "declaring_external_team": self.declaring_external_team,
            "determinism_metadata": self.determinism_metadata,
            "engine_identity": self.engine_identity,
            "entry_id": self.entry_id,
            "evaluation_id": self.evaluation_id,
            "evaluation_mode": self.evaluation_mode,
            "event_log_id": self.event_log_id,
            "execution_status": self.execution_status.value,
            "failure": None if self.failure is None else self.failure.to_data(),
            "first_leader": self.first_leader,
            "forehand": self.forehand,
            "match_winner_external_team": self.match_winner_external_team,
            "raw_result_digest": self.raw_result_digest,
            "reset": self.reset,
            "ruleset_id": self.ruleset_id,
            "schedule_position": self.schedule_position,
            "schema_version": self.schema_version,
            "score_after": None if self.score_after is None else list(self.score_after),
            "seat_agent_ids": list(self.seat_agent_ids),
            "seat_external_teams": list(self.seat_external_teams),
            "seat_team_ids": list(self.seat_team_ids),
            "starting_score": list(self.starting_score),
            "team_tricks": None if self.team_tricks is None else list(self.team_tricks),
            "terminal": self.terminal,
            "transformation_id": self.transformation_id,
            "transformed_deal_id": self.transformed_deal_id,
            "winner_engine_team": self.winner_engine_team,
            "winner_external_team": self.winner_external_team,
        }


def game_record_to_data(record: GameRecord) -> dict[str, object]:
    return {
        **record.semantic_data(),
        "action_durations_seconds": list(record.action_durations_seconds),
        "duration_seconds": record.duration_seconds,
        "record_id": record.record_id,
    }


def _tuple4(value: object, label: str) -> tuple:
    if type(value) is not list or len(value) != 4:
        raise EvaluationValidationError(f"{label} must contain four values")
    return tuple(value)


def _pair(value: object, label: str, *, nullable: bool) -> tuple[int, int] | None:
    if value is None and nullable:
        return None
    if type(value) is not list or len(value) != 2:
        raise EvaluationValidationError(f"{label} must contain two integers")
    return (value[0], value[1])


def game_record_from_data(value: object) -> GameRecord:
    obj = require_object(value, "game record")
    semantic_keys = {
        "agent_seeds", "base_deal_id", "block_index", "contract",
        "deal_points", "dealer", "deals_played", "declarer",
        "declaring_engine_team", "declaring_external_team",
        "determinism_metadata", "engine_identity", "entry_id", "evaluation_id",
        "evaluation_mode", "event_log_id", "execution_status", "failure",
        "first_leader", "forehand", "match_winner_external_team",
        "raw_result_digest", "reset", "ruleset_id", "schedule_position",
        "schema_version", "score_after", "seat_agent_ids",
        "seat_external_teams", "seat_team_ids", "starting_score", "team_tricks",
        "terminal", "transformation_id", "transformed_deal_id",
        "winner_engine_team", "winner_external_team",
    }
    require_exact_keys(
        obj,
        semantic_keys | {"action_durations_seconds", "duration_seconds", "record_id"},
        "game record",
    )
    if obj["schema_version"] != GAME_RECORD_SCHEMA_VERSION:
        raise EvaluationValidationError("unsupported game-record schema_version")
    failure = None
    if obj["failure"] is not None:
        raw = require_object(obj["failure"], "failure")
        require_exact_keys(
            raw,
            {"acting_seat", "action_index", "exception_type", "kind", "message"},
            "failure",
        )
        failure = FailureDetails(
            kind=FailureKind(raw["kind"]),
            exception_type=raw["exception_type"],
            message=raw["message"],
            acting_seat=raw["acting_seat"],
            action_index=raw["action_index"],
        )
    durations = obj["action_durations_seconds"]
    if type(durations) is not list:
        raise EvaluationValidationError("action durations must be an array")
    return GameRecord(
        record_id=obj["record_id"],
        evaluation_id=obj["evaluation_id"],
        entry_id=obj["entry_id"],
        base_deal_id=obj["base_deal_id"],
        transformation_id=obj["transformation_id"],
        transformed_deal_id=obj["transformed_deal_id"],
        schedule_position=obj["schedule_position"],
        block_index=obj["block_index"],
        evaluation_mode=obj["evaluation_mode"],
        ruleset_id=obj["ruleset_id"],
        engine_identity=obj["engine_identity"],
        seat_team_ids=_tuple4(obj["seat_team_ids"], "seat_team_ids"),
        seat_agent_ids=_tuple4(obj["seat_agent_ids"], "seat_agent_ids"),
        seat_external_teams=_tuple4(
            obj["seat_external_teams"], "seat_external_teams"
        ),
        dealer=obj["dealer"],
        forehand=obj["forehand"],
        starting_score=_pair(obj["starting_score"], "starting_score", nullable=False),  # type: ignore[arg-type]
        contract=obj["contract"],
        declarer=obj["declarer"],
        declaring_engine_team=obj["declaring_engine_team"],
        declaring_external_team=obj["declaring_external_team"],
        first_leader=obj["first_leader"],
        team_tricks=_pair(obj["team_tricks"], "team_tricks", nullable=True),
        winner_engine_team=obj["winner_engine_team"],
        winner_external_team=obj["winner_external_team"],
        deal_points=obj["deal_points"],
        score_after=_pair(obj["score_after"], "score_after", nullable=True),
        reset=obj["reset"],
        terminal=obj["terminal"],
        match_winner_external_team=obj["match_winner_external_team"],
        deals_played=obj["deals_played"],
        execution_status=ExecutionStatus(obj["execution_status"]),
        failure=failure,
        raw_result_digest=obj["raw_result_digest"],
        event_log_id=obj["event_log_id"],
        agent_seeds=_tuple4(obj["agent_seeds"], "agent_seeds"),
        determinism_metadata_json=canonical_json_text(
            require_object(obj["determinism_metadata"], "determinism_metadata")
        ),
        duration_seconds=obj["duration_seconds"],
        action_durations_seconds=tuple(durations),
    )


@dataclass(frozen=True, slots=True)
class DuplicateBlockRecord:
    block_record_id: str
    evaluation_id: str
    block_index: int
    base_deal_id: str
    game_record_ids: tuple[str, ...]
    valid_game_count: int
    invalid_game_count: int
    complete: bool
    paired_utility: float | None
    block_outcome: str | None
    schema_version: str = field(default=DUPLICATE_BLOCK_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        if type(self.game_record_ids) is not tuple or len(self.game_record_ids) != 8:
            raise EvaluationValidationError(
                "canonical duplicate block requires eight game records"
            )
        if len(set(self.game_record_ids)) != 8:
            raise EvaluationValidationError("duplicate block game IDs must be unique")
        for label, count in (
            ("valid_game_count", self.valid_game_count),
            ("invalid_game_count", self.invalid_game_count),
        ):
            if type(count) is not int or count < 0:
                raise EvaluationValidationError(f"{label} must be nonnegative")
        if self.valid_game_count + self.invalid_game_count != len(self.game_record_ids):
            raise EvaluationValidationError("duplicate block counts are inconsistent")
        if self.complete != (self.invalid_game_count == 0):
            raise EvaluationValidationError("duplicate block complete flag is invalid")
        if self.complete:
            if self.paired_utility is None or self.block_outcome not in ("win", "tie", "loss"):
                raise EvaluationValidationError("complete block lacks paired outcome")
        elif self.paired_utility is not None or self.block_outcome is not None:
            raise EvaluationValidationError("incomplete block cannot enter paired inference")
        if self.block_record_id != f"block:{content_digest(self.identity_data())}":
            raise EvaluationValidationError("duplicate-block identity is invalid")

    def identity_data(self) -> dict[str, object]:
        return {
            "base_deal_id": self.base_deal_id,
            "block_index": self.block_index,
            "block_outcome": self.block_outcome,
            "complete": self.complete,
            "evaluation_id": self.evaluation_id,
            "game_record_ids": list(self.game_record_ids),
            "invalid_game_count": self.invalid_game_count,
            "paired_utility": self.paired_utility,
            "schema_version": self.schema_version,
            "valid_game_count": self.valid_game_count,
        }


def build_duplicate_block(records: tuple[GameRecord, ...]) -> DuplicateBlockRecord:
    if type(records) is not tuple or not records:
        raise EvaluationValidationError("cannot build an empty duplicate block")
    block_indices = {record.block_index for record in records}
    base_ids = {record.base_deal_id for record in records}
    evaluation_ids = {record.evaluation_id for record in records}
    if len(block_indices) != 1 or len(base_ids) != 1 or len(evaluation_ids) != 1:
        raise EvaluationValidationError("duplicate block records do not share an unit")
    ordered = tuple(sorted(records, key=lambda item: item.schedule_position))
    if len(ordered) != 8:
        raise EvaluationValidationError(
            "canonical duplicate blocks require exactly eight game records"
        )
    if len({record.entry_id for record in ordered}) != 8:
        raise EvaluationValidationError("duplicate block contains repeated entries")
    valid = tuple(
        record for record in ordered if record.execution_status is ExecutionStatus.SUCCESS
    )
    complete = len(valid) == len(ordered)
    utility = (
        sum(record.signed_utility for record in valid) / len(valid)  # type: ignore[arg-type]
        if complete
        else None
    )
    outcome = None
    if utility is not None:
        outcome = "win" if utility > 0 else "loss" if utility < 0 else "tie"
    identity = {
        "base_deal_id": ordered[0].base_deal_id,
        "block_index": ordered[0].block_index,
        "block_outcome": outcome,
        "complete": complete,
        "evaluation_id": ordered[0].evaluation_id,
        "game_record_ids": [record.record_id for record in ordered],
        "invalid_game_count": len(ordered) - len(valid),
        "paired_utility": utility,
        "schema_version": DUPLICATE_BLOCK_SCHEMA_VERSION,
        "valid_game_count": len(valid),
    }
    return DuplicateBlockRecord(
        block_record_id=f"block:{content_digest(identity)}",
        evaluation_id=ordered[0].evaluation_id,
        block_index=ordered[0].block_index,
        base_deal_id=ordered[0].base_deal_id,
        game_record_ids=tuple(record.record_id for record in ordered),
        valid_game_count=len(valid),
        invalid_game_count=len(ordered) - len(valid),
        complete=complete,
        paired_utility=utility,
        block_outcome=outcome,
    )


def duplicate_block_to_data(record: DuplicateBlockRecord) -> dict[str, object]:
    return {**record.identity_data(), "block_record_id": record.block_record_id}


def duplicate_block_from_data(value: object) -> DuplicateBlockRecord:
    obj = require_object(value, "duplicate block")
    require_exact_keys(
        obj,
        {
            "base_deal_id",
            "block_index",
            "block_outcome",
            "block_record_id",
            "complete",
            "evaluation_id",
            "game_record_ids",
            "invalid_game_count",
            "paired_utility",
            "schema_version",
            "valid_game_count",
        },
        "duplicate block",
    )
    if obj["schema_version"] != DUPLICATE_BLOCK_SCHEMA_VERSION:
        raise EvaluationValidationError("unsupported duplicate-block schema_version")
    raw_ids = obj["game_record_ids"]
    if type(raw_ids) is not list:
        raise EvaluationValidationError("game_record_ids must be an array")
    return DuplicateBlockRecord(
        block_record_id=obj["block_record_id"],
        evaluation_id=obj["evaluation_id"],
        block_index=obj["block_index"],
        base_deal_id=obj["base_deal_id"],
        game_record_ids=tuple(raw_ids),
        valid_game_count=obj["valid_game_count"],
        invalid_game_count=obj["invalid_game_count"],
        complete=obj["complete"],
        paired_utility=obj["paired_utility"],
        block_outcome=obj["block_outcome"],
    )


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    result_id: str
    evaluation_id: str
    configuration_digest: str
    schedule_id: str
    deal_bank_id: str
    evaluation_mode: str
    game_records: tuple[GameRecord, ...]
    duplicate_blocks: tuple[DuplicateBlockRecord, ...]
    summary_json: str
    failure_count: int
    schema_version: str = field(default=EVALUATION_RESULT_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        if type(self.game_records) is not tuple or not self.game_records:
            raise EvaluationValidationError("evaluation result requires game records")
        if type(self.duplicate_blocks) is not tuple or not self.duplicate_blocks:
            raise EvaluationValidationError("evaluation result requires duplicate blocks")
        if tuple(record.schedule_position for record in self.game_records) != tuple(
            range(len(self.game_records))
        ):
            raise EvaluationValidationError("game records are not in canonical order")
        actual_failures = sum(
            record.execution_status is ExecutionStatus.FAILED
            for record in self.game_records
        )
        if self.failure_count != actual_failures:
            raise EvaluationValidationError("failure_count is inconsistent")
        if any(
            record.evaluation_id != self.evaluation_id
            for record in self.game_records
        ) or any(
            block.evaluation_id != self.evaluation_id
            for block in self.duplicate_blocks
        ):
            raise EvaluationValidationError("nested records use another evaluation ID")
        grouped: dict[int, list[GameRecord]] = {}
        for record in self.game_records:
            grouped.setdefault(record.block_index, []).append(record)
        rebuilt = tuple(
            build_duplicate_block(tuple(grouped[index])) for index in sorted(grouped)
        )
        if rebuilt != self.duplicate_blocks:
            raise EvaluationValidationError(
                "duplicate blocks disagree with their game records"
            )
        try:
            summary = json.loads(self.summary_json)
        except (json.JSONDecodeError, TypeError) as exc:
            raise EvaluationValidationError("summary is invalid JSON") from exc
        if type(summary) is not dict or canonical_json_text(summary) != self.summary_json:
            raise EvaluationValidationError("summary must be a canonical JSON object")
        if self.result_id != f"result:{content_digest(self.semantic_data())}":
            raise EvaluationValidationError("evaluation result identity is invalid")

    @property
    def summary(self) -> dict[str, Any]:
        return json.loads(self.summary_json)

    def semantic_data(self) -> dict[str, object]:
        summary = self.summary
        execution = summary.get("execution_metrics")
        if type(execution) is dict:
            summary["execution_metrics"] = {
                "decision_failure_rate": execution.get("decision_failure_rate"),
                "failed_games": execution.get("failed_games"),
                "successful_games": execution.get("successful_games"),
            }
        return {
            "configuration_digest": self.configuration_digest,
            "deal_bank_id": self.deal_bank_id,
            "duplicate_blocks": [item.identity_data() for item in self.duplicate_blocks],
            "evaluation_id": self.evaluation_id,
            "evaluation_mode": self.evaluation_mode,
            "failure_count": self.failure_count,
            "games": [item.semantic_data() for item in self.game_records],
            "schedule_id": self.schedule_id,
            "schema_version": self.schema_version,
            "summary": summary,
        }


def evaluation_result_to_data(result: EvaluationResult) -> dict[str, object]:
    return {
        "configuration_digest": result.configuration_digest,
        "deal_bank_id": result.deal_bank_id,
        "duplicate_blocks": [
            duplicate_block_to_data(item) for item in result.duplicate_blocks
        ],
        "evaluation_id": result.evaluation_id,
        "evaluation_mode": result.evaluation_mode,
        "failure_count": result.failure_count,
        "games": [game_record_to_data(item) for item in result.game_records],
        "result_id": result.result_id,
        "schedule_id": result.schedule_id,
        "schema_version": result.schema_version,
        "summary": result.summary,
    }


def evaluation_result_from_data(value: object) -> EvaluationResult:
    obj = require_object(value, "evaluation result")
    require_exact_keys(
        obj,
        {
            "configuration_digest",
            "deal_bank_id",
            "duplicate_blocks",
            "evaluation_id",
            "evaluation_mode",
            "failure_count",
            "games",
            "result_id",
            "schedule_id",
            "schema_version",
            "summary",
        },
        "evaluation result",
    )
    if obj["schema_version"] != EVALUATION_RESULT_SCHEMA_VERSION:
        raise EvaluationValidationError("unsupported evaluation-result schema_version")
    raw_games = obj["games"]
    raw_blocks = obj["duplicate_blocks"]
    if type(raw_games) is not list or type(raw_blocks) is not list:
        raise EvaluationValidationError("result games and blocks must be arrays")
    return EvaluationResult(
        result_id=obj["result_id"],
        evaluation_id=obj["evaluation_id"],
        configuration_digest=obj["configuration_digest"],
        schedule_id=obj["schedule_id"],
        deal_bank_id=obj["deal_bank_id"],
        evaluation_mode=obj["evaluation_mode"],
        game_records=tuple(game_record_from_data(item) for item in raw_games),
        duplicate_blocks=tuple(
            duplicate_block_from_data(item) for item in raw_blocks
        ),
        summary_json=canonical_json_text(require_object(obj["summary"], "summary")),
        failure_count=obj["failure_count"],
    )


@dataclass(frozen=True, slots=True)
class PromotionDecision:
    decision_id: str
    candidate_team_id: str
    champion_team_id: str
    evaluation_result_ids: tuple[str, ...]
    primary_metric: str
    confidence_interval: tuple[float, float] | None
    historical_agent_results_json: str
    contract_regressions_json: str
    score_state_regressions_json: str
    failure_rate: float
    latency_budget_seconds: float
    reproducible: bool
    outcome: PromotionOutcome
    rationale: str
    schema_version: str = field(default=PROMOTION_DECISION_SCHEMA_VERSION, init=False)

    @classmethod
    def build(
        cls,
        *,
        candidate_team_id: str,
        champion_team_id: str,
        evaluation_result_ids: tuple[str, ...],
        primary_metric: str,
        confidence_interval: tuple[float, float] | None,
        historical_agent_results: dict[str, Any],
        contract_regressions: dict[str, Any],
        score_state_regressions: dict[str, Any],
        failure_rate: float,
        latency_budget_seconds: float,
        reproducible: bool,
        outcome: PromotionOutcome,
        rationale: str,
        claimed_decision_id: str | None = None,
    ) -> "PromotionDecision":
        values = {
            "candidate_team_id": candidate_team_id,
            "champion_team_id": champion_team_id,
            "evaluation_result_ids": tuple(evaluation_result_ids),
            "primary_metric": primary_metric,
            "confidence_interval": confidence_interval,
            "historical_agent_results_json": canonical_json_text(
                historical_agent_results
            ),
            "contract_regressions_json": canonical_json_text(contract_regressions),
            "score_state_regressions_json": canonical_json_text(
                score_state_regressions
            ),
            "failure_rate": failure_rate,
            "latency_budget_seconds": latency_budget_seconds,
            "reproducible": reproducible,
            "outcome": outcome,
            "rationale": rationale,
        }
        provisional = object.__new__(cls)
        for name, item in values.items():
            object.__setattr__(provisional, name, item)
        object.__setattr__(
            provisional, "schema_version", PROMOTION_DECISION_SCHEMA_VERSION
        )
        computed = f"promotion:{content_digest(provisional.identity_data())}"
        return cls(decision_id=claimed_decision_id or computed, **values)

    def __post_init__(self) -> None:
        if type(self.evaluation_result_ids) is not tuple or not self.evaluation_result_ids:
            raise EvaluationValidationError("promotion requires evaluation results")
        if not 0 <= self.failure_rate <= 1:
            raise EvaluationValidationError("failure_rate must be in 0..1")
        if self.latency_budget_seconds <= 0:
            raise EvaluationValidationError("latency budget must be positive")
        if not isinstance(self.reproducible, bool) or not isinstance(
            self.outcome, PromotionOutcome
        ):
            raise EvaluationValidationError("promotion status is invalid")
        for value in (
            self.historical_agent_results_json,
            self.contract_regressions_json,
            self.score_state_regressions_json,
        ):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError as exc:
                raise EvaluationValidationError("promotion JSON field is invalid") from exc
            if canonical_json_text(parsed) != value:
                raise EvaluationValidationError("promotion JSON must be canonical")
        if not self.rationale:
            raise EvaluationValidationError("promotion rationale is required")
        if self.decision_id != f"promotion:{content_digest(self.identity_data())}":
            raise EvaluationValidationError("promotion decision identity is invalid")

    def identity_data(self) -> dict[str, object]:
        return {
            "candidate_team_id": self.candidate_team_id,
            "champion_team_id": self.champion_team_id,
            "confidence_interval": (
                None
                if self.confidence_interval is None
                else list(self.confidence_interval)
            ),
            "contract_regressions": json.loads(self.contract_regressions_json),
            "evaluation_result_ids": list(self.evaluation_result_ids),
            "failure_rate": self.failure_rate,
            "historical_agent_results": json.loads(
                self.historical_agent_results_json
            ),
            "latency_budget_seconds": self.latency_budget_seconds,
            "outcome": self.outcome.value,
            "primary_metric": self.primary_metric,
            "rationale": self.rationale,
            "reproducible": self.reproducible,
            "schema_version": self.schema_version,
            "score_state_regressions": json.loads(self.score_state_regressions_json),
        }


def promotion_decision_to_data(value: PromotionDecision) -> dict[str, object]:
    return {**value.identity_data(), "decision_id": value.decision_id}


def promotion_decision_from_data(value: object) -> PromotionDecision:
    obj = require_object(value, "promotion decision")
    expected = {
        "candidate_team_id",
        "champion_team_id",
        "confidence_interval",
        "contract_regressions",
        "decision_id",
        "evaluation_result_ids",
        "failure_rate",
        "historical_agent_results",
        "latency_budget_seconds",
        "outcome",
        "primary_metric",
        "rationale",
        "reproducible",
        "schema_version",
        "score_state_regressions",
    }
    require_exact_keys(obj, expected, "promotion decision")
    if obj["schema_version"] != PROMOTION_DECISION_SCHEMA_VERSION:
        raise EvaluationValidationError("unsupported promotion schema_version")
    raw_ids = obj["evaluation_result_ids"]
    if type(raw_ids) is not list:
        raise EvaluationValidationError("evaluation_result_ids must be an array")
    raw_interval = obj["confidence_interval"]
    if raw_interval is not None and (
        type(raw_interval) is not list or len(raw_interval) != 2
    ):
        raise EvaluationValidationError("confidence_interval must be null or a pair")
    try:
        outcome = PromotionOutcome(obj["outcome"])
    except (TypeError, ValueError) as exc:
        raise EvaluationValidationError("promotion outcome is invalid") from exc
    return PromotionDecision.build(
        candidate_team_id=obj["candidate_team_id"],
        champion_team_id=obj["champion_team_id"],
        evaluation_result_ids=tuple(raw_ids),
        primary_metric=obj["primary_metric"],
        confidence_interval=(
            None if raw_interval is None else (raw_interval[0], raw_interval[1])
        ),
        historical_agent_results=require_object(
            obj["historical_agent_results"], "historical_agent_results"
        ),
        contract_regressions=require_object(
            obj["contract_regressions"], "contract_regressions"
        ),
        score_state_regressions=require_object(
            obj["score_state_regressions"], "score_state_regressions"
        ),
        failure_rate=obj["failure_rate"],
        latency_budget_seconds=obj["latency_budget_seconds"],
        reproducible=obj["reproducible"],
        outcome=outcome,
        rationale=obj["rationale"],
        claimed_decision_id=obj["decision_id"],
    )
