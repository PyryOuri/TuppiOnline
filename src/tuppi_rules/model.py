"""Immutable value types for ``project_target_v1``."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import IntEnum, StrEnum

from .errors import (
    InvalidCardError,
    InvalidDealScoreError,
    InvalidMatchScoreError,
    InvalidSeatError,
    InvalidShowingSequenceError,
    InvalidTeamError,
)


class RulesetId(StrEnum):
    PROJECT_TARGET_V1 = "project_target_v1"


class Suit(StrEnum):
    HEARTS = "hearts"
    DIAMONDS = "diamonds"
    CLUBS = "clubs"
    SPADES = "spades"


class Color(StrEnum):
    RED = "red"
    BLACK = "black"


class Rank(IntEnum):
    TWO = 2
    THREE = 3
    FOUR = 4
    FIVE = 5
    SIX = 6
    SEVEN = 7
    EIGHT = 8
    NINE = 9
    TEN = 10
    JACK = 11
    QUEEN = 12
    KING = 13
    ACE = 14


class Contract(StrEnum):
    RAMI = "RAMI"
    NOLO = "NOLO"


class Team(IntEnum):
    TEAM_0 = 0
    TEAM_1 = 1


@dataclass(frozen=True, slots=True)
class Card:
    suit: Suit
    rank: Rank

    def __post_init__(self) -> None:
        if not isinstance(self.suit, Suit):
            raise InvalidCardError("card suit must be a Suit value")
        if not isinstance(self.rank, Rank):
            raise InvalidCardError("card rank must be a Rank value")

    def to_code(self) -> str:
        from .cards import card_to_code

        return card_to_code(self)

    @classmethod
    def from_code(cls, code: str) -> Card:
        from .cards import card_from_code

        return card_from_code(code)


@dataclass(frozen=True, slots=True, init=False)
class ShowAction:
    """A validated show action whose verbal flag was derived from its hand."""

    seat: int
    shown_card: Card
    declared_contract: Contract
    verbal_required: bool

    def __init__(
        self,
        *,
        seat: int,
        hand: Iterable[Card],
        shown_card: Card,
        declared_contract: Contract,
        claimed_verbal_required: bool | None = None,
    ) -> None:
        # Imported lazily to keep the immutable model independent of rule
        # module import order. The hand is validated but never retained.
        from .showing import _derive_show_action_fields

        validated = _derive_show_action_fields(
            seat=seat,
            hand=hand,
            shown_card=shown_card,
            declared_contract=declared_contract,
            claimed_verbal_required=claimed_verbal_required,
        )
        object.__setattr__(self, "seat", validated[0])
        object.__setattr__(self, "shown_card", validated[1])
        object.__setattr__(self, "declared_contract", validated[2])
        object.__setattr__(self, "verbal_required", validated[3])


@dataclass(frozen=True, slots=True)
class ShowingResolution:
    contract: Contract
    declarer: int | None
    actions: tuple[ShowAction, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.contract, Contract):
            raise InvalidShowingSequenceError(
                "resolution contract must be a Contract value"
            )
        if type(self.actions) is not tuple or not self.actions:
            raise InvalidShowingSequenceError(
                "resolution actions must be a non-empty tuple"
            )
        if any(not isinstance(action, ShowAction) for action in self.actions):
            raise InvalidShowingSequenceError(
                "resolution actions must contain only ShowAction values"
            )
        if self.contract is Contract.RAMI:
            if type(self.declarer) is not int or self.declarer not in range(4):
                raise InvalidShowingSequenceError(
                    "RAMI resolution requires a declarer in seats 0..3"
                )
            rami_positions = tuple(
                index
                for index, action in enumerate(self.actions)
                if action.declared_contract is Contract.RAMI
            )
            if rami_positions != (len(self.actions) - 1,):
                raise InvalidShowingSequenceError(
                    "RAMI resolution must end at its sole RAMI declaration"
                )
            if self.actions[-1].seat != self.declarer:
                raise InvalidShowingSequenceError(
                    "RAMI resolution declarer must be the final showing seat"
                )
        else:
            if self.declarer is not None:
                raise InvalidShowingSequenceError("NOLO resolution has no declarer")
            if len(self.actions) != 4 or any(
                action.declared_contract is not Contract.NOLO
                for action in self.actions
            ):
                raise InvalidShowingSequenceError(
                    "NOLO resolution requires exactly four NOLO actions"
                )


@dataclass(frozen=True, slots=True)
class PlayedCard:
    seat: int
    card: Card

    def __post_init__(self) -> None:
        if type(self.seat) is not int or self.seat not in range(4):
            raise InvalidSeatError("played-card seat must be an integer in 0..3")
        if not isinstance(self.card, Card):
            raise InvalidCardError("played card must be a Card value")


@dataclass(frozen=True, slots=True)
class DealScore:
    """An immutable complete-deal score that validates its own formula."""

    contract: Contract
    winner_team: Team
    points: int
    team_tricks: tuple[int, int]
    declaring_team: Team | None
    stolen_rami: bool

    def __post_init__(self) -> None:
        if not isinstance(self.contract, Contract):
            raise InvalidDealScoreError("deal-score contract must be a Contract value")
        if not isinstance(self.winner_team, Team):
            raise InvalidDealScoreError("deal-score winner must be a Team value")
        if type(self.points) is not int or self.points <= 0:
            raise InvalidDealScoreError("deal-score points must be a positive integer")
        if type(self.team_tricks) is not tuple or len(self.team_tricks) != 2:
            raise InvalidDealScoreError("deal-score team_tricks must be a pair")
        if any(type(value) is not int or value < 0 for value in self.team_tricks):
            raise InvalidDealScoreError(
                "deal-score trick totals must be nonnegative integers"
            )
        if sum(self.team_tricks) != 13:
            raise InvalidDealScoreError("deal-score trick totals must sum to 13")
        if type(self.stolen_rami) is not bool:
            raise InvalidDealScoreError("stolen_rami must be a boolean")

        if self.contract is Contract.NOLO:
            if self.declaring_team is not None or self.stolen_rami:
                raise InvalidDealScoreError(
                    "NOLO has no declaring team and cannot be stolen RAMI"
                )
            expected_winner = (
                Team.TEAM_0
                if self.team_tricks[0] < self.team_tricks[1]
                else Team.TEAM_1
            )
            expected_points = 4 * (7 - self.team_tricks[expected_winner.value])
        else:
            if not isinstance(self.declaring_team, Team):
                raise InvalidDealScoreError(
                    "RAMI deal score requires a declaring Team"
                )
            declaring_tricks = self.team_tricks[self.declaring_team.value]
            if declaring_tricks >= 7:
                expected_winner = self.declaring_team
                expected_points = 4 * (declaring_tricks - 6)
                if self.stolen_rami:
                    raise InvalidDealScoreError("made RAMI cannot be marked stolen")
            else:
                expected_winner = (
                    Team.TEAM_1
                    if self.declaring_team is Team.TEAM_0
                    else Team.TEAM_0
                )
                expected_points = 8 * (self.team_tricks[expected_winner.value] - 6)
                if not self.stolen_rami:
                    raise InvalidDealScoreError("failed RAMI must be marked stolen")

        if self.winner_team is not expected_winner or self.points != expected_points:
            raise InvalidDealScoreError(
                "deal-score winner or points disagree with the authoritative formula"
            )


@dataclass(frozen=True, slots=True)
class MatchScore:
    team0: int = 0
    team1: int = 0

    def __post_init__(self) -> None:
        for label, value in (("team0", self.team0), ("team1", self.team1)):
            if type(value) is not int:
                raise InvalidMatchScoreError(f"{label} score must be an integer")
            if value < 0:
                raise InvalidMatchScoreError(f"{label} score must be nonnegative")
        if self.team0 > 0 and self.team1 > 0:
            raise InvalidMatchScoreError(
                "at most one team may have a positive rising score"
            )

    @property
    def up_team(self) -> Team | None:
        if self.team0 > 0:
            return Team.TEAM_0
        if self.team1 > 0:
            return Team.TEAM_1
        return None

    def for_team(self, team: Team) -> int:
        if not isinstance(team, Team):
            raise InvalidTeamError("team must be a Team value")
        return self.team0 if team is Team.TEAM_0 else self.team1

    def as_tuple(self) -> tuple[int, int]:
        return (self.team0, self.team1)
