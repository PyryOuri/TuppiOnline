"""Exact counting and exactly uniform sampling, checked against enumeration."""

from __future__ import annotations

from collections import Counter
from fractions import Fraction
from itertools import combinations
import math

import pytest

from tuppi_engine import EnginePhase
from tuppi_exact.constraints import HardConstraintModel
from tuppi_exact.counting import (
    ClassAllocation,
    CountingPlan,
    assignments_with_card_at_seat,
    bounded_compositions,
    count_plan,
    count_summary,
    exact_ownership_counts,
    exact_uniform_marginals,
    feasible_assignment_count,
    multinomial,
)
from tuppi_exact.errors import CountingError, SamplingError
from tuppi_exact.sampling import (
    DeterministicBitSource,
    UniformFeasibleSampler,
    sample_assignments,
    uniform_sampling_summary,
)

from .conftest import walk_deal


def enumerate_assignments(model: HardConstraintModel) -> list[tuple[frozenset, ...]]:
    """Brute-force every feasible assignment; only for small models."""

    seats = model.unknown_seats
    cards = list(model.unknown_cards)

    results: list[tuple[frozenset, ...]] = []

    def recurse(index: int, remaining: dict[int, int], chosen: dict[int, list]):
        if index == len(cards):
            if all(value == 0 for value in remaining.values()):
                results.append(
                    tuple(frozenset(chosen.get(seat, ())) for seat in range(4))
                )
            return
        card = cards[index]
        for seat in sorted(model.allowed_seats(card)):
            if remaining.get(seat, 0) <= 0:
                continue
            remaining[seat] -= 1
            chosen.setdefault(seat, []).append(card)
            recurse(index + 1, remaining, chosen)
            chosen[seat].pop()
            remaining[seat] += 1

    recurse(0, {seat: model.capacity[seat] for seat in seats}, {})
    return results


def test_bounded_compositions_enumerates_exactly():
    assert set(bounded_compositions(3, (2, 2))) == {(1, 2), (2, 1)}
    assert list(bounded_compositions(0, ())) == [()]
    assert list(bounded_compositions(1, ())) == []
    assert set(bounded_compositions(2, (1, 1, 1))) == {(0, 1, 1), (1, 0, 1), (1, 1, 0)}


def test_multinomial_matches_factorials():
    assert multinomial(6, (2, 2, 2)) == math.factorial(6) // (2 * 2 * 2)
    assert multinomial(4, (4,)) == 1
    with pytest.raises(CountingError):
        multinomial(4, (1, 1))


def test_a_hand_worked_example_counts_by_hand():
    """Two classes, three seats: 6 * 3 + 4 * 3 = 30, verified arithmetically."""

    from tuppi_rules import card_from_code

    plan = CountingPlan(
        seat_order=(0, 1, 3),
        capacities=(3, 2, 2),
        classes=(
            ClassAllocation(
                allowed_seats=(0, 1),
                cards=tuple(card_from_code(code) for code in ("2H", "3H", "4H", "5H")),
            ),
            ClassAllocation(
                allowed_seats=(0, 1, 3),
                cards=tuple(card_from_code(code) for code in ("2D", "3D", "4D")),
            ),
        ),
    )
    assert count_plan(plan) == 30


def test_count_agrees_with_enumeration(small_model_position):
    model = HardConstraintModel.build(small_model_position.observation)
    enumerated = enumerate_assignments(model)
    assert feasible_assignment_count(model) == len(enumerated)
    assert len({item for item in enumerated}) == len(enumerated)


def test_marginals_sum_to_the_total_at_every_decision():
    for stream_index in range(3):
        for position in walk_deal(stream_index=stream_index):
            model = HardConstraintModel.build(position.observation)
            total = feasible_assignment_count(model)
            assert total >= 1
            for card, counts in exact_ownership_counts(model).items():
                assert sum(counts) == total
                assert all(
                    counts[seat] == 0
                    for seat in range(4)
                    if seat not in model.allowed_seats(card)
                )


def test_marginals_are_exact_rationals(small_model_position):
    model = HardConstraintModel.build(small_model_position.observation)
    marginals = exact_uniform_marginals(model)
    for card, values in marginals.items():
        assert all(isinstance(value, Fraction) for value in values)
        assert sum(values) == Fraction(1)
        del card


def test_marginals_agree_with_enumeration(small_model_position):
    model = HardConstraintModel.build(small_model_position.observation)
    enumerated = enumerate_assignments(model)
    total = len(enumerated)
    for card in model.unknown_cards:
        for seat in range(4):
            expected = sum(1 for item in enumerated if card in item[seat])
            assert assignments_with_card_at_seat(model, card, seat) == expected
        del seat
    assert feasible_assignment_count(model) == total


def test_the_truth_is_always_a_feasible_assignment():
    for stream_index in range(3):
        for position in walk_deal(stream_index=stream_index):
            model = HardConstraintModel.build(position.observation)
            for card in model.unknown_cards:
                truth = next(
                    seat
                    for seat, hand in enumerate(position.true_hands)
                    if card in hand
                )
                assert assignments_with_card_at_seat(model, card, truth) > 0


def test_count_summary_is_canonical(small_model_position):
    model = HardConstraintModel.build(small_model_position.observation)
    summary = count_summary(model)
    assert summary["schema_version"] == "tuppi.exact.feasible_assignment_count.v1"
    assert summary["structurally_feasible"] is True
    assert summary["unknown_card_count"] == len(model.unknown_cards)
    assert summary["feasible_assignment_count"] == feasible_assignment_count(model)


