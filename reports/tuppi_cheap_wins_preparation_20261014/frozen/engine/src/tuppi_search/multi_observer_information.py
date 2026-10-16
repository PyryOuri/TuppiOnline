"""Canonical per-seat information states for Phase 5E.

The payload intentionally reuses the audited Phase 5D-B observation projection.
The only additions are the Phase 5E namespace and the physical observer seat;
no sampled or parent-world field is admitted.
"""

from __future__ import annotations

from tuppi_engine import PlayerObservation
from tuppi_eval.serialization import content_digest

from .information_state import root_information_state_data


MULTI_OBSERVER_INFORMATION_STATE_SCHEMA_VERSION = (
    "tuppi.search.multi_observer_information_state.v1"
)


def multi_observer_information_state_data(
    observation: PlayerObservation,
) -> dict[str, object]:
    if not isinstance(observation, PlayerObservation):
        raise TypeError("multi_observer_information_state_data requires an observation")
    return {
        "observer_seat": observation.observing_seat,
        "observation": root_information_state_data(observation),
        "schema_version": MULTI_OBSERVER_INFORMATION_STATE_SCHEMA_VERSION,
    }


def multi_observer_information_state_key(observation: PlayerObservation) -> str:
    return "mois:" + content_digest(multi_observer_information_state_data(observation))
