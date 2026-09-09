"""The qualification gate must fail closed on anything short of the plan.

The evaluator is tolerant on purpose: a block that is simply absent from the
results never reaches ``build_duplicate_block``, and
``paired_statistical_summary`` reports an incomplete block only as a count. Those
are the right defaults for a development summary and the wrong ones for a
qualification claim. These tests pin both halves - the gap, and the gate that
closes it - and pin that the gate is not a second estimator: it must hand the
identical native objects to the identical native summary.
"""

from __future__ import annotations

import pytest

from tuppi_eval.errors import (
    EvaluationSerializationError,
    IncompleteEvidenceError,
)
from tuppi_eval.qualification import (
    ExpectedBlock,
    admitted_blocks,
    expected_blocks_for,
    qualified_summary,
)
from tuppi_eval.records import DuplicateBlockRecord
from tuppi_eval.serialization import content_digest
from tuppi_eval.statistics import paired_statistical_summary

from .support import evaluation_inputs


EVALUATION_ID = "eval:qualification-test"
ANALYSIS = {
    "confidence_level": 0.95,
    "analysis_seed": "qualification-test",
    "bootstrap_replicates": 64,
    "permutation_replicates": 64,
}


def make_block(
    index: int,
    *,
    value: float | None = 1.0,
    evaluation_id: str = EVALUATION_ID,
    base_deal_id: str | None = None,
    game_record_ids: tuple[str, ...] | None = None,
    complete: bool = True,
    valid_game_count: int = 8,
    invalid_game_count: int = 0,
) -> DuplicateBlockRecord:
    """A valid native block record, built the way the evaluator builds one."""

    base_deal_id = base_deal_id or f"base:deal-{index}"
    game_record_ids = game_record_ids or tuple(
        f"game:block-{index}-game-{position}" for position in range(8)
    )
    outcome = None
    if value is not None:
        outcome = "win" if value > 0 else "loss" if value < 0 else "tie"
    identity = {
        "base_deal_id": base_deal_id,
        "block_index": index,
        "block_outcome": outcome,
        "complete": complete,
        "evaluation_id": evaluation_id,
        "game_record_ids": list(game_record_ids),
        "invalid_game_count": invalid_game_count,
        "paired_utility": value,
        "schema_version": "tuppi.eval.duplicate_block_record.v1",
        "valid_game_count": valid_game_count,
    }
    return DuplicateBlockRecord(
        block_record_id=f"block:{content_digest(identity)}",
        evaluation_id=evaluation_id,
        block_index=index,
        base_deal_id=base_deal_id,
        game_record_ids=game_record_ids,
        valid_game_count=valid_game_count,
        invalid_game_count=invalid_game_count,
        complete=complete,
        paired_utility=value,
        block_outcome=outcome,
    )


def planned(count: int) -> tuple[ExpectedBlock, ...]:
    return tuple(
        ExpectedBlock(
            evaluation_id=EVALUATION_ID,
            block_index=index,
            base_deal_id=f"base:deal-{index}",
        )
        for index in range(count)
    )


def test_a_complete_manifest_is_admitted_unchanged() -> None:
    blocks = tuple(make_block(index) for index in range(3))
    admitted = admitted_blocks(blocks, planned(3))
    assert admitted == blocks
    assert all(a is b for a, b in zip(admitted, blocks))


def test_admission_uses_manifest_order_not_arrival_order() -> None:
    blocks = tuple(make_block(index) for index in range(3))
    assert admitted_blocks((blocks[2], blocks[0], blocks[1]), planned(3)) == blocks


def test_a_missing_planned_block_is_rejected() -> None:
    blocks = tuple(make_block(index) for index in range(3))
    with pytest.raises(IncompleteEvidenceError, match="missing from the results"):
        admitted_blocks(blocks[:2], planned(3))


def test_native_statistics_alone_accept_the_same_truncated_evidence() -> None:
    """Why this gate exists: the estimator does not object on its own.

    The truncated summary is not merely permitted, it looks healthy - the sample
    size silently drops while ``incomplete_block_count`` stays at zero, because
    a block that never executed is not an incomplete block, just an absent one.
    """
    blocks = tuple(make_block(index) for index in range(3))
    full = paired_statistical_summary(blocks, **ANALYSIS)
    truncated = paired_statistical_summary(blocks[:2], **ANALYSIS)
    assert full["independent_base_deals"] == 3
    assert truncated["independent_base_deals"] == 2
    assert truncated["incomplete_block_count"] == 0


def test_an_unplanned_block_is_rejected() -> None:
    blocks = tuple(make_block(index) for index in range(4))
    with pytest.raises(IncompleteEvidenceError, match="not in the planned manifest"):
        admitted_blocks(blocks, planned(3))


