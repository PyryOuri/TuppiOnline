"""Canonical eight-game balanced duplicate schedule."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from enum import StrEnum

from tuppi_rules import forehand

from .deals import DealBank
from .errors import ScheduleError
from .identities import TeamSpecification
from .serialization import content_digest, require_exact_keys, require_object
from .transformations import (
    Transformation,
    transform_deal,
    transformation_from_data,
    transformation_to_data,
)


SCHEDULE_SCHEMA_VERSION = "tuppi.eval.schedule.v1"
SCHEDULE_ENTRY_SCHEMA_VERSION = "tuppi.eval.schedule_entry.v1"
CANONICAL_SCHEDULE_DESIGN = "balanced_duplicate_8_v1"
CANONICAL_BLOCK_SIZE = 8


class EvaluationMode(StrEnum):
    DEAL = "deal"
    MATCH = "match"


def canonical_transformations() -> tuple[Transformation, ...]:
    """Return the smallest rows balancing four rotations and both teams.

    For each clockwise rotation ``r``, both external team assignments ``e``
    occur. Partner order is woven in as ``e XOR parity(r)``. This produces
    eight rows, balances dealer and forehand at every physical seat twice,
    gives each compared team every partnership four times, and places each
    component agent at every physical seat twice.
    """

    return tuple(
        Transformation.build(
            seat_rotation=rotation,
            team_assignment_exchange=exchange,
            partner_seat_exchange=bool(exchange ^ (rotation % 2)),
            label=(
                f"canonical_r{rotation}_team_exchange_{int(exchange)}_"
                f"partner_exchange_{int(bool(exchange ^ (rotation % 2)))}"
            ),
            strength_estimation=True,
        )
        for rotation in range(4)
        for exchange in (False, True)
    )


def _seat_assignments(
    team_a: TeamSpecification,
    team_b: TeamSpecification,
    transformation: Transformation,
) -> tuple[tuple[str, str, str, str], tuple[str, str, str, str], tuple[str, str, str, str]]:
    a_engine_team = 1 if transformation.team_assignment_exchange else 0
    teams = (team_a, team_b) if a_engine_team == 0 else (team_b, team_a)
    external = ("A", "B") if a_engine_team == 0 else ("B", "A")
    seat_team_ids: list[str | None] = [None, None, None, None]
    seat_agent_ids: list[str | None] = [None, None, None, None]
    seat_external: list[str | None] = [None, None, None, None]
    for engine_team, seats in enumerate(((0, 2), (1, 3))):
        component_ids = teams[engine_team].component_agent_ids
        if transformation.partner_seat_exchange:
            component_ids = (component_ids[1], component_ids[0])
        for seat, agent_id in zip(seats, component_ids, strict=True):
            seat_team_ids[seat] = teams[engine_team].team_id
            seat_agent_ids[seat] = agent_id
            seat_external[seat] = external[engine_team]
    return (
        tuple(seat_team_ids),  # type: ignore[return-value]
        tuple(seat_agent_ids),  # type: ignore[return-value]
        tuple(seat_external),  # type: ignore[return-value]
    )


@dataclass(frozen=True, slots=True)
class ScheduleEntry:
    entry_id: str
    schedule_position: int
    block_index: int
    base_deal_index: int
    base_deal_id: str
    source_base_deal_indices: tuple[int, ...]
    source_base_deal_ids: tuple[str, ...]
    transformation: Transformation
    transformed_deal_id: str
    transformed_deal_ids: tuple[str, ...]
    transformed_dealer: int
    transformed_forehand: int
    seat_team_ids: tuple[str, str, str, str]
    seat_agent_ids: tuple[str, str, str, str]
    seat_external_teams: tuple[str, str, str, str]
    schema_version: str = field(default=SCHEDULE_ENTRY_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        for label, value in (
            ("schedule_position", self.schedule_position),
            ("block_index", self.block_index),
            ("base_deal_index", self.base_deal_index),
        ):
            if type(value) is not int or value < 0:
                raise ScheduleError(f"{label} must be nonnegative")
        if not isinstance(self.transformation, Transformation):
            raise ScheduleError("entry transformation is invalid")
        if (
            type(self.source_base_deal_indices) is not tuple
            or not self.source_base_deal_indices
            or type(self.source_base_deal_ids) is not tuple
            or len(self.source_base_deal_ids) != len(self.source_base_deal_indices)
            or type(self.transformed_deal_ids) is not tuple
            or len(self.transformed_deal_ids) != len(self.source_base_deal_indices)
        ):
            raise ScheduleError("entry source-deal sequence is invalid")
        if self.base_deal_index != self.source_base_deal_indices[0]:
            raise ScheduleError("base_deal_index must identify the first source deal")
        if self.transformed_dealer not in range(4):
            raise ScheduleError("entry dealer must be in 0..3")
        if self.transformed_forehand != forehand(self.transformed_dealer):
            raise ScheduleError("entry forehand disagrees with dealer")
        for label, values in (
            ("seat_team_ids", self.seat_team_ids),
            ("seat_agent_ids", self.seat_agent_ids),
            ("seat_external_teams", self.seat_external_teams),
        ):
            if type(values) is not tuple or len(values) != 4:
                raise ScheduleError(f"{label} must contain four values")
        if any(value not in ("A", "B") for value in self.seat_external_teams):
            raise ScheduleError("seat_external_teams may contain only A and B")
        if self.seat_external_teams[0] != self.seat_external_teams[2] or (
            self.seat_external_teams[1] != self.seat_external_teams[3]
        ):
            raise ScheduleError("external teams must occupy opposite partnerships")
        if self.seat_external_teams[0] == self.seat_external_teams[1]:
            raise ScheduleError("both external teams must be represented")
        if self.entry_id != f"entry:{content_digest(self.identity_data())}":
            raise ScheduleError("entry_id disagrees with schedule-entry content")

    def identity_data(self) -> dict[str, object]:
        return {
            "base_deal_id": self.base_deal_id,
            "base_deal_index": self.base_deal_index,
            "block_index": self.block_index,
            "schema_version": self.schema_version,
            "seat_agent_ids": list(self.seat_agent_ids),
            "seat_external_teams": list(self.seat_external_teams),
            "seat_team_ids": list(self.seat_team_ids),
            "source_base_deal_ids": list(self.source_base_deal_ids),
            "source_base_deal_indices": list(self.source_base_deal_indices),
            "transformation_id": self.transformation.transformation_id,
            "transformed_deal_id": self.transformed_deal_id,
            "transformed_deal_ids": list(self.transformed_deal_ids),
            "transformed_dealer": self.transformed_dealer,
            "transformed_forehand": self.transformed_forehand,
        }


def schedule_entry_to_data(entry: ScheduleEntry) -> dict[str, object]:
    return {
        **entry.identity_data(),
        "entry_id": entry.entry_id,
        "schedule_position": entry.schedule_position,
        "transformation": transformation_to_data(entry.transformation),
    }


@dataclass(frozen=True, slots=True)
class Schedule:
    schedule_id: str
    design_id: str
    mode: EvaluationMode
    deal_bank_id: str
    team_a_id: str
    team_b_id: str
    block_size: int
    transformations: tuple[Transformation, ...]
    entries: tuple[ScheduleEntry, ...]
    schema_version: str = field(default=SCHEDULE_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        if self.design_id != CANONICAL_SCHEDULE_DESIGN:
            raise ScheduleError("unsupported schedule design")
        if not isinstance(self.mode, EvaluationMode):
            raise ScheduleError("schedule mode is invalid")
        if self.block_size != CANONICAL_BLOCK_SIZE:
            raise ScheduleError("canonical block size must be eight")
        if type(self.transformations) is not tuple or len(self.transformations) != 8:
            raise ScheduleError("canonical schedule requires eight transformations")
        if len({item.transformation_id for item in self.transformations}) != 8:
            raise ScheduleError("canonical transformations must be unique")
        if type(self.entries) is not tuple or not self.entries:
            raise ScheduleError("schedule requires entries")
        if tuple(entry.schedule_position for entry in self.entries) != tuple(
            range(len(self.entries))
        ):
            raise ScheduleError("schedule positions must be contiguous from zero")
        if len({entry.entry_id for entry in self.entries}) != len(self.entries):
            raise ScheduleError("schedule contains duplicate entries")
        self._validate_balance()
        if self.schedule_id != f"schedule:{content_digest(self.identity_data())}":
            raise ScheduleError("schedule_id disagrees with canonical content")

    def _validate_balance(self) -> None:
        grouped: dict[int, list[ScheduleEntry]] = {}
        for entry in self.entries:
            grouped.setdefault(entry.block_index, []).append(entry)
        if tuple(sorted(grouped)) != tuple(range(len(grouped))):
            raise ScheduleError("block indices must be contiguous from zero")
        expected_rows = {
            (
                transformation.seat_rotation,
                transformation.team_assignment_exchange,
                transformation.partner_seat_exchange,
            )
            for transformation in canonical_transformations()
        }
        for block_index, block in grouped.items():
            if len(block) != self.block_size:
                raise ScheduleError(f"block {block_index} does not contain eight games")
            if len({entry.base_deal_id for entry in block}) != 1:
                raise ScheduleError("duplicate block mixes independent base deals")
            if len({entry.source_base_deal_ids for entry in block}) != 1:
                raise ScheduleError("duplicate block mixes source-deal sequences")
            actual_rows = {
                (
                    entry.transformation.seat_rotation,
                    entry.transformation.team_assignment_exchange,
                    entry.transformation.partner_seat_exchange,
                )
                for entry in block
            }
            if actual_rows != expected_rows:
                raise ScheduleError("duplicate block does not use canonical rows")
            if Counter(entry.transformed_dealer for entry in block) != Counter(
                {0: 2, 1: 2, 2: 2, 3: 2}
            ):
                raise ScheduleError("dealer seats are not balanced")
            if Counter(entry.transformed_forehand for entry in block) != Counter(
                {0: 2, 1: 2, 2: 2, 3: 2}
            ):
                raise ScheduleError("forehand seats are not balanced")
            a_partnerships = Counter(
                0 if entry.seat_external_teams[0] == "A" else 1 for entry in block
            )
            if a_partnerships != Counter({0: 4, 1: 4}):
                raise ScheduleError("team partnership assignments are not balanced")
            for external in ("A", "B"):
                dealer_count = sum(
                    entry.seat_external_teams[entry.transformed_dealer] == external
                    for entry in block
                )
                forehand_count = sum(
                    entry.seat_external_teams[entry.transformed_forehand] == external
                    for entry in block
                )
                if dealer_count != 4 or forehand_count != 4:
                    raise ScheduleError("external dealer/forehand roles are not balanced")
            all_agent_ids = {
                agent_id for entry in block for agent_id in entry.seat_agent_ids
            }
            for agent_id in all_agent_ids:
                seat_counts = tuple(
                    sum(entry.seat_agent_ids[seat] == agent_id for entry in block)
                    for seat in range(4)
                )
                if len(set(seat_counts)) != 1:
                    raise ScheduleError("component-agent seat roles are not balanced")

    def identity_data(self) -> dict[str, object]:
        return {
            "block_size": self.block_size,
            "deal_bank_id": self.deal_bank_id,
            "design_id": self.design_id,
            "entries": [entry.identity_data() for entry in self.entries],
            "mode": self.mode.value,
            "schema_version": self.schema_version,
            "team_a_id": self.team_a_id,
            "team_b_id": self.team_b_id,
            "transformation_ids": [
                item.transformation_id for item in self.transformations
            ],
        }


def build_canonical_schedule(
    *,
    deal_bank: DealBank,
    team_a: TeamSpecification,
    team_b: TeamSpecification,
    mode: EvaluationMode = EvaluationMode.DEAL,
    match_sequence_length: int | None = None,
) -> Schedule:
    if not isinstance(mode, EvaluationMode):
        raise ScheduleError("mode must be an EvaluationMode")
    transformations = canonical_transformations()
    entries: list[ScheduleEntry] = []
    if mode is EvaluationMode.DEAL:
        if match_sequence_length is not None:
            raise ScheduleError("deal mode does not accept match_sequence_length")
        units = tuple((deal,) for deal in deal_bank.base_deals)
    else:
        if (
            type(match_sequence_length) is not int
            or match_sequence_length <= 0
            or len(deal_bank.base_deals) % match_sequence_length
        ):
            raise ScheduleError(
                "match mode requires a positive sequence length dividing the deal bank"
            )
        units = tuple(
            deal_bank.base_deals[index : index + match_sequence_length]
            for index in range(0, len(deal_bank.base_deals), match_sequence_length)
        )
    for block_index, unit in enumerate(units):
        source_ids = tuple(deal.base_deal_id for deal in unit)
        source_indices = tuple(deal.index for deal in unit)
        independent_id = (
            source_ids[0]
            if len(source_ids) == 1
            else f"sequence:{content_digest({'base_deal_ids': list(source_ids), 'schema_version': 'tuppi.eval.match_sequence.v1'})}"
        )
        for transformation in transformations:
            transformed_sequence = tuple(
                transform_deal(base_deal, transformation) for base_deal in unit
            )
            transformed = transformed_sequence[0]
            transformed_ids = tuple(
                item.transformed_deal_id for item in transformed_sequence
            )
            concrete_id = (
                transformed_ids[0]
                if len(transformed_ids) == 1
                else f"concrete-sequence:{content_digest({'transformed_deal_ids': list(transformed_ids), 'schema_version': 'tuppi.eval.transformed_match_sequence.v1'})}"
            )
            team_ids, agent_ids, external = _seat_assignments(
                team_a, team_b, transformation
            )
            identity = {
                "base_deal_id": independent_id,
                "base_deal_index": source_indices[0],
                "block_index": block_index,
                "schema_version": SCHEDULE_ENTRY_SCHEMA_VERSION,
                "seat_agent_ids": list(agent_ids),
                "seat_external_teams": list(external),
                "seat_team_ids": list(team_ids),
                "source_base_deal_ids": list(source_ids),
                "source_base_deal_indices": list(source_indices),
                "transformation_id": transformation.transformation_id,
                "transformed_deal_id": concrete_id,
                "transformed_deal_ids": list(transformed_ids),
                "transformed_dealer": transformed.dealer,
                "transformed_forehand": forehand(transformed.dealer),
            }
            entries.append(
                ScheduleEntry(
                    entry_id=f"entry:{content_digest(identity)}",
                    schedule_position=len(entries),
                    block_index=block_index,
                    base_deal_index=source_indices[0],
                    base_deal_id=independent_id,
                    source_base_deal_indices=source_indices,
                    source_base_deal_ids=source_ids,
                    transformation=transformation,
                    transformed_deal_id=concrete_id,
                    transformed_deal_ids=transformed_ids,
                    transformed_dealer=transformed.dealer,
                    transformed_forehand=forehand(transformed.dealer),
                    seat_team_ids=team_ids,
                    seat_agent_ids=agent_ids,
                    seat_external_teams=external,
                )
            )
    provisional = {
        "block_size": CANONICAL_BLOCK_SIZE,
        "deal_bank_id": deal_bank.deal_bank_id,
        "design_id": CANONICAL_SCHEDULE_DESIGN,
        "entries": [entry.identity_data() for entry in entries],
        "mode": mode.value,
        "schema_version": SCHEDULE_SCHEMA_VERSION,
        "team_a_id": team_a.team_id,
        "team_b_id": team_b.team_id,
        "transformation_ids": [
            item.transformation_id for item in transformations
        ],
    }
    return Schedule(
        schedule_id=f"schedule:{content_digest(provisional)}",
        design_id=CANONICAL_SCHEDULE_DESIGN,
        mode=mode,
        deal_bank_id=deal_bank.deal_bank_id,
        team_a_id=team_a.team_id,
        team_b_id=team_b.team_id,
        block_size=CANONICAL_BLOCK_SIZE,
        transformations=transformations,
        entries=tuple(entries),
    )


def schedule_to_data(schedule: Schedule) -> dict[str, object]:
    return {
        "block_size": schedule.block_size,
        "deal_bank_id": schedule.deal_bank_id,
        "design_id": schedule.design_id,
        "entries": [schedule_entry_to_data(entry) for entry in schedule.entries],
        "mode": schedule.mode.value,
        "schedule_id": schedule.schedule_id,
        "schema_version": schedule.schema_version,
        "team_a_id": schedule.team_a_id,
        "team_b_id": schedule.team_b_id,
        "transformations": [
            transformation_to_data(item) for item in schedule.transformations
        ],
    }


def schedule_from_data(value: object) -> Schedule:
    obj = require_object(value, "schedule")
    require_exact_keys(
        obj,
        {
            "block_size",
            "deal_bank_id",
            "design_id",
            "entries",
            "mode",
            "schedule_id",
            "schema_version",
            "team_a_id",
            "team_b_id",
            "transformations",
        },
        "schedule",
    )
    if obj["schema_version"] != SCHEDULE_SCHEMA_VERSION:
        raise ScheduleError("unsupported schedule schema_version")
    try:
        mode = EvaluationMode(obj["mode"])
    except (TypeError, ValueError) as exc:
        raise ScheduleError("invalid evaluation mode") from exc
    raw_transforms = obj["transformations"]
    if type(raw_transforms) is not list:
        raise ScheduleError("transformations must be an array")
    transforms = tuple(transformation_from_data(item) for item in raw_transforms)
    by_id = {item.transformation_id: item for item in transforms}
    raw_entries = obj["entries"]
    if type(raw_entries) is not list:
        raise ScheduleError("entries must be an array")
    entries: list[ScheduleEntry] = []
    for raw in raw_entries:
        item = require_object(raw, "schedule entry")
        require_exact_keys(
            item,
            {
                "base_deal_id",
                "base_deal_index",
                "block_index",
                "entry_id",
                "schedule_position",
                "schema_version",
                "seat_agent_ids",
                "seat_external_teams",
                "seat_team_ids",
                "source_base_deal_ids",
                "source_base_deal_indices",
                "transformation",
                "transformation_id",
                "transformed_deal_id",
                "transformed_deal_ids",
                "transformed_dealer",
                "transformed_forehand",
            },
            "schedule entry",
        )
        transformation = transformation_from_data(item["transformation"])
        if transformation.transformation_id != item["transformation_id"] or (
            transformation.transformation_id not in by_id
        ):
            raise ScheduleError("entry transformation is absent from schedule")
        tuple_fields = {}
        for name in ("seat_team_ids", "seat_agent_ids", "seat_external_teams"):
            raw_values = item[name]
            if type(raw_values) is not list or len(raw_values) != 4:
                raise ScheduleError(f"{name} must contain four values")
            tuple_fields[name] = tuple(raw_values)
        sequence_fields = {}
        for name in (
            "source_base_deal_indices",
            "source_base_deal_ids",
            "transformed_deal_ids",
        ):
            raw_values = item[name]
            if type(raw_values) is not list or not raw_values:
                raise ScheduleError(f"{name} must be a nonempty array")
            sequence_fields[name] = tuple(raw_values)
        entries.append(
            ScheduleEntry(
                entry_id=item["entry_id"],
                schedule_position=item["schedule_position"],
                block_index=item["block_index"],
                base_deal_index=item["base_deal_index"],
                base_deal_id=item["base_deal_id"],
                **sequence_fields,
                transformation=transformation,
                transformed_deal_id=item["transformed_deal_id"],
                transformed_dealer=item["transformed_dealer"],
                transformed_forehand=item["transformed_forehand"],
                **tuple_fields,
            )
        )
    return Schedule(
        schedule_id=obj["schedule_id"],
        design_id=obj["design_id"],
        mode=mode,
        deal_bank_id=obj["deal_bank_id"],
        team_a_id=obj["team_a_id"],
        team_b_id=obj["team_b_id"],
        block_size=obj["block_size"],
        transformations=transforms,
        entries=tuple(entries),
    )
