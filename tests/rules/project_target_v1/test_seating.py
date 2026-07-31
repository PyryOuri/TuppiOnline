from __future__ import annotations

import pytest

from tuppi_rules import (
    Contract,
    InvalidSeatError,
    InvalidShowingSequenceError,
    InvalidTeamError,
    Team,
    first_leader,
    forehand,
    opposing_team,
    partner_for_seat,
    rotate_dealer,
    team_for_seat,
    validate_team,
)


def test_partnerships_and_partner_lookup() -> None:
    assert [team_for_seat(seat) for seat in range(4)] == [
        Team.TEAM_0,
        Team.TEAM_1,
        Team.TEAM_0,
        Team.TEAM_1,
    ]
    assert [partner_for_seat(seat) for seat in range(4)] == [2, 3, 0, 1]
    assert opposing_team(Team.TEAM_0) is Team.TEAM_1
    assert opposing_team(Team.TEAM_1) is Team.TEAM_0


@pytest.mark.parametrize("dealer", range(4))
def test_forehand_and_dealer_rotation_for_every_seat(dealer: int) -> None:
    expected = (dealer + 1) % 4
    assert forehand(dealer) == expected
    assert rotate_dealer(dealer) == expected


@pytest.mark.parametrize("dealer", range(4))
def test_nolo_first_leader_is_forehand_for_every_dealer(dealer: int) -> None:
    assert first_leader(contract=Contract.NOLO, dealer=dealer, declarer=None) == (
        dealer + 1
    ) % 4


@pytest.mark.parametrize("dealer", range(4))
@pytest.mark.parametrize("declarer", range(4))
def test_rami_first_leader_for_every_dealer_and_declarer(
    dealer: int, declarer: int
) -> None:
    assert first_leader(
        contract=Contract.RAMI, dealer=dealer, declarer=declarer
    ) == (declarer - 1) % 4


@pytest.mark.parametrize("seat", [-1, 4, True, False, 1.0, "1", None])
def test_invalid_seats_are_rejected(seat) -> None:
    with pytest.raises(InvalidSeatError):
        team_for_seat(seat)


@pytest.mark.parametrize("team", [0, 1, True, "team_0", None])
def test_invalid_team_identifiers_are_rejected(team) -> None:
    with pytest.raises(InvalidTeamError):
        validate_team(team)


def test_contract_and_declarer_mismatches_are_rejected() -> None:
    with pytest.raises(InvalidShowingSequenceError, match="must not"):
        first_leader(contract=Contract.NOLO, dealer=0, declarer=1)
    with pytest.raises(InvalidShowingSequenceError, match="requires"):
        first_leader(contract=Contract.RAMI, dealer=0, declarer=None)
    with pytest.raises(InvalidShowingSequenceError, match="Contract"):
        first_leader(contract="NOLO", dealer=0, declarer=None)  # type: ignore[arg-type]
