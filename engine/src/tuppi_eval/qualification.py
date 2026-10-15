"""Fail-closed admission of a *planned* evaluation before it is summarised.

The evaluator is deliberately tolerant while a run is in progress. Blocks are
built from whatever game records exist (:func:`~.records.build_duplicate_block`
requires eight records for a block that *is* present, but nothing requires the
block to be present at all), and :func:`~.statistics.paired_statistical_summary`
drops an incomplete block and reports it only as ``incomplete_block_count``. That
is right for a development summary and wrong for a qualification claim: a base
deal that never executed - which ``run_evaluation``'s own ``max_new_games`` makes
routine - silently shrinks the sample instead of failing.

This module supplies the missing comparison against the pre-execution manifest.
It replaces no estimator, record, identity or utility: :func:`admitted_blocks`
returns the very same native objects, in manifest order, or raises. Build the
manifest with :func:`expected_blocks_for` from the committed configuration and
schedule - never from the rows that happened to succeed, which is the error this
module exists to catch.

Exploratory summaries of an unfinished run remain legitimate; they simply must
not be labelled qualification.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Callable

from .config import EvaluationConfiguration
from .errors import IncompleteEvidenceError
from .records import DuplicateBlockRecord
from .schedules import CANONICAL_BLOCK_SIZE, Schedule


@dataclass(frozen=True, slots=True)
class ExpectedBlock:
    """One independent unit the run committed to producing, before it ran."""

    evaluation_id: str
    block_index: int
    base_deal_id: str
    #: Supplied only when game record identities are already committed. They are
    #: content digests over executed outcomes, so a schedule cannot know them.
    game_record_ids: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        if not _text(self.evaluation_id) or not _text(self.base_deal_id):
            raise IncompleteEvidenceError("expected block requires nonempty identifiers")
        if type(self.block_index) is not int or self.block_index < 0:
            raise IncompleteEvidenceError("expected block index must be nonnegative")
        if self.game_record_ids is not None and (
            type(self.game_record_ids) is not tuple
            or len(self.game_record_ids) != CANONICAL_BLOCK_SIZE
            or any(not _text(item) for item in self.game_record_ids)
            or len(set(self.game_record_ids)) != CANONICAL_BLOCK_SIZE
        ):
            raise IncompleteEvidenceError(
                "stipulated game record IDs must be eight distinct nonempty strings"
            )

    @property
    def key(self) -> tuple[str, int, str]:
        return self.evaluation_id, self.block_index, self.base_deal_id


def _text(value: object) -> bool:
    return isinstance(value, str) and bool(value)


def expected_blocks_for(
    config: EvaluationConfiguration, schedule: Schedule
) -> tuple[ExpectedBlock, ...]:
    """Derive the committed manifest from the configuration and schedule.

    This is the intended way to obtain the argument to :func:`admitted_blocks`:
    it is fixed before execution, so it cannot be contaminated by which entries
    later succeeded.
    """

    if not isinstance(config, EvaluationConfiguration):
        raise IncompleteEvidenceError("an EvaluationConfiguration is required")
    if not isinstance(schedule, Schedule):
        raise IncompleteEvidenceError("a Schedule is required")
    if schedule.schedule_id != config.schedule_id:
        raise IncompleteEvidenceError(
            "schedule does not belong to this evaluation configuration"
        )
    planned: dict[int, str] = {}
    counts: dict[int, int] = {}
    for entry in schedule.entries:
        existing = planned.setdefault(entry.block_index, entry.base_deal_id)
        if existing != entry.base_deal_id:
            raise IncompleteEvidenceError(
                "schedule block spans more than one independent base deal"
            )
        counts[entry.block_index] = counts.get(entry.block_index, 0) + 1
    for block_index, count in counts.items():
        if count != CANONICAL_BLOCK_SIZE:
            raise IncompleteEvidenceError(
                f"planned block {block_index} has {count} entries, not "
                f"{CANONICAL_BLOCK_SIZE}"
            )
    return tuple(
        ExpectedBlock(
            evaluation_id=config.evaluation_id,
            block_index=block_index,
            base_deal_id=planned[block_index],
        )
        for block_index in sorted(planned)
    )


def admitted_blocks(
    blocks: tuple[DuplicateBlockRecord, ...],
    expected: tuple[ExpectedBlock, ...],
) -> tuple[DuplicateBlockRecord, ...]:
    """Return the planned blocks unchanged, in manifest order, or raise.

    Rejects a missing, duplicated, unplanned, incomplete, invalid or non-finite
    block, and a game record reused across two independent units. Validates
    identifiers and completeness only; it does not re-derive deal generation,
    re-check the utility formula or reorder anything within a block.
    """

    if type(blocks) is not tuple:
        raise IncompleteEvidenceError("blocks must be an immutable tuple")
    if type(expected) is not tuple or not expected:
        raise IncompleteEvidenceError("a nonempty expected manifest is required")
    if any(not isinstance(item, ExpectedBlock) for item in expected):
        raise IncompleteEvidenceError("expected manifest holds a foreign record type")
    if len({item.evaluation_id for item in expected}) != 1:
        raise IncompleteEvidenceError(
            "one evaluation at a time; separate conditions are not extra samples"
        )
    if (
        len({item.key for item in expected}) != len(expected)
        or len({item.base_deal_id for item in expected}) != len(expected)
        or len({item.block_index for item in expected}) != len(expected)
    ):
        raise IncompleteEvidenceError(
            "expected manifest repeats a block index or base deal"
        )
    wanted = {item.key: item for item in expected}
    found: dict[tuple[str, int, str], DuplicateBlockRecord] = {}
    seen_game_ids: set[str] = set()
    for block in blocks:
        if not isinstance(block, DuplicateBlockRecord):
            raise IncompleteEvidenceError("blocks must be DuplicateBlockRecord values")
        key = (block.evaluation_id, block.block_index, block.base_deal_id)
        if key not in wanted:
            raise IncompleteEvidenceError(
                f"block {block.block_index} was not in the planned manifest"
            )
        if key in found:
            raise IncompleteEvidenceError(
                f"block {block.block_index} appears more than once"
            )
        if (
            block.complete is not True
            or block.valid_game_count != CANONICAL_BLOCK_SIZE
            or block.invalid_game_count != 0
        ):
            raise IncompleteEvidenceError(
                f"block {block.block_index} is incomplete: "
                f"{block.valid_game_count} valid, {block.invalid_game_count} invalid"
            )
        if seen_game_ids.intersection(block.game_record_ids):
            raise IncompleteEvidenceError(
                "a game record is shared by two independent blocks"
            )
        stipulated = wanted[key].game_record_ids
        if stipulated is not None and block.game_record_ids != stipulated:
            raise IncompleteEvidenceError(
                f"block {block.block_index} game records disagree with the manifest"
            )
        utility = block.paired_utility
        if type(utility) not in (int, float) or not math.isfinite(utility):
            raise IncompleteEvidenceError(
                f"block {block.block_index} has no finite paired utility"
            )
        seen_game_ids.update(block.game_record_ids)
        found[key] = block
    absent = [item.block_index for item in expected if item.key not in found]
    if absent:
        raise IncompleteEvidenceError(
            f"planned blocks are missing from the results: {absent}"
        )
    return tuple(found[item.key] for item in expected)


def qualified_summary(
    blocks: tuple[DuplicateBlockRecord, ...],
    expected: tuple[ExpectedBlock, ...],
    *,
    native_summary: Callable[..., dict[str, object]],
    confidence_level: float,
    analysis_seed: int | str,
    bootstrap_replicates: int,
    permutation_replicates: int,
) -> dict[str, object]:
    """Admit the manifest, then delegate to the unchanged native estimator.

    ``native_summary`` is injected rather than imported so that this gate can
    never be mistaken for a second estimator; pass
    :func:`~.statistics.paired_statistical_summary`.
    """

    admitted = admitted_blocks(blocks, expected)
    return native_summary(
        admitted,
        confidence_level=confidence_level,
        analysis_seed=analysis_seed,
        bootstrap_replicates=bootstrap_replicates,
        permutation_replicates=permutation_replicates,
    )


__all__ = [
    "ExpectedBlock",
    "admitted_blocks",
    "expected_blocks_for",
    "qualified_summary",
]