# ------------------------------------------------------------------- sampling


def test_bit_source_is_exactly_uniform_and_unbiased():
    source = DeterministicBitSource("uniformity")
    counts = Counter(source.below(3) for _ in range(30000))
    assert set(counts) == {0, 1, 2}
    for value in counts.values():
        assert abs(value - 10000) < 500
    assert source.below(1) == 0


def test_bit_source_is_reproducible():
    left = DeterministicBitSource("same")
    right = DeterministicBitSource("same")
    assert [left.below(1000) for _ in range(50)] == [
        right.below(1000) for _ in range(50)
    ]
    other = DeterministicBitSource("different")
    assert [left.below(1000) for _ in range(20)] != [
        other.below(1000) for _ in range(20)
    ]


def test_bit_source_rejects_a_nonpositive_bound():
    source = DeterministicBitSource("guard")
    with pytest.raises(SamplingError):
        source.below(0)


def test_every_sample_satisfies_the_hard_constraints():
    for stream_index in range(3):
        for position in walk_deal(stream_index=stream_index):
            model = HardConstraintModel.build(position.observation)
            if not model.unknown_cards:
                continue
            sampler = UniformFeasibleSampler.build(model, seed="constraint-check")
            for assignment in sampler.sample(6):
                for card, seat in assignment.sampled_owner.items():
                    assert seat in model.allowed_seats(card)
                assert sum(len(hand) for hand in assignment.hands) == sum(
                    model.cards_remaining
                )
                assert set(assignment.hands[model.observing_seat]) == set(
                    position.observation.own_hand
                )


def test_sampling_covers_every_feasible_assignment_uniformly(small_model_position):
    model = HardConstraintModel.build(small_model_position.observation)
    total = feasible_assignment_count(model)
    assert 2 <= total <= 2000
    sampler = UniformFeasibleSampler.build(model, seed="uniformity-test")
    draws = sampler.sample(200 * total)
    tally = Counter(item.content_key() for item in draws)
    assert len(tally) == total, "every feasible assignment must be reachable"
    chi_square = sum((value - 200) ** 2 / 200 for value in tally.values())
    # A uniform sampler has expectation total-1; a factor of three is a very
    # loose bound that a biased sampler would still fail.
    assert chi_square < 3 * total


def test_sampling_is_reproducible_and_seed_sensitive(small_model_position):
    model = HardConstraintModel.build(small_model_position.observation)
    first = UniformFeasibleSampler.build(model, seed="alpha").sample(20)
    again = UniformFeasibleSampler.build(model, seed="alpha").sample(20)
    other = UniformFeasibleSampler.build(model, seed="beta").sample(20)
    assert [item.content_key() for item in first] == [
        item.content_key() for item in again
    ]
    assert [item.content_key() for item in first] != [
        item.content_key() for item in other
    ]


def test_sample_prefix_is_stable(small_model_position):
    model = HardConstraintModel.build(small_model_position.observation)
    sampler = UniformFeasibleSampler.build(model, seed="prefix")
    long = sampler.sample(12)
    short = sampler.sample(5)
    assert [item.content_key() for item in long[:5]] == [
        item.content_key() for item in short
    ]
    assert sampler.sample_one(index=3).content_key() == long[3].content_key()


def test_sampler_provenance_states_it_is_not_a_posterior(small_model_position):
    model = HardConstraintModel.build(small_model_position.observation)
    provenance = UniformFeasibleSampler.build(model, seed="p").provenance()
    assert provenance["is_posterior_over_opponent_hands"] is False
    assert provenance["distribution"] == "uniform_over_feasible_assignments"
    assert "posterior" in provenance["posterior_caveat"]


def test_sampling_summary_and_convenience_entry_point(small_model_position):
    observation = small_model_position.observation
    summary = uniform_sampling_summary(observation, seed="cli", count=5)
    assert summary["requested_count"] == 5
    assert summary["distinct_assignments_drawn"] >= 1
    drawn = sample_assignments(observation, seed="cli", count=5)
    assert len(drawn) == 5


def test_sampling_rejects_bad_arguments(small_model_position):
    model = HardConstraintModel.build(small_model_position.observation)
    with pytest.raises(SamplingError):
        UniformFeasibleSampler.build(model, seed="")
    sampler = UniformFeasibleSampler.build(model, seed="ok")
    with pytest.raises(SamplingError):
        sampler.sample(0)
    with pytest.raises(SamplingError):
        sampler.sample_one(index=-1)


def test_a_fully_determined_position_has_exactly_one_assignment():
    """The last trick leaves nothing unknown, so the count must be one."""

    seen = False
    for position in walk_deal():
        if position.deal_state.phase is not EnginePhase.TRICK_PLAY:
            continue
        model = HardConstraintModel.build(position.observation)
        if not model.unknown_cards:
            assert feasible_assignment_count(model) == 1
            seen = True
    assert seen


def test_unranking_is_a_bijection_over_combinations():
    from tuppi_exact.sampling import _unrank_combination

    items = list(range(6))
    for size in range(len(items) + 1):
        total = math.comb(len(items), size)
        produced = {
            _unrank_combination(list(items), size, rank) for rank in range(total)
        }
        assert produced == {tuple(item) for item in combinations(items, size)}
    with pytest.raises(SamplingError):
        _unrank_combination(list(items), 2, math.comb(6, 2))
