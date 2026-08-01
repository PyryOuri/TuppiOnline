from __future__ import annotations

from dataclasses import replace

import pytest
from hypothesis import given, settings, strategies as st

from tuppi_engine import PlayCardAction, ShowAction
from tuppi_eval.deals import (
    DealerPolicy,
    DealBank,
    deal_bank_from_data,
    deal_bank_to_data,
    generate_base_deal,
    generate_deal_bank,
    load_deal_bank,
    save_deal_bank,
)
from tuppi_eval.errors import DealBankError
from tuppi_eval.serialization import content_digest
from tuppi_eval.transformations import (
    Transformation,
    compose_transformations,
    diagnostic_suit_permutation,
    identity_transformation,
    rotation_transformation,
    transform_action,
    transform_deal,
)
from tuppi_rules import FULL_DECK, SUIT_ORDER, Contract, MatchScore, card_to_code


@given(st.integers(), st.integers(min_value=0, max_value=500))
@settings(max_examples=30)
def test_counter_derived_deal_is_stable_and_complete(seed: int, index: int) -> None:
    kwargs = {
        "root_seed": seed,
        "index": index,
        "dealer_policy": DealerPolicy.DIGEST_DERIVED,
        "initial_dealer": 2,
        "starting_score": MatchScore(),
    }
    first = generate_base_deal(**kwargs)
    second = generate_base_deal(**kwargs)
    assert first == second
    cards = tuple(card for hand in first.hands for card in hand)
    assert len(cards) == 52
    assert frozenset(cards) == frozenset(FULL_DECK)


def test_generation_order_and_metadata_do_not_change_deal_identity() -> None:
    generated_reverse = {
        index: generate_base_deal(
            root_seed=1729,
            index=index,
            dealer_policy=DealerPolicy.ROUND_ROBIN,
            initial_dealer=3,
            starting_score=MatchScore(17, 0),
        )
        for index in reversed(range(12))
    }
    generated_forward = {
        index: generate_base_deal(
            root_seed=1729,
            index=index,
            dealer_policy=DealerPolicy.ROUND_ROBIN,
            initial_dealer=3,
            starting_score=MatchScore(17, 0),
        )
        for index in range(12)
    }
    assert generated_reverse == generated_forward
    assert [generated_forward[index].dealer for index in range(8)] == [
        3,
        0,
        1,
        2,
        3,
        0,
        1,
        2,
    ]

    first = generate_deal_bank(
        count=2,
        root_seed=12,
        dealer_policy=DealerPolicy.ROUND_ROBIN,
        initial_dealer=0,
        starting_score=MatchScore(),
        creation_metadata={"path": "/tmp/a"},
    )
    second = DealBank.build(
        root_seed=first.root_seed,
        dealer_policy=first.dealer_policy,
        initial_dealer=first.initial_dealer,
        base_deals=first.base_deals,
        creation_metadata={"path": "/different/output"},
    )
    assert first.deal_bank_id == second.deal_bank_id


def test_deal_bank_round_trip_mismatch_and_duplicate_detection(tmp_path) -> None:
    bank = generate_deal_bank(
        count=2,
        root_seed="bank-test",
        dealer_policy=DealerPolicy.ROUND_ROBIN,
        initial_dealer=1,
        starting_score=MatchScore(),
        creation_metadata={"created_for": "test"},
    )
    path = tmp_path / "bank.json"
    save_deal_bank(path, bank)
    assert load_deal_bank(path) == bank
    with pytest.raises(DealBankError, match="ruleset mismatch"):
        load_deal_bank(path, expected_ruleset_id="another_ruleset")

    with pytest.raises(DealBankError, match="duplicate"):
        DealBank.build(
            root_seed=bank.root_seed,
            dealer_policy=bank.dealer_policy,
            initial_dealer=bank.initial_dealer,
            base_deals=(bank.base_deals[0], replace(bank.base_deals[0], index=1)),
            creation_metadata={},
        )

    same_cards_new_dealer = type(bank.base_deals[0]).build(
        index=1,
        dealer=2,
        hands=bank.base_deals[0].hands,
        starting_score=bank.base_deals[0].starting_score,
    )
    with pytest.raises(DealBankError, match="duplicate card material"):
        DealBank.build(
            root_seed=bank.root_seed,
            dealer_policy=bank.dealer_policy,
            initial_dealer=1,
            base_deals=(bank.base_deals[0], same_cards_new_dealer),
            creation_metadata={},
        )

    unknown = deal_bank_to_data(bank)
    unknown["output_path"] = "ignored"
    with pytest.raises(Exception, match="unknown"):
        deal_bank_from_data(unknown)


