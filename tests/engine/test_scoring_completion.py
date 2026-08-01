from __future__ import annotations

import pytest

from tuppi_engine import (
    DealOutcome,
    EnginePhase,
    ExplicitDeal,
    PlayCardAction,
    ShowAction,
    TerminalStateError,
    apply_match_action,
    begin_explicit_deal,
)
from tuppi_rules import (
    Contract,
    MatchScore,
    Team,
    card_from_code,
    score_nolo,
    score_rami_for_declarer,
)

from .conftest import (
    apply_first_legal,
    card,
    legal_action_for_contract,
    run_first_legal,
    start_match_deal,
    suit_block_hands,
)


BOUNDARY_HANDS = {
    "nolo_6_7": (
        ("QH", "5H", "3S", "AS", "8S", "4S", "KD", "4H", "2D", "6D", "7H", "8C", "AH"),
        ("8H", "6S", "KH", "KC", "9H", "10C", "JD", "7C", "3C", "9D", "JC", "5C", "AD"),
        ("6H", "AC", "10H", "9C", "QS", "2S", "3H", "QC", "JH", "10D", "8D", "JS", "7S"),
        ("9S", "4D", "5D", "5S", "10S", "2H", "4C", "3D", "2C", "7D", "KS", "6C", "QD"),
    ),
    "nolo_5_8": (
        ("2D", "4C", "5H", "8D", "5C", "2C", "AS", "JD", "QC", "QH", "8C", "8H", "KH"),
        ("6D", "9C", "JS", "KD", "7C", "3H", "7D", "7H", "4H", "10D", "7S", "10S", "6S"),
        ("4S", "3C", "5S", "9D", "9H", "JH", "AD", "QS", "2S", "AH", "3D", "JC", "5D"),
        ("8S", "2H", "9S", "6H", "KS", "3S", "6C", "AC", "QD", "10H", "10C", "KC", "4D"),
    ),
    "rami_7_6": (
        ("3C", "6S", "6H", "2S", "AC", "3S", "JD", "4C", "8C", "9H", "QS", "KD", "4D"),
        ("AS", "8S", "7D", "7S", "9C", "5H", "3D", "10H", "5C", "KH", "10C", "QH", "2D"),
        ("9S", "4S", "8D", "AD", "10D", "10S", "JC", "8H", "2C", "AH", "JS", "6D", "3H"),
        ("9D", "QD", "6C", "KC", "5S", "JH", "2H", "4H", "5D", "7C", "7H", "QC", "KS"),
    ),
    "rami_6_7_stolen": (
        ("7D", "6H", "6D", "4D", "AC", "7C", "JS", "QH", "10H", "5H", "10C", "2D", "KD"),
        ("10D", "7S", "JD", "9H", "8S", "3C", "3H", "5S", "5D", "2H", "2C", "9C", "QC"),
        ("KS", "QD", "9D", "3D", "4S", "AD", "4H", "7H", "JH", "8D", "10S", "8H", "6S"),
        ("2S", "3S", "6C", "9S", "KH", "AH", "KC", "8C", "AS", "5C", "QS", "JC", "4C"),
    ),
}


def _hands(name: str):
    return tuple(
        tuple(card_from_code(code) for code in hand) for hand in BOUNDARY_HANDS[name]
    )


def _run_boundary(name: str, *, rami: bool, score: MatchScore | None = None):
    state = start_match_deal(hands=_hands(name), dealer=0, score=score)
    if rami:
        state = apply_match_action(
            state, legal_action_for_contract(state, Contract.RAMI)
        )
    while state.phase in (EnginePhase.SHOWING, EnginePhase.TRICK_PLAY):
        state = apply_first_legal(state)
    return state


def _successful_rami_hands():
    return (
        tuple(card(f"H{rank}") for rank in ("2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"))
        + (card("D2"),),
        (card("HA"),)
        + tuple(card(f"D{rank}") for rank in ("3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A")),
        tuple(card(f"C{rank}") for rank in ("2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A")),
        tuple(card(f"S{rank}") for rank in ("2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A")),
    )


def _run_successful_rami_13(score: MatchScore | None = None):
    state = start_match_deal(hands=_successful_rami_hands(), dealer=0, score=score)
    state = apply_match_action(state, ShowAction(1, card("D3"), Contract.RAMI))
    actions = [
        PlayCardAction(0, card("H2")),
        PlayCardAction(1, card("HA")),
        PlayCardAction(2, card("C2")),
        PlayCardAction(3, card("S2")),
    ]
    ranks = ("3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A")
    for index, rank in enumerate(ranks):
        actions.extend(
            (
                PlayCardAction(1, card(f"D{rank}")),
                PlayCardAction(2, card(f"C{rank}")),
                PlayCardAction(3, card(f"S{rank}")),
                PlayCardAction(0, card("D2") if index == 0 else card(f"H{ranks[index - 1]}")),
            )
        )
    for action in actions:
        state = apply_match_action(state, action)
    return state


