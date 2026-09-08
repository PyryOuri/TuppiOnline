"""The differential gate for ``tuppi_engine.trusted``.

``trusted_transitions`` stops the engine from proving that its own successor
states are well-formed, so the elision has to be *shown* not to change play
rather than argued to be safe.  That is what
``test_trusted_play_is_byte_identical`` is: the same streams played through both
paths, comparing every selected action in order plus each match's final score
and deal count.

The second thing these tests pin is the boundary.  Four implicit revalidations
are elided and nothing else, so a malformed explicit deal, an explicit
validation request, and a genuinely wrong argument all still raise inside a
trusted block.  ``test_a_corrupted_internal_state_is_not_caught`` records the
price of that trade honestly rather than leaving it to the docstring.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from tuppi_agents.improved_registry import improved_agents_for_seats
from tuppi_engine import (
    EnginePhase,
    ExplicitDeal,
    MatchState,
    apply_match_action,
    begin_explicit_deal,
    create_match,
    match_observation_for,
    validate_match_state,
)
from tuppi_engine.errors import StateInvariantError
from tuppi_engine.serialization import action_to_data, observation_to_data
from tuppi_engine.state import validate_deal_state
from tuppi_engine.trusted import is_trusted, trusted_transitions
from tuppi_match.streams import MatchStream
from tuppi_rules import MatchScore


REFERENCE = "partner_aware_lead_v2"


def _play(streams: int, deals: int) -> tuple[list[object], list[object]]:
    """Every action in order, and every observation, for one fixed workload."""

    actions: list[object] = []
    observations: list[object] = []
    for index in range(streams):
        stream = MatchStream.build(
            root_seed="trusted-gate-v1",
            stream_index=index,
            initial_dealer=index % 4,
        )
        table = improved_agents_for_seats(REFERENCE)
        state = create_match(
            initial_score=MatchScore(0, 0),
            initial_dealer=stream.initial_dealer,
            match_ref=f"trusted-{index:06d}",
        )
        deal_index = 0
        while not state.terminal and deal_index < deals:
            if state.phase in (EnginePhase.AWAITING_DEAL, EnginePhase.DEAL_COMPLETE):
                state = begin_explicit_deal(
                    state, stream.deal(deal_index).explicit_deal(state.dealer)
                )
                deal_index += 1
                continue
            actor = state.current_actor
            observation = match_observation_for(state, actor)
            observations.append(observation_to_data(observation))
            action = table[actor].choose_action(observation)
            actions.append((index, actor, action_to_data(action)))
            state = apply_match_action(state, action)
        actions.append(
            (index, "final", (state.score.team0, state.score.team1, deal_index))
        )
    return actions, observations


def _reached_trick_play() -> MatchState:
    stream = MatchStream.build(
        root_seed="trusted-gate-v1", stream_index=0, initial_dealer=0
    )
    table = improved_agents_for_seats(REFERENCE)
    state = create_match(
        initial_score=MatchScore(0, 0), initial_dealer=0, match_ref="trusted-000000"
    )
    state = begin_explicit_deal(state, stream.deal(0).explicit_deal(state.dealer))
    while state.phase is EnginePhase.SHOWING:
        actor = state.current_actor
        state = apply_match_action(
            state, table[actor].choose_action(match_observation_for(state, actor))
        )
    assert state.phase is EnginePhase.TRICK_PLAY
    return state


# ------------------------------------------------------------------ the gate


def test_trusted_play_is_byte_identical() -> None:
    authoritative_actions, authoritative_observations = _play(streams=3, deals=4)
    with trusted_transitions():
        trusted_actions, trusted_observations = _play(streams=3, deals=4)

    assert authoritative_actions == trusted_actions
    assert authoritative_observations == trusted_observations

    # A workload that never left the showing phase, or that compared two empty
    # traces, would pass the equalities above vacuously.
    kinds = [
        entry[2]["type"]
        for entry in authoritative_actions
        if isinstance(entry[2], dict)
    ]
    assert kinds.count("play") >= 300
    assert kinds.count("show") >= 3
    assert len(authoritative_observations) == len(kinds)


# ---------------------------------------------------------------- the scope


def test_the_mode_is_off_by_default_and_restores() -> None:
    assert not is_trusted()
    with trusted_transitions():
        assert is_trusted()
        with trusted_transitions():
            assert is_trusted()
        assert is_trusted(), "an inner block must not clear the outer one"
    assert not is_trusted()


def test_the_mode_restores_on_exception() -> None:
    with pytest.raises(RuntimeError):
        with trusted_transitions():
            assert is_trusted()
            raise RuntimeError("boom")
    assert not is_trusted()


def test_beginning_a_deal_still_validates_external_data() -> None:
    """``begin_explicit_deal`` accepts external data and is never elided."""

    stream = MatchStream.build(
        root_seed="trusted-gate-v1", stream_index=0, initial_dealer=0
    )
    state = create_match(
        initial_score=MatchScore(0, 0), initial_dealer=0, match_ref="trusted-000000"
    )
    good = stream.deal(0).explicit_deal(state.dealer)
    # A hand that duplicates a card between two seats is malformed input.
    broken_hands = (good.hands[0], good.hands[0], good.hands[2], good.hands[3])
    with trusted_transitions():
        with pytest.raises(Exception):
            begin_explicit_deal(
                state, ExplicitDeal(dealer=good.dealer, hands=broken_hands)
            )


def test_explicit_validation_is_honoured_inside_a_trusted_block() -> None:
    """The in-run revalidation sample depends on this exact property."""

    state = _reached_trick_play()
    with trusted_transitions():
        assert validate_match_state(state) is state
        assert validate_deal_state(state.active_deal) is state.active_deal

        corrupted = replace(state.active_deal, forehand=(state.active_deal.forehand + 1) % 4)
        with pytest.raises(StateInvariantError):
            validate_deal_state(corrupted)


def test_a_wrong_argument_still_raises_in_a_trusted_block() -> None:
    with trusted_transitions():
        with pytest.raises(StateInvariantError):
            apply_match_action("not a match state", None)  # type: ignore[arg-type]
        with pytest.raises(StateInvariantError):
            match_observation_for(object(), 0)  # type: ignore[arg-type]


def test_a_corrupted_internal_state_is_not_caught() -> None:
    """The documented price of the elision, pinned rather than described.

    Outside a trusted block an inconsistent successor cannot be constructed at
    all.  Inside one it can, and only an explicit validation finds it - which is
    why a trusted generator owes the caller a differential gate and a
    revalidation sample.
    """

    deal = _reached_trick_play().active_deal
    with pytest.raises(StateInvariantError):
        replace(deal, forehand=(deal.forehand + 1) % 4)

    with trusted_transitions():
        corrupted = replace(deal, forehand=(deal.forehand + 1) % 4)
        assert corrupted.forehand != deal.forehand
    with pytest.raises(StateInvariantError):
        validate_deal_state(corrupted)


def test_the_mode_does_not_leak_out_of_the_block() -> None:
    deal = _reached_trick_play().active_deal
    with trusted_transitions():
        pass
    with pytest.raises(StateInvariantError):
        replace(deal, forehand=(deal.forehand + 1) % 4)
