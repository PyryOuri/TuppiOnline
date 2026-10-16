"""Two transparent showing policies under ``project_target_v1``.

``legacy_show_v1``
    Ports the frozen expected-value contract choice and the frozen
    minimum-information card choice, adapted to the target ruleset's 3-9
    eligibility and its explicit verbal fallback.

``simple_show_v1``
    Uses a small documented set of hand descriptors, an explicit RAMI
    declaration threshold, and an explicit NOLO suitability veto. Neither
    threshold is claimed to be optimal; both live in strict profile
    configuration so they can be ablated.

Both policies score every legal show action, so the decision and the shown-card
choice are separately testable.
"""

from __future__ import annotations

from dataclasses import dataclass

from tuppi_engine import Action, PlayerObservation, ShowAction
from tuppi_rules import Card, Contract, card_to_index

from .action_scoring import CandidateEvaluation, ScoredActions, component_layout, score_legal_actions
from .errors import PolicyError
from .features import MatchRole, PublicFeatures, VerbalFallbackCategory
from .legacy_formulas import (
    expected_value_nolo,
    expected_value_rami,
    nolo_hand_index,
    rami_strength,
)
from .ordering import LEGACY_SUIT_PRECEDENCE_ID, legacy_suit_precedence
from .profiles import HeuristicProfile, ShowingPolicyId


SHOW_SCORE_LAYOUT = component_layout(
    ("contract_preferred", "rank_preference", "suit_precedence")
)

_COMMON_SHOW_RULES = (
    "common.play.legal_actions_only.v1",
    "common.select.deterministic_maximum.v1",
    "common.show.authoritative_fallback.v1",
)


@dataclass(frozen=True, slots=True)
class ContractPreference:
    """The contract a showing policy wants, with its explaining scalars."""

    contract: Contract
    rule_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]
    scalars: tuple[tuple[str, float], ...]


def legacy_contract_preference(
    features: PublicFeatures, profile: HeuristicProfile
) -> ContractPreference:
    features.require_showing()
    cards = features.own_hand
    strength = rami_strength(cards)
    index = nolo_hand_index(cards)
    value_rami = expected_value_rami(strength)
    value_nolo = expected_value_nolo(index)

    deal = features.deal
    minimum = float(profile.parameter("legacy_rami_ev_minimum_table"))
    protected_score = int(profile.parameter("legacy_protected_score"))
    reasons = ["legacy_expected_value_choice"]
    rules = [
        "show.legacy.rs_nhi_expected_value.v1",
        "show.legacy.minimum_information_card.v1",
    ]
    if deal.match_role is MatchRole.UP and deal.own_match_points >= protected_score:
        minimum = float(profile.parameter("legacy_rami_ev_minimum_protected"))
        reasons.append("legacy_protect_large_rise")
        rules.append("show.legacy.rising_score_threshold_adjustment.v1")
    elif (
        deal.match_role is MatchRole.DOWN
        and deal.opponent_match_points >= protected_score
    ):
        minimum = float(profile.parameter("legacy_rami_ev_minimum_pressured"))
        reasons.append("legacy_gamble_for_reset")
        rules.append("show.legacy.rising_score_threshold_adjustment.v1")

    margin = float(profile.parameter("legacy_rami_ev_margin"))
    declares_rami = value_rami >= minimum and value_rami > value_nolo + margin
    reasons.append("rami_declared" if declares_rami else "nolo_declared")
    return ContractPreference(
        contract=Contract.RAMI if declares_rami else Contract.NOLO,
        rule_ids=tuple(sorted(set(rules))),
        reason_codes=tuple(reasons),
        scalars=(
            ("legacy_rami_strength", float(strength)),
            ("legacy_nolo_hand_index", float(index)),
            ("legacy_expected_value_rami", float(value_rami)),
            ("legacy_expected_value_nolo", float(value_nolo)),
            ("legacy_rami_expected_value_minimum", minimum),
            ("legacy_rami_expected_value_margin", margin),
        ),
    )


def simple_rami_score(features: PublicFeatures) -> float:
    """High-rank concentration, controls, and length, with fixed coefficients."""

    hand = features.hand
    return (
        float(hand.high_card_points)
        + 0.5 * hand.aces
        + 0.25 * hand.control_cards
        + 0.5 * max(0, hand.longest_suit_length - 4)
    )


def simple_nolo_score(features: PublicFeatures) -> float:
    """Low-rank concentration and shortness, minus dangerous high cards."""

    hand = features.hand
    return (
        1.5 * hand.low_card_count
        + 3.0 * hand.void_count
        + 2.0 * hand.singleton_count
        + 1.0 * hand.doubleton_count
        - 1.0 * hand.top_five_count
        - 0.5 * hand.honour_count
    )


