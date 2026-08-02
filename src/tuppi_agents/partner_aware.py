"""``partner_aware_v1``: public counting plus explicit partnership rules.

This rung adds partnership reasoning that is stated openly rather than hidden
in a signalling convention. Nothing here encodes a private meaning for a card:
the rules read only the public record and the scoring formulas.

Two of the rules are mechanical consequences of the ruleset rather than
hypotheses:

* if no seat still to play can beat a partner's winning card, the partnership is
  certain to take the trick, so overtaking cannot add a trick;
* NOLO scores *team* trick totals, so once the partnership is certain to take a
  trick, which partner takes it cannot change the score. Individual trick counts
  are never rewarded.

The convention-like rules have stable IDs, are independently disableable, and
are ``generic_trick_taking_hypothesis`` at best. The optional legacy showing
convention lives in its own profile with ``legacy_port`` provenance; it is never
described as Finnish expert practice.
"""

from __future__ import annotations

from tuppi_engine import Action, PlayerObservation
from tuppi_rules import Card

from .action_scoring import (
    CandidateEvaluation,
    ScoredActions,
    component_layout,
    score_legal_actions,
)
from .counting import (
    certainly_wins,
    counting_components,
    counting_layout,
    partner_card_is_safe,
)
from .errors import PolicyError
from .features import PublicFeatures
from .profiles import HeuristicProfile
from .protocol import RuleBasedPolicy
from .reactive import (
    COMMON_PLAY_RULES,
    TIER_DESIRABLE,
    TIER_OVERTAKE_TO_SECURE,
    TIER_UNDESIRABLE,
    PlayContext,
    PlayMode,
    base_play_mode,
    build_play_context,
    card_of,
)
from .showing import score_showing


PROTECT_RULE = "partner.rami.protect_certain_partner_winner.v1"
OVERTAKE_RULE = "partner.rami.overtake_when_partner_beatable.v1"
CONCEDE_RULE = "partner.nolo.dump_liability_when_partner_certainly_wins.v1"
NOLO_VOID_LEAD_RULE = "partner.nolo.prefer_leading_partner_void_suit.v1"
RAMI_FOLLOWABLE_LEAD_RULE = "partner.rami.prefer_leading_suit_partner_can_follow.v1"
SECURE_RULE = "match.play.secure_decisive_trick.v1"


def partner_play_mode(
    features: PublicFeatures, profile: HeuristicProfile
) -> PlayMode:
    mode = base_play_mode(features)
    if mode is not PlayMode.NOLO_FOLLOW or not profile.rule_enabled(CONCEDE_RULE):
        return mode
    inference = features.require_inference()
    if partner_card_is_safe(features.require_trick(), inference):
        return PlayMode.NOLO_CONCEDED
    return mode


def partner_layout(mode: PlayMode, profile: HeuristicProfile) -> tuple[str, ...]:
    base = counting_layout(mode)
    if mode is PlayMode.RAMI_LEAD and profile.rule_enabled(RAMI_FOLLOWABLE_LEAD_RULE):
        return component_layout((base[0], "partner_can_follow") + base[1:])
    if mode is PlayMode.NOLO_LEAD and profile.rule_enabled(NOLO_VOID_LEAD_RULE):
        return component_layout((base[0], "partner_void_in_suit") + base[1:])
    return base


