"""Tests for the live, mid-deal training-odds computation."""

from __future__ import annotations

import itertools

import pytest

from tests.exact.conftest import walk_deal
from tuppi_engine import EnginePhase
from tuppi_exact import HardConstraintModel, exact_uniform_marginals
from tuppi_rules import Contract, card_to_code
from tuppi_server.training_analysis import (
    TRAINING_ANALYSIS_SCHEMA_VERSION,
    SUIT_ORDER,
    behavioural_exclusions,
    generate_training_analysis,
)


def _sampled_positions():
    """Real deterministic decision points, spread across several deals.

    Deliberately spans whole deals rather than only the opening tricks: a
    proven void and a publicly shown card both appear part-way through, and
    the invariants below are worth nothing if the fixture never reaches a
    position where they can fail.
    """

    collected = []
    for stream_index in range(3):
        for index, position in enumerate(walk_deal(stream_index=stream_index)):
            if position.deal_state.phase is not EnginePhase.TRICK_PLAY:
                continue
            if index % 3 == 0:
                collected.append(position)
    assert collected
    return collected


@pytest.fixture(scope="module")
def positions():
    return _sampled_positions()


def test_response_has_exactly_the_expected_fields(positions) -> None:
    for position in positions:
        response = generate_training_analysis(position.observation)
        assert set(response) == {
            "schema_version",
            "match_ref",
            "deal_ref",
            "seat",
            "other_seats",
            "suit_splits",
            "card_locations",
            "assumed",
        }
        assert response["schema_version"] == TRAINING_ANALYSIS_SCHEMA_VERSION
        assert response["match_ref"] == position.observation.match_ref
        assert response["deal_ref"] == position.observation.deal_ref
        assert response["seat"] == position.observation.observing_seat
        assert sorted(response["other_seats"]) == [
            seat for seat in range(4) if seat != position.observation.observing_seat
        ]


def test_suit_splits_cover_every_suit_and_sum_to_one(positions) -> None:
    for position in positions:
        response = generate_training_analysis(position.observation)
        assert set(response["suit_splits"]) == {suit.value for suit in SUIT_ORDER}
        for suit_key, split in response["suit_splits"].items():
            total_probability = sum(
                entry["probability"] for entry in split["distribution"]
            )
            assert total_probability == pytest.approx(1.0, abs=1e-9)
            for entry in split["distribution"]:
                assert sum(entry["counts"]) == split["outstanding"]
                assert len(entry["counts"]) == 3
                assert entry["probability"] > 0.0


def test_split_law_and_card_marginals_describe_the_same_position(positions) -> None:
    """The two panels must not contradict each other.

    Expected cards of a suit at a seat can be read two ways: from the split
    distribution, and by summing that suit's per-card ownership frequencies.
    Both come from one constraint model, so they have to agree exactly. An
    earlier implementation derived the split from hand sizes and voids alone
    and drifted by more than a card and a half once a show exclusion applied.
    """

    for position in positions:
        model = HardConstraintModel.build(position.observation)
        other_seats = tuple(
            seat for seat in range(4) if seat != model.observing_seat
        )
        marginals = exact_uniform_marginals(model)
        response = generate_training_analysis(position.observation)
        for suit in SUIT_ORDER:
            split = response["suit_splits"][suit.value]
            if split["outstanding"] == 0:
                continue
            from_split = [
                sum(
                    entry["counts"][index] * entry["probability"]
                    for entry in split["distribution"]
                )
                for index in range(3)
            ]
            from_marginals = [
                sum(
                    float(marginals[card][seat])
                    for card in model.unknown_cards
                    if card.suit is suit
                )
                for seat in other_seats
            ]
            for index in range(3):
                assert from_split[index] == pytest.approx(
                    from_marginals[index], abs=1e-9
                )


