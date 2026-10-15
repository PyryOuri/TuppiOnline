"""``legacy_heuristic_port_v1``: the frozen public-information heuristic, ported.

What is ported
--------------
The deterministic, public-information parts of the frozen
``HeuristicPolicy``: its RS/NHI expected-value contract choice, its
minimum-information show-card choice, its RAMI lead and follow branches, and its
NOLO lead, follow, forced-win, and discard branches. Legacy selection depended
on ``min``/``max`` over a hand sorted by ``(legacy suit index, -rank)``, so the
port reproduces that precedence explicitly as its own score component instead of
relying on any iteration order.

What is deliberately not ported
-------------------------------
``MonteCarloAI``, ``MonteCarloAdvisor``, ``estimate_value_generic``,
``simulate_from_state``, hidden-hand determinization, the shared module-global
RNG, the human input loop, and the presentation layer. There is no runtime
import of ``tuppi_legacy`` and no rollout of any kind.

Unavoidable semantic deviations
-------------------------------
1. **Show-rank eligibility.** Legacy banned only ranks 2, J, Q, K, so ranks 3-10
   and the ace were showable. ``project_target_v1`` allows only ranks 3-9. The
   port uses the target eligibility, so a legacy choice of a ten or an ace is not
   reproducible.
2. **Cardless verbal declaration.** Legacy returned ``ShowBid(card=None,
   verbal=True)`` when it held no card of the wanted colour. ``project_target_v1``
   always requires a shown card and derives ``verbal_required`` from the
   authoritative fallback hierarchy, so the port shows the lowest eligible
   off-colour card instead.
3. **Flat scoring.** Legacy had a non-rising branch that lowered its RAMI bar to
   3.0. ``project_target_v1`` is always played in rising mode, so that branch is
   unreachable; its constant survives only as the configurable
   ``legacy_rami_ev_minimum_pressured`` parameter used for the opposite case.
4. **Dead threshold.** Legacy computed ``base_thr`` (17.0, adjusted by +1.0 near
   the winning line) and never used it. The port omits it.
5. **Score-state shape.** Legacy read a mutable ``ScoreState`` with a
   ``rising_team`` that could be ``None``. The port reads the frozen
   ``MatchScore`` and maps ``up_team is None`` to the legacy table case.
6. **No partnership awareness.** The frozen RAMI follow branch ignored who held
   the trick, so the port can and does overtake its own partner. This is
   preserved on purpose; it is one of the behaviours the higher ladder rungs are
   meant to improve on.

Complete behavioural equivalence across the two rulesets is therefore *not*
claimed. The Archive is the historical oracle only for the curated positions
where the two rule sets coincide.
"""

from __future__ import annotations

from dataclasses import dataclass

from tuppi_engine import Action, PlayerObservation
from tuppi_rules import Card, Contract, Suit

from .action_scoring import (
    CandidateEvaluation,
    ScoredActions,
    component_layout,
    score_legal_actions,
)
from .errors import PolicyError
from .features import PublicFeatures
from .legacy_formulas import (
    legacy_suit_lengths,
    legacy_suit_strength,
    nolo_discard_liability,
)
from .ordering import legacy_suit_precedence
from .profiles import HeuristicProfile
from .protocol import RuleBasedPolicy
from .reactive import COMMON_PLAY_RULES, PlayMode, base_play_mode, card_of
from .showing import score_showing
from .trick_context import TrickContext


LEGACY_RAMI_LEAD_LAYOUT = component_layout(
    (
        "legacy_lead_suit_strength",
        "legacy_lead_suit_length",
        "legacy_suit_precedence",
        "legacy_lead_rank",
    )
)
LEGACY_RAMI_FOLLOW_LAYOUT = component_layout(
    ("legacy_takes_trick", "legacy_rank_cost", "legacy_suit_precedence")
)
LEGACY_NOLO_LEAD_LAYOUT = component_layout(
    (
        "legacy_is_exit_card",
        "legacy_rank_cost",
        "legacy_suit_shortness",
        "legacy_suit_precedence",
    )
)
LEGACY_NOLO_FOLLOW_LAYOUT = component_layout(
    ("legacy_loses_trick", "legacy_rank_direction", "legacy_suit_precedence")
)
LEGACY_NOLO_DISCARD_LAYOUT = component_layout(
    (
        "legacy_liability",
        "legacy_short_suit_bonus",
        "legacy_rank",
        "legacy_suit_precedence",
    )
)

LEGACY_EXIT_RANKS = (2, 3, 4)


@dataclass(frozen=True, slots=True)
class LegacyPlayContext:
    mode: PlayMode
    trick: TrickContext
    features: PublicFeatures
    suit_lengths: tuple[int, int, int, int]
    suit_strengths: tuple[float, float, float, float]
    any_losing_card: bool

    def suit_length(self, suit: Suit) -> int:
        return self.suit_lengths[legacy_suit_precedence(suit)]

    def suit_strength(self, suit: Suit) -> float:
        return self.suit_strengths[legacy_suit_precedence(suit)]


