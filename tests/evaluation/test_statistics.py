from __future__ import annotations

import math

from hypothesis import given, settings, strategies as st

from tuppi_eval.statistics import paired_statistical_summary, paired_value_summary

from .support import synthetic_block


def _summary(values: tuple[float | None, ...], seed: int | str = 123):
    return paired_statistical_summary(
        tuple(synthetic_block(value, index) for index, value in enumerate(values)),
        confidence_level=0.95,
        analysis_seed=seed,
        bootstrap_replicates=500,
        permutation_replicates=500,
    )


def test_known_paired_dataset_mean_interval_and_independent_count() -> None:
    result = _summary((1.0, 2.0, 3.0, 4.0))
    assert result["mean_paired_utility"] == 2.5
    assert result["median_paired_utility"] == 2.5
    assert result["independent_base_deals"] == 4
    assert result["transformed_games"] == 32
    assert result["standard_error"] == math.sqrt(5 / 3) / 2
    assert result["confidence_interval"][0] < 2.5 < result["confidence_interval"][1]
    assert result["win_tie_loss_blocks"] == {"loss": 0, "tie": 0, "win": 4}
    assert result["sign_test_p_value"] == 0.125
    assert result["paired_permutation_method"] == "exact_sign_flip"


def test_generic_paired_values_preserve_one_observation_per_block() -> None:
    values = (0.5, -0.25, 0.0)
    result = paired_value_summary(
        values,
        incomplete_block_count=2,
        transformed_game_count=40,
        confidence_level=0.95,
        analysis_seed="supporting-metric",
        bootstrap_replicates=500,
        permutation_replicates=500,
    )
    assert result["independent_base_deals"] == 3
    assert result["transformed_games"] == 40
    assert result["incomplete_block_count"] == 2
    assert result["mean_paired_utility"] == sum(values) / len(values)
    assert result["win_tie_loss_blocks"] == {"loss": 1, "tie": 1, "win": 1}


def test_bootstrap_and_permutation_are_reproducible_and_seed_separated() -> None:
    values = tuple(float(index - 10) for index in range(21))
    first = _summary(values, seed="analysis-a")
    second = _summary(values, seed="analysis-a")
    other = _summary(values, seed="analysis-b")
    assert first == second
    assert first["analysis_seed"] == "analysis-a"
    assert first["paired_permutation_method"] == "monte_carlo_sign_flip"
    assert (
        first["bootstrap_confidence_interval"]
        != other["bootstrap_confidence_interval"]
        or first["paired_permutation_p_value"]
        != other["paired_permutation_p_value"]
    )


def test_empty_insufficient_incomplete_and_ties_are_explicit() -> None:
    empty = _summary((None,))
    assert empty["independent_base_deals"] == 0
    assert empty["mean_paired_utility"] is None
    assert empty["warning"] == "no complete independent duplicate blocks"

    one = _summary((0.0,))
    assert one["standard_error"] is None
    assert one["confidence_interval"] is None
    assert one["win_tie_loss_blocks"]["tie"] == 1
    assert one["sign_test_p_value"] is None


@given(st.lists(st.integers(min_value=-20, max_value=20), min_size=1, max_size=12))
@settings(max_examples=30)
def test_paired_utility_orientation_reverses_all_directional_statistics(
    values: list[int],
) -> None:
    positive = _summary(tuple(float(value) for value in values))
    negative = _summary(tuple(float(-value) for value in values))
    assert negative["mean_paired_utility"] == -positive["mean_paired_utility"]
    assert negative["median_paired_utility"] == -positive["median_paired_utility"]
    assert negative["standard_error"] == positive["standard_error"]
    assert negative["sign_test_p_value"] == positive["sign_test_p_value"]
    assert negative["win_tie_loss_blocks"] == {
        "loss": positive["win_tie_loss_blocks"]["win"],
        "tie": positive["win_tie_loss_blocks"]["tie"],
        "win": positive["win_tie_loss_blocks"]["loss"],
    }
