"""Finite serial arena with canonical shards, quarantine, and deterministic resume."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from importlib.metadata import PackageNotFoundError, version
import json
from pathlib import Path
import platform
import subprocess
import sys
import time
from typing import Any

from tuppi_engine import (
    Agent,
    AgentProtocolError,
    EngineError,
    ExplicitMatchInput,
    InvalidActionError,
    ResearchRunResult,
    SerializationError as EngineSerializationError,
    StateInvariantError,
    action_from_data,
    begin_explicit_deal,
    create_match,
    match_result_from_state,
    play_active_deal,
    research_run_result_to_data,
)
from tuppi_rules import Team, team_for_seat

from .agents import construct_agent
from .config import EvaluationConfiguration, FailurePolicy, evaluation_config_to_data
from .deals import DealBank, deal_bank_to_data, derive_seed
from .errors import (
    ArenaError,
    EvaluationSerializationError,
    EvaluationTimeout,
    InterruptedEvaluation,
    RegistryError,
)
from .records import (
    EVALUATION_RESULT_SCHEMA_VERSION,
    GAME_RECORD_SCHEMA_VERSION,
    EvaluationResult,
    ExecutionStatus,
    FailureDetails,
    FailureKind,
    GameRecord,
    build_duplicate_block,
    evaluation_result_to_data,
    game_record_from_data,
    game_record_to_data,
)
from .registry import AgentRegistry
from .schedules import EvaluationMode, Schedule, ScheduleEntry, schedule_to_data
from .serialization import (
    atomic_write_canonical_json,
    canonical_json_text,
    content_digest,
    strict_json_load_file,
)
from .summaries import build_evaluation_summary
from .transformations import transform_actions, transform_deal


MANIFEST_SCHEMA_VERSION = "tuppi.eval.reproducibility_manifest.v1"
RUN_STATUS_SCHEMA_VERSION = "tuppi.eval.run_status.v1"


class _ActionTimeout(EvaluationTimeout):
    def __init__(self, *, seat: int, action_index: int, elapsed: float, limit: float):
        super().__init__(
            f"seat {seat} action {action_index} took {elapsed:.9f}s; limit={limit:.9f}s"
        )
        self.seat = seat
        self.action_index = action_index


class _DealTimeout(EvaluationTimeout):
    pass


class _MatchTimeout(EvaluationTimeout):
    pass


class _InsufficientMatchDeals(ArenaError):
    pass


class _TimedAgent:
    def __init__(
        self,
        delegate: Agent,
        *,
        seat: int,
        limit: float | None,
        durations: list[float],
        audit: dict[str, int | None],
    ) -> None:
        self._delegate = delegate
        self._seat = seat
        self._limit = limit
        self._durations = durations
        self._audit = audit

    @property
    def identity(self) -> str:
        return self._delegate.identity

    def choose_action(self, observation):
        action_index = len(self._durations)
        self._audit["acting_seat"] = self._seat
        self._audit["action_index"] = action_index
        started = time.perf_counter()
        action = self._delegate.choose_action(observation)
        elapsed = time.perf_counter() - started
        self._durations.append(elapsed)
        if self._limit is not None and elapsed > self._limit:
            raise _ActionTimeout(
                seat=self._seat,
                action_index=action_index,
                elapsed=elapsed,
                limit=self._limit,
            )
        return action


@dataclass(frozen=True, slots=True)
class ArenaRun:
    result: EvaluationResult
    manifest: dict[str, object]
    resumed_game_count: int
    executed_game_count: int


def _validate_inputs(
    config: EvaluationConfiguration, bank: DealBank, schedule: Schedule
) -> AgentRegistry:
    if config.deal_bank_id != bank.deal_bank_id:
        raise ArenaError("configuration and deal bank IDs differ")
    if config.schedule_id != schedule.schedule_id:
        raise ArenaError("configuration and schedule IDs differ")
    if config.schedule_design_id != schedule.design_id:
        raise ArenaError("configuration and schedule designs differ")
    if config.evaluation_mode is not schedule.mode:
        raise ArenaError("configuration and schedule modes differ")
    if config.team_a.team_id != schedule.team_a_id or (
        config.team_b.team_id != schedule.team_b_id
    ):
        raise ArenaError("configuration and schedule teams differ")
    if config.number_base_deals != len(bank.base_deals):
        raise ArenaError("configured base-deal count differs from deal bank")
    if config.seed_hierarchy.deal_root_seed != bank.root_seed:
        raise ArenaError("deal seed differs from deal-bank root seed")
    if config.dealer_policy is not bank.dealer_policy:
        raise ArenaError("dealer policy differs from deal bank")
    if tuple(item.transformation_id for item in schedule.transformations) != (
        config.transformations_applied
    ):
        raise ArenaError("configured transformations differ from schedule")
    if any(
        deal.starting_score != config.starting_score for deal in bank.base_deals
    ):
        raise ArenaError("deal-bank starting score differs from configuration")
    registry = AgentRegistry.build(config.agent_specifications)
    if registry.registry_digest != config.agent_registry_digest:
        raise ArenaError("agent registry digest differs from configuration")
    return registry


def _game_filename(entry: ScheduleEntry) -> str:
    digest_suffix = entry.entry_id.rsplit(":", 1)[-1][:16]
    return f"{entry.schedule_position:08d}-{digest_suffix}.json"


def _script_for_spec(specification, entry: ScheduleEntry, seat: int):
    if specification.implementation_reference != "tuppi_eval.agents:fixed_script_v1":
        return None
    configuration = specification.configuration
    raw_actions = configuration.get("actions")
    if type(raw_actions) is not list:
        raise RegistryError("fixed-script specification requires an actions array")
    parsed = tuple(action_from_data(item) for item in raw_actions)
    transformed = transform_actions(parsed, entry.transformation)
    return tuple(action for action in transformed if action.seat == seat)


def _construct_agents(
    entry: ScheduleEntry,
    registry: AgentRegistry,
    config: EvaluationConfiguration,
    durations: list[float],
    audit: dict[str, int | None],
) -> tuple[tuple[Agent, Agent, Agent, Agent], tuple[str | None, ...]]:
    agents: list[Agent] = []
    seeds: list[str | None] = []
    for seat, agent_id in enumerate(entry.seat_agent_ids):
        specification = registry.get(agent_id)
        seed = (
            derive_seed(
                config.seed_hierarchy.agent_root_seed,
                "agent",
                entry.entry_id,
                seat,
                specification.agent_id,
            )
            if specification.seed_policy.value == "derived_per_entry_seat"
            else None
        )
        delegate = construct_agent(
            specification,
            seed=seed,
            seat=seat,
            scripted_actions=_script_for_spec(specification, entry, seat),
        )
        agents.append(
            _TimedAgent(
                delegate,
                seat=seat,
                limit=config.timeouts.per_action_seconds,
                durations=durations,
                audit=audit,
            )
        )
        seeds.append(seed)
    if len({id(agent) for agent in agents}) != 4:
        raise RegistryError("arena constructed a shared runtime agent object")
    return tuple(agents), tuple(seeds)  # type: ignore[return-value]


def _transformed_sequence(
    entry: ScheduleEntry, bank: DealBank
) -> tuple:
    transformed = tuple(
        transform_deal(bank.base_deals[index], entry.transformation)
        for index in entry.source_base_deal_indices
    )
    if tuple(item.transformed_deal_id for item in transformed) != (
        entry.transformed_deal_ids
    ):
        raise ArenaError("schedule transformed-deal identity mismatch")
    return transformed


def _run_deal(
    entry: ScheduleEntry,
    bank: DealBank,
    agents: tuple[Agent, Agent, Agent, Agent],
    config: EvaluationConfiguration,
) -> ResearchRunResult:
    transformed = _transformed_sequence(entry, bank)
    if len(transformed) != 1:
        raise ArenaError("deal-mode schedule entry contains a sequence")
    item = transformed[0]
    match_ref = (
        f"eval-{config.configuration_digest[7:19]}-g{entry.schedule_position}"
    )
    match_input = ExplicitMatchInput(
        match_ref=match_ref,
        initial_score=item.starting_score,
        initial_dealer=item.dealer,
        deals=(item.explicit_deal(),),
    )
    from tuppi_engine.runner import run_match_input

    started = time.perf_counter()
    result = run_match_input(match_input, agents)
    elapsed = time.perf_counter() - started
    if config.timeouts.per_deal_seconds is not None and (
        elapsed > config.timeouts.per_deal_seconds
    ):
        raise _DealTimeout(
            f"deal took {elapsed:.9f}s; limit={config.timeouts.per_deal_seconds:.9f}s"
        )
    return result


def _run_match(
    entry: ScheduleEntry,
    bank: DealBank,
    agents: tuple[Agent, Agent, Agent, Agent],
    config: EvaluationConfiguration,
) -> ResearchRunResult:
    transformed = _transformed_sequence(entry, bank)
    first = transformed[0]
    match_ref = (
        f"eval-{config.configuration_digest[7:19]}-m{entry.schedule_position}"
    )
    state = create_match(
        initial_score=first.starting_score,
        initial_dealer=first.dealer,
        match_ref=match_ref,
    )
    used = []
    match_started = time.perf_counter()
    for item in transformed:
        if state.terminal:
            break
        deal_started = time.perf_counter()
        state = begin_explicit_deal(state, item.explicit_deal())
        state = play_active_deal(state, agents)
        used.append(item.explicit_deal())
        deal_elapsed = time.perf_counter() - deal_started
        if config.timeouts.per_deal_seconds is not None and (
            deal_elapsed > config.timeouts.per_deal_seconds
        ):
            raise _DealTimeout(
                f"match deal took {deal_elapsed:.9f}s; "
                f"limit={config.timeouts.per_deal_seconds:.9f}s"
            )
        if config.timeouts.per_match_seconds is not None and (
            time.perf_counter() - match_started > config.timeouts.per_match_seconds
        ):
            raise _MatchTimeout("match wall-time limit was exceeded")
    if not state.terminal:
        raise _InsufficientMatchDeals(
            "explicit match sequence ended before either team reached 52"
        )
    match_input = ExplicitMatchInput(
        match_ref=match_ref,
        initial_score=first.starting_score,
        initial_dealer=first.dealer,
        deals=tuple(used),
    )
    return ResearchRunResult(
        match_input_id=match_input.match_input_id,
        match_ref=match_ref,
        initial_score=first.starting_score,
        initial_dealer=first.dealer,
        agent_ids=tuple(agent.identity for agent in agents),  # type: ignore[arg-type]
        deals=state.completed_deals,
        final_score=state.score,
        next_dealer=None,
        terminal=True,
        match_result=match_result_from_state(state),
        public_events=state.public_events,
    )


def _failure_kind(error: BaseException, *, during_construction: bool) -> FailureKind:
    if during_construction:
        return FailureKind.AGENT_CONSTRUCTION
    if isinstance(error, EvaluationTimeout):
        return FailureKind.TIMEOUT
    if isinstance(error, _InsufficientMatchDeals):
        return FailureKind.INSUFFICIENT_MATCH_DEALS
    if isinstance(error, InvalidActionError):
        return FailureKind.ILLEGAL_AGENT_ACTION
    if isinstance(error, AgentProtocolError):
        return FailureKind.AGENT_PROTOCOL
    if isinstance(error, StateInvariantError):
        return FailureKind.ENGINE_INVARIANT
    if isinstance(error, (EvaluationSerializationError, EngineSerializationError)):
        return FailureKind.SERIALIZATION
    if isinstance(error, EngineError):
        return FailureKind.ENGINE_INVARIANT
    return FailureKind.UNEXPECTED


def _new_game_record(fields: dict[str, Any]) -> GameRecord:
    provisional = object.__new__(GameRecord)
    for name, value in fields.items():
        object.__setattr__(provisional, name, value)
    object.__setattr__(provisional, "schema_version", GAME_RECORD_SCHEMA_VERSION)
    record_id = f"game:{content_digest(provisional.semantic_data())}"
    return GameRecord(record_id=record_id, **fields)


def _record_success(
    *,
    entry: ScheduleEntry,
    config: EvaluationConfiguration,
    result: ResearchRunResult,
    raw_data: dict[str, object],
    seeds: tuple[str | None, ...],
    duration: float,
    action_durations: list[float],
) -> GameRecord:
    public = result.deals[-1].public_result
    winner_engine = public.deal_score.winner_team.value
    winner_external = entry.seat_external_teams[winner_engine]
    declaring_engine = (
        None if public.declarer is None else team_for_seat(public.declarer).value
    )
    declaring_external = (
        None
        if declaring_engine is None
        else entry.seat_external_teams[declaring_engine]
    )
    up_team = public.score_before.up_team
    reset = up_team is not None and up_team is not public.deal_score.winner_team
    match_winner_external = None
    if result.terminal and result.match_result is not None:
        match_winner_external = entry.seat_external_teams[
            result.match_result.winner_team.value
        ]
    fields = {
        "evaluation_id": config.evaluation_id,
        "entry_id": entry.entry_id,
        "base_deal_id": entry.base_deal_id,
        "transformation_id": entry.transformation.transformation_id,
        "transformed_deal_id": entry.transformed_deal_id,
        "schedule_position": entry.schedule_position,
        "block_index": entry.block_index,
        "evaluation_mode": config.evaluation_mode.value,
        "ruleset_id": config.ruleset_id,
        "engine_identity": config.engine_identity,
        "seat_team_ids": entry.seat_team_ids,
        "seat_agent_ids": entry.seat_agent_ids,
        "seat_external_teams": entry.seat_external_teams,
        "dealer": public.dealer if config.evaluation_mode is EvaluationMode.MATCH else entry.transformed_dealer,
        "forehand": public.forehand if config.evaluation_mode is EvaluationMode.MATCH else entry.transformed_forehand,
        "starting_score": tuple(result.initial_score.as_tuple()),
        "contract": public.contract.value,
        "declarer": public.declarer,
        "declaring_engine_team": declaring_engine,
        "declaring_external_team": declaring_external,
        "first_leader": public.first_leader,
        "team_tricks": tuple(public.team_tricks),
        "winner_engine_team": winner_engine,
        "winner_external_team": winner_external,
        "deal_points": public.deal_score.points,
        "score_after": tuple(public.score_after.as_tuple()),
        "reset": reset,
        "terminal": result.terminal,
        "match_winner_external_team": match_winner_external,
        "deals_played": len(result.deals),
        "execution_status": ExecutionStatus.SUCCESS,
        "failure": None,
        "raw_result_digest": content_digest(raw_data),
        "event_log_id": raw_data["event_log_id"],
        "agent_seeds": tuple(seeds),
        "determinism_metadata_json": canonical_json_text(
            {
                "agent_seed_namespace": "tuppi.eval.seed_derivation.v1",
                "deal_generation_independent_of_agents": True,
                "source_base_deal_ids": list(entry.source_base_deal_ids),
                "worker_count": 1,
            }
        ),
        "duration_seconds": duration,
        "action_durations_seconds": tuple(action_durations),
    }
    return _new_game_record(fields)


def _record_failure(
    *,
    entry: ScheduleEntry,
    config: EvaluationConfiguration,
    error: BaseException,
    during_construction: bool,
    seeds: tuple[str | None, ...],
    duration: float,
    action_durations: list[float],
    audit: dict[str, int | None],
) -> GameRecord:
    acting_seat = getattr(error, "seat", audit.get("acting_seat"))
    action_index = getattr(error, "action_index", audit.get("action_index"))
    failure = FailureDetails(
        kind=_failure_kind(error, during_construction=during_construction),
        exception_type=type(error).__name__,
        message=str(error),
        acting_seat=acting_seat,
        action_index=action_index,
    )
    starting_score = config.starting_score.as_tuple()
    if entry.transformation.seat_rotation % 2:
        starting_score = (starting_score[1], starting_score[0])
    fields = {
        "evaluation_id": config.evaluation_id,
        "entry_id": entry.entry_id,
        "base_deal_id": entry.base_deal_id,
        "transformation_id": entry.transformation.transformation_id,
        "transformed_deal_id": entry.transformed_deal_id,
        "schedule_position": entry.schedule_position,
        "block_index": entry.block_index,
        "evaluation_mode": config.evaluation_mode.value,
        "ruleset_id": config.ruleset_id,
        "engine_identity": config.engine_identity,
        "seat_team_ids": entry.seat_team_ids,
        "seat_agent_ids": entry.seat_agent_ids,
        "seat_external_teams": entry.seat_external_teams,
        "dealer": entry.transformed_dealer,
        "forehand": entry.transformed_forehand,
        "starting_score": tuple(starting_score),
        "contract": None,
        "declarer": None,
        "declaring_engine_team": None,
        "declaring_external_team": None,
        "first_leader": None,
        "team_tricks": None,
        "winner_engine_team": None,
        "winner_external_team": None,
        "deal_points": None,
        "score_after": None,
        "reset": None,
        "terminal": None,
        "match_winner_external_team": None,
        "deals_played": 0,
        "execution_status": ExecutionStatus.FAILED,
        "failure": failure,
        "raw_result_digest": None,
        "event_log_id": None,
        "agent_seeds": tuple(seeds),
        "determinism_metadata_json": canonical_json_text(
            {
                "agent_seed_namespace": "tuppi.eval.seed_derivation.v1",
                "deal_generation_independent_of_agents": True,
                "source_base_deal_ids": list(entry.source_base_deal_ids),
                "worker_count": 1,
            }
        ),
        "duration_seconds": duration,
        "action_durations_seconds": tuple(action_durations),
    }
    return _new_game_record(fields)


def _execute_entry(
    entry: ScheduleEntry,
    *,
    config: EvaluationConfiguration,
    bank: DealBank,
    registry: AgentRegistry,
) -> tuple[GameRecord, dict[str, object] | None]:
    durations: list[float] = []
    audit: dict[str, int | None] = {"acting_seat": None, "action_index": None}
    seeds: tuple[str | None, ...] = (None, None, None, None)
    overall_start = time.perf_counter()
    during_construction = True
    try:
        agents, seeds = _construct_agents(entry, registry, config, durations, audit)
        during_construction = False
        if config.evaluation_mode is EvaluationMode.DEAL:
            result = _run_deal(entry, bank, agents, config)
        else:
            result = _run_match(entry, bank, agents, config)
        raw_data = research_run_result_to_data(result)
        duration = time.perf_counter() - overall_start
        record = _record_success(
            entry=entry,
            config=config,
            result=result,
            raw_data=raw_data,
            seeds=seeds,
            duration=duration,
            action_durations=durations,
        )
        return record, raw_data
    except BaseException as exc:
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        duration = time.perf_counter() - overall_start
        return (
            _record_failure(
                entry=entry,
                config=config,
                error=exc,
                during_construction=during_construction,
                seeds=seeds,
                duration=duration,
                action_durations=durations,
                audit=audit,
            ),
            None,
        )


def _load_resumed_record(
    path: Path,
    *,
    entry: ScheduleEntry,
    config: EvaluationConfiguration,
    raw_directory: Path,
) -> GameRecord:
    record = game_record_from_data(strict_json_load_file(path))
    if (
        record.evaluation_id != config.evaluation_id
        or record.entry_id != entry.entry_id
        or record.schedule_position != entry.schedule_position
    ):
        raise ArenaError("existing shard belongs to a different schedule entry")
    if record.execution_status is ExecutionStatus.SUCCESS:
        raw_path = raw_directory / _game_filename(entry)
        if not raw_path.exists():
            raise ArenaError("successful resumed shard is missing its raw result")
        raw_data = strict_json_load_file(raw_path)
        if content_digest(raw_data) != record.raw_result_digest:
            raise ArenaError("resumed raw result digest mismatch")
    return record


def _evaluation_result(
    config: EvaluationConfiguration,
    schedule: Schedule,
    records: tuple[GameRecord, ...],
) -> EvaluationResult:
    grouped: dict[int, list[GameRecord]] = {}
    for record in records:
        grouped.setdefault(record.block_index, []).append(record)
    blocks = tuple(
        build_duplicate_block(tuple(grouped[index])) for index in sorted(grouped)
    )
    summary = build_evaluation_summary(records, blocks, config)
    fields = {
        "evaluation_id": config.evaluation_id,
        "configuration_digest": config.configuration_digest,
        "schedule_id": schedule.schedule_id,
        "deal_bank_id": config.deal_bank_id,
        "evaluation_mode": config.evaluation_mode.value,
        "game_records": records,
        "duplicate_blocks": blocks,
        "summary_json": canonical_json_text(summary),
        "failure_count": sum(
            record.execution_status is ExecutionStatus.FAILED for record in records
        ),
    }
    provisional = object.__new__(EvaluationResult)
    for name, value in fields.items():
        object.__setattr__(provisional, name, value)
    object.__setattr__(
        provisional, "schema_version", EVALUATION_RESULT_SCHEMA_VERSION
    )
    result_id = f"result:{content_digest(provisional.semantic_data())}"
    return EvaluationResult(result_id=result_id, **fields)


def _git_metadata(root: Path) -> tuple[str | None, bool | None]:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
                timeout=20,
            ).stdout
        )
        return commit, dirty
    except (OSError, subprocess.SubprocessError):
        return None, None


def _file_digest(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _artifact_digests(output_directory: Path) -> dict[str, str]:
    artifacts: dict[str, str] = {}
    for path in sorted(output_directory.rglob("*.json")):
        if path.name == "reproducibility_manifest.json":
            continue
        artifacts[str(path.relative_to(output_directory))] = _file_digest(path)
    return artifacts


def _installed_package_version() -> str:
    try:
        return version("tuppi-research")
    except PackageNotFoundError:
        return "source-tree"


def run_evaluation(
    config: EvaluationConfiguration,
    bank: DealBank,
    schedule: Schedule,
    *,
    output_directory: str | Path,
    max_new_games: int | None = None,
) -> ArenaRun:
    """Execute or resume a finite serial evaluation in canonical order."""

    registry = _validate_inputs(config, bank, schedule)
    if max_new_games is not None and (
        type(max_new_games) is not int or max_new_games <= 0
    ):
        raise ArenaError("max_new_games must be null or a positive integer")
    output = Path(output_directory)
    output.mkdir(parents=True, exist_ok=True)
    games_directory = output / "games"
    raw_directory = output / "raw"
    quarantine_directory = output / "quarantine"
    games_directory.mkdir(exist_ok=True)
    raw_directory.mkdir(exist_ok=True)
    quarantine_directory.mkdir(exist_ok=True)
    start_time = datetime.now(timezone.utc).isoformat()
    status_path = output / "run_status.json"
    if status_path.exists():
        existing_status = strict_json_load_file(status_path)
        if type(existing_status) is dict and isinstance(
            existing_status.get("start_timestamp"), str
        ):
            start_time = existing_status["start_timestamp"]
    atomic_write_canonical_json(output / "evaluation_config.json", evaluation_config_to_data(config))
    atomic_write_canonical_json(output / "deal_bank.json", deal_bank_to_data(bank))
    atomic_write_canonical_json(output / "schedule.json", schedule_to_data(schedule))
    atomic_write_canonical_json(
        status_path,
        {
            "evaluation_id": config.evaluation_id,
            "schema_version": RUN_STATUS_SCHEMA_VERSION,
            "start_timestamp": start_time,
            "status": "running",
        },
    )
    records: list[GameRecord] = []
    resumed = 0
    executed = 0
    for entry in schedule.entries:
        game_path = games_directory / _game_filename(entry)
        if game_path.exists():
            record = _load_resumed_record(
                game_path,
                entry=entry,
                config=config,
                raw_directory=raw_directory,
            )
            resumed += 1
        else:
            record, raw_data = _execute_entry(
                entry,
                config=config,
                bank=bank,
                registry=registry,
            )
            if raw_data is not None:
                atomic_write_canonical_json(
                    raw_directory / _game_filename(entry), raw_data
                )
            atomic_write_canonical_json(game_path, game_record_to_data(record))
            if record.execution_status is ExecutionStatus.FAILED:
                atomic_write_canonical_json(
                    quarantine_directory / _game_filename(entry),
                    {
                        "entry_id": entry.entry_id,
                        "evaluation_id": config.evaluation_id,
                        "failure": record.failure.to_data(),  # type: ignore[union-attr]
                        "record_id": record.record_id,
                        "schema_version": "tuppi.eval.quarantined_failure.v1",
                    },
                )
            executed += 1
        records.append(record)
        if (
            record.execution_status is ExecutionStatus.FAILED
            and config.failure_policy is FailurePolicy.ABORT
        ):
            raise ArenaError(
                f"evaluation aborted after failed entry {entry.entry_id}"
            )
        if max_new_games is not None and executed >= max_new_games and (
            len(records) < len(schedule.entries)
        ):
            atomic_write_canonical_json(
                status_path,
                {
                    "completed_entries": len(records),
                    "evaluation_id": config.evaluation_id,
                    "schema_version": RUN_STATUS_SCHEMA_VERSION,
                    "start_timestamp": start_time,
                    "status": "interrupted",
                },
            )
            raise InterruptedEvaluation(
                f"run interrupted after {executed} new game shard(s)"
            )
    ordered = tuple(sorted(records, key=lambda item: item.schedule_position))
    result = _evaluation_result(config, schedule, ordered)
    atomic_write_canonical_json(output / "evaluation_result.json", evaluation_result_to_data(result))
    atomic_write_canonical_json(output / "summary.json", result.summary)
    completion_time = datetime.now(timezone.utc).isoformat()
    atomic_write_canonical_json(
        status_path,
        {
            "completed_entries": len(ordered),
            "completion_timestamp": completion_time,
            "evaluation_id": config.evaluation_id,
            "schema_version": RUN_STATUS_SCHEMA_VERSION,
            "start_timestamp": start_time,
            "status": "complete",
        },
    )
    repository_root = Path(__file__).resolve().parents[2]
    git_commit, dirty = _git_metadata(repository_root)
    manifest: dict[str, object] = {
        "agent_registry_digest": config.agent_registry_digest,
        "analysis_seed": config.seed_hierarchy.analysis_seed,
        "completion_timestamp": completion_time,
        "configuration_digest": config.configuration_digest,
        "deal_bank_digest": bank.content_digest,
        "dirty_tree": dirty,
        "engine_identity": config.engine_identity,
        "evaluation_package_version": _installed_package_version(),
        "evaluation_id": config.evaluation_id,
        "failure_count": result.failure_count,
        "git_commit": git_commit,
        "output_artifact_digests": _artifact_digests(output),
        "platform": platform.platform(),
        "python_version": sys.version,
        "result_id": result.result_id,
        "ruleset_id": config.ruleset_id,
        "schedule_digest": content_digest(schedule.identity_data()),
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "seed_hierarchy": config.seed_hierarchy.to_data(),
        "start_timestamp": start_time,
        "worker_count": 1,
    }
    atomic_write_canonical_json(output / "reproducibility_manifest.json", manifest)
    return ArenaRun(
        result=result,
        manifest=manifest,
        resumed_game_count=resumed,
        executed_game_count=executed,
    )


def summarize_run_directory(path: str | Path) -> EvaluationResult:
    """Rebuild and validate a final summary from canonical raw game shards."""

    directory = Path(path)
    from .config import evaluation_config_from_data
    from .deals import deal_bank_from_data
    from .schedules import schedule_from_data

    config = evaluation_config_from_data(
        strict_json_load_file(directory / "evaluation_config.json")
    )
    bank = deal_bank_from_data(strict_json_load_file(directory / "deal_bank.json"))
    schedule = schedule_from_data(strict_json_load_file(directory / "schedule.json"))
    _validate_inputs(config, bank, schedule)
    records = tuple(
        game_record_from_data(strict_json_load_file(path))
        for path in sorted((directory / "games").glob("*.json"))
    )
    if len(records) != len(schedule.entries):
        raise ArenaError("run directory is incomplete and cannot be summarized")
    result = _evaluation_result(config, schedule, records)
    atomic_write_canonical_json(
        directory / "evaluation_result.json", evaluation_result_to_data(result)
    )
    atomic_write_canonical_json(directory / "summary.json", result.summary)
    return result
