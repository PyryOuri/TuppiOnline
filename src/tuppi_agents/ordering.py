"""Explicitly versioned deterministic action ordering and tie-breaking.

Phase 4 policies never iterate a ``set``, never depend on dictionary insertion
order arising from incidental construction, never compare object identity, and
never consult the locale or randomized string hashing. Two orderings are
defined here and both are versioned:

``ACTION_ORDERING_ID``
    The engine's own stable legal-action order, copied verbatim from
    ``PlayerObservation.legal_actions``. Position in that tuple is the only
    tie-break used by any Phase 4 policy.

``LEGACY_SUIT_PRECEDENCE_ID``
    The frozen legacy hand order (spades, hearts, diamonds, clubs). It is not
    a tie-break; ``legacy_heuristic_port_v1`` folds it into its score vector so
    that the port reproduces the archived ``min``/``max`` selections, which
    depended on legacy hand ordering.
"""

from __future__ import annotations

from tuppi_engine import Action, PlayCardAction, PlayerObservation, ShowAction
from tuppi_rules import Card, Contract, Suit, card_to_index

from .errors import ObservationBoundaryError


ACTION_ORDERING_ID = "tuppi.agents.engine_legal_action_order.v1"
TIE_BREAK_ID = "lowest_engine_legal_action_index_v1"
LEGACY_SUIT_PRECEDENCE_ID = "legacy_v9_suit_precedence_shdc_v1"
CANONICAL_SUIT_PRECEDENCE_ID = "project_target_v1_suit_order_hdcs_v1"

# Frozen legacy suit indices were spades=0, hearts=1, diamonds=2, clubs=3 and
# ``sort_hand`` ordered a hand by that index. ``project_target_v1`` orders
# suits hearts, diamonds, clubs, spades instead.
_LEGACY_SUIT_PRECEDENCE: dict[Suit, int] = {
    Suit.SPADES: 0,
    Suit.HEARTS: 1,
    Suit.DIAMONDS: 2,
    Suit.CLUBS: 3,
}

_CONTRACT_PRECEDENCE: dict[Contract, int] = {Contract.NOLO: 0, Contract.RAMI: 1}


def require_observation(value: object) -> PlayerObservation:
    """Reject anything that is not a frozen formal player observation."""

    if not isinstance(value, PlayerObservation):
        raise ObservationBoundaryError(
            "a Phase 4 policy accepts only a PlayerObservation"
        )
    return value


def ordered_legal_actions(observation: PlayerObservation) -> tuple[Action, ...]:
    """Return the engine's stable legal-action order without copying state."""

    checked = require_observation(observation)
    actions = checked.legal_actions
    if type(actions) is not tuple or not actions:
        raise ObservationBoundaryError("observation contains no legal action")
    return actions


def legacy_suit_precedence(suit: Suit) -> int:
    if not isinstance(suit, Suit):
        raise ObservationBoundaryError("legacy suit precedence requires a Suit")
    return _LEGACY_SUIT_PRECEDENCE[suit]


def legacy_card_order_key(card: Card) -> tuple[int, int]:
    """Reproduce the frozen ``sort_hand`` key: suit block, then rank descending."""

    return (legacy_suit_precedence(card.suit), -card.rank.value)


def canonical_card_order_key(card: Card) -> int:
    """Return the ``project_target_v1`` canonical deck index of a card."""

    return card_to_index(card)


def action_sort_key(action: Action) -> tuple[int, int, int]:
    """Return a total canonical order over engine actions.

    Show actions sort before play actions, shows sort by the engine's
    ``NOLO`` then ``RAMI`` contract order, and cards sort by canonical deck
    index. This function is used only for stable reporting of action sets; the
    selection tie-break is always the engine legal-action index.
    """

    if isinstance(action, ShowAction):
        return (
            0,
            _CONTRACT_PRECEDENCE[action.declared_contract],
            card_to_index(action.shown_card),
        )
    if isinstance(action, PlayCardAction):
        return (1, 0, card_to_index(action.card))
    raise ObservationBoundaryError("unsupported engine action type")
