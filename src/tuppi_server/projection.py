"""The only permitted route from authoritative match state to wire data."""

from __future__ import annotations

from collections.abc import Iterable

from tuppi_engine import (
    MatchState,
    event_to_data,
    match_observation_for,
    match_result_from_state,
    match_result_to_data,
    observation_to_data,
)


def project_observation(state: MatchState, *, seat: int) -> dict[str, object]:
    """Return only the observation authorized for ``seat``."""

    observation = match_observation_for(state, seat)
    return observation_to_data(observation)


def project_event_batch(
    events: Iterable[object], *, after_event_index: int = -1
) -> list[dict[str, object]]:
    """Serialize public events after a client's last applied cursor."""

    if type(after_event_index) is not int:
        raise ValueError("after_event_index must be an integer")
    return [
        event_to_data(event)
        for event in events
        if event.event_index > after_event_index
    ]


def project_match_result(state: MatchState) -> dict[str, object]:
    """Serialize a terminal public result without exposing research state."""

    return match_result_to_data(match_result_from_state(state))
