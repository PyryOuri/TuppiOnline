"""Declared decision rules: how an interval becomes a verdict.

Until now :func:`cycle.review` could return only NO_EFFECT for a control and
INCONCLUSIVE for everything else, because no useful-effect threshold existed. The
consequence was visible the first time a real candidate ran: a policy that lost by
20.33 points per block with a permutation p of 0.0005 was recorded
``inconclusive``, which is not a description of the evidence.

Two separate questions were being conflated, and this module keeps them apart.

*Is the effect real?* is answered by the native estimator's interval.
*Is the effect worth having?* is a value judgement that no amount of data
settles. It has to be declared, and it has to be declared **before** looking at a
candidate's result, or it is not a threshold - it is a rationalisation.

So a rule is a small immutable object with a content address, and every finding
records which rule judged it. Changing the threshold mints a new rule id rather
than silently re-interpreting old results.

Two further properties matter:

* **A rule is bound to one endpoint.** ``useful_effect`` is a quantity in the
  endpoint's own units, so it is meaningless against a different endpoint.
  :func:`decide` refuses rather than converting. If the project changes endpoint -
  which the endpoint-semantics work may force - the rule becomes void by
  construction instead of quietly carrying over.
* **A rule cannot promote.** It produces a development verdict. Promotion needs
  fresh sealed confirmation and staged rules, and nothing here reaches that.

Rejection deliberately needs no usefulness bar. Establishing that a candidate is
*not* an improvement is a weaker claim than establishing that it is a useful one,
and it only needs the interval to sit below zero.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json

from .errors import CycleError
from .ledger import Verdict

DECISION_RULE_SCHEMA_VERSION = "tuppi.research.decision_rule.v1"


@dataclass(frozen=True, slots=True)
class DecisionRule:
    """A declared, content-addressed mapping from interval to verdict."""

    endpoint: str
    useful_effect: float
    confidence_level: float
    rationale: str
    rule_id: str = field(default="", compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.endpoint, str) or not self.endpoint:
            raise CycleError("a decision rule requires an endpoint")
        if type(self.useful_effect) not in (int, float) or self.useful_effect <= 0:
            raise CycleError("useful_effect must be a positive quantity")
        if not 0.0 < self.confidence_level < 1.0:
            raise CycleError("confidence_level must lie strictly in (0, 1)")
        if not isinstance(self.rationale, str) or not self.rationale:
            raise CycleError("a decision rule must record why its bar is where it is")
        computed = _rule_id(
            endpoint=self.endpoint,
            useful_effect=float(self.useful_effect),
            confidence_level=float(self.confidence_level),
        )
        if self.rule_id and self.rule_id != computed:
            raise CycleError("rule_id disagrees with the declared bar")
        object.__setattr__(self, "rule_id", computed)

    def identity_data(self) -> dict[str, object]:
        return {
            "confidence_level": float(self.confidence_level),
            "endpoint": self.endpoint,
            "schema_version": DECISION_RULE_SCHEMA_VERSION,
            "useful_effect": float(self.useful_effect),
        }


def _rule_id(*, endpoint: str, useful_effect: float, confidence_level: float) -> str:
    payload = {
        "confidence_level": confidence_level,
        "endpoint": endpoint,
        "schema_version": DECISION_RULE_SCHEMA_VERSION,
        "useful_effect": useful_effect,
    }
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return f"rule:sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"


#: The candidate-screening rule for the signed-deal-points endpoint.
#:
#: SCOPE. This rule screens *candidate policies* on the development surrogate. It
#: does NOT govern headroom questions - "is there anything to be gained at this
#: decision" is measured in frozen-continuation equity against delta = 0.001, the
#: endpoint S1/S1b established with a symmetric-model control. A bar in the wrong
#: units is worse than no bar, so :func:`decide` refuses a foreign endpoint rather
#: than converting.
#:
#: The bar is 1.0 signed deal point per eight-game block, where two independently
#: measured anchors converge:
#:
#:   B. ~9% of a typical deal's swing (mean |deal points| 11.21, median 8) -> 0.78-1.0
#:   C. twice the effect the instrument already detects in ~20 min (0.5) -> 1.00
#:
#: A third anchor was originally declared and has been STRUCK: 10% of E1's
#: hindsight headroom (9.38 points per deal) gave 0.94. Hindsight headroom is not a
#: bound on achievable improvement. S1b measured a perfect observation-compatible
#: selector capturing only 3.9% of the oracle gap at showing, and E6 then priced a
#: rule drawn from a 3x hindsight-loss association and found the counterfactual
#: reversed its sign, netting -4.08 points per deal. Anchors B and C are measured
#: on realised play and stand; anchor A was measured on a quantity that does not
#: transfer, and it should never have been one of the three.
#:
#: Striking it does not move `rule_id`, which is a content address over endpoint,
#: bar and confidence only - so every finding already recorded under this rule
#: remains correctly attributed.
#:
#: It is testable: 193-313 base deals, 3-5 minutes, at the SD range P8 measured.
#: It is a SCREENING bar for deciding what to pursue, and explicitly not a
#: promotion criterion.
DEAL_POINTS_SCREENING_RULE = DecisionRule(
    endpoint="mean_signed_deal_points_per_eight_game_block",
    useful_effect=1.0,
    confidence_level=0.95,
    rationale=(
        "1.0 signed deal point per eight-game block, for screening CANDIDATE "
        "POLICIES on the development surrogate. Two measured anchors converge "
        "there: roughly 9% of a typical deal's swing, mean |deal points| 11.21 "
        "and median 8 (0.78-1.0); and twice the 0.5-point effect P8 showed the "
        "instrument already resolves in about twenty minutes (1.00). A third "
        "anchor, 10% of E1's hindsight headroom (0.94), has been STRUCK: "
        "hindsight headroom does not bound achievable improvement - S1b measured "
        "3.9% observation-compatible capture of the oracle gap at showing, and E6 "
        "found a rule built on a 3x hindsight association netted -4.08 points per "
        "deal once its counterfactual was priced. Headroom questions are governed "
        "instead by frozen-continuation equity against 0.001. Detectable in "
        "193-313 base deals, three to five minutes. Screening only; promotion is "
        "governed separately and this rule cannot reach it."
    ),
)


def decide(
    rule: DecisionRule,
    *,
    endpoint: str,
    confidence_interval: tuple[float, float] | list[float] | None,
    confidence_level: float,
) -> tuple[Verdict, str]:
    """Map an interval to a verdict under *rule*, or refuse.

    Order is fixed and equivalence comes first. The margin is precisely the
    declaration that differences this small do not matter, so rejecting a
    candidate for a difference already declared immaterial would be incoherent -
    an interval wholly inside the margin is practical equivalence even when it
    excludes zero. That is the standard equivalence reading, and the statement
    below records which of the two cases produced it.
    """

    if not isinstance(rule, DecisionRule):
        raise CycleError("decide requires a DecisionRule")
    if endpoint != rule.endpoint:
        raise CycleError(
            f"rule {rule.rule_id} is declared for {rule.endpoint!r} and cannot "
            f"judge {endpoint!r}; declare a rule for the new endpoint instead"
        )
    if abs(confidence_level - rule.confidence_level) > 1e-12:
        raise CycleError(
            f"rule {rule.rule_id} is declared at confidence "
            f"{rule.confidence_level} but the interval is at {confidence_level}"
        )
    if confidence_interval is None:
        raise CycleError(
            "the native summary carries no confidence interval, so this sample is "
            "too small to place a candidate; a verdict would be invented"
        )
    if len(confidence_interval) != 2:
        raise CycleError("confidence_interval must be a low/high pair")
    low, high = float(confidence_interval[0]), float(confidence_interval[1])
    if low > high:
        raise CycleError("confidence_interval is inverted")
    delta = float(rule.useful_effect)

    if low >= -delta and high <= delta:
        contains_zero = low <= 0.0 <= high
        detail = (
            "contains zero" if contains_zero
            else "excludes zero, so a real but immaterial difference"
        )
        return (
            Verdict.NO_EFFECT,
            f"Interval [{low:.4g}, {high:.4g}] lies wholly inside the "
            f"useful-effect margin of +/-{delta:g} and {detail}. The candidate is "
            f"practically equivalent to the incumbent on this endpoint.",
        )
    if low > delta:
        return (
            Verdict.ACCEPTED,
            f"Interval [{low:.4g}, {high:.4g}] lies wholly above the useful-effect "
            f"bar of {delta:g}, so the improvement is both real and useful on this "
            f"endpoint. Development verdict only: promotion is governed separately "
            f"and requires fresh sealed confirmation.",
        )
    if high < 0.0:
        return (
            Verdict.REJECTED,
            f"Interval [{low:.4g}, {high:.4g}] lies wholly below zero and reaches "
            f"beyond the useful-effect margin, so the candidate is reliably not an "
            f"improvement. Rejection needs no usefulness bar - it is the weaker "
            f"claim.",
        )
    return (
        Verdict.INCONCLUSIVE,
        f"Interval [{low:.4g}, {high:.4g}] straddles a decision boundary at "
        f"+/-{delta:g}, so this sample cannot place the candidate. Enlarging the "
        f"sample is legitimate only under a fresh preregistration.",
    )


__all__ = [
    "DEAL_POINTS_SCREENING_RULE",
    "DECISION_RULE_SCHEMA_VERSION",
    "DecisionRule",
    "decide",
]
