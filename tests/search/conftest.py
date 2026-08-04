"""Shared fixtures for the Phase 5C search suite.

PIMC is expensive: a single four-world decision costs about 1.3 s. Every fixture
here is therefore built for the *cheapest configuration that still exercises the
real path* - two worlds, real sampling, real rollouts, real aggregation - and the
session-scoped ones are reused rather than recomputed.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from tuppi_agents import construct_agent, phase4_specifications_by_profile_key
from tuppi_engine import (
    DealState,
    EnginePhase,
    ExplicitDeal,
    PlayerObservation,
    apply_action,
    begin_explicit_deal,
    create_match,
    observation_for,
)
from tuppi_match.streams import MatchStream
from tuppi_rules import MatchScore

from tuppi_search.config import PimcConfiguration
from tuppi_search.utilities import UtilityId


TEST_ROOT_SEED = "tuppi-phase5c-tests-v1"
REFERENCE_POLICY = "partner_aware_v1"


@dataclass(frozen=True, slots=True)
class Position:
    """One reproducible decision point plus the private state behind it."""

    deal_state: DealState
    observation: PlayerObservation
    true_hands: tuple

    @property
    def tricks_remaining(self) -> int:
        return 13 - len(self.deal_state.completed_tricks)

    @property
    def legal_action_count(self) -> int:
        return len(self.observation.legal_actions)


def walk_deal(
    *,
    stream_index: int = 0,
    deal_index: int = 0,
    score: tuple[int, int] = (0, 0),
    profile_key: str = REFERENCE_POLICY,
    root_seed: str = TEST_ROOT_SEED,
):
    """Yield every decision point of one deterministic deal."""

    specification = phase4_specifications_by_profile_key()[profile_key]
    stream = MatchStream.build(
        root_seed=root_seed, stream_index=stream_index, initial_dealer=0
    )
    deal = stream.deal(deal_index)
    state = create_match(
        initial_score=MatchScore(*score),
        initial_dealer=0,
        match_ref=f"stest-{stream_index}-{deal_index}",
    )
    state = begin_explicit_deal(state, ExplicitDeal(dealer=0, hands=deal.hands))
    active = state.active_deal
    while not active.complete:
        actor = active.current_actor
        observation = observation_for(active, actor)
        yield Position(
            deal_state=active, observation=observation, true_hands=deal.hands
        )
        active = apply_action(
            active,
            construct_agent(specification, seat=actor).choose_action(observation),
        )


def advance_to(
    *,
    tricks: int,
    stream_index: int = 0,
    score: tuple[int, int] = (0, 0),
    minimum_legal_actions: int = 2,
) -> Position:
    """Return the first position at or after ``tricks`` with a real choice."""

    for position in walk_deal(stream_index=stream_index, score=score):
        if position.deal_state.phase is not EnginePhase.TRICK_PLAY:
            continue
        if len(position.deal_state.completed_tricks) < tricks:
            continue
        if position.legal_action_count < minimum_legal_actions:
            continue
        return position
    raise AssertionError(f"no position found at or after trick {tricks}")


@pytest.fixture(scope="session")
def smoke_config() -> PimcConfiguration:
    """Two worlds: the cheapest configuration that exercises the whole path."""

    return PimcConfiguration.build(world_count=2)


@pytest.fixture(scope="session")
def tail_config() -> PimcConfiguration:
    return PimcConfiguration.build(
        world_count=2, exact_tail_enabled=True, exact_tail_max_tricks_remaining=4
    )


@pytest.fixture(scope="session")
def deal_utility_config() -> PimcConfiguration:
    return PimcConfiguration.build(
        world_count=2, utility_id=UtilityId.DEAL_RESULT_V1
    )


@pytest.fixture(scope="session")
def showing_position() -> Position:
    """The first showing decision of a fixed deal."""

    for position in walk_deal():
        if position.deal_state.phase is EnginePhase.SHOWING:
            return position
    raise AssertionError("no showing position was reached")


@pytest.fixture(scope="session")
def late_position() -> Position:
    """A trick-play position with a genuine choice, late enough for the tail."""

    return advance_to(tricks=9)


@pytest.fixture(scope="session")
def mid_position() -> Position:
    """A trick-play position in the middle of a deal."""

    return advance_to(tricks=4)


@pytest.fixture(scope="session")
def forced_position() -> Position:
    """A trick-play position with exactly one legal action."""

    for position in walk_deal():
        if (
            position.deal_state.phase is EnginePhase.TRICK_PLAY
            and position.legal_action_count == 1
        ):
            return position
    raise AssertionError("no forced position was reached")


@pytest.fixture(scope="session")
def positions_by_seat() -> dict[int, Position]:
    """One trick-play position per acting seat, for orientation tests."""

    found: dict[int, Position] = {}
    for stream_index in range(6):
        for position in walk_deal(stream_index=stream_index):
            if position.deal_state.phase is not EnginePhase.TRICK_PLAY:
                continue
            if position.legal_action_count < 2:
                continue
            seat = position.observation.observing_seat
            found.setdefault(seat, position)
        if len(found) == 4:
            break
    assert set(found) == {0, 1, 2, 3}, f"only reached seats {sorted(found)}"
    return found
