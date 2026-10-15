"""Seat, partnership, dealer, and leader relations."""

from __future__ import annotations

from .errors import InvalidSeatError, InvalidShowingSequenceError, InvalidTeamError
from .model import Contract, Team


PLAYER_COUNT = 4


def validate_seat(seat: object) -> int:
    if type(seat) is not int or seat not in range(PLAYER_COUNT):
        raise InvalidSeatError("seat must be an integer in 0..3")
    return seat


def validate_team(team: object) -> Team:
    if not isinstance(team, Team):
        raise InvalidTeamError("team must be a Team value")
    return team


def team_for_seat(seat: int) -> Team:
    validated = validate_seat(seat)
    return Team.TEAM_0 if validated % 2 == 0 else Team.TEAM_1


def partner_for_seat(seat: int) -> int:
    return (validate_seat(seat) + 2) % PLAYER_COUNT


def opposing_team(team: Team) -> Team:
    validated = validate_team(team)
    return Team.TEAM_1 if validated is Team.TEAM_0 else Team.TEAM_0


def forehand(dealer: int) -> int:
    return (validate_seat(dealer) + 1) % PLAYER_COUNT


def rotate_dealer(dealer: int) -> int:
    return (validate_seat(dealer) + 1) % PLAYER_COUNT


def first_leader(
    *, contract: Contract, dealer: int, declarer: int | None
) -> int:
    validated_dealer = validate_seat(dealer)
    if not isinstance(contract, Contract):
        raise InvalidShowingSequenceError("contract must be a Contract value")
    if contract is Contract.NOLO:
        if declarer is not None:
            raise InvalidShowingSequenceError("NOLO must not have a declarer")
        return forehand(validated_dealer)
    if declarer is None:
        raise InvalidShowingSequenceError("RAMI requires a declarer")
    return (validate_seat(declarer) - 1) % PLAYER_COUNT
