"""The hard constraint model must be sound, complete, and never a belief model."""

from __future__ import annotations

import pytest

from tuppi_agents import PublicInference
from tuppi_engine import EnginePhase
from tuppi_exact.constraints import (
    ELIGIBLE_SHOW_CARDS,
    ELIGIBLE_SHOW_CARDS_BY_COLOR,
    HardConstraintModel,
    derive_show_exclusions,
    own_show_exclusion_is_consistent,
    show_exclusion_for,
)
from tuppi_exact.errors import ConstraintError
from tuppi_rules import (
    Color,
    Contract,
    card_from_code,
    is_show_rank_eligible,
    validate_show_action,
)

from .conftest import walk_deal


def test_eligible_show_card_sets_match_the_ruleset():
    assert len(ELIGIBLE_SHOW_CARDS) == 28
    assert all(is_show_rank_eligible(card.rank) for card in ELIGIBLE_SHOW_CARDS)
    assert len(ELIGIBLE_SHOW_CARDS_BY_COLOR[Color.RED]) == 14
    assert len(ELIGIBLE_SHOW_CARDS_BY_COLOR[Color.BLACK]) == 14
    assert (
        ELIGIBLE_SHOW_CARDS_BY_COLOR[Color.RED]
        | ELIGIBLE_SHOW_CARDS_BY_COLOR[Color.BLACK]
        == ELIGIBLE_SHOW_CARDS
    )


def _hand(*codes: str) -> tuple:
    cards = tuple(card_from_code(code) for code in codes)
    assert len(cards) == 13
    return cards


#: An eligible red card exists, so RAMI shows it directly at priority 1.
PRIORITY_ONE_HAND = _hand(
    "5H", "6H", "7H", "8H", "9H", "2D", "10D", "JD", "QD", "KD", "AD", "2C", "10C"
)
#: No eligible red card, but eligible black ones, so RAMI falls to priority 2.
PRIORITY_TWO_HAND = _hand(
    "2H", "10H", "JH", "QH", "KH", "AH", "2D", "10D", "JD", "5C", "6C", "7C", "8C"
)
#: No card of ranks 3-9 at all, so any declaration falls to priority 3.
PRIORITY_THREE_HAND = _hand(
    "2H", "10H", "JH", "QH", "KH", "AH", "2D", "10D", "JD", "QD", "KD", "AD", "2C"
)


def test_priority_one_show_excludes_nothing():
    action = validate_show_action(
        seat=1,
        hand=PRIORITY_ONE_HAND,
        shown_card=card_from_code("5H"),
        declared_contract=Contract.RAMI,
        claimed_verbal_required=None,
    )
    assert action.verbal_required is False
    assert show_exclusion_for(action) == frozenset()


def test_priority_two_show_excludes_the_whole_normal_colour():
    action = validate_show_action(
        seat=1,
        hand=PRIORITY_TWO_HAND,
        shown_card=card_from_code("5C"),
        declared_contract=Contract.RAMI,
        claimed_verbal_required=None,
    )
    assert action.verbal_required is True
    excluded = show_exclusion_for(action)
    assert excluded == ELIGIBLE_SHOW_CARDS_BY_COLOR[Color.RED]
    assert len(excluded) == 14
    assert card_from_code("5C") not in excluded
    assert not excluded & set(PRIORITY_TWO_HAND)


def test_priority_three_show_excludes_every_eligible_rank():
    action = validate_show_action(
        seat=2,
        hand=PRIORITY_THREE_HAND,
        shown_card=card_from_code("AH"),
        declared_contract=Contract.NOLO,
        claimed_verbal_required=None,
    )
    assert action.verbal_required is True
    assert not is_show_rank_eligible(action.shown_card.rank)
    assert show_exclusion_for(action) == ELIGIBLE_SHOW_CARDS
    assert len(show_exclusion_for(action)) == 28
    assert not show_exclusion_for(action) & set(PRIORITY_THREE_HAND)


def test_a_priority_three_show_can_never_show_an_eligible_card():
    """The rank of the shown card is what separates priority 2 from priority 3."""

    with pytest.raises(Exception):
        validate_show_action(
            seat=0,
            hand=PRIORITY_THREE_HAND,
            shown_card=card_from_code("5H"),
            declared_contract=Contract.NOLO,
            claimed_verbal_required=None,
        )


