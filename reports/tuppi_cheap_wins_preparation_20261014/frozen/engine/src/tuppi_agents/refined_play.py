"""``partner_aware_lead_v3``: ``partner_aware_lead_v2`` with three RAMI card-play corrections.

The corrections were found by disagreement mining against a strong self-play
policy (TuppiAI ``models/vrpo3_final.pt``) and each was measured paired against
``partner_aware_lead_v2`` in this engine (project_target_v3), with
pre-registered screens and confirmations (TuppiAI ``docs/HEURISTIC_PLAN.md``):

* **cash a singleton winner late**: leading in RAMI with at most five tricks
  left, lead a singleton that is a certain winner (the highest such);
* **underlead an unsupported honour**: leading in RAMI, if the inherited choice
  is the top card of a suit and that card is not a certain winner, lead the
  suit's lowest card instead;
* **second hand low**: second to play in RAMI and following suit, if the
  inherited choice would win the trick now but is not a certain winner, play
  the lowest card of the led suit instead.

A card is a *certain winner* when every higher card of its suit is in the
player's own hand or already played: led, it wins the trick whatever the
others hold. Only the player's own hand and the public play history are used.

Package result against ``partner_aware_lead_v2`` (4,096 base deals each):
+0.00502 [+0.00456, +0.00549] match equity per deal from 0-0, and
+0.01225 [+0.01075, +0.01374] from uniformly drawn starting scores. Measured
paired, not expert-validated, and not a Phase 4 profile. NOLO play and showing
are unchanged.
"""

from __future__ import annotations

from tuppi_engine import EnginePhase, PlayerObservation
from tuppi_rules import Card, Contract

from .action_scoring import ScoredActions
from .features import PublicFeatures
from .void_lead import VoidSeekingPartnerAwarePolicy

REFINED_PROFILE_KEY = "partner_aware_lead_v3"

CASH_COMPONENT = "cash_singleton_winner_preference"
CASH_REASON_CODE = "cash_singleton_winner_late"
UNDERLEAD_COMPONENT = "underlead_unsupported_honour_preference"
UNDERLEAD_REASON_CODE = "underlead_unsupported_honour"
SECOND_HAND_COMPONENT = "second_hand_low_preference"
SECOND_HAND_REASON_CODE = "second_hand_low"
#: The singleton rule applies only with at most this many tricks left; earlier
#: it measured negative for the declaring side.
CASH_MAX_TRICKS_LEFT = 5


def played_cards(observation: PlayerObservation) -> frozenset[Card]:
    """Every card played so far in the deal, including the current trick."""

    cards = {play.card for trick in observation.completed_tricks for play in trick.plays}
    cards.update(play.card for play in observation.current_trick)
    return frozenset(cards)


def certain_winner(card: Card, hand, played: frozenset[Card]) -> bool:
    """No unplayed higher card of the suit is outside the hand."""

    held = set(hand)
    return all(
        Card(suit=card.suit, rank=rank) in held or Card(suit=card.suit, rank=rank) in played
        for rank in type(card.rank)
        if rank.value > card.rank.value
    )


def _rami_trick_play(observation: PlayerObservation) -> bool:
    return (
        observation.phase is EnginePhase.TRICK_PLAY
        and observation.contract is Contract.RAMI
        and observation.current_actor == observation.observing_seat
    )


def cash_singleton_winner_late(observation: PlayerObservation, chosen: Card) -> Card | None:
    if not _rami_trick_play(observation) or observation.current_trick:
        return None
    if 13 - len(observation.completed_tricks) > CASH_MAX_TRICKS_LEFT:
        return None
    hand = observation.own_hand
    played = played_cards(observation)
    singletons = [
        card for card in hand
        if sum(1 for other in hand if other.suit is card.suit) == 1 and certain_winner(card, hand, played)
    ]
    if not singletons or chosen in singletons:
        return None
    return max(singletons, key=lambda card: card.rank.value)


def underlead_unsupported_honour(observation: PlayerObservation, chosen: Card) -> Card | None:
    if not _rami_trick_play(observation) or observation.current_trick:
        return None
    hand = observation.own_hand
    same = [card for card in hand if card.suit is chosen.suit]
    if len(same) < 2 or chosen != max(same, key=lambda card: card.rank.value):
        return None
    if certain_winner(chosen, hand, played_cards(observation)):
        return None
    return min(same, key=lambda card: card.rank.value)


def second_hand_low(observation: PlayerObservation, chosen: Card) -> Card | None:
    if not _rami_trick_play(observation) or len(observation.current_trick) != 1:
        return None
    lead = observation.current_trick[0].card
    if chosen.suit is not lead.suit or chosen.rank.value < lead.rank.value:
        return None
    hand = observation.own_hand
    if certain_winner(chosen, hand, played_cards(observation)):
        return None
    low = min((card for card in hand if card.suit is lead.suit), key=lambda card: card.rank.value)
    return None if low == chosen else low


#: Applied in order above the inherited (``partner_aware_lead_v2``) choice; the
#: first rule that changes the card decides.
REFINEMENTS = (
    (cash_singleton_winner_late, CASH_COMPONENT, CASH_REASON_CODE),
    (underlead_unsupported_honour, UNDERLEAD_COMPONENT, UNDERLEAD_REASON_CODE),
    (second_hand_low, SECOND_HAND_COMPONENT, SECOND_HAND_REASON_CODE),
)


class RefinedPartnerAwarePolicy(VoidSeekingPartnerAwarePolicy):
    """``partner_aware_lead_v2`` with the RAMI refinements above."""

    def score_play_actions(
        self, observation: PlayerObservation, features: PublicFeatures
    ) -> ScoredActions:
        scored = super().score_play_actions(observation, features)
        if not _rami_trick_play(observation):
            return scored
        selected = next(
            candidate for candidate in scored.candidates
            if candidate.action_order_index == scored.selected_index
        )
        chosen = getattr(selected.action, "card", None)
        if chosen is None:
            return scored
        for rule, component, reason in REFINEMENTS:
            wanted = rule(observation, chosen)
            if wanted is not None and wanted != chosen:
                return self._prefer(scored, wanted, component, reason)
        return scored
