"""A declared rule must turn an interval into a verdict, and refuse otherwise.

The rule exists because before it, every real candidate was recorded
INCONCLUSIVE - including one that lost by 20.33 points per block. That label
described the project's missing threshold, not the evidence.

Two questions are kept apart here and the tests pin both: whether an effect is
real, which the interval answers, and whether it is worth having, which only a
declared bar answers.
"""

from __future__ import annotations

import pytest

from tuppi_research.decisions import (
    DEAL_POINTS_SCREENING_RULE,
    DecisionRule,
    decide,
)
from tuppi_research.errors import CycleError
from tuppi_research.ledger import Verdict

RULE = DEAL_POINTS_SCREENING_RULE
ENDPOINT = RULE.endpoint


def verdict_for(low: float, high: float) -> Verdict:
    got, _ = decide(
        RULE, endpoint=ENDPOINT, confidence_interval=(low, high),
        confidence_level=0.95,
    )
    return got


@pytest.mark.parametrize(
    ("low", "high", "expected"),
    [
        (0.0, 0.0, Verdict.NO_EFFECT),            # the null control's exact zero
        (-0.5, 0.5, Verdict.NO_EFFECT),           # equivalent, contains zero
        (0.2, 0.6, Verdict.NO_EFFECT),            # real but immaterial
        (-0.8, -0.2, Verdict.NO_EFFECT),          # worse but immaterial
        (1.2, 3.0, Verdict.ACCEPTED),             # real and useful
        (-24.0, -16.66, Verdict.REJECTED),        # the shift candidate
        (-3.0, -0.5, Verdict.REJECTED),           # reliably worse
        (0.5, 3.0, Verdict.INCONCLUSIVE),         # straddles the bar
        (-2.0, 4.0, Verdict.INCONCLUSIVE),        # too wide to place
    ],
)
def test_the_four_way_mapping_is_exhaustive_and_ordered(low, high, expected):
    assert verdict_for(low, high) is expected


def test_equivalence_takes_precedence_over_direction():
    """The margin declares such differences immaterial, so rejecting one would
    contradict the rule that defines it."""
    assert verdict_for(-0.9, -0.1) is Verdict.NO_EFFECT
    assert verdict_for(-1.5, -0.1) is Verdict.REJECTED


def test_rejection_needs_no_usefulness_bar():
    """Establishing a candidate is not an improvement is the weaker claim."""
    verdict, statement = decide(
        RULE, endpoint=ENDPOINT, confidence_interval=(-5.0, -2.0),
        confidence_level=0.95,
    )
    assert verdict is Verdict.REJECTED
    assert "weaker claim" in statement


def test_a_rule_is_bound_to_one_endpoint():
    with pytest.raises(CycleError, match="cannot judge"):
        decide(
            RULE, endpoint="match_paired_win_rate",
            confidence_interval=(0.1, 0.2), confidence_level=0.95,
        )


def test_a_rule_is_bound_to_its_confidence_level():
    with pytest.raises(CycleError, match="declared at confidence"):
        decide(
            RULE, endpoint=ENDPOINT, confidence_interval=(0.1, 0.2),
            confidence_level=0.99,
        )


def test_an_inverted_or_malformed_interval_is_refused():
    with pytest.raises(CycleError, match="inverted"):
        decide(RULE, endpoint=ENDPOINT, confidence_interval=(1.0, 0.0),
               confidence_level=0.95)
    with pytest.raises(CycleError, match="low/high pair"):
        decide(RULE, endpoint=ENDPOINT, confidence_interval=(1.0,),
               confidence_level=0.95)


def test_rule_identity_is_a_content_address_over_the_bar():
    tighter = DecisionRule(
        endpoint=ENDPOINT, useful_effect=0.5, confidence_level=0.95,
        rationale="A different bar, for the test.",
    )
    assert tighter.rule_id != RULE.rule_id
    same = DecisionRule(
        endpoint=ENDPOINT, useful_effect=1.0, confidence_level=0.95,
        rationale="Reworded rationale must not change identity.",
    )
    assert same.rule_id == RULE.rule_id


def test_a_rule_must_declare_why_its_bar_is_where_it_is():
    with pytest.raises(CycleError, match="why its bar"):
        DecisionRule(
            endpoint=ENDPOINT, useful_effect=1.0, confidence_level=0.95,
            rationale="",
        )
    with pytest.raises(CycleError, match="positive quantity"):
        DecisionRule(
            endpoint=ENDPOINT, useful_effect=0.0, confidence_level=0.95,
            rationale="zero bar",
        )


def test_the_shipped_rule_records_its_three_anchors():
    assert RULE.useful_effect == 1.0
    assert RULE.confidence_level == 0.95
    for anchor in ("9.38", "11.21", "0.5"):
        assert anchor in RULE.rationale
    assert "promotion is governed separately" in RULE.rationale


def test_the_shipped_rule_cannot_promote():
    """A development verdict is not a promotion, and says so."""
    _, statement = decide(
        RULE, endpoint=ENDPOINT, confidence_interval=(2.0, 4.0),
        confidence_level=0.95,
    )
    assert "promotion is governed separately" in statement


def test_a_sample_too_small_for_an_interval_is_refused_not_guessed():
    """A one-unit run has no interval; inventing a verdict would be worse than
    refusing one."""
    with pytest.raises(CycleError, match="too small to place a candidate"):
        decide(
            RULE, endpoint=ENDPOINT, confidence_interval=None,
            confidence_level=0.95,
        )
