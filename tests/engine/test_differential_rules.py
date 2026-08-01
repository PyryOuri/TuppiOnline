from __future__ import annotations

from tuppi_engine import (
    PlayCardAction,
    ShowAction,
    apply_match_action,
    match_observation_for,
)
from tuppi_rules import (
    Contract,
    first_leader,
    legal_cards,
    resolve_showing,
    score_nolo,
    trick_winner,
    validate_completed_deal,
    validate_show_action,
)

from .conftest import apply_first_legal, resolve_all_nolo, run_first_legal, start_match_deal


def test_engine_show_acceptance_matches_pure_rules_value() -> None:
    state = start_match_deal(dealer=0)
    actor = state.current_actor
    action = next(
        item
        for item in match_observation_for(state, actor).legal_actions
        if isinstance(item, ShowAction) and item.declared_contract is Contract.NOLO
    )
    expected = validate_show_action(
        seat=action.seat,
        hand=state.active_deal.hands[action.seat],  # type: ignore[union-attr]
        shown_card=action.shown_card,
        declared_contract=action.declared_contract,
    )
    state = apply_match_action(state, action)
    assert state.active_deal.show_actions[-1] == expected  # type: ignore[union-attr]


def test_engine_contract_and_leader_match_pure_rules_resolution() -> None:
    state = resolve_all_nolo(start_match_deal(dealer=2))
    resolution = resolve_showing(
        dealer=2, actions=state.active_deal.show_actions  # type: ignore[union-attr]
    )
    assert state.active_deal.contract is resolution.contract  # type: ignore[union-attr]
    assert state.active_deal.declarer == resolution.declarer  # type: ignore[union-attr]
    assert state.active_deal.first_leader == first_leader(  # type: ignore[union-attr]
        contract=resolution.contract,
        dealer=2,
        declarer=resolution.declarer,
    )


def test_engine_legal_cards_and_winner_match_pure_rules() -> None:
    state = resolve_all_nolo(start_match_deal(dealer=0))
    for _ in range(4):
        actor = state.current_actor
        observation = match_observation_for(state, actor)
        led_suit = (
            state.active_deal.current_trick[0].card.suit  # type: ignore[union-attr]
            if state.active_deal.current_trick  # type: ignore[union-attr]
            else None
        )
        assert {action.card for action in observation.legal_actions} == set(
            legal_cards(state.active_deal.hands[actor], led_suit)  # type: ignore[index,union-attr]
        )
        state = apply_match_action(state, observation.legal_actions[0])
    trick = state.active_deal.completed_tricks[0]  # type: ignore[union-attr]
    assert trick.winner == trick_winner(trick.plays)


def test_completed_engine_transcript_and_score_match_reference_rules() -> None:
    state = run_first_legal(start_match_deal(dealer=0))
    deal = state.completed_deals[-1].public_result
    totals = validate_completed_deal(
        tuple(trick.plays for trick in deal.completed_tricks),
        expected_first_leader=deal.first_leader,
    )
    assert totals == deal.team_tricks
    assert deal.deal_score == score_nolo(*totals)
