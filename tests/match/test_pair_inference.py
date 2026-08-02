from __future__ import annotations

import pytest

from tuppi_match import LegIdentity, LegStatus, PairStatus, length_distribution
from tuppi_match.errors import InferenceError, RecordError
from tuppi_match.statistics import pair_inference, secondary_metrics

from .conftest import synthetic_leg, synthetic_pair


ANALYSIS = {
    "confidence_level": 0.95,
    "analysis_seed": "test-analysis",
    "bootstrap_replicates": 400,
    "sign_flip_replicates": 400,
}


# --------------------------------------------------------------- D_match sign


def test_d_match_is_plus_one_when_the_candidate_wins_both_orientations() -> None:
    # Leg E: engine team 0 wins and the candidate is even, so the candidate won.
    # Leg O: engine team 1 wins and the candidate is odd, so the candidate won.
    pair = synthetic_pair(even_winner=0, odd_winner=1)
    assert pair.leg_even.candidate_won is True
    assert pair.leg_odd.candidate_won is True
    assert pair.leg_even.y_even == 1
    assert pair.leg_odd.y_even == -1
    assert pair.d_match == 1


def test_d_match_is_minus_one_when_the_opponent_wins_both_orientations() -> None:
    pair = synthetic_pair(even_winner=1, odd_winner=0)
    assert pair.leg_even.candidate_won is False
    assert pair.leg_odd.candidate_won is False
    assert pair.d_match == -1


@pytest.mark.parametrize("winner", [0, 1])
def test_d_match_is_zero_when_the_same_seats_win_both_legs(winner: int) -> None:
    pair = synthetic_pair(even_winner=winner, odd_winner=winner)
    assert pair.d_match == 0
    assert pair.leg_even.candidate_won is not pair.leg_odd.candidate_won


def test_d_match_matches_the_defining_formula() -> None:
    for even_winner in (0, 1):
        for odd_winner in (0, 1):
            pair = synthetic_pair(even_winner=even_winner, odd_winner=odd_winner)
            expected = (pair.leg_even.y_even - pair.leg_odd.y_even) / 2
            assert pair.d_match == expected


# --------------------------------------------- win probability transformation


def test_candidate_win_probability_is_the_documented_transform() -> None:
    pairs = tuple(
        synthetic_pair(even_winner=0, odd_winner=1, index=index) for index in range(4)
    )
    summary = pair_inference(pairs, **ANALYSIS)
    assert summary["mean_d_match"] == 1.0
    assert summary["candidate_match_win_probability"] == 1.0
    assert summary["advantage_over_half"] == 0.5

    losses = tuple(
        synthetic_pair(even_winner=1, odd_winner=0, index=index) for index in range(4)
    )
    summary = pair_inference(losses, **ANALYSIS)
    assert summary["mean_d_match"] == -1.0
    assert summary["candidate_match_win_probability"] == 0.0
    assert summary["advantage_over_half"] == -0.5

    mixed = (
        synthetic_pair(even_winner=0, odd_winner=1, index=0),
        synthetic_pair(even_winner=1, odd_winner=0, index=1),
        synthetic_pair(even_winner=0, odd_winner=0, index=2),
        synthetic_pair(even_winner=1, odd_winner=1, index=3),
    )
    summary = pair_inference(mixed, **ANALYSIS)
    assert summary["mean_d_match"] == 0.0
    assert summary["candidate_match_win_probability"] == 0.5
    assert summary["pair_outcomes"] == {"win": 1, "tie": 2, "loss": 1}


def test_a_three_quarter_win_rate_maps_to_the_right_probability() -> None:
    pairs = (
        synthetic_pair(even_winner=0, odd_winner=1, index=0),
        synthetic_pair(even_winner=0, odd_winner=1, index=1),
        synthetic_pair(even_winner=0, odd_winner=1, index=2),
        synthetic_pair(even_winner=1, odd_winner=0, index=3),
    )
    summary = pair_inference(pairs, **ANALYSIS)
    assert summary["mean_d_match"] == 0.5
    assert summary["candidate_match_win_probability"] == 0.75
    assert summary["complete_pair_count"] == 4


# ------------------------------------------------------ the unit of inference


def test_only_pairs_are_counted_never_legs_or_deals() -> None:
    pairs = tuple(
        synthetic_pair(even_winner=0, odd_winner=1, index=index) for index in range(6)
    )
    summary = pair_inference(pairs, **ANALYSIS)
    assert summary["complete_pair_count"] == 6
    assert summary["unit_of_inference"] == "complete_complementary_match_pair"
    # Six pairs are twelve legs and many deals; the sample size stays six.
    assert summary["leg_length_distribution"]["count"] == 12
    assert summary["complete_pair_count"] != summary["leg_length_distribution"]["count"]
    assert summary["standard_error"] == 0.0 or summary["standard_error"] is not None


