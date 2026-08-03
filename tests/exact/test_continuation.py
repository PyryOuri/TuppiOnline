"""Hypothetical continuations must be real engine states, and never mistakable.

The load-bearing property tested here is that the *engine* rejects an unsound
assignment. If it did not, an unsound constraint model would produce
plausible-looking hypotheticals and every downstream number would be quietly
wrong.
"""

from __future__ import annotations

import pytest

from tuppi_engine import EnginePhase
from tuppi_engine.errors import EngineError
from tuppi_exact.constraints import HardConstraintModel
from tuppi_exact.continuation import (
    HYPOTHETICAL_MATCH_REF_PREFIX,
    HypotheticalContinuation,
    continuations_for,
    hypothetical_continuation,
    reconstruct_initial_hands,
)
from tuppi_exact.errors import ContinuationError
from tuppi_exact.sampling import HiddenHandAssignment, UniformFeasibleSampler
from tuppi_rules import card_to_index

from .conftest import walk_deal


def _swap(assignment, card_a, seat_a, card_b, seat_b):
    hands = [list(hand) for hand in assignment.hands]
    hands[seat_a].remove(card_a)
    hands[seat_a].append(card_b)
    hands[seat_b].remove(card_b)
    hands[seat_b].append(card_a)
    owner = dict(assignment.sampled_owner)
    owner[card_a] = seat_b
    owner[card_b] = seat_a
    return HiddenHandAssignment(
        observing_seat=assignment.observing_seat,
        hands=tuple(tuple(sorted(hand, key=card_to_index)) for hand in hands),
        sampled_owner=owner,
        sample_index=0,
    )


def test_continuations_land_on_the_same_decision_point():
    built = 0
    for stream_index in range(3):
        for position in walk_deal(stream_index=stream_index):
            model = HardConstraintModel.build(position.observation)
            if not model.unknown_cards:
                continue
            sampler = UniformFeasibleSampler.build(model, seed=f"c{stream_index}")
            for continuation in continuations_for(
                position.observation, sampler.sample(3)
            ):
                state = continuation.state
                observation = position.observation
                assert state.phase is observation.phase
                assert state.current_actor == observation.current_actor
                assert len(state.completed_tricks) == len(observation.completed_tricks)
                assert state.current_trick == observation.current_trick
                assert state.team_tricks == observation.team_tricks
                assert state.contract is observation.contract
                assert state.declarer == observation.declarer
                assert state.starting_score == observation.match_score
                assert set(state.hands[observation.observing_seat]) == set(
                    observation.own_hand
                )
                built += 1
    assert built > 50


def test_continuations_are_labelled_as_hypothetical():
    for position in walk_deal():
        model = HardConstraintModel.build(position.observation)
        if not model.unknown_cards:
            continue
        sampler = UniformFeasibleSampler.build(model, seed="label")
        continuation = hypothetical_continuation(
            position.observation, sampler.sample_one()
        )
        assert continuation.is_hypothetical is True
        assert continuation.visibility == "research_private_hypothetical"
        assert continuation.state.match_ref.startswith(HYPOTHETICAL_MATCH_REF_PREFIX)
        assert continuation.state.match_ref != position.observation.match_ref
        provenance = continuation.provenance()
        assert provenance["is_hypothetical"] is True
        assert "must never" in provenance["usage_rule"]
        assert provenance["source_deal_ref"] == position.observation.deal_ref
        return
    raise AssertionError("no position with unknown cards was reached")


def test_reconstructed_initial_hands_partition_the_deck():
    for position in walk_deal():
        model = HardConstraintModel.build(position.observation)
        if not model.unknown_cards:
            continue
        sampler = UniformFeasibleSampler.build(model, seed="deck")
        hands = reconstruct_initial_hands(
            position.observation, sampler.sample_one()
        )
        assert len(hands) == 4
        assert all(len(hand) == 13 for hand in hands)
        flat = [card for hand in hands for card in hand]
        assert len(set(flat)) == 52


def test_the_true_assignment_reproduces_the_real_hands():
    """Feeding the truth back in must rebuild the same hands, seat by seat."""

    checked = 0
    for position in walk_deal():
        observation = position.observation
        if observation.phase is not EnginePhase.TRICK_PLAY:
            continue
        truth = HiddenHandAssignment(
            observing_seat=observation.observing_seat,
            hands=tuple(
                tuple(sorted(hand, key=card_to_index))
                for hand in position.deal_state.hands
            ),
            sampled_owner={},
            sample_index=0,
        )
        continuation = hypothetical_continuation(observation, truth)
        for seat in range(4):
            assert set(continuation.state.hands[seat]) == set(
                position.deal_state.hands[seat]
            )
        # The observing seat's order is known and preserved exactly, so its
        # legal-action order - and therefore Phase 4's tie-break - is unchanged.
        assert tuple(
            continuation.state.hands[observation.observing_seat]
        ) == tuple(observation.own_hand)
        checked += 1
    assert checked > 20


