"""``match_aware_v1``: partner awareness plus deterministic rising-score rules.

``project_target_v1`` uses one continuous rising score to 52, and only one
partnership may hold points at a time. That produces distinctions a deal-only
policy cannot see:

* at **0-0** the deal winner starts the rise at its deal points;
* when the acting partnership is **up**, deal points add to the rise, so margin
  has match value - until the smallest still-reachable win already reaches 52,
  after which extra margin is discarded;
* when the acting partnership is **down**, a deal win only resets the score to
  0-0 and awards it nothing, so a 56-point stolen RAMI and a 4-point NOLO win
  have exactly the same match value: zero margin, one reset.

Phase 4 has no search and no probability model, so match awareness is limited to
deterministic rules that the observation supports directly: a showing-threshold
overlay, a coasting rule for worthless margin, and one decisive-trick rule.

One negative finding is recorded here deliberately. "Deny the opponents' terminal
margin" was examined and *not* implemented as a separate rule: in both contracts
the opponents' points fall as the acting partnership takes more tricks, which is
already the direction ordinary play takes, so a distinct rule would change
nothing.
"""

from __future__ import annotations

from tuppi_engine import Action, PlayerObservation
from tuppi_rules import Contract

from .action_scoring import (
    CandidateEvaluation,
    ScoredActions,
    component_layout,
    score_legal_actions,
)
from .features import PublicFeatures
from .partner_aware import (
    SECURE_RULE,
    partner_components,
    partner_layout,
    partner_play_mode,
)
from .profiles import HeuristicProfile
from .protocol import RuleBasedPolicy
from .reactive import (
    COMMON_PLAY_RULES,
    PlayMode,
    build_play_context,
    card_of,
)
from .showing import score_showing


COAST_RULE = "match.play.coast_when_margin_worthless.v1"
COAST_LAYOUT = component_layout(("rank_cost",))


def margin_is_worthless(features: PublicFeatures) -> bool:
    """True when the deal win is secured and further margin cannot move the match."""

    deal = features.deal
    return (
        deal.own_deal_win_possible
        and not deal.opponent_deal_win_possible
        and not deal.margin_beyond_minimum_has_match_value
    )


def decisive_trick_pending(features: PublicFeatures) -> bool:
    """True when the own partnership's next trick decides a RAMI deal."""

    deal = features.deal
    return (
        deal.contract is Contract.RAMI
        and deal.own_win_requires_at_least_tricks is not None
        and deal.own_team_tricks == deal.own_win_requires_at_least_tricks - 1
    )


def match_play_mode(
    features: PublicFeatures, profile: HeuristicProfile
) -> PlayMode:
    if (
        profile.match_state_enabled
        and profile.rule_enabled(COAST_RULE)
        and margin_is_worthless(features)
    ):
        return PlayMode.COAST
    return partner_play_mode(features, profile)


def score_match_play(
    observation: PlayerObservation,
    features: PublicFeatures,
    profile: HeuristicProfile,
) -> ScoredActions:
    mode = match_play_mode(features, profile)
    if mode is not PlayMode.COAST:
        secure = (
            profile.match_state_enabled
            and profile.rule_enabled(SECURE_RULE)
            and decisive_trick_pending(features)
        )
        return _score_partner_like(observation, features, profile, secure=secure)

    context = build_play_context(features, profile, mode=mode)
    del context  # the coast layout needs no per-decision context

    def scorer(action: Action, index: int) -> CandidateEvaluation:
        card = card_of(action)
        return CandidateEvaluation(
            action=action,
            action_order_index=index,
            component_names=COAST_LAYOUT,
            score_vector=(-float(card.rank.value),),
            rule_ids=tuple(sorted(set((COAST_RULE,) + COMMON_PLAY_RULES))),
            reason_codes=(mode.value, "margin_has_no_match_value"),
        )

    return score_legal_actions(observation, scorer)


def _score_partner_like(
    observation: PlayerObservation,
    features: PublicFeatures,
    profile: HeuristicProfile,
    *,
    secure: bool,
) -> ScoredActions:
    mode = partner_play_mode(features, profile)
    context = build_play_context(
        features, profile, mode=mode, secure_decisive_trick=secure
    )
    layout = partner_layout(mode, profile)

    def scorer(action: Action, index: int) -> CandidateEvaluation:
        card = card_of(action)
        values, rules, reasons = partner_components(card, context)
        extra = ("secure_decisive_trick_active",) if secure else ()
        return CandidateEvaluation(
            action=action,
            action_order_index=index,
            component_names=layout,
            score_vector=values,
            rule_ids=tuple(sorted(set(rules + COMMON_PLAY_RULES))),
            reason_codes=(mode.value,) + reasons + extra,
        )

    return score_legal_actions(observation, scorer)


class MatchAwarePolicy(RuleBasedPolicy):
    """The rising-score-aware baseline agent."""

    def score_showing_actions(
        self, observation: PlayerObservation, features: PublicFeatures
    ) -> ScoredActions:
        return score_showing(observation, features, self.profile)

    def score_play_actions(
        self, observation: PlayerObservation, features: PublicFeatures
    ) -> ScoredActions:
        return score_match_play(observation, features, self.profile)