def test_the_standard_error_uses_the_pair_count() -> None:
    import math
    from statistics import stdev

    pairs = (
        synthetic_pair(even_winner=0, odd_winner=1, index=0),
        synthetic_pair(even_winner=1, odd_winner=0, index=1),
        synthetic_pair(even_winner=0, odd_winner=0, index=2),
        synthetic_pair(even_winner=0, odd_winner=1, index=3),
    )
    summary = pair_inference(pairs, **ANALYSIS)
    values = [1.0, -1.0, 0.0, 1.0]
    assert summary["standard_error"] == pytest.approx(
        stdev(values) / math.sqrt(len(values))
    )


# ---------------------------------------------------------- censoring is not a draw


def test_a_censored_leg_makes_its_pair_incomplete_and_excluded() -> None:
    censored = synthetic_pair(even_winner=0, odd_winner=None, index=9)
    assert censored.status is PairStatus.INCOMPLETE_CENSORED
    assert censored.d_match is None
    assert censored.analysable is False

    pairs = (
        synthetic_pair(even_winner=0, odd_winner=1, index=0),
        censored,
        synthetic_pair(even_winner=0, odd_winner=1, index=2),
    )
    summary = pair_inference(pairs, **ANALYSIS)
    assert summary["observed_pair_count"] == 3
    assert summary["complete_pair_count"] == 2
    assert summary["censored_pair_count"] == 1
    assert summary["censoring_rate_pairs"] == pytest.approx(1 / 3)
    # The censored pair does not drag the mean toward zero the way a draw would.
    assert summary["mean_d_match"] == 1.0
    assert summary["candidate_match_win_probability"] == 1.0


def test_a_censored_leg_cannot_claim_a_winner() -> None:
    """The record type refuses to let censoring become a policy outcome."""

    from tuppi_match import LegRecord, ScoreStateOccupancy

    honest = synthetic_leg(leg=LegIdentity.EVEN, winner=None)
    fields = {
        "comparison_id": honest.comparison_id,
        "stream_id": honest.stream_id,
        "leg": honest.leg,
        "initial_dealer": honest.initial_dealer,
        "safety_cap": honest.safety_cap,
        "status": LegStatus.CENSORED_INFRASTRUCTURE,
        "deals_consumed": honest.deals_consumed,
        "consumed_deal_ids": honest.consumed_deal_ids,
        "final_score": honest.final_score,
        "resets": 0,
        "rami_deals": honest.deals_consumed,
        "nolo_deals": 0,
        "successful_rami": honest.deals_consumed,
        "stolen_rami": 0,
        "declarer_seat_counts": honest.declarer_seat_counts,
        "candidate_deal_points": 0,
        "opponent_deal_points": 0,
        "candidate_tricks": 0,
        "opponent_tricks": 0,
        "immediate_completion": False,
        "occupancy": ScoreStateOccupancy(
            deals_at_table=honest.deals_consumed,
            deals_candidate_up=0,
            deals_candidate_down=0,
        ),
        "action_count": 0,
        "duration_seconds": 0.0,
        "failure_kind": "censored_infrastructure",
        "failure_detail": "synthetic censoring",
    }
    for claim in (
        {"winning_engine_team": 0, "even_partnership_won": None, "candidate_won": None},
        {"winning_engine_team": None, "even_partnership_won": True, "candidate_won": None},
        {"winning_engine_team": None, "even_partnership_won": None, "candidate_won": True},
    ):
        with pytest.raises(RecordError, match="censoring is never a policy outcome"):
            LegRecord.build(**fields, **claim)


def test_a_failed_pair_is_separated_from_a_censored_pair() -> None:
    failed = synthetic_pair(even_winner=0, odd_winner=None, index=4)
    from tuppi_match.records import PairRecord

    broken = PairRecord.build(
        comparison_id=failed.comparison_id,
        stream_id=failed.stream_id,
        leg_even=failed.leg_even,
        leg_odd=synthetic_leg(
            leg=LegIdentity.ODD,
            winner=None,
            status=LegStatus.FAILED,
            stream_id=failed.stream_id,
            comparison_id=failed.comparison_id,
            deal_ids=failed.leg_even.consumed_deal_ids,
        ),
    )
    assert broken.status is PairStatus.INCOMPLETE_FAILED
    summary = pair_inference((broken,), **ANALYSIS)
    assert summary["failed_pair_count"] == 1
    assert summary["censored_pair_count"] == 0
    assert summary["complete_pair_count"] == 0
    assert summary["candidate_match_win_probability"] is None
    assert "never treated as draws" in summary["warning"]


def test_an_all_censored_comparison_reports_nothing_rather_than_a_tie() -> None:
    pairs = tuple(
        synthetic_pair(even_winner=None, odd_winner=None, index=index)
        for index in range(3)
    )
    summary = pair_inference(pairs, **ANALYSIS)
    assert summary["complete_pair_count"] == 0
    assert summary["mean_d_match"] is None
    assert summary["candidate_match_win_probability"] is None
    assert summary["pair_outcomes"] == {"loss": 0, "tie": 0, "win": 0}