def _run_stolen_rami_0_13(score: MatchScore | None = None):
    state = start_match_deal(
        hands=suit_block_hands(), dealer=3, score=score
    )
    state = apply_match_action(state, ShowAction(0, card("H3"), Contract.RAMI))
    while state.phase is EnginePhase.TRICK_PLAY:
        state = apply_first_legal(state)
    return state


def test_nolo_6_7_and_0_13_integrate_exact_rules_scores() -> None:
    boundary = _run_boundary("nolo_6_7", rami=False).completed_deals[-1].public_result
    assert boundary.team_tricks == (6, 7)
    assert boundary.deal_score == score_nolo(6, 7)
    assert boundary.outcome is DealOutcome.NOLO
    assert boundary.deal_score.winner_team is Team.TEAM_0
    assert boundary.deal_score.points == 4

    extreme = run_first_legal(start_match_deal(dealer=0)).completed_deals[-1].public_result
    assert extreme.team_tricks == (0, 13)
    assert extreme.deal_score == score_nolo(0, 13)
    assert extreme.deal_score.points == 28


def test_successful_rami_7_6_and_13_0_integrate_exact_rules_scores() -> None:
    boundary = _run_boundary("rami_7_6", rami=True).completed_deals[-1].public_result
    assert boundary.team_tricks == (6, 7)
    assert boundary.declarer == 1
    assert boundary.deal_score == score_rami_for_declarer(1, 6, 7)
    assert boundary.outcome is DealOutcome.MADE_RAMI
    assert boundary.deal_score.points == 4

    extreme = _run_successful_rami_13().completed_deals[-1].public_result
    assert extreme.team_tricks == (0, 13)
    assert extreme.deal_score == score_rami_for_declarer(1, 0, 13)
    assert extreme.deal_score.points == 28


def test_stolen_rami_6_7_and_0_13_integrate_exact_rules_scores() -> None:
    boundary = _run_boundary(
        "rami_6_7_stolen", rami=True
    ).completed_deals[-1].public_result
    assert boundary.team_tricks == (7, 6)
    assert boundary.declarer == 1
    assert boundary.deal_score == score_rami_for_declarer(1, 7, 6)
    assert boundary.outcome is DealOutcome.STOLEN_RAMI
    assert boundary.deal_score.points == 8

    extreme = _run_stolen_rami_0_13().completed_deals[-1].public_result
    assert extreme.team_tricks == (0, 13)
    assert extreme.deal_score == score_rami_for_declarer(0, 0, 13)
    assert extreme.deal_score.points == 56


def test_score_gain_addition_and_down_team_reset() -> None:
    from_table = run_first_legal(start_match_deal(score=MatchScore()))
    assert from_table.score == MatchScore(28, 0)
    up_adds = run_first_legal(start_match_deal(score=MatchScore(20, 0)))
    assert up_adds.score == MatchScore(48, 0)
    down_resets = run_first_legal(start_match_deal(score=MatchScore(0, 20)))
    assert down_resets.score == MatchScore(0, 0)


def test_48_plus_4_and_48_plus_8_are_terminal() -> None:
    exact = _run_boundary("nolo_6_7", rami=False, score=MatchScore(48, 0))
    assert exact.score == MatchScore(52, 0)
    assert exact.terminal
    overshoot = _run_boundary("nolo_5_8", rami=False, score=MatchScore(48, 0))
    assert overshoot.score == MatchScore(56, 0)
    assert overshoot.terminal


def test_down_team_56_point_stolen_rami_resets_instead_of_winning() -> None:
    state = _run_stolen_rami_0_13(score=MatchScore(20, 0))
    result = state.completed_deals[-1].public_result
    assert result.deal_score.winner_team is Team.TEAM_1
    assert result.deal_score.points == 56
    assert state.score == MatchScore(0, 0)
    assert not state.terminal


def test_dealer_rotates_only_after_nonterminal_deal() -> None:
    nonterminal = run_first_legal(start_match_deal(dealer=0))
    assert nonterminal.dealer == 1
    assert nonterminal.completed_deals[-1].public_result.next_dealer == 1
    terminal = _run_stolen_rami_0_13()
    assert terminal.terminal
    assert terminal.dealer == 3
    assert terminal.completed_deals[-1].public_result.next_dealer is None


def test_no_additional_deal_or_action_after_match_completion() -> None:
    state = _run_stolen_rami_0_13()
    with pytest.raises(TerminalStateError):
        begin_explicit_deal(
            state, ExplicitDeal(dealer=0, hands=suit_block_hands())
        )
    with pytest.raises(TerminalStateError):
        apply_match_action(state, PlayCardAction(0, card("H2")))
