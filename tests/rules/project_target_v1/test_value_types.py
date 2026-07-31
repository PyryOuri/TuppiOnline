from __future__ import annotations

from dataclasses import FrozenInstanceError
import importlib

import pytest

from tuppi_rules import (
    FULL_DECK,
    Card,
    Contract,
    DealScore,
    InvalidDealScoreError,
    MatchScore,
    PlayedCard,
    Rank,
    ShowAction,
    ShowingResolution,
    Suit,
    Team,
    resolve_showing,
    score_nolo,
    transition_rising_score,
    validate_show_action,
)


def test_all_reference_value_objects_are_frozen() -> None:
    card = Card(Suit.HEARTS, Rank.THREE)
    played = PlayedCard(0, card)
    score = score_nolo(6, 7)
    match = MatchScore(4, 0)
    action = validate_show_action(
        seat=1,
        hand=FULL_DECK[:13],
        shown_card=card,
        declared_contract=Contract.RAMI,
    )
    resolution = resolve_showing(dealer=0, actions=(action,))

    for value, field, replacement in (
        (card, "rank", Rank.ACE),
        (played, "seat", 1),
        (score, "points", 8),
        (match, "team0", 8),
        (action, "verbal_required", True),
        (resolution, "declarer", 2),
    ):
        with pytest.raises(FrozenInstanceError):
            setattr(value, field, replacement)

    assert not hasattr(action, "hand")


def test_removed_unchecked_factories_cannot_be_used_to_forge_values() -> None:
    assert not hasattr(ShowAction, "_from_validated")
    assert not hasattr(DealScore, "_from_validated")


def test_match_transition_revalidates_a_maliciously_forged_deal_score() -> None:
    forged = object.__new__(DealScore)
    object.__setattr__(forged, "contract", Contract.NOLO)
    object.__setattr__(forged, "winner_team", 0)
    object.__setattr__(forged, "points", 4)
    object.__setattr__(forged, "team_tricks", (6, 7))
    object.__setattr__(forged, "declaring_team", None)
    object.__setattr__(forged, "stolen_rami", False)
    with pytest.raises(InvalidDealScoreError):
        transition_rising_score(MatchScore(), forged)


def test_rules_modules_expose_no_mutable_global_constants() -> None:
    for module_name in (
        "tuppi_rules",
        "tuppi_rules.cards",
        "tuppi_rules.match",
        "tuppi_rules.seating",
        "tuppi_rules.trick_play",
    ):
        module = importlib.import_module(module_name)
        for name, value in vars(module).items():
            if name.isupper() or name == "__all__":
                assert not isinstance(value, (list, dict, set, bytearray)), (
                    module_name,
                    name,
                )