def test_a_duplicated_block_is_rejected() -> None:
    blocks = tuple(make_block(index) for index in range(2))
    with pytest.raises(IncompleteEvidenceError, match="more than once"):
        admitted_blocks(blocks + (blocks[1],), planned(2))


def test_an_incomplete_block_is_rejected() -> None:
    incomplete = make_block(
        1, value=None, complete=False, valid_game_count=7, invalid_game_count=1
    )
    with pytest.raises(IncompleteEvidenceError, match="is incomplete"):
        admitted_blocks((make_block(0), incomplete), planned(2))


def test_the_native_record_already_refuses_a_nonfinite_utility() -> None:
    """The gate's finiteness check is defence in depth, not the only barrier."""
    with pytest.raises(EvaluationSerializationError):
        make_block(0, value=float("nan"))


def test_a_game_record_shared_by_two_blocks_is_rejected() -> None:
    first = make_block(0)
    second = make_block(1, game_record_ids=first.game_record_ids)
    with pytest.raises(IncompleteEvidenceError, match="two independent blocks"):
        admitted_blocks((first, second), planned(2))


def test_stipulated_game_records_must_agree() -> None:
    first = make_block(0)
    manifest = (
        ExpectedBlock(
            evaluation_id=EVALUATION_ID,
            block_index=0,
            base_deal_id="base:deal-0",
            game_record_ids=tuple(reversed(first.game_record_ids)),
        ),
    )
    with pytest.raises(IncompleteEvidenceError, match="disagree with the manifest"):
        admitted_blocks((first,), manifest)


def test_a_manifest_may_not_stack_two_evaluations() -> None:
    stacked = planned(1) + (
        ExpectedBlock(
            evaluation_id="eval:other", block_index=1, base_deal_id="base:deal-1"
        ),
    )
    with pytest.raises(IncompleteEvidenceError, match="one evaluation at a time"):
        admitted_blocks((make_block(0), make_block(1)), stacked)


def test_a_manifest_may_not_repeat_an_independent_unit() -> None:
    with pytest.raises(IncompleteEvidenceError, match="repeats a block index"):
        admitted_blocks((make_block(0),), planned(1) * 2)


def test_an_empty_manifest_is_refused() -> None:
    with pytest.raises(IncompleteEvidenceError, match="nonempty expected manifest"):
        admitted_blocks((make_block(0),), ())


def test_an_expected_block_validates_its_own_identifiers() -> None:
    with pytest.raises(IncompleteEvidenceError, match="nonempty identifiers"):
        ExpectedBlock(evaluation_id="", block_index=0, base_deal_id="base:deal-0")
    with pytest.raises(IncompleteEvidenceError, match="nonnegative"):
        ExpectedBlock(
            evaluation_id=EVALUATION_ID, block_index=-1, base_deal_id="base:deal-0"
        )
    with pytest.raises(IncompleteEvidenceError, match="eight distinct"):
        ExpectedBlock(
            evaluation_id=EVALUATION_ID,
            block_index=0,
            base_deal_id="base:deal-0",
            game_record_ids=("game:only-one",),
        )


def test_expected_blocks_come_from_the_committed_schedule() -> None:
    _, _, _, _, schedule, config = evaluation_inputs(3)
    expected = expected_blocks_for(config, schedule)
    assert len(expected) == 3
    assert [item.block_index for item in expected] == [0, 1, 2]
    assert {item.evaluation_id for item in expected} == {config.evaluation_id}
    assert {item.base_deal_id for item in expected} == {
        entry.base_deal_id for entry in schedule.entries
    }
    assert all(item.game_record_ids is None for item in expected)


def test_expected_blocks_reject_a_foreign_schedule() -> None:
    _, _, _, _, schedule, _ = evaluation_inputs(1)
    _, _, _, _, _, other_config = evaluation_inputs(2)
    with pytest.raises(IncompleteEvidenceError, match="does not belong"):
        expected_blocks_for(other_config, schedule)


def test_qualified_summary_matches_the_native_estimator_exactly() -> None:
    blocks = tuple(make_block(index) for index in range(3))
    direct = paired_statistical_summary(blocks, **ANALYSIS)
    gated = qualified_summary(
        blocks, planned(3), native_summary=paired_statistical_summary, **ANALYSIS
    )
    assert gated == direct


def test_qualified_summary_refuses_before_it_summarises() -> None:
    blocks = tuple(make_block(index) for index in range(3))
    with pytest.raises(IncompleteEvidenceError):
        qualified_summary(
            blocks[:1],
            planned(3),
            native_summary=paired_statistical_summary,
            **ANALYSIS,
        )