def partner_components(
    card: Card, context: PlayContext
) -> tuple[tuple[float, ...], tuple[str, ...], tuple[str, ...]]:
    inference = context.features.require_inference()
    profile = context.profile
    partner_seat = context.features.partner_seat
    mode = context.mode

    if mode is PlayMode.RAMI_FOLLOW and context.trick.partner_is_winning:
        return _partner_rami_follow(card, context)

    values, rules, reasons = counting_components(card, context)

    if mode is PlayMode.RAMI_LEAD and profile.rule_enabled(RAMI_FOLLOWABLE_LEAD_RULE):
        can_follow = not inference.is_seat_void(partner_seat, card.suit)
        return (
            (values[0], 1.0 if can_follow else 0.0) + values[1:],
            rules + (RAMI_FOLLOWABLE_LEAD_RULE,),
            reasons + (("partner_can_follow",) if can_follow else ("partner_void",)),
        )
    if mode is PlayMode.NOLO_LEAD and profile.rule_enabled(NOLO_VOID_LEAD_RULE):
        partner_void = inference.is_seat_void(partner_seat, card.suit)
        return (
            (values[0], 1.0 if partner_void else 0.0) + values[1:],
            rules + (NOLO_VOID_LEAD_RULE,),
            reasons + (("partner_void",) if partner_void else ()),
        )
    if mode is PlayMode.NOLO_CONCEDED:
        return (
            values,
            rules + (CONCEDE_RULE,),
            reasons + ("partner_certainly_wins_team_count_fixed",),
        )
    return (values, rules, reasons)


def _partner_rami_follow(
    card: Card, context: PlayContext
) -> tuple[tuple[float, ...], tuple[str, ...], tuple[str, ...]]:
    inference = context.features.require_inference()
    trick = context.trick
    profile = context.profile
    wins = trick.wins_now(card)
    certain = certainly_wins(card, trick, inference)
    partner_safe = partner_card_is_safe(trick, inference)

    if partner_safe and profile.rule_enabled(PROTECT_RULE):
        tier = TIER_UNDESIRABLE if wins else TIER_DESIRABLE
        rules = (PROTECT_RULE,)
        reasons = ("partner_certainly_wins",) + (
            ("would_overtake_certain_partner",) if wins else ("protects_partner_trick",)
        )
    elif wins and certain and profile.rule_enabled(OVERTAKE_RULE):
        tier = TIER_OVERTAKE_TO_SECURE
        rules = (OVERTAKE_RULE,)
        reasons = ("partner_beatable", "overtakes_with_certain_winner")
    elif (
        wins
        and context.secure_decisive_trick
        and profile.rule_enabled(SECURE_RULE)
    ):
        tier = TIER_OVERTAKE_TO_SECURE
        rules = (SECURE_RULE,)
        reasons = ("partner_beatable", "overtakes_to_secure_decisive_trick")
    elif wins:
        tier = TIER_UNDESIRABLE
        rules = ("reactive.rami.avoid_overtaking_partner.v1",)
        reasons = ("partner_beatable", "declines_provisional_overtake")
    else:
        tier = TIER_DESIRABLE
        rules = ("reactive.rami.avoid_overtaking_partner.v1",)
        reasons = ("partner_beatable", "keeps_partner_on_trick")
    return (
        (tier, 1.0 if certain else 0.0, -float(card.rank.value)),
        rules,
        reasons,
    )


def score_partner_play(
    observation: PlayerObservation,
    features: PublicFeatures,
    profile: HeuristicProfile,
    *,
    secure_decisive_trick: bool = False,
) -> ScoredActions:
    mode = partner_play_mode(features, profile)
    context = build_play_context(
        features, profile, mode=mode, secure_decisive_trick=secure_decisive_trick
    )
    layout = partner_layout(mode, profile)

    def scorer(action: Action, index: int) -> CandidateEvaluation:
        card = card_of(action)
        values, rules, reasons = partner_components(card, context)
        if len(values) != len(layout):
            raise PolicyError("partner-aware score layout and values disagree")
        return CandidateEvaluation(
            action=action,
            action_order_index=index,
            component_names=layout,
            score_vector=values,
            rule_ids=tuple(sorted(set(rules + COMMON_PLAY_RULES))),
            reason_codes=(mode.value,) + reasons,
        )

    return score_legal_actions(observation, scorer)


class PartnerAwarePolicy(RuleBasedPolicy):
    """The partnership-aware baseline agent."""

    def score_showing_actions(
        self, observation: PlayerObservation, features: PublicFeatures
    ) -> ScoredActions:
        return score_showing(observation, features, self.profile)

    def score_play_actions(
        self, observation: PlayerObservation, features: PublicFeatures
    ) -> ScoredActions:
        return score_partner_play(observation, features, self.profile)
