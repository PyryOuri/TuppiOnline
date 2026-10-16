"""The sooli subgame of ``project_target_v2`` (docs/rules/project_target_v2.md).

After a RAMI declaration, one defender - the soolaaja - may play alone against
the RAMI pair. The soolaaja gives one card to their partner, the partner
returns one (not the same card), and the partner's hand is then out of play.
Three players remain. The declarer leads the first trick; in every trick the
leader plays first, the other RAMI player second and the soolaaja last; the
highest card of the led suit wins with the ace ranked lowest. The deal ends
as soon as the soolaaja wins a trick (RAMI pair +24); if the soolaaja wins no
trick in 13, the soolaaja's team scores 24. The points enter the ordinary
rising-score transition.

Everything here is pure and validating, in the style of the v1 modules.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from .cards import normalize_cards
from .errors import (
    IllegalPlayError,
    InvalidDealScoreError,
    InvalidMatchScoreError,
    InvalidShowingSequenceError,
    InvalidTrickError,
    TerminalMatchError,
)
from .match import is_match_terminal
from .model import Card, MatchScore, PlayedCard, Rank, Team
from .seating import partner_for_seat, team_for_seat, validate_seat
from .trick_play import validate_play

SOOLI_POINTS = 24
SOOLI_CARDS_PER_TRICK = 3
SOOLI_MAX_TRICKS = 13


def sooli_offer_order(declarer: int) -> tuple[int, int]:
    """The defenders in the order they are asked: after the declarer, then the other."""
    d = validate_seat(declarer)
    return ((d + 1) % 4, (d + 3) % 4)


def sooli_rank_value(card: Card) -> int:
    """Ace-low rank used in sooli trick play: A=1, 2=2, ..., K=13."""
    if not isinstance(card, Card):
        raise InvalidTrickError("sooli rank requires a Card")
    return 1 if card.rank is Rank.ACE else card.rank.value


def sooli_trick_seats(*, leader: int, declarer: int, soolaaja: int) -> tuple[int, int, int]:
    """Seats in play order for one sooli trick: leader, other RAMI player, soolaaja."""
    lead, dec, solo = validate_seat(leader), validate_seat(declarer), validate_seat(soolaaja)
    rami_pair = (dec, partner_for_seat(dec))
    if solo in rami_pair:
        raise InvalidShowingSequenceError("the soolaaja must be a defender")
    if lead not in rami_pair:
        raise InvalidTrickError("a sooli trick is always led by a RAMI player")
    other = rami_pair[1] if lead == rami_pair[0] else rami_pair[0]
    return (lead, other, solo)


def validate_sooli_trick(
    plays: Sequence[PlayedCard], *, leader: int, declarer: int, soolaaja: int, complete: bool = True
) -> tuple[PlayedCard, ...]:
    """Validate seat order and card distinctness of a (partial) sooli trick."""
    if isinstance(plays, (str, bytes)):
        raise InvalidTrickError("a sooli trick must be a sequence of PlayedCard values")
    normalized = tuple(plays)
    if any(not isinstance(play, PlayedCard) for play in normalized):
        raise InvalidTrickError("every sooli trick entry must be a PlayedCard")
    expected = sooli_trick_seats(leader=leader, declarer=declarer, soolaaja=soolaaja)
    if complete and len(normalized) != SOOLI_CARDS_PER_TRICK:
        raise InvalidTrickError("a completed sooli trick has exactly three cards")
    if len(normalized) > SOOLI_CARDS_PER_TRICK:
        raise InvalidTrickError("a sooli trick has at most three cards")
    if tuple(play.seat for play in normalized) != expected[: len(normalized)]:
        raise InvalidTrickError(f"sooli trick seats must be {expected}")
    cards = tuple(play.card for play in normalized)
    if len(set(cards)) != len(cards):
        raise InvalidTrickError("a card cannot be played twice in one trick")
    return normalized


def sooli_trick_winner(plays: Sequence[PlayedCard]) -> int:
    """Seat winning a completed sooli trick: highest ace-low card of the led suit."""
    normalized = tuple(plays)
    if len(normalized) != SOOLI_CARDS_PER_TRICK:
        raise InvalidTrickError("a completed sooli trick has exactly three cards")
    led = normalized[0].card.suit
    return max((p for p in normalized if p.card.suit is led), key=lambda p: sooli_rank_value(p.card)).seat


def validate_sooli_play(*, hand: Iterable[Card], card: Card, led_suit) -> Card:
    """Follow suit if able, exactly as in ``project_target_v1``."""
    return validate_play(hand=hand, card=card, led_suit=led_suit)


def validate_exchange(
    *, giver_hand: Iterable[Card], card: Card, received: Card | None = None
) -> Card:
    """One exchanged card: held by the giver; the partner may not return what it received."""
    cards = normalize_cards(giver_hand, context="exchange hand", allow_empty=False)
    if not isinstance(card, Card):
        raise IllegalPlayError("exchanged card must be a Card")
    if card not in cards:
        raise IllegalPlayError("exchanged card is not in the giver's hand")
    if received is not None and card == received:
        raise IllegalPlayError("the partner may not return the card it just received")
    return card


@dataclass(frozen=True, slots=True)
class SooliScore:
    """Validated result of a sooli deal."""

    declarer: int
    soolaaja: int
    soolaaja_won_trick: bool
    tricks_played: int
    winner_team: Team
    points: int

    def __post_init__(self) -> None:
        dec, solo = validate_seat(self.declarer), validate_seat(self.soolaaja)
        if team_for_seat(solo) is team_for_seat(dec):
            raise InvalidDealScoreError("the soolaaja must be a defender")
        if type(self.soolaaja_won_trick) is not bool:
            raise InvalidDealScoreError("soolaaja_won_trick must be a boolean")
        if type(self.tricks_played) is not int or not 1 <= self.tricks_played <= SOOLI_MAX_TRICKS:
            raise InvalidDealScoreError("a sooli deal plays 1 to 13 tricks")
        if not self.soolaaja_won_trick and self.tricks_played != SOOLI_MAX_TRICKS:
            raise InvalidDealScoreError("a successful sooli plays all 13 tricks")
        expected_winner = team_for_seat(dec) if self.soolaaja_won_trick else team_for_seat(solo)
        if self.winner_team is not expected_winner:
            raise InvalidDealScoreError("sooli winner disagrees with the outcome")
        if self.points != SOOLI_POINTS:
            raise InvalidDealScoreError("a sooli deal is worth exactly 24 points")


def score_sooli(*, declarer: int, soolaaja: int, soolaaja_won_trick: bool, tricks_played: int) -> SooliScore:
    winner = team_for_seat(declarer) if soolaaja_won_trick else team_for_seat(soolaaja)
    return SooliScore(declarer=declarer, soolaaja=soolaaja, soolaaja_won_trick=soolaaja_won_trick,
                      tricks_played=tricks_played, winner_team=winner, points=SOOLI_POINTS)


def transition_after_sooli(current: MatchScore, score: SooliScore) -> MatchScore:
    """The ordinary rising-score transition applied to a sooli result."""
    if not isinstance(current, MatchScore):
        raise InvalidMatchScoreError("score must be a MatchScore value")
    if not isinstance(score, SooliScore):
        raise InvalidDealScoreError("sooli transition requires a SooliScore")
    if is_match_terminal(current):
        raise TerminalMatchError("a terminal match cannot accept another deal score")
    up = current.up_team
    if up is None:
        return MatchScore(score.points, 0) if score.winner_team is Team.TEAM_0 else MatchScore(0, score.points)
    if score.winner_team is up:
        return (MatchScore(current.team0 + score.points, 0) if up is Team.TEAM_0
                else MatchScore(0, current.team1 + score.points))
    return MatchScore(0, 0)


__all__ = (
    "SOOLI_CARDS_PER_TRICK",
    "SOOLI_MAX_TRICKS",
    "SOOLI_POINTS",
    "SooliScore",
    "score_sooli",
    "sooli_offer_order",
    "sooli_rank_value",
    "sooli_trick_seats",
    "sooli_trick_winner",
    "transition_after_sooli",
    "validate_exchange",
    "validate_sooli_play",
    "validate_sooli_trick",
)
