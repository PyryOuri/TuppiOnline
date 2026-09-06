"""N09 harness checks: the pairing, the signs, and what an incomplete block does.

Every mistake this file is written to catch is silent. A sign flipped in one of
the two effect families reads as a clean win. A four-arm map that puts the
candidate on the wrong seats still produces plausible numbers. An incomplete
block quietly dropped turns a partial trial into a confident one. None of those
raises an exception on its own, so each has an assertion here.

The trial itself is hours of exact search, so these run on hand-built blocks and
on a candidate configured to delegate everywhere, which exercises the same code
path at no cost.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tuppi_nolo.support import SupportBudget
from tuppi_nolo.trial import (
    ARMS,
    TRICK_IMPROVEMENT_THRESHOLD,
    WIN_NONINFERIORITY_MARGIN,
    _policies,
    analyse,
    contrast,
    play_arm,
    run_paired,
)

#: A candidate that is out of range at every decision, so C delegates to v2
#: everywhere and every arm must play the identical deal.
DELEGATING = SupportBudget(0, 100, 100_000)


def block(index, team0_by_arm, winner_by_arm=None):
    """One hand-built four-arm block with chosen Team-0 totals."""

    winner_by_arm = winner_by_arm or {}
    return {
        "deal_index": index,
        "complete": True,
        "arms": {
            arm: {
                "arm": arm,
                "team_tricks": [team0_by_arm[arm], 13 - team0_by_arm[arm]],
                "winner_team": winner_by_arm.get(arm, 0 if team0_by_arm[arm] < 7 else 1),
                "points": 0,
                "counters": {"decisions": 0, "plan_mismatches": 0},
            }
            for arm in ARMS
        },
    }


def uniform(count, *, bb, cb, bc, cc, winners=None):
    return [block(i, {"BB": bb, "CB": cb, "BC": bc, "CC": cc}, winners) for i in range(count)]


# ------------------------------------------------------------------- pairing


@pytest.mark.parametrize(
    "arm,expected",
    [("BB", set()), ("CB", {0, 2}), ("BC", {1, 3}), ("CC", {0, 1, 2, 3})],
)
def test_each_arm_puts_the_candidate_on_the_right_seats(arm, expected):
    """Team 0 is seats 0 and 2, and both seats of a team use its policy."""

    _agents, candidate_seats = _policies(arm, SupportBudget())
    assert candidate_seats == expected


def test_the_two_primary_contrasts_use_the_declared_arms_and_team_zero():
    report = analyse(uniform(4, bb=7, cb=6, bc=7, cc=6), attempted=4, cap_reached=False)
    assert report["primary"]["D_B"]["baseline_arm"] == "BB"
    assert report["primary"]["D_B"]["candidate_arm"] == "CB"
    assert report["primary"]["D_C"]["baseline_arm"] == "BC"
    assert report["primary"]["D_C"]["candidate_arm"] == "CC"
    assert {c["team"] for c in report["primary"].values()} == {0}


def test_the_team_one_mirror_is_reported_apart_and_never_pooled():
    report = analyse(uniform(4, bb=7, cb=6, bc=7, cc=6), attempted=4, cap_reached=False)
    assert set(report["primary"]) == {"D_B", "D_C"}
    assert {c["team"] for c in report["secondary_orientation_only"].values()} == {1}
    assert "secondary" not in report["primary"]


# --------------------------------------------------------------------- signs


def test_fewer_tricks_for_the_candidate_is_a_positive_trick_effect():
    """The sign convention, on totals chosen by hand: C takes one trick fewer."""

    report = analyse(uniform(16, bb=7, cb=6, bc=7, cc=6), attempted=16, cap_reached=False)
    for name in ("D_B", "D_C"):
        assert report["primary"][name]["tricks"]["mean_paired_utility"] == pytest.approx(1.0)


def test_more_tricks_for_the_candidate_is_a_negative_trick_effect():
    report = analyse(uniform(16, bb=6, cb=7, bc=6, cc=7), attempted=16, cap_reached=False)
    for name in ("D_B", "D_C"):
        assert report["primary"][name]["tricks"]["mean_paired_utility"] == pytest.approx(-1.0)


def test_a_deal_win_for_the_candidate_is_a_positive_win_effect():
    """The win family is oriented the other way round on purpose: more wins is
    better, fewer tricks is better, and both must come out positive for C."""

    winners = {"BB": 1, "CB": 0, "BC": 1, "CC": 0}
    report = analyse(uniform(16, bb=7, cb=6, bc=7, cc=6, winners=winners),
                     attempted=16, cap_reached=False)
    for name in ("D_B", "D_C"):
        assert report["primary"][name]["deal_wins"]["mean_paired_utility"] == pytest.approx(1.0)
        assert report["primary"][name]["tricks"]["mean_paired_utility"] == pytest.approx(1.0)


def test_a_contrast_of_a_bank_with_no_difference_is_exactly_zero():
    summary = contrast(uniform(8, bb=7, cb=7, bc=7, cc=7),
                       baseline_arm="BB", candidate_arm="CB", team=0)
    assert summary["tricks"]["mean_paired_utility"] == 0.0
    assert summary["deal_wins"]["mean_paired_utility"] == 0.0


# ------------------------------------------------------------------ endpoints


def test_a_clear_improvement_meets_every_endpoint():
    report = analyse(uniform(16, bb=7, cb=6, bc=7, cc=6), attempted=16, cap_reached=False)
    assert report["outcome"] == "SUPPORTED"
    assert report["sound"] is True


def test_a_clear_regression_is_reported_as_harm():
    report = analyse(uniform(16, bb=6, cb=7, bc=6, cc=7), attempted=16, cap_reached=False)
    assert report["outcome"] == "HARM_DETECTED"


def test_a_tiny_favourable_mean_is_inconclusive_not_a_weak_positive():
    """One deal in thirty-two improves by a trick: the mean lands below the
    threshold and the interval crosses zero, which the rule calls inconclusive."""

    blocks = uniform(31, bb=7, cb=7, bc=7, cc=7) + [
        block(99, {"BB": 7, "CB": 6, "BC": 7, "CC": 6})
    ]
    report = analyse(blocks, attempted=32, cap_reached=False)
    mean = report["primary"]["D_B"]["tricks"]["mean_paired_utility"]
    assert 0 < mean < TRICK_IMPROVEMENT_THRESHOLD
    assert report["outcome"] == "INCONCLUSIVE"


def test_winning_on_tricks_but_losing_deals_breaches_the_noninferiority_margin():
    losers = {"BB": 0, "CB": 1, "BC": 0, "CC": 1}
    report = analyse(uniform(16, bb=7, cb=6, bc=7, cc=6, winners=losers),
                     attempted=16, cap_reached=False)
    assert report["primary"]["D_B"]["deal_wins"]["mean_paired_utility"] == pytest.approx(-1.0)
    assert report["outcome"] in {"HARM_DETECTED", "INCONCLUSIVE"}
    assert report["outcome"] != "SUPPORTED", "tricks alone cannot carry the endpoint"


def test_the_thresholds_are_the_preregistered_ones():
    report = analyse(uniform(4, bb=7, cb=6, bc=7, cc=6), attempted=4, cap_reached=False)
    assert report["thresholds"]["trick_improvement"] == TRICK_IMPROVEMENT_THRESHOLD == 0.05
    assert report["thresholds"]["deal_win_noninferiority_margin"] == WIN_NONINFERIORITY_MARGIN
    assert report["thresholds"]["confidence_level"] == 0.95
    assert report["thresholds"]["bootstrap_replicates"] == 5000
    assert report["thresholds"]["analysis_seed"] == "nolo-info-strength-analysis-v1"


# -------------------------------------------------------- incomplete handling


def test_an_incomplete_block_is_counted_and_never_substituted():
    blocks = uniform(15, bb=7, cb=6, bc=7, cc=6) + [
        {"deal_index": 15, "complete": False, "error": "CB: TrialError()", "arms": {}}
    ]
    report = analyse(blocks, attempted=16, cap_reached=False)
    assert report["violations"]["incomplete_blocks"] == 1
    assert report["violations"]["blocks_complete"] == 15
    assert report["primary"]["D_B"]["tricks"]["incomplete_block_count"] == 1
    assert report["primary"]["D_B"]["tricks"]["independent_base_deals"] == 15
    assert report["outcome"] == "INCONCLUSIVE", "a partial bank cannot be SUPPORTED"
    assert report["incomplete"] == [{"deal_index": 15, "error": "CB: TrialError()"}]


def test_reaching_the_cap_is_inconclusive_however_good_the_effects_look():
    report = analyse(uniform(16, bb=7, cb=6, bc=7, cc=6), attempted=16, cap_reached=True)
    assert report["outcome"] == "INCONCLUSIVE" and report["sound"] is False


def test_a_broken_continuation_commitment_invalidates_the_trial():
    blocks = uniform(16, bb=7, cb=6, bc=7, cc=6)
    blocks[0]["arms"]["CB"]["counters"]["plan_mismatches"] = 1
    report = analyse(blocks, attempted=16, cap_reached=False)
    assert report["outcome"] == "INVALID"
    assert report["violations"]["plan_mismatches"] == 1


def test_a_short_bank_is_inconclusive_even_when_every_block_completed():
    report = analyse(uniform(15, bb=7, cb=6, bc=7, cc=6), attempted=16, cap_reached=False)
    assert report["outcome"] == "INCONCLUSIVE"


# ------------------------------------------------------------- the real thing


def test_a_delegating_candidate_produces_four_identical_arms(tmp_path):
    """The strongest end-to-end check available cheaply: if C never corrects
    anything, the four arms must play the same cards and every effect must be
    exactly zero. Any pairing or seat-assignment error would break this."""

    report = run_paired(seed="nolo-info-dev-v1", deals=2, workers=1, out_dir=tmp_path,
                        budget=DELEGATING, log=lambda message: None)
    assert report["violations"]["blocks_complete"] == 2
    assert report["violations"]["plan_mismatches"] == 0
    for family in ("tricks", "deal_wins"):
        for name in ("D_B", "D_C"):
            assert report["primary"][name][family]["mean_paired_utility"] == 0.0
        for name in report["secondary_orientation_only"]:
            assert report["secondary_orientation_only"][name][family][
                "mean_paired_utility"] == 0.0
    assert report["outcome"] == "INCONCLUSIVE", "no effect is not an improvement"
    assert (tmp_path / "blocks.jsonl").exists() and (tmp_path / "report.json").exists()


def test_a_delegating_candidate_never_claims_anything():
    result = play_arm("nolo-info-dev-v1", 0, "CC", budget=DELEGATING)
    counters = result["counters"]
    assert counters["decisions"] == 52, "all four candidate seats decide thirteen times"
    assert counters["corrections"] == 0 and counters["plan_commitments"] == 0
    assert counters["fallbacks"] == counters["decisions"]
    assert sum(result["team_tricks"]) == 13


def test_every_arm_plays_all_thirteen_tricks():
    for arm in ARMS:
        result = play_arm("nolo-info-dev-v1", 0, arm, budget=DELEGATING)
        assert sum(result["team_tricks"]) == 13
        assert result["winner_team"] in (0, 1)
