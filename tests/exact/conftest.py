"""Shared deterministic fixtures for the Phase 5B exact layer."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from tuppi_agents import construct_agent, phase4_specifications_by_profile_key
from tuppi_engine import (
    DealState,
    EnginePhase,
    ExplicitDeal,
    PlayerObservation,
    apply_match_action,
    begin_explicit_deal,
    create_match,
    match_observation_for,
)
from tuppi_match.streams import MatchStream
from tuppi_rules import MatchScore


@dataclass(frozen=True, slots=True)
class Position:
    """One reproducible decision point plus the private state behind it."""

    deal_state: DealState
    observation: PlayerObservation
    true_hands: tuple[tuple, ...]

    @property
    def tricks_remaining(self) -> int:
        return 13 - len(self.deal_state.completed_tricks)


def walk_deal(
    *,
    profile_key: str = "partner_aware_v1",
    root_seed: str = "tuppi-exact-tests-v1",
    stream_index: int = 0,
    deal_index: int = 0,
    score: tuple[int, int] = (0, 0),
):
    """Yield every decision point of one deterministic deal, with private state.

    The same agent occupies all four seats so the trajectory is reproducible from
    the profile key alone.
    """

    specification = phase4_specifications_by_profile_key()[profile_key]
    stream = MatchStream.build(
        root_seed=root_seed, stream_index=stream_index, initial_dealer=0
    )
    deal = stream.deal(deal_index)
    state = create_match(
        initial_score=MatchScore(*score),
        initial_dealer=0,
        match_ref=f"exacttest-{stream_index}-{deal_index}",
    )
    state = begin_explicit_deal(state, ExplicitDeal(dealer=0, hands=deal.hands))
    agents = tuple(construct_agent(specification, seat=seat) for seat in range(4))
    while state.phase in (EnginePhase.SHOWING, EnginePhase.TRICK_PLAY):
        actor = state.current_actor
        assert actor is not None
        observation = match_observation_for(state, actor)
        active = state.active_deal
        assert active is not None
        yield Position(
            deal_state=active, observation=observation, true_hands=deal.hands
        )
        state = apply_match_action(state, agents[actor].choose_action(observation))


@pytest.fixture(scope="session")
def deal_positions() -> tuple[Position, ...]:
    """Every decision point of one fixed deal."""

    return tuple(walk_deal())


@pytest.fixture(scope="session")
def late_positions() -> tuple[Position, ...]:
    """Trick-play positions with at most four tricks left, from several deals."""

    collected: list[Position] = []
    for stream_index in range(4):
        for position in walk_deal(stream_index=stream_index):
            if (
                position.deal_state.phase is EnginePhase.TRICK_PLAY
                and position.tricks_remaining <= 4
            ):
                collected.append(position)
    assert collected
    return tuple(collected)


@pytest.fixture(scope="session")
def small_model_position() -> Position:
    """A position whose feasible-assignment count is small enough to enumerate."""

    from tuppi_exact.constraints import HardConstraintModel
    from tuppi_exact.counting import feasible_assignment_count

    for stream_index in range(8):
        for position in walk_deal(stream_index=stream_index):
            if position.deal_state.phase is not EnginePhase.TRICK_PLAY:
                continue
            model = HardConstraintModel.build(position.observation)
            if 2 <= len(model.unknown_cards) <= 7 and (
                2 <= feasible_assignment_count(model) <= 2000
            ):
                return position
    raise AssertionError("no small enumerable position was found")
