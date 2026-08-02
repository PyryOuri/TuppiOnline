"""Pair-level inference for the complete-match protocol.

The independent statistical unit is the **complete complementary pair**. Legs,
deals, transformations, tricks, and decisions are not observations and are never
counted as such: a pair contributes exactly one number.

For a completed pair, with ``Y`` equal to ``+1`` when the *even* partnership
wins a leg and ``-1`` when it loses:

``D_match = (Y_E - Y_O) / 2``

so ``+1`` means the candidate won both orientations, ``-1`` means the opponent
did, and ``0`` means the pair split. The candidate's orientation-averaged match
win probability is ``(1 + mean(D_match)) / 2``.

Randomness here is digest-derived from the manifest's analysis seed. There is no
call to ``random``: a bootstrap or a randomization test must reproduce exactly.
"""

from __future__ import annotations

import hashlib
import math
from statistics import NormalDist, fmean, median, stdev

from tuppi_eval.serialization import content_digest

from .errors import InferenceError
from .manifest import STATISTICS_VERSION
from .records import LegStatus, PairRecord, PairStatus


EXACT_SIGN_FLIP_LIMIT = 18


def _analysis_integer(seed: int | str, *parts: object) -> int:
    material = "\0".join(["tuppi.match.analysis.v1", str(seed), *map(str, parts)])
    return int.from_bytes(hashlib.sha256(material.encode("utf-8")).digest(), "big")


