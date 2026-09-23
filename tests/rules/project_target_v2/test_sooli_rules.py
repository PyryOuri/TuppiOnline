"""Normative tests for the sooli subgame of project_target_v2."""

from __future__ import annotations

import pytest

from tuppi_rules import Card, MatchScore, PlayedCard, Rank, Suit, Team, RulesError
from tuppi_rules.sooli import (
    SOOLI_POINTS,
    SooliScore,
    score_sooli,
    sooli_offer_order,
    sooli_rank_value,
    sooli_trick_seats,
    sooli_trick_winner,
    transition_after_sooli,
    validate_exchange,
    validate_sooli_trick,
)

H, D, C, S = Suit.HEARTS, Suit.DIAMONDS, Suit.CLUBS, Suit.SPADES


def card(suit, rank):
    return Card(suit, Rank(rank))


@pytest.mark.parametrize("declarer, order", [(0, (1, 3)), (1, (2, 0)), (2, (3, 1)), (3, (0, 2))])
def test_offer_order_is_defender_after_declarer_then_other(declarer, order):
    assert sooli_offer_order(declarer) == order


def test_ace_is_lowest_in_sooli():
    values = [sooli_rank_value(card(H, r)) for r in range(2, 15)]
    assert sooli_rank_value(card(H, 14)) == 1
    assert min(values) == 1 and max(values) == 13
    assert sooli_rank_value(card(H, 13)) == 13 and sooli_rank_value(card(H, 2)) == 2


@pytest.mark.parametrize("declarer", range(4))
def test_trick_order_is_leader_other_rami_then_soolaaja(declarer):
    partner = (declarer + 2) % 4
    for soolaaja in ((declarer + 1) % 4, (declarer + 3) % 4):
        assert sooli_trick_seats(leader=declarer, declarer=declarer, soolaaja=soolaaja) == (declarer, partner, soolaaja)
        assert sooli_trick_seats(leader=partner, declarer=declarer, soolaaja=soolaaja) == (partner, declarer, soolaaja)
    with pytest.raises(RulesError):
        sooli_trick_seats(leader=(declarer + 1) % 4, declarer=declarer, soolaaja=(declarer + 3) % 4)
    with pytest.raises(RulesError):
        sooli_trick_seats(leader=declarer, declarer=declarer, soolaaja=partner)


def test_trick_winner_ace_low_and_off_suit_never_wins():
    # Declarer 0 leads 5H, partner 2 plays AH (lowest), soolaaja 1 plays KH: soolaaja wins.
    t = (PlayedCard(0, card(H, 5)), PlayedCard(2, card(H, 14)), PlayedCard(1, card(H, 13)))
    assert sooli_trick_winner(t) == 1
    # Soolaaja ducks with AH under 5H.
    t = (PlayedCard(0, card(H, 5)), PlayedCard(2, card(H, 3)), PlayedCard(1, card(H, 14)))
    assert sooli_trick_winner(t) == 0
    # Soolaaja void discards the KS: cannot win.
    t = (PlayedCard(0, card(H, 2)), PlayedCard(2, card(H, 3)), PlayedCard(1, card(S, 13)))
    assert sooli_trick_winner(t) == 2


def test_trick_validation():
    ok = (PlayedCard(0, card(H, 5)), PlayedCard(2, card(H, 3)), PlayedCard(1, card(H, 14)))
    assert validate_sooli_trick(ok, leader=0, declarer=0, soolaaja=1) == ok
    assert validate_sooli_trick(ok[:2], leader=0, declarer=0, soolaaja=1, complete=False) == ok[:2]
    with pytest.raises(RulesError):  # wrong order: soolaaja before the other RAMI player
        validate_sooli_trick((ok[0], ok[2], ok[1]), leader=0, declarer=0, soolaaja=1)
    with pytest.raises(RulesError):
        validate_sooli_trick(ok[:2], leader=0, declarer=0, soolaaja=1)


def test_exchange_validation():
    hand = [card(H, 5), card(S, 13)]
    assert validate_exchange(giver_hand=hand, card=card(S, 13)) == card(S, 13)
    with pytest.raises(RulesError):
        validate_exchange(giver_hand=hand, card=card(D, 4))
    with pytest.raises(RulesError):  # the partner may not return the received card
        validate_exchange(giver_hand=hand + [card(C, 9)], card=card(C, 9), received=card(C, 9))


def test_scoring():
    fail = score_sooli(declarer=0, soolaaja=1, soolaaja_won_trick=True, tricks_played=4)
    assert fail.winner_team is Team.TEAM_0 and fail.points == SOOLI_POINTS == 24
    win = score_sooli(declarer=0, soolaaja=3, soolaaja_won_trick=False, tricks_played=13)
    assert win.winner_team is Team.TEAM_1 and win.points == 24
    with pytest.raises(RulesError):  # success needs all 13 tricks
        score_sooli(declarer=0, soolaaja=1, soolaaja_won_trick=False, tricks_played=12)
    with pytest.raises(RulesError):  # soolaaja must be a defender
        score_sooli(declarer=0, soolaaja=2, soolaaja_won_trick=True, tricks_played=1)
    with pytest.raises(RulesError):
        SooliScore(declarer=0, soolaaja=1, soolaaja_won_trick=True, tricks_played=1, winner_team=Team.TEAM_1, points=24)


def test_match_transition_is_ordinary_rising_score():
    win1 = score_sooli(declarer=0, soolaaja=1, soolaaja_won_trick=False, tricks_played=13)  # team 1 wins
    win0 = score_sooli(declarer=0, soolaaja=1, soolaaja_won_trick=True, tricks_played=2)  # team 0 wins
    assert transition_after_sooli(MatchScore(0, 0), win1) == MatchScore(0, 24)
    assert transition_after_sooli(MatchScore(0, 8), win1) == MatchScore(0, 32)
    assert transition_after_sooli(MatchScore(0, 40), win0) == MatchScore(0, 0)  # down team resets
    assert transition_after_sooli(MatchScore(28, 0), win0) == MatchScore(52, 0)
    with pytest.raises(RulesError):
        transition_after_sooli(MatchScore(52, 0), win0)