def test_show_exclusions_agree_with_the_rules_validator():
    """Whatever the exclusion claims absent must make the rules reject the show."""

    hand = tuple(
        card_from_code(code)
        for code in (
            "2C", "10C", "JC", "QC", "KC", "AC",
            "2S", "10S", "JS", "QS", "KS", "AS", "5H",
        )
    )
    action = validate_show_action(
        seat=0,
        hand=hand,
        shown_card=card_from_code("5H"),
        declared_contract=Contract.NOLO,
        claimed_verbal_required=True,
    )
    assert action.verbal_required is True
    excluded = show_exclusion_for(action)
    assert excluded == ELIGIBLE_SHOW_CARDS_BY_COLOR[Color.BLACK]
    assert not excluded & set(hand)


def test_model_is_sound_against_the_true_hands():
    """No hard constraint may ever exclude the truth, at any decision."""

    checked = 0
    for stream_index in range(6):
        for position in walk_deal(stream_index=stream_index):
            truth = {
                card: seat
                for seat, hand in enumerate(position.true_hands)
                for card in hand
            }
            model = HardConstraintModel.build(position.observation)
            for card in model.unknown_cards:
                assert truth[card] in model.allowed_seats(card)
            for seat in range(4):
                for card in model.known_held[seat]:
                    assert truth[card] == seat
                assert not model.show_exclusions[seat] & set(
                    position.true_hands[seat]
                )
            assert own_show_exclusion_is_consistent(position.observation)
            checked += 1
    assert checked > 200


def test_show_exclusions_actually_fire_somewhere():
    """A constraint nobody ever hits would be untested rather than sound."""

    fired = 0
    for stream_index in range(40):
        for position in walk_deal(stream_index=stream_index):
            exclusions = derive_show_exclusions(position.observation)
            fired += sum(1 for item in exclusions if item)
    assert fired > 0


def test_model_arithmetic_is_internally_consistent(deal_positions):
    for position in deal_positions:
        model = HardConstraintModel.build(position.observation)
        assert sum(model.capacity) == len(model.unknown_cards)
        assert model.capacity[model.observing_seat] == 0
        for seat in range(4):
            assert (
                len(model.known_held[seat]) + model.capacity[seat]
                == model.cards_remaining[seat]
            )
        for card in model.unknown_cards:
            seats = model.allowed_seats(card)
            assert seats
            assert all(model.capacity[seat] > 0 for seat in seats)
        assert model.is_structurally_feasible()
        assert not model.hall_deficiency()


def test_equivalence_classes_partition_the_unknown_cards(deal_positions):
    for position in deal_positions:
        model = HardConstraintModel.build(position.observation)
        collected = [
            card for _, cards in model.equivalence_classes() for card in cards
        ]
        assert sorted(collected, key=str) == sorted(model.unknown_cards, key=str)
        for seats, cards in model.equivalence_classes():
            for card in cards:
                assert model.allowed_seats(card) == seats


def test_model_is_at_least_as_strong_as_phase4_inference(deal_positions):
    """Adding show exclusions may only narrow, never widen, an allowed-seat set."""

    for position in deal_positions:
        inference = PublicInference.build(position.observation)
        model = HardConstraintModel.build(position.observation)
        for card in model.unknown_cards:
            assert model.allowed_seats(card) <= inference.possible_owners(card)
        for seat in range(4):
            assert inference.known_held[seat] <= model.known_held[seat]


def test_the_model_carries_no_probabilistic_attribute():
    forbidden = ("probability", "likelihood", "prior", "belief", "weight")
    for name in HardConstraintModel.__slots__:
        assert not any(token in name for token in forbidden)


def test_show_exclusion_rejects_a_non_show_action():
    with pytest.raises(ConstraintError):
        show_exclusion_for("not an action")  # type: ignore[arg-type]


def test_derive_show_exclusions_requires_an_observation():
    with pytest.raises(ConstraintError):
        derive_show_exclusions(object())  # type: ignore[arg-type]


def test_observing_seat_never_receives_an_exclusion(deal_positions):
    for position in deal_positions:
        exclusions = derive_show_exclusions(position.observation)
        assert exclusions[position.observation.observing_seat] == frozenset()


def test_a_terminal_showing_position_still_builds(deal_positions):
    showing = [
        item
        for item in deal_positions
        if item.deal_state.phase is EnginePhase.SHOWING
    ]
    assert showing
    for position in showing:
        model = HardConstraintModel.build(position.observation)
        assert len(model.unknown_cards) == 39
        assert model.capacity.count(13) == 3
