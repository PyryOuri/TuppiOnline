"""Authoritative showing hierarchy and contract resolution."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from .cards import ELIGIBLE_SHOW_RANKS, card_color, normalize_cards
from .errors import (
    IncompleteShowingError,
    InvalidCardError,
    InvalidShowActionError,
    InvalidShowingSequenceError,
)
from .model import Card, Color, Contract, Rank, ShowAction, ShowingResolution
from .seating import forehand, validate_seat


def contract_color(contract: Contract) -> Color:
    if not isinstance(contract, Contract):
        raise InvalidShowActionError("declared contract must be a Contract value")
    return Color.RED if contract is Contract.RAMI else Color.BLACK


def is_show_rank_eligible(card_or_rank: Card | Rank) -> bool:
    if isinstance(card_or_rank, Card):
        rank = card_or_rank.rank
    elif isinstance(card_or_rank, Rank):
        rank = card_or_rank
    else:
        raise InvalidCardError("show-rank eligibility requires a Card or Rank value")
    return rank in ELIGIBLE_SHOW_RANKS


def valid_show_cards(
    hand: Iterable[Card], declared_contract: Contract
) -> frozenset[Card]:
    cards = normalize_cards(hand, context="showing hand", allow_empty=False)
    desired_color = contract_color(declared_contract)
    eligible = tuple(card for card in cards if is_show_rank_eligible(card))
    matching = tuple(card for card in eligible if card_color(card) is desired_color)
    if matching:
        return frozenset(matching)
    if eligible:
        return frozenset(eligible)
    return frozenset(cards)


def verbal_declaration_required(
    hand: Iterable[Card], shown_card: Card, declared_contract: Contract
) -> bool:
    cards = normalize_cards(hand, context="showing hand", allow_empty=False)
    if not isinstance(shown_card, Card):
        raise InvalidShowActionError("shown card must be a Card value")
    if shown_card not in cards:
        raise InvalidShowActionError("shown card must belong to the player's hand")
    if shown_card not in valid_show_cards(cards, declared_contract):
        raise InvalidShowActionError(
            "shown card is not allowed by the authoritative fallback hierarchy"
        )
    return not (
        is_show_rank_eligible(shown_card)
        and card_color(shown_card) is contract_color(declared_contract)
    )


def validate_show_action(
    *,
    seat: int,
    hand: Iterable[Card],
    shown_card: Card,
    declared_contract: Contract,
    claimed_verbal_required: bool | None = None,
) -> ShowAction:
    return ShowAction(
        seat=seat,
        hand=hand,
        shown_card=shown_card,
        declared_contract=declared_contract,
        claimed_verbal_required=claimed_verbal_required,
    )


def _derive_show_action_fields(
    *,
    seat: int,
    hand: Iterable[Card],
    shown_card: Card,
    declared_contract: Contract,
    claimed_verbal_required: bool | None,
) -> tuple[int, Card, Contract, bool]:
    validated_seat = validate_seat(seat)
    cards = normalize_cards(hand, context="showing hand", allow_empty=False)
    if len(cards) != 13:
        raise InvalidShowActionError(
            "a show action requires the player's complete 13-card hand"
        )
    verbal_required = verbal_declaration_required(
        cards, shown_card, declared_contract
    )
    if claimed_verbal_required is not None:
        if type(claimed_verbal_required) is not bool:
            raise InvalidShowActionError("claimed verbal_required must be a boolean")
        if claimed_verbal_required is not verbal_required:
            raise InvalidShowActionError(
                "claimed verbal_required disagrees with the value derived from the hand"
            )
    return (validated_seat, shown_card, declared_contract, verbal_required)


def resolve_showing(
    *, dealer: int, actions: Sequence[ShowAction]
) -> ShowingResolution:
    validated_dealer = validate_seat(dealer)
    if isinstance(actions, (str, bytes)):
        raise InvalidShowingSequenceError("actions must be a sequence of ShowAction values")
    try:
        normalized = tuple(actions)
    except TypeError as exc:
        raise InvalidShowingSequenceError(
            "actions must be a sequence of ShowAction values"
        ) from exc
    if len(normalized) > 4:
        raise InvalidShowingSequenceError("showing cannot contain more than four actions")
    for action in normalized:
        if not isinstance(action, ShowAction):
            raise InvalidShowingSequenceError("every showing item must be a ShowAction")
        if (
            type(action.seat) is not int
            or action.seat not in range(4)
            or not isinstance(action.shown_card, Card)
            or not isinstance(action.declared_contract, Contract)
            or type(action.verbal_required) is not bool
        ):
            raise InvalidShowingSequenceError(
                "ShowAction contains invalid or unvalidated fields"
            )
    seats = tuple(action.seat for action in normalized)
    if len(set(seats)) != len(seats):
        raise InvalidShowingSequenceError("a player cannot show more than once")
    expected = tuple((forehand(validated_dealer) + index) % 4 for index in range(4))
    if seats != expected[: len(seats)]:
        raise InvalidShowingSequenceError(
            f"showing seats must follow clockwise order {expected}; received {seats}"
        )

    rami_positions = tuple(
        index
        for index, action in enumerate(normalized)
        if action.declared_contract is Contract.RAMI
    )
    if rami_positions:
        first_rami = rami_positions[0]
        if first_rami != len(normalized) - 1:
            raise InvalidShowingSequenceError(
                "no action is allowed after the first RAMI declaration"
            )
        action = normalized[first_rami]
        return ShowingResolution(
            contract=Contract.RAMI,
            declarer=action.seat,
            actions=normalized,
        )

    if len(normalized) < 4:
        raise IncompleteShowingError(
            "an all-NOLO showing is unresolved until all four players have shown"
        )
    return ShowingResolution(
        contract=Contract.NOLO,
        declarer=None,
        actions=normalized,
    )


def rami_declarer(*, dealer: int, actions: Sequence[ShowAction]) -> int | None:
    return resolve_showing(dealer=dealer, actions=actions).declarer