def build_legacy_context(features: PublicFeatures) -> LegacyPlayContext:
    trick = features.require_trick()
    hand = features.own_hand
    lengths = legacy_suit_lengths(hand)
    strengths = tuple(legacy_suit_strength(hand, index) for index in range(4))
    return LegacyPlayContext(
        mode=base_play_mode(features),
        trick=trick,
        features=features,
        suit_lengths=lengths,
        suit_strengths=strengths,  # type: ignore[arg-type]
        any_losing_card=bool(trick.currently_losing_cards),
    )


def legacy_layout(mode: PlayMode) -> tuple[str, ...]:
    if mode is PlayMode.RAMI_LEAD:
        return LEGACY_RAMI_LEAD_LAYOUT
    if mode is PlayMode.RAMI_FOLLOW:
        return LEGACY_RAMI_FOLLOW_LAYOUT
    if mode is PlayMode.NOLO_LEAD:
        return LEGACY_NOLO_LEAD_LAYOUT
    if mode is PlayMode.NOLO_FOLLOW:
        return LEGACY_NOLO_FOLLOW_LAYOUT
    if mode is PlayMode.NOLO_DISCARD:
        return LEGACY_NOLO_DISCARD_LAYOUT
    raise PolicyError(f"the legacy port has no layout for {mode.value!r}")


def legacy_components(
    card: Card, context: LegacyPlayContext
) -> tuple[tuple[float, ...], tuple[str, ...], tuple[str, ...]]:
    mode = context.mode
    trick = context.trick
    precedence = -float(legacy_suit_precedence(card.suit))
    if mode is PlayMode.RAMI_LEAD:
        return (
            (
                context.suit_strength(card.suit),
                float(context.suit_length(card.suit)),
                precedence,
                float(card.rank.value),
            ),
            ("legacy.rami.lead_best_suit_highest_card.v1",),
            ("legacy_rami_lead",),
        )
    if mode is PlayMode.RAMI_FOLLOW:
        takes = trick.wins_now(card)
        return (
            (1.0 if takes else 0.0, -float(card.rank.value), precedence),
            ("legacy.rami.cheapest_winner_else_lowest.v1",),
            ("legacy_rami_takes_trick",) if takes else ("legacy_rami_dumps_low",),
        )
    if mode is PlayMode.NOLO_LEAD:
        is_exit = card.rank.value in LEGACY_EXIT_RANKS
        return (
            (
                1.0 if is_exit else 0.0,
                -float(card.rank.value),
                -float(context.suit_length(card.suit)),
                precedence,
            ),
            ("legacy.nolo.lead_lowest_exit_shortest_suit.v1",),
            ("legacy_nolo_exit_lead",) if is_exit else ("legacy_nolo_low_lead",),
        )
    if mode is PlayMode.NOLO_FOLLOW:
        loses = not trick.wins_now(card)
        if context.any_losing_card:
            direction = float(card.rank.value)
            rules = ("legacy.nolo.highest_losing_card.v1",)
            reasons = ("legacy_nolo_highest_loser",)
        else:
            direction = (
                float(card.rank.value)
                if trick.is_last_to_play
                else -float(card.rank.value)
            )
            rules = ("legacy.nolo.forced_win_position_rule.v1",)
            reasons = (
                ("legacy_nolo_forced_win_last_seat",)
                if trick.is_last_to_play
                else ("legacy_nolo_forced_win_early_seat",)
            )
        return ((1.0 if loses else 0.0, direction, precedence), rules, reasons)
    if mode is PlayMode.NOLO_DISCARD:
        short = 1.0 if context.suit_length(card.suit) <= 2 else 0.0
        return (
            (
                nolo_discard_liability(card),
                short,
                float(card.rank.value),
                precedence,
            ),
            ("legacy.nolo.discard_liability_table.v1",),
            ("legacy_nolo_discard",),
        )
    raise PolicyError(f"the legacy port cannot score mode {mode.value!r}")


def score_legacy_play(
    observation: PlayerObservation,
    features: PublicFeatures,
    profile: HeuristicProfile,
) -> ScoredActions:
    del profile  # the ported play branches take no profile parameter
    context = build_legacy_context(features)
    layout = legacy_layout(context.mode)

    def scorer(action: Action, index: int) -> CandidateEvaluation:
        card = card_of(action)
        values, rules, reasons = legacy_components(card, context)
        if len(values) != len(layout):
            raise PolicyError("legacy port score layout and values disagree")
        return CandidateEvaluation(
            action=action,
            action_order_index=index,
            component_names=layout,
            score_vector=values,
            rule_ids=tuple(sorted(set(rules + COMMON_PLAY_RULES))),
            reason_codes=(context.mode.value,) + reasons,
        )

    return score_legal_actions(observation, scorer)


class LegacyHeuristicPortPolicy(RuleBasedPolicy):
    """The ported frozen heuristic, with no legacy import and no rollouts."""

    def score_showing_actions(
        self, observation: PlayerObservation, features: PublicFeatures
    ) -> ScoredActions:
        if features.deal.contract is not None:  # pragma: no cover - engine invariant
            raise PolicyError("showing cannot run after the contract resolves")
        return score_showing(observation, features, self.profile)

    def score_play_actions(
        self, observation: PlayerObservation, features: PublicFeatures
    ) -> ScoredActions:
        if features.deal.contract not in (Contract.RAMI, Contract.NOLO):
            raise PolicyError("trick play requires a resolved contract")
        return score_legacy_play(observation, features, self.profile)
