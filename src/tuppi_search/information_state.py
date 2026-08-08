"""Canonical root-player information states for Phase 5D-B.

The Phase 5C seed digest intentionally includes the engine's public match and
deal references.  Those references are useful protocol coordinates, but they are
not part of a behavioural information set.  This module is the stricter identity
used by the root information-set tree: it contains only observable state that can
change a legal action or a frozen policy decision.
"""

from __future__ import annotations

from tuppi_engine import PlayerObservation
from tuppi_eval.serialization import content_digest
from tuppi_rules import card_to_code

from .random import canonical_action_id


ROOT_INFORMATION_STATE_SCHEMA_VERSION = "tuppi.search.root_information_state.v1"


def root_information_state_data(
    observation: PlayerObservation,
) -> dict[str, object]:
    """Return the hidden-state-free semantic data for one root observation.

    ``match_ref`` and ``deal_ref`` are deliberately absent.  They identify an
    engine protocol entry, not a decision information set, and including either
    would prevent equivalent sampled worlds from sharing a node.
    """

    if not isinstance(observation, PlayerObservation):
        raise TypeError("root_information_state_data requires a PlayerObservation")
    return {
        "completed_tricks": [
            {
                "leader": trick.leader,
                "plays": [
                    {"card": card_to_code(play.card), "seat": play.seat}
                    for play in trick.plays
                ],
                "trick_index": trick.trick_index,
                "winner": trick.winner,
            }
            for trick in observation.completed_tricks
        ],
        "contract": None if observation.contract is None else observation.contract.value,
        "current_actor": observation.current_actor,
        "current_trick": [
            {"card": card_to_code(play.card), "seat": play.seat}
            for play in observation.current_trick
        ],
        "dealer": observation.dealer,
        "declarer": observation.declarer,
        "first_leader": observation.first_leader,
        "forehand": observation.forehand,
        "legal_actions": [canonical_action_id(action) for action in observation.legal_actions],
        "match_score": list(observation.match_score.as_tuple()),
        "observing_seat": observation.observing_seat,
        "own_hand": [card_to_code(card) for card in observation.own_hand],
        "phase": observation.phase.value,
        "public_void_suits": [
            sorted(suit.value for suit in suits)
            for suits in _public_void_suits(observation)
        ],
        "publicly_shown_cards": [
            {"card": card_to_code(card), "seat": seat}
            for seat, card in observation.publicly_shown_cards
        ],
        "root_partner_seat": observation.partner_seat,
        "root_team": observation.team.value,
        "ruleset_id": observation.ruleset_id.value,
        "schema_version": ROOT_INFORMATION_STATE_SCHEMA_VERSION,
        "show_actions": [
            {
                "declared_contract": action.declared_contract.value,
                "seat": action.seat,
                "shown_card": card_to_code(action.shown_card),
                "verbal_required": action.verbal_required,
            }
            for action in observation.show_actions
        ],
        "team_tricks": list(observation.team_tricks),
        "observation_schema": observation.schema_version,
    }


def _public_void_suits(observation: PlayerObservation) -> tuple[frozenset, ...]:
    """Derive only voids witnessed by public trick play.

    This deliberately does not invoke the Phase 5B constraint/sampling layer.
    Showing delegation can therefore compute a diagnostic identity without
    entering hidden-world inference at all; the sampler is used only after a
    trick-play search decision has been admitted.
    """

    voids: list[set] = [set(), set(), set(), set()]
    tricks = tuple(observation.completed_tricks) + (observation.current_trick,)
    for trick in tricks:
        plays = trick.plays if hasattr(trick, "plays") else trick
        if not plays:
            continue
        led = plays[0].card.suit
        for play in plays[1:]:
            if play.card.suit is not led:
                voids[play.seat].add(led)
    return tuple(frozenset(item) for item in voids)


def root_information_state_key(observation: PlayerObservation) -> str:
    """Return the canonical node key for the root player's information set."""

    return "rootinfo:" + content_digest(root_information_state_data(observation))