def simple_contract_preference(
    features: PublicFeatures, profile: HeuristicProfile
) -> ContractPreference:
    features.require_showing()
    rami_score = simple_rami_score(features)
    nolo_score = simple_nolo_score(features)
    threshold = float(profile.parameter("simple_rami_threshold"))
    veto = float(profile.parameter("simple_nolo_veto_threshold"))
    reasons: list[str] = []
    rules = [
        "show.simple.rami_strength_threshold.v1",
        "show.simple.nolo_suitability_veto.v1",
        "show.simple.lowest_eligible_colour_card.v1",
    ]

    deal = features.deal
    if profile.match_state_enabled:
        if (
            deal.match_role is MatchRole.UP
            and deal.own_distance_to_target is not None
            and deal.own_distance_to_target
            <= int(profile.parameter("match_protect_distance"))
            and profile.rule_enabled("match.show.protect_terminal_lead.v1")
        ):
            threshold += float(profile.parameter("match_protect_threshold_bonus"))
            reasons.append("match_protect_terminal_lead")
            rules.append("match.show.protect_terminal_lead.v1")
        elif (
            deal.match_role is MatchRole.DOWN
            and deal.up_team_distance_to_target is not None
            and deal.up_team_distance_to_target
            <= int(profile.parameter("match_pressure_distance"))
            and profile.rule_enabled("match.show.reset_opponent_rise.v1")
        ):
            threshold -= float(profile.parameter("match_pressure_threshold_discount"))
            reasons.append("match_reset_opponent_rise")
            rules.append("match.show.reset_opponent_rise.v1")

    strong_enough = rami_score >= threshold
    vetoed = nolo_score > veto
    declares_rami = strong_enough and not vetoed
    if strong_enough:
        reasons.append("rami_threshold_met")
    if vetoed:
        reasons.append("nolo_veto_applied")
    reasons.append("rami_declared" if declares_rami else "nolo_declared")
    return ContractPreference(
        contract=Contract.RAMI if declares_rami else Contract.NOLO,
        rule_ids=tuple(sorted(set(rules))),
        reason_codes=tuple(reasons),
        scalars=(
            ("simple_rami_score", rami_score),
            ("simple_nolo_score", nolo_score),
            ("simple_rami_threshold", threshold),
            ("simple_nolo_veto_threshold", veto),
        ),
    )


def contract_preference(
    features: PublicFeatures, profile: HeuristicProfile
) -> ContractPreference:
    if profile.showing_policy is ShowingPolicyId.LEGACY:
        return legacy_contract_preference(features, profile)
    return simple_contract_preference(features, profile)


def score_showing(
    observation: PlayerObservation,
    features: PublicFeatures,
    profile: HeuristicProfile,
) -> ScoredActions:
    """Rank every legal show action under the profile's showing policy."""

    preference = contract_preference(features, profile)
    showing = features.require_showing()
    legacy_tie_break = profile.show_tie_break_id == LEGACY_SUIT_PRECEDENCE_ID
    rules = tuple(sorted(set(_COMMON_SHOW_RULES + preference.rule_ids)))
    if legacy_tie_break and profile.rule_enabled(
        "partner.legacy.minimum_information_show.v1"
    ):
        rules = tuple(sorted(set(rules + ("partner.legacy.minimum_information_show.v1",))))

    def scorer(action: Action, index: int) -> CandidateEvaluation:
        if not isinstance(action, ShowAction):
            raise PolicyError("showing observation contained a non-show action")
        matches = action.declared_contract is preference.contract
        category = showing.fallback_category(action.declared_contract)
        reasons = list(preference.reason_codes)
        reasons.append("preferred_contract" if matches else "rejected_contract")
        reasons.append(_category_code(category))
        return CandidateEvaluation(
            action=action,
            action_order_index=index,
            component_names=SHOW_SCORE_LAYOUT,
            score_vector=(
                1.0 if matches else 0.0,
                -float(action.shown_card.rank.value),
                -float(_suit_precedence(action.shown_card, legacy=legacy_tie_break)),
            ),
            rule_ids=rules,
            reason_codes=tuple(reasons),
        )

    return score_legal_actions(observation, scorer)


def showing_scalars(
    features: PublicFeatures, profile: HeuristicProfile
) -> tuple[tuple[str, float], ...]:
    """Expose the showing policy's explaining scalars for documentation use."""

    return contract_preference(features, profile).scalars


def _suit_precedence(card: Card, *, legacy: bool) -> int:
    if legacy:
        return legacy_suit_precedence(card.suit)
    return card_to_index(card) // 13


def _category_code(category: VerbalFallbackCategory) -> str:
    if category is VerbalFallbackCategory.DIRECT_COLOR_CARD:
        return "direct_colour_show_card"
    if category is VerbalFallbackCategory.ELIGIBLE_OFF_COLOR:
        return "verbal_fallback_off_colour"
    return "verbal_fallback_no_eligible_rank"
