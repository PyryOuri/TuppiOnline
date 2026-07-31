from __future__ import annotations

import pytest

from tuppi_rules import (
    FULL_DECK,
    Card,
    Contract,
    IncompleteShowingError,
    InvalidShowingSequenceError,
    Rank,
    Suit,
    first_leader,
    forehand,
    rami_declarer,
    resolve_showing,
    validate_show_action,
    is_show_rank_eligible,
)


def make_action(seat: int, contract: Contract):
    suit = Suit.HEARTS if contract is Contract.RAMI else Suit.CLUBS
    card = Card(suit, Rank.THREE)
    fillers = tuple(
        candidate
        for candidate in FULL_DECK
        if not is_show_rank_eligible(candidate) and candidate != card
    )
    hand = (card, *fillers[:12])
    return validate_show_action(
        seat=seat, hand=hand, shown_card=card, declared_contract=contract
    )


@pytest.mark.parametrize("dealer", range(4))
@pytest.mark.parametrize("rami_position", range(4))
def test_first_rami_at_every_possible_position_terminates_showing(
    dealer: int, rami_position: int
) -> None:
    order = tuple((forehand(dealer) + offset) % 4 for offset in range(4))
    actions = tuple(
        make_action(
            seat,
            Contract.RAMI if index == rami_position else Contract.NOLO,
        )
        for index, seat in enumerate(order[: rami_position + 1])
    )
    result = resolve_showing(dealer=dealer, actions=actions)
    assert result.contract is Contract.RAMI
    assert result.declarer == order[rami_position]
    assert result.actions == actions
    assert rami_declarer(dealer=dealer, actions=actions) == result.declarer
    assert first_leader(
        contract=result.contract, dealer=dealer, declarer=result.declarer
    ) == (result.declarer - 1) % 4


@pytest.mark.parametrize("dealer", range(4))
def test_four_ordered_nolo_actions_resolve_without_declarer(dealer: int) -> None:
    order = tuple((forehand(dealer) + offset) % 4 for offset in range(4))
    actions = tuple(make_action(seat, Contract.NOLO) for seat in order)
    result = resolve_showing(dealer=dealer, actions=actions)
    assert result.contract is Contract.NOLO
    assert result.declarer is None
    assert rami_declarer(dealer=dealer, actions=actions) is None


@pytest.mark.parametrize("length", range(4))
def test_incomplete_all_nolo_sequence_is_not_resolved(length: int) -> None:
    order = (1, 2, 3, 0)
    actions = tuple(make_action(seat, Contract.NOLO) for seat in order[:length])
    with pytest.raises(IncompleteShowingError, match="unresolved"):
        resolve_showing(dealer=0, actions=actions)


def test_actions_after_first_rami_are_rejected() -> None:
    actions = (
        make_action(1, Contract.RAMI),
        make_action(2, Contract.NOLO),
    )
    with pytest.raises(InvalidShowingSequenceError, match="after"):
        resolve_showing(dealer=0, actions=actions)


def test_invalid_order_skips_duplicates_and_excess_actions_are_rejected() -> None:
    with pytest.raises(InvalidShowingSequenceError, match="clockwise"):
        resolve_showing(dealer=0, actions=(make_action(2, Contract.RAMI),))
    with pytest.raises(InvalidShowingSequenceError, match="more than once"):
        resolve_showing(
            dealer=0,
            actions=(make_action(1, Contract.NOLO), make_action(1, Contract.RAMI)),
        )
    with pytest.raises(InvalidShowingSequenceError, match="clockwise"):
        resolve_showing(
            dealer=0,
            actions=(make_action(1, Contract.NOLO), make_action(3, Contract.RAMI)),
        )
    five = tuple(make_action(index % 4, Contract.NOLO) for index in range(5))
    with pytest.raises(InvalidShowingSequenceError, match="more than four"):
        resolve_showing(dealer=3, actions=five)


def test_nonsequence_and_nonaction_inputs_raise_typed_errors() -> None:
    with pytest.raises(InvalidShowingSequenceError):
        resolve_showing(dealer=0, actions=None)  # type: ignore[arg-type]
    with pytest.raises(InvalidShowingSequenceError, match="ShowAction"):
        resolve_showing(dealer=0, actions=(object(),))  # type: ignore[arg-type]


@pytest.mark.parametrize("rami_seat", [0, 1])
def test_rami_declarer_composes_to_the_correct_declaring_partnership(
    rami_seat: int,
) -> None:
    from tuppi_rules import Team, score_rami_for_declarer, team_for_seat

    dealer = (rami_seat - 1) % 4
    action = make_action(rami_seat, Contract.RAMI)
    resolution = resolve_showing(dealer=dealer, actions=(action,))
    totals = (7, 6) if team_for_seat(rami_seat) is Team.TEAM_0 else (6, 7)
    score = score_rami_for_declarer(resolution.declarer, *totals)
    assert score.declaring_team is team_for_seat(rami_seat)
    assert score.winner_team is Team(rami_seat % 2)