@given(st.integers(min_value=0, max_value=3), st.integers(min_value=0, max_value=3))
def test_rotation_composition_and_inverse(first_rotation: int, second_rotation: int) -> None:
    first = rotation_transformation(first_rotation)
    second = rotation_transformation(second_rotation)
    composed = compose_transformations(first, second, label="property-composition")
    for seat in range(4):
        assert composed.map_seat(seat) == second.map_seat(first.map_seat(seat))
        assert composed.inverse().map_seat(composed.map_seat(seat)) == seat
    for card in FULL_DECK:
        assert composed.inverse().map_card(composed.map_card(card)) == card


@given(st.integers(), st.integers(min_value=0, max_value=3))
@settings(max_examples=20)
def test_transformation_conserves_cards_and_restores_deal(
    seed: int, rotation: int
) -> None:
    base = generate_base_deal(
        root_seed=seed,
        index=0,
        dealer_policy=DealerPolicy.ROUND_ROBIN,
        initial_dealer=1,
        starting_score=MatchScore(9, 0),
    )
    transformation = Transformation.build(
        seat_rotation=rotation,
        team_assignment_exchange=bool(rotation & 1),
        partner_seat_exchange=bool(rotation & 2),
        label="property-transform",
        strength_estimation=True,
    )
    transformed = transform_deal(base, transformation)
    cards = tuple(card for hand in transformed.hands for card in hand)
    assert len(cards) == 52
    assert frozenset(cards) == frozenset(FULL_DECK)

    rebased = type(base).build(
        index=base.index,
        dealer=transformed.dealer,
        hands=transformed.hands,
        starting_score=transformed.starting_score,
    )
    restored = transform_deal(rebased, transformation.inverse())
    assert restored.hands == base.hands
    assert restored.dealer == base.dealer
    assert restored.starting_score == base.starting_score


def test_action_and_suit_transformations_are_explicit_and_invertible() -> None:
    base = generate_base_deal(
        root_seed=4,
        index=0,
        dealer_policy=DealerPolicy.ROUND_ROBIN,
        initial_dealer=0,
        starting_score=MatchScore(),
    )
    suit_transform = diagnostic_suit_permutation(
        (SUIT_ORDER[1], SUIT_ORDER[0], SUIT_ORDER[3], SUIT_ORDER[2]),
        label="red-black-pair-swap",
    )
    assert not suit_transform.strength_estimation
    show = ShowAction(
        seat=1,
        shown_card=base.hands[1][0],
        declared_contract=Contract.NOLO,
    )
    play = PlayCardAction(seat=2, card=base.hands[2][0])
    for action in (show, play):
        assert transform_action(
            transform_action(action, suit_transform), suit_transform.inverse()
        ) == action
    assert transform_deal(base, identity_transformation()).hands == base.hands


def test_four_clockwise_rotations_return_identity() -> None:
    composed = identity_transformation()
    quarter = rotation_transformation(1)
    for index in range(4):
        composed = compose_transformations(
            composed, quarter, label=f"quarter-turn-{index + 1}"
        )
    assert composed.seat_rotation == 0
    assert all(composed.map_seat(seat) == seat for seat in range(4))