def test_known_cards_are_reported_separately_from_the_split(positions) -> None:
    """A publicly shown card is certain, so it stays out of the odds."""

    saw_a_known_card = False
    for position in positions:
        model = HardConstraintModel.build(position.observation)
        other_seats = tuple(
            seat for seat in range(4) if seat != model.observing_seat
        )
        response = generate_training_analysis(position.observation)
        for suit in SUIT_ORDER:
            split = response["suit_splits"][suit.value]
            expected = [
                sum(1 for card in model.known_held[seat] if card.suit is suit)
                for seat in other_seats
            ]
            assert split["known_counts"] == expected
            if any(expected):
                saw_a_known_card = True
            # The split covers only the unknown cards of the suit.
            assert split["outstanding"] == sum(
                1 for card in model.unknown_cards if card.suit is suit
            )
    assert saw_a_known_card, "fixture never exercised a publicly shown card"


def test_suit_split_respects_proven_voids(positions) -> None:
    checked_voids = 0
    for position in positions:
        model = HardConstraintModel.build(position.observation)
        other_seats = tuple(
            seat for seat in range(4) if seat != model.observing_seat
        )
        response = generate_training_analysis(position.observation)
        for suit in SUIT_ORDER:
            split = response["suit_splits"][suit.value]
            for index, seat in enumerate(other_seats):
                if suit not in model.void_suits[seat]:
                    continue
                checked_voids += 1
                assert all(
                    entry["counts"][index] == 0
                    for entry in split["distribution"]
                )
    assert checked_voids, "fixture never reached a proven void"


def test_split_law_agrees_with_exhaustive_enumeration() -> None:
    """Ground-truth the split law against brute force on small positions.

    Enumerating every feasible assignment and tallying the suits directly uses
    none of the counting machinery the implementation is built on, so this is
    an independent check rather than a restatement of it.
    """

    checked = 0
    for stream_index in range(10):
        for position in walk_deal(stream_index=stream_index):
            if position.deal_state.phase is not EnginePhase.TRICK_PLAY:
                continue
            model = HardConstraintModel.build(position.observation)
            if not 2 <= len(model.unknown_cards) <= 9:
                continue
            other_seats = tuple(
                seat for seat in range(4) if seat != model.observing_seat
            )
            response = generate_training_analysis(position.observation)
            for suit in SUIT_ORDER:
                tally, total = _brute_force_split(model, suit, other_seats)
                computed = {
                    tuple(entry["counts"]): entry["probability"]
                    for entry in response["suit_splits"][suit.value]["distribution"]
                }
                assert set(computed) == set(tally)
                for placement, ways in tally.items():
                    assert computed[placement] == pytest.approx(
                        ways / total, abs=1e-12
                    )
                checked += 1
            if checked >= 60:
                return
    assert checked, "no small enumerable position was found"


def _brute_force_split(model, suit, other_seats):
    """Tally suit placements over every feasible assignment, exhaustively."""

    cards = model.unknown_cards
    allowed = [sorted(model.allowed_seat_map[card]) for card in cards]
    capacities = list(model.capacity)
    tally: dict[tuple[int, ...], int] = {}
    total = 0
    for combination in itertools.product(*allowed):
        used = [0, 0, 0, 0]
        for seat in combination:
            used[seat] += 1
        if used != capacities:
            continue
        total += 1
        placement = tuple(
            sum(
                1
                for card, seat in zip(cards, combination)
                if seat == target and card.suit is suit
            )
            for target in other_seats
        )
        tally[placement] = tally.get(placement, 0) + 1
    return tally, total


