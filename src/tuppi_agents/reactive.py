"""``reactive_contract_v1``: the simple transparent contract-aware baseline.

This layer is the bottom of the Phase 4 ladder for trick play. It uses only

* the observing player's own hand,
* the current trick,
* partner and opponent seat relations,
* the contract, and
* the legal action set.

It deliberately does **not** use inferred voids, public card accounting, or
match-score strategy. Higher rungs add exactly one capability each, so the
ladder's ablations are structural rather than parametric.

Every context has a fixed, named, lexicographic score layout. The layout order
*is* the rule priority; within a component the magnitude decides.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from tuppi_engine import Action, PlayCardAction, PlayerObservation
from tuppi_rules import Card, Contract, Suit

from .action_scoring import (
    CandidateEvaluation,
    ScoredActions,
    component_layout,
    score_legal_actions,
)
from .errors import PolicyError
from .features import PublicFeatures
from .legacy_formulas import nolo_discard_liability
from .profiles import HeuristicProfile
from .protocol import RuleBasedPolicy
from .showing import score_showing
from .trick_context import TrickContext


COMMON_PLAY_RULES = (
    "common.play.differentiated_trick_reward.v1",
    "common.play.legal_actions_only.v1",
    "common.select.deterministic_maximum.v1",
)

RAMI_LEAD_LAYOUT = component_layout(("lead_suit_score", "lead_rank_preference"))
RAMI_FOLLOW_LAYOUT = component_layout(("trick_preference", "rank_cost"))
NOLO_LEAD_LAYOUT = component_layout(("lead_rank_cost", "lead_suit_shortness"))
NOLO_FOLLOW_LAYOUT = component_layout(("safe_loss_preference", "rank_preference"))
NOLO_DISCARD_LAYOUT = component_layout(
    ("discard_liability", "short_suit_bonus", "rank_preference")
)

_HONOUR_WEIGHT: dict[int, float] = {14: 4.0, 13: 3.0, 12: 2.0, 11: 1.0}

# Trick-preference tiers. Higher is better. The partner-aware layer adds the
# OVERTAKE_TO_SECURE tier; lower rungs never emit it.
TIER_UNDESIRABLE = 0.0
TIER_DESIRABLE = 2.0
TIER_OVERTAKE_TO_SECURE = 3.0


class PlayMode(StrEnum):
    RAMI_LEAD = "rami_lead"
    RAMI_FOLLOW = "rami_follow"
    NOLO_LEAD = "nolo_lead"
    NOLO_FOLLOW = "nolo_follow"
    NOLO_DISCARD = "nolo_discard"
    NOLO_CONCEDED = "nolo_conceded"
    COAST = "coast"


@dataclass(frozen=True, slots=True)
class PlayContext:
    """Per-decision facts shared by every candidate in one play decision."""

    mode: PlayMode
    contract: Contract
    trick: TrickContext
    features: PublicFeatures
    profile: HeuristicProfile
    any_safe_card: bool
    prefer_high_when_forced: bool
    suit_scores: tuple[tuple[Suit, float], ...]
    secure_decisive_trick: bool = False

    def suit_score(self, suit: Suit) -> float:
        for candidate, value in self.suit_scores:
            if candidate is suit:
                return value
        raise PolicyError("suit score requested for a suit not present in hand")


def base_play_mode(features: PublicFeatures) -> PlayMode:
    trick = features.require_trick()
    contract = features.deal.contract
    if contract is None:
        raise PolicyError("trick play requires a resolved contract")
    if contract is Contract.RAMI:
        return PlayMode.RAMI_LEAD if trick.is_leading else PlayMode.RAMI_FOLLOW
    if trick.is_leading:
        return PlayMode.NOLO_LEAD
    return PlayMode.NOLO_FOLLOW if trick.can_follow_suit else PlayMode.NOLO_DISCARD


def build_play_context(
    features: PublicFeatures,
    profile: HeuristicProfile,
    *,
    mode: PlayMode,
    secure_decisive_trick: bool = False,
) -> PlayContext:
    trick = features.require_trick()
    contract = features.deal.contract
    if contract is None:
        raise PolicyError("trick play requires a resolved contract")
    any_safe = bool(trick.currently_losing_cards)
    return PlayContext(
        mode=mode,
        contract=contract,
        trick=trick,
        features=features,
        profile=profile,
        any_safe_card=any_safe,
        prefer_high_when_forced=trick.is_last_to_play,
        suit_scores=_suit_scores(features, profile),
        secure_decisive_trick=secure_decisive_trick,
    )


def layout_for(mode: PlayMode) -> tuple[str, ...]:
    if mode is PlayMode.RAMI_LEAD:
        return RAMI_LEAD_LAYOUT
    if mode is PlayMode.RAMI_FOLLOW:
        return RAMI_FOLLOW_LAYOUT
    if mode is PlayMode.NOLO_LEAD:
        return NOLO_LEAD_LAYOUT
    if mode is PlayMode.NOLO_FOLLOW:
        return NOLO_FOLLOW_LAYOUT
    if mode is PlayMode.NOLO_DISCARD:
        return NOLO_DISCARD_LAYOUT
    raise PolicyError(f"mode {mode.value!r} has no reactive layout")


def reactive_components(
    card: Card, context: PlayContext
) -> tuple[tuple[float, ...], tuple[str, ...], tuple[str, ...]]:
    """Return the reactive score values, rule IDs, and reason codes."""

    mode = context.mode
    trick = context.trick
    if mode is PlayMode.RAMI_LEAD:
        return (
            (context.suit_score(card.suit), float(card.rank.value)),
            ("reactive.rami.lead_high_from_best_suit.v1",),
            ("rami_lead_best_suit",),
        )
    if mode is PlayMode.RAMI_FOLLOW:
        return _rami_follow_components(card, context)
    if mode is PlayMode.NOLO_LEAD:
        return (
            (
                -float(card.rank.value),
                -float(context.features.hand.suit_length(card.suit)),
            ),
            ("reactive.nolo.lead_lowest_from_shortest_suit.v1",),
            ("nolo_lead_low_short",),
        )
    if mode is PlayMode.NOLO_FOLLOW:
        safe = not trick.wins_now(card)
        if context.any_safe_card:
            rank = float(card.rank.value)
            rules = ("reactive.nolo.prefer_safe_loss.v1",)
            reasons = ("nolo_safe_loss",) if safe else ("nolo_would_win",)
        else:
            rank = (
                float(card.rank.value)
                if context.prefer_high_when_forced
                else -float(card.rank.value)
            )
            rules = ("reactive.nolo.forced_win_position_rule.v1",)
            reasons = (
                ("nolo_forced_win_last_seat",)
                if context.prefer_high_when_forced
                else ("nolo_forced_win_early_seat",)
            )
        return ((TIER_DESIRABLE if safe else TIER_UNDESIRABLE, rank), rules, reasons)
    if mode is PlayMode.NOLO_DISCARD:
        short = 1.0 if context.features.hand.suit_length(card.suit) <= 2 else 0.0
        return (
            (nolo_discard_liability(card), short, float(card.rank.value)),
            ("reactive.nolo.discard_highest_liability.v1",),
            ("nolo_discard_liability",),
        )
    raise PolicyError(f"mode {mode.value!r} is not a reactive mode")


def _rami_follow_components(
    card: Card, context: PlayContext
) -> tuple[tuple[float, ...], tuple[str, ...], tuple[str, ...]]:
    trick = context.trick
    wins = trick.wins_now(card)
    if trick.partner_is_winning:
        desirable = not wins
        rules = ("reactive.rami.avoid_overtaking_partner.v1",)
        reasons = ("rami_partner_holds_trick",) + (
            ("rami_avoids_overtaking",) if desirable else ("rami_overtakes_partner",)
        )
    else:
        desirable = wins
        rules = (
            ("reactive.rami.cheapest_current_winner.v1",)
            if wins
            else ("reactive.rami.preserve_strength_when_losing.v1",)
        )
        reasons = ("rami_takes_trick",) if wins else ("rami_cannot_take_trick",)
    return (
        (TIER_DESIRABLE if desirable else TIER_UNDESIRABLE, -float(card.rank.value)),
        rules,
        reasons,
    )


def _suit_scores(
    features: PublicFeatures, profile: HeuristicProfile
) -> tuple[tuple[Suit, float], ...]:
    bonus = float(profile.parameter("rami_lead_length_bonus"))
    scores: list[tuple[Suit, float]] = []
    for suit in Suit:
        length = features.hand.suit_length(suit)
        if length == 0:
            continue
        weight = sum(
            _HONOUR_WEIGHT.get(card.rank.value, 0.0)
            for card in features.own_hand
            if card.suit is suit
        )
        scores.append((suit, weight + bonus * length))
    return tuple(scores)


def score_reactive_play(
    observation: PlayerObservation,
    features: PublicFeatures,
    profile: HeuristicProfile,
) -> ScoredActions:
    mode = base_play_mode(features)
    context = build_play_context(features, profile, mode=mode)
    layout = layout_for(mode)

    def scorer(action: Action, index: int) -> CandidateEvaluation:
        card = card_of(action)
        values, rules, reasons = reactive_components(card, context)
        return CandidateEvaluation(
            action=action,
            action_order_index=index,
            component_names=layout,
            score_vector=values,
            rule_ids=tuple(sorted(set(rules + COMMON_PLAY_RULES))),
            reason_codes=(mode.value,) + reasons,
        )

    return score_legal_actions(observation, scorer)


def card_of(action: Action) -> Card:
    if not isinstance(action, PlayCardAction):
        raise PolicyError("trick-play observation contained a non-play action")
    return action.card


class ReactiveContractPolicy(RuleBasedPolicy):
    """The simple transparent contract-aware baseline agent."""

    def score_showing_actions(
        self, observation: PlayerObservation, features: PublicFeatures
    ) -> ScoredActions:
        return score_showing(observation, features, self.profile)

    def score_play_actions(
        self, observation: PlayerObservation, features: PublicFeatures
    ) -> ScoredActions:
        return score_reactive_play(observation, features, self.profile)
