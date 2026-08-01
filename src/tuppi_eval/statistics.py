"""Inspectable paired inference over independent duplicate blocks."""

from __future__ import annotations

import hashlib
import math
from statistics import NormalDist, fmean, median, stdev

from .errors import EvaluationValidationError
from .records import DuplicateBlockRecord
from .serialization import canonical_json_bytes


STATISTICS_METHOD_ID = "tuppi.eval.paired_statistics.v1"
MAX_EXACT_SIGN_FLIP_BLOCKS = 16


def _analysis_integer(seed: int | str, *parts: object) -> int:
    material = canonical_json_bytes(
        {
            "parts": [str(part) for part in parts],
            "schema_version": "tuppi.eval.analysis_rng.v1",
            "seed": seed,
        }
    )
    return int.from_bytes(hashlib.sha256(material).digest(), "big")


def _quantile(values: list[float], probability: float) -> float:
    if not values:
        raise EvaluationValidationError("quantile requires at least one value")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = probability * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _sign_test(wins: int, losses: int) -> float | None:
    count = wins + losses
    if count == 0:
        return None
    tail = min(wins, losses)
    probability = sum(math.comb(count, k) for k in range(tail + 1)) / (2**count)
    return min(1.0, 2.0 * probability)


def _permutation_p_value(
    values: tuple[float, ...], *, seed: int | str, replicates: int
) -> tuple[float | None, str, int]:
    if not values:
        return None, "unavailable", 0
    observed = abs(fmean(values))
    if len(values) <= MAX_EXACT_SIGN_FLIP_BLOCKS:
        total = 1 << len(values)
        extreme = 0
        for mask in range(total):
            permuted = fmean(
                value if (mask >> index) & 1 else -value
                for index, value in enumerate(values)
            )
            if abs(permuted) >= observed - 1e-15:
                extreme += 1
        return extreme / total, "exact_sign_flip", total
    extreme = 0
    for replicate in range(replicates):
        permuted = fmean(
            value
            if _analysis_integer(seed, "permutation", replicate, index) & 1
            else -value
            for index, value in enumerate(values)
        )
        if abs(permuted) >= observed - 1e-15:
            extreme += 1
    return (extreme + 1) / (replicates + 1), "monte_carlo_sign_flip", replicates


def paired_statistical_summary(
    blocks: tuple[DuplicateBlockRecord, ...],
    *,
    confidence_level: float,
    analysis_seed: int | str,
    bootstrap_replicates: int,
    permutation_replicates: int,
) -> dict[str, object]:
    """Summarize one value per independently generated base deal."""

    if type(blocks) is not tuple:
        raise EvaluationValidationError("blocks must be an immutable tuple")
    if not 0.5 < confidence_level < 1:
        raise EvaluationValidationError("confidence_level must be in (0.5, 1)")
    if type(bootstrap_replicates) is not int or bootstrap_replicates <= 0:
        raise EvaluationValidationError("bootstrap_replicates must be positive")
    if type(permutation_replicates) is not int or permutation_replicates <= 0:
        raise EvaluationValidationError("permutation_replicates must be positive")
    values = tuple(
        block.paired_utility
        for block in blocks
        if block.complete and block.paired_utility is not None
    )
    independent_count = len(values)
    transformed_game_count = sum(len(block.game_record_ids) for block in blocks)
    incomplete_count = len(blocks) - independent_count
    if not values:
        return {
            "analysis_seed": analysis_seed,
            "bootstrap_confidence_interval": None,
            "bootstrap_replicates": bootstrap_replicates,
            "confidence_interval": None,
            "confidence_level": confidence_level,
            "effect_size_cohens_dz": None,
            "incomplete_block_count": incomplete_count,
            "independent_base_deals": 0,
            "mean_paired_utility": None,
            "median_paired_utility": None,
            "method_id": STATISTICS_METHOD_ID,
            "paired_permutation_method": "unavailable",
            "paired_permutation_p_value": None,
            "paired_permutation_replicates": 0,
            "sign_test_p_value": None,
            "standard_error": None,
            "transformed_games": transformed_game_count,
            "warning": "no complete independent duplicate blocks",
            "win_tie_loss_blocks": {"loss": 0, "tie": 0, "win": 0},
        }
    mean_value = fmean(values)
    median_value = median(values)
    sample_sd = stdev(values) if independent_count >= 2 else None
    standard_error = (
        sample_sd / math.sqrt(independent_count) if sample_sd is not None else None
    )
    alpha = 1.0 - confidence_level
    if standard_error is None:
        interval = None
    else:
        critical = NormalDist().inv_cdf(1 - alpha / 2)
        interval = [
            mean_value - critical * standard_error,
            mean_value + critical * standard_error,
        ]
    bootstrap_means: list[float] = []
    for replicate in range(bootstrap_replicates):
        sample = tuple(
            values[
                _analysis_integer(
                    analysis_seed, "bootstrap", replicate, position
                )
                % independent_count
            ]
            for position in range(independent_count)
        )
        bootstrap_means.append(fmean(sample))
    bootstrap_interval = [
        _quantile(bootstrap_means, alpha / 2),
        _quantile(bootstrap_means, 1 - alpha / 2),
    ]
    wins = sum(value > 0 for value in values)
    losses = sum(value < 0 for value in values)
    ties = independent_count - wins - losses
    permutation_p, permutation_method, actual_permutations = _permutation_p_value(
        values,
        seed=analysis_seed,
        replicates=permutation_replicates,
    )
    effect_size = (
        mean_value / sample_sd
        if sample_sd is not None and sample_sd > 0
        else None
    )
    warning = None
    if independent_count < 2:
        warning = "at least two complete base deals are required for a standard error"
    elif independent_count < 10:
        warning = "small independent sample; uncertainty estimates are unstable"
    return {
        "analysis_seed": analysis_seed,
        "bootstrap_confidence_interval": bootstrap_interval,
        "bootstrap_replicates": bootstrap_replicates,
        "confidence_interval": interval,
        "confidence_level": confidence_level,
        "effect_size_cohens_dz": effect_size,
        "incomplete_block_count": incomplete_count,
        "independent_base_deals": independent_count,
        "mean_paired_utility": mean_value,
        "median_paired_utility": median_value,
        "method_id": STATISTICS_METHOD_ID,
        "paired_permutation_method": permutation_method,
        "paired_permutation_p_value": permutation_p,
        "paired_permutation_replicates": actual_permutations,
        "sign_test_p_value": _sign_test(wins, losses),
        "standard_error": standard_error,
        "transformed_games": transformed_game_count,
        "warning": warning,
        "win_tie_loss_blocks": {"loss": losses, "tie": ties, "win": wins},
    }