def test_the_assumed_layer_never_excludes_a_card_a_seat_actually_holds() -> None:
    """The assumption must not delete an opponent's real card.

    A behavioural exclusion is a claim about how somebody chose to play, so
    unlike the hard facts it can simply be wrong — and a wrong one removes the
    true holding from the feasible set, which silently shifts every percentage
    the overlay shows. A companion rule ("a seat taking a trick sheds its
    highest card of the suit") was rejected on exactly this test at 55.5%.
    """

    firings = {Contract.NOLO: 0, Contract.RAMI: 0}
    for stream_index in range(10):
        for position in walk_deal(stream_index=stream_index):
            if position.deal_state.phase is not EnginePhase.TRICK_PLAY:
                continue
            contract = position.deal_state.contract
            exclusions = behavioural_exclusions(position.observation)
            for seat in range(4):
                if not exclusions[seat]:
                    continue
                firings[contract] += 1
                held = set(position.deal_state.hands[seat])
                assert not (exclusions[seat] & held), (
                    f"{contract.value} seat {seat} was assumed not to hold "
                    f"{sorted(card_to_code(c) for c in exclusions[seat] & held)}"
                )
    # Both contracts must be exercised: the rules are opposites, and a NOLO-only
    # fixture would have hidden that they were being applied to RAMI as well.
    assert firings[Contract.NOLO], "no NOLO firings, so this proves nothing"
    assert firings[Contract.RAMI], "no RAMI firings, so this proves nothing"


def test_assumed_layer_is_a_strict_refinement_of_the_hard_facts(positions) -> None:
    """Assuming more can only narrow what is still open, never widen it.

    The assumption can be strong enough to *prove* an owner: once a seat is
    excluded from enough cards, the pigeonhole and Hall propagation inside the
    constraint model can pin one down, moving it out of the unknown set and
    into that seat's known holding. So the unknown count legitimately shrinks;
    what cannot change is the total number of the suit's cards that are
    neither in the player's own hand nor already played.
    """

    compared = 0
    sharpened = 0
    for position in positions:
        response = generate_training_analysis(position.observation)
        assumed = response["assumed"]
        if assumed is None:
            continue
        compared += 1
        for suit in SUIT_ORDER:
            hard = response["suit_splits"][suit.value]
            soft = assumed["suit_splits"][suit.value]
            assert soft["outstanding"] <= hard["outstanding"]
            assert all(
                after >= before
                for after, before in zip(soft["known_counts"], hard["known_counts"])
            )
            assert soft["outstanding"] + sum(soft["known_counts"]) == (
                hard["outstanding"] + sum(hard["known_counts"])
            )
            if soft["outstanding"] < hard["outstanding"]:
                sharpened += 1
            assert sum(e["probability"] for e in soft["distribution"]) == pytest.approx(
                1.0, abs=1e-9
            )
    assert compared, "no position produced an assumed layer"


def test_card_locations_are_exactly_the_unknown_cards(positions) -> None:
    for position in positions:
        model = HardConstraintModel.build(position.observation)
        response = generate_training_analysis(position.observation)
        expected_cards = {card_to_code(card) for card in model.unknown_cards}
        actual_cards = {entry["card"] for entry in response["card_locations"]}
        assert actual_cards == expected_cards


def test_card_location_probabilities_sum_to_one_and_exclude_own_seat(
    positions,
) -> None:
    for position in positions:
        seat = position.observation.observing_seat
        response = generate_training_analysis(position.observation)
        for entry in response["card_locations"]:
            probabilities = entry["seat_probabilities"]
            assert len(probabilities) == 4
            assert sum(probabilities) == pytest.approx(1.0, abs=1e-9)
            assert probabilities[seat] == 0.0


def test_own_hand_and_played_cards_never_appear_in_card_locations(positions) -> None:
    for position in positions:
        observation = position.observation
        response = generate_training_analysis(observation)
        listed = {entry["card"] for entry in response["card_locations"]}
        own_hand_codes = {card_to_code(card) for card in observation.own_hand}
        assert listed.isdisjoint(own_hand_codes)
        played_codes = {
            card_to_code(play.card)
            for trick in observation.completed_tricks
            for play in trick.plays
        } | {card_to_code(play.card) for play in observation.current_trick}
        assert listed.isdisjoint(played_codes)
