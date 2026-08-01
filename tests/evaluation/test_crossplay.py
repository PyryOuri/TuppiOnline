from __future__ import annotations

from tuppi_eval.crossplay import (
    CrossplayCellStatus,
    crossplay_matrix_from_data,
    crossplay_matrix_to_data,
    run_crossplay,
)
from tuppi_eval.deals import DealerPolicy, generate_deal_bank
from tuppi_rules import MatchScore

from .support import baseline_teams, comparison_config


def _bank():
    return generate_deal_bank(
        count=1,
        root_seed="crossplay",
        dealer_policy=DealerPolicy.ROUND_ROBIN,
        initial_dealer=0,
        starting_score=MatchScore(),
        creation_metadata={},
    )


def test_crossplay_normalizes_orientation_and_preserves_missing_cells(tmp_path) -> None:
    registry, first, second = baseline_teams()
    left, right = sorted((first, second), key=lambda team: team.team_id)
    bank = _bank()
    _, comparison = comparison_config(
        bank=bank,
        registry=registry,
        team_a=left,
        team_b=right,
    )
    matrix = run_crossplay(
        (comparison,),
        bank,
        output_directory=tmp_path / "matrix",
        include_missing=True,
    )
    assert len(matrix.cells) == 3
    assert [cell.status for cell in matrix.cells].count(CrossplayCellStatus.MISSING) == 2
    valid = next(cell for cell in matrix.cells if cell.status is CrossplayCellStatus.VALID)
    assert matrix.oriented_value(left.team_id, right.team_id) == (
        valid.mean_paired_utility_row_orientation
    )
    assert matrix.oriented_value(right.team_id, left.team_id) == -(
        valid.mean_paired_utility_row_orientation
    )
    assert crossplay_matrix_from_data(crossplay_matrix_to_data(matrix)) == matrix
    assert (tmp_path / "matrix" / "crossplay_report.md").is_file()


def test_crossplay_diagonal_runs_mirror_play_and_has_stable_ids(tmp_path) -> None:
    registry, team, _ = baseline_teams()
    bank = _bank()
    _, diagonal = comparison_config(
        bank=bank,
        registry=registry,
        team_a=team,
        team_b=team,
    )
    first = run_crossplay(
        (diagonal,),
        bank,
        output_directory=tmp_path / "one",
        include_missing=False,
    )
    second = run_crossplay(
        (diagonal,),
        bank,
        output_directory=tmp_path / "two",
        include_missing=False,
    )
    assert len(first.cells) == 1
    assert first.cells[0].row_team_id == first.cells[0].column_team_id
    assert first.cells[0].status is CrossplayCellStatus.VALID
    assert first.cells[0].cell_id == second.cells[0].cell_id
    assert first.matrix_id == second.matrix_id
