"""Deterministic unordered-pair cross-play with symmetric presentation."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from .arena import run_evaluation
from .config import EvaluationConfiguration
from .deals import DealBank
from .errors import EvaluationValidationError
from .records import EvaluationResult
from .schedules import Schedule, build_canonical_schedule
from .serialization import (
    atomic_write_canonical_json,
    content_digest,
    require_exact_keys,
    require_object,
)


CROSSPLAY_CELL_SCHEMA_VERSION = "tuppi.eval.crossplay_cell.v1"
CROSSPLAY_MATRIX_SCHEMA_VERSION = "tuppi.eval.crossplay_matrix.v1"


class CrossplayCellStatus(StrEnum):
    VALID = "valid"
    INVALID = "invalid"
    MISSING = "missing"


@dataclass(frozen=True, slots=True)
class CrossplayCell:
    cell_id: str
    row_team_id: str
    column_team_id: str
    status: CrossplayCellStatus
    evaluation_id: str | None
    result_id: str | None
    mean_paired_utility_row_orientation: float | None
    independent_base_deals: int
    failure_count: int
    schema_version: str = field(default=CROSSPLAY_CELL_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        if self.row_team_id > self.column_team_id:
            raise EvaluationValidationError(
                "cross-play cell orientation must be lexicographically normalized"
            )
        if not isinstance(self.status, CrossplayCellStatus):
            raise EvaluationValidationError("cross-play cell status is invalid")
        if self.status is CrossplayCellStatus.MISSING:
            if any(
                value is not None
                for value in (
                    self.evaluation_id,
                    self.result_id,
                    self.mean_paired_utility_row_orientation,
                )
            ) or self.independent_base_deals != 0:
                raise EvaluationValidationError("missing cell contains result data")
        elif self.evaluation_id is None or self.result_id is None:
            raise EvaluationValidationError("evaluated cell lacks result identity")
        if type(self.independent_base_deals) is not int or self.independent_base_deals < 0:
            raise EvaluationValidationError("independent_base_deals must be nonnegative")
        if type(self.failure_count) is not int or self.failure_count < 0:
            raise EvaluationValidationError("failure_count must be nonnegative")
        if self.cell_id != f"cell:{content_digest(self.identity_data())}":
            raise EvaluationValidationError("cross-play cell identity is invalid")

    def identity_data(self) -> dict[str, object]:
        return {
            "column_team_id": self.column_team_id,
            "evaluation_id": self.evaluation_id,
            "failure_count": self.failure_count,
            "independent_base_deals": self.independent_base_deals,
            "mean_paired_utility_row_orientation": self.mean_paired_utility_row_orientation,
            "result_id": self.result_id,
            "row_team_id": self.row_team_id,
            "schema_version": self.schema_version,
            "status": self.status.value,
        }


def _make_cell(
    *,
    row_team_id: str,
    column_team_id: str,
    status: CrossplayCellStatus,
    result: EvaluationResult | None,
) -> CrossplayCell:
    inference = None if result is None else result.summary["primary_inference"]
    identity = {
        "column_team_id": column_team_id,
        "evaluation_id": None if result is None else result.evaluation_id,
        "failure_count": 0 if result is None else result.failure_count,
        "independent_base_deals": (
            0 if inference is None else inference["independent_base_deals"]
        ),
        "mean_paired_utility_row_orientation": (
            None if inference is None else inference["mean_paired_utility"]
        ),
        "result_id": None if result is None else result.result_id,
        "row_team_id": row_team_id,
        "schema_version": CROSSPLAY_CELL_SCHEMA_VERSION,
        "status": status.value,
    }
    return CrossplayCell(
        cell_id=f"cell:{content_digest(identity)}",
        row_team_id=row_team_id,
        column_team_id=column_team_id,
        status=status,
        evaluation_id=identity["evaluation_id"],  # type: ignore[arg-type]
        result_id=identity["result_id"],  # type: ignore[arg-type]
        mean_paired_utility_row_orientation=identity[
            "mean_paired_utility_row_orientation"
        ],  # type: ignore[arg-type]
        independent_base_deals=identity["independent_base_deals"],  # type: ignore[arg-type]
        failure_count=identity["failure_count"],  # type: ignore[arg-type]
    )


def crossplay_cell_to_data(cell: CrossplayCell) -> dict[str, object]:
    return {**cell.identity_data(), "cell_id": cell.cell_id}


@dataclass(frozen=True, slots=True)
class CrossplayMatrix:
    matrix_id: str
    team_ids: tuple[str, ...]
    deal_bank_id: str
    cells: tuple[CrossplayCell, ...]
    schema_version: str = field(default=CROSSPLAY_MATRIX_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        if type(self.team_ids) is not tuple or not self.team_ids:
            raise EvaluationValidationError("cross-play matrix requires teams")
        if self.team_ids != tuple(sorted(set(self.team_ids))):
            raise EvaluationValidationError("matrix team IDs must be unique and sorted")
        pairs = tuple((cell.row_team_id, cell.column_team_id) for cell in self.cells)
        expected = tuple(
            (left, right)
            for left_index, left in enumerate(self.team_ids)
            for right in self.team_ids[left_index:]
        )
        if pairs != expected:
            raise EvaluationValidationError(
                "matrix must contain each normalized unordered pair exactly once"
            )
        if self.matrix_id != f"matrix:{content_digest(self.identity_data())}":
            raise EvaluationValidationError("cross-play matrix identity is invalid")

    def identity_data(self) -> dict[str, object]:
        return {
            "cells": [cell.identity_data() for cell in self.cells],
            "deal_bank_id": self.deal_bank_id,
            "schema_version": self.schema_version,
            "team_ids": list(self.team_ids),
        }

    def oriented_value(self, row_team_id: str, column_team_id: str) -> float | None:
        left, right = sorted((row_team_id, column_team_id))
        cell = next(
            item
            for item in self.cells
            if item.row_team_id == left and item.column_team_id == right
        )
        value = cell.mean_paired_utility_row_orientation
        if value is None or row_team_id == column_team_id:
            return value
        return value if row_team_id == left else -value


def crossplay_matrix_to_data(matrix: CrossplayMatrix) -> dict[str, object]:
    display = []
    for row in matrix.team_ids:
        display.append(
            [
                {
                    "cell_id": next(
                        cell.cell_id
                        for cell in matrix.cells
                        if cell.row_team_id == min(row, column)
                        and cell.column_team_id == max(row, column)
                    ),
                    "status": next(
                        cell.status.value
                        for cell in matrix.cells
                        if cell.row_team_id == min(row, column)
                        and cell.column_team_id == max(row, column)
                    ),
                    "value": matrix.oriented_value(row, column),
                }
                for column in matrix.team_ids
            ]
        )
    return {
        "cells": [crossplay_cell_to_data(cell) for cell in matrix.cells],
        "deal_bank_id": matrix.deal_bank_id,
        "display_matrix": display,
        "matrix_id": matrix.matrix_id,
        "schema_version": matrix.schema_version,
        "team_ids": list(matrix.team_ids),
    }


def crossplay_matrix_from_data(value: object) -> CrossplayMatrix:
    obj = require_object(value, "cross-play matrix")
    require_exact_keys(
        obj,
        {
            "cells",
            "deal_bank_id",
            "display_matrix",
            "matrix_id",
            "schema_version",
            "team_ids",
        },
        "cross-play matrix",
    )
    if obj["schema_version"] != CROSSPLAY_MATRIX_SCHEMA_VERSION:
        raise EvaluationValidationError("unsupported cross-play schema_version")
    raw_cells = obj["cells"]
    if type(raw_cells) is not list:
        raise EvaluationValidationError("cross-play cells must be an array")
    cells = []
    for raw_value in raw_cells:
        raw = require_object(raw_value, "cross-play cell")
        require_exact_keys(
            raw,
            {
                "cell_id",
                "column_team_id",
                "evaluation_id",
                "failure_count",
                "independent_base_deals",
                "mean_paired_utility_row_orientation",
                "result_id",
                "row_team_id",
                "schema_version",
                "status",
            },
            "cross-play cell",
        )
        cells.append(
            CrossplayCell(
                cell_id=raw["cell_id"],
                row_team_id=raw["row_team_id"],
                column_team_id=raw["column_team_id"],
                status=CrossplayCellStatus(raw["status"]),
                evaluation_id=raw["evaluation_id"],
                result_id=raw["result_id"],
                mean_paired_utility_row_orientation=raw[
                    "mean_paired_utility_row_orientation"
                ],
                independent_base_deals=raw["independent_base_deals"],
                failure_count=raw["failure_count"],
            )
        )
    matrix = CrossplayMatrix(
        matrix_id=obj["matrix_id"],
        team_ids=tuple(obj["team_ids"]),
        deal_bank_id=obj["deal_bank_id"],
        cells=tuple(cells),
    )
    if crossplay_matrix_to_data(matrix)["display_matrix"] != obj["display_matrix"]:
        raise EvaluationValidationError("display matrix disagrees with raw cells")
    return matrix


def run_crossplay(
    configurations: tuple[EvaluationConfiguration, ...],
    bank: DealBank,
    *,
    output_directory: str | Path,
    include_missing: bool,
) -> CrossplayMatrix:
    if type(configurations) is not tuple or not configurations:
        raise EvaluationValidationError("cross-play requires comparison configs")
    team_specs = {
        team.team_id: team
        for config in configurations
        for team in (config.team_a, config.team_b)
    }
    team_ids = tuple(sorted(team_specs))
    by_pair: dict[tuple[str, str], EvaluationConfiguration] = {}
    for config in configurations:
        pair = (config.team_a.team_id, config.team_b.team_id)
        if pair[0] > pair[1]:
            raise EvaluationValidationError(
                "cross-play configuration orientation is not normalized"
            )
        if pair in by_pair:
            raise EvaluationValidationError("unordered team pair is configured twice")
        by_pair[pair] = config
    output = Path(output_directory)
    output.mkdir(parents=True, exist_ok=True)
    cells = []
    for left_index, left in enumerate(team_ids):
        for right in team_ids[left_index:]:
            pair = (left, right)
            config = by_pair.get(pair)
            if config is None:
                if not include_missing:
                    raise EvaluationValidationError(
                        f"cross-play configuration is missing pair {pair}"
                    )
                cells.append(
                    _make_cell(
                        row_team_id=left,
                        column_team_id=right,
                        status=CrossplayCellStatus.MISSING,
                        result=None,
                    )
                )
                continue
            schedule = build_canonical_schedule(
                deal_bank=bank,
                team_a=config.team_a,
                team_b=config.team_b,
                mode=config.evaluation_mode,
                match_sequence_length=config.match_sequence_length,
            )
            if schedule.schedule_id != config.schedule_id:
                raise EvaluationValidationError(
                    "cross-play config schedule does not match canonical schedule"
                )
            cell_directory = output / "cells" / f"{left[5:21]}--{right[5:21]}"
            arena = run_evaluation(
                config,
                bank,
                schedule,
                output_directory=cell_directory,
            )
            independent = arena.result.summary["primary_inference"][
                "independent_base_deals"
            ]
            status = (
                CrossplayCellStatus.VALID
                if arena.result.failure_count == 0 and independent > 0
                else CrossplayCellStatus.INVALID
            )
            cells.append(
                _make_cell(
                    row_team_id=left,
                    column_team_id=right,
                    status=status,
                    result=arena.result,
                )
            )
    provisional = {
        "cells": [cell.identity_data() for cell in cells],
        "deal_bank_id": bank.deal_bank_id,
        "schema_version": CROSSPLAY_MATRIX_SCHEMA_VERSION,
        "team_ids": list(team_ids),
    }
    matrix = CrossplayMatrix(
        matrix_id=f"matrix:{content_digest(provisional)}",
        team_ids=team_ids,
        deal_bank_id=bank.deal_bank_id,
        cells=tuple(cells),
    )
    atomic_write_canonical_json(
        output / "crossplay_matrix.json", crossplay_matrix_to_data(matrix)
    )
    lines = ["# Baseline cross-play", "", "Paired utility; row orientation. No transitive ranking is inferred.", ""]
    lines.append("| team | " + " | ".join(team_ids) + " |")
    lines.append("| --- | " + " | ".join("---" for _ in team_ids) + " |")
    for row in team_ids:
        values = []
        for column in team_ids:
            value = matrix.oriented_value(row, column)
            values.append("missing" if value is None else f"{value:.6g}")
        lines.append(f"| {row} | " + " | ".join(values) + " |")
    (output / "crossplay_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return matrix
