from __future__ import annotations

from collections.abc import Iterable

import pytest
from hypothesis import HealthCheck, settings

from tuppi_engine import (
    Action,
    EnginePhase,
    ExplicitDeal,
    MatchState,
    ShowAction,
    apply_match_action,
    begin_explicit_deal,
    create_match,
    match_observation_for,
)
from tuppi_rules import FULL_DECK, Card, Contract, MatchScore, card_from_code


settings.register_profile(
    "engine_deterministic",
    max_examples=40,
    derandomize=True,
    database=None,
    deadline=None,
    suppress_health_check=(HealthCheck.too_slow,),
)
settings.load_profile("engine_deterministic")


def card(code: str) -> Card:
    # Test builders use compact suit-first literals for visual grouping. The
    # external JSON boundary is tested separately and accepts only canonical
    # rank-first codes.
    if code and code[0] in "HDCS":
        code = f"{code[1:]}{code[0]}"
    return card_from_code(code)


def suit_block_hands() -> tuple[tuple[Card, ...], ...]:
    return tuple(
        tuple(FULL_DECK[seat * 13 : (seat + 1) * 13]) for seat in range(4)
    )


def round_robin_hands() -> tuple[tuple[Card, ...], ...]:
    return tuple(tuple(FULL_DECK[seat::4]) for seat in range(4))


def no_eligible_forehand_hands() -> tuple[tuple[Card, ...], ...]:
    return (
        tuple(card(f"H{rank}") for rank in ("3", "4", "5", "6", "7", "8", "9"))
        + tuple(card(f"D{rank}") for rank in ("3", "4", "5", "6", "7", "8")),
        tuple(
            card(code)
            for code in (
                "H2",
                "H10",
                "HJ",
                "HQ",
                "HK",
                "HA",
                "D2",
                "D10",
                "DJ",
                "DQ",
                "DK",
                "DA",
                "C2",
            )
        ),
        (card("D9"),)
        + tuple(card(f"C{rank}") for rank in ("3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A")),
        tuple(card(f"S{rank}") for rank in ("2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A")),
    )


def start_match_deal(
    *,
    hands: Iterable[Iterable[Card]] | None = None,
    dealer: int = 0,
    score: MatchScore | None = None,
    match_ref: str = "test-match",
) -> MatchState:
    explicit = ExplicitDeal(
        dealer=dealer,
        hands=suit_block_hands() if hands is None else hands,
    )
    match = create_match(
        initial_score=MatchScore() if score is None else score,
        initial_dealer=dealer,
        match_ref=match_ref,
    )
    return begin_explicit_deal(match, explicit)


def legal_action_for_contract(state: MatchState, contract: Contract) -> ShowAction:
    actor = state.current_actor
    assert actor is not None
    observation = match_observation_for(state, actor)
    return next(
        action
        for action in observation.legal_actions
        if isinstance(action, ShowAction) and action.declared_contract is contract
    )


def resolve_all_nolo(state: MatchState) -> MatchState:
    current = state
    while current.phase is EnginePhase.SHOWING:
        current = apply_match_action(
            current, legal_action_for_contract(current, Contract.NOLO)
        )
    return current


def apply_first_legal(state: MatchState) -> MatchState:
    actor = state.current_actor
    assert actor is not None
    observation = match_observation_for(state, actor)
    assert observation.legal_actions
    return apply_match_action(state, observation.legal_actions[0])


def run_first_legal(state: MatchState) -> MatchState:
    current = state
    while current.phase in (EnginePhase.SHOWING, EnginePhase.TRICK_PLAY):
        current = apply_first_legal(current)
    return current


@pytest.fixture
def suit_hands() -> tuple[tuple[Card, ...], ...]:
    return suit_block_hands()