# ------------------------------------------------------------- reproducibility


def test_bootstrap_and_randomization_are_reproducible() -> None:
    pairs = (
        synthetic_pair(even_winner=0, odd_winner=1, index=0),
        synthetic_pair(even_winner=1, odd_winner=0, index=1),
        synthetic_pair(even_winner=0, odd_winner=1, index=2),
        synthetic_pair(even_winner=0, odd_winner=0, index=3),
        synthetic_pair(even_winner=0, odd_winner=1, index=4),
    )
    first = pair_inference(pairs, **ANALYSIS)
    second = pair_inference(pairs, **ANALYSIS)
    assert first == second

    other = dict(ANALYSIS)
    other["analysis_seed"] = "a-different-seed"
    third = pair_inference(pairs, **other)
    assert third["mean_d_match"] == first["mean_d_match"]
    assert third["sign_flip_p_value"] == first["sign_flip_p_value"]  # exact below 19


def test_the_randomization_test_is_exact_for_small_samples() -> None:
    pairs = tuple(
        synthetic_pair(even_winner=0, odd_winner=1, index=index) for index in range(5)
    )
    summary = pair_inference(pairs, **ANALYSIS)
    assert summary["sign_flip_method"] == "exact_sign_flip"
    assert summary["sign_flip_replicates"] == 2**5
    # Only the all-positive and all-negative flips are as extreme as observed.
    assert summary["sign_flip_p_value"] == pytest.approx(2 / 32)


def test_the_randomization_test_switches_to_monte_carlo_when_large() -> None:
    pairs = tuple(
        synthetic_pair(
            even_winner=0 if index % 3 else 1,
            odd_winner=1 if index % 3 else 0,
            index=index,
        )
        for index in range(24)
    )
    summary = pair_inference(pairs, **ANALYSIS)
    assert summary["sign_flip_method"] == "monte_carlo_sign_flip"
    assert summary["sign_flip_replicates"] == 400
    assert 0.0 < summary["sign_flip_p_value"] <= 1.0


def test_the_bootstrap_interval_brackets_the_mean() -> None:
    pairs = tuple(
        synthetic_pair(
            even_winner=0 if index % 4 else 1,
            odd_winner=1 if index % 4 else 0,
            index=index,
        )
        for index in range(20)
    )
    summary = pair_inference(pairs, **ANALYSIS)
    low, high = summary["bootstrap_confidence_interval"]
    assert low <= summary["mean_d_match"] <= high


# ------------------------------------------------------------ leg correlation


def test_leg_correlation_is_minus_one_when_the_deals_decide_everything() -> None:
    """If the same seats win both legs, the candidate always splits the pair."""

    pairs = tuple(
        synthetic_pair(even_winner=index % 2, odd_winner=index % 2, index=index)
        for index in range(8)
    )
    summary = pair_inference(pairs, **ANALYSIS)
    assert summary["mean_d_match"] == 0.0
    assert summary["complementary_leg_correlation"] == pytest.approx(-1.0)


def test_leg_correlation_is_plus_one_when_the_policy_decides_everything() -> None:
    pairs = tuple(
        synthetic_pair(
            even_winner=0 if index % 2 else 1,
            odd_winner=1 if index % 2 else 0,
            index=index,
        )
        for index in range(8)
    )
    summary = pair_inference(pairs, **ANALYSIS)
    assert summary["complementary_leg_correlation"] == pytest.approx(1.0)


# ------------------------------------------------------------------- validity


def test_inference_rejects_an_invalid_confidence_level() -> None:
    pairs = (synthetic_pair(even_winner=0, odd_winner=1),)
    with pytest.raises(InferenceError):
        pair_inference(pairs, **{**ANALYSIS, "confidence_level": 0.4})
    with pytest.raises(InferenceError):
        pair_inference([], **ANALYSIS)  # type: ignore[arg-type]


def test_length_distribution_reports_the_tail() -> None:
    summary = length_distribution([5, 10, 20, 40, 125])
    assert summary["count"] == 5
    assert summary["minimum"] == 5
    assert summary["maximum"] == 125
    assert summary["median"] == 20
    assert summary["p90"] is not None and summary["p90"] <= 125
    assert length_distribution([])["count"] == 0


def test_secondary_metrics_never_replace_the_primary() -> None:
    pairs = tuple(
        synthetic_pair(even_winner=0, odd_winner=1, index=index) for index in range(3)
    )
    secondary = secondary_metrics(pairs)
    assert secondary["complete_leg_count"] == 6
    assert "candidate_match_win_probability" not in secondary
    assert "d_match" not in secondary
    assert secondary["deals_per_match"]["count"] == 6