def test_a_hypothetical_cannot_reproduce_the_real_deal_identity():
    """Opponent hand order is not public, so the deal_id must differ.

    That is deliberate. A hypothetical whose ``deal_id`` matched a dealt deal
    could be filed as one; a hypothetical whose identity always differs cannot.
    """

    checked = 0
    for position in walk_deal():
        observation = position.observation
        if observation.phase is not EnginePhase.TRICK_PLAY:
            continue
        truth = HiddenHandAssignment(
            observing_seat=observation.observing_seat,
            hands=tuple(
                tuple(sorted(hand, key=card_to_index))
                for hand in position.deal_state.hands
            ),
            sampled_owner={},
            sample_index=0,
        )
        continuation = hypothetical_continuation(observation, truth)
        assert continuation.state.deal_ref != position.deal_state.deal_ref
        checked += 1
    assert checked > 20


def test_a_void_violating_assignment_is_rejected_by_the_engine():
    for stream_index in range(60):
        for position in walk_deal(stream_index=stream_index):
            model = HardConstraintModel.build(position.observation)
            if not model.unknown_cards:
                continue
            sampler = UniformFeasibleSampler.build(model, seed="void")
            good = sampler.sample_one()
            for seat in range(4):
                if seat == model.observing_seat or not model.void_suits[seat]:
                    continue
                suit = sorted(model.void_suits[seat], key=lambda item: item.value)[0]
                donors = [
                    (card, other)
                    for other in range(4)
                    if other != seat
                    for card in good.hands[other]
                    if card.suit is suit
                ]
                keeps = list(good.hands[seat])
                if not donors or not keeps:
                    continue
                bad_card, donor = donors[0]
                forged = _swap(good, keeps[0], seat, bad_card, donor)
                with pytest.raises((ContinuationError, EngineError)):
                    hypothetical_continuation(position.observation, forged)
                return
    raise AssertionError("no position with a proven void was reached")


def test_a_show_violating_assignment_is_rejected_by_the_engine():
    """The show-derived exclusion is necessary, not decorative."""

    for stream_index in range(60):
        for position in walk_deal(stream_index=stream_index):
            model = HardConstraintModel.build(position.observation)
            if not model.unknown_cards:
                continue
            sampler = UniformFeasibleSampler.build(model, seed="show")
            good = sampler.sample_one()
            for seat in range(4):
                if seat == model.observing_seat or not model.show_exclusions[seat]:
                    continue
                donors = [
                    (card, other)
                    for other in range(4)
                    if other != seat
                    for card in good.hands[other]
                    if card in model.show_exclusions[seat]
                ]
                keeps = [
                    card
                    for card in good.hands[seat]
                    if card not in model.show_exclusions[seat]
                ]
                if not donors or not keeps:
                    continue
                bad_card, donor = donors[0]
                forged = _swap(good, keeps[0], seat, bad_card, donor)
                with pytest.raises((ContinuationError, EngineError)):
                    hypothetical_continuation(position.observation, forged)
                return
    raise AssertionError("no position with a show-derived exclusion was reached")


def test_continuation_rejects_a_mismatched_seat():
    positions = [
        item
        for item in walk_deal()
        if HardConstraintModel.build(item.observation).unknown_cards
    ]
    first, second = positions[0], positions[1]
    assert first.observation.observing_seat != second.observation.observing_seat
    sampler = UniformFeasibleSampler.build(
        HardConstraintModel.build(first.observation), seed="mismatch"
    )
    with pytest.raises(ContinuationError):
        reconstruct_initial_hands(second.observation, sampler.sample_one())


def test_continuation_rejects_a_non_hypothetical_match_ref():
    for position in walk_deal():
        model = HardConstraintModel.build(position.observation)
        if not model.unknown_cards:
            continue
        sampler = UniformFeasibleSampler.build(model, seed="ref")
        with pytest.raises(ContinuationError):
            hypothetical_continuation(
                position.observation, sampler.sample_one(), match_ref="looks-real"
            )
        return


def test_continuation_wrapper_validates_its_own_input():
    with pytest.raises(ContinuationError):
        HypotheticalContinuation(
            state="not a state",  # type: ignore[arg-type]
            observing_seat=0,
            source_match_ref="m",
            source_deal_ref="m/deal:0",
            sample_index=0,
        )
    with pytest.raises(ContinuationError):
        continuations_for(next(iter(walk_deal())).observation, ())
