"""``public_counting_v1``: the reactive baseline plus hard public inference.

This rung adds exactly one capability: proven public knowledge. It may use
inferred voids, public card accounting, and certainty deductions that follow
directly from the public record. It may not sample hidden hands, weight
possibilities, or assert an owner the public record does not prove.

Each added rule enters as a *new named component* in the score layout, placed at
the priority the rule claims. Nothing in the reactive layer is rewritten, so a
counting-versus-reactive ablation isolates exactly this capability.
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
from .errors import PolicyError
from .features import PublicFeatures
from .profiles import HeuristicProfile
from .protocol import RuleBasedPolicy
from .public_inference import PublicInference
from .trick_context import TrickContext
from .reactive import (
    COMMON_PLAY_RULES,
    PlayContext,
    PlayMode,
    base_play_mode,
    build_play_context,
    layout_for,
    reactive_components,
    card_of,
)
from .showing import score_showing


def counting_layout(mode: PlayMode) -> tuple[str, ...]:
    base = layout_for(_reactive_mode(mode))
    if mode is PlayMode.RAMI_LEAD:
        return component_layout(("certain_trick",) + base)
    if mode is PlayMode.RAMI_FOLLOW:
        return component_layout((base[0], "certainty") + base[1:])
    if mode is PlayMode.NOLO_LEAD:
        return component_layout((base[0], "unaccounted_higher_count") + base[1:])
    if mode is PlayMode.NOLO_FOLLOW:
        return component_layout((base[0], "shed_certain_winner") + base[1:])
    if mode in (PlayMode.NOLO_DISCARD, PlayMode.NOLO_CONCEDED):
        return component_layout(("shed_certain_winner",) + base)
    raise PolicyError(f"mode {mode.value!r} has no counting layout")


def counting_components(
    card: Card, context: PlayContext
) -> tuple[tuple[float, ...], tuple[str, ...], tuple[str, ...]]:
    inference = context.features.require_inference()
    base_values, rules, reasons = reactive_components(
        card, _as_reactive_context(context)
    )
    mode = context.mode
    if mode is PlayMode.RAMI_LEAD:
        certain = inference.is_highest_unplayed_in_suit(card)
        return (
            (1.0 if certain else 0.0,) + base_values,
            rules + ("counting.play.lead_certain_winner.v1",),
            reasons + (("certain_lead_winner",) if certain else ()),
        )
    if mode is PlayMode.RAMI_FOLLOW:
        certain = certainly_wins(card, context.trick, inference)
        return (
            (base_values[0], 1.0 if certain else 0.0) + base_values[1:],
            rules + ("counting.play.certain_winner_priority.v1",),
            reasons + (("certain_trick_winner",) if certain else ()),
        )
    if mode is PlayMode.NOLO_LEAD:
        higher = float(len(inference.unaccounted_higher_in_suit(card)))
        return (
            (base_values[0], higher) + base_values[1:],
            rules + ("counting.nolo.lead_suit_with_most_unaccounted_higher.v1",),
            reasons + ("counted_unaccounted_higher",),
        )
    if mode is PlayMode.NOLO_FOLLOW:
        shed = inference.is_highest_unplayed_in_suit(card)
        return (
            (base_values[0], 1.0 if shed else 0.0) + base_values[1:],
            rules + ("counting.nolo.avoid_retaining_certain_winner.v1",),
            reasons + (("sheds_certain_future_winner",) if shed else ()),
        )
    if mode in (PlayMode.NOLO_DISCARD, PlayMode.NOLO_CONCEDED):
        shed = inference.is_highest_unplayed_in_suit(card)
        return (
            (1.0 if shed else 0.0,) + base_values,
            rules + ("counting.nolo.avoid_retaining_certain_winner.v1",),
            reasons + (("sheds_certain_future_winner",) if shed else ()),
        )
    raise PolicyError(f"mode {mode.value!r} is not a counting mode")


def certainly_wins(
    card: Card, trick: TrickContext, inference: PublicInference
) -> bool:
    """True when public information proves the card takes the current trick.

    The card must beat the current best card of the led suit, and no seat that
    has not yet played may still be able to hold a higher card of that suit.
    ``project_target_v1`` has no trump suit, so an off-suit discard from a later
    seat can never take the trick.
    """

    if not trick.wins_now(card):
        return False
    if trick.is_leading:
        return inference.is_highest_unplayed_in_suit(card)
    return not inference.seats_that_could_hold_higher(card, trick.seats_still_to_play)


def partner_card_is_safe(trick: TrickContext, inference: PublicInference) -> bool:
    """True when no seat still to play can beat the partner's winning card."""

    if not trick.partner_is_winning or trick.current_winning_card is None:
        return False
    return not inference.seats_that_could_hold_higher(
        trick.current_winning_card, trick.seats_still_to_play
    )


def score_counting_play(
    observation: PlayerObservation,
    features: PublicFeatures,
    profile: HeuristicProfile,
) -> ScoredActions:
    mode = base_play_mode(features)
    context = build_play_context(features, profile, mode=mode)
    layout = counting_layout(mode)

    def scorer(action: Action, index: int) -> CandidateEvaluation:
        card = card_of(action)
        values, rules, reasons = counting_components(card, context)
        return CandidateEvaluation(
            action=action,
            action_order_index=index,
            component_names=layout,
            score_vector=values,
            rule_ids=tuple(sorted(set(rules + COMMON_PLAY_RULES))),
            reason_codes=(mode.value,) + reasons,
        )

    return score_legal_actions(observation, scorer)


def _reactive_mode(mode: PlayMode) -> PlayMode:
    """Map a higher-rung mode onto the reactive mode whose layout it reuses."""

    if mode is PlayMode.NOLO_CONCEDED:
        return PlayMode.NOLO_DISCARD
    return mode


def _as_reactive_context(context: PlayContext) -> PlayContext:
    if context.mode is PlayMode.NOLO_CONCEDED:
        from dataclasses import replace

        return replace(context, mode=PlayMode.NOLO_DISCARD)
    return context


class PublicCountingPolicy(RuleBasedPolicy):
    """The hard-public-inference baseline agent."""

    def score_showing_actions(
        self, observation: PlayerObservation, features: PublicFeatures
    ) -> ScoredActions:
        return score_showing(observation, features, self.profile)

    def score_play_actions(
        self, observation: PlayerObservation, features: PublicFeatures
    ) -> ScoredActions:
        return score_counting_play(observation, features, self.profile)