def _quantile(values: list[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    index = probability * (len(ordered) - 1)
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    weight = index - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def length_distribution(values: list[int]) -> dict[str, object]:
    """Summarize a match-length sample, including the tail that matters."""

    if not values:
        return {
            "count": 0,
            "maximum": None,
            "mean": None,
            "median": None,
            "minimum": None,
            "p90": None,
            "p95": None,
            "p99": None,
        }
    floats = [float(value) for value in values]
    return {
        "count": len(values),
        "maximum": max(values),
        "mean": fmean(floats),
        "median": median(floats),
        "minimum": min(values),
        "p90": _quantile(floats, 0.90),
        "p95": _quantile(floats, 0.95),
        "p99": _quantile(floats, 0.99),
    }


def _correlation(left: list[float], right: list[float]) -> float | None:
    if len(left) < 2:
        return None
    mean_left = fmean(left)
    mean_right = fmean(right)
    covariance = sum(
        (a - mean_left) * (b - mean_right) for a, b in zip(left, right, strict=True)
    )
    variance_left = sum((a - mean_left) ** 2 for a in left)
    variance_right = sum((b - mean_right) ** 2 for b in right)
    if variance_left <= 0 or variance_right <= 0:
        return None
    return covariance / math.sqrt(variance_left * variance_right)


def _sign_flip_p_value(
    values: list[float], *, seed: int | str, replicates: int
) -> tuple[float, str, int]:
    """Two-sided randomization test under the pair-exchangeability null."""

    observed = abs(fmean(values))
    count = len(values)
    if count == 0:
        raise InferenceError("a randomization test needs at least one pair")
    if count <= EXACT_SIGN_FLIP_LIMIT:
        total = 1 << count
        extreme = 0
        for mask in range(total):
            flipped = sum(
                -value if (mask >> index) & 1 else value
                for index, value in enumerate(values)
            )
            if abs(flipped / count) >= observed - 1e-12:
                extreme += 1
        return (extreme / total, "exact_sign_flip", total)
    extreme = 0
    for replicate in range(replicates):
        total_value = 0.0
        for index, value in enumerate(values):
            bit = _analysis_integer(seed, "signflip", replicate, index) & 1
            total_value += -value if bit else value
        if abs(total_value / count) >= observed - 1e-12:
            extreme += 1
    return ((extreme + 1) / (replicates + 1), "monte_carlo_sign_flip", replicates)


def _bootstrap_interval(
    values: list[float], *, seed: int | str, replicates: int, alpha: float
) -> list[float] | None:
    count = len(values)
    if count < 2:
        return None
    means: list[float] = []
    for replicate in range(replicates):
        total = 0.0
        for position in range(count):
            index = (
                _analysis_integer(seed, "bootstrap", replicate, position) % count
            )
            total += values[index]
        means.append(total / count)
    return [_quantile(means, alpha / 2), _quantile(means, 1 - alpha / 2)]


def pair_inference(
    pairs: tuple[PairRecord, ...],
    *,
    confidence_level: float,
    analysis_seed: int | str,
    bootstrap_replicates: int,
    sign_flip_replicates: int,
) -> dict[str, object]:
    """Summarize one comparison from its complete complementary pairs."""

    if type(pairs) is not tuple:
        raise InferenceError("pairs must be an immutable tuple")
    if not 0.5 < confidence_level < 1.0:
        raise InferenceError("confidence_level must lie in (0.5, 1)")

    complete = tuple(item for item in pairs if item.status is PairStatus.COMPLETE)
    censored = sum(
        1 for item in pairs if item.status is PairStatus.INCOMPLETE_CENSORED
    )
    failed = sum(1 for item in pairs if item.status is PairStatus.INCOMPLETE_FAILED)
    censored_legs = sum(
        1
        for item in pairs
        for leg in (item.leg_even, item.leg_odd)
        if leg.status is LegStatus.CENSORED_INFRASTRUCTURE
    )
    failed_legs = sum(
        1
        for item in pairs
        for leg in (item.leg_even, item.leg_odd)
        if leg.status is LegStatus.FAILED
    )

    leg_lengths = [
        leg.deals_consumed
        for item in complete
        for leg in (item.leg_even, item.leg_odd)
    ]
    base: dict[str, object] = {
        "analysis_seed": analysis_seed,
        "candidate_leg_win_rate": None,
        "censored_leg_count": censored_legs,
        "censored_pair_count": censored,
        "censoring_rate_pairs": (censored / len(pairs)) if pairs else None,
        "complementary_leg_correlation": None,
        "confidence_level": confidence_level,
        "failed_leg_count": failed_legs,
        "failed_pair_count": failed,
        "leg_length_distribution": length_distribution(leg_lengths),
        "observed_pair_count": len(pairs),
        "statistics_version": STATISTICS_VERSION,
        "unit_of_inference": "complete_complementary_match_pair",
    }
    if not complete:
        base.update(
            {
                "advantage_over_half": None,
                "bootstrap_confidence_interval": None,
                "candidate_match_win_probability": None,
                "complete_pair_count": 0,
                "confidence_interval": None,
                "mean_d_match": None,
                "pair_outcomes": {"loss": 0, "tie": 0, "win": 0},
                "sign_flip_method": "unavailable",
                "sign_flip_p_value": None,
                "sign_flip_replicates": 0,
                "standard_error": None,
                "warning": (
                    "no complete complementary pairs; censored pairs are an "
                    "infrastructure outcome and are never treated as draws"
                ),
                "win_probability_confidence_interval": None,
            }
        )
        return base

    values = [float(item.d_match) for item in complete]
    count = len(values)
    mean_value = fmean(values)
    wins = sum(1 for value in values if value > 0)
    losses = sum(1 for value in values if value < 0)
    ties = count - wins - losses

    sample_sd = stdev(values) if count >= 2 else None
    standard_error = sample_sd / math.sqrt(count) if sample_sd is not None else None
    alpha = 1.0 - confidence_level
    if standard_error is None or standard_error == 0.0:
        interval = None if standard_error is None else [mean_value, mean_value]
    else:
        critical = NormalDist().inv_cdf(1 - alpha / 2)
        interval = [
            mean_value - critical * standard_error,
            mean_value + critical * standard_error,
        ]
    bootstrap = _bootstrap_interval(
        values, seed=analysis_seed, replicates=bootstrap_replicates, alpha=alpha
    )
    p_value, method, used = _sign_flip_p_value(
        values, seed=analysis_seed, replicates=sign_flip_replicates
    )

    candidate_even = [1.0 if item.leg_even.candidate_won else -1.0 for item in complete]
    candidate_odd = [1.0 if item.leg_odd.candidate_won else -1.0 for item in complete]
    leg_wins = sum(1 for value in candidate_even + candidate_odd if value > 0)

    probability = (1.0 + mean_value) / 2.0
    base.update(
        {
            "advantage_over_half": probability - 0.5,
            "bootstrap_confidence_interval": bootstrap,
            "candidate_leg_win_rate": leg_wins / (2 * count),
            "candidate_match_win_probability": probability,
            "complementary_leg_correlation": _correlation(
                candidate_even, candidate_odd
            ),
            "complete_pair_count": count,
            "confidence_interval": interval,
            "mean_d_match": mean_value,
            "pair_outcomes": {"loss": losses, "tie": ties, "win": wins},
            "sign_flip_method": method,
            "sign_flip_p_value": p_value,
            "sign_flip_replicates": used,
            "standard_error": standard_error,
            "win_probability_confidence_interval": (
                None if interval is None else [(1 + interval[0]) / 2, (1 + interval[1]) / 2]
            ),
        }
    )
    return base


def secondary_metrics(pairs: tuple[PairRecord, ...]) -> dict[str, object]:
    """Match-level descriptive metrics; never able to override the primary."""

    legs = [
        leg
        for item in pairs
        for leg in (item.leg_even, item.leg_odd)
        if leg.status is LegStatus.COMPLETE
    ]
    if not legs:
        return {"complete_leg_count": 0}
    deals = sum(leg.deals_consumed for leg in legs)
    return {
        "complete_leg_count": len(legs),
        "contract_frequencies": {
            "nolo_share": sum(leg.nolo_deals for leg in legs) / deals,
            "rami_share": sum(leg.rami_deals for leg in legs) / deals,
            "stolen_rami_share_of_rami": (
                sum(leg.stolen_rami for leg in legs)
                / max(1, sum(leg.rami_deals for leg in legs))
            ),
            "successful_rami_share_of_rami": (
                sum(leg.successful_rami for leg in legs)
                / max(1, sum(leg.rami_deals for leg in legs))
            ),
        },
        "deal_points": {
            "mean_candidate_per_match": fmean(
                [float(leg.candidate_deal_points) for leg in legs]
            ),
            "mean_opponent_per_match": fmean(
                [float(leg.opponent_deal_points) for leg in legs]
            ),
        },
        "deals_per_match": length_distribution([leg.deals_consumed for leg in legs]),
        "declarer_seat_share": [
            sum(leg.declarer_seat_counts[seat] for leg in legs) / deals
            for seat in range(4)
        ],
        "immediate_completion_rate": (
            sum(1 for leg in legs if leg.immediate_completion) / len(legs)
        ),
        "mean_actions_per_match": fmean([float(leg.action_count) for leg in legs]),
        "resets_per_match": length_distribution([leg.resets for leg in legs]),
        "score_state_occupancy_share": {
            "candidate_down": sum(leg.occupancy.deals_candidate_down for leg in legs)
            / deals,
            "candidate_up": sum(leg.occupancy.deals_candidate_up for leg in legs)
            / deals,
            "table": sum(leg.occupancy.deals_at_table for leg in legs) / deals,
        },
        "terminal_winning_score": length_distribution(
            [max(leg.final_score) for leg in legs]
        ),
        "tricks": {
            "mean_candidate_per_match": fmean(
                [float(leg.candidate_tricks) for leg in legs]
            ),
            "mean_opponent_per_match": fmean(
                [float(leg.opponent_tricks) for leg in legs]
            ),
        },
    }


def inference_digest(summary: dict[str, object]) -> str:
    return content_digest(summary)
