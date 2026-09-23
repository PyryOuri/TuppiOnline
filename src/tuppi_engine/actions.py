"""Immutable actions accepted by the clean engine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

from tuppi_rules import Card, Contract

from .errors import InvalidActionError


@dataclass(frozen=True, slots=True)
class ShowAction:
    seat: int
    shown_card: Card
    declared_contract: Contract

    def __post_init__(self) -> None:
        if type(self.seat) is not int or self.seat not in range(4):
            raise InvalidActionError("show-action seat must be an integer in 0..3")
        if not isinstance(self.shown_card, Card):
            raise InvalidActionError("shown_card must be a Card value")
        if not isinstance(self.declared_contract, Contract):
            raise InvalidActionError("declared_contract must be a Contract value")


@dataclass(frozen=True, slots=True)
class PlayCardAction:
    seat: int
    card: Card

    def __post_init__(self) -> None:
        if type(self.seat) is not int or self.seat not in range(4):
            raise InvalidActionError("play-action seat must be an integer in 0..3")
        if not isinstance(self.card, Card):
            raise InvalidActionError("played card must be a Card value")


@dataclass(frozen=True, slots=True)
class SooliDecisionAction:
    """project_target_v2: a defender accepts or declines playing sooli."""

    seat: int
    play_sooli: bool

    def __post_init__(self) -> None:
        if type(self.seat) is not int or self.seat not in range(4):
            raise InvalidActionError("sooli decision seat must be an integer in 0..3")
        if type(self.play_sooli) is not bool:
            raise InvalidActionError("play_sooli must be a boolean")


@dataclass(frozen=True, slots=True)
class SooliExchangeAction:
    """project_target_v2: the soolaaja gives, then the partner returns, one card."""

    seat: int
    card: Card

    def __post_init__(self) -> None:
        if type(self.seat) is not int or self.seat not in range(4):
            raise InvalidActionError("exchange seat must be an integer in 0..3")
        if not isinstance(self.card, Card):
            raise InvalidActionError("exchanged card must be a Card value")


Action: TypeAlias = ShowAction | PlayCardAction | SooliDecisionAction | SooliExchangeAction
