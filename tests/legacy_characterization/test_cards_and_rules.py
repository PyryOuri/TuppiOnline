from __future__ import annotations

import contextlib
import io

import pytest


def test_all_52_encoded_cards_are_unique_and_invertible(legacy) -> None:
    cards = [
        legacy.make_card(rank, suit)
        for suit in range(4)
        for rank in range(2, 15)
    ]
    assert cards == list(range(52))
    for suit in range(4):
        for rank in range(2, 15):
            card = legacy.make_card(rank, suit)
            assert legacy.card_rank(card) == rank
            assert legacy.card_suit(card) == suit


def test_supported_card_formatting_and_parsing_round_trip(legacy) -> None:
    for card in range(52):
        assert legacy.parse_card(legacy.short_card_str(card)) == card
        assert legacy.parse_card(legacy.card_str(card)) == card
    assert legacy.parse_card("  qd ") == legacy.make_card(12, 2)
    assert legacy.parse_card("not-a-card") is None


def test_following_suit_preserves_legacy_input_order(legacy) -> None:
    hand = [
        legacy.make_card(4, 1),
        legacy.make_card(14, 0),
        legacy.make_card(2, 1),
        legacy.make_card(9, 3),
    ]
    assert legacy.legal_moves(hand, 1) == [hand[0], hand[2]]
    assert legacy.legal_moves(hand, 2) == hand
    assert legacy.legal_moves(hand, None) == hand


def test_trick_winner_uses_only_highest_card_of_led_suit(legacy) -> None:
    led_two = [
        (3, legacy.make_card(2, 0)),
        (0, legacy.make_card(14, 1)),
        (1, legacy.make_card(13, 0)),
        (2, legacy.make_card(14, 2)),
    ]
    assert legacy.trick_winner(led_two) == 1

    ace_last = [
        (1, legacy.make_card(9, 3)),
        (2, legacy.make_card(10, 3)),
        (3, legacy.make_card(13, 3)),
        (0, legacy.make_card(14, 3)),
    ]
    assert legacy.trick_winner(ace_last) == 0


@pytest.mark.parametrize(
    ("declarer", "team0_tricks", "team1_tricks", "expected"),
    [
        (0, 7, 6, (0, 4)),
        (0, 13, 0, (0, 28)),
        (0, 6, 7, (1, 8)),
        (0, 0, 13, (1, 56)),
        (1, 6, 7, (1, 4)),
        (1, 7, 6, (0, 8)),
    ],
)
def test_legacy_rami_scoring_endpoints(
    legacy, declarer, team0_tricks, team1_tricks, expected
) -> None:
    assert (
        legacy.score_deal(
            legacy.Contract.RAMI, declarer, team0_tricks, team1_tricks
        )
        == expected
    )


@pytest.mark.parametrize(
    ("team0_tricks", "team1_tricks", "expected"),
    [
        (0, 13, (0, 28)),
        (6, 7, (0, 4)),
        (7, 6, (1, 4)),
        (13, 0, (1, 28)),
    ],
)
def test_legacy_nolo_scoring_endpoints(
    legacy, team0_tricks, team1_tricks, expected
) -> None:
    assert legacy.score_deal(legacy.Contract.NOLO, None, team0_tricks, team1_tricks) == expected


def test_partnership_indexing(legacy) -> None:
    assert [legacy.team_of(seat) for seat in range(4)] == [0, 1, 0, 1]


class _ScriptedPlayer:
    def __init__(self, legacy, seat: int, rami_seat: int | None, first_states: dict):
        self.legacy = legacy
        self.seat = seat
        self.rami_seat = rami_seat
        self.first_states = first_states
        self.hand = []

    def set_hand(self, cards):
        self.hand = self.legacy.sort_hand(list(cards))

    def choose_show_bid(self, dealer, score_state, show_banned_ranks):
        choice = (
            self.legacy.Contract.RAMI
            if self.seat == self.rami_seat
            else self.legacy.Contract.NOLO
        )
        # Legacy accepts verbal bids without engine-level eligibility checks.
        return self.legacy.ShowBid(choice=choice, card=None, verbal=True)

    def choose_play_card(self, pub, show_banned_ranks):
        self.first_states.setdefault(self.seat, pub)
        return self.legacy.legal_moves(self.hand, pub.lead_suit())[0]


@pytest.mark.parametrize(
    ("dealer", "rami_seat", "expected_contract", "expected_declarer", "expected_leader"),
    [
        (2, None, "NOLO", None, 3),
        (0, 3, "RAMI", 3, 2),
    ],
)
def test_legacy_dealer_and_first_leader_observed_in_public_state(
    legacy, dealer, rami_seat, expected_contract, expected_declarer, expected_leader
) -> None:
    original_random_state = legacy.random.getstate()
    try:
        first_states = {}
        game = legacy.TuppiGame(seed=101, rollouts=0, analysis_level="none")
        game.dealer = dealer
        game.players = [
            _ScriptedPlayer(legacy, seat, rami_seat, first_states)
            for seat in range(4)
        ]
        with contextlib.redirect_stdout(io.StringIO()):
            game.play_one_hand()
        first = min(first_states.values(), key=lambda state: len(state.played_cards))
        assert first.dealer == dealer
        assert first.contract == expected_contract
        assert first.declarer == expected_declarer
        assert first.leader == expected_leader
    finally:
        legacy.random.setstate(original_random_state)


def test_infer_turn_seat_uses_leader_then_clockwise_order(legacy) -> None:
    score = legacy.ScoreState()
    empty = legacy.PublicState(
        legacy.Contract.NOLO,
        None,
        0,
        3,
        0,
        [],
        [],
        (0, 0),
        (0, 0, 0, 0),
        {},
        score,
    )
    assert legacy.infer_turn_seat(empty) == 3
    empty.current_trick = [(3, 0), (0, 1)]
    assert legacy.infer_turn_seat(empty) == 1
