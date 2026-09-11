"""Stable strategy-rule identities with explicit provenance classification.

Every heuristic rule and weighted feature used by a Phase 4 policy appears
here exactly once, with a stable identifier, the contract and phase it affects,
its condition, its action preference, its provenance, its rationale, its known
limitations, and the profiles that implement it.

Provenance is a claim about *where a rule came from*, not about how good it is.
No Phase 4 rule is labelled ``expert_validated``: no expert validation has been
performed for this project. No rule is labelled ``simulation_validated``
either, because that label is reserved for rules that survive a controlled
ablation with a preregistered comparison, which Phase 4 only sets up.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from .errors import RuleCatalogueError


RULE_CATALOGUE_SCHEMA_VERSION = "tuppi.agents.strategy_rule_catalogue.v1"

RAMI_ONLY = ("RAMI",)
NOLO_ONLY = ("NOLO",)
BOTH_CONTRACTS = ("NOLO", "RAMI")
SHOWING = ("SHOWING",)
TRICK_PLAY = ("TRICK_PLAY",)
ALL_PHASES = ("SHOWING", "TRICK_PLAY")


class Provenance(StrEnum):
    MECHANICAL = "mechanical"
    LEGACY_PORT = "legacy_port"
    GENERIC_TRICK_TAKING_HYPOTHESIS = "generic_trick_taking_hypothesis"
    PROJECT_HYPOTHESIS = "project_hypothesis"
    OWNER_SUPPLIED = "owner_supplied"
    EXPERT_VALIDATED = "expert_validated"
    SIMULATION_VALIDATED = "simulation_validated"


FORBIDDEN_PHASE4_PROVENANCE: frozenset[Provenance] = frozenset(
    (Provenance.EXPERT_VALIDATED, Provenance.SIMULATION_VALIDATED)
)


@dataclass(frozen=True, slots=True)
class StrategyRule:
    rule_id: str
    contracts: tuple[str, ...]
    phases: tuple[str, ...]
    condition: str
    action_preference: str
    provenance: Provenance
    rationale: str
    limitations: str
    implementing_profiles: tuple[str, ...]
    independently_disableable: bool
    schema_version: str = field(default=RULE_CATALOGUE_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.rule_id, str) or not self.rule_id:
            raise RuleCatalogueError("rule_id must be a nonempty string")
        if not self.rule_id.endswith(".v1"):
            raise RuleCatalogueError(f"rule {self.rule_id!r} must carry a version suffix")
        for label, value in (
            ("contracts", self.contracts),
            ("phases", self.phases),
            ("implementing_profiles", self.implementing_profiles),
        ):
            if type(value) is not tuple or not value:
                raise RuleCatalogueError(f"{label} must be a nonempty tuple")
            if len(set(value)) != len(value) or tuple(sorted(value)) != value:
                raise RuleCatalogueError(f"{label} must be sorted and unique")
        if any(item not in ("NOLO", "RAMI") for item in self.contracts):
            raise RuleCatalogueError("contracts must be NOLO and/or RAMI")
        if any(item not in ("SHOWING", "TRICK_PLAY") for item in self.phases):
            raise RuleCatalogueError("phases must be SHOWING and/or TRICK_PLAY")
        if not isinstance(self.provenance, Provenance):
            raise RuleCatalogueError("provenance must be a Provenance value")
        if self.provenance in FORBIDDEN_PHASE4_PROVENANCE:
            raise RuleCatalogueError(
                f"rule {self.rule_id!r} claims unearned provenance "
                f"{self.provenance.value!r}"
            )
        for label, text in (
            ("condition", self.condition),
            ("action_preference", self.action_preference),
            ("rationale", self.rationale),
            ("limitations", self.limitations),
        ):
            if not isinstance(text, str) or not text:
                raise RuleCatalogueError(f"{label} must be a nonempty string")
        if type(self.independently_disableable) is not bool:
            raise RuleCatalogueError("independently_disableable must be a boolean")


def _rule(
    rule_id: str,
    *,
    contracts: tuple[str, ...],
    phases: tuple[str, ...],
    condition: str,
    preference: str,
    provenance: Provenance,
    rationale: str,
    limitations: str,
    profiles: tuple[str, ...],
    disableable: bool = False,
) -> StrategyRule:
    return StrategyRule(
        rule_id=rule_id,
        contracts=contracts,
        phases=phases,
        condition=condition,
        action_preference=preference,
        provenance=provenance,
        rationale=rationale,
        limitations=limitations,
        implementing_profiles=tuple(sorted(profiles)),
        independently_disableable=disableable,
    )


_LEGACY = "legacy_heuristic_port_v1"
_REACTIVE = "reactive_contract_v1"
_REACTIVE_LEGACY_SHOW = "reactive_contract_legacy_show_v1"
_COUNTING = "public_counting_v1"
_PARTNER = "partner_aware_v1"
_PARTNER_CONVENTION = "partner_aware_legacy_convention_v1"
_MATCH = "match_aware_v1"
_MATCH_NO_STATE = "match_aware_no_match_features_v1"

_SIMPLE_SHOW_PROFILES = (
    _REACTIVE,
    _COUNTING,
    _PARTNER,
    _PARTNER_CONVENTION,
    _MATCH,
    _MATCH_NO_STATE,
)
_REACTIVE_PLAY_PROFILES = (
    _REACTIVE,
    _REACTIVE_LEGACY_SHOW,
    _COUNTING,
    _PARTNER,
    _PARTNER_CONVENTION,
    _MATCH,
    _MATCH_NO_STATE,
)
_COUNTING_PROFILES = (
    _COUNTING,
    _PARTNER,
    _PARTNER_CONVENTION,
    _MATCH,
    _MATCH_NO_STATE,
)
_PARTNER_PROFILES = (_PARTNER, _PARTNER_CONVENTION, _MATCH, _MATCH_NO_STATE)
_MATCH_PROFILES = (_MATCH,)
_ALL_PROFILES = (
    _LEGACY,
    _REACTIVE,
    _REACTIVE_LEGACY_SHOW,
    _COUNTING,
    _PARTNER,
    _PARTNER_CONVENTION,
    _MATCH,
    _MATCH_NO_STATE,
)


RULE_CATALOGUE: tuple[StrategyRule, ...] = tuple(
    sorted(
        (
            # ------------------------------------------------------ mechanical
            _rule(
                "common.play.legal_actions_only.v1",
                contracts=BOTH_CONTRACTS,
                phases=ALL_PHASES,
                condition="A policy is asked for an action.",
                preference=(
                    "Consider only the actions present in "
                    "PlayerObservation.legal_actions, in the engine's stable order."
                ),
                provenance=Provenance.MECHANICAL,
                rationale=(
                    "The engine rejects illegal actions and never repairs them, so "
                    "the legal set is the whole action space."
                ),
                limitations="None; this is a restatement of the rules.",
                profiles=_ALL_PROFILES,
            ),
            _rule(
                "common.select.deterministic_maximum.v1",
                contracts=BOTH_CONTRACTS,
                phases=ALL_PHASES,
                condition="More than one legal action remains after scoring.",
                preference=(
                    "Select the lexicographic maximum score vector; break ties by "
                    "the lowest engine legal-action index."
                ),
                provenance=Provenance.MECHANICAL,
                rationale=(
                    "A single documented tie-break makes the policy reproducible "
                    "without depending on set iteration or object identity."
                ),
                limitations=(
                    "The tie-break is arbitrary with respect to strength; it is "
                    "chosen only for reproducibility."
                ),
                profiles=_ALL_PROFILES,
            ),
            _rule(
                "common.show.authoritative_fallback.v1",
                contracts=BOTH_CONTRACTS,
                phases=SHOWING,
                condition="A policy declares a contract during showing.",
                preference=(
                    "Show only a card allowed by project_target_v1 "
                    "valid_show_cards; accept the derived verbal_required flag."
                ),
                provenance=Provenance.MECHANICAL,
                rationale=(
                    "project_target_v1 restricts show ranks to 3-9 and defines an "
                    "explicit off-colour and no-eligible-rank fallback hierarchy."
                ),
                limitations=(
                    "project_target_v1 has no cardless verbal declaration, so the "
                    "legacy 'declare with no card' branch cannot be reproduced."
                ),
                profiles=_ALL_PROFILES,
            ),
            _rule(
                "common.play.differentiated_trick_reward.v1",
                contracts=BOTH_CONTRACTS,
                phases=TRICK_PLAY,
                condition="A policy compares candidate cards by trick value.",
                preference=(
                    "Take the sign of a trick's value from the contract and keep "
                    "RAMI and NOLO on separate rule branches. The deal-point scale "
                    "is exposed as +4 per trick for a RAMI declaring team, +8 for a "
                    "RAMI defending partnership above the sixth trick, and -4 in "
                    "NOLO. No policy may use one undifferentiated trick reward."
                ),
                provenance=Provenance.MECHANICAL,
                rationale=(
                    "The scoring formulas award 4*(declarer tricks - 6), "
                    "8*(defender tricks - 6) and 4*(7 - fewer tricks); the sign and "
                    "the scale genuinely differ."
                ),
                limitations=(
                    "Marginal values are exact only away from the 6/7 boundary, "
                    "where the swing is larger than one increment."
                ),
                profiles=_ALL_PROFILES,
            ),
            # ------------------------------------------- legacy showing profile
            _rule(
                "show.legacy.rs_nhi_expected_value.v1",
                contracts=BOTH_CONTRACTS,
                phases=SHOWING,
                condition="A policy using the legacy showing profile must declare.",
                preference=(
                    "Declare RAMI when the ported RAMI expected value reaches the "
                    "minimum and exceeds the ported NOLO expected value by the "
                    "configured margin; otherwise declare NOLO."
                ),
                provenance=Provenance.LEGACY_PORT,
                rationale=(
                    "Ported verbatim from the frozen HeuristicPolicy: RS and NHI "
                    "feed logistic make/win estimates, which feed a Binomial(13, p) "
                    "expected value in the actual scoring tables."
                ),
                limitations=(
                    "The logistic centres, scales and the Binomial trick-share "
                    "abstraction are uncalibrated legacy constants; the frozen "
                    "emulator also computed an unused base threshold, which the "
                    "port omits as dead code."
                ),
                profiles=(_LEGACY, _REACTIVE_LEGACY_SHOW),
            ),
            _rule(
                "show.legacy.rising_score_threshold_adjustment.v1",
                contracts=RAMI_ONLY,
                phases=SHOWING,
                condition="The legacy showing profile evaluates the rising score.",
                preference=(
                    "Require a higher RAMI expected value when the own partnership "
                    "is up with at least the configured protected score, and a "
                    "lower one when the opponents are up that high."
                ),
                provenance=Provenance.LEGACY_PORT,
                rationale=(
                    "The frozen policy raised its RAMI bar to 6.0 to protect a "
                    "large rise and lowered it to 3.0 to gamble for a reset."
                ),
                limitations=(
                    "project_target_v1 is always played in rising mode, so the "
                    "legacy flat-scoring branch is unreachable and its 3.0 base is "
                    "retained only as a configurable parameter."
                ),
                profiles=(_LEGACY, _REACTIVE_LEGACY_SHOW),
            ),
            _rule(
                "show.legacy.minimum_information_card.v1",
                contracts=BOTH_CONTRACTS,
                phases=SHOWING,
                condition="The legacy showing profile has chosen a contract.",
                preference=(
                    "Show the lowest eligible rank of the contract colour; break "
                    "rank ties by the frozen legacy suit precedence "
                    "(spades, hearts, diamonds, clubs)."
                ),
                provenance=Provenance.LEGACY_PORT,
                rationale=(
                    "The frozen policy revealed the lowest allowed rank of the "
                    "wanted colour to minimise the information given away."
                ),
                limitations=(
                    "Legacy allowed ranks 3-10 and the ace; project_target_v1 "
                    "allows only 3-9, so the eligible set is narrower."
                ),
                profiles=(_LEGACY, _REACTIVE_LEGACY_SHOW),
            ),
            # ------------------------------------------- simple showing profile
            _rule(
                "show.simple.rami_strength_threshold.v1",
                contracts=RAMI_ONLY,
                phases=SHOWING,
                condition="A policy using the simple showing profile must declare.",
                preference=(
                    "Declare RAMI only when high-card points plus ace, control and "
                    "length bonuses reach the configured threshold."
                ),
                provenance=Provenance.PROJECT_HYPOTHESIS,
                rationale=(
                    "A small, readable set of hand descriptors is easier to ablate "
                    "than a calibrated formula and gives an honest floor."
                ),
                limitations=(
                    "The threshold is uncalibrated and is not claimed to be "
                    "optimal or even good."
                ),
                profiles=_SIMPLE_SHOW_PROFILES,
            ),
            _rule(
                "show.simple.nolo_suitability_veto.v1",
                contracts=RAMI_ONLY,
                phases=SHOWING,
                condition="The simple showing profile would otherwise declare RAMI.",
                preference=(
                    "Withhold the RAMI declaration when the NOLO suitability score "
                    "exceeds the configured veto threshold."
                ),
                provenance=Provenance.PROJECT_HYPOTHESIS,
                rationale=(
                    "A hand can be strong in high cards and still be a much better "
                    "NOLO hand; two explicit thresholds avoid comparing two "
                    "differently scaled scores."
                ),
                limitations="Both thresholds are uncalibrated.",
                profiles=_SIMPLE_SHOW_PROFILES,
            ),
            _rule(
                "show.simple.lowest_eligible_colour_card.v1",
                contracts=BOTH_CONTRACTS,
                phases=SHOWING,
                condition="The simple showing profile has chosen a contract.",
                preference=(
                    "Show the lowest eligible rank of the contract colour; break "
                    "rank ties by canonical project_target_v1 suit order."
                ),
                provenance=Provenance.PROJECT_HYPOTHESIS,
                rationale=(
                    "Revealing the lowest legal card gives an opponent the least "
                    "usable information about the rest of the hand."
                ),
                limitations=(
                    "Whether minimum-information showing is actually best in this "
                    "ruleset is untested."
                ),
                profiles=_SIMPLE_SHOW_PROFILES,
            ),
            # -------------------------------------------------- reactive: RAMI
            _rule(
                "reactive.rami.lead_high_from_best_suit.v1",
                contracts=RAMI_ONLY,
                phases=TRICK_PLAY,
                condition="The policy is on lead in a RAMI deal.",
                preference=(
                    "Score each own suit as its high-card weight plus the "
                    "configured length bonus times its length, then lead the "
                    "highest card of the best-scoring suit."
                ),
                provenance=Provenance.GENERIC_TRICK_TAKING_HYPOTHESIS,
                rationale=(
                    "With no trump suit, top cards and length are the two ordinary "
                    "sources of tricks; the length bonus makes their trade-off an "
                    "explicit, ablatable profile weight."
                ),
                limitations=(
                    "Ignores entries, opponent distribution and the value of "
                    "keeping a high card for a later round. The weight is "
                    "uncalibrated."
                ),
                profiles=_REACTIVE_PLAY_PROFILES,
            ),
            _rule(
                "reactive.rami.avoid_overtaking_partner.v1",
                contracts=RAMI_ONLY,
                phases=TRICK_PLAY,
                condition="A partner currently holds the trick in a RAMI deal.",
                preference=(
                    "Prefer a card that does not take the trick from the partner, "
                    "and among those prefer the lowest."
                ),
                provenance=Provenance.GENERIC_TRICK_TAKING_HYPOTHESIS,
                rationale=(
                    "The partnership already holds the trick, so spending a higher "
                    "card on it cannot add a trick."
                ),
                limitations=(
                    "Provisional: a later opponent may still overtake the partner, "
                    "and this rule does not look at who is still to play."
                ),
                profiles=_REACTIVE_PLAY_PROFILES,
                disableable=True,
            ),
            _rule(
                "reactive.rami.cheapest_current_winner.v1",
                contracts=RAMI_ONLY,
                phases=TRICK_PLAY,
                condition="An opponent currently holds the trick in a RAMI deal.",
                preference="Play the cheapest legal card that currently takes it.",
                provenance=Provenance.GENERIC_TRICK_TAKING_HYPOTHESIS,
                rationale="Winning with the cheapest sufficient card preserves strength.",
                limitations=(
                    "Provisional for any seat that is not last to play; the trick "
                    "can still be taken back."
                ),
                profiles=_REACTIVE_PLAY_PROFILES,
            ),
            _rule(
                "reactive.rami.preserve_strength_when_losing.v1",
                contracts=RAMI_ONLY,
                phases=TRICK_PLAY,
                condition="No legal card currently takes the trick in a RAMI deal.",
                preference="Play the lowest legal card.",
                provenance=Provenance.GENERIC_TRICK_TAKING_HYPOTHESIS,
                rationale="A trick that cannot be won should cost as little as possible.",
                limitations="Ignores discard signalling and future suit control.",
                profiles=_REACTIVE_PLAY_PROFILES,
            ),
            # -------------------------------------------------- reactive: NOLO
            _rule(
                "reactive.nolo.lead_lowest_from_shortest_suit.v1",
                contracts=NOLO_ONLY,
                phases=TRICK_PLAY,
                condition="The policy is on lead in a NOLO deal.",
                preference=(
                    "Lead the lowest rank available; break rank ties toward the "
                    "shortest own suit, then canonical suit order."
                ),
                provenance=Provenance.GENERIC_TRICK_TAKING_HYPOTHESIS,
                rationale=(
                    "A low lead is unlikely to win the trick, and shortening a suit "
                    "creates a void that lets the hand discard liabilities later."
                ),
                limitations=(
                    "Creating a void can also force the partnership to win later "
                    "tricks in other suits."
                ),
                profiles=_REACTIVE_PLAY_PROFILES,
            ),
            _rule(
                "reactive.nolo.prefer_safe_loss.v1",
                contracts=NOLO_ONLY,
                phases=TRICK_PLAY,
                condition="At least one legal card cannot take the current trick.",
                preference=(
                    "Prefer a card that cannot take the trick, and among those the "
                    "highest, shedding the largest safe liability."
                ),
                provenance=Provenance.GENERIC_TRICK_TAKING_HYPOTHESIS,
                rationale=(
                    "In a misere contract a trick is a penalty, and a card that is "
                    "safe now may be a forced winner later."
                ),
                limitations=(
                    "Safety is provisional for any seat that is not last to play."
                ),
                profiles=_REACTIVE_PLAY_PROFILES,
            ),
            _rule(
                "reactive.nolo.forced_win_position_rule.v1",
                contracts=NOLO_ONLY,
                phases=TRICK_PLAY,
                condition="Every legal card would currently take the trick.",
                preference=(
                    "Play the highest such card when last to play, otherwise the "
                    "lowest."
                ),
                provenance=Provenance.LEGACY_PORT,
                rationale=(
                    "Ported from the frozen policy: the last seat cannot be "
                    "overtaken, so it purges its largest liability; an earlier seat "
                    "keeps the trick cheap so a later seat can still take it."
                ),
                limitations=(
                    "The earlier-seat branch relies on an opponent or the partner "
                    "actually overtaking."
                ),
                profiles=_REACTIVE_PLAY_PROFILES,
            ),
            _rule(
                "reactive.nolo.discard_highest_liability.v1",
                contracts=NOLO_ONLY,
                phases=TRICK_PLAY,
                condition="The policy cannot follow the led suit in a NOLO deal.",
                preference=(
                    "Discard the highest-liability card by the ported liability "
                    "table, preferring short suits on ties."
                ),
                provenance=Provenance.LEGACY_PORT,
                rationale=(
                    "Ported from the frozen discard routine: aces and kings are the "
                    "cards most likely to be forced to win a later trick."
                ),
                limitations=(
                    "The liability weights are uncalibrated legacy constants."
                ),
                profiles=_REACTIVE_PLAY_PROFILES,
            ),
            # ---------------------------------------------- legacy port: play
            _rule(
                "legacy.rami.lead_best_suit_highest_card.v1",
                contracts=RAMI_ONLY,
                phases=TRICK_PLAY,
                condition="The legacy port is on lead in a RAMI deal.",
                preference=(
                    "Score each suit present in hand by honour weight plus a "
                    "length bonus and a tiny length tiebreaker, then lead the "
                    "highest card of the best suit."
                ),
                provenance=Provenance.LEGACY_PORT,
                rationale="Ported verbatim from the frozen RAMI lead branch.",
                limitations=(
                    "The 0.01-per-card term exists in the frozen code only to "
                    "avoid selecting an empty suit."
                ),
                profiles=(_LEGACY,),
            ),
            _rule(
                "legacy.rami.cheapest_winner_else_lowest.v1",
                contracts=RAMI_ONLY,
                phases=TRICK_PLAY,
                condition="The legacy port is following in a RAMI deal.",
                preference=(
                    "Play the cheapest card of the led suit that beats the current "
                    "best; otherwise the lowest card of the led suit; otherwise the "
                    "lowest legal card."
                ),
                provenance=Provenance.LEGACY_PORT,
                rationale="Ported verbatim from the frozen RAMI follow branch.",
                limitations=(
                    "The frozen branch ignored partnership state entirely, so the "
                    "port can overtake its own partner."
                ),
                profiles=(_LEGACY,),
            ),
            _rule(
                "legacy.nolo.highest_losing_card.v1",
                contracts=NOLO_ONLY,
                phases=TRICK_PLAY,
                condition="The legacy port can follow suit and lose the trick.",
                preference="Play the highest card of the led suit that still loses.",
                provenance=Provenance.LEGACY_PORT,
                rationale="Ported verbatim from the frozen NOLO follow branch.",
                limitations=(
                    "The frozen branch considered only cards of the led suit, so a "
                    "safe off-suit discard was never preferred while following."
                ),
                profiles=(_LEGACY,),
            ),
            _rule(
                "legacy.nolo.forced_win_position_rule.v1",
                contracts=NOLO_ONLY,
                phases=TRICK_PLAY,
                condition=(
                    "The legacy port holds led-suit cards but none of them loses "
                    "the trick."
                ),
                preference=(
                    "Play the highest led-suit card when last to play, otherwise "
                    "the lowest."
                ),
                provenance=Provenance.LEGACY_PORT,
                rationale=(
                    "Ported verbatim: the last seat cannot be overtaken and purges "
                    "its largest liability, while an earlier seat keeps the trick "
                    "cheap so a later seat can still take it."
                ),
                limitations=(
                    "The earlier-seat branch relies on some later seat actually "
                    "overtaking."
                ),
                profiles=(_LEGACY,),
            ),
            _rule(
                "legacy.nolo.discard_liability_table.v1",
                contracts=NOLO_ONLY,
                phases=TRICK_PLAY,
                condition="The legacy port cannot follow the led suit in NOLO.",
                preference=(
                    "Discard by the frozen liability table, then a short-suit bonus, "
                    "then the highest rank, then legacy suit precedence."
                ),
                provenance=Provenance.LEGACY_PORT,
                rationale=(
                    "Ported verbatim from ``_nolo_discard_any``, including its use "
                    "of full-hand suit lengths for the short-suit bonus."
                ),
                limitations=(
                    "The liability weights (4, 3, 2, 1, 0.5, 0.25) are uncalibrated "
                    "legacy constants."
                ),
                profiles=(_LEGACY,),
            ),
            _rule(
                "legacy.nolo.lead_lowest_exit_shortest_suit.v1",
                contracts=NOLO_ONLY,
                phases=TRICK_PLAY,
                condition="The legacy port is on lead in a NOLO deal.",
                preference=(
                    "Prefer an exit card of rank 2-4, choosing the lowest rank and "
                    "then the shortest suit; otherwise the lowest rank overall."
                ),
                provenance=Provenance.LEGACY_PORT,
                rationale="Ported verbatim from the frozen NOLO lead branch.",
                limitations="The 2-4 exit band is an uncalibrated legacy constant.",
                profiles=(_LEGACY,),
            ),
            # ------------------------------------------------------- counting
            _rule(
                "counting.play.lead_certain_winner.v1",
                contracts=RAMI_ONLY,
                phases=TRICK_PLAY,
                condition=(
                    "The policy is on lead and holds the highest unplayed card of "
                    "some suit."
                ),
                preference="Prefer leading that card.",
                provenance=Provenance.MECHANICAL,
                rationale=(
                    "project_target_v1 has no trump suit and only led-suit cards "
                    "can win, so the highest unplayed card of a suit wins with "
                    "certainty when it is led."
                ),
                limitations=(
                    "Certain for this trick only; it says nothing about who leads "
                    "the next one or about the rest of the deal."
                ),
                profiles=_COUNTING_PROFILES,
            ),
            _rule(
                "counting.play.certain_winner_priority.v1",
                contracts=RAMI_ONLY,
                phases=TRICK_PLAY,
                condition=(
                    "The policy is following, an opponent holds the trick, and some "
                    "legal card beats every led-suit card the remaining seats could "
                    "still hold."
                ),
                preference=(
                    "Prefer the cheapest such certain winner over a merely "
                    "provisional winner."
                ),
                provenance=Provenance.MECHANICAL,
                rationale=(
                    "Hard public inference proves that no remaining seat can hold a "
                    "higher card of the led suit, so the trick cannot be taken back."
                ),
                limitations=(
                    "Only as strong as the public record: an unaccounted higher "
                    "card blocks the deduction even when nobody actually holds it."
                ),
                profiles=_COUNTING_PROFILES,
            ),
            _rule(
                "counting.nolo.avoid_retaining_certain_winner.v1",
                contracts=NOLO_ONLY,
                phases=TRICK_PLAY,
                condition="The policy may discard or safely lose in a NOLO deal.",
                preference=(
                    "Prefer to shed a card that is the highest unplayed card of its "
                    "suit."
                ),
                provenance=Provenance.GENERIC_TRICK_TAKING_HYPOTHESIS,
                rationale=(
                    "A card that no unplayed card can beat is a guaranteed future "
                    "trick, which is exactly what a misere contract must avoid."
                ),
                limitations=(
                    "Shedding a top card can also strip a suit and force later "
                    "wins elsewhere."
                ),
                profiles=_COUNTING_PROFILES,
                disableable=True,
            ),
            _rule(
                "counting.nolo.lead_suit_with_most_unaccounted_higher.v1",
                contracts=NOLO_ONLY,
                phases=TRICK_PLAY,
                condition="The policy is on lead in a NOLO deal.",
                preference=(
                    "Among the lowest-rank candidates, prefer the card with the most "
                    "unaccounted higher cards in its suit."
                ),
                provenance=Provenance.GENERIC_TRICK_TAKING_HYPOTHESIS,
                rationale=(
                    "The count of unaccounted higher cards is a hard public count, "
                    "and a larger count means more cards that can take the trick "
                    "instead of the leader."
                ),
                limitations=(
                    "A count is not a probability; the rule makes no claim about "
                    "how those cards are distributed."
                ),
                profiles=_COUNTING_PROFILES,
                disableable=True,
            ),
            # -------------------------------------------------- partner aware
            _rule(
                "partner.rami.protect_certain_partner_winner.v1",
                contracts=RAMI_ONLY,
                phases=TRICK_PLAY,
                condition=(
                    "A partner holds the trick and no seat still to play can beat "
                    "the partner's card."
                ),
                preference="Never overtake; play the lowest legal card.",
                provenance=Provenance.MECHANICAL,
                rationale=(
                    "The partnership is certain to take the trick, so any card "
                    "spent on it is pure loss."
                ),
                limitations=(
                    "Certainty depends on the public record; unaccounted higher "
                    "cards defeat the deduction."
                ),
                profiles=_PARTNER_PROFILES,
            ),
            _rule(
                "partner.rami.overtake_when_partner_beatable.v1",
                contracts=RAMI_ONLY,
                phases=TRICK_PLAY,
                condition=(
                    "A partner holds the trick, a seat still to play could beat it, "
                    "and the policy holds a card that beats every such card."
                ),
                preference="Overtake with the cheapest certain winner.",
                provenance=Provenance.GENERIC_TRICK_TAKING_HYPOTHESIS,
                rationale=(
                    "Converting a beatable partner winner into an unbeatable one "
                    "secures a trick the partnership would otherwise risk."
                ),
                limitations=(
                    "Spends a high card on a trick the partner might have won "
                    "anyway, and the deduction ignores how likely that is."
                ),
                profiles=_PARTNER_PROFILES,
                disableable=True,
            ),
            _rule(
                "partner.nolo.dump_liability_when_partner_certainly_wins.v1",
                contracts=NOLO_ONLY,
                phases=TRICK_PLAY,
                condition=(
                    "A partner holds the trick in a NOLO deal and no seat still to "
                    "play can beat the partner's card."
                ),
                preference=(
                    "Treat the trick as already conceded by the partnership and "
                    "discard the highest-liability legal card."
                ),
                provenance=Provenance.MECHANICAL,
                rationale=(
                    "NOLO scores team trick totals, so once the partnership is "
                    "certain to take the trick the choice of card cannot change "
                    "the team count. Individual trick counts are not scored."
                ),
                limitations=(
                    "Ignores that taking the trick oneself would change who leads "
                    "the next trick."
                ),
                profiles=_PARTNER_PROFILES,
            ),
            _rule(
                "partner.nolo.prefer_leading_partner_void_suit.v1",
                contracts=NOLO_ONLY,
                phases=TRICK_PLAY,
                condition=(
                    "The policy is on lead in a NOLO deal and the partner is "
                    "publicly void in a candidate suit."
                ),
                preference="Prefer leading a suit the partner is publicly void in.",
                provenance=Provenance.GENERIC_TRICK_TAKING_HYPOTHESIS,
                rationale=(
                    "A void partner cannot be forced to win that trick and can "
                    "discard a liability instead."
                ),
                limitations=(
                    "Only voids proven by a public failure to follow are used, so "
                    "the rule is silent early in a deal."
                ),
                profiles=_PARTNER_PROFILES,
                disableable=True,
            ),
            _rule(
                "partner.rami.prefer_leading_suit_partner_can_follow.v1",
                contracts=RAMI_ONLY,
                phases=TRICK_PLAY,
                condition=(
                    "The policy is on lead in a RAMI deal and the partner is "
                    "publicly void in some candidate suit."
                ),
                preference="Avoid leading a suit the partner is publicly void in.",
                provenance=Provenance.GENERIC_TRICK_TAKING_HYPOTHESIS,
                rationale=(
                    "A void partner cannot support the suit, so the lead is worth "
                    "less to the partnership."
                ),
                limitations=(
                    "A void partner can also discard usefully; the rule is a weak "
                    "preference only."
                ),
                profiles=_PARTNER_PROFILES,
                disableable=True,
            ),
            _rule(
                "partner.legacy.minimum_information_show.v1",
                contracts=BOTH_CONTRACTS,
                phases=SHOWING,
                condition="The optional legacy convention profile is enabled.",
                preference=(
                    "Show with legacy suit precedence rather than canonical suit "
                    "order, reproducing the frozen implementation's implicit card "
                    "choice among equal ranks."
                ),
                provenance=Provenance.LEGACY_PORT,
                rationale=(
                    "The frozen policy's card choice depended on its hand sort "
                    "order; treating that as a partnership convention makes the "
                    "assumption explicit and separately testable."
                ),
                limitations=(
                    "There is no evidence that any partner interprets this choice, "
                    "and it must not be described as Finnish expert practice."
                ),
                profiles=(_PARTNER_CONVENTION,),
                disableable=True,
            ),
            # ---------------------------------------------------- match aware
            _rule(
                "match.play.coast_when_margin_worthless.v1",
                contracts=BOTH_CONTRACTS,
                phases=TRICK_PLAY,
                condition=(
                    "The own partnership's deal win is already secured and extra "
                    "margin cannot move the match: either the opponents hold the "
                    "rising score, or the own minimum win already reaches the "
                    "target."
                ),
                preference=(
                    "Stop competing for further tricks and play the lowest legal "
                    "card."
                ),
                provenance=Provenance.MECHANICAL,
                rationale=(
                    "A deal win by the non-rising partnership resets the score to "
                    "0-0 and awards it nothing, so a 56-point win and a 4-point win "
                    "have identical match value; and points beyond the target are "
                    "discarded. In both cases the remaining tricks are worthless."
                ),
                limitations=(
                    "Deliberately ignores tournament-style aggregate margin, which "
                    "project_target_v1 does not score."
                ),
                profiles=_MATCH_PROFILES,
                disableable=True,
            ),
            _rule(
                "match.play.secure_decisive_trick.v1",
                contracts=RAMI_ONLY,
                phases=TRICK_PLAY,
                condition=(
                    "The own partnership holds exactly six tricks, a partner "
                    "currently holds the trick, and a seat still to play could beat "
                    "the partner's card."
                ),
                preference=(
                    "Overtake the partner with the cheapest winning card even when "
                    "no card is a proven winner, instead of leaving the decisive "
                    "trick at risk."
                ),
                provenance=Provenance.PROJECT_HYPOTHESIS,
                rationale=(
                    "Crossing the 6/7 boundary changes the deal winner, which is "
                    "worth far more than one increment of margin or one preserved "
                    "high card."
                ),
                limitations=(
                    "Deterministic and myopic: it looks only at the current trick "
                    "and spends a card the partner might not have needed."
                ),
                profiles=_MATCH_PROFILES,
                disableable=True,
            ),
            _rule(
                "match.show.protect_terminal_lead.v1",
                contracts=RAMI_ONLY,
                phases=SHOWING,
                condition=(
                    "The own partnership is up and within the configured protected "
                    "distance of the target."
                ),
                preference=(
                    "Raise the RAMI declaration threshold, preferring the reliable "
                    "NOLO line."
                ),
                provenance=Provenance.PROJECT_HYPOTHESIS,
                rationale=(
                    "At 48 points any NOLO win scores at least 4 and reaches 52, "
                    "while a failed RAMI hands the opponents 8 per trick above six "
                    "and destroys the whole accumulated rise."
                ),
                limitations=(
                    "Reliability is asserted by rule, not estimated; the protected "
                    "distance and the threshold bonus are uncalibrated."
                ),
                profiles=_MATCH_PROFILES,
                disableable=True,
            ),
            _rule(
                "match.show.reset_opponent_rise.v1",
                contracts=RAMI_ONLY,
                phases=SHOWING,
                condition=(
                    "The opponents are up and within the configured pressure "
                    "distance of the target."
                ),
                preference="Lower the RAMI declaration threshold.",
                provenance=Provenance.PROJECT_HYPOTHESIS,
                rationale=(
                    "A deal win resets the opponents to 0-0 whatever its margin, so "
                    "the partnership should accept more variance to obtain one."
                ),
                limitations=(
                    "A failed RAMI also accelerates the opponents; the trade-off is "
                    "asserted, not computed."
                ),
                profiles=_MATCH_PROFILES,
                disableable=True,
            ),
        ),
        key=lambda rule: rule.rule_id,
    )
)


def rule_catalogue_by_id() -> dict[str, StrategyRule]:
    catalogue = {rule.rule_id: rule for rule in RULE_CATALOGUE}
    if len(catalogue) != len(RULE_CATALOGUE):
        raise RuleCatalogueError("rule catalogue contains duplicate rule IDs")
    return catalogue


_BY_ID = rule_catalogue_by_id()


def require_rule(rule_id: str) -> StrategyRule:
    try:
        return _BY_ID[rule_id]
    except KeyError as exc:
        raise RuleCatalogueError(f"unknown strategy rule {rule_id!r}") from exc


def require_rules(rule_ids: tuple[str, ...]) -> tuple[StrategyRule, ...]:
    return tuple(require_rule(rule_id) for rule_id in rule_ids)


def rules_for_profile(profile_key: str) -> tuple[StrategyRule, ...]:
    return tuple(
        rule for rule in RULE_CATALOGUE if profile_key in rule.implementing_profiles
    )


def disableable_rule_ids(profile_key: str) -> tuple[str, ...]:
    return tuple(
        rule.rule_id
        for rule in rules_for_profile(profile_key)
        if rule.independently_disableable
    )


def strategy_rule_to_data(rule: StrategyRule) -> dict[str, object]:
    return {
        "action_preference": rule.action_preference,
        "condition": rule.condition,
        "contracts": list(rule.contracts),
        "implementing_profiles": list(rule.implementing_profiles),
        "independently_disableable": rule.independently_disableable,
        "limitations": rule.limitations,
        "phases": list(rule.phases),
        "provenance": rule.provenance.value,
        "rationale": rule.rationale,
        "rule_id": rule.rule_id,
        "schema_version": rule.schema_version,
    }


def rule_catalogue_to_data() -> dict[str, object]:
    return {
        "no_expert_validated_rules": True,
        "rules": [strategy_rule_to_data(rule) for rule in RULE_CATALOGUE],
        "ruleset_id": "project_target_v1",
        "schema_version": RULE_CATALOGUE_SCHEMA_VERSION,
    }
